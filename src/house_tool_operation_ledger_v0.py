"""Small durable receipt/replay owner for House provider-agent tool calls.

The ledger persists raw-free identities, bindings, states, and receipts plus a
separate backend-private normalized result payload needed for restart replay.
It does not own provider normalization, tool schemas, capability decisions,
dispatch, leases, retries, or workflow planning.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping

import house_provider_agent_tool_contract_v0 as contract


SCHEMA_VERSION = "house_tool_operation_ledger_schema_v1"
_HASH_RE = re.compile(r"[0-9a-f]{64}")

_METADATA_DDL = "CREATE TABLE IF NOT EXISTS ledger_metadata (schema_version TEXT PRIMARY KEY NOT NULL)"
_PARENTS_DDL = """CREATE TABLE IF NOT EXISTS parent_operations (
    parent_operation_id TEXT PRIMARY KEY NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""
_CALLS_DDL = """CREATE TABLE IF NOT EXISTS tool_calls (
    tool_call_id TEXT PRIMARY KEY NOT NULL,
    parent_operation_id TEXT NOT NULL,
    provider_leg_id TEXT NOT NULL,
    tool_call_binding_sha256 TEXT NOT NULL,
    state TEXT NOT NULL,
    receipt_binding_sha256 TEXT,
    receipt_json TEXT,
    replay_payload_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(parent_operation_id) REFERENCES parent_operations(parent_operation_id)
)"""


class ToolOperationLedgerError(RuntimeError):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ToolOperationLedgerError("invalid_identity", f"{field} is malformed.")
    return value


def _hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ToolOperationLedgerError("invalid_binding", f"{field} is malformed.")
    return value


def _call_projection(tool_call: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(tool_call, Mapping) or tool_call.get("schema_version") != contract.SCHEMA_VERSION:
        raise ToolOperationLedgerError("invalid_tool_call", "Normalized tool-call contract is unsupported.")
    return {
        "parent_operation_id": _text(tool_call.get("parent_operation_id"), "parent_operation_id"),
        "provider_leg_id": _text(tool_call.get("provider_leg_id"), "provider_leg_id"),
        "tool_call_id": _text(tool_call.get("tool_call_id"), "tool_call_id"),
        "tool_call_binding_sha256": _hash(
            tool_call.get("tool_call_binding_sha256"), "tool_call_binding_sha256"
        ),
    }


def _receipt_from_row(row: sqlite3.Row) -> dict[str, Any] | None:
    if row["receipt_json"] is None:
        return None
    receipt = json.loads(row["receipt_json"])
    if receipt.get("raw_content_present") is not False:
        raise ToolOperationLedgerError("stored_receipt_not_raw_free", "Stored receipt is not raw-free.")
    return receipt


def _canonical_replay_payload(tool_result: Mapping[str, Any]) -> str:
    if (
        not isinstance(tool_result, Mapping)
        or tool_result.get("schema_version") != contract.SCHEMA_VERSION
        or tool_result.get("raw_content_present") is not True
        or contract.canonical_sha256(tool_result.get("result")) != tool_result.get("result_sha256")
    ):
        raise ToolOperationLedgerError(
            "invalid_replay_payload", "Backend-private replay payload does not match its result hash."
        )
    return json.dumps(
        dict(tool_result), ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def _replay_payload_from_row(row: sqlite3.Row) -> dict[str, Any] | None:
    if row["replay_payload_json"] is None:
        return None
    try:
        payload = json.loads(row["replay_payload_json"])
        canonical = _canonical_replay_payload(payload)
        receipt = contract.build_tool_receipt(payload)
    except (
        json.JSONDecodeError,
        contract.ProviderAgentToolContractError,
        ToolOperationLedgerError,
    ) as exc:
        raise ToolOperationLedgerError(
            "stored_replay_payload_mismatch", "Stored replay payload is malformed."
        ) from exc
    if canonical != row["replay_payload_json"]:
        raise ToolOperationLedgerError(
            "stored_replay_payload_mismatch", "Stored replay payload is not canonical."
        )
    stored_receipt = _receipt_from_row(row)
    if (
        stored_receipt is None
        or receipt["receipt_binding_sha256"] != row["receipt_binding_sha256"]
        or receipt != stored_receipt
    ):
        raise ToolOperationLedgerError(
            "stored_replay_payload_mismatch", "Stored replay payload and receipt bindings differ."
        )
    return payload


class ToolOperationLedger:
    def __init__(self, sqlite_path: str | Path) -> None:
        self.path = Path(sqlite_path)
        if not self.path.is_absolute():
            raise ToolOperationLedgerError("unsafe_ledger_path", "Ledger path must be absolute.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def _db(self):
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._db() as db:
            db.execute(_METADATA_DDL)
            db.execute(_PARENTS_DDL)
            db.execute(_CALLS_DDL)
            versions = [row[0] for row in db.execute("SELECT schema_version FROM ledger_metadata")]
            if not versions:
                db.execute("INSERT INTO ledger_metadata(schema_version) VALUES (?)", (SCHEMA_VERSION,))
            elif versions != [SCHEMA_VERSION]:
                raise ToolOperationLedgerError("unsupported_ledger_schema", "Ledger schema version is unsupported.")

    @staticmethod
    def _public(
        row: sqlite3.Row, disposition: str, *, include_replay_payload: bool = False,
    ) -> dict[str, Any]:
        receipt = _receipt_from_row(row)
        replay_payload = _replay_payload_from_row(row) if include_replay_payload else None
        state = row["state"]
        return {
            "schema_version": SCHEMA_VERSION,
            "disposition": disposition,
            "parent_operation_id": row["parent_operation_id"],
            "provider_leg_id": row["provider_leg_id"],
            "tool_call_id": row["tool_call_id"],
            "state": state,
            "should_dispatch": state in {"proposed", "validated", "queued"},
            "receipt": receipt,
            "replay_payload": replay_payload,
            "raw_content_returned": replay_payload is not None,
        }

    def register_call(self, tool_call: Mapping[str, Any]) -> dict[str, Any]:
        """Atomically register the parent and call, or classify an exact replay."""
        call = _call_projection(tool_call)
        now = _now()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO parent_operations VALUES (?,?,?,?)",
                (call["parent_operation_id"], "accepted", now, now),
            )
            row = db.execute(
                "SELECT * FROM tool_calls WHERE tool_call_id=?", (call["tool_call_id"],)
            ).fetchone()
            if row is not None:
                try:
                    contract.compare_replay_binding(
                        dict(row),
                        call,
                        identity_field="tool_call_id",
                        binding_field="tool_call_binding_sha256",
                    )
                except contract.ProviderAgentToolContractError as exc:
                    db.rollback()
                    raise ToolOperationLedgerError(
                        "tool_call_identity_collision", "Tool-call identity has a different binding."
                    ) from exc
                disposition = {
                    "succeeded": "completed_replay",
                    "failed": "failed_replay",
                    "ambiguous": "ambiguous_replay",
                    "cancelled": "cancelled_replay",
                }.get(row["state"], "exact_replay")
                db.commit()
                return self._public(
                    row,
                    disposition,
                    include_replay_payload=row["state"] in {"succeeded", "failed"},
                )
            db.execute(
                "INSERT INTO tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    call["tool_call_id"], call["parent_operation_id"], call["provider_leg_id"],
                    call["tool_call_binding_sha256"], "proposed", None, None, None, now, now,
                ),
            )
            row = db.execute(
                "SELECT * FROM tool_calls WHERE tool_call_id=?", (call["tool_call_id"],)
            ).fetchone()
            db.commit()
            return self._public(row, "registered")

    def mark_running(self, tool_call_id: str) -> dict[str, Any]:
        """Record dispatch start without adding a lease/retry subsystem."""
        call_id = _text(tool_call_id, "tool_call_id")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tool_calls WHERE tool_call_id=?", (call_id,)).fetchone()
            if row is None:
                db.rollback()
                raise ToolOperationLedgerError("tool_call_missing", "Tool call is absent.")
            if row["state"] == "running":
                db.commit()
                return self._public(row, "exact_replay")
            if row["state"] != "proposed":
                db.rollback()
                raise ToolOperationLedgerError("tool_call_not_dispatchable", "Tool call cannot start.")
            state = row["state"]
            for next_state in ("validated", "queued", "leased", "running"):
                state = contract.validate_state_transition("tool_call", state, next_state)
            now = _now()
            db.execute("UPDATE tool_calls SET state='running',updated_at=? WHERE tool_call_id=?", (now, call_id))
            db.execute(
                "UPDATE parent_operations SET state='running',updated_at=? WHERE parent_operation_id=?",
                (now, row["parent_operation_id"]),
            )
            row = db.execute("SELECT * FROM tool_calls WHERE tool_call_id=?", (call_id,)).fetchone()
            db.commit()
            return self._public(row, "running")

    def record_result(self, tool_result: Mapping[str, Any]) -> dict[str, Any]:
        """Persist one raw-free receipt and any private replay payload exactly once."""
        try:
            receipt = contract.build_tool_receipt(tool_result)
        except contract.ProviderAgentToolContractError as exc:
            raise ToolOperationLedgerError("invalid_tool_result", "Tool result contract is invalid.") from exc
        call_id = _text(receipt["tool_call_id"], "tool_call_id")
        receipt_binding = _hash(receipt["receipt_binding_sha256"], "receipt_binding_sha256")
        receipt_json = json.dumps(receipt, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        replay_payload_json = (
            _canonical_replay_payload(tool_result)
            if receipt["state"] in {"succeeded", "failed"}
            else None
        )
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tool_calls WHERE tool_call_id=?", (call_id,)).fetchone()
            if row is None:
                db.rollback()
                raise ToolOperationLedgerError("tool_call_missing", "Tool call is absent.")
            if row["tool_call_binding_sha256"] != receipt["tool_call_binding_sha256"]:
                db.rollback()
                raise ToolOperationLedgerError("tool_call_identity_collision", "Result call binding differs.")
            if row["receipt_binding_sha256"] is not None:
                if row["receipt_binding_sha256"] != receipt_binding:
                    db.rollback()
                    raise ToolOperationLedgerError("receipt_identity_collision", "Recorded receipt differs.")
                if row["replay_payload_json"] != replay_payload_json:
                    db.rollback()
                    raise ToolOperationLedgerError(
                        "replay_payload_collision", "Same receipt has a different replay payload."
                    )
                db.commit()
                return self._public(row, "exact_replay")
            if row["state"] != "running":
                db.rollback()
                raise ToolOperationLedgerError("tool_call_not_running", "Only a running call may record a result.")
            contract.validate_state_transition("tool_call", row["state"], receipt["state"])
            now = _now()
            db.execute(
                "UPDATE tool_calls SET state=?,receipt_binding_sha256=?,receipt_json=?,replay_payload_json=?,updated_at=? WHERE tool_call_id=?",
                (receipt["state"], receipt_binding, receipt_json, replay_payload_json, now, call_id),
            )
            row = db.execute("SELECT * FROM tool_calls WHERE tool_call_id=?", (call_id,)).fetchone()
            db.commit()
            return self._public(row, "recorded")

    def cancel_before_execution(self, tool_call_id: str) -> dict[str, Any]:
        call_id = _text(tool_call_id, "tool_call_id")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tool_calls WHERE tool_call_id=?", (call_id,)).fetchone()
            if row is None:
                db.rollback()
                raise ToolOperationLedgerError("tool_call_missing", "Tool call is absent.")
            if row["state"] == "cancelled":
                db.commit()
                return self._public(row, "cancelled_replay")
            if row["state"] != "proposed":
                db.rollback()
                raise ToolOperationLedgerError("cancel_after_execution_started", "Call has already started.")
            contract.validate_state_transition("tool_call", row["state"], "cancelled")
            db.execute("UPDATE tool_calls SET state='cancelled',updated_at=? WHERE tool_call_id=?", (_now(), call_id))
            row = db.execute("SELECT * FROM tool_calls WHERE tool_call_id=?", (call_id,)).fetchone()
            db.commit()
            return self._public(row, "cancelled")

    def doctor(self) -> dict[str, Any]:
        """Expose counts and opaque IDs only; never return bindings or receipts."""
        with self._db() as db:
            counts = {row[0]: row[1] for row in db.execute("SELECT state,COUNT(*) FROM tool_calls GROUP BY state")}
            parent_ids = [row[0] for row in db.execute("SELECT parent_operation_id FROM parent_operations ORDER BY parent_operation_id")]
            call_ids = [row[0] for row in db.execute("SELECT tool_call_id FROM tool_calls ORDER BY tool_call_id")]
        return {
            "schema_version": SCHEMA_VERSION,
            "parent_operation_count": len(parent_ids),
            "tool_call_count": len(call_ids),
            "state_counts": counts,
            "parent_operation_ids": parent_ids,
            "tool_call_ids": call_ids,
            "raw_content_returned": False,
        }


__all__ = ["SCHEMA_VERSION", "ToolOperationLedger", "ToolOperationLedgerError"]
