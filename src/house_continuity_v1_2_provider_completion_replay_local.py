"""Synthetic private provider-completion replay owner for Gates 4/5 closure.

This local-only owner is intentionally separate from the raw-free capability
and outbox database. It retains one bounded exact terminal response so parsing
and durable preparation can resume after a crash without another provider
call. It is not imported by a standing-live route.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from house_continuity_v1_2_capability_terminal_parser_local import (
    HouseContinuityTerminalParserLocal,
)
from house_continuity_v1_2_durable_preparation_outbox_local import (
    DurablePreparationOutboxLocalError,
    HouseContinuityDurablePreparationOutboxLocal,
)
from house_continuity_v1_2_executable_contracts_v0 import (
    canonical_json_bytes,
    canonical_sha256,
)


STORE_SCHEMA_VERSION = (
    "house_continuity_private_provider_completion_replay_local_v2"
)
MAX_RETAINED_RESPONSE_BYTES = 4 * 1024 * 1024


class ProviderCompletionReplayLocalError(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _fail(code: str) -> None:
    raise ProviderCompletionReplayLocalError(code)


def _json(value: Mapping[str, Any]) -> str:
    return canonical_json_bytes(value).decode("utf-8")


class HouseContinuityProviderCompletionReplayLocal:
    """Private exact-response retention and deterministic local replay."""

    def __init__(
        self,
        root: str | Path,
        *,
        synthetic_only: bool = False,
        protected_shadow_only: bool = False,
    ):
        if synthetic_only is not True and protected_shadow_only is not True:
            _fail("synthetic_only_required")
        if synthetic_only is True and protected_shadow_only is True:
            _fail("one_local_or_protected_shadow_mode_required")
        self.root = Path(root).resolve()
        if not self.root.exists() or not self.root.is_dir():
            _fail("existing_local_root_required")
        self.database_path = (
            self.root / "private_provider_completion_replay_local.sqlite3"
        )
        existing_store = self.database_path.exists()
        self._connection = sqlite3.connect(
            str(self.database_path), timeout=0.1, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS replay_meta(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provider_completions(
              provider_operation_id TEXT PRIMARY KEY,
              terminal_response_sha256 TEXT NOT NULL UNIQUE,
              state TEXT NOT NULL,
              revision INTEGER NOT NULL,
              record_sha256 TEXT NOT NULL,
              record_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS private_responses(
              provider_operation_id TEXT PRIMARY KEY,
              exact_response BLOB NOT NULL,
              FOREIGN KEY(provider_operation_id)
                REFERENCES provider_completions(provider_operation_id)
            );
            CREATE TABLE IF NOT EXISTS private_visible_responses(
              provider_operation_id TEXT PRIMARY KEY,
              visible_response_sha256 TEXT NOT NULL,
              exact_visible_response BLOB NOT NULL,
              FOREIGN KEY(provider_operation_id)
                REFERENCES provider_completions(provider_operation_id)
            );
            """
        )
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            rows = dict(
                self._connection.execute(
                    "SELECT key,value FROM replay_meta"
                )
            )
            if not rows:
                if existing_store:
                    _fail("replay_store_metadata_missing")
                self._connection.executemany(
                    "INSERT INTO replay_meta VALUES(?,?)",
                    (
                        ("schema_version", STORE_SCHEMA_VERSION),
                        ("store_id", "replay_" + secrets.token_hex(16)),
                    ),
                )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        meta = dict(
            self._connection.execute("SELECT key,value FROM replay_meta")
        )
        if (
            set(meta) != {"schema_version", "store_id"}
            or meta["schema_version"] != STORE_SCHEMA_VERSION
            or not meta["store_id"].startswith("replay_")
            or len(meta["store_id"]) != 39
        ):
            self.close()
            _fail("replay_store_identity_mismatch")
        self.store_id = meta["store_id"]

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def record_completion(
        self,
        *,
        provider_operation_id: str,
        client_turn_id: str,
        room_id: str,
        terminal_response: bytes,
        completed_at: str,
        projection_mode: str = "carrier_tail",
    ) -> dict[str, Any]:
        if (
            not isinstance(terminal_response, bytes)
            or not terminal_response
            or len(terminal_response) > MAX_RETAINED_RESPONSE_BYTES
        ):
            _fail("invalid_private_terminal_response")
        digest = hashlib.sha256(terminal_response).hexdigest()
        record = {
            "schema_version": STORE_SCHEMA_VERSION,
            "provider_operation_id": provider_operation_id,
            "client_turn_id": client_turn_id,
            "room_id": room_id,
            "terminal_response_sha256": digest,
            "state": "retained_unparsed",
            "parse_receipt_sha256": None,
            "visible_response_sha256": None,
            "stripped_private_ranges": [],
            "outbox_bundle_id": None,
            "last_error_code": None,
            "completed_at": completed_at,
            "visible_released_at": None,
            "provider_call_count": 1,
            "replay_provider_call_count": 0,
            "raw_body_in_record": False,
        }
        if projection_mode not in {
            "carrier_tail",
            "structured_terminal_result",
        }:
            _fail("invalid_private_projection_mode")
        if projection_mode != "carrier_tail":
            record["projection_mode"] = projection_mode
        existing = self._row(provider_operation_id)
        if existing is not None:
            stored = json.loads(existing["record_json"])
            private = self._response(provider_operation_id)
            if stored != record or private != terminal_response:
                _fail("provider_completion_identity_conflict")
            return stored
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                "INSERT INTO provider_completions VALUES(?,?,?,?,?,?)",
                (
                    provider_operation_id,
                    digest,
                    record["state"],
                    1,
                    canonical_sha256(record),
                    _json(record),
                ),
            )
            self._connection.execute(
                "INSERT INTO private_responses VALUES(?,?)",
                (provider_operation_id, terminal_response),
            )
            self._connection.commit()
        except sqlite3.IntegrityError as exc:
            self._connection.rollback()
            raise ProviderCompletionReplayLocalError(
                "provider_completion_identity_conflict"
            ) from exc
        return record

    def replay_parse_and_prepare(
        self,
        provider_operation_id: str,
        *,
        parser: HouseContinuityTerminalParserLocal,
        outbox: HouseContinuityDurablePreparationOutboxLocal,
        parser_arguments: Mapping[str, Any],
        now: str,
        capability_id: str,
        failpoint: str | None = None,
        parsed_result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        current, revision, record_sha = self._current(
            provider_operation_id
        )
        if current["state"] in {
            "prepared",
            "rejected",
            "explicit_no_delta",
            "closed_unused",
            "preparation_failed_visible_authorized",
            "visible_released",
        }:
            return current
        response = self._response(provider_operation_id)
        if failpoint == "after_provider_result_before_parse":
            _fail("simulated_crash_after_provider_result")
        result = (
            deepcopy(dict(parsed_result))
            if parsed_result is not None
            else parser.parse(
                response,
                now=now,
                **deepcopy(dict(parser_arguments)),
            )
        )
        if result.get("response_sha256") != hashlib.sha256(response).hexdigest():
            _fail("provider_completion_parse_identity_conflict")
        parse_receipt_sha = canonical_sha256(
            {
                "provider_operation_id": provider_operation_id,
                "response_sha256": result["response_sha256"],
                "visible_sha256": result["visible_sha256"],
                "stripped_private_ranges": result[
                    "stripped_private_ranges"
                ],
                "continuity_state": result["continuity_state"],
                "capability_effect": result["capability_effect"],
            }
        )
        visible_bytes = bytes(result["visible_bytes"])
        parsed = deepcopy(current)
        parsed.update(
            {
                "state": "parsed_pending_preparation",
                "parse_receipt_sha256": parse_receipt_sha,
                "visible_response_sha256": hashlib.sha256(
                    visible_bytes
                ).hexdigest(),
                "stripped_private_ranges": result[
                    "stripped_private_ranges"
                ],
            }
        )
        if current["state"] == "retained_unparsed":
            current = self._record_parse(
                current,
                parsed,
                visible_bytes=visible_bytes,
                expected_revision=revision,
                expected_record_sha256=record_sha,
            )
            current, revision, record_sha = self._current(
                provider_operation_id
            )
        elif current["state"] == "parsed_pending_preparation":
            if (
                current["visible_response_sha256"]
                != hashlib.sha256(visible_bytes).hexdigest()
                or self._visible_response(provider_operation_id)
                != visible_bytes
            ):
                _fail("provider_completion_parse_identity_conflict")
        if failpoint == "after_parse_before_preparation":
            _fail("simulated_crash_after_parse")
        changed = deepcopy(current)
        existing_preparation = outbox.preparation_receipt_for_capability(
            capability_id
        )
        if existing_preparation is not None:
            changed["state"] = "prepared"
            changed["outbox_bundle_id"] = existing_preparation["bundle_id"]
            return self._cas_replace(
                current,
                changed,
                expected_revision=revision,
                expected_record_sha256=record_sha,
            )
        if result["continuity_write_permitted"]:
            try:
                receipt = outbox.prepare(result, now=now)
                if (
                    failpoint
                    == "after_preparation_commit_before_replay_cas"
                ):
                    _fail("simulated_crash_after_preparation_commit")
                changed["state"] = "prepared"
                changed["outbox_bundle_id"] = receipt["bundle_id"]
            except DurablePreparationOutboxLocalError:
                existing_preparation = (
                    outbox.preparation_receipt_for_capability(capability_id)
                )
                if existing_preparation is not None:
                    changed["state"] = "prepared"
                    changed["outbox_bundle_id"] = existing_preparation[
                        "bundle_id"
                    ]
                else:
                    outbox.record_preparation_failure(
                        provider_operation_id, at=now
                    )
                    changed["state"] = (
                        "preparation_failed_visible_authorized"
                    )
                    changed["last_error_code"] = (
                        "durable_preparation_failed_retryable"
                    )
        elif result["capability_effect"] in {
            "rejected_consumed",
            "binding_failure_recorded",
            "replay_recorded",
        }:
            changed["state"] = "rejected"
        elif result["capability_effect"] == "explicit_no_delta_consumed":
            changed["state"] = "explicit_no_delta"
        else:
            capability = parser.registry.read(capability_id)
            if capability is None:
                _fail("capability_not_found_for_close")
            parser.registry.close_unused(
                capability_id,
                client_turn_id=current["client_turn_id"],
                room_id=current["room_id"],
                provider_operation_id=provider_operation_id,
                protocol_version=capability["protocol_version"],
                terminal_response_sha256=current[
                    "terminal_response_sha256"
                ],
                at=now,
            )
            changed["state"] = "closed_unused"
        return self._cas_replace(
            current,
            changed,
            expected_revision=revision,
            expected_record_sha256=record_sha,
        )

    def release_visible(
        self,
        provider_operation_id: str,
        *,
        outbox: HouseContinuityDurablePreparationOutboxLocal,
        at: str,
    ) -> bytes:
        current, revision, record_sha = self._current(
            provider_operation_id
        )
        if current["state"] == "visible_released":
            return self._visible_response(provider_operation_id)
        if current["state"] not in {
            "prepared",
            "rejected",
            "explicit_no_delta",
            "closed_unused",
            "preparation_failed_visible_authorized",
        }:
            _fail("private_response_release_not_authorized")
        outbox.record_visible_release(provider_operation_id, at=at)
        changed = deepcopy(current)
        changed["state"] = "visible_released"
        changed["visible_released_at"] = at
        self._cas_replace(
            current,
            changed,
            expected_revision=revision,
            expected_record_sha256=record_sha,
        )
        return self._visible_response(provider_operation_id)

    @staticmethod
    def _visible_bytes(
        response: bytes, ranges: list[Mapping[str, Any]]
    ) -> bytes:
        cursor = 0
        pieces = []
        for item in sorted(ranges, key=lambda value: value["start"]):
            pieces.append(response[cursor : item["start"]])
            cursor = item["end"]
        pieces.append(response[cursor:])
        return b"".join(pieces)

    def read(self, provider_operation_id: str) -> dict[str, Any] | None:
        row = self._row(provider_operation_id)
        return None if row is None else json.loads(row["record_json"])

    def doctor(self) -> dict[str, Any]:
        meta = dict(
            self._connection.execute("SELECT key,value FROM replay_meta")
        )
        if meta != {
            "schema_version": STORE_SCHEMA_VERSION,
            "store_id": self.store_id,
        }:
            _fail("replay_store_identity_mismatch")
        if self._connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            _fail("replay_foreign_keys_unavailable")
        if self._connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] != "ok":
            _fail("replay_sqlite_integrity_failure")
        if list(self._connection.execute("PRAGMA foreign_key_check")):
            _fail("replay_foreign_key_failure")
        count = 0
        for row in self._connection.execute(
            "SELECT * FROM provider_completions"
        ):
            record = json.loads(row["record_json"])
            response = self._response(row["provider_operation_id"])
            visible_row = self._connection.execute(
                "SELECT visible_response_sha256,exact_visible_response"
                " FROM private_visible_responses"
                " WHERE provider_operation_id=?",
                (row["provider_operation_id"],),
            ).fetchone()
            parsed_state = record["state"] != "retained_unparsed"
            if (
                row["terminal_response_sha256"]
                != hashlib.sha256(response).hexdigest()
                or row["state"] != record["state"]
                or row["record_sha256"] != canonical_sha256(record)
                or row["revision"] < 1
                or record["raw_body_in_record"] is not False
                or record["replay_provider_call_count"] != 0
                or parsed_state != (visible_row is not None)
            ):
                _fail("replay_record_integrity_failure")
            if visible_row is not None:
                visible = bytes(visible_row["exact_visible_response"])
                visible_sha = hashlib.sha256(visible).hexdigest()
                projection_mode = record.get(
                    "projection_mode", "carrier_tail"
                )
                if projection_mode == "structured_terminal_result":
                    from house_continuity_v1_2_structured_terminal_result_v1 import (
                        visible_response_from_replay_arguments,
                    )
                    projected_visible = (
                        visible_response_from_replay_arguments(response)
                    )
                else:
                    projected_visible = self._visible_bytes(
                        response, record["stripped_private_ranges"]
                    )
                if (
                    visible_row["visible_response_sha256"] != visible_sha
                    or record["visible_response_sha256"] != visible_sha
                    or projected_visible != visible
                ):
                    _fail("replay_visible_projection_integrity_failure")
            count += 1
        return {
            "schema_version": "house_continuity_replay_doctor_v1",
            "store_id": self.store_id,
            "completion_count": count,
            "provider_replay_call_count": 0,
            "private_response_owner_separate": True,
        }

    def _row(self, operation_id: str):
        return self._connection.execute(
            "SELECT * FROM provider_completions"
            " WHERE provider_operation_id=?",
            (operation_id,),
        ).fetchone()

    def _response(self, operation_id: str) -> bytes:
        row = self._connection.execute(
            "SELECT exact_response FROM private_responses"
            " WHERE provider_operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            _fail("private_response_missing")
        return bytes(row["exact_response"])

    def _visible_response(self, operation_id: str) -> bytes:
        row = self._connection.execute(
            "SELECT exact_visible_response FROM private_visible_responses"
            " WHERE provider_operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            _fail("private_visible_response_missing")
        return bytes(row["exact_visible_response"])

    def _current(self, operation_id: str):
        row = self._row(operation_id)
        if row is None:
            _fail("provider_completion_not_found")
        return (
            json.loads(row["record_json"]),
            row["revision"],
            row["record_sha256"],
        )

    def _cas_replace(
        self,
        previous: Mapping[str, Any],
        changed: Mapping[str, Any],
        *,
        expected_revision: int,
        expected_record_sha256: str,
    ) -> dict[str, Any]:
        next_record = deepcopy(dict(changed))
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            updated = self._connection.execute(
                "UPDATE provider_completions SET state=?,revision=?,"
                "record_sha256=?,record_json=?"
                " WHERE provider_operation_id=? AND revision=?"
                " AND record_sha256=?",
                (
                    next_record["state"],
                    expected_revision + 1,
                    canonical_sha256(next_record),
                    _json(next_record),
                    previous["provider_operation_id"],
                    expected_revision,
                    expected_record_sha256,
                ),
            ).rowcount
            if updated != 1:
                self._connection.rollback()
                _fail("provider_completion_cas_conflict")
            self._connection.commit()
        except sqlite3.OperationalError as exc:
            if self._connection.in_transaction:
                self._connection.rollback()
            if "locked" in str(exc).lower():
                raise ProviderCompletionReplayLocalError(
                    "sqlite_write_locked"
                ) from exc
            raise
        return next_record

    def _record_parse(
        self,
        previous: Mapping[str, Any],
        changed: Mapping[str, Any],
        *,
        visible_bytes: bytes,
        expected_revision: int,
        expected_record_sha256: str,
    ) -> dict[str, Any]:
        next_record = deepcopy(dict(changed))
        visible_sha = hashlib.sha256(visible_bytes).hexdigest()
        if next_record["visible_response_sha256"] != visible_sha:
            _fail("provider_completion_visible_hash_mismatch")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            updated = self._connection.execute(
                "UPDATE provider_completions SET state=?,revision=?,"
                "record_sha256=?,record_json=?"
                " WHERE provider_operation_id=? AND revision=?"
                " AND record_sha256=?",
                (
                    next_record["state"],
                    expected_revision + 1,
                    canonical_sha256(next_record),
                    _json(next_record),
                    previous["provider_operation_id"],
                    expected_revision,
                    expected_record_sha256,
                ),
            ).rowcount
            if updated != 1:
                self._connection.rollback()
                _fail("provider_completion_cas_conflict")
            self._connection.execute(
                "INSERT INTO private_visible_responses VALUES(?,?,?)",
                (
                    previous["provider_operation_id"],
                    visible_sha,
                    visible_bytes,
                ),
            )
            self._connection.commit()
        except sqlite3.IntegrityError as exc:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise ProviderCompletionReplayLocalError(
                "provider_completion_parse_identity_conflict"
            ) from exc
        return next_record


__all__ = [
    "HouseContinuityProviderCompletionReplayLocal",
    "MAX_RETAINED_RESPONSE_BYTES",
    "ProviderCompletionReplayLocalError",
    "STORE_SCHEMA_VERSION",
]
