"""Operation-bound M5 application of an already verified and bound M2 outbox."""

from __future__ import annotations

import json
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any, Mapping

from house_continuity_v1_2_durable_preparation_outbox_local import (
    Gate1AtomicOutboxApplicationAdapter,
    HouseContinuityDurablePreparationOutboxLocal,
)
from house_continuity_v1_2_executable_contracts_v0 import canonical_sha256
from house_continuity_v1_2_local_store_v1 import HouseContinuityV12LocalStore
import house_continuity_v1_2_milestone2_authority_local as milestone2


SCHEMA_VERSION = "house_continuity_milestone5_m2_application_bridge_v1"
STORE_SCHEMA_VERSION = "house_continuity_milestone5_m2_application_journal_v1"
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,180}$")


class Milestone5M2ApplicationError(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _fail(code: str) -> None:
    raise Milestone5M2ApplicationError(code)


def _identifier(value: Any, *, code: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        _fail(code)
    return value


class Milestone5M2ApplicationBridge:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "milestone5_m2_application.sqlite3"
        self.connection = sqlite3.connect(self.path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS applications(
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
            _fail("m5_m2_store_schema_unknown")

    def close(self) -> None:
        self.connection.close()

    def apply_bound_bundle(
        self,
        *,
        operation_id: str,
        bundle_id: str,
        room_id: str,
        complete_unit_id: str,
        complete_unit_sha256: str,
        outbox: HouseContinuityDurablePreparationOutboxLocal,
        working_set_store: HouseContinuityV12LocalStore,
        now: str,
        lease_expires_at: str,
    ) -> dict[str, Any]:
        operation_id = _identifier(operation_id, code="m5_m2_operation_id_invalid")
        bundle_id = _identifier(bundle_id, code="m5_m2_bundle_id_invalid")
        room_id = _identifier(room_id, code="m5_m2_room_id_invalid")
        complete_unit_id = _identifier(
            complete_unit_id,
            code="m5_m2_complete_unit_id_invalid",
        )
        if (
            not isinstance(complete_unit_sha256, str)
            or len(complete_unit_sha256) != 64
        ):
            _fail("m5_m2_complete_unit_sha_invalid")
        if not isinstance(outbox, HouseContinuityDurablePreparationOutboxLocal):
            _fail("m5_m2_outbox_owner_invalid")
        if not isinstance(working_set_store, HouseContinuityV12LocalStore):
            _fail("m5_m2_working_set_owner_invalid")
        expected_working_root = (outbox.root / "working_set").resolve()
        if working_set_store.root != expected_working_root:
            _fail("m5_m2_owner_root_mismatch")
        request = {
            "operation_id": operation_id,
            "bundle_id": bundle_id,
            "room_id": room_id,
            "complete_unit_id": complete_unit_id,
            "complete_unit_sha256": complete_unit_sha256,
            "outbox_store_id": outbox.doctor()["store_id"],
            "working_set_store_id": working_set_store.store_id,
        }
        request_sha256 = canonical_sha256(request)
        existing = self.connection.execute(
            "SELECT request_sha256,receipt_json FROM applications WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if existing is not None:
            if existing["request_sha256"] != request_sha256:
                _fail("m5_m2_operation_replay_conflict")
            return json.loads(existing["receipt_json"])
        bundle = outbox.read_bundle(bundle_id)
        if bundle is None:
            _fail("m5_m2_bundle_missing")
        if (
            bundle["provider_operation_id"] != operation_id
            or bundle["room_id"] != room_id
        ):
            _fail("m5_m2_bundle_operation_binding_mismatch")
        operation = outbox._operation(operation_id)
        unit = operation.get("complete_unit_binding")
        if (
            not isinstance(unit, Mapping)
            or unit.get("unit_id") != complete_unit_id
            or unit.get("source_payload_sha256") != complete_unit_sha256
        ):
            _fail("m5_m2_complete_unit_binding_mismatch")
        prior_state = bundle["state"]
        if prior_state in {
            "prepared_waiting_visible",
            "visible_released_waiting_unit",
            "cancelled_before_visible",
        }:
            _fail("m5_m2_bundle_not_bound_and_eligible")
        if prior_state == "applying":
            _fail("m5_m2_application_in_progress")
        if prior_state == "conflict_recorded":
            outcome = outbox.outcome(bundle_id)
            application_state = "rejected_fail_closed"
        elif prior_state == "applied":
            outcome = outbox.outcome(bundle_id)
            application_state = "idempotent_replay"
        elif prior_state == "ready_to_apply":
            clear_lease_token = "m5lease_" + secrets.token_urlsafe(32)
            outbox.acquire_lease(
                bundle_id,
                clear_lease_token=clear_lease_token,
                now=now,
                expires_at=lease_expires_at,
            )
            outcome = outbox.apply(
                bundle_id,
                Gate1AtomicOutboxApplicationAdapter(working_set_store),
                clear_lease_token=clear_lease_token,
                now=now,
            )
            application_state = (
                "rejected_fail_closed"
                if outcome.get("state") == "conflict_recorded"
                else "applied"
            )
        else:
            _fail("m5_m2_bundle_state_unknown")
        final_bundle = outbox.read_bundle(bundle_id)
        projection = milestone2.read_authoritative_projection(
            working_set_store,
            room_id=room_id,
            now=now,
        )
        body = {
            "schema_version": SCHEMA_VERSION,
            "application_state": application_state,
            "operation_id": operation_id,
            "bundle_id": bundle_id,
            "command_bundle_sha256": final_bundle["command_bundle_sha256"],
            "room_id": room_id,
            "complete_unit_id": complete_unit_id,
            "complete_unit_sha256": complete_unit_sha256,
            "outbox_store_id": request["outbox_store_id"],
            "working_set_store_id": request["working_set_store_id"],
            "outbox_state": final_bundle["state"],
            "working_set_receipt_ids": list(
                final_bundle["working_set_receipt_ids"]
            ),
            "coverage_receipt_ids": list(final_bundle["coverage_receipt_ids"]),
            "outcome_receipt_sha256": outcome.get("receipt_sha256"),
            "m2_projection_sha256": projection["projection_sha256"],
            "m2_authoritative_empty": projection["authoritative_empty"],
            "m2_authorship_result_state": projection["authorship_result_state"],
            "provider_calls_made": False,
            "memory_writes": 0,
            "vault_writes": 0,
            "source_writes": 0,
            "self_state_writes": 0,
            "source_eviction_enabled": False,
            "raw_material_present": False,
        }
        receipt = {**body, "receipt_sha256": canonical_sha256(body)}
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.connection.execute(
                "SELECT request_sha256,receipt_json FROM applications WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["request_sha256"] != request_sha256:
                    _fail("m5_m2_operation_replay_conflict")
                stored = json.loads(existing["receipt_json"])
                if stored != receipt:
                    _fail("m5_m2_operation_replay_result_changed")
                self.connection.commit()
                return stored
            self.connection.execute(
                "INSERT INTO applications(operation_id,request_sha256,receipt_json) VALUES(?,?,?)",
                (
                    operation_id,
                    request_sha256,
                    json.dumps(
                        receipt,
                        ensure_ascii=True,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
            self.connection.commit()
            return receipt
        except Exception:
            self.connection.rollback()
            raise


__all__ = [
    "Milestone5M2ApplicationBridge",
    "Milestone5M2ApplicationError",
    "SCHEMA_VERSION",
    "STORE_SCHEMA_VERSION",
]
