"""Operation-bound canonical complete-turn producer for Milestone-3 context.

The bridge consumes only the validated complete-unit facade and the atomic M2
reader. It serializes ingestion per candidate root, derives every M3 identity,
and records raw-free restart/replay evidence. It makes no provider/helper,
Memory, Vault, Source, self-state, Android, or source-eviction write.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping, Sequence

import house_continuity_v1_2_milestone2_authority_local as milestone2
import house_continuity_v1_2_milestone3_context_local as milestone3
from house_continuity_v1_2_executable_contracts_v0 import (
    validate_complete_continuity_unit,
)
from house_continuity_v1_2_local_store_v1 import HouseContinuityV12LocalStore


SCHEMA_VERSION = "house_continuity_milestone5_m3_producer_bridge_v1"
STORE_SCHEMA_VERSION = "house_continuity_milestone5_m3_producer_journal_v1"
DERIVATION_VERSION = "m5_complete_unit_to_m3_deterministic_v1"
COMPACTION_POLICY_VERSION = "m5_hot8_batch4_warm4_v1"
HOT_MAX_UNITS = 8
HOT_COMPACTION_BATCH = 4
WARM_MAX_EPISODES = 4
_OPERATION_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


class Milestone5M3ProducerError(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _fail(code: str) -> None:
    raise Milestone5M3ProducerError(code)


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _id(prefix: str, value: Any) -> str:
    return prefix + milestone3.canonical_sha256(value)[:32]


def _scope_from_projection(projection: Mapping[str, Any]) -> dict[str, Any]:
    binding = projection.get("binding")
    room_id = projection.get("room_id")
    if not isinstance(room_id, str) or not room_id.startswith("cws_room_"):
        _fail("m5_m3_room_binding_invalid")
    project_id = binding.get("project_id") if isinstance(binding, Mapping) else None
    if isinstance(binding, Mapping) and binding.get("room_id") != room_id:
        _fail("m5_m3_room_binding_invalid")
    if project_id is None:
        return {"scope_kind": "room", "room_id": room_id, "project_id": None}
    if not isinstance(project_id, str) or not project_id.startswith("cws_prj_"):
        _fail("m5_m3_project_binding_invalid")
    return {
        "scope_kind": "project",
        "room_id": room_id,
        "project_id": project_id,
    }


def _source_unit(
    facade: Mapping[str, Any],
    *,
    room_id: str,
    sequence: int,
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    messages = []
    for message in facade["messages"]:
        authoritative_id = str(message["message_id"])
        authoritative_parent = str(message["parent_turn_id"])
        messages.append(
            {
                "message_id": _id("m3_msg_", authoritative_id),
                "side": message["side"],
                "text": message["text"],
                "complete": message["complete"],
                "segment_index": message["segment_index"],
                "segment_count": message["segment_count"],
                "parent_turn_id": _id("m3_turn_", authoritative_parent),
                "created_at_epoch_millis": message["created_at_epoch_millis"],
            }
        )
    source_ids = [message["message_id"] for message in messages]
    value = {
        "schema_version": milestone3.SOURCE_UNIT_SCHEMA_VERSION,
        "unit_id": _id(
            "m3_unit_",
            {
                "complete_unit_id": facade["unit_id"],
                "complete_unit_sha256": facade["source_payload_sha256"],
            },
        ),
        "room_id": room_id,
        "sequence": sequence,
        "messages": messages,
        "source_ids": source_ids,
        "source_start_id": source_ids[0],
        "source_end_id": source_ids[-1],
        "authorship": "joint",
        "provenance": {
            "source_owner": (
                "house_complete_continuity_unit_v1_facade:"
                + str(facade["unit_id"])
            ),
            "snapshot_id": str(facade["source_payload_sha256"]),
        },
        "scope": dict(scope),
    }
    return milestone3.normalize_source_unit(value)


def _unknown_entry() -> dict[str, Any]:
    return {
        "availability": "unknown",
        "value": None,
        "source_unit_ids": [],
        "authorship": "source_unknown",
        "exactness": "unavailable",
        "uncertainty": "complete unit has no machine-declared value for this field",
    }


def _m2_snapshot(projection: Mapping[str, Any]) -> dict[str, Any]:
    normalized = milestone2.validate_authoritative_projection(projection)
    selected_ids = [
        str(entry["item"]["item_id"])
        for entry in normalized["selected_items"]
    ]
    return {
        "projection_sha256": normalized["projection_sha256"],
        "projection_domain": "m2_authoritative_projection_sorted_json_utf8_v1",
        "canonicalization_version": milestone3.CANONICAL_JSON_VERSION,
        "authoritative_empty": normalized["authoritative_empty"],
        "authorship_result_state": normalized["authorship_result_state"],
        "selected_item_ids": selected_ids,
    }


def _episode(
    units: Sequence[Mapping[str, Any]],
    *,
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    unit_ids = [str(unit["unit_id"]) for unit in units]
    source_ids = [source_id for unit in units for source_id in unit["source_ids"]]
    anchors = []
    for unit in units:
        for message in unit["messages"]:
            quote = str(message["text"])
            quote_bytes = quote.encode("utf-8")
            anchors.append(
                {
                    "anchor_id": _id(
                        "m3_anchor_",
                        {"unit_id": unit["unit_id"], "message_id": message["message_id"]},
                    ),
                    "source_unit_id": unit["unit_id"],
                    "source_message_id": message["message_id"],
                    "utf8_start": 0,
                    "utf8_end": len(quote_bytes),
                    "exact_quote": quote,
                    "source_representation_domain": milestone3.SOURCE_TEXT_DOMAIN,
                    "canonicalization_version": "utf8_no_normalization_v1",
                    "source_message_utf8_sha256": hashlib.sha256(quote_bytes).hexdigest(),
                    "exact_quote_utf8_sha256": hashlib.sha256(quote_bytes).hexdigest(),
                }
            )
    m2 = _m2_snapshot(projection)
    body = {
        "source_unit_ids": unit_ids,
        "m2_projection_sha256": m2["projection_sha256"],
        "derivation_version": DERIVATION_VERSION,
    }
    candidate = {
        "schema_version": milestone3.EPISODE_SCHEMA_VERSION,
        "episode_id": _id("m3_episode_", body),
        "room_id": units[0]["room_id"],
        "source_unit_ids": unit_ids,
        "source_start_id": source_ids[0],
        "source_end_id": source_ids[-1],
        "authorship": "house_derived",
        "provenance": {
            "derivation_owner": SCHEMA_VERSION,
            "derivation_version": DERIVATION_VERSION,
            "source_snapshot_sha256": milestone3.canonical_sha256(list(units)),
        },
        "scope": dict(units[0]["scope"]),
        "uncertainty": (
            "semantic structured fields remain unknown unless a canonical owner "
            "declares them"
        ),
        "exactness": "derived",
        "derived_summary": (
            f"{len(units)} complete House Talk turns; M2 state "
            f"{m2['authorship_result_state']}."
        ),
        "structured_fields": {
            field: [_unknown_entry()] for field in milestone3.STRUCTURED_FIELDS
        },
        "exact_anchors": anchors,
        "m2_snapshot": m2,
    }
    return milestone3.normalize_episode(candidate, source_units=units)


class Milestone5M3ProducerBridge:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.context_root = self.root / "context"
        self.context_root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "milestone5_m3_producer.sqlite3"
        self.connection = sqlite3.connect(self.path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operations(
              operation_id TEXT PRIMARY KEY,
              request_sha256 TEXT NOT NULL,
              receipt_json TEXT NOT NULL
            );
            """
        )
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO metadata(key,value) VALUES('schema_version',?)",
                (STORE_SCHEMA_VERSION,),
            )
        elif row["value"] != STORE_SCHEMA_VERSION:
            _fail("m5_m3_store_schema_unknown")

    def close(self) -> None:
        self.connection.close()

    def ingest_complete_unit(
        self,
        *,
        operation_id: str,
        room_id: str,
        complete_unit: Mapping[str, Any],
        working_set_store: HouseContinuityV12LocalStore,
        now: str,
    ) -> dict[str, Any]:
        if not isinstance(operation_id, str) or not _OPERATION_ID_RE.fullmatch(
            operation_id
        ):
            _fail("m5_m3_operation_id_invalid")
        facade = validate_complete_continuity_unit(complete_unit)
        if facade["unit_kind"] != "visible_exchange" or facade["complete"] is not True:
            _fail("m5_m3_complete_visible_unit_required")
        projection = milestone2.read_authoritative_projection(
            working_set_store, room_id=room_id, now=now
        )
        scope = _scope_from_projection(projection)
        request = {
            "operation_id": operation_id,
            "room_id": room_id,
            "complete_unit_id": facade["unit_id"],
            "complete_unit_sha256": facade["source_payload_sha256"],
            "m2_projection_sha256": projection["projection_sha256"],
            "derivation_version": DERIVATION_VERSION,
            "compaction_policy_version": COMPACTION_POLICY_VERSION,
        }
        request_sha = milestone3.canonical_sha256(request)
        self.connection.execute("BEGIN IMMEDIATE")
        context = Milestone3ContextStore(self.context_root)
        try:
            existing = self.connection.execute(
                "SELECT request_sha256,receipt_json FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["request_sha256"] != request_sha:
                    _fail("m5_m3_operation_replay_conflict")
                self.connection.commit()
                return json.loads(existing["receipt_json"])
            before = context.projection(room_id)
            all_entries = [
                entry for zone in before["zones"].values() for entry in zone
            ]
            unit_id = _id(
                "m3_unit_",
                {
                    "complete_unit_id": facade["unit_id"],
                    "complete_unit_sha256": facade["source_payload_sha256"],
                },
            )
            known_ids = {entry["unit_id"] for entry in all_entries}
            append_state = "idempotent_existing"
            if unit_id not in known_ids:
                sequence = max((entry["sequence"] for entry in all_entries), default=-1) + 1
                source_unit = _source_unit(
                    facade,
                    room_id=room_id,
                    sequence=sequence,
                    scope=scope,
                )
                append_attempt = _id("m3_attempt_", {"append": unit_id})
                append = context.append_hot_units(
                    room_id=room_id,
                    expected_revision=before["revision"],
                    expected_snapshot_sha256=before["projection_sha256"],
                    attempt_id=append_attempt,
                    units=[source_unit],
                )
                if append["state"] != "committed":
                    _fail("m5_m3_append_failed_closed")
                append_state = "committed"
            after_append = context.projection(room_id)
            compacted_episode_id = None
            hot_entries = list(after_append["zones"]["hot"])
            if len(hot_entries) > HOT_MAX_UNITS:
                batch_entries = hot_entries[:HOT_COMPACTION_BATCH]
                units = [
                    context.source_unit(room_id=room_id, unit_id=entry["unit_id"])
                    for entry in batch_entries
                ]
                boundary_projection = milestone2.read_authoritative_projection(
                    working_set_store, room_id=room_id, now=now
                )
                episode = _episode(units, projection=boundary_projection)
                warm_manifests = [
                    item
                    for item in after_append["episode_manifests"]
                    if item["zone"] == "warm"
                ]
                move_count = max(0, len(warm_manifests) + 1 - WARM_MAX_EPISODES)
                cold_ids = [
                    item["episode_id"] for item in warm_manifests[:move_count]
                ]
                compact = context.compact(
                    room_id=room_id,
                    expected_revision=after_append["revision"],
                    expected_snapshot_sha256=after_append["projection_sha256"],
                    attempt_id=_id("m3_attempt_", {"compact": episode["episode_id"]}),
                    episode=episode,
                    warm_to_cold_episode_ids=cold_ids,
                )
                if compact["state"] != "committed":
                    _fail("m5_m3_compaction_failed_closed")
                compacted_episode_id = episode["episode_id"]
            final_projection = context.projection(room_id)
            body = {
                "schema_version": SCHEMA_VERSION,
                "state": "committed",
                "operation_id": operation_id,
                "room_id": room_id,
                "complete_unit_id": facade["unit_id"],
                "complete_unit_sha256": facade["source_payload_sha256"],
                "complete_source_start_id_sha256": _sha_text(facade["source_start_id"]),
                "complete_source_end_id_sha256": _sha_text(facade["source_end_id"]),
                "m3_unit_id": unit_id,
                "append_state": append_state,
                "compacted_episode_id": compacted_episode_id,
                "m2_projection_sha256": projection["projection_sha256"],
                "m2_authoritative_empty": projection["authoritative_empty"],
                "m2_authorship_result_state": projection["authorship_result_state"],
                "successor_projection_sha256": final_projection["projection_sha256"],
                "successor_revision": final_projection["revision"],
                "derivation_version": DERIVATION_VERSION,
                "compaction_policy_version": COMPACTION_POLICY_VERSION,
                "provider_calls_made": False,
                "helper_calls_made": False,
                "memory_writes": 0,
                "vault_writes": 0,
                "source_writes": 0,
                "self_state_writes": 0,
                "source_eviction_enabled": False,
                "raw_material_present": False,
            }
            receipt = {**body, "receipt_sha256": milestone3.canonical_sha256(body)}
            self.connection.execute(
                "INSERT INTO operations(operation_id,request_sha256,receipt_json) VALUES(?,?,?)",
                (
                    operation_id,
                    request_sha,
                    milestone3.canonical_json_bytes(receipt).decode("utf-8"),
                ),
            )
            self.connection.commit()
            return receipt
        except Exception:
            self.connection.rollback()
            raise
        finally:
            context.close()


Milestone3ContextStore = milestone3.Milestone3ContextStore


__all__ = [
    "COMPACTION_POLICY_VERSION",
    "DERIVATION_VERSION",
    "HOT_COMPACTION_BATCH",
    "HOT_MAX_UNITS",
    "Milestone5M3ProducerBridge",
    "Milestone5M3ProducerError",
    "SCHEMA_VERSION",
    "STORE_SCHEMA_VERSION",
    "WARM_MAX_EPISODES",
]
