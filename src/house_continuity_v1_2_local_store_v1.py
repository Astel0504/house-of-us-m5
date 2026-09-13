"""Canonical Continuity V1.2 event store for local proof and the M5 candidate.

Legacy callers remain explicitly ``synthetic_only=True``.  M5 uses the same
event owner with a distinct fail-closed production-candidate schema marker;
the default-off runtime does not create or open that store.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from house_continuity_v1_2_executable_contracts_v0 import (
    HouseContinuityV12ContractError,
    canonical_json_bytes,
    canonical_sha256,
    validate_event_chains,
    validate_joint_attestation,
    validate_outbox_bundle,
    validate_outbox_transition,
    validate_scope_binding,
    validate_scope_binding_event,
    validate_unit_coverage,
    validate_working_set_event,
    validate_working_set_item,
)
from house_continuity_v1_2_cross_gate_receipts_v1 import (
    CrossGateReceiptError,
    validate_accepted_joint_receipt,
)


STORE_SCHEMA_VERSION = "house_continuity_v1_2_local_store_v2"
PRODUCTION_CANDIDATE_STORE_SCHEMA_VERSION = (
    "house_continuity_v1_2_production_candidate_store_v1"
)
ATOMIC_BUNDLE_RECEIPT_SCHEMA_VERSION = (
    "house_continuity_atomic_bundle_application_receipt_v1"
)
PROJECTION_LINEAGE_SCHEMA_VERSION = (
    "house_continuity_projection_lineage_v1"
)
LEGACY_ITEM_SCHEMA_VERSION = "house_continuity_working_set_item_v1_1"
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_STORE_ID_PREFIX = "cws_store_"
_PROJECTION_LINEAGE_STATE = "non_authoritative"
_CONFLICT_REASON_CODES = frozenset(
    {
        "explicit_equal_agency_conflict",
        "semantic_incompatibility",
        "stale_revision_conflict",
        "successor_incompatibility",
    }
)
_ACTOR_REFS = {
    "solen_explicit": "house_talk_continuity_authorship_intent_v1",
    "astel_explicit": "house_continuity_astel_explicit_command_v1",
    "joint_explicit": "house_continuity_joint_authorship_attestation_v1",
    "structured_client_event": "house_continuity_structured_client_event_v1",
    "structured_tool_event": "house_continuity_structured_tool_event_v1",
}
_DETERMINISTIC_ACTOR_REFS = {
    "expire": "house_continuity_expiry_v1",
    "mark_cleanup_eligible": "house_continuity_cleanup_v1",
    "conflict_recorded": "house_continuity_parallel_conflict_v1",
    "scope_rebind_reference": "house_continuity_scope_reference_v1",
}

_ITEM_IMMUTABLE_FIELDS = frozenset(
    {
        "schema_version",
        "item_id",
        "creation_seed_sha256",
        "scope_kind",
        "room_id",
        "project_id",
        "thread_id",
        "item_kind",
        "created_at",
        "provider_visible_eligible",
        "memory_vault_truth",
        "exact_evidence",
        "self_state",
        "action_permission",
        "raw_history_included",
    }
)
_REVISION_FIELDS = frozenset(
    {
        "revision",
        "base_event_id",
        "idempotency_key",
        "updated_at",
    }
)
_AUTHORSHIP_FIELDS = frozenset(
    {
        "authorship_kind",
        "author_participants",
        "semantic_authority_code",
        "command_owner",
        "authorship_evidence_refs",
    }
)
_PROVENANCE_FIELDS = frozenset(
    {
        "source_turn_ids",
        "source_room_ids",
        "source_operation_ids",
        "source_proposal_ids",
        "exact_anchor_refs",
    }
)
_FRESHNESS_FIELDS = frozenset(
    {
        "last_confirmed_at",
        "fresh_until",
        "aging_after",
        "dormant_after",
        "expires_at",
    }
)
_PATCH_ALLOWLISTS = {
    "create": None,
    "confirm": (
        _REVISION_FIELDS
        | _AUTHORSHIP_FIELDS
        | _PROVENANCE_FIELDS
        | _FRESHNESS_FIELDS
    ),
    "revise": (
        _REVISION_FIELDS
        | _AUTHORSHIP_FIELDS
        | _PROVENANCE_FIELDS
        | _FRESHNESS_FIELDS
        | {"summary", "kind_payload", "content_sha256"}
    ),
    "resolve": (
        _REVISION_FIELDS
        | _AUTHORSHIP_FIELDS
        | _PROVENANCE_FIELDS
        | {
            "lifecycle_state",
            "resolved_at",
            "resolution_reason_code",
        }
    ),
    "supersede": (
        _REVISION_FIELDS
        | _AUTHORSHIP_FIELDS
        | _PROVENANCE_FIELDS
        | {
            "lifecycle_state",
            "superseded_by_item_id",
            "supersedes_item_ids",
        }
    ),
    "abandon": (
        _REVISION_FIELDS
        | _AUTHORSHIP_FIELDS
        | _PROVENANCE_FIELDS
        | {
            "lifecycle_state",
            "abandoned_at",
            "abandonment_reason_code",
        }
    ),
    "expire": _REVISION_FIELDS | {"lifecycle_state"},
    "reopen": (
        _REVISION_FIELDS
        | _AUTHORSHIP_FIELDS
        | _PROVENANCE_FIELDS
        | _FRESHNESS_FIELDS
        | {
            "lifecycle_state",
            "resolved_at",
            "abandoned_at",
            "resolution_reason_code",
            "abandonment_reason_code",
            "reopens_item_id",
        }
    ),
    "attest_joint": _REVISION_FIELDS | _AUTHORSHIP_FIELDS | _PROVENANCE_FIELDS,
    "mark_cleanup_eligible": (
        _REVISION_FIELDS | {"cleanup_state", "cleanup_eligible_at"}
    ),
    "merge_disjoint": (
        _REVISION_FIELDS
        | _AUTHORSHIP_FIELDS
        | _PROVENANCE_FIELDS
        | _FRESHNESS_FIELDS
        | {"summary", "kind_payload", "content_sha256"}
    ),
    "conflict_recorded": _REVISION_FIELDS,
    "scope_rebind_reference": _REVISION_FIELDS | {"source_room_ids"},
}

_TRANSITIONS = {
    "create": {(None, "active")},
    "confirm": {("active", "active")},
    "revise": {("active", "active")},
    "resolve": {("active", "resolved")},
    "supersede": {
        ("active", "superseded"),
        ("resolved", "superseded"),
        ("abandoned", "superseded"),
    },
    "abandon": {("active", "abandoned")},
    "expire": {("active", "expired")},
    "reopen": {("resolved", "active"), ("abandoned", "active")},
    "attest_joint": {
        ("active", "active"),
        ("resolved", "resolved"),
        ("abandoned", "abandoned"),
    },
    "mark_cleanup_eligible": {
        ("resolved", "resolved"),
        ("superseded", "superseded"),
        ("abandoned", "abandoned"),
        ("expired", "expired"),
    },
    "merge_disjoint": {("active", "active")},
    "conflict_recorded": {
        ("active", "active"),
        ("resolved", "resolved"),
        ("abandoned", "abandoned"),
    },
    "scope_rebind_reference": {
        ("active", "active"),
        ("resolved", "resolved"),
        ("abandoned", "abandoned"),
    },
}

_PARTICIPANT_OR_STRUCTURED = frozenset(
    {
        "solen_explicit",
        "astel_explicit",
        "joint_explicit",
        "structured_client_event",
        "structured_tool_event",
    }
)
_ACTOR_ALLOWLISTS = {
    "create": _PARTICIPANT_OR_STRUCTURED,
    "confirm": _PARTICIPANT_OR_STRUCTURED,
    "revise": _PARTICIPANT_OR_STRUCTURED,
    "resolve": _PARTICIPANT_OR_STRUCTURED,
    "supersede": _PARTICIPANT_OR_STRUCTURED,
    "abandon": frozenset(
        {"solen_explicit", "astel_explicit", "structured_client_event"}
    ),
    "expire": frozenset({"deterministic_lifecycle"}),
    "reopen": frozenset(
        {"solen_explicit", "astel_explicit", "structured_client_event"}
    ),
    "attest_joint": frozenset({"joint_explicit"}),
    "mark_cleanup_eligible": frozenset({"deterministic_lifecycle"}),
    "merge_disjoint": _PARTICIPANT_OR_STRUCTURED,
    "conflict_recorded": frozenset({"deterministic_lifecycle"}),
    "scope_rebind_reference": _PARTICIPANT_OR_STRUCTURED
    | frozenset({"deterministic_lifecycle"}),
}

_PROJECTION_LINEAGE_DDL = """
CREATE TABLE IF NOT EXISTS projection_lineage(
  lineage_id TEXT PRIMARY KEY,
  item_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  item_event_id TEXT NOT NULL,
  authority_state TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  source_operation_ids_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  record_sha256 TEXT NOT NULL UNIQUE,
  FOREIGN KEY(item_id) REFERENCES items(item_id),
  FOREIGN KEY(item_event_id) REFERENCES events(event_id),
  UNIQUE(item_id, revision)
)
"""


class HouseContinuityLocalStoreError(ValueError):
    """Body-free deterministic local-store failure."""

    def __init__(self, error_code: str):
        super().__init__(error_code)
        self.error_code = error_code


def _fail(error_code: str) -> None:
    raise HouseContinuityLocalStoreError(error_code)


def _json(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _load(value: str) -> Any:
    return json.loads(value)


def _time(value: str) -> datetime:
    parsed = datetime.strptime(value, _UTC_FORMAT).replace(tzinfo=timezone.utc)
    return parsed


def _event_payload_hash(value: Mapping[str, Any]) -> str:
    chain_fields = {
        "event_payload_sha256",
        "global_event_sequence",
        "prior_global_event_sha256",
        "global_event_sha256",
        "item_event_sequence",
        "prior_item_event_sha256",
        "item_event_sha256",
        "binding_event_sequence",
        "prior_binding_event_sha256",
        "binding_event_sha256",
    }
    return canonical_sha256(
        {key: item for key, item in value.items() if key not in chain_fields}
    )


def _global_hash(value: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "global_event_sequence": value["global_event_sequence"],
            "prior_global_event_sha256": value["prior_global_event_sha256"],
            "event_id": value["event_id"],
            "event_payload_sha256": value["event_payload_sha256"],
        }
    )


def _item_hash(value: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "item_id": value["item_id"],
            "item_event_sequence": value["item_event_sequence"],
            "prior_item_event_sha256": value["prior_item_event_sha256"],
            "event_id": value["event_id"],
            "event_payload_sha256": value["event_payload_sha256"],
        }
    )


def _binding_hash(value: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "room_id": value["room_id"],
            "binding_event_sequence": value["binding_event_sequence"],
            "prior_binding_event_sha256": value[
                "prior_binding_event_sha256"
            ],
            "event_id": value["event_id"],
            "event_payload_sha256": value["event_payload_sha256"],
        }
    )


class HouseContinuityV12LocalStore:
    """Append-only canonical SQLite owner for synthetic or M5 candidate roots."""

    def __init__(
        self,
        root: str | Path,
        *,
        synthetic_only: bool,
        production_candidate: bool = False,
    ):
        if synthetic_only is True and production_candidate is False:
            self.store_mode = "synthetic_local"
            self.expected_store_schema_version = STORE_SCHEMA_VERSION
        elif synthetic_only is False and production_candidate is True:
            self.store_mode = "m5_production_candidate"
            self.expected_store_schema_version = (
                PRODUCTION_CANDIDATE_STORE_SCHEMA_VERSION
            )
        else:
            _fail("synthetic_only_required")
        self.root = Path(root).resolve()
        if not self.root.exists() or not self.root.is_dir():
            _fail("existing_local_root_required")
        self.database_path = self.root / "house_continuity_v1_2_local.sqlite3"
        existing_store = self.database_path.exists()
        self._connection = sqlite3.connect(
            str(self.database_path), timeout=0.1
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._write_transaction_depth = 0
        if self._connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            self._connection.close()
            _fail("foreign_keys_unavailable")
        if existing_store:
            try:
                self._verify_store_identity()
            except Exception:
                self._connection.close()
                raise
        else:
            self._create_schema()
            self.store_id = _STORE_ID_PREFIX + secrets.token_hex(16)
            with self._connection:
                self._connection.executemany(
                    "INSERT INTO store_meta(key,value) VALUES(?,?)",
                    [
                        ("schema_version", self.expected_store_schema_version),
                        ("store_id", self.store_id),
                        *(
                            [("store_mode", self.store_mode)]
                            if self.store_mode == "m5_production_candidate"
                            else []
                        ),
                    ],
                )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "HouseContinuityV12LocalStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @contextmanager
    def _write_transaction(self):
        outermost = self._write_transaction_depth == 0
        if outermost and not self._connection.in_transaction:
            self._connection.execute("BEGIN IMMEDIATE")
        self._write_transaction_depth += 1
        try:
            yield
            self._write_transaction_depth -= 1
            if outermost:
                self._connection.commit()
        except Exception:
            self._write_transaction_depth -= 1
            if outermost and self._connection.in_transaction:
                self._connection.rollback()
            raise

    @contextmanager
    def outbox_bundle_transaction(self):
        """Gate-5 local adapter seam; one Gate-1 SQLite transaction."""

        with self._write_transaction():
            yield self

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS store_meta(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS creation_seeds(
              entity_id TEXT PRIMARY KEY,
              entity_kind TEXT NOT NULL,
              creation_seed_sha256 TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events(
              global_sequence INTEGER PRIMARY KEY,
              event_id TEXT NOT NULL UNIQUE,
              owner_kind TEXT NOT NULL,
              owner_id TEXT NOT NULL,
              owner_sequence INTEGER NOT NULL,
              event_json TEXT NOT NULL,
              FOREIGN KEY(event_id) REFERENCES creation_seeds(entity_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS events_owner_sequence
              ON events(owner_kind, owner_id, owner_sequence);
            CREATE TABLE IF NOT EXISTS items(
              item_id TEXT PRIMARY KEY,
              revision INTEGER NOT NULL,
              lifecycle_state TEXT NOT NULL,
              item_json TEXT NOT NULL,
              FOREIGN KEY(item_id) REFERENCES creation_seeds(entity_id)
            );
            CREATE TABLE IF NOT EXISTS item_history(
              item_id TEXT NOT NULL,
              revision INTEGER NOT NULL,
              item_json TEXT NOT NULL,
              PRIMARY KEY(item_id, revision),
              FOREIGN KEY(item_id) REFERENCES items(item_id)
            );
            CREATE TABLE IF NOT EXISTS bindings(
              room_id TEXT PRIMARY KEY,
              revision INTEGER NOT NULL,
              binding_json TEXT NOT NULL,
              FOREIGN KEY(room_id) REFERENCES creation_seeds(entity_id)
            );
            CREATE TABLE IF NOT EXISTS idempotency_receipts(
              idempotency_key TEXT PRIMARY KEY,
              command_sha256 TEXT NOT NULL,
              event_id TEXT NOT NULL,
              receipt_json TEXT NOT NULL,
              FOREIGN KEY(event_id) REFERENCES events(event_id)
            );
            CREATE TABLE IF NOT EXISTS conflict_receipts(
              receipt_id TEXT PRIMARY KEY,
              event_id TEXT NOT NULL UNIQUE,
              item_id TEXT NOT NULL,
              reason_code TEXT NOT NULL,
              command_sha256 TEXT NOT NULL,
              created_at TEXT NOT NULL,
              receipt_json TEXT NOT NULL,
              FOREIGN KEY(event_id) REFERENCES events(event_id),
              FOREIGN KEY(item_id) REFERENCES items(item_id)
            );
            CREATE TABLE IF NOT EXISTS unit_coverage(
              coverage_id TEXT PRIMARY KEY,
              complete_unit_id TEXT NOT NULL,
              complete_unit_sha256 TEXT NOT NULL,
              coverage_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox_bundles(
              bundle_id TEXT PRIMARY KEY,
              command_bundle_sha256 TEXT NOT NULL,
              outbox_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS joint_attestations(
              attestation_id TEXT PRIMARY KEY,
              canonical_semantic_sha256 TEXT NOT NULL,
              attestation_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS accepted_joint_receipts(
              receipt_id TEXT PRIMARY KEY,
              attestation_id TEXT NOT NULL UNIQUE,
              item_id TEXT NOT NULL,
              expected_revision INTEGER NOT NULL,
              receipt_sha256 TEXT NOT NULL UNIQUE,
              receipt_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS atomic_bundle_receipts(
              bundle_id TEXT PRIMARY KEY,
              command_bundle_sha256 TEXT NOT NULL,
              receipt_sha256 TEXT NOT NULL UNIQUE,
              receipt_json TEXT NOT NULL
            );
            """
        )
        self._connection.execute(_PROJECTION_LINEAGE_DDL)
        self._connection.commit()

    def _verify_store_identity(self) -> None:
        try:
            table = self._connection.execute(
                "SELECT 1 FROM sqlite_master"
                " WHERE type='table' AND name='store_meta'"
            ).fetchone()
            if table is None:
                _fail("store_metadata_missing")
            rows = {
                row["key"]: row["value"]
                for row in self._connection.execute(
                    "SELECT key,value FROM store_meta"
                )
            }
        except sqlite3.DatabaseError as exc:
            raise HouseContinuityLocalStoreError(
                "store_metadata_unreadable"
            ) from exc
        expected_keys = (
            {"schema_version", "store_id", "store_mode"}
            if self.store_mode == "m5_production_candidate"
            else {"schema_version", "store_id"}
        )
        if set(rows) != expected_keys:
            _fail("store_metadata_missing")
        if rows["schema_version"] != self.expected_store_schema_version:
            _fail("store_schema_version_mismatch")
        if (
            self.store_mode == "m5_production_candidate"
            and rows["store_mode"] != self.store_mode
        ):
            _fail("store_mode_mismatch")
        store_id = rows["store_id"]
        if (
            not isinstance(store_id, str)
            or not store_id.startswith(_STORE_ID_PREFIX)
            or len(store_id) != len(_STORE_ID_PREFIX) + 32
            or any(
                character not in "0123456789abcdef"
                for character in store_id[len(_STORE_ID_PREFIX) :]
            )
        ):
            _fail("store_id_invalid")
        self.store_id = store_id
        required_columns = {
            row["name"]
            for row in self._connection.execute(
                "PRAGMA table_info(creation_seeds)"
            )
        }
        if required_columns != {
            "entity_id",
            "entity_kind",
            "creation_seed_sha256",
            "created_at",
        }:
            _fail("store_schema_layout_mismatch")

    def register_creation_seed(
        self,
        entity_id: str,
        creation_seed_sha256: str,
        *,
        entity_kind: str,
        created_at: str,
    ) -> bool:
        row = self._connection.execute(
            "SELECT entity_kind,creation_seed_sha256,created_at"
            " FROM creation_seeds WHERE entity_id=?",
            (entity_id,),
        ).fetchone()
        if row is not None:
            if (
                row["creation_seed_sha256"] != creation_seed_sha256
                or row["entity_kind"] != entity_kind
                or row["created_at"] != created_at
            ):
                _fail("creation_seed_collision")
            return False
        if (
            not isinstance(creation_seed_sha256, str)
            or len(creation_seed_sha256) != 64
            or any(character not in "0123456789abcdef" for character in creation_seed_sha256)
        ):
            _fail("invalid_creation_seed_sha256")
        if entity_kind not in {
            "item",
            "room",
            "event",
            "coverage",
            "outbox",
            "joint_attestation",
            "accepted_joint_receipt",
            "capability",
        }:
            _fail("invalid_creation_seed_entity_kind")
        _time(created_at)
        try:
            self._connection.execute(
                "INSERT INTO creation_seeds"
                "(entity_id,entity_kind,creation_seed_sha256,created_at)"
                " VALUES(?,?,?,?)",
                (entity_id, entity_kind, creation_seed_sha256, created_at),
            )
        except sqlite3.IntegrityError as exc:
            raise HouseContinuityLocalStoreError(
                "creation_seed_identity_conflict"
            ) from exc
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower():
                raise HouseContinuityLocalStoreError(
                    "sqlite_write_locked"
                ) from exc
            raise HouseContinuityLocalStoreError(
                "sqlite_write_failure"
            ) from exc
        return True

    @staticmethod
    def event_creation_seed(
        *, event_id: str, event_kind: str, created_at: str
    ) -> str:
        return canonical_sha256(
            {
                "entity_kind": "event",
                "event_id": event_id,
                "event_kind": event_kind,
                "created_at": created_at,
                "versioned_namespace": "house_continuity_event_v1_1",
            }
        )

    def _global_head(self) -> tuple[int, str | None]:
        row = self._connection.execute(
            "SELECT global_sequence,event_json FROM events"
            " ORDER BY global_sequence DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return 0, None
        event = _load(row["event_json"])
        return row["global_sequence"], event["global_event_sha256"]

    def _owner_head(
        self, owner_kind: str, owner_id: str, hash_field: str
    ) -> tuple[int, str | None]:
        row = self._connection.execute(
            "SELECT owner_sequence,event_json FROM events"
            " WHERE owner_kind=? AND owner_id=?"
            " ORDER BY owner_sequence DESC LIMIT 1",
            (owner_kind, owner_id),
        ).fetchone()
        if row is None:
            return 0, None
        return row["owner_sequence"], _load(row["event_json"])[hash_field]

    def read_item(self, item_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT item_json FROM items WHERE item_id=?", (item_id,)
        ).fetchone()
        return None if row is None else _load(row["item_json"])

    @staticmethod
    def _validate_projection_lineage(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "lineage_id",
            "item_id",
            "revision",
            "item_event_id",
            "authority_state",
            "reason_code",
            "source_operation_ids",
            "created_at",
            "record_sha256",
        }:
            _fail("projection_lineage_invalid")
        if value["schema_version"] != PROJECTION_LINEAGE_SCHEMA_VERSION:
            _fail("projection_lineage_schema_invalid")
        if (
            not isinstance(value["lineage_id"], str)
            or not value["lineage_id"].startswith("cws_lineage_")
            or len(value["lineage_id"]) != len("cws_lineage_") + 32
            or any(
                character not in "0123456789abcdef"
                for character in value["lineage_id"][len("cws_lineage_") :]
            )
        ):
            _fail("projection_lineage_identity_invalid")
        if (
            not isinstance(value["item_id"], str)
            or not value["item_id"].startswith("cws_item_")
            or not isinstance(value["item_event_id"], str)
            or not value["item_event_id"].startswith("cws_evt_")
        ):
            _fail("projection_lineage_reference_invalid")
        if (
            isinstance(value["revision"], bool)
            or not isinstance(value["revision"], int)
            or value["revision"] < 1
        ):
            _fail("projection_lineage_revision_invalid")
        if value["authority_state"] != _PROJECTION_LINEAGE_STATE:
            _fail("projection_lineage_state_invalid")
        reason = value["reason_code"]
        if (
            not isinstance(reason, str)
            or not reason
            or len(reason) > 96
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz"
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-"
                for character in reason
            )
        ):
            _fail("projection_lineage_reason_invalid")
        source_operations = value["source_operation_ids"]
        if (
            not isinstance(source_operations, list)
            or len(source_operations) > 8
            or any(
                not isinstance(operation_id, str)
                or not operation_id
                or len(operation_id) > 180
                for operation_id in source_operations
            )
        ):
            _fail("projection_lineage_provenance_invalid")
        _time(value["created_at"])
        body = {
            key: value[key]
            for key in value
            if key not in {"lineage_id", "record_sha256"}
        }
        if (
            not isinstance(value["record_sha256"], str)
            or len(value["record_sha256"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in value["record_sha256"]
            )
            or value["record_sha256"] != canonical_sha256(body)
            or value["lineage_id"]
            != "cws_lineage_" + value["record_sha256"][:32]
        ):
            _fail("projection_lineage_hash_invalid")
        return {
            "schema_version": PROJECTION_LINEAGE_SCHEMA_VERSION,
            "lineage_id": value["lineage_id"],
            "item_id": value["item_id"],
            "revision": value["revision"],
            "item_event_id": value["item_event_id"],
            "authority_state": _PROJECTION_LINEAGE_STATE,
            "reason_code": reason,
            "source_operation_ids": list(source_operations),
            "created_at": value["created_at"],
            "record_sha256": value["record_sha256"],
        }

    def _read_projection_lineage(self) -> list[dict[str, Any]]:
        table = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table'"
            " AND name='projection_lineage'"
        ).fetchone()
        if table is None:
            return []
        lineage = []
        for row in self._connection.execute(
            "SELECT lineage_id,item_id,revision,item_event_id,authority_state,"
            "reason_code,source_operation_ids_json,created_at,record_sha256"
            " FROM projection_lineage ORDER BY lineage_id"
        ):
            value = _load(row["source_operation_ids_json"])
            normalized = self._validate_projection_lineage(
                {
                    "schema_version": PROJECTION_LINEAGE_SCHEMA_VERSION,
                    "lineage_id": row["lineage_id"],
                    "item_id": row["item_id"],
                    "revision": row["revision"],
                    "item_event_id": row["item_event_id"],
                    "authority_state": row["authority_state"],
                    "reason_code": row["reason_code"],
                    "source_operation_ids": value,
                    "created_at": row["created_at"],
                    "record_sha256": row["record_sha256"],
                }
            )
            lineage.append(normalized)
        return lineage

    def read_projection_lineage(self) -> list[dict[str, Any]]:
        """Read raw-free authority dispositions without changing history."""

        return deepcopy(self._read_projection_lineage())

    def record_non_authoritative_revision(
        self,
        *,
        item_id: str,
        revision: int,
        reason_code: str,
        recorded_at: str,
    ) -> dict[str, Any]:
        """Append a failure disposition for one item lineage revision.

        This records projection authority separately from item/event history.
        It never edits the item head, history rows, events, or receipts.  Once
        a revision is marked non-authoritative, later revisions in that same
        item lineage remain excluded; a fresh item identity is the recovery
        seam for a genuinely new semantic successor.
        """

        _time(recorded_at)
        if (
            not isinstance(item_id, str)
            or not item_id.startswith("cws_item_")
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
        ):
            _fail("projection_lineage_reference_invalid")
        current = self.read_item(item_id)
        if current is None:
            _fail("projection_lineage_item_missing")
        if current["revision"] == revision:
            item = validate_working_set_item(current)
        else:
            row = self._connection.execute(
                "SELECT item_json FROM item_history WHERE item_id=? AND revision=?",
                (item_id, revision),
            ).fetchone()
            if row is None:
                _fail("projection_lineage_item_revision_missing")
            item = validate_working_set_item(_load(row["item_json"]))
        event = self._connection.execute(
            "SELECT event_json FROM events WHERE event_id=?", (item["base_event_id"],)
        ).fetchone()
        if event is None:
            _fail("projection_lineage_event_missing")
        event_value = validate_working_set_event(_load(event["event_json"]))
        if (
            event_value["item_id"] != item_id
            or event_value["new_revision"] != revision
        ):
            _fail("projection_lineage_binding_mismatch")
        body = {
            "schema_version": PROJECTION_LINEAGE_SCHEMA_VERSION,
            "item_id": item_id,
            "revision": revision,
            "item_event_id": item["base_event_id"],
            "authority_state": _PROJECTION_LINEAGE_STATE,
            "reason_code": reason_code,
            "source_operation_ids": list(item["source_operation_ids"]),
            "created_at": recorded_at,
        }
        record = self._validate_projection_lineage(
            {
                **body,
                "lineage_id": "cws_lineage_" + canonical_sha256(body)[:32],
                "record_sha256": canonical_sha256(body),
            }
        )
        try:
            with self._write_transaction():
                # Existing pre-lineage stores remain read-only until this
                # canonical append-only writer is actually used.
                self._connection.execute(_PROJECTION_LINEAGE_DDL)
                existing = self._connection.execute(
                    "SELECT lineage_id,record_sha256,source_operation_ids_json,"
                    "authority_state,reason_code,created_at,item_id,revision,item_event_id"
                    " FROM projection_lineage WHERE item_id=? AND revision=?",
                    (item_id, revision),
                ).fetchone()
                if existing is not None:
                    prior = self._validate_projection_lineage(
                        {
                            "schema_version": PROJECTION_LINEAGE_SCHEMA_VERSION,
                            "lineage_id": existing["lineage_id"],
                            "item_id": existing["item_id"],
                            "revision": existing["revision"],
                            "item_event_id": existing["item_event_id"],
                            "authority_state": existing["authority_state"],
                            "reason_code": existing["reason_code"],
                            "source_operation_ids": _load(
                                existing["source_operation_ids_json"]
                            ),
                            "created_at": existing["created_at"],
                            "record_sha256": existing["record_sha256"],
                        }
                    )
                    if prior != record:
                        _fail("projection_lineage_identity_conflict")
                    return deepcopy(prior)
                self._connection.execute(
                    "INSERT INTO projection_lineage VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        record["lineage_id"],
                        record["item_id"],
                        record["revision"],
                        record["item_event_id"],
                        record["authority_state"],
                        record["reason_code"],
                        _json(record["source_operation_ids"]),
                        record["created_at"],
                        record["record_sha256"],
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise HouseContinuityLocalStoreError(
                "projection_lineage_identity_conflict"
            ) from exc
        return deepcopy(record)

    def record_non_authoritative_operation(
        self,
        *,
        source_operation_id: str,
        reason_code: str,
        recorded_at: str,
    ) -> list[dict[str, Any]]:
        """Record every persisted semantic revision from one failed operation.

        The operation outcome is finalized outside the append-only item/event
        writer (for example, by an M5 postcondition check).  This helper
        resolves that outcome through the immutable source-operation
        provenance already carried by item history and delegates each exact
        item/revision to :meth:`record_non_authoritative_revision`.

        An operation that failed before a semantic revision was persisted is
        a valid no-op: there is no item head to exclude from projection.  A
        repeated finalization returns the same lineage records, so crash
        recovery cannot double-record or alter history.
        """

        if (
            not isinstance(source_operation_id, str)
            or not source_operation_id
            or len(source_operation_id) > 180
        ):
            _fail("projection_lineage_operation_invalid")
        _time(recorded_at)
        candidates: list[tuple[str, int]] = []
        for row in self._connection.execute(
            "SELECT item_id,revision,item_json FROM item_history"
            " ORDER BY item_id,revision"
        ):
            item = validate_working_set_item(_load(row["item_json"]))
            if (
                row["item_id"] != item["item_id"]
                or row["revision"] != item["revision"]
            ):
                _fail("item_history_index_json_mismatch")
            if source_operation_id in item["source_operation_ids"]:
                candidates.append((item["item_id"], item["revision"]))
        return [
            self.record_non_authoritative_revision(
                item_id=item_id,
                revision=revision,
                reason_code=reason_code,
                recorded_at=recorded_at,
            )
            for item_id, revision in candidates
        ]

    def read_binding(self, room_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT binding_json FROM bindings WHERE room_id=?", (room_id,)
        ).fetchone()
        return None if row is None else _load(row["binding_json"])

    def read_applied_events(
        self, event_ids: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        """Return exact append-only events only after they exist in this store."""

        if (
            not isinstance(event_ids, tuple)
            or not event_ids
            or len(event_ids) > 8
            or len(event_ids) != len(set(event_ids))
            or any(
                not isinstance(event_id, str)
                or not event_id.startswith("cws_evt_")
                for event_id in event_ids
            )
        ):
            _fail("invalid_applied_event_ids")
        rows = self._connection.execute(
            "SELECT event_id,event_json FROM events WHERE event_id IN ("
            + ",".join("?" for _ in event_ids)
            + ")",
            event_ids,
        ).fetchall()
        by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                event = validate_working_set_event(_load(row["event_json"]))
            except HouseContinuityV12ContractError as exc:
                raise HouseContinuityLocalStoreError(
                    "stored_applied_event_invalid"
                ) from exc
            if row["event_id"] != event["event_id"]:
                _fail("applied_event_index_json_mismatch")
            by_id[event["event_id"]] = event
        if set(by_id) != set(event_ids):
            _fail("applied_event_missing")
        return [by_id[event_id] for event_id in event_ids]

    def prepare_item_event(
        self,
        *,
        event_id: str,
        event_kind: str,
        next_item: Mapping[str, Any],
        expected_revision: int,
        actor_kind: str,
        actor_ref: str,
        idempotency_key: str,
        command_sha256: str,
        created_at: str,
    ) -> dict[str, Any]:
        next_normalized = validate_working_set_item(next_item)
        current = self.read_item(next_normalized["item_id"])
        current_revision = 0 if current is None else current["revision"]
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            _fail("invalid_expected_revision")
        if expected_revision != current_revision:
            _fail("stale_expected_revision")
        global_sequence, prior_global = self._global_head()
        item_sequence, prior_item = self._owner_head(
            "item",
            next_normalized["item_id"],
            "item_event_sha256",
        )
        if current is None:
            patch = deepcopy(next_normalized)
            from_lifecycle = None
        else:
            patch = {
                key: deepcopy(value)
                for key, value in next_normalized.items()
                if current[key] != value
            }
            from_lifecycle = current["lifecycle_state"]
        event = {
            "schema_version": "house_continuity_event_v1_1",
            "event_id": event_id,
            "creation_seed_sha256": self.event_creation_seed(
                event_id=event_id,
                event_kind=event_kind,
                created_at=created_at,
            ),
            "event_payload_sha256": "",
            "global_event_sequence": global_sequence + 1,
            "prior_global_event_sha256": prior_global,
            "global_event_sha256": "",
            "item_id": next_normalized["item_id"],
            "item_event_sequence": item_sequence + 1,
            "prior_item_event_sha256": prior_item,
            "item_event_sha256": "",
            "event_kind": event_kind,
            "from_lifecycle_state": from_lifecycle,
            "to_lifecycle_state": next_normalized["lifecycle_state"],
            "expected_revision": expected_revision,
            "new_revision": next_normalized["revision"],
            "patch": patch,
            "actor_kind": actor_kind,
            "actor_ref": actor_ref,
            "idempotency_key": idempotency_key,
            "command_sha256": command_sha256,
            "source_turn_ids": next_normalized["source_turn_ids"],
            "source_room_ids": next_normalized["source_room_ids"],
            "source_operation_ids": next_normalized["source_operation_ids"],
            "source_proposal_ids": next_normalized["source_proposal_ids"],
            "created_at": created_at,
        }
        event["event_payload_sha256"] = _event_payload_hash(event)
        event["global_event_sha256"] = _global_hash(event)
        event["item_event_sha256"] = _item_hash(event)
        return validate_working_set_event(event)

    def _idempotent_receipt(
        self, idempotency_key: str, command_sha256: str
    ) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT command_sha256,receipt_json FROM idempotency_receipts"
            " WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        if row["command_sha256"] != command_sha256:
            _fail("idempotency_key_command_mismatch")
        return _load(row["receipt_json"])

    def _validate_item_transition(
        self,
        event: Mapping[str, Any],
        current: Mapping[str, Any] | None,
        next_item: Mapping[str, Any],
    ) -> None:
        event_kind = event["event_kind"]
        transition = (
            event["from_lifecycle_state"],
            event["to_lifecycle_state"],
        )
        if transition not in _TRANSITIONS[event_kind]:
            _fail("invalid_lifecycle_transition")
        if event["actor_kind"] not in _ACTOR_ALLOWLISTS[event_kind]:
            _fail("actor_transition_incompatible")
        actor_kind = event["actor_kind"]
        if actor_kind == "deterministic_lifecycle":
            if event["actor_ref"] != _DETERMINISTIC_ACTOR_REFS.get(event_kind):
                _fail("actor_ref_mismatch")
        else:
            if event["actor_ref"] != _ACTOR_REFS.get(actor_kind):
                _fail("actor_ref_mismatch")
            if (
                next_item["authorship_kind"] != actor_kind
                or next_item["command_owner"] != event["actor_ref"]
            ):
                _fail("actor_authorship_mismatch")
        if event_kind == "create":
            if current is not None or event["patch"] != next_item:
                _fail("invalid_create_projection")
        else:
            if current is None:
                _fail("missing_item_projection")
            changed = {
                key: deepcopy(value)
                for key, value in next_item.items()
                if current[key] != value
            }
            if event["patch"] != changed:
                _fail("event_patch_projection_mismatch")
            if any(key in _ITEM_IMMUTABLE_FIELDS for key in changed):
                _fail("immutable_item_field_changed")
            allowed = _PATCH_ALLOWLISTS[event_kind]
            if not set(changed).issubset(allowed):
                _fail("event_patch_field_forbidden")
        if next_item["revision"] != event["new_revision"]:
            _fail("projection_revision_mismatch")
        if next_item["base_event_id"] != event["event_id"]:
            _fail("projection_base_event_mismatch")
        if next_item["idempotency_key"] != event["idempotency_key"]:
            _fail("projection_idempotency_mismatch")
        if event_kind in {"confirm", "resolve"} and any(
            field in event["patch"]
            for field in ("summary", "kind_payload", "content_sha256")
        ):
            _fail("semantic_rewrite_forbidden")
        if event_kind == "expire":
            if next_item["item_kind"] not in {
                "temporary_fact",
                "completed_tool_result_ref",
            }:
                _fail("time_only_semantic_terminal_forbidden")
            if _time(event["created_at"]) < _time(next_item["expires_at"]):
                _fail("expiry_not_reached")
        if event_kind == "attest_joint":
            if (
                next_item["authorship_kind"] != "joint_explicit"
                or next_item["command_owner"]
                != "house_continuity_joint_authorship_attestation_v1"
            ):
                _fail("joint_projection_required")
        if event_kind == "mark_cleanup_eligible":
            if next_item["cleanup_state"] != "cleanup_eligible":
                _fail("cleanup_projection_required")
            boundary = self._cleanup_boundary(next_item, current)
            if _time(next_item["cleanup_eligible_at"]) < boundary:
                _fail("cleanup_retention_not_reached")
        if event_kind == "supersede":
            successor = self.read_item(next_item["superseded_by_item_id"])
            if (
                successor is None
                or next_item["item_id"]
                not in successor["supersedes_item_ids"]
                or successor["scope_kind"] != next_item["scope_kind"]
                or successor["room_id"] != next_item["room_id"]
                or successor["project_id"] != next_item["project_id"]
                or successor["thread_id"] != next_item["thread_id"]
            ):
                _fail("authorized_successor_relationship_required")

    def _cleanup_boundary(
        self,
        item: Mapping[str, Any],
        current: Mapping[str, Any] | None,
    ) -> datetime:
        if item["lifecycle_state"] == "expired":
            return _time(item["expires_at"]) + timedelta(days=30)
        if item["lifecycle_state"] == "resolved":
            terminal = _time(item["resolved_at"])
        elif item["lifecycle_state"] == "abandoned":
            terminal = _time(item["abandoned_at"])
        elif item["lifecycle_state"] == "superseded":
            if current is None:
                _fail("cleanup_terminal_projection_required")
            terminal = _time(current["updated_at"])
        else:
            _fail("cleanup_active_forbidden")
        return terminal + timedelta(days=365)

    def apply_item_event(
        self,
        event: Mapping[str, Any],
        next_item: Mapping[str, Any],
        *,
        conflict_reason_code: str | None = None,
        accepted_joint_receipt: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_event = validate_working_set_event(event)
        normalized_item = validate_working_set_item(next_item)
        retry = self._idempotent_receipt(
            normalized_event["idempotency_key"],
            normalized_event["command_sha256"],
        )
        if retry is not None:
            return retry
        current = self.read_item(normalized_event["item_id"])
        current_revision = 0 if current is None else current["revision"]
        if normalized_event["expected_revision"] != current_revision:
            _fail("stale_expected_revision")
        global_sequence, prior_global = self._global_head()
        item_sequence, prior_item = self._owner_head(
            "item", normalized_event["item_id"], "item_event_sha256"
        )
        if (
            normalized_event["global_event_sequence"] != global_sequence + 1
            or normalized_event["prior_global_event_sha256"] != prior_global
            or normalized_event["item_event_sequence"] != item_sequence + 1
            or normalized_event["prior_item_event_sha256"] != prior_item
        ):
            _fail("event_chain_head_mismatch")
        self._validate_item_transition(
            normalized_event, current, normalized_item
        )
        if normalized_event["event_kind"] == "conflict_recorded":
            if conflict_reason_code not in _CONFLICT_REASON_CODES:
                _fail("conflict_reason_required")
        elif conflict_reason_code is not None:
            _fail("conflict_reason_forbidden")
        if normalized_event["event_kind"] == "attest_joint":
            if accepted_joint_receipt is None:
                _fail("accepted_joint_receipt_required")
            self._verify_accepted_joint_receipt(
                normalized_event,
                normalized_item,
                accepted_joint_receipt,
            )
        elif accepted_joint_receipt is not None:
            _fail("accepted_joint_receipt_forbidden")
        self.register_creation_seed(
            normalized_event["item_id"],
            normalized_item["creation_seed_sha256"],
            entity_kind="item",
            created_at=normalized_item["created_at"],
        )
        self.register_creation_seed(
            normalized_event["event_id"],
            normalized_event["creation_seed_sha256"],
            entity_kind="event",
            created_at=normalized_event["created_at"],
        )
        conflict_receipt = None
        if conflict_reason_code is not None:
            conflict_receipt = {
                "schema_version": "house_continuity_conflict_receipt_v1",
                "receipt_id": (
                    "cws_conflict_" + normalized_event["event_id"][8:]
                ),
                "event_id": normalized_event["event_id"],
                "item_id": normalized_event["item_id"],
                "reason_code": conflict_reason_code,
                "command_sha256": normalized_event["command_sha256"],
                "created_at": normalized_event["created_at"],
                "raw_body_included": False,
            }
        receipt = {
            "state": "applied",
            "event_id": normalized_event["event_id"],
            "item_id": normalized_event["item_id"],
            "new_revision": normalized_event["new_revision"],
            "global_event_sequence": normalized_event[
                "global_event_sequence"
            ],
            "global_event_sha256": normalized_event["global_event_sha256"],
            "item_event_sha256": normalized_event["item_event_sha256"],
            "conflict_reason_code": conflict_reason_code,
            "conflict_receipt_id": (
                None
                if conflict_receipt is None
                else conflict_receipt["receipt_id"]
            ),
        }
        try:
            with self._write_transaction():
                self._connection.execute(
                    "INSERT INTO events VALUES(?,?,?,?,?,?)",
                    (
                        normalized_event["global_event_sequence"],
                        normalized_event["event_id"],
                        "item",
                        normalized_event["item_id"],
                        normalized_event["item_event_sequence"],
                        _json(normalized_event),
                    ),
                )
                self._connection.execute(
                    "INSERT OR REPLACE INTO items VALUES(?,?,?,?)",
                    (
                        normalized_item["item_id"],
                        normalized_item["revision"],
                        normalized_item["lifecycle_state"],
                        _json(normalized_item),
                    ),
                )
                self._connection.execute(
                    "INSERT INTO item_history VALUES(?,?,?)",
                    (
                        normalized_item["item_id"],
                        normalized_item["revision"],
                        _json(normalized_item),
                    ),
                )
                self._connection.execute(
                    "INSERT INTO idempotency_receipts VALUES(?,?,?,?)",
                    (
                        normalized_event["idempotency_key"],
                        normalized_event["command_sha256"],
                        normalized_event["event_id"],
                        _json(receipt),
                    ),
                )
                if conflict_receipt is not None:
                    self._connection.execute(
                        "INSERT INTO conflict_receipts VALUES(?,?,?,?,?,?,?)",
                        (
                            conflict_receipt["receipt_id"],
                            normalized_event["event_id"],
                            normalized_event["item_id"],
                            conflict_reason_code,
                            normalized_event["command_sha256"],
                            normalized_event["created_at"],
                            _json(conflict_receipt),
                        ),
                    )
        except sqlite3.IntegrityError as exc:
            raise HouseContinuityLocalStoreError(
                "transactional_identity_conflict"
            ) from exc
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower():
                raise HouseContinuityLocalStoreError(
                    "sqlite_write_locked"
                ) from exc
            raise HouseContinuityLocalStoreError(
                "sqlite_write_failure"
            ) from exc
        return receipt

    def _verify_accepted_joint_receipt(
        self,
        event: Mapping[str, Any],
        next_item: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> None:
        try:
            normalized = validate_accepted_joint_receipt(receipt)
        except CrossGateReceiptError as exc:
            raise HouseContinuityLocalStoreError(exc.error_code) from exc
        row = self._connection.execute(
            "SELECT receipt_json FROM accepted_joint_receipts"
            " WHERE receipt_id=?",
            (normalized["receipt_id"],),
        ).fetchone()
        if row is None or _load(row["receipt_json"]) != normalized:
            _fail("accepted_joint_receipt_not_durable")
        scope_sha = canonical_sha256(
            {
                "scope_kind": next_item["scope_kind"],
                "room_id": next_item["room_id"],
                "project_id": next_item["project_id"],
                "thread_id": next_item["thread_id"],
            }
        )
        evidence = {
            ref["participant"]: ref
            for ref in next_item["authorship_evidence_refs"]
        }
        if (
            normalized["item_id"] != event["item_id"]
            or normalized["expected_revision"] != event["expected_revision"]
            or normalized["scope_sha256"] != scope_sha
            or normalized["canonical_semantic_sha256"]
            != next_item["content_sha256"]
            or normalized["idempotency_identity"]
            != event["idempotency_key"]
            or set(evidence) != {"astel", "solen"}
        ):
            _fail("accepted_joint_receipt_binding_mismatch")
        for participant in ("astel", "solen"):
            ref = evidence[participant]
            if (
                ref["evidence_id"]
                != normalized[f"{participant}_evidence_id"]
                or ref["event_id"] != normalized[f"{participant}_event_id"]
                or ref["content_sha256"]
                != normalized[f"{participant}_content_sha256"]
            ):
                _fail("accepted_joint_evidence_ref_mismatch")

    def apply_disjoint_merge(
        self,
        *,
        base_revision: int,
        event: Mapping[str, Any],
        next_item: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized_event = validate_working_set_event(event)
        if normalized_event["event_kind"] != "merge_disjoint":
            _fail("merge_disjoint_event_required")
        history = self._connection.execute(
            "SELECT item_json FROM item_history WHERE item_id=? AND revision=?",
            (normalized_event["item_id"], base_revision),
        ).fetchone()
        current = self.read_item(normalized_event["item_id"])
        if history is None or current is None:
            _fail("merge_base_revision_unavailable")
        base = _load(history["item_json"])
        requested_fields = set(normalized_event["patch"]) - _REVISION_FIELDS
        for field in requested_fields:
            if current[field] != base[field]:
                _fail("merge_field_changed_since_base")
        return self.apply_item_event(normalized_event, next_item)

    def prepare_binding_event(
        self,
        *,
        event_id: str,
        event_kind: str,
        to_binding: Mapping[str, Any],
        expected_binding_revision: int,
        actor_kind: str,
        actor_ref: str,
        idempotency_key: str,
        command_sha256: str,
        created_at: str,
    ) -> dict[str, Any]:
        room_id = to_binding["room_id"]
        current = self.read_binding(room_id)
        current_revision = (
            0 if current is None else current["binding_revision"]
        )
        if (
            isinstance(expected_binding_revision, bool)
            or not isinstance(expected_binding_revision, int)
            or expected_binding_revision < 0
        ):
            _fail("invalid_expected_binding_revision")
        if expected_binding_revision != current_revision:
            _fail("stale_binding_revision")
        global_sequence, prior_global = self._global_head()
        binding_sequence, prior_binding = self._owner_head(
            "binding", room_id, "binding_event_sha256"
        )
        event = {
            "schema_version": "house_continuity_scope_binding_event_v1_1",
            "event_id": event_id,
            "creation_seed_sha256": self.event_creation_seed(
                event_id=event_id,
                event_kind=event_kind,
                created_at=created_at,
            ),
            "event_payload_sha256": "",
            "global_event_sequence": global_sequence + 1,
            "prior_global_event_sha256": prior_global,
            "global_event_sha256": "",
            "room_id": room_id,
            "binding_event_sequence": binding_sequence + 1,
            "prior_binding_event_sha256": prior_binding,
            "binding_event_sha256": "",
            "event_kind": event_kind,
            "expected_binding_revision": expected_binding_revision,
            "new_binding_revision": to_binding["binding_revision"],
            "from_binding": current,
            "to_binding": dict(to_binding),
            "actor_kind": actor_kind,
            "actor_ref": actor_ref,
            "idempotency_key": idempotency_key,
            "command_sha256": command_sha256,
            "source_turn_ids": [],
            "source_room_ids": [room_id],
            "source_operation_ids": [],
            "created_at": created_at,
        }
        event["event_payload_sha256"] = _event_payload_hash(event)
        event["global_event_sha256"] = _global_hash(event)
        event["binding_event_sha256"] = _binding_hash(event)
        return validate_scope_binding_event(event)

    def apply_binding_event(
        self, event: Mapping[str, Any]
    ) -> dict[str, Any]:
        normalized = validate_scope_binding_event(event)
        retry = self._idempotent_receipt(
            normalized["idempotency_key"], normalized["command_sha256"]
        )
        if retry is not None:
            return retry
        current = self.read_binding(normalized["room_id"])
        current_revision = (
            0 if current is None else current["binding_revision"]
        )
        if normalized["expected_binding_revision"] != current_revision:
            _fail("stale_binding_revision")
        self._validate_binding_transition(normalized, current)
        actor_kind = normalized["actor_kind"]
        expected_ref = (
            _DETERMINISTIC_ACTOR_REFS.get("scope_rebind_reference")
            if actor_kind == "deterministic_lifecycle"
            else _ACTOR_REFS.get(actor_kind)
        )
        if normalized["actor_ref"] != expected_ref:
            _fail("binding_actor_ref_mismatch")
        global_sequence, prior_global = self._global_head()
        binding_sequence, prior_binding = self._owner_head(
            "binding", normalized["room_id"], "binding_event_sha256"
        )
        if (
            normalized["global_event_sequence"] != global_sequence + 1
            or normalized["prior_global_event_sha256"] != prior_global
            or normalized["binding_event_sequence"] != binding_sequence + 1
            or normalized["prior_binding_event_sha256"] != prior_binding
        ):
            _fail("binding_chain_head_mismatch")
        self.register_creation_seed(
            normalized["room_id"],
            canonical_sha256(
                {
                    "entity_kind": "room",
                    "room_id": normalized["room_id"],
                    "versioned_namespace": "house_continuity_scope_binding_v1",
                }
            ),
            entity_kind="room",
            created_at=normalized["to_binding"]["created_at"],
        )
        self.register_creation_seed(
            normalized["event_id"],
            normalized["creation_seed_sha256"],
            entity_kind="event",
            created_at=normalized["created_at"],
        )
        receipt = {
            "state": "applied",
            "event_id": normalized["event_id"],
            "room_id": normalized["room_id"],
            "new_binding_revision": normalized["new_binding_revision"],
            "global_event_sequence": normalized["global_event_sequence"],
            "global_event_sha256": normalized["global_event_sha256"],
            "binding_event_sha256": normalized["binding_event_sha256"],
        }
        try:
            with self._write_transaction():
                self._connection.execute(
                    "INSERT INTO events VALUES(?,?,?,?,?,?)",
                    (
                        normalized["global_event_sequence"],
                        normalized["event_id"],
                        "binding",
                        normalized["room_id"],
                        normalized["binding_event_sequence"],
                        _json(normalized),
                    ),
                )
                self._connection.execute(
                    "INSERT OR REPLACE INTO bindings VALUES(?,?,?)",
                    (
                        normalized["room_id"],
                        normalized["new_binding_revision"],
                        _json(normalized["to_binding"]),
                    ),
                )
                self._connection.execute(
                    "INSERT INTO idempotency_receipts VALUES(?,?,?,?)",
                    (
                        normalized["idempotency_key"],
                        normalized["command_sha256"],
                        normalized["event_id"],
                        _json(receipt),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise HouseContinuityLocalStoreError(
                "transactional_identity_conflict"
            ) from exc
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower():
                raise HouseContinuityLocalStoreError(
                    "sqlite_write_locked"
                ) from exc
            raise HouseContinuityLocalStoreError(
                "sqlite_write_failure"
            ) from exc
        return receipt

    def _validate_binding_transition(
        self,
        event: Mapping[str, Any],
        current: Mapping[str, Any] | None,
    ) -> None:
        kind = event["event_kind"]
        target = event["to_binding"]
        bound = target["project_id"] is not None
        if kind == "bind" and current is not None:
            _fail("bind_requires_missing_source")
        if kind in {"rebind", "inherit", "decline"} and current is None:
            _fail("binding_source_required")
        if kind == "decline" and (
            bound
            or target["thread_id"] is not None
            or target["binding_source"] != "new_unbound"
        ):
            _fail("decline_must_leave_unbound_target")
        if kind == "inherit" and (
            not bound
            or target["predecessor_room_id"] is None
            or target["binding_source"] != "explicit_inherit"
        ):
            _fail("inherit_binding_incompatible")
        if kind == "rebind" and target["binding_source"] not in {
            "reviewed_rebind",
            "explicit_project",
            "explicit_thread",
        }:
            _fail("rebind_source_incompatible")

    def put_unit_coverage(
        self, coverage: Mapping[str, Any]
    ) -> dict[str, Any]:
        normalized = validate_unit_coverage(coverage)
        self.register_creation_seed(
            normalized["coverage_id"],
            normalized["creation_seed_sha256"],
            entity_kind="coverage",
            created_at=normalized["created_at"],
        )
        row = self._connection.execute(
            "SELECT coverage_json FROM unit_coverage WHERE coverage_id=?",
            (normalized["coverage_id"],),
        ).fetchone()
        if row is not None:
            existing = _load(row["coverage_json"])
            if existing != normalized:
                _fail("coverage_identity_conflict")
            return existing
        with self._write_transaction():
            self._connection.execute(
                "INSERT INTO unit_coverage VALUES(?,?,?,?)",
                (
                    normalized["coverage_id"],
                    normalized["complete_unit_id"],
                    normalized["complete_unit_sha256"],
                    _json(normalized),
                ),
            )
        return normalized

    def read_unit_coverage(
        self, coverage_id: str
    ) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT coverage_json FROM unit_coverage WHERE coverage_id=?",
            (coverage_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            return validate_unit_coverage(_load(row["coverage_json"]))
        except HouseContinuityV12ContractError as exc:
            raise HouseContinuityLocalStoreError(exc.error_code) from exc

    def apply_outbox_bundle_atomic(
        self,
        *,
        bundle_id: str,
        command_bundle_sha256: str,
        item_applications: tuple[Mapping[str, Any], ...],
        binding_event: Mapping[str, Any] | None,
        coverage: Mapping[str, Any],
        committed_at: str,
    ) -> dict[str, Any]:
        """Apply one Gate-5 bundle as a single selection-eligible commit."""

        _time(committed_at)
        if (
            not isinstance(bundle_id, str)
            or not bundle_id.startswith("cws_out_")
            or not isinstance(command_bundle_sha256, str)
            or len(command_bundle_sha256) != 64
        ):
            _fail("invalid_atomic_bundle_identity")
        normalized_packages = []
        for package in item_applications:
            if not isinstance(package, Mapping) or set(package) != {
                "event",
                "next_item",
                "conflict_reason_code",
                "accepted_joint_receipt",
            }:
                _fail("invalid_atomic_item_application")
            normalized_packages.append(
                {
                    "event": validate_working_set_event(package["event"]),
                    "next_item": validate_working_set_item(
                        package["next_item"]
                    ),
                    "conflict_reason_code": package[
                        "conflict_reason_code"
                    ],
                    "accepted_joint_receipt": deepcopy(
                        package["accepted_joint_receipt"]
                    ),
                }
            )
        normalized_binding = (
            None
            if binding_event is None
            else validate_scope_binding_event(binding_event)
        )
        normalized_coverage = validate_unit_coverage(coverage)
        application_input_sha256 = canonical_sha256(
            {
                "bundle_id": bundle_id,
                "command_bundle_sha256": command_bundle_sha256,
                "item_applications": normalized_packages,
                "binding_event": normalized_binding,
                "coverage": normalized_coverage,
            }
        )
        existing = self._connection.execute(
            "SELECT command_bundle_sha256,receipt_json"
            " FROM atomic_bundle_receipts WHERE bundle_id=?",
            (bundle_id,),
        ).fetchone()
        if existing is not None:
            receipt = _load(existing["receipt_json"])
            if (
                existing["command_bundle_sha256"]
                != command_bundle_sha256
                or receipt.get("application_input_sha256")
                != application_input_sha256
            ):
                _fail("atomic_bundle_identity_conflict")
            return receipt
        try:
            with self._write_transaction():
                raced = self._connection.execute(
                    "SELECT command_bundle_sha256,receipt_json"
                    " FROM atomic_bundle_receipts WHERE bundle_id=?",
                    (bundle_id,),
                ).fetchone()
                if raced is not None:
                    receipt = _load(raced["receipt_json"])
                    if (
                        raced["command_bundle_sha256"]
                        != command_bundle_sha256
                        or receipt.get("application_input_sha256")
                        != application_input_sha256
                    ):
                        _fail("atomic_bundle_identity_conflict")
                    return receipt
                item_receipts = []
                for package in normalized_packages:
                    item_receipts.append(
                        self.apply_item_event(
                            package["event"],
                            package["next_item"],
                            conflict_reason_code=package[
                                "conflict_reason_code"
                            ],
                            accepted_joint_receipt=package[
                                "accepted_joint_receipt"
                            ],
                        )
                    )
                binding_receipt = (
                    None
                    if normalized_binding is None
                    else self.apply_binding_event(normalized_binding)
                )
                stored_coverage = self.put_unit_coverage(
                    normalized_coverage
                )
                body = {
                    "schema_version": (
                        ATOMIC_BUNDLE_RECEIPT_SCHEMA_VERSION
                    ),
                    "bundle_id": bundle_id,
                    "command_bundle_sha256": command_bundle_sha256,
                    "application_input_sha256": application_input_sha256,
                    "item_event_ids": [
                        receipt["event_id"] for receipt in item_receipts
                    ],
                    "binding_event_id": (
                        None
                        if binding_receipt is None
                        else binding_receipt["event_id"]
                    ),
                    "coverage_id": stored_coverage["coverage_id"],
                    "committed_at": committed_at,
                    "committed": True,
                    "raw_body_included": False,
                }
                receipt_sha256 = canonical_sha256(body)
                receipt = {
                    "receipt_id": (
                        "cws_bundle_receipt_" + receipt_sha256[:32]
                    ),
                    **body,
                    "receipt_sha256": receipt_sha256,
                }
                self._connection.execute(
                    "INSERT INTO atomic_bundle_receipts VALUES(?,?,?,?)",
                    (
                        bundle_id,
                        command_bundle_sha256,
                        receipt_sha256,
                        _json(receipt),
                    ),
                )
                return receipt
        except sqlite3.IntegrityError as exc:
            raise HouseContinuityLocalStoreError(
                "atomic_bundle_identity_conflict"
            ) from exc
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower():
                raise HouseContinuityLocalStoreError(
                    "sqlite_write_locked"
                ) from exc
            raise HouseContinuityLocalStoreError(
                "sqlite_write_failure"
            ) from exc

    def put_atomic_bundle_receipt(
        self, receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        required = {
            "receipt_id",
            "schema_version",
            "bundle_id",
            "command_bundle_sha256",
            "application_input_sha256",
            "item_event_ids",
            "binding_event_id",
            "coverage_id",
            "committed_at",
            "committed",
            "raw_body_included",
            "receipt_sha256",
        }
        if not isinstance(receipt, Mapping) or set(receipt) != required:
            _fail("invalid_atomic_bundle_receipt")
        normalized = deepcopy(dict(receipt))
        body = {
            key: value
            for key, value in normalized.items()
            if key not in {"receipt_id", "receipt_sha256"}
        }
        expected_sha = canonical_sha256(body)
        if (
            normalized["schema_version"]
            != ATOMIC_BUNDLE_RECEIPT_SCHEMA_VERSION
            or normalized["receipt_id"]
            != "cws_bundle_receipt_" + expected_sha[:32]
            or normalized["receipt_sha256"] != expected_sha
            or normalized["committed"] is not True
            or normalized["raw_body_included"] is not False
        ):
            _fail("invalid_atomic_bundle_receipt")
        _time(normalized["committed_at"])
        row = self._connection.execute(
            "SELECT receipt_json FROM atomic_bundle_receipts"
            " WHERE bundle_id=?",
            (normalized["bundle_id"],),
        ).fetchone()
        if row is not None:
            existing = _load(row["receipt_json"])
            if existing != normalized:
                _fail("atomic_bundle_identity_conflict")
            return existing
        with self._write_transaction():
            self._connection.execute(
                "INSERT INTO atomic_bundle_receipts VALUES(?,?,?,?)",
                (
                    normalized["bundle_id"],
                    normalized["command_bundle_sha256"],
                    normalized["receipt_sha256"],
                    _json(normalized),
                ),
            )
        return normalized

    def put_outbox_bundle(
        self,
        bundle: Mapping[str, Any],
        *,
        transition_event: str,
    ) -> dict[str, Any]:
        normalized = validate_outbox_bundle(bundle)
        self.register_creation_seed(
            normalized["bundle_id"],
            normalized["creation_seed_sha256"],
            entity_kind="outbox",
            created_at=normalized["prepared_at"],
        )
        row = self._connection.execute(
            "SELECT outbox_json FROM outbox_bundles WHERE bundle_id=?",
            (normalized["bundle_id"],),
        ).fetchone()
        if row is not None:
            existing = _load(row["outbox_json"])
            if existing["command_bundle_sha256"] != normalized[
                "command_bundle_sha256"
            ]:
                _fail("outbox_identity_conflict")
            validate_outbox_transition(
                existing, normalized, event=transition_event
            )
            with self._write_transaction():
                self._connection.execute(
                    "UPDATE outbox_bundles SET outbox_json=? WHERE bundle_id=?",
                    (_json(normalized), normalized["bundle_id"]),
                )
            return normalized
        validate_outbox_transition(
            None, normalized, event=transition_event
        )
        with self._write_transaction():
            self._connection.execute(
                "INSERT INTO outbox_bundles VALUES(?,?,?)",
                (
                    normalized["bundle_id"],
                    normalized["command_bundle_sha256"],
                    _json(normalized),
                ),
            )
        return normalized

    def put_joint_attestation(
        self, attestation: Mapping[str, Any]
    ) -> dict[str, Any]:
        normalized = validate_joint_attestation(attestation)
        self.register_creation_seed(
            normalized["attestation_id"],
            normalized["creation_seed_sha256"],
            entity_kind="joint_attestation",
            created_at=normalized["created_at"],
        )
        row = self._connection.execute(
            "SELECT attestation_json FROM joint_attestations"
            " WHERE attestation_id=?",
            (normalized["attestation_id"],),
        ).fetchone()
        if row is not None:
            existing = _load(row["attestation_json"])
            if existing != normalized:
                _fail("joint_attestation_identity_conflict")
            return existing
        with self._write_transaction():
            self._connection.execute(
                "INSERT INTO joint_attestations VALUES(?,?,?)",
                (
                    normalized["attestation_id"],
                    normalized["canonical_semantic_sha256"],
                    _json(normalized),
                ),
            )
        return normalized

    def put_accepted_joint_receipt(
        self, receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        try:
            normalized = validate_accepted_joint_receipt(receipt)
        except CrossGateReceiptError as exc:
            raise HouseContinuityLocalStoreError(exc.error_code) from exc
        self.register_creation_seed(
            normalized["receipt_id"],
            canonical_sha256(
                {
                    "entity_kind": "accepted_joint_receipt",
                    "receipt_id": normalized["receipt_id"],
                    "attestation_id": normalized["attestation_id"],
                    "versioned_namespace": normalized["schema_version"],
                }
            ),
            entity_kind="accepted_joint_receipt",
            created_at=normalized["committed_at"],
        )
        row = self._connection.execute(
            "SELECT receipt_json FROM accepted_joint_receipts"
            " WHERE receipt_id=? OR attestation_id=?",
            (normalized["receipt_id"], normalized["attestation_id"]),
        ).fetchone()
        if row is not None:
            existing = _load(row["receipt_json"])
            if existing != normalized:
                _fail("accepted_joint_receipt_identity_conflict")
            return existing
        try:
            with self._write_transaction():
                self._connection.execute(
                    "INSERT INTO accepted_joint_receipts VALUES(?,?,?,?,?,?)",
                    (
                        normalized["receipt_id"],
                        normalized["attestation_id"],
                        normalized["item_id"],
                        normalized["expected_revision"],
                        normalized["receipt_sha256"],
                        _json(normalized),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise HouseContinuityLocalStoreError(
                "accepted_joint_receipt_identity_conflict"
            ) from exc
        return normalized

    def read_projection(
        self,
        *,
        now: str,
        room_id: str | None,
        project_id: str | None,
        thread_id: str | None,
        explicit_item_ids: tuple[str, ...] = (),
        linked_trigger_item_ids: tuple[str, ...] = (),
        exact_relevance_item_ids: tuple[str, ...] = (),
        approved_wake_item_ids: tuple[str, ...] = (),
        after_items_read_for_test: Any | None = None,
    ) -> dict[str, Any]:
        read_time = _time(now)
        selected = []
        expiry_due = []
        projection_lineage = self._read_projection_lineage()
        explicit_ids = set(explicit_item_ids)
        linked_ids = set(linked_trigger_item_ids)
        relevance_ids = set(exact_relevance_item_ids)
        approved_ids = set(approved_wake_item_ids)
        wake_ids = explicit_ids | linked_ids | relevance_ids | approved_ids
        owns_transaction = not self._connection.in_transaction
        try:
            if owns_transaction:
                self._connection.execute("BEGIN")
            rows = self._connection.execute(
                "SELECT item_id,revision,lifecycle_state,item_json"
                " FROM items ORDER BY item_id"
            ).fetchall()
            if after_items_read_for_test is not None:
                after_items_read_for_test()
            head_sequence, head_sha256 = self._global_head()
            current_items = {}
            for row in rows:
                item = _load(row["item_json"])
                if (
                    row["item_id"] != item["item_id"]
                    or row["revision"] != item["revision"]
                    or row["lifecycle_state"] != item["lifecycle_state"]
                ):
                    _fail("item_index_json_mismatch")
                current_items[item["item_id"]] = item
            history_by_item: dict[str, dict[int, dict[str, Any]]] = {}
            if projection_lineage:
                for history_row in self._connection.execute(
                    "SELECT item_id,revision,item_json FROM item_history"
                ):
                    history_item = validate_working_set_item(
                        _load(history_row["item_json"])
                    )
                    if (
                        history_row["item_id"] != history_item["item_id"]
                        or history_row["revision"] != history_item["revision"]
                    ):
                        _fail("item_history_index_json_mismatch")
                    history_by_item.setdefault(
                        history_item["item_id"], {}
                    )[history_item["revision"]] = history_item
                for lineage in projection_lineage:
                    current = current_items.get(lineage["item_id"])
                    historical = history_by_item.get(lineage["item_id"], {}).get(
                        lineage["revision"]
                    )
                    referenced = (
                        current
                        if current is not None
                        and current["revision"] == lineage["revision"]
                        else historical
                    )
                    if (
                        referenced is None
                        or referenced["base_event_id"]
                        != lineage["item_event_id"]
                        or referenced["source_operation_ids"]
                        != lineage["source_operation_ids"]
                    ):
                        _fail("projection_lineage_binding_mismatch")
            projection_items = []
            for item in current_items.values():
                item_lineage = [
                    lineage
                    for lineage in projection_lineage
                    if lineage["item_id"] == item["item_id"]
                ]
                if item_lineage:
                    cutoff = min(
                        lineage["revision"] for lineage in item_lineage
                    )
                    candidates = [
                        candidate
                        for revision, candidate in history_by_item.get(
                            item["item_id"], {}
                        ).items()
                        if revision < cutoff
                    ]
                    if item["revision"] < cutoff:
                        candidates.append(item)
                    item = (
                        max(candidates, key=lambda value: value["revision"])
                        if candidates
                        else None
                    )
                if item is not None:
                    projection_items.append(item)
            for item in projection_items:
                freshness = self._selection_freshness(item, read_time)
                scope_match = (
                    item["scope_kind"] == "global"
                    or (
                        item["scope_kind"] == "room"
                        and item["room_id"] == room_id
                    )
                    or (
                        item["scope_kind"] == "project"
                        and item["project_id"] == project_id
                        and (
                            item["thread_id"] is None
                            or item["thread_id"] == thread_id
                        )
                    )
                )
                if freshness == "expiry_due":
                    if scope_match or item["item_id"] in wake_ids:
                        expiry_due.append(item["item_id"])
                    continue
                eligible = (
                    freshness in {"current", "recent"} and scope_match
                )
                if freshness in {"aging", "dormant"}:
                    if item["scope_kind"] == "global":
                        eligible = item["item_id"] in wake_ids
                    else:
                        eligible = scope_match or item["item_id"] in wake_ids
                if eligible:
                    wake_reason_codes = []
                    if freshness in {"aging", "dormant"}:
                        if scope_match and item["scope_kind"] == "room":
                            wake_reason_codes.append(
                                "exact_room_scope_continuation"
                            )
                        elif (
                            scope_match
                            and item["scope_kind"] == "project"
                        ):
                            wake_reason_codes.append(
                                "exact_project_scope_continuation"
                            )
                        if item["item_id"] in explicit_ids:
                            wake_reason_codes.append("explicit_item_id")
                        if item["item_id"] in linked_ids:
                            wake_reason_codes.append("linked_trigger")
                        if item["item_id"] in relevance_ids:
                            wake_reason_codes.append("exact_relevance")
                        if item["item_id"] in approved_ids:
                            wake_reason_codes.append("approved_wake")
                    selected.append(
                        {
                            "item": item,
                            "selection_freshness": freshness,
                            "wake_applied": bool(wake_reason_codes),
                            "wake_reason_codes": wake_reason_codes,
                        }
                    )
            if owns_transaction:
                self._connection.commit()
        except Exception:
            if owns_transaction and self._connection.in_transaction:
                self._connection.rollback()
            raise
        blocked = bool(expiry_due)
        return {
            "selected": selected,
            "authoritative_empty": not selected and not blocked,
            "selection_state": "expiry_due" if blocked else "ready",
            "expiry_due_item_ids": expiry_due,
            "snapshot_global_event_sequence": head_sequence,
            "snapshot_global_event_sha256": head_sha256,
        }

    def read_bound_projection(
        self,
        *,
        now: str,
        room_id: str,
        explicit_item_ids: tuple[str, ...] = (),
        linked_trigger_item_ids: tuple[str, ...] = (),
        exact_relevance_item_ids: tuple[str, ...] = (),
        approved_wake_item_ids: tuple[str, ...] = (),
        after_binding_read_for_test: Any | None = None,
        after_items_read_for_test: Any | None = None,
        allow_unbound: bool = False,
        include_authority_metadata: bool = False,
    ) -> dict[str, Any]:
        """Read one binding and its item/event projection in one SQLite snapshot."""

        if (
            not isinstance(room_id, str)
            or not room_id.startswith("cws_room_")
        ):
            _fail("invalid_bound_projection_room_id")
        if type(allow_unbound) is not bool or type(include_authority_metadata) is not bool:
            _fail("invalid_bound_projection_option")
        try:
            self._connection.execute("BEGIN")
            row = self._connection.execute(
                "SELECT room_id,revision,binding_json FROM bindings"
                " WHERE room_id=?",
                (room_id,),
            ).fetchone()
            if row is None:
                if not allow_unbound:
                    _fail("scope_binding_unavailable")
                binding = None
            else:
                binding = validate_scope_binding(_load(row["binding_json"]))
                if (
                    row["room_id"] != binding["room_id"]
                    or row["revision"] != binding["binding_revision"]
                ):
                    _fail("binding_index_json_mismatch")
            if after_binding_read_for_test is not None:
                after_binding_read_for_test()
            projection = self.read_projection(
                now=now,
                room_id=room_id,
                project_id=(None if binding is None else binding["project_id"]),
                thread_id=(None if binding is None else binding["thread_id"]),
                explicit_item_ids=explicit_item_ids,
                linked_trigger_item_ids=linked_trigger_item_ids,
                exact_relevance_item_ids=exact_relevance_item_ids,
                approved_wake_item_ids=approved_wake_item_ids,
                after_items_read_for_test=after_items_read_for_test,
            )
            authority_metadata = None
            if include_authority_metadata:
                terminal_items = []
                for item_row in self._connection.execute(
                    "SELECT item_id,revision,lifecycle_state,item_json"
                    " FROM items WHERE lifecycle_state!='active' ORDER BY item_id"
                ):
                    item = validate_working_set_item(_load(item_row["item_json"]))
                    if (
                        item_row["item_id"] != item["item_id"]
                        or item_row["revision"] != item["revision"]
                        or item_row["lifecycle_state"] != item["lifecycle_state"]
                    ):
                        _fail("item_index_json_mismatch")
                    terminal_items.append(item)
                unit_coverage = []
                for coverage_row in self._connection.execute(
                    "SELECT coverage_id,coverage_json FROM unit_coverage"
                    " ORDER BY coverage_id"
                ):
                    coverage = validate_unit_coverage(
                        _load(coverage_row["coverage_json"])
                    )
                    if coverage_row["coverage_id"] != coverage["coverage_id"]:
                        _fail("coverage_index_json_mismatch")
                    unit_coverage.append(coverage)
                authority_metadata = {
                    "terminal_items": terminal_items,
                    "unit_coverage": unit_coverage,
                }
            self._connection.commit()
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise
        result = {"binding": binding, "projection": projection}
        if authority_metadata is not None:
            result["authority_metadata"] = authority_metadata
        return result

    def read_checkpoint_snapshot(
        self,
        *,
        item_ids: tuple[str, ...],
        after_items_read_for_test: Any | None = None,
    ) -> dict[str, Any]:
        """Read exact current item revisions and the event head atomically."""

        if len(item_ids) > 24 or len(item_ids) != len(set(item_ids)):
            _fail("invalid_checkpoint_item_ids")
        if any(
            not isinstance(item_id, str)
            or not item_id.startswith("cws_item_")
            for item_id in item_ids
        ):
            _fail("invalid_checkpoint_item_ids")
        try:
            self._connection.execute("BEGIN")
            if item_ids:
                placeholders = ",".join("?" for _ in item_ids)
                rows = self._connection.execute(
                    "SELECT item_id,revision,lifecycle_state,item_json"
                    f" FROM items WHERE item_id IN ({placeholders})",
                    item_ids,
                ).fetchall()
            else:
                rows = []
            items_by_id = {}
            for row in rows:
                item = validate_working_set_item(_load(row["item_json"]))
                if (
                    row["item_id"] != item["item_id"]
                    or row["revision"] != item["revision"]
                    or row["lifecycle_state"] != item["lifecycle_state"]
                ):
                    _fail("item_index_json_mismatch")
                items_by_id[item["item_id"]] = item
            if after_items_read_for_test is not None:
                after_items_read_for_test()
            head_sequence, head_sha256 = self._global_head()
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return {
            "items": [
                items_by_id[item_id]
                for item_id in item_ids
                if item_id in items_by_id
            ],
            "missing_item_ids": [
                item_id for item_id in item_ids if item_id not in items_by_id
            ],
            "snapshot_global_event_sequence": head_sequence,
            "snapshot_global_event_sha256": head_sha256,
        }

    def _selection_freshness(
        self, item: Mapping[str, Any], now: datetime
    ) -> str:
        if item["lifecycle_state"] != "active":
            return "terminal_ineligible"
        if item["expires_at"] is not None and now >= _time(item["expires_at"]):
            return "expiry_due"
        if now <= _time(item["fresh_until"]):
            return "current"
        if now <= _time(item["aging_after"]):
            return "recent"
        if now <= _time(item["dormant_after"]):
            return "aging"
        return "dormant"

    def read_legacy_v1_1_item(
        self, value: Mapping[str, Any]
    ) -> dict[str, Any]:
        if value.get("schema_version") != LEGACY_ITEM_SCHEMA_VERSION:
            _fail("unsupported_legacy_item_schema")
        forbidden = {
            "raw_transcript",
            "provider_body",
            "memory_body",
            "vault_body",
            "self_state_body",
            "credential",
            "token",
            "secret",
        }
        if forbidden.intersection(value):
            _fail("legacy_raw_private_field_forbidden")
        if (
            value.get("authorship_kind") == "joint_explicit"
            and value.get("command_owner")
            == "house_talk_continuity_authorship_intent_v1"
        ):
            _fail("legacy_joint_solen_owner_invalid")
        return {
            "compatibility_state": (
                "legacy_read_only_requires_v1_2_authorship_evidence"
            ),
            "provider_visible_eligible": False,
            "stored_value_preserved": deepcopy(dict(value)),
        }

    def event_count(self) -> int:
        return self._connection.execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()[0]

    def doctor(self) -> dict[str, Any]:
        if self._connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            _fail("foreign_keys_disabled")
        if self._connection.execute("PRAGMA foreign_key_check").fetchone():
            _fail("foreign_key_integrity_failure")
        metadata = {
            row["key"]: row["value"]
            for row in self._connection.execute(
                "SELECT key,value FROM store_meta"
            )
        }
        if metadata != {
            "schema_version": STORE_SCHEMA_VERSION,
            "store_id": self.store_id,
        }:
            _fail("store_metadata_mismatch")

        event_rows = self._connection.execute(
            "SELECT global_sequence,event_id,owner_kind,owner_id,"
            "owner_sequence,event_json FROM events ORDER BY global_sequence"
        ).fetchall()
        events: list[dict[str, Any]] = []
        for row in event_rows:
            event = _load(row["event_json"])
            if row["owner_kind"] == "item":
                normalized = validate_working_set_event(event)
                owner_id = normalized["item_id"]
                owner_sequence = normalized["item_event_sequence"]
            elif row["owner_kind"] == "binding":
                normalized = validate_scope_binding_event(event)
                owner_id = normalized["room_id"]
                owner_sequence = normalized["binding_event_sequence"]
            else:
                _fail("event_owner_kind_invalid")
            if (
                row["global_sequence"]
                != normalized["global_event_sequence"]
                or row["event_id"] != normalized["event_id"]
                or row["owner_id"] != owner_id
                or row["owner_sequence"] != owner_sequence
            ):
                _fail("event_index_json_mismatch")
            seed = self._connection.execute(
                "SELECT entity_kind,creation_seed_sha256,created_at"
                " FROM creation_seeds WHERE entity_id=?",
                (normalized["event_id"],),
            ).fetchone()
            expected_seed = self.event_creation_seed(
                event_id=normalized["event_id"],
                event_kind=normalized["event_kind"],
                created_at=normalized["created_at"],
            )
            if (
                seed is None
                or seed["entity_kind"] != "event"
                or seed["creation_seed_sha256"] != expected_seed
                or seed["created_at"] != normalized["created_at"]
                or normalized["creation_seed_sha256"] != expected_seed
            ):
                _fail("event_creation_seed_binding_mismatch")
            events.append(normalized)
        if events:
            chain = validate_event_chains(events)
        else:
            chain = {
                "event_count": 0,
                "global_head_sequence": 0,
                "global_head_sha256": None,
                "item_heads": {},
                "binding_heads": {},
            }
        replay_items: dict[str, dict[str, Any]] = {}
        replay_item_history: dict[tuple[str, int], dict[str, Any]] = {}
        replay_bindings: dict[str, dict[str, Any]] = {}
        for event in events:
            if "item_id" in event:
                current = replay_items.get(event["item_id"])
                if event["event_kind"] == "create":
                    candidate = deepcopy(event["patch"])
                else:
                    if current is None:
                        _fail("replay_missing_item")
                    candidate = deepcopy(current)
                    candidate.update(deepcopy(event["patch"]))
                replay_items[event["item_id"]] = validate_working_set_item(
                    candidate
                )
                replay_item_history[
                    (event["item_id"], event["new_revision"])
                ] = replay_items[event["item_id"]]
            else:
                replay_bindings[event["room_id"]] = deepcopy(
                    event["to_binding"]
                )
        stored_items = {}
        for row in self._connection.execute(
            "SELECT item_id,revision,lifecycle_state,item_json FROM items"
        ):
            item = validate_working_set_item(_load(row["item_json"]))
            if (
                row["item_id"] != item["item_id"]
                or row["revision"] != item["revision"]
                or row["lifecycle_state"] != item["lifecycle_state"]
            ):
                _fail("item_index_json_mismatch")
            self._doctor_seed(
                item["item_id"],
                "item",
                item["creation_seed_sha256"],
                item["created_at"],
            )
            stored_items[row["item_id"]] = item
        stored_item_history = {}
        for row in self._connection.execute(
            "SELECT item_id,revision,item_json FROM item_history"
        ):
            item = validate_working_set_item(_load(row["item_json"]))
            if row["item_id"] != item["item_id"] or row["revision"] != item[
                "revision"
            ]:
                _fail("item_history_index_json_mismatch")
            stored_item_history[(row["item_id"], row["revision"])] = item
        stored_bindings = {}
        for row in self._connection.execute(
            "SELECT room_id,revision,binding_json FROM bindings"
        ):
            binding = validate_scope_binding(_load(row["binding_json"]))
            if (
                row["room_id"] != binding["room_id"]
                or row["revision"] != binding["binding_revision"]
            ):
                _fail("binding_index_json_mismatch")
            self._doctor_seed(
                binding["room_id"],
                "room",
                canonical_sha256(
                    {
                        "entity_kind": "room",
                        "room_id": binding["room_id"],
                        "versioned_namespace": (
                            "house_continuity_scope_binding_v1"
                        ),
                    }
                ),
                binding["created_at"],
            )
            stored_bindings[row["room_id"]] = binding
        if replay_items != stored_items:
            _fail("item_projection_replay_mismatch")
        if replay_item_history != stored_item_history:
            _fail("item_history_replay_mismatch")
        if replay_bindings != stored_bindings:
            _fail("binding_projection_replay_mismatch")

        events_by_id = {event["event_id"]: event for event in events}
        projection_lineage = self._read_projection_lineage()
        for lineage in projection_lineage:
            item = stored_item_history.get(
                (lineage["item_id"], lineage["revision"])
            )
            if item is None:
                item = stored_items.get(lineage["item_id"])
            event = events_by_id.get(lineage["item_event_id"])
            if (
                item is None
                or item["revision"] != lineage["revision"]
                or item["base_event_id"] != lineage["item_event_id"]
                or item["source_operation_ids"]
                != lineage["source_operation_ids"]
                or event is None
                or event["item_id"] != lineage["item_id"]
                or event["new_revision"] != lineage["revision"]
            ):
                _fail("projection_lineage_binding_mismatch")
        receipt_event_ids: set[str] = set()
        for row in self._connection.execute(
            "SELECT idempotency_key,command_sha256,event_id,receipt_json"
            " FROM idempotency_receipts"
        ):
            receipt_event_ids.add(row["event_id"])
            receipt = _load(row["receipt_json"])
            event = events_by_id.get(row["event_id"])
            if (
                event is None
                or row["idempotency_key"] != event["idempotency_key"]
                or row["command_sha256"] != event["command_sha256"]
                or receipt.get("event_id") != event["event_id"]
                or receipt.get("state") != "applied"
                or receipt.get("global_event_sequence")
                != event["global_event_sequence"]
                or receipt.get("global_event_sha256")
                != event["global_event_sha256"]
            ):
                _fail("idempotency_receipt_mismatch")
        if receipt_event_ids != set(events_by_id):
            _fail("idempotency_receipt_coverage_mismatch")

        conflict_count = 0
        for row in self._connection.execute(
            "SELECT receipt_id,event_id,item_id,reason_code,command_sha256,"
            "created_at,receipt_json FROM conflict_receipts"
        ):
            conflict_count += 1
            receipt = _load(row["receipt_json"])
            event = events_by_id.get(row["event_id"])
            expected = {
                "schema_version": "house_continuity_conflict_receipt_v1",
                "receipt_id": row["receipt_id"],
                "event_id": row["event_id"],
                "item_id": row["item_id"],
                "reason_code": row["reason_code"],
                "command_sha256": row["command_sha256"],
                "created_at": row["created_at"],
                "raw_body_included": False,
            }
            if (
                event is None
                or event["event_kind"] != "conflict_recorded"
                or row["reason_code"] not in _CONFLICT_REASON_CODES
                or row["item_id"] != event["item_id"]
                or row["command_sha256"] != event["command_sha256"]
                or row["created_at"] != event["created_at"]
                or receipt != expected
            ):
                _fail("conflict_receipt_mismatch")
        for event in events:
            if event.get("event_kind") == "conflict_recorded":
                row = self._connection.execute(
                    "SELECT 1 FROM conflict_receipts WHERE event_id=?",
                    (event["event_id"],),
                ).fetchone()
                if row is None:
                    _fail("conflict_receipt_missing")

        coverage_count = 0
        for row in self._connection.execute(
            "SELECT coverage_id,complete_unit_id,complete_unit_sha256,"
            "coverage_json FROM unit_coverage"
        ):
            coverage_count += 1
            coverage = validate_unit_coverage(_load(row["coverage_json"]))
            if (
                row["coverage_id"] != coverage["coverage_id"]
                or row["complete_unit_id"] != coverage["complete_unit_id"]
                or row["complete_unit_sha256"]
                != coverage["complete_unit_sha256"]
            ):
                _fail("coverage_index_json_mismatch")
            self._doctor_seed(
                coverage["coverage_id"],
                "coverage",
                coverage["creation_seed_sha256"],
                coverage["created_at"],
            )

        outbox_count = 0
        for row in self._connection.execute(
            "SELECT bundle_id,command_bundle_sha256,outbox_json"
            " FROM outbox_bundles"
        ):
            outbox_count += 1
            bundle = validate_outbox_bundle(_load(row["outbox_json"]))
            if (
                row["bundle_id"] != bundle["bundle_id"]
                or row["command_bundle_sha256"]
                != bundle["command_bundle_sha256"]
            ):
                _fail("outbox_index_json_mismatch")
            self._doctor_seed(
                bundle["bundle_id"],
                "outbox",
                bundle["creation_seed_sha256"],
                bundle["prepared_at"],
            )

        joint_count = 0
        for row in self._connection.execute(
            "SELECT attestation_id,canonical_semantic_sha256,"
            "attestation_json FROM joint_attestations"
        ):
            joint_count += 1
            attestation = validate_joint_attestation(
                _load(row["attestation_json"])
            )
            if (
                row["attestation_id"] != attestation["attestation_id"]
                or row["canonical_semantic_sha256"]
                != attestation["canonical_semantic_sha256"]
            ):
                _fail("joint_attestation_index_json_mismatch")
            self._doctor_seed(
                attestation["attestation_id"],
                "joint_attestation",
                attestation["creation_seed_sha256"],
                attestation["created_at"],
            )

        accepted_joint_count = 0
        for row in self._connection.execute(
            "SELECT receipt_id,attestation_id,item_id,expected_revision,"
            "receipt_sha256,receipt_json FROM accepted_joint_receipts"
        ):
            accepted_joint_count += 1
            try:
                receipt = validate_accepted_joint_receipt(
                    _load(row["receipt_json"])
                )
            except CrossGateReceiptError as exc:
                raise HouseContinuityLocalStoreError(
                    exc.error_code
                ) from exc
            if (
                row["receipt_id"] != receipt["receipt_id"]
                or row["attestation_id"] != receipt["attestation_id"]
                or row["item_id"] != receipt["item_id"]
                or row["expected_revision"] != receipt["expected_revision"]
                or row["receipt_sha256"] != receipt["receipt_sha256"]
            ):
                _fail("accepted_joint_receipt_index_json_mismatch")
            self._doctor_seed(
                receipt["receipt_id"],
                "accepted_joint_receipt",
                canonical_sha256(
                    {
                        "entity_kind": "accepted_joint_receipt",
                        "receipt_id": receipt["receipt_id"],
                        "attestation_id": receipt["attestation_id"],
                        "versioned_namespace": receipt["schema_version"],
                    }
                ),
                receipt["committed_at"],
            )
        atomic_bundle_count = 0
        for row in self._connection.execute(
            "SELECT bundle_id,command_bundle_sha256,receipt_sha256,"
            "receipt_json FROM atomic_bundle_receipts"
        ):
            atomic_bundle_count += 1
            receipt = _load(row["receipt_json"])
            required = {
                "receipt_id",
                "schema_version",
                "bundle_id",
                "command_bundle_sha256",
                "application_input_sha256",
                "item_event_ids",
                "binding_event_id",
                "coverage_id",
                "committed_at",
                "committed",
                "raw_body_included",
                "receipt_sha256",
            }
            body = {
                key: value
                for key, value in receipt.items()
                if key not in {"receipt_id", "receipt_sha256"}
            }
            expected_sha = canonical_sha256(body)
            referenced_event_ids = set(receipt.get("item_event_ids", []))
            if receipt.get("binding_event_id") is not None:
                referenced_event_ids.add(receipt["binding_event_id"])
            coverage_exists = self._connection.execute(
                "SELECT 1 FROM unit_coverage WHERE coverage_id=?",
                (receipt.get("coverage_id"),),
            ).fetchone()
            if (
                set(receipt) != required
                or receipt["schema_version"]
                != ATOMIC_BUNDLE_RECEIPT_SCHEMA_VERSION
                or row["bundle_id"] != receipt["bundle_id"]
                or row["command_bundle_sha256"]
                != receipt["command_bundle_sha256"]
                or row["receipt_sha256"] != receipt["receipt_sha256"]
                or receipt["receipt_sha256"] != expected_sha
                or receipt["receipt_id"]
                != "cws_bundle_receipt_" + expected_sha[:32]
                or receipt["committed"] is not True
                or receipt["raw_body_included"] is not False
                or referenced_event_ids
                - set(events_by_id)
                or coverage_exists is None
            ):
                _fail("atomic_bundle_receipt_mismatch")
            _time(receipt["committed_at"])
        return {
            **chain,
            "item_projection_count": len(stored_items),
            "binding_projection_count": len(stored_bindings),
            "item_history_count": len(stored_item_history),
            "conflict_receipt_count": conflict_count,
            "coverage_count": coverage_count,
            "gate1_compatibility_outbox_count": outbox_count,
            "schema_valid_joint_attestation_count": joint_count,
            "accepted_joint_receipt_count": accepted_joint_count,
            "atomic_bundle_receipt_count": atomic_bundle_count,
            "projection_lineage_count": len(projection_lineage),
            "outbox_authority": "gate5_owned_compatibility_only",
            "replay_exact": True,
        }

    def _doctor_seed(
        self,
        entity_id: str,
        entity_kind: str,
        creation_seed_sha256: str,
        created_at: str,
    ) -> None:
        row = self._connection.execute(
            "SELECT entity_kind,creation_seed_sha256,created_at"
            " FROM creation_seeds WHERE entity_id=?",
            (entity_id,),
        ).fetchone()
        if (
            row is None
            or row["entity_kind"] != entity_kind
            or row["creation_seed_sha256"] != creation_seed_sha256
            or row["created_at"] != created_at
        ):
            _fail("creation_seed_binding_mismatch")


__all__ = [
    "HouseContinuityLocalStoreError",
    "HouseContinuityV12LocalStore",
    "PRODUCTION_CANDIDATE_STORE_SCHEMA_VERSION",
    "PROJECTION_LINEAGE_SCHEMA_VERSION",
    "STORE_SCHEMA_VERSION",
]
