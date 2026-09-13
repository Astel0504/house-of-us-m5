"""Gate-4 local capability registry and end-anchored private-tail parser.

This module is synthetic/local only.  It is not imported by a House runtime
route, does not call a provider, does not invoke the Memory writer, and does
not prepare a durable continuity outbox.  A valid result is explicitly a
Gate-5 preparation candidate, never a committed continuity mutation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from house_continuity_v1_2_executable_contracts_v0 import (
    HouseContinuityV12ContractError,
    canonical_json_bytes,
    is_no_delta_canonicalization,
    validate_command_context,
    validate_continuity_intent,
    validate_intent_against_capability,
    validate_intent_capability,
)
from house_continuity_v1_2_terminal_tail_fixtures_v0 import (
    CONTINUITY_CLOSE,
    CONTINUITY_OPEN,
    MAX_CONTINUITY_CANDIDATE_BYTES,
    MAX_TERMINAL_WHITESPACE_BYTES,
    MEMORY_CLOSE,
    MEMORY_OPEN,
)


STORE_SCHEMA_VERSION = (
    "house_continuity_v1_2_capability_terminal_parser_local_v2"
)
PARSE_RESULT_SCHEMA_VERSION = (
    "house_continuity_terminal_parse_result_local_v1"
)
_CAPABILITY_PREFIX = re.compile(
    rb'^<house-continuity-intent>\{"capability":"'
    rb"(cwc_[A-Za-z0-9_-]{43})\""
)
_CLEAR_CAPABILITY_RE = re.compile(r"^cwc_[A-Za-z0-9_-]{43}$")
_JSON_STRING_TOKEN_RE = re.compile(
    rb'"(?:[\x20-\x21\x23-\x5b\x5d-\xff]'
    rb'|\\(?:["\\/bfnrt]|u[0-9A-Fa-f]{4}))*"'
)
_TERMINAL_WHITESPACE = b" \t\r\n"
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_PRIVACY_TAIL_BYTES = _MAX_RESPONSE_BYTES


class CapabilityTerminalParserLocalError(ValueError):
    """Stable body-free Gate-4 failure."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _fail(code: str) -> None:
    raise CapabilityTerminalParserLocalError(code)


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        _fail("invalid_gate4_timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail("invalid_gate4_timestamp")
    if parsed.tzinfo != timezone.utc:
        _fail("invalid_gate4_timestamp")
    return parsed


def _json(value: Mapping[str, Any]) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _load(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        _fail("stored_gate4_shape_invalid")
    return loaded


def _response_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _record_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _before_line_break(data: bytes, start: int) -> int:
    cursor = start
    if cursor > 0 and data[cursor - 1 : cursor] == b"\n":
        cursor -= 1
        if cursor > 0 and data[cursor - 1 : cursor] == b"\r":
            cursor -= 1
    return cursor


def _line_start(data: bytes, end: int) -> int:
    return data.rfind(b"\n", 0, end) + 1


def _line_is_fenced(data: bytes, start: int) -> bool:
    """Return whether the line at start is inside a preceding Markdown fence."""

    fence_char: int | None = None
    fence_length = 0
    for line in data[:start].splitlines():
        indent = len(line) - len(line.lstrip(b" "))
        if indent > 3:
            continue
        stripped = line[indent:]
        if not stripped or stripped[0] not in (ord("`"), ord("~")):
            continue
        marker = stripped[0]
        marker_length = len(stripped) - len(stripped.lstrip(bytes((marker,))))
        if marker_length < 3:
            continue
        remainder = stripped[marker_length:]
        if fence_char is None:
            if marker == ord("`") and b"`" in remainder:
                continue
            fence_char = marker
            fence_length = marker_length
            continue
        if (
            marker == fence_char
            and marker_length >= fence_length
            and not remainder.strip(b" \t")
        ):
            fence_char = None
            fence_length = 0
    return fence_char is not None


def _terminal_whitespace_start(data: bytes) -> tuple[int, bool]:
    cursor = len(data)
    while cursor > 0 and data[cursor - 1] in _TERMINAL_WHITESPACE:
        cursor -= 1
    count = len(data) - cursor
    return cursor, count <= MAX_TERMINAL_WHITESPACE_BYTES


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _canonical_intent_bytes(intent: Mapping[str, Any]) -> bytes:
    return json.dumps(
        intent,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


class HouseContinuityCapabilityRegistryLocal:
    """Digest-only local registry for one-use turn capabilities."""

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
            self.root / "continuity_capability_terminal_parser_local.sqlite3"
        )
        existing_store = self.database_path.exists()
        self._connection = sqlite3.connect(
            str(self.database_path), timeout=0.1
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        if self._connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            self._connection.close()
            _fail("gate4_foreign_keys_unavailable")
        self._connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS store_meta(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS capabilities(
              capability_id TEXT PRIMARY KEY,
              capability_sha256 TEXT NOT NULL UNIQUE,
              client_turn_id TEXT NOT NULL,
              room_id TEXT NOT NULL,
              provider_operation_id TEXT NOT NULL,
              protocol_version TEXT NOT NULL,
              state TEXT NOT NULL,
              replay_attempt_count INTEGER NOT NULL,
              revision INTEGER NOT NULL,
              record_sha256 TEXT NOT NULL,
              record_json TEXT NOT NULL,
              UNIQUE(
                client_turn_id,
                room_id,
                provider_operation_id,
                protocol_version
              )
            );
            CREATE TABLE IF NOT EXISTS parser_receipts(
              receipt_id TEXT PRIMARY KEY,
              capability_id TEXT NOT NULL,
              capability_revision INTEGER NOT NULL,
              client_turn_id TEXT NOT NULL,
              room_id TEXT NOT NULL,
              provider_operation_id TEXT NOT NULL,
              protocol_version TEXT NOT NULL,
              terminal_response_sha256 TEXT NOT NULL,
              result_code TEXT NOT NULL,
              created_at TEXT NOT NULL,
              receipt_sha256 TEXT NOT NULL UNIQUE,
              raw_body_included INTEGER NOT NULL CHECK(raw_body_included=0),
              FOREIGN KEY(capability_id)
                REFERENCES capabilities(capability_id)
            );
            """
        )
        with self._connection:
            metadata = dict(
                self._connection.execute("SELECT key,value FROM store_meta")
            )
            if not metadata:
                if existing_store:
                    self._connection.close()
                    _fail("gate4_store_metadata_missing")
                self._connection.executemany(
                    "INSERT INTO store_meta(key,value) VALUES(?,?)",
                    (
                        ("schema_version", STORE_SCHEMA_VERSION),
                        ("store_id", "gate4_" + secrets.token_hex(16)),
                    ),
                )
        metadata = dict(
            self._connection.execute("SELECT key,value FROM store_meta")
        )
        if (
            set(metadata) != {"schema_version", "store_id"}
            or metadata["schema_version"] != STORE_SCHEMA_VERSION
            or not metadata["store_id"].startswith("gate4_")
            or len(metadata["store_id"]) != 38
        ):
            self._connection.close()
            _fail("gate4_store_metadata_mismatch")
        self.store_id = metadata["store_id"]

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "HouseContinuityCapabilityRegistryLocal":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def issue(
        self, record: Mapping[str, Any], *, clear_capability: str
    ) -> dict[str, Any]:
        try:
            normalized = validate_intent_capability(record)
        except HouseContinuityV12ContractError as exc:
            raise CapabilityTerminalParserLocalError(
                exc.error_code
            ) from exc
        if normalized["state"] != "issued":
            _fail("capability_must_begin_issued")
        if not isinstance(clear_capability, str):
            _fail("invalid_clear_continuity_capability")
        try:
            clear_bytes = clear_capability.encode("ascii")
        except UnicodeEncodeError:
            _fail("invalid_clear_continuity_capability")
        digest = hashlib.sha256(clear_bytes).hexdigest()
        if not hmac.compare_digest(
            digest, normalized["capability_sha256"]
        ):
            _fail("clear_capability_digest_mismatch")
        row = self._connection.execute(
            "SELECT record_json FROM capabilities"
            " WHERE capability_id=? OR capability_sha256=?",
            (
                normalized["capability_id"],
                normalized["capability_sha256"],
            ),
        ).fetchone()
        if row is not None:
            existing = _load(row["record_json"])
            if existing != normalized:
                _fail("capability_identity_conflict")
            return existing
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO capabilities VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        normalized["capability_id"],
                        normalized["capability_sha256"],
                        normalized["client_turn_id"],
                        normalized["room_id"],
                        normalized["provider_operation_id"],
                        normalized["protocol_version"],
                        normalized["state"],
                        normalized["replay_attempt_count"],
                        1,
                        _record_sha256(normalized),
                        _json(normalized),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise CapabilityTerminalParserLocalError(
                "capability_identity_conflict"
            ) from exc
        return normalized

    def lookup_clear(self, clear_capability: str) -> dict[str, Any] | None:
        if not isinstance(clear_capability, str):
            return None
        try:
            clear_bytes = clear_capability.encode("ascii")
        except UnicodeEncodeError:
            return None
        digest = hashlib.sha256(clear_bytes).hexdigest()
        row = self._connection.execute(
            "SELECT capability_sha256,record_json FROM capabilities"
            " WHERE capability_sha256=?",
            (digest,),
        ).fetchone()
        if row is None or not hmac.compare_digest(
            row["capability_sha256"], digest
        ):
            return None
        try:
            return validate_intent_capability(_load(row["record_json"]))
        except HouseContinuityV12ContractError as exc:
            raise CapabilityTerminalParserLocalError(
                exc.error_code
            ) from exc

    def read(self, capability_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT record_json FROM capabilities WHERE capability_id=?",
            (capability_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            return validate_intent_capability(_load(row["record_json"]))
        except HouseContinuityV12ContractError as exc:
            raise CapabilityTerminalParserLocalError(
                exc.error_code
            ) from exc

    def transition_for_test(
        self,
        capability_id: str,
        *,
        state: str,
        at: str | None = None,
        outbox_bundle_id: str | None = None,
        terminal_response_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Fixture-only lifecycle setup; Gate 5 owns real atomic preparation."""

        current = self.read(capability_id)
        if current is None:
            _fail("capability_not_found")
        changed = deepcopy(current)
        changed.update(
            {
                "state": state,
                "consumed_at": (
                    at
                    if state in {"prepared_consumed", "rejected_consumed"}
                    else None
                ),
                "outbox_bundle_id": (
                    outbox_bundle_id if state == "prepared_consumed" else None
                ),
                "terminal_response_sha256": (
                    terminal_response_sha256
                    if state in {"prepared_consumed", "rejected_consumed"}
                    else None
                ),
            }
        )
        return self._cas_replace(
            current,
            changed,
            result_code="fixture_transition",
            response_sha256=(
                terminal_response_sha256
                or hashlib.sha256(b"fixture-transition").hexdigest()
            ),
            at=at or current["issued_at"],
            write_receipt=False,
        )

    def close_unused(
        self,
        capability_id: str,
        *,
        client_turn_id: str,
        room_id: str,
        provider_operation_id: str,
        protocol_version: str,
        terminal_response_sha256: str,
        at: str,
    ) -> dict[str, Any]:
        return self._terminal_unconsumed_transition(
            capability_id,
            state="closed_unused",
            result_code="operation_closed_without_carrier",
            client_turn_id=client_turn_id,
            room_id=room_id,
            provider_operation_id=provider_operation_id,
            protocol_version=protocol_version,
            terminal_response_sha256=terminal_response_sha256,
            at=at,
        )

    def invalidate(
        self,
        capability_id: str,
        *,
        client_turn_id: str,
        room_id: str,
        provider_operation_id: str,
        protocol_version: str,
        terminal_response_sha256: str,
        at: str,
    ) -> dict[str, Any]:
        return self._terminal_unconsumed_transition(
            capability_id,
            state="invalidated",
            result_code="turn_or_operation_cancelled",
            client_turn_id=client_turn_id,
            room_id=room_id,
            provider_operation_id=provider_operation_id,
            protocol_version=protocol_version,
            terminal_response_sha256=terminal_response_sha256,
            at=at,
        )

    def expire(
        self,
        capability_id: str,
        *,
        client_turn_id: str,
        room_id: str,
        provider_operation_id: str,
        protocol_version: str,
        terminal_response_sha256: str,
        now: str,
    ) -> dict[str, Any]:
        current = self.read(capability_id)
        if current is None:
            _fail("capability_not_found")
        self._require_binding(
            current,
            client_turn_id=client_turn_id,
            room_id=room_id,
            provider_operation_id=provider_operation_id,
            protocol_version=protocol_version,
        )
        if _timestamp(now) < _timestamp(current["expires_at"]):
            _fail("capability_not_due_for_expiry")
        if current["state"] != "issued":
            return self.record_binding_or_replay_failure(
                current,
                response_sha256=terminal_response_sha256,
                result_code="expiry_raced_terminal_state",
                at=now,
            )
        changed = deepcopy(current)
        changed["state"] = "expired"
        try:
            return self._cas_replace(
                current,
                changed,
                result_code="ttl_elapsed",
                response_sha256=terminal_response_sha256,
                at=now,
            )
        except CapabilityTerminalParserLocalError as exc:
            if exc.error_code != "capability_cas_conflict":
                raise
            return self.record_binding_or_replay_failure(
                self.read(capability_id),
                response_sha256=terminal_response_sha256,
                result_code="expiry_raced_terminal_state",
                at=now,
            )

    def _terminal_unconsumed_transition(
        self,
        capability_id: str,
        *,
        state: str,
        result_code: str,
        client_turn_id: str,
        room_id: str,
        provider_operation_id: str,
        protocol_version: str,
        terminal_response_sha256: str,
        at: str,
    ) -> dict[str, Any]:
        current = self.read(capability_id)
        if current is None:
            _fail("capability_not_found")
        self._require_binding(
            current,
            client_turn_id=client_turn_id,
            room_id=room_id,
            provider_operation_id=provider_operation_id,
            protocol_version=protocol_version,
        )
        if current["state"] != "issued":
            return self.record_binding_or_replay_failure(
                current,
                response_sha256=terminal_response_sha256,
                result_code=result_code + "_raced_terminal_state",
                at=at,
            )
        changed = deepcopy(current)
        changed["state"] = state
        try:
            return self._cas_replace(
                current,
                changed,
                result_code=result_code,
                response_sha256=terminal_response_sha256,
                at=at,
            )
        except CapabilityTerminalParserLocalError as exc:
            if exc.error_code != "capability_cas_conflict":
                raise
            return self.record_binding_or_replay_failure(
                self.read(capability_id),
                response_sha256=terminal_response_sha256,
                result_code=result_code + "_raced_terminal_state",
                at=at,
            )

    @staticmethod
    def _require_binding(
        record: Mapping[str, Any],
        *,
        client_turn_id: str,
        room_id: str,
        provider_operation_id: str,
        protocol_version: str,
    ) -> None:
        if (
            record["client_turn_id"] != client_turn_id
            or record["room_id"] != room_id
            or record["provider_operation_id"] != provider_operation_id
            or record["protocol_version"] != protocol_version
        ):
            _fail("capability_lifecycle_binding_mismatch")

    def record_binding_or_replay_failure(
        self,
        record: Mapping[str, Any],
        *,
        response_sha256: str,
        result_code: str,
        at: str,
    ) -> dict[str, Any]:
        capability_id = record["capability_id"]
        for _ in range(8):
            current = self.read(capability_id)
            if current is None:
                _fail("capability_not_found")
            changed = deepcopy(current)
            changed["replay_attempt_count"] += 1
            try:
                return self._cas_replace(
                    current,
                    changed,
                    result_code=result_code,
                    response_sha256=response_sha256,
                    at=at,
                )
            except CapabilityTerminalParserLocalError as exc:
                if exc.error_code != "capability_cas_conflict":
                    raise
        _fail("capability_cas_retry_exhausted")

    def is_explicit_no_delta_replay(
        self,
        record: Mapping[str, Any],
        *,
        response_sha256: str,
    ) -> bool:
        """Recognize the same durable no-delta completion during reparsing.

        The false-scope-conflict correction consumes the capability while
        recording explicit no-delta. A crash can occur before the replay
        owner records its parse receipt, so a restart must reclassify that
        exact response instead of converting it into generic replay
        rejection. The response digest, consumed capability, and durable
        receipt code bind this recognition to the original terminal result.
        """
        if (
            record.get("state") != "rejected_consumed"
            or record.get("terminal_response_sha256") != response_sha256
        ):
            return False
        row = self._connection.execute(
            "SELECT result_code FROM parser_receipts "
            "WHERE capability_id=? AND terminal_response_sha256=? "
            "ORDER BY capability_revision DESC LIMIT 1",
            (record["capability_id"], response_sha256),
        ).fetchone()
        return row is not None and row["result_code"] == (
            "explicit_solen_no_semantic_delta"
        )

    def reject_consumed(
        self,
        record: Mapping[str, Any],
        *,
        response_sha256: str,
        result_code: str,
        at: str,
    ) -> dict[str, Any]:
        current = self.read(record["capability_id"])
        if current is None:
            _fail("capability_not_found")
        if current["state"] != "issued":
            return self.record_binding_or_replay_failure(
                current,
                response_sha256=response_sha256,
                result_code=result_code,
                at=at,
            )
        changed = deepcopy(current)
        changed.update(
            {
                "state": "rejected_consumed",
                "consumed_at": at,
                "outbox_bundle_id": None,
                "terminal_response_sha256": response_sha256,
            }
        )
        try:
            return self._cas_replace(
                current,
                changed,
                result_code=result_code,
                response_sha256=response_sha256,
                at=at,
            )
        except CapabilityTerminalParserLocalError as exc:
            if exc.error_code != "capability_cas_conflict":
                raise
            return self.record_binding_or_replay_failure(
                self.read(current["capability_id"]),
                response_sha256=response_sha256,
                result_code=result_code + "_raced",
                at=at,
            )

    def expire_if_due(
        self, record: Mapping[str, Any], *, now: str
    ) -> dict[str, Any]:
        if (
            record["state"] == "issued"
            and _timestamp(now) >= _timestamp(record["expires_at"])
        ):
            return self.expire(
                record["capability_id"],
                client_turn_id=record["client_turn_id"],
                room_id=record["room_id"],
                provider_operation_id=record["provider_operation_id"],
                protocol_version=record["protocol_version"],
                terminal_response_sha256=hashlib.sha256(
                    (
                        "expiry:"
                        + record["capability_id"]
                        + ":"
                        + now
                    ).encode("utf-8")
                ).hexdigest(),
                now=now,
            )
        return dict(record)

    def _cas_replace(
        self,
        current: Mapping[str, Any],
        record: Mapping[str, Any],
        *,
        result_code: str,
        response_sha256: str,
        at: str,
        write_receipt: bool = True,
    ) -> dict[str, Any]:
        try:
            normalized = validate_intent_capability(record)
        except HouseContinuityV12ContractError as exc:
            raise CapabilityTerminalParserLocalError(
                exc.error_code
            ) from exc
        _timestamp(at)
        if not re.fullmatch(r"[0-9a-f]{64}", response_sha256):
            _fail("invalid_terminal_response_sha256")
        row = self._connection.execute(
            "SELECT revision,record_sha256,record_json FROM capabilities"
            " WHERE capability_id=?",
            (normalized["capability_id"],),
        ).fetchone()
        if row is None:
            _fail("capability_not_found")
        if _load(row["record_json"]) != current:
            _fail("capability_cas_conflict")
        next_revision = row["revision"] + 1
        next_sha = _record_sha256(normalized)
        receipt = self._transition_receipt(
            normalized,
            capability_revision=next_revision,
            response_sha256=response_sha256,
            result_code=result_code,
            at=at,
        )
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            changed = self._connection.execute(
                "UPDATE capabilities SET state=?,replay_attempt_count=?,"
                "revision=?,record_sha256=?,record_json=?"
                " WHERE capability_id=? AND revision=? AND record_sha256=?",
                (
                    normalized["state"],
                    normalized["replay_attempt_count"],
                    next_revision,
                    next_sha,
                    _json(normalized),
                    normalized["capability_id"],
                    row["revision"],
                    row["record_sha256"],
                ),
            ).rowcount
            if changed != 1:
                self._connection.rollback()
                _fail("capability_cas_conflict")
            if write_receipt:
                self._insert_receipt(receipt)
            self._connection.commit()
        except CapabilityTerminalParserLocalError:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise CapabilityTerminalParserLocalError(
                "capability_transition_identity_conflict"
            ) from exc
        except sqlite3.OperationalError as exc:
            if self._connection.in_transaction:
                self._connection.rollback()
            if "locked" in str(exc).lower():
                raise CapabilityTerminalParserLocalError(
                    "sqlite_write_locked"
                ) from exc
            raise CapabilityTerminalParserLocalError(
                "sqlite_write_failure"
            ) from exc
        return normalized

    def _transition_receipt(
        self,
        record: Mapping[str, Any],
        *,
        capability_revision: int,
        response_sha256: str,
        result_code: str,
        at: str,
    ) -> dict[str, Any]:
        body = {
            "capability_id": record["capability_id"],
            "capability_revision": capability_revision,
            "client_turn_id": record["client_turn_id"],
            "room_id": record["room_id"],
            "provider_operation_id": record["provider_operation_id"],
            "protocol_version": record["protocol_version"],
            "terminal_response_sha256": response_sha256,
            "result_code": result_code,
            "created_at": at,
            "raw_body_included": False,
        }
        receipt_sha = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        return {
            "receipt_id": "gate4_receipt_" + receipt_sha[:32],
            **body,
            "receipt_sha256": receipt_sha,
        }

    def _insert_receipt(self, receipt: Mapping[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO parser_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,0)",
            (
                receipt["receipt_id"],
                receipt["capability_id"],
                receipt["capability_revision"],
                receipt["client_turn_id"],
                receipt["room_id"],
                receipt["provider_operation_id"],
                receipt["protocol_version"],
                receipt["terminal_response_sha256"],
                receipt["result_code"],
                receipt["created_at"],
                receipt["receipt_sha256"],
            ),
        )

    def doctor(self, *, require_outbox_links: bool = False) -> dict[str, Any]:
        metadata = dict(
            self._connection.execute("SELECT key,value FROM store_meta")
        )
        if (
            metadata.get("schema_version") != STORE_SCHEMA_VERSION
            or metadata.get("store_id") != self.store_id
            or set(metadata) != {"schema_version", "store_id"}
        ):
            _fail("gate4_store_metadata_mismatch")
        if self._connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            _fail("gate4_foreign_keys_unavailable")
        integrity = self._connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        if integrity != "ok":
            _fail("gate4_sqlite_integrity_failure")
        if list(self._connection.execute("PRAGMA foreign_key_check")):
            _fail("gate4_foreign_key_failure")
        capability_count = 0
        for row in self._connection.execute(
            "SELECT capability_id,capability_sha256,client_turn_id,room_id,"
            "provider_operation_id,protocol_version,state,"
            "replay_attempt_count,revision,record_sha256,record_json"
            " FROM capabilities"
        ):
            try:
                record = validate_intent_capability(_load(row["record_json"]))
            except HouseContinuityV12ContractError as exc:
                raise CapabilityTerminalParserLocalError(
                    exc.error_code
                ) from exc
            indexed = {
                "capability_id": record["capability_id"],
                "capability_sha256": record["capability_sha256"],
                "client_turn_id": record["client_turn_id"],
                "room_id": record["room_id"],
                "provider_operation_id": record["provider_operation_id"],
                "protocol_version": record["protocol_version"],
                "state": record["state"],
                "replay_attempt_count": record["replay_attempt_count"],
            }
            if any(row[key] != value for key, value in indexed.items()):
                _fail("capability_index_json_mismatch")
            if (
                row["revision"] < 1
                or row["record_sha256"] != _record_sha256(record)
            ):
                _fail("capability_revision_hash_mismatch")
            if require_outbox_links and record["state"] == "prepared_consumed":
                linked = self._connection.execute(
                    "SELECT 1 FROM outbox_bundles"
                    " WHERE bundle_id=? AND capability_id=?",
                    (record["outbox_bundle_id"], record["capability_id"]),
                ).fetchone()
                if linked is None:
                    _fail("prepared_capability_outbox_link_missing")
            capability_count += 1
        receipt_count = 0
        for row in self._connection.execute(
            "SELECT * FROM parser_receipts ORDER BY capability_id,"
            "capability_revision"
        ):
            body = {
                "capability_id": row["capability_id"],
                "capability_revision": row["capability_revision"],
                "client_turn_id": row["client_turn_id"],
                "room_id": row["room_id"],
                "provider_operation_id": row["provider_operation_id"],
                "protocol_version": row["protocol_version"],
                "terminal_response_sha256": row[
                    "terminal_response_sha256"
                ],
                "result_code": row["result_code"],
                "created_at": row["created_at"],
                "raw_body_included": False,
            }
            receipt_sha = hashlib.sha256(
                canonical_json_bytes(body)
            ).hexdigest()
            cap = self._connection.execute(
                "SELECT client_turn_id,room_id,provider_operation_id,"
                "protocol_version,revision FROM capabilities"
                " WHERE capability_id=?",
                (row["capability_id"],),
            ).fetchone()
            if (
                cap is None
                or row["capability_revision"] < 2
                or row["capability_revision"] > cap["revision"]
                or any(
                    row[key] != cap[key]
                    for key in (
                        "client_turn_id",
                        "room_id",
                        "provider_operation_id",
                        "protocol_version",
                    )
                )
                or row["receipt_sha256"] != receipt_sha
                or row["receipt_id"]
                != "gate4_receipt_" + receipt_sha[:32]
                or row["raw_body_included"] != 0
                or not re.fullmatch(
                    r"[a-z0-9_]{1,120}", row["result_code"]
                )
            ):
                _fail("parser_receipt_integrity_failure")
            _timestamp(row["created_at"])
            if not re.fullmatch(
                r"[0-9a-f]{64}", row["terminal_response_sha256"]
            ):
                _fail("parser_receipt_integrity_failure")
            receipt_count += 1
        for suffix in ("", "-wal"):
            candidate = Path(str(self.database_path) + suffix)
            if not candidate.exists():
                continue
            data = candidate.read_bytes()
            if (
                b"<house-continuity-intent>" in data
                or re.search(rb"cwc_[A-Za-z0-9_-]{43}", data)
            ):
                _fail("gate4_private_material_detected")
        return {
            "schema_version": "house_continuity_gate4_doctor_v1",
            "store_id": self.store_id,
            "capability_count": capability_count,
            "parser_receipt_count": receipt_count,
            "foreign_keys_enabled": True,
            "sqlite_integrity": "ok",
            "raw_private_material_detected": False,
        }


class HouseContinuityTerminalParserLocal:
    """End-anchored parser over successful assistant response bytes."""

    def __init__(self, registry: HouseContinuityCapabilityRegistryLocal):
        self.registry = registry

    def parse(
        self,
        response_bytes: bytes,
        *,
        client_turn_id: str,
        room_id: str,
        provider_operation_id: str,
        protocol_version: str,
        command_context: Mapping[str, Any],
        current_snapshot_sequence: int,
        current_snapshot_sha256: str,
        current_binding_revision: int,
        now: str,
    ) -> dict[str, Any]:
        if not isinstance(response_bytes, bytes):
            _fail("response_bytes_required")
        if len(response_bytes) > _MAX_RESPONSE_BYTES:
            _fail("response_byte_cap_exceeded")
        try:
            response_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            _fail("response_utf8_invalid")
        _timestamp(now)
        try:
            normalized_context = validate_command_context(command_context)
        except HouseContinuityV12ContractError as exc:
            raise CapabilityTerminalParserLocalError(
                exc.error_code
            ) from exc

        response_hash = _response_sha256(response_bytes)
        whitespace_start, whitespace_allowed = _terminal_whitespace_start(
            response_bytes
        )

        cursor = whitespace_start
        ranges: list[dict[str, Any]] = []
        memory_candidates: list[dict[str, Any]] = []
        final_memory = self._memory_candidate(
            response_bytes, cursor, trailing_end=len(response_bytes)
        )
        if final_memory is not None:
            memory_candidates.append(final_memory)
            cursor = _before_line_break(response_bytes, final_memory["start"])
            while True:
                prior_memory = self._memory_candidate(
                    response_bytes, cursor, trailing_end=cursor
                )
                if prior_memory is None:
                    break
                memory_candidates.append(prior_memory)
                cursor = _before_line_break(
                    response_bytes, prior_memory["start"]
                )

        continuity = self._continuity_candidate(
            response_bytes, cursor, trailing_end=(
                len(response_bytes)
                if not memory_candidates
                else cursor
            )
        )
        if continuity is not None:
            cursor = _before_line_break(response_bytes, continuity["start"])

        preceding_private: list[dict[str, Any]] = []
        if continuity is not None:
            while True:
                prior_continuity = self._continuity_candidate(
                    response_bytes, cursor, trailing_end=cursor
                )
                prior_memory = self._memory_candidate(
                    response_bytes, cursor, trailing_end=cursor
                )
                prior = prior_continuity or prior_memory
                if prior is None:
                    break
                preceding_private.append(prior)
                cursor = _before_line_break(response_bytes, prior["start"])

        privacy_attempt = self._privacy_current_capability_attempt(
            response_bytes,
            terminal_content_end=(
                cursor if memory_candidates else whitespace_start
            ),
        )
        canonical_continuity_start = (
            None
            if continuity is None
            else min(
                [continuity["start"]]
                + [
                    item["start"]
                    for item in preceding_private
                    if item["owner"] == "continuity"
                ]
            )
        )
        if privacy_attempt is not None and (
            not whitespace_allowed
            or continuity is None
            or privacy_attempt["start"] < canonical_continuity_start
        ):
            return self._reject_privacy_attempt(
                response_bytes,
                privacy_attempt,
                response_hash=response_hash,
                client_turn_id=client_turn_id,
                room_id=room_id,
                provider_operation_id=provider_operation_id,
                protocol_version=protocol_version,
                at=now,
                memory_candidates=memory_candidates,
            )
        if not whitespace_allowed:
            return self._result(
                response_bytes=response_bytes,
                visible=response_bytes,
                ranges=[],
                continuity_state="not_terminal_literal_visible",
                memory_disposition="not_supplied",
                continuity_write=False,
                memory_write=False,
                normalized_intent=None,
                validated_command_bundle=None,
                capability_id=None,
                capability_effect="none",
                memory_candidate=None,
            )

        structural_code = None
        if len(memory_candidates) > 1:
            structural_code = "rejected_duplicate_private_block"
        if preceding_private:
            owners = [item["owner"] for item in preceding_private]
            if "memory" in owners:
                structural_code = "rejected_out_of_order_private_block"
            else:
                structural_code = "rejected_duplicate_private_block"

        memory = memory_candidates[0] if memory_candidates else None
        memory_disposition = (
            "not_supplied"
            if memory is None
            else memory["disposition"]
        )
        memory_write = bool(memory and memory["valid"])
        normalized_intent = None
        validated_bundle = None
        capability_id = None
        capability_effect = "none"
        continuity_write = False

        all_private = [
            *reversed(preceding_private),
            *([continuity] if continuity is not None else []),
            *reversed(memory_candidates),
        ]
        if structural_code is not None:
            ranges.extend(
                self._range(item["owner"], item["start"], item["end"])
                for item in all_private
            )
            if continuity is not None:
                record = continuity["record"]
                capability_id = record["capability_id"]
                if self._binding_matches(
                    record,
                    client_turn_id=client_turn_id,
                    room_id=room_id,
                    provider_operation_id=provider_operation_id,
                    protocol_version=protocol_version,
                ):
                    self.registry.reject_consumed(
                        record,
                        response_sha256=response_hash,
                        result_code=structural_code,
                        at=now,
                    )
                    capability_effect = "rejected_consumed"
                else:
                    self.registry.record_binding_or_replay_failure(
                        record,
                        response_sha256=response_hash,
                        result_code=structural_code,
                        at=now,
                    )
                    capability_effect = "binding_failure_recorded"
            if memory is not None or any(
                item["owner"] == "memory" for item in preceding_private
            ):
                memory_disposition = structural_code
            memory_write = False
            continuity_state = (
                structural_code
                if continuity is not None
                else "authorship_not_supplied"
            )
        elif continuity is None:
            if memory is not None:
                ranges.append(
                    self._range("memory", memory["start"], memory["end"])
                )
            continuity_state = self._visible_continuity_state(
                response_bytes, whitespace_start
            )
        else:
            record = continuity["record"]
            capability_id = record["capability_id"]
            ranges.append(
                self._range(
                    "continuity", continuity["start"], continuity["end"]
                )
            )
            if memory is not None:
                ranges.append(
                    self._range("memory", memory["start"], memory["end"])
                )
            record = self.registry.expire_if_due(record, now=now)
            binding_matches = self._binding_matches(
                record,
                client_turn_id=client_turn_id,
                room_id=room_id,
                provider_operation_id=provider_operation_id,
                protocol_version=protocol_version,
            )
            explicit_no_delta_replay = (
                binding_matches
                and self.registry.is_explicit_no_delta_replay(
                    record,
                    response_sha256=response_hash,
                )
            )
            if not binding_matches:
                continuity_state = self._binding_failure_code(
                    record,
                    client_turn_id=client_turn_id,
                    room_id=room_id,
                    provider_operation_id=provider_operation_id,
                    protocol_version=protocol_version,
                )
                self.registry.record_binding_or_replay_failure(
                    record,
                    response_sha256=response_hash,
                    result_code=continuity_state,
                    at=now,
                )
                capability_effect = "binding_failure_recorded"
            elif (
                record["state"] != "issued"
                and not explicit_no_delta_replay
            ):
                continuity_state = f"rejected_capability_{record['state']}"
                self.registry.record_binding_or_replay_failure(
                    record,
                    response_sha256=response_hash,
                    result_code=continuity_state,
                    at=now,
                )
                capability_effect = "replay_recorded"
            elif continuity["classification"] != "closed":
                continuity_state = (
                    "rejected_unterminated_known_capability"
                )
                self.registry.reject_consumed(
                    record,
                    response_sha256=response_hash,
                    result_code=continuity_state,
                    at=now,
                )
                capability_effect = "rejected_consumed"
            elif continuity["candidate_size"] > MAX_CONTINUITY_CANDIDATE_BYTES:
                continuity_state = "rejected_oversized_known_capability"
                self.registry.reject_consumed(
                    record,
                    response_sha256=response_hash,
                    result_code=continuity_state,
                    at=now,
                )
                capability_effect = "rejected_consumed"
            else:
                try:
                    intent = self._decode_canonical_intent(
                        continuity["candidate_bytes"]
                    )
                    if intent["protocol_version"] != protocol_version:
                        raise CapabilityTerminalParserLocalError(
                            "wrong_protocol_binding"
                        )
                    capability_for_validation = record
                    if explicit_no_delta_replay:
                        capability_for_validation = deepcopy(record)
                        capability_for_validation.update(
                            {
                                "state": "issued",
                                "consumed_at": None,
                                "outbox_bundle_id": None,
                                "terminal_response_sha256": None,
                            }
                        )
                    validated_bundle = validate_intent_against_capability(
                        intent,
                        normalized_context,
                        capability_for_validation,
                        current_snapshot_sequence=current_snapshot_sequence,
                        current_snapshot_sha256=current_snapshot_sha256,
                        current_binding_revision=current_binding_revision,
                    )
                    validated_bundle[
                        "gate5_durable_operation_context"
                    ] = self._gate5_durable_operation_context(
                        normalized_context,
                        validated_bundle["intent"],
                    )
                    normalized_intent = validated_bundle["intent"]
                except CapabilityTerminalParserLocalError as exc:
                    continuity_state = self._schema_failure_state(
                        exc.error_code
                    )
                    if exc.error_code in {
                        "invalid_protocol_version",
                        "wrong_protocol_binding",
                    }:
                        self.registry.record_binding_or_replay_failure(
                            record,
                            response_sha256=response_hash,
                            result_code=continuity_state,
                            at=now,
                        )
                        capability_effect = "binding_failure_recorded"
                    else:
                        self.registry.reject_consumed(
                            record,
                            response_sha256=response_hash,
                            result_code=continuity_state,
                            at=now,
                        )
                        capability_effect = "rejected_consumed"
                except HouseContinuityV12ContractError as exc:
                    continuity_state = self._schema_failure_state(
                        exc.error_code
                    )
                    if exc.error_code == "invalid_protocol_version":
                        self.registry.record_binding_or_replay_failure(
                            record,
                            response_sha256=response_hash,
                            result_code=continuity_state,
                            at=now,
                        )
                        capability_effect = "binding_failure_recorded"
                    else:
                        self.registry.reject_consumed(
                            record,
                            response_sha256=response_hash,
                            result_code=continuity_state,
                            at=now,
                        )
                        capability_effect = "rejected_consumed"
                else:
                    if is_no_delta_canonicalization(validated_bundle):
                        self.registry.reject_consumed(
                            record,
                            response_sha256=response_hash,
                            result_code="explicit_solen_no_semantic_delta",
                            at=now,
                        )
                        continuity_state = (
                            "explicit_solen_no_semantic_delta"
                        )
                        continuity_write = False
                        capability_effect = "explicit_no_delta_consumed"
                    else:
                        continuity_state = "accepted_known_capability"
                        continuity_write = True
                        capability_effect = "pending_gate5_durable_preparation"

        ranges.sort(key=lambda item: item["start"])
        visible = self._remove_ranges(response_bytes, ranges)
        return self._result(
            response_bytes=response_bytes,
            visible=visible,
            ranges=ranges,
            continuity_state=continuity_state,
            memory_disposition=memory_disposition,
            continuity_write=continuity_write,
            memory_write=memory_write,
            normalized_intent=normalized_intent,
            validated_command_bundle=validated_bundle,
            capability_id=capability_id,
            capability_effect=capability_effect,
            memory_candidate=(
                None if memory is None else memory["candidate_bytes"]
            ),
        )

    def _privacy_current_capability_attempt(
        self,
        data: bytes,
        *,
        terminal_content_end: int,
    ) -> dict[str, Any] | None:
        """Recognize current private authority without relaxing write grammar."""

        lower_bound = max(0, terminal_content_end - _MAX_PRIVACY_TAIL_BYTES)
        open_bytes = CONTINUITY_OPEN.encode("ascii")
        close_bytes = CONTINUITY_CLOSE.encode("ascii")
        starts: list[int] = []
        cursor = lower_bound
        while True:
            found = data.find(open_bytes, cursor, terminal_content_end)
            if found < 0:
                break
            starts.append(found)
            cursor = found + len(open_bytes)
        if not starts:
            return None
        current_matches: list[tuple[int, dict[str, Any]]] = []
        for start in starts:
            if self._privacy_location_protected(data, start):
                continue
            region = data[start:terminal_content_end]
            for clear in self._privacy_capability_strings(region):
                record = self.registry.lookup_clear(clear)
                if record is not None:
                    current_matches.append((start, record))
                    break
        if not current_matches:
            return None
        start, record = min(current_matches, key=lambda item: item[0])
        last_close = data.rfind(close_bytes, start, terminal_content_end)
        if last_close >= start:
            end = last_close + len(close_bytes)
            trailing = data[end:terminal_content_end]
            if trailing.strip(b" \t\r\n"):
                return None
        else:
            end = terminal_content_end
        return {
            "owner": "continuity",
            "start": start,
            "end": end,
            "record": record,
            "classification": "privacy_recognized_noncanonical",
        }

    @staticmethod
    def _privacy_capability_strings(region: bytes):
        """Yield bounded capabilities from one continuity-tag region.

        Raw tokens preserve the existing malformed-tail privacy behavior.
        JSON decoding is restricted to complete JSON string tokens inside
        this already-bounded private candidate. It does not decode arbitrary
        encodings or relax canonical command acceptance.
        """

        seen: set[str] = set()
        for match in re.finditer(rb"cwc_[A-Za-z0-9_-]{43}", region):
            clear = match.group(0).decode("ascii")
            if clear not in seen:
                seen.add(clear)
                yield clear
        for match in _JSON_STRING_TOKEN_RE.finditer(region):
            try:
                decoded = json.loads(match.group(0).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(decoded, str)
                and _CLEAR_CAPABILITY_RE.fullmatch(decoded) is not None
                and decoded not in seen
            ):
                seen.add(decoded)
                yield decoded

    @staticmethod
    def _privacy_location_protected(data: bytes, start: int) -> bool:
        line_start = _line_start(data, start)
        prefix = data[line_start:start]
        if prefix.startswith(b">") or prefix.startswith(b"\t"):
            return True
        if len(prefix) >= 4 and prefix.strip(b" ") == b"":
            return True
        if prefix.strip(b" "):
            return True
        if _line_is_fenced(data, line_start):
            return True
        return False

    def _reject_privacy_attempt(
        self,
        response_bytes: bytes,
        attempt: Mapping[str, Any],
        *,
        response_hash: str,
        client_turn_id: str,
        room_id: str,
        provider_operation_id: str,
        protocol_version: str,
        at: str,
        memory_candidates: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        record = attempt["record"]
        if self._binding_matches(
            record,
            client_turn_id=client_turn_id,
            room_id=room_id,
            provider_operation_id=provider_operation_id,
            protocol_version=protocol_version,
        ):
            self.registry.reject_consumed(
                record,
                response_sha256=response_hash,
                result_code="rejected_noncanonical_current_private_attempt",
                at=at,
            )
            effect = "rejected_consumed"
            state = "rejected_noncanonical_current_private_attempt"
        else:
            self.registry.record_binding_or_replay_failure(
                record,
                response_sha256=response_hash,
                result_code="rejected_noncanonical_wrong_binding",
                at=at,
            )
            effect = "binding_failure_recorded"
            state = "rejected_wrong_capability_binding"
        preceding_memory: list[dict[str, Any]] = []
        cursor = _before_line_break(response_bytes, attempt["start"])
        trailing_end = attempt["start"]
        while True:
            candidate = self._memory_candidate(
                response_bytes,
                cursor,
                trailing_end=trailing_end,
            )
            if candidate is None:
                break
            preceding_memory.append(candidate)
            trailing_end = candidate["start"]
            cursor = _before_line_break(
                response_bytes, candidate["start"]
            )
        all_memory_candidates = [
            *reversed(preceding_memory),
            *memory_candidates,
        ]
        private_range = self._range(
            "continuity",
            attempt["start"],
            attempt["end"],
        )
        ranges = [
            private_range,
            *[
                self._range(
                    "memory",
                    item["start"],
                    item["end"],
                )
                for item in all_memory_candidates
            ],
        ]
        ranges.sort(key=lambda item: item["start"])
        visible = self._remove_ranges(response_bytes, ranges)
        if preceding_memory:
            memory_disposition = "rejected_out_of_order_private_block"
            memory_write = False
        elif not all_memory_candidates:
            memory_disposition = "not_supplied"
            memory_write = False
        elif len(all_memory_candidates) == 1:
            memory_disposition = all_memory_candidates[0]["disposition"]
            memory_write = bool(all_memory_candidates[0]["valid"])
        else:
            memory_disposition = "rejected_duplicate_private_block"
            memory_write = False
        return self._result(
            response_bytes=response_bytes,
            visible=visible,
            ranges=ranges,
            continuity_state=state,
            memory_disposition=memory_disposition,
            continuity_write=False,
            memory_write=memory_write,
            normalized_intent=None,
            validated_command_bundle=None,
            capability_id=record["capability_id"],
            capability_effect=effect,
            memory_candidate=None,
        )

    def _continuity_candidate(
        self, data: bytes, end: int, *, trailing_end: int
    ) -> dict[str, Any] | None:
        start = _line_start(data, end)
        line = data[start:end]
        if (
            not line.startswith(CONTINUITY_OPEN.encode("ascii"))
            or _line_is_fenced(data, start)
        ):
            return None
        prefix = _CAPABILITY_PREFIX.match(line)
        if prefix is None:
            return None
        try:
            clear = prefix.group(1).decode("ascii")
        except UnicodeDecodeError:
            return None
        record = self.registry.lookup_clear(clear)
        if record is None:
            return None
        closed = line.endswith(CONTINUITY_CLOSE.encode("ascii"))
        return {
            "owner": "continuity",
            "start": start,
            "end": trailing_end,
            "candidate_bytes": line,
            "candidate_size": len(line),
            "classification": "closed" if closed else "unterminated",
            "clear_capability": clear,
            "record": record,
        }

    @staticmethod
    def _gate5_durable_operation_context(
        context: Mapping[str, Any],
        intent: Mapping[str, Any],
    ) -> dict[str, Any]:
        offered_items = {
            item["item_id"]: item for item in context["items"]
        }
        create_offers = {
            item["offer_id"]: item for item in context["create_offers"]
        }
        operation_contexts = []
        for operation in intent["semantic_operations"]:
            if operation["operation_kind"] == "create":
                matching = [
                    offer
                    for offer in create_offers.values()
                    if offer["scope"] == operation["scope"]
                    and operation["item_kind"]
                    in offer["allowed_item_kinds"]
                ]
                offered = None
                successor = None
                offer_id = matching[0]["offer_id"]
            else:
                offered = offered_items[operation["item_id"]]
                successor = (
                    offered_items[operation["superseded_by_item_id"]]
                    if operation["operation_kind"] == "supersede"
                    else None
                )
                offer_id = None
            identity = {
                "operation_key": operation["operation_key"],
                "operation_kind": operation["operation_kind"],
                "offer_id": offer_id,
                "offered_item": deepcopy(offered),
                "offered_successor_item": deepcopy(successor),
                "operation_sha256": hashlib.sha256(
                    canonical_json_bytes(operation)
                ).hexdigest(),
                "raw_body_included": False,
            }
            identity["identity_sha256"] = hashlib.sha256(
                canonical_json_bytes(identity)
            ).hexdigest()
            operation_contexts.append(identity)
        binding_context = None
        binding_operation = intent["scope_binding_operation"]
        if binding_operation is not None:
            choice = next(
                item
                for item in context[
                    "provisional_scope_binding_choices"
                ]
                if item["choice_code"]
                == binding_operation["choice_code"]
            )
            binding_context = {
                "operation": deepcopy(binding_operation),
                "offered_choice": deepcopy(choice),
                "raw_body_included": False,
            }
            binding_context["identity_sha256"] = hashlib.sha256(
                canonical_json_bytes(binding_context)
            ).hexdigest()
        body = {
            "operation_contexts": operation_contexts,
            "scope_binding_context": binding_context,
            "raw_body_included": False,
        }
        return {
            **body,
            "context_sha256": hashlib.sha256(
                canonical_json_bytes(body)
            ).hexdigest(),
        }

    def _memory_candidate(
        self, data: bytes, end: int, *, trailing_end: int
    ) -> dict[str, Any] | None:
        start = _line_start(data, end)
        line = data[start:end]
        open_bytes = MEMORY_OPEN.encode("ascii")
        close_bytes = MEMORY_CLOSE.encode("ascii")
        if (
            not line.startswith(open_bytes)
            or not line.endswith(close_bytes)
            or _line_is_fenced(data, start)
        ):
            return None
        inner = line[len(open_bytes) : -len(close_bytes)]
        valid = False
        try:
            decoded = json.loads(
                inner.decode("utf-8"),
                object_pairs_hook=_duplicate_rejecting_object,
            )
            valid = isinstance(decoded, dict)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            valid = False
        return {
            "owner": "memory",
            "start": start,
            "end": trailing_end,
            "candidate_bytes": line,
            "valid": valid,
            "disposition": (
                "delegate_valid_candidate_to_existing_memory_owner"
                if valid
                else "recognized_rejected_invalid_memory"
            ),
        }

    def _decode_canonical_intent(
        self, candidate: bytes
    ) -> dict[str, Any]:
        open_bytes = CONTINUITY_OPEN.encode("ascii")
        close_bytes = CONTINUITY_CLOSE.encode("ascii")
        if not (
            candidate.startswith(open_bytes)
            and candidate.endswith(close_bytes)
        ):
            _fail("malformed_known_capability")
        inner = candidate[len(open_bytes) : -len(close_bytes)]
        try:
            decoded = json.loads(
                inner.decode("utf-8"),
                object_pairs_hook=_duplicate_rejecting_object,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            _fail("malformed_known_capability")
        try:
            normalized = validate_continuity_intent(decoded)
        except HouseContinuityV12ContractError as exc:
            raise CapabilityTerminalParserLocalError(
                exc.error_code
            ) from exc
        if inner != _canonical_intent_bytes(normalized):
            _fail("noncanonical_known_capability_json")
        return normalized

    @staticmethod
    def _binding_matches(
        record: Mapping[str, Any],
        *,
        client_turn_id: str,
        room_id: str,
        provider_operation_id: str,
        protocol_version: str,
    ) -> bool:
        return (
            record["client_turn_id"] == client_turn_id
            and record["room_id"] == room_id
            and record["provider_operation_id"] == provider_operation_id
            and record["protocol_version"] == protocol_version
        )

    @staticmethod
    def _binding_failure_code(
        record: Mapping[str, Any],
        *,
        client_turn_id: str,
        room_id: str,
        provider_operation_id: str,
        protocol_version: str,
    ) -> str:
        if record["client_turn_id"] != client_turn_id:
            return "rejected_wrong_turn_binding"
        if record["room_id"] != room_id:
            return "rejected_wrong_room_binding"
        if record["provider_operation_id"] != provider_operation_id:
            return "rejected_wrong_operation_binding"
        if record["protocol_version"] != protocol_version:
            return "rejected_wrong_protocol_binding"
        return "rejected_capability_binding"

    @staticmethod
    def _schema_failure_state(code: str) -> str:
        if code in {"malformed_known_capability", "duplicate_json_key"}:
            return "rejected_malformed_known_capability"
        if code in {
            "invalid_protocol_version",
            "wrong_protocol_binding",
        }:
            return "rejected_wrong_protocol_binding"
        return "recognized_rejected_schema_invalid"

    def _visible_continuity_state(self, data: bytes, end: int) -> str:
        open_bytes = CONTINUITY_OPEN.encode("ascii")
        if open_bytes not in data:
            return "authorship_not_supplied"
        start = _line_start(data, end)
        line = data[start:end]
        prefix = _CAPABILITY_PREFIX.match(line)
        if (
            prefix is not None
            and line.endswith(CONTINUITY_CLOSE.encode("ascii"))
            and not _line_is_fenced(data, start)
        ):
            try:
                clear = prefix.group(1).decode("ascii")
            except UnicodeDecodeError:
                return "literal_visible"
            if self.registry.lookup_clear(clear) is None:
                return "unknown_capability_literal_visible"
        return "literal_visible"

    @staticmethod
    def _range(owner: str, start: int, end: int) -> dict[str, Any]:
        return {"owner": owner, "start": start, "end": end}

    @staticmethod
    def _remove_ranges(data: bytes, ranges: list[dict[str, Any]]) -> bytes:
        cursor = 0
        pieces = []
        for item in ranges:
            if item["start"] < cursor or item["end"] < item["start"]:
                _fail("overlapping_private_ranges")
            pieces.append(data[cursor : item["start"]])
            cursor = item["end"]
        pieces.append(data[cursor:])
        return b"".join(pieces)

    @staticmethod
    def _result(
        *,
        response_bytes: bytes,
        visible: bytes,
        ranges: list[dict[str, Any]],
        continuity_state: str,
        memory_disposition: str,
        continuity_write: bool,
        memory_write: bool,
        normalized_intent: Mapping[str, Any] | None,
        validated_command_bundle: Mapping[str, Any] | None,
        capability_id: str | None,
        capability_effect: str,
        memory_candidate: bytes | None,
    ) -> dict[str, Any]:
        return {
            "schema_version": PARSE_RESULT_SCHEMA_VERSION,
            "response_sha256": _response_sha256(response_bytes),
            "visible_bytes": visible,
            "visible_sha256": _response_sha256(visible),
            "stripped_private_ranges": deepcopy(ranges),
            "continuity_state": continuity_state,
            "memory_disposition": memory_disposition,
            "continuity_write_permitted": continuity_write,
            "memory_write_permitted": memory_write,
            "any_write_permitted": continuity_write or memory_write,
            "normalized_intent": (
                None
                if normalized_intent is None
                else deepcopy(dict(normalized_intent))
            ),
            "validated_command_bundle": (
                None
                if validated_command_bundle is None
                else deepcopy(dict(validated_command_bundle))
            ),
            "capability_id": capability_id,
            "capability_effect": capability_effect,
            "memory_candidate_bytes": memory_candidate,
            "second_provider_call_count": 0,
            "raw_body_persisted": False,
        }


__all__ = [
    "CapabilityTerminalParserLocalError",
    "HouseContinuityCapabilityRegistryLocal",
    "HouseContinuityTerminalParserLocal",
    "PARSE_RESULT_SCHEMA_VERSION",
    "STORE_SCHEMA_VERSION",
]
