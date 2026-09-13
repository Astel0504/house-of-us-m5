"""Gate-3 synthetic/local participant-evidence authority.

This owner is not imported by a runtime route.  It proves that Astel evidence
comes from an authenticated-client-shaped source, Solen evidence comes from an
applied-outbox-shaped source, reviewed confirmation is one-use, and joint
authorship is accepted only from two independently persisted exact sources.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from house_continuity_v1_2_executable_contracts_v0 import (
    HouseContinuityV12ContractError,
    canonical_astel_semantic_command,
    canonical_json_bytes,
    canonical_sha256,
    normalize_scope,
    validate_astel_confirmation_capability,
    validate_astel_explicit_command,
    validate_astel_reviewed_command_against_capability,
    validate_item_kind_payload,
    validate_joint_attestation,
)
from house_continuity_v1_2_cross_gate_receipts_v1 import (
    CrossGateReceiptError,
    validate_accepted_joint_receipt,
)


STORE_SCHEMA_VERSION = "house_continuity_v1_2_participant_evidence_local_v1"
SEMANTIC_CANDIDATE_SCHEMA_VERSION = (
    "house_continuity_participant_semantic_candidate_v1"
)
ASTEL_SOURCE_SCHEMA_VERSION = "house_continuity_authenticated_astel_source_v1"
SOLEN_SOURCE_SCHEMA_VERSION = "house_continuity_applied_solen_source_v1"
SOLEN_SOURCE_SCHEMA_VERSION_V2 = (
    "house_continuity_applied_solen_source_v2"
)
EVIDENCE_SCHEMA_VERSION = "house_continuity_participant_evidence_v1"
SOLEN_OUTBOX_AUTHORITY_BOUNDARY = (
    "gate5_must_replace_applied_outbox_shaped_fixture_with_exact_durable_owner"
)
_FORBIDDEN_NAMES = {
    "authorization",
    "body",
    "cookie",
    "credential",
    "exact_quote",
    "memory_body",
    "password",
    "private_key",
    "prompt",
    "provider_body",
    "raw_history",
    "secret",
    "token",
    "transcript",
    "vault_body",
}
_CLEAR_CONFIRMATION_CAPABILITY = re.compile(r"cac_[A-Za-z0-9_-]{43}")


class ParticipantEvidenceLocalError(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _fail(code: str) -> None:
    raise ParticipantEvidenceLocalError(code)


def _exact(value: Any, fields: tuple[str, ...], *, code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(fields):
        _fail(code)
    _reject_private(value)
    return dict(value)


def _reject_private(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in _FORBIDDEN_NAMES or any(
                fragment in lowered
                for fragment in (
                    "api_key",
                    "auth_header",
                    "private_path",
                    "raw_chat",
                    "secret_value",
                )
            ):
                _fail("raw_private_or_secret_field_forbidden")
            _reject_private(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_private(nested)


def _identifier(value: Any, *, code: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 180
        or not value[0].isalnum()
        or any(not (character.isalnum() or character in "_.:-") for character in value)
    ):
        _fail(code)
    return value


def _hash(value: Any, *, code: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail(code)
    return value


def _timestamp_value(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        _fail("invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail("invalid_timestamp")
    if parsed.tzinfo != timezone.utc:
        _fail("invalid_timestamp")
    return parsed


def _json(value: Mapping[str, Any]) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _load(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        _fail("stored_shape_invalid")
    return loaded


def validate_semantic_candidate(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "item_id",
            "expected_revision",
            "item_kind",
            "scope",
            "summary",
            "kind_payload",
        ),
        code="invalid_semantic_candidate_shape",
    )
    if raw["schema_version"] != SEMANTIC_CANDIDATE_SCHEMA_VERSION:
        _fail("invalid_semantic_candidate_schema")
    item_id = raw["item_id"]
    if item_id is not None:
        if (
            not isinstance(item_id, str)
            or not item_id.startswith("cws_item_")
            or len(item_id) != 41
        ):
            _fail("invalid_semantic_candidate_item")
    revision = raw["expected_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        _fail("invalid_semantic_candidate_revision")
    if (item_id is None) != (revision == 0):
        _fail("semantic_candidate_target_mismatch")
    item_kind = raw["item_kind"]
    try:
        scope = normalize_scope(raw["scope"], path="participant_semantic_candidate")
        payload = validate_item_kind_payload(item_kind, raw["kind_payload"])
    except HouseContinuityV12ContractError as exc:
        raise ParticipantEvidenceLocalError(exc.error_code) from exc
    summary = raw["summary"]
    if not isinstance(summary, str) or not summary or len(summary) > 640:
        _fail("invalid_semantic_candidate_summary")
    return {
        "schema_version": SEMANTIC_CANDIDATE_SCHEMA_VERSION,
        "item_id": item_id,
        "expected_revision": revision,
        "item_kind": item_kind,
        "scope": scope,
        "summary": summary,
        "kind_payload": payload,
    }


def semantic_candidate_sha256(candidate: Mapping[str, Any]) -> str:
    normalized = validate_semantic_candidate(candidate)
    return canonical_sha256(
        {
            "item_kind": normalized["item_kind"],
            "scope": normalized["scope"],
            "summary": normalized["summary"],
            "kind_payload": normalized["kind_payload"],
        }
    )


def _evidence_id(participant: str, source_event_id: str, semantic_sha: str) -> str:
    seed = canonical_sha256(
        {
            "participant": participant,
            "semantic_sha256": semantic_sha,
            "source_event_id": source_event_id,
            "versioned_namespace": EVIDENCE_SCHEMA_VERSION,
        }
    )
    return f"cws_pev_{seed[:32]}"


def _evidence_record(
    *,
    participant: str,
    source_event_id: str,
    source_kind: str,
    source_receipt_sha256: str,
    command_owner: str,
    candidate: Mapping[str, Any],
    created_at: str,
    semantic_snapshot_complete: bool,
) -> dict[str, Any]:
    normalized = validate_semantic_candidate(candidate)
    semantic_sha = semantic_candidate_sha256(normalized)
    scope_sha = canonical_sha256(normalized["scope"])
    record = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_id": _evidence_id(participant, source_event_id, semantic_sha),
        "event_id": source_event_id,
        "participant": participant,
        "content_sha256": semantic_sha,
        "scope_sha256": scope_sha,
        "item_id": normalized["item_id"],
        "expected_revision": normalized["expected_revision"],
        "item_kind": normalized["item_kind"],
        "source_kind": source_kind,
        "source_receipt_sha256": source_receipt_sha256,
        "command_owner": command_owner,
        "semantic_snapshot_complete": semantic_snapshot_complete,
        "created_at": created_at,
        "evidence_sha256": "",
    }
    record["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in record.items() if key != "evidence_sha256"}
    )
    return record


def _bounded_source_receipt(
    *,
    source_event_id: str,
    source_kind: str,
    participant: str,
    room_id: str,
    client_turn_id: str,
    source_receipt_sha256: str,
    semantic_sha256: str,
    command_sha256: str,
    created_at: str,
    operation_kind: str,
    reason_code: str | None,
    successor_item_id: str | None,
    provider_operation_id: str | None = None,
    outbox_bundle_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "house_continuity_participant_source_receipt_v1",
        "source_event_id": source_event_id,
        "source_kind": source_kind,
        "participant": participant,
        "room_id": room_id,
        "client_turn_id": client_turn_id,
        "source_receipt_sha256": source_receipt_sha256,
        "semantic_sha256": semantic_sha256,
        "command_sha256": command_sha256,
        "operation_kind": operation_kind,
        "reason_code": reason_code,
        "successor_item_id": successor_item_id,
        "provider_operation_id": provider_operation_id,
        "outbox_bundle_id": outbox_bundle_id,
        "created_at": created_at,
        "raw_body_included": False,
        "clear_capability_stored": False,
    }


class HouseContinuityParticipantEvidenceLocal:
    def __init__(
        self,
        root: str | Path,
        *,
        synthetic_only: bool,
        working_set_store: Any | None = None,
    ):
        if synthetic_only is not True:
            _fail("synthetic_only_required")
        self.root = Path(root).resolve()
        self._working_set_store = working_set_store
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / "participant_evidence_local.sqlite3"
        self._connection = sqlite3.connect(str(self.database_path))
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS store_meta(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS confirmation_capabilities(
              confirmation_capability_id TEXT PRIMARY KEY,
              capability_sha256 TEXT NOT NULL UNIQUE,
              state TEXT NOT NULL,
              capability_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_events(
              source_event_id TEXT PRIMARY KEY,
              participant TEXT NOT NULL,
              source_kind TEXT NOT NULL,
              source_receipt_sha256 TEXT NOT NULL,
              source_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS participant_evidence(
              evidence_id TEXT PRIMARY KEY,
              event_id TEXT NOT NULL UNIQUE,
              participant TEXT NOT NULL,
              content_sha256 TEXT NOT NULL,
              scope_sha256 TEXT NOT NULL,
              item_id TEXT,
              expected_revision INTEGER NOT NULL,
              evidence_sha256 TEXT NOT NULL,
              evidence_json TEXT NOT NULL,
              FOREIGN KEY(event_id) REFERENCES source_events(source_event_id)
            );
            CREATE TABLE IF NOT EXISTS joint_attestations(
              attestation_id TEXT PRIMARY KEY,
              idempotency_key TEXT NOT NULL UNIQUE,
              joint_act_sha256 TEXT NOT NULL UNIQUE,
              attestation_sha256 TEXT NOT NULL UNIQUE,
              item_id TEXT NOT NULL,
              expected_revision INTEGER NOT NULL,
              astel_evidence_id TEXT NOT NULL,
              solen_evidence_id TEXT NOT NULL,
              attestation_json TEXT NOT NULL,
              FOREIGN KEY(astel_evidence_id) REFERENCES participant_evidence(evidence_id),
              FOREIGN KEY(solen_evidence_id) REFERENCES participant_evidence(evidence_id)
            );
            CREATE TABLE IF NOT EXISTS accepted_joint_receipts(
              receipt_id TEXT PRIMARY KEY,
              attestation_id TEXT NOT NULL UNIQUE,
              idempotency_identity TEXT NOT NULL UNIQUE,
              receipt_sha256 TEXT NOT NULL UNIQUE,
              receipt_json TEXT NOT NULL,
              FOREIGN KEY(attestation_id) REFERENCES joint_attestations(attestation_id)
            );
            CREATE TABLE IF NOT EXISTS idempotency_receipts(
              idempotency_key TEXT PRIMARY KEY,
              command_sha256 TEXT NOT NULL,
              receipt_json TEXT NOT NULL
            );
            """
        )
        self._connection.execute(
            "INSERT OR IGNORE INTO store_meta(key,value) VALUES(?,?)",
            ("schema_version", STORE_SCHEMA_VERSION),
        )
        self._connection.commit()
        metadata = dict(
            self._connection.execute("SELECT key,value FROM store_meta")
        )
        if metadata != {"schema_version": STORE_SCHEMA_VERSION}:
            self._connection.close()
            _fail("participant_store_metadata_mismatch")

    def close(self) -> None:
        self._connection.close()

    def issue_confirmation_capability(
        self, capability: Mapping[str, Any]
    ) -> dict[str, Any]:
        try:
            normalized = validate_astel_confirmation_capability(capability)
        except HouseContinuityV12ContractError as exc:
            raise ParticipantEvidenceLocalError(exc.error_code) from exc
        if normalized["state"] != "issued":
            _fail("confirmation_capability_must_begin_issued")
        row = self._connection.execute(
            "SELECT capability_json FROM confirmation_capabilities"
            " WHERE confirmation_capability_id=?",
            (normalized["confirmation_capability_id"],),
        ).fetchone()
        if row is not None:
            existing = _load(row["capability_json"])
            if existing != normalized:
                _fail("confirmation_capability_identity_conflict")
            return existing
        with self._connection:
            self._connection.execute(
                "INSERT INTO confirmation_capabilities VALUES(?,?,?,?)",
                (
                    normalized["confirmation_capability_id"],
                    normalized["capability_sha256"],
                    "issued",
                    _json(normalized),
                ),
            )
        return normalized

    def _put_source_and_evidence(
        self,
        *,
        source: Mapping[str, Any],
        evidence: Mapping[str, Any],
        idempotency_key: str,
        capability_consumption: tuple[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        command_sha = canonical_sha256(
            {"source": source, "evidence": evidence}
        )
        prior = self._connection.execute(
            "SELECT command_sha256,receipt_json FROM idempotency_receipts"
            " WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if prior is not None:
            if prior["command_sha256"] != command_sha:
                _fail("participant_evidence_idempotency_conflict")
            return _load(prior["receipt_json"])
        receipt = {
            "schema_version": "house_continuity_participant_evidence_receipt_v1",
            "evidence_id": evidence["evidence_id"],
            "event_id": evidence["event_id"],
            "participant": evidence["participant"],
            "content_sha256": evidence["content_sha256"],
            "evidence_sha256": evidence["evidence_sha256"],
            "committed": True,
        }
        with self._connection:
            if capability_consumption is not None:
                capability_id, consumed = capability_consumption
                changed = self._connection.execute(
                    "UPDATE confirmation_capabilities"
                    " SET state='consumed', capability_json=?"
                    " WHERE confirmation_capability_id=? AND state='issued'",
                    (_json(consumed), capability_id),
                ).rowcount
                if changed != 1:
                    _fail("confirmation_capability_replayed")
            self._connection.execute(
                "INSERT INTO source_events VALUES(?,?,?,?,?)",
                (
                    source["source_event_id"],
                    evidence["participant"],
                    evidence["source_kind"],
                    evidence["source_receipt_sha256"],
                    _json(source),
                ),
            )
            self._connection.execute(
                "INSERT INTO participant_evidence VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    evidence["evidence_id"],
                    evidence["event_id"],
                    evidence["participant"],
                    evidence["content_sha256"],
                    evidence["scope_sha256"],
                    evidence["item_id"],
                    evidence["expected_revision"],
                    evidence["evidence_sha256"],
                    _json(evidence),
                ),
            )
            self._connection.execute(
                "INSERT INTO idempotency_receipts VALUES(?,?,?)",
                (idempotency_key, command_sha, _json(receipt)),
            )
        return receipt

    def _current_working_set_candidate(
        self, item_id: str, expected_revision: int
    ) -> dict[str, Any]:
        if self._working_set_store is None:
            _fail("working_set_revision_fence_required")
        current = self._working_set_store.read_item(item_id)
        if current is None:
            _fail("astel_working_set_item_unavailable")
        if current["revision"] != expected_revision:
            _fail("astel_working_set_revision_mismatch")
        return validate_semantic_candidate(
            {
                "schema_version": SEMANTIC_CANDIDATE_SCHEMA_VERSION,
                "item_id": current["item_id"],
                "expected_revision": current["revision"],
                "item_kind": current["item_kind"],
                "scope": {
                    "scope_kind": current["scope_kind"],
                    "room_id": current["room_id"],
                    "project_id": current["project_id"],
                    "thread_id": current["thread_id"],
                },
                "summary": current["summary"],
                "kind_payload": current["kind_payload"],
            }
        )

    def _validate_astel_candidate(
        self,
        command: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized = validate_semantic_candidate(candidate)
        if command["operation_kind"] == "create":
            expected = {
                "item_id": None,
                "expected_revision": 0,
                "item_kind": command["item_kind"],
                "scope": command["scope"],
                "summary": command["summary"],
                "kind_payload": command["kind_payload"],
            }
            if any(normalized[key] != value for key, value in expected.items()):
                _fail("astel_source_candidate_mismatch")
            return normalized
        if (
            command["item_id"] != normalized["item_id"]
            or command["expected_revision"] != normalized["expected_revision"]
        ):
            _fail("astel_source_target_revision_mismatch")
        current = self._current_working_set_candidate(
            command["item_id"], command["expected_revision"]
        )
        if normalized != current:
            _fail("astel_candidate_not_current_precommand_snapshot")
        return normalized

    def accept_astel_direct(
        self, source: Mapping[str, Any]
    ) -> dict[str, Any]:
        raw = _exact(
            source,
            (
                "schema_version",
                "source_event_id",
                "source_kind",
                "authentication_receipt_sha256",
                "authenticated_participant",
                "client_turn_id",
                "room_id",
                "command",
                "semantic_candidate",
                "created_at",
            ),
            code="invalid_astel_source_shape",
        )
        if (
            raw["schema_version"] != ASTEL_SOURCE_SCHEMA_VERSION
            or raw["source_kind"] != "authenticated_structured_action"
            or raw["authenticated_participant"] != "astel"
        ):
            _fail("invalid_astel_source_authority")
        try:
            command = validate_astel_explicit_command(raw["command"])
        except HouseContinuityV12ContractError as exc:
            raise ParticipantEvidenceLocalError(exc.error_code) from exc
        if command["confirmation_mode"] != "direct_structured_action":
            _fail("direct_astel_source_requires_direct_command")
        if (
            command["client_turn_id"] != raw["client_turn_id"]
            or command["room_id"] != raw["room_id"]
        ):
            _fail("astel_source_turn_room_mismatch")
        candidate = self._validate_astel_candidate(
            command, raw["semantic_candidate"]
        )
        snapshot_complete = True
        created_at = raw["created_at"]
        _timestamp_value(created_at)
        source_event_id = _identifier(
            raw["source_event_id"], code="invalid_astel_source_event_id"
        )
        receipt_hash = _hash(
            raw["authentication_receipt_sha256"],
            code="invalid_astel_authentication_receipt",
        )
        evidence = _evidence_record(
            participant="astel",
            source_event_id=source_event_id,
            source_kind=raw["source_kind"],
            source_receipt_sha256=receipt_hash,
            command_owner="house_continuity_astel_explicit_command_v1",
            candidate=candidate,
            created_at=created_at,
            semantic_snapshot_complete=snapshot_complete,
        )
        stored_source = _bounded_source_receipt(
            source_event_id=source_event_id,
            source_kind=raw["source_kind"],
            participant="astel",
            room_id=raw["room_id"],
            client_turn_id=raw["client_turn_id"],
            source_receipt_sha256=receipt_hash,
            semantic_sha256=evidence["content_sha256"],
            command_sha256=canonical_sha256(
                canonical_astel_semantic_command(command)
            ),
            created_at=created_at,
            operation_kind=command["operation_kind"],
            reason_code=command["reason_code"],
            successor_item_id=command["successor_item_id"],
        )
        return self._put_source_and_evidence(
            source=stored_source,
            evidence=evidence,
            idempotency_key=command["idempotency_key"],
        )

    def accept_astel_reviewed(
        self, source: Mapping[str, Any]
    ) -> dict[str, Any]:
        raw = _exact(
            source,
            (
                "schema_version",
                "source_event_id",
                "source_kind",
                "authentication_receipt_sha256",
                "authenticated_participant",
                "client_turn_id",
                "room_id",
                "command",
                "semantic_candidate",
                "created_at",
            ),
            code="invalid_astel_source_shape",
        )
        if (
            raw["schema_version"] != ASTEL_SOURCE_SCHEMA_VERSION
            or raw["source_kind"] != "authenticated_reviewed_confirmation"
            or raw["authenticated_participant"] != "astel"
        ):
            _fail("invalid_astel_source_authority")
        clear = raw["command"].get("confirmation_capability")
        if (
            not isinstance(clear, str)
            or _CLEAR_CONFIRMATION_CAPABILITY.fullmatch(clear) is None
        ):
            _fail("invalid_confirmation_capability")
        try:
            clear_sha = hashlib.sha256(clear.encode("ascii")).hexdigest()
        except UnicodeEncodeError:
            _fail("invalid_confirmation_capability")
        row = self._connection.execute(
            "SELECT confirmation_capability_id,state,capability_json"
            " FROM confirmation_capabilities WHERE capability_sha256=?",
            (clear_sha,),
        ).fetchone()
        if row is None:
            _fail("unknown_confirmation_capability")
        if row["state"] != "issued":
            capability = _load(row["capability_json"])
            capability["replay_attempt_count"] += 1
            try:
                capability = validate_astel_confirmation_capability(capability)
            except HouseContinuityV12ContractError as exc:
                raise ParticipantEvidenceLocalError(exc.error_code) from exc
            with self._connection:
                self._connection.execute(
                    "UPDATE confirmation_capabilities SET capability_json=?"
                    " WHERE confirmation_capability_id=?",
                    (_json(capability), row["confirmation_capability_id"]),
                )
            _fail("confirmation_capability_replayed")
        capability = _load(row["capability_json"])
        try:
            validated = validate_astel_reviewed_command_against_capability(
                raw["command"], capability
            )
        except HouseContinuityV12ContractError as exc:
            raise ParticipantEvidenceLocalError(exc.error_code) from exc
        command = validated["command"]
        if (
            command["client_turn_id"] != raw["client_turn_id"]
            or command["room_id"] != raw["room_id"]
        ):
            _fail("astel_source_turn_room_mismatch")
        created_at = raw["created_at"]
        created_value = _timestamp_value(created_at)
        if not (
            _timestamp_value(capability["issued_at"])
            <= created_value
            <= _timestamp_value(capability["expires_at"])
        ):
            _fail("confirmation_capability_expired")
        semantic_command = canonical_astel_semantic_command(command)
        candidate = self._validate_astel_candidate(
            semantic_command, raw["semantic_candidate"]
        )
        source_event_id = _identifier(
            raw["source_event_id"], code="invalid_astel_source_event_id"
        )
        receipt_hash = _hash(
            raw["authentication_receipt_sha256"],
            code="invalid_astel_authentication_receipt",
        )
        evidence = _evidence_record(
            participant="astel",
            source_event_id=source_event_id,
            source_kind=raw["source_kind"],
            source_receipt_sha256=receipt_hash,
            command_owner="house_continuity_astel_explicit_command_v1",
            candidate=candidate,
            created_at=created_at,
            semantic_snapshot_complete=True,
        )
        stored_source = _bounded_source_receipt(
            source_event_id=source_event_id,
            source_kind=raw["source_kind"],
            participant="astel",
            room_id=raw["room_id"],
            client_turn_id=raw["client_turn_id"],
            source_receipt_sha256=receipt_hash,
            semantic_sha256=evidence["content_sha256"],
            command_sha256=canonical_sha256(semantic_command),
            created_at=created_at,
            operation_kind=command["operation_kind"],
            reason_code=command["reason_code"],
            successor_item_id=command["successor_item_id"],
        )
        consumed = dict(capability)
        consumed["state"] = "consumed"
        consumed["consumed_at"] = created_at
        try:
            consumed = validate_astel_confirmation_capability(consumed)
        except HouseContinuityV12ContractError as exc:
            raise ParticipantEvidenceLocalError(exc.error_code) from exc
        return self._put_source_and_evidence(
            source=stored_source,
            evidence=evidence,
            idempotency_key=command["idempotency_key"],
            capability_consumption=(
                capability["confirmation_capability_id"],
                consumed,
            ),
        )

    def accept_solen_applied(
        self, source: Mapping[str, Any]
    ) -> dict[str, Any]:
        v2 = (
            isinstance(source, Mapping)
            and source.get("schema_version")
            == SOLEN_SOURCE_SCHEMA_VERSION_V2
        )
        extra_fields = (
            (
                "operation_kind",
                "reason_code",
                "successor_item_id",
                "semantic_candidate_sha256",
                "application_receipt_id",
                "application_receipt_sha256",
                "terminal_applied_receipt_id",
            )
            if v2
            else ()
        )
        raw = _exact(
            source,
            (
                "schema_version",
                "source_event_id",
                "source_kind",
                "participant_id",
                "authorship_kind",
                "command_owner",
                "client_turn_id",
                "room_id",
                "provider_operation_id",
                "outbox_bundle_id",
                "outbox_state",
                "outbox_applied_receipt_sha256",
                "semantic_candidate",
                "created_at",
                *extra_fields,
            ),
            code="invalid_solen_source_shape",
        )
        if (
            raw["schema_version"]
            not in {
                SOLEN_SOURCE_SCHEMA_VERSION,
                SOLEN_SOURCE_SCHEMA_VERSION_V2,
            }
            or raw["source_kind"] != "applied_solen_outbox"
            or raw["participant_id"] != "solen"
            or raw["authorship_kind"] != "solen_explicit"
            or raw["command_owner"]
            != "house_talk_continuity_authorship_intent_v1"
            or raw["outbox_state"] != "applied"
        ):
            _fail("invalid_solen_source_authority")
        for field in (
            "source_event_id",
            "client_turn_id",
            "room_id",
            "provider_operation_id",
            "outbox_bundle_id",
        ):
            _identifier(raw[field], code=f"invalid_{field}")
        receipt_hash = _hash(
            raw["outbox_applied_receipt_sha256"],
            code="invalid_solen_applied_receipt",
        )
        candidate = validate_semantic_candidate(raw["semantic_candidate"])
        semantic_sha = semantic_candidate_sha256(candidate)
        if v2:
            if (
                raw["semantic_candidate_sha256"] != semantic_sha
                or raw["terminal_applied_receipt_id"] is None
                or raw["application_receipt_id"] is None
            ):
                _fail("invalid_solen_applied_semantic_binding")
            _identifier(
                raw["terminal_applied_receipt_id"],
                code="invalid_solen_terminal_receipt_id",
            )
            _identifier(
                raw["application_receipt_id"],
                code="invalid_solen_application_receipt_id",
            )
            _hash(
                raw["application_receipt_sha256"],
                code="invalid_solen_application_receipt",
            )
        created_at = raw["created_at"]
        _timestamp_value(created_at)
        evidence = _evidence_record(
            participant="solen",
            source_event_id=raw["source_event_id"],
            source_kind=raw["source_kind"],
            source_receipt_sha256=receipt_hash,
            command_owner=raw["command_owner"],
            candidate=candidate,
            created_at=created_at,
            semantic_snapshot_complete=True,
        )
        stored_source = _bounded_source_receipt(
            source_event_id=raw["source_event_id"],
            source_kind=raw["source_kind"],
            participant="solen",
            room_id=raw["room_id"],
            client_turn_id=raw["client_turn_id"],
            source_receipt_sha256=receipt_hash,
            semantic_sha256=evidence["content_sha256"],
            command_sha256=canonical_sha256(
                {
                    "authorship_kind": raw["authorship_kind"],
                    "command_owner": raw["command_owner"],
                    "outbox_bundle_id": raw["outbox_bundle_id"],
                    "semantic_sha256": evidence["content_sha256"],
                    **(
                        {
                            "operation_kind": raw["operation_kind"],
                            "reason_code": raw["reason_code"],
                            "successor_item_id": raw[
                                "successor_item_id"
                            ],
                            "application_receipt_id": raw[
                                "application_receipt_id"
                            ],
                            "application_receipt_sha256": raw[
                                "application_receipt_sha256"
                            ],
                            "terminal_applied_receipt_id": raw[
                                "terminal_applied_receipt_id"
                            ],
                            "terminal_applied_receipt_sha256": (
                                receipt_hash
                            ),
                        }
                        if v2
                        else {}
                    ),
                }
            ),
            created_at=created_at,
            operation_kind=(
                raw["operation_kind"]
                if v2
                else "semantic_attestation"
            ),
            reason_code=raw["reason_code"] if v2 else None,
            successor_item_id=(
                raw["successor_item_id"] if v2 else None
            ),
            provider_operation_id=raw["provider_operation_id"],
            outbox_bundle_id=raw["outbox_bundle_id"],
        )
        idempotency_key = (
            "solen-applied:"
            + raw["outbox_bundle_id"]
            + ":"
            + evidence["content_sha256"]
        )
        return self._put_source_and_evidence(
            source=stored_source,
            evidence=evidence,
            idempotency_key=idempotency_key,
        )

    def read_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT evidence_json FROM participant_evidence WHERE evidence_id=?",
            (evidence_id,),
        ).fetchone()
        return None if row is None else _load(row["evidence_json"])

    def attest_joint(self, attestation: Mapping[str, Any]) -> dict[str, Any]:
        try:
            normalized = validate_joint_attestation(attestation)
        except HouseContinuityV12ContractError as exc:
            raise ParticipantEvidenceLocalError(exc.error_code) from exc
        attestation_sha = canonical_sha256(normalized)
        prior = self._connection.execute(
            "SELECT attestation_sha256,attestation_json FROM joint_attestations"
            " WHERE idempotency_key=?",
            (normalized["idempotency_key"],),
        ).fetchone()
        if prior is not None:
            if prior["attestation_sha256"] != attestation_sha:
                _fail("joint_attestation_idempotency_conflict")
            return _load(prior["attestation_json"])
        astel = self.read_evidence(normalized["astel_evidence"]["evidence_id"])
        solen = self.read_evidence(normalized["solen_evidence"]["evidence_id"])
        if astel is None or solen is None:
            _fail("joint_source_evidence_unavailable")
        for expected, stored in (
            (normalized["astel_evidence"], astel),
            (normalized["solen_evidence"], solen),
        ):
            if any(
                expected[field] != stored[field]
                for field in ("evidence_id", "event_id", "participant", "content_sha256")
            ):
                _fail("joint_source_evidence_mismatch")
        if (
            astel["source_kind"]
            not in {
                "authenticated_structured_action",
                "authenticated_reviewed_confirmation",
            }
            or astel["command_owner"]
            != "house_continuity_astel_explicit_command_v1"
            or solen["source_kind"] != "applied_solen_outbox"
            or solen["command_owner"]
            != "house_talk_continuity_authorship_intent_v1"
        ):
            _fail("joint_source_authority_mismatch")
        if not (
            astel["semantic_snapshot_complete"]
            and solen["semantic_snapshot_complete"]
        ):
            _fail("joint_semantic_snapshot_incomplete")
        if astel["item_kind"] != solen["item_kind"]:
            _fail("joint_item_kind_mismatch")
        if (
            astel["item_id"] != normalized["item_id"]
            or solen["item_id"] != normalized["item_id"]
            or astel["expected_revision"] != normalized["expected_revision"]
            or solen["expected_revision"] != normalized["expected_revision"]
        ):
            _fail("joint_target_revision_mismatch")
        if (
            astel["scope_sha256"] != normalized["scope_sha256"]
            or solen["scope_sha256"] != normalized["scope_sha256"]
        ):
            _fail("joint_scope_mismatch")
        if self._working_set_store is None:
            _fail("working_set_revision_fence_required")
        current_item = self._working_set_store.read_item(normalized["item_id"])
        if current_item is None:
            _fail("joint_working_set_item_unavailable")
        current_scope = {
            "scope_kind": current_item["scope_kind"],
            "room_id": current_item["room_id"],
            "project_id": current_item["project_id"],
            "thread_id": current_item["thread_id"],
        }
        current_candidate = validate_semantic_candidate(
            {
                "schema_version": SEMANTIC_CANDIDATE_SCHEMA_VERSION,
                "item_id": current_item["item_id"],
                "expected_revision": current_item["revision"],
                "item_kind": current_item["item_kind"],
                "scope": current_scope,
                "summary": current_item["summary"],
                "kind_payload": current_item["kind_payload"],
            }
        )
        if (
            current_item["revision"] != normalized["expected_revision"]
            or semantic_candidate_sha256(current_candidate)
            != normalized["canonical_semantic_sha256"]
            or canonical_sha256(current_scope) != normalized["scope_sha256"]
        ):
            _fail("joint_working_set_cas_mismatch")
        joint_act_sha = canonical_sha256(
            {
                "item_id": normalized["item_id"],
                "expected_revision": normalized["expected_revision"],
                "canonical_semantic_sha256": normalized[
                    "canonical_semantic_sha256"
                ],
                "scope_sha256": normalized["scope_sha256"],
                "astel_evidence": normalized["astel_evidence"],
                "solen_evidence": normalized["solen_evidence"],
            }
        )
        duplicate = self._connection.execute(
            "SELECT 1 FROM joint_attestations"
            " WHERE attestation_id=? OR joint_act_sha256=?",
            (normalized["attestation_id"], joint_act_sha),
        ).fetchone()
        if duplicate is not None:
            _fail("duplicate_joint_attestation_identity")
        receipt = {
            "schema_version": "house_continuity_accepted_joint_receipt_v1",
            "receipt_id": (
                "cws_jrc_"
                + canonical_sha256(
                    {
                        "attestation_id": normalized["attestation_id"],
                        "idempotency_identity": normalized[
                            "idempotency_key"
                        ],
                        "versioned_namespace": (
                            "house_continuity_accepted_joint_receipt_v1"
                        ),
                    }
                )[:32]
            ),
            "attestation_id": normalized["attestation_id"],
            "attestation_sha256": attestation_sha,
            "astel_evidence_id": astel["evidence_id"],
            "astel_event_id": astel["event_id"],
            "astel_content_sha256": astel["content_sha256"],
            "solen_evidence_id": solen["evidence_id"],
            "solen_event_id": solen["event_id"],
            "solen_content_sha256": solen["content_sha256"],
            "item_id": normalized["item_id"],
            "expected_revision": normalized["expected_revision"],
            "scope_sha256": normalized["scope_sha256"],
            "canonical_semantic_sha256": normalized[
                "canonical_semantic_sha256"
            ],
            "idempotency_identity": normalized["idempotency_key"],
            "committed_at": normalized["created_at"],
            "durably_committed": True,
            "raw_body_included": False,
            "receipt_sha256": "",
        }
        receipt["receipt_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in receipt.items()
                if key != "receipt_sha256"
            }
        )
        try:
            receipt = validate_accepted_joint_receipt(receipt)
        except CrossGateReceiptError as exc:
            raise ParticipantEvidenceLocalError(exc.error_code) from exc
        with self._connection:
            self._connection.execute(
                "INSERT INTO joint_attestations VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    normalized["attestation_id"],
                    normalized["idempotency_key"],
                    joint_act_sha,
                    attestation_sha,
                    normalized["item_id"],
                    normalized["expected_revision"],
                    astel["evidence_id"],
                    solen["evidence_id"],
                    _json(normalized),
                ),
            )
            self._connection.execute(
                "INSERT INTO accepted_joint_receipts VALUES(?,?,?,?,?)",
                (
                    receipt["receipt_id"],
                    receipt["attestation_id"],
                    receipt["idempotency_identity"],
                    receipt["receipt_sha256"],
                    _json(receipt),
                ),
            )
        return normalized

    def read_accepted_joint_receipt(
        self, attestation_id: str
    ) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT receipt_json FROM accepted_joint_receipts"
            " WHERE attestation_id=?",
            (attestation_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            return validate_accepted_joint_receipt(
                _load(row["receipt_json"])
            )
        except CrossGateReceiptError as exc:
            raise ParticipantEvidenceLocalError(exc.error_code) from exc


__all__ = [
    "ASTEL_SOURCE_SCHEMA_VERSION",
    "EVIDENCE_SCHEMA_VERSION",
    "HouseContinuityParticipantEvidenceLocal",
    "ParticipantEvidenceLocalError",
    "SEMANTIC_CANDIDATE_SCHEMA_VERSION",
    "SOLEN_SOURCE_SCHEMA_VERSION",
    "SOLEN_OUTBOX_AUTHORITY_BOUNDARY",
    "semantic_candidate_sha256",
    "validate_semantic_candidate",
]
