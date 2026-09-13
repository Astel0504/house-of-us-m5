"""Gate-12R one-shot acceptance, no-provider readiness, and call isolation.

This owner is separate from the historical Gate-12 latch and stores.  It
persists only bounded identities, enums, counts, hashes, and booleans.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading
from typing import Any, Mapping


GATE_ID = (
    "HOUSE_CONTINUITY_V1_2_GATE12R_PRODUCTION_PREFLIGHT_AND_EXTERNAL_CALL_ISOLATION"
)
SWITCH_ENV = GATE_ID
ROOT_ENV = "HOUSE_CONTINUITY_V1_2_GATE12R_PRIVATE_ROOT"
OFF = "off"
CORRECTIVE_CANARY = "corrective_canary"
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
SCHEMA_VERSION = "house_continuity_v1_2_gate12r_control_v1"
RECEIPT_SCHEMA_VERSION = "house_continuity_v1_2_gate12r_receipt_v1"
ALLOWED_MAIN_PURPOSE = "provider_agent_leg"
_SAFE_STATES = frozenset(
    {"accepted_pending_readiness", "readiness_failed", "ready", "dispatched"}
)
_READINESS_STAGES = frozenset(
    {
        "not_started",
        "complete_endpoint",
        "route_selection",
        "tool_route",
        "memory_route",
        "standing_roots",
        "dynamic_root_isolation",
        "typed_assembly",
        "typed_assembly_dependency",
        "stable_message_boundary",
        "tool_semantics",
        "canonical_stable_surface",
        "serialized_stable_identity",
        "generation2_endpoint_preflight",
        "unknown_internal",
    }
)
_READINESS_ERROR_CODES = frozenset(
    {
        "none",
        "model_or_route_mismatch",
        "tools_or_broker_unavailable",
        "memory_authorship_route_unavailable",
        "root_registry_order_body_mismatch",
        "dynamic_root_isolation_failure",
        "assembly_fallback",
        "assembly_dependency_signature_mismatch",
        "stable_message_boundary_mismatch",
        "tool_semantic_mismatch",
        "canonical_stable_surface_mismatch",
        "exact_serialized_stable_message_tool_identity_mismatch",
        "unknown_internal_validation_failure",
    }
)
_PROCESS_BINDINGS: dict[str, Path] = {}
_PROCESS_BINDINGS_LOCK = threading.RLock()
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_IDENTITY_RE = re.compile(r"[A-Za-z0-9_-]{1,180}")
_PARENT_OPERATION_RE = re.compile(r"hpaop_[0-9a-f]{64}")
_STORE_ID_RE = re.compile(r"gate12r_[0-9a-f]{32}")
_READINESS_STATES = frozenset({"pending", "failed", "ready"})
_INITIAL_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "gate_id",
        "client_turn_id",
        "attempt_consumed",
        "generation2_readiness",
        "capability_issued",
        "capability_consumed",
        "provider_dispatch_performed",
        "external_transport_count",
        "raw_material_present",
    }
)
_FULL_RECEIPT_FIELDS = frozenset(
    {
        *_INITIAL_RECEIPT_FIELDS,
        "generation2_effective",
        "readiness_stage",
        "readiness_error_code",
        "denied_transport_count",
        "endpoint_request_sha256",
        "generation1_identity_sha256",
        "generation2_identity_sha256",
    }
)


class Gate12RControlError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class Gate12RExternalCallDenied(Gate12RControlError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _sha(value: bytes | str) -> str:
    body = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(body).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_sha256(value: str | None) -> str | None:
    return value if isinstance(value, str) and _SHA256_RE.fullmatch(value) else None


def _parsed_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    canonical = parsed.astimezone(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    return parsed if canonical == value else None


def _receipt_is_field_closed(row: Mapping[str, Any], receipt: Any) -> bool:
    if not isinstance(receipt, Mapping):
        return False
    fields = frozenset(receipt)
    if fields not in {_INITIAL_RECEIPT_FIELDS, _FULL_RECEIPT_FIELDS}:
        return False
    if (
        receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or receipt.get("gate_id") != GATE_ID
        or receipt.get("client_turn_id") != row["client_turn_id"]
        or _IDENTITY_RE.fullmatch(str(receipt.get("client_turn_id") or ""))
        is None
        or receipt.get("raw_material_present") is not False
        or receipt.get("attempt_consumed") is not bool(row["attempt_consumed"])
        or receipt.get("generation2_readiness") != row["readiness_state"]
        or receipt.get("generation2_readiness") not in _READINESS_STATES
        or receipt.get("capability_issued") is not bool(row["capability_issued"])
        or receipt.get("capability_consumed")
        is not bool(row["capability_consumed"])
        or receipt.get("provider_dispatch_performed")
        is not bool(row["provider_dispatch_performed"])
        or receipt.get("external_transport_count")
        != int(row["external_transport_count"])
        or type(receipt.get("external_transport_count")) is not int
        or receipt.get("external_transport_count") < 0
    ):
        return False
    if fields == _INITIAL_RECEIPT_FIELDS:
        return row["readiness_state"] == "pending"
    return (
        receipt.get("generation2_effective")
        is bool(row["generation2_effective"])
        and receipt.get("readiness_stage") == row["readiness_stage"]
        and receipt.get("readiness_error_code") == row["readiness_error_code"]
        and receipt.get("readiness_stage") in _READINESS_STAGES
        and receipt.get("readiness_error_code") in _READINESS_ERROR_CODES
        and receipt.get("denied_transport_count")
        == int(row["denied_transport_count"])
        and type(receipt.get("denied_transport_count")) is int
        and receipt.get("denied_transport_count") >= 0
        and receipt.get("endpoint_request_sha256")
        == row["endpoint_request_sha256"]
        and receipt.get("generation1_identity_sha256")
        == row["generation1_identity_sha256"]
        and receipt.get("generation2_identity_sha256")
        == row["generation2_identity_sha256"]
    )


def _attempt_row_is_bounded(row: Mapping[str, Any]) -> bool:
    parent = row["parent_operation_id"]
    state = row["state"]
    readiness = row["readiness_state"]
    external_count = row["external_transport_count"]
    denied_count = row["denied_transport_count"]
    booleans = (
        row["attempt_consumed"],
        row["generation2_effective"],
        row["capability_issued"],
        row["capability_consumed"],
        row["provider_dispatch_performed"],
    )
    created_at = _parsed_timestamp(row["created_at"])
    updated_at = _parsed_timestamp(row["updated_at"])
    state_pair_valid = (
        (
            state == "accepted_pending_readiness"
            and readiness == "pending"
            and row["readiness_stage"] == "not_started"
            and row["readiness_error_code"] == "none"
            and external_count == 0
            and row["provider_dispatch_performed"] == 0
        )
        or (
            state == "readiness_failed"
            and readiness == "failed"
            and row["readiness_stage"] != "complete_endpoint"
            and row["readiness_error_code"] != "none"
            and external_count == 0
            and row["provider_dispatch_performed"] == 0
        )
        or (
            state == "ready"
            and readiness == "ready"
            and row["readiness_stage"] == "complete_endpoint"
            and row["readiness_error_code"] == "none"
            and external_count == 0
            and row["provider_dispatch_performed"] == 0
        )
        or (
            state == "dispatched"
            and readiness == "ready"
            and row["readiness_stage"] == "complete_endpoint"
            and row["readiness_error_code"] == "none"
            and external_count == 1
            and row["provider_dispatch_performed"] == 1
        )
    )
    return (
        _IDENTITY_RE.fullmatch(str(row["client_turn_id"] or "")) is not None
        and (
            parent is None
            or _PARENT_OPERATION_RE.fullmatch(str(parent)) is not None
        )
        and state in _SAFE_STATES
        and readiness in _READINESS_STATES
        and row["readiness_stage"] in _READINESS_STAGES
        and row["readiness_error_code"] in _READINESS_ERROR_CODES
        and state_pair_valid
        and all(value in (0, 1) for value in booleans)
        and row["attempt_consumed"] == 1
        and row["capability_consumed"] <= row["capability_issued"]
        and (
            readiness == "ready"
            or (
                row["generation2_effective"] == 0
                and row["capability_issued"] == 0
                and row["capability_consumed"] == 0
            )
        )
        and (
            external_count == 0
            or (
                row["generation2_effective"] == 1
                and row["capability_issued"] == 1
            )
        )
        and type(external_count) is int
        and 0 <= external_count <= 1
        and type(denied_count) is int
        and denied_count >= 0
        and created_at is not None
        and updated_at is not None
        and created_at <= updated_at
    )


def configured(env: Mapping[str, str] | None) -> bool:
    source = env if env is not None else os.environ
    return str(source.get(SWITCH_ENV) or OFF).strip() == CORRECTIVE_CANARY


def root_from_env(env: Mapping[str, str] | None) -> Path:
    source = env if env is not None else os.environ
    raw = str(source.get(ROOT_ENV) or "").strip()
    if not raw:
        raise Gate12RControlError("gate12r_root_unconfigured")
    configured_root = Path(raw)
    if configured_root.is_symlink():
        raise Gate12RControlError("gate12r_root_symlink_invalid")
    root = configured_root.resolve()
    if not root.exists() or not root.is_dir():
        raise Gate12RControlError("gate12r_root_unavailable")
    if os.name != "nt":
        info = root.stat()
        if stat.S_IMODE(info.st_mode) != PRIVATE_DIRECTORY_MODE:
            raise Gate12RControlError("gate12r_root_mode_invalid")
        if info.st_uid != os.geteuid():
            raise Gate12RControlError("gate12r_root_owner_invalid")
    return root


def _validate_private_file(path: Path) -> None:
    if not path.exists():
        return
    if path.is_symlink() or not path.is_file():
        raise Gate12RControlError("gate12r_store_file_invalid")
    info = path.stat()
    if info.st_nlink != 1:
        raise Gate12RControlError("gate12r_store_link_count_invalid")
    if os.name != "nt":
        if stat.S_IMODE(info.st_mode) != PRIVATE_FILE_MODE:
            raise Gate12RControlError("gate12r_store_mode_invalid")
        if info.st_uid != os.geteuid():
            raise Gate12RControlError("gate12r_store_owner_invalid")


def _secure_store_files(path: Path) -> None:
    for child in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if not child.exists():
            continue
        if child.is_symlink() or not child.is_file():
            raise Gate12RControlError("gate12r_store_file_invalid")
        if child.stat().st_nlink != 1:
            raise Gate12RControlError("gate12r_store_link_count_invalid")
        if os.name != "nt":
            os.chmod(child, PRIVATE_FILE_MODE)


class Gate12RAttemptStore:
    def __init__(
        self, root: str | Path, *, require_existing: bool = False
    ) -> None:
        self.root = Path(root).resolve()
        self.path = self.root / "gate12r_attempts.sqlite3"
        if require_existing and not self.path.exists():
            raise Gate12RControlError("gate12r_store_missing")
        for child in (
            self.path,
            Path(str(self.path) + "-wal"),
            Path(str(self.path) + "-shm"),
        ):
            _validate_private_file(child)
        self.connection = sqlite3.connect(
            str(self.path), timeout=0.5, isolation_level=None
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS meta(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS latch(
              singleton INTEGER PRIMARY KEY CHECK(singleton=1),
              state TEXT NOT NULL,
              revision INTEGER NOT NULL,
              armed_at TEXT,
              consumed_at TEXT,
              client_turn_id TEXT
            );
            CREATE TABLE IF NOT EXISTS attempts(
              client_turn_id TEXT PRIMARY KEY,
              parent_operation_id TEXT,
              state TEXT NOT NULL,
              attempt_consumed INTEGER NOT NULL CHECK(attempt_consumed IN (0,1)),
              readiness_state TEXT NOT NULL,
              readiness_stage TEXT NOT NULL,
              readiness_error_code TEXT NOT NULL,
              generation2_effective INTEGER NOT NULL CHECK(generation2_effective IN (0,1)),
              capability_issued INTEGER NOT NULL CHECK(capability_issued IN (0,1)),
              capability_consumed INTEGER NOT NULL CHECK(capability_consumed IN (0,1)),
              provider_dispatch_performed INTEGER NOT NULL CHECK(provider_dispatch_performed IN (0,1)),
              external_transport_count INTEGER NOT NULL,
              denied_transport_count INTEGER NOT NULL,
              endpoint_request_sha256 TEXT,
              generation1_identity_sha256 TEXT,
              generation2_identity_sha256 TEXT,
              receipt_json TEXT NOT NULL,
              receipt_sha256 TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO meta VALUES('schema_version',?)",
                (SCHEMA_VERSION,),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO meta VALUES('store_id',?)",
                ("gate12r_" + secrets.token_hex(16),),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO latch VALUES(1,'unarmed',1,NULL,NULL,NULL)"
            )
        _secure_store_files(self.path)

    def close(self) -> None:
        self.connection.close()

    def arm_for_local_proof(self) -> None:
        """Local-test/operator seam; production activation is separately authorized."""
        with self.connection:
            row = self.connection.execute(
                "SELECT state,revision FROM latch WHERE singleton=1"
            ).fetchone()
            if row is None or row["state"] not in {"unarmed", "armed"}:
                raise Gate12RControlError("gate12r_latch_not_armable")
            self.connection.execute(
                """
                UPDATE latch SET state='armed',revision=?,armed_at=?,
                  consumed_at=NULL,client_turn_id=NULL WHERE singleton=1
                """,
                (int(row["revision"]) + 1, _now()),
            )

    def accept(
        self, *, client_turn_id: str, parent_operation_id: str | None
    ) -> dict[str, Any] | None:
        if _IDENTITY_RE.fullmatch(client_turn_id) is None:
            raise Gate12RControlError("gate12r_turn_identity_invalid")
        if (
            parent_operation_id is not None
            and _PARENT_OPERATION_RE.fullmatch(parent_operation_id) is None
        ):
            raise Gate12RControlError("gate12r_parent_operation_identity_invalid")
        at = _now()
        receipt = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "gate_id": GATE_ID,
            "client_turn_id": client_turn_id,
            "attempt_consumed": True,
            "generation2_readiness": "pending",
            "capability_issued": False,
            "capability_consumed": False,
            "provider_dispatch_performed": False,
            "external_transport_count": 0,
            "raw_material_present": False,
        }
        encoded = _canonical(receipt)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            latch = self.connection.execute(
                "SELECT state,revision FROM latch WHERE singleton=1"
            ).fetchone()
            if latch is None or latch["state"] != "armed":
                self.connection.execute("ROLLBACK")
                return None
            self.connection.execute(
                """
                UPDATE latch SET state='consumed',revision=?,consumed_at=?,
                  client_turn_id=? WHERE singleton=1 AND state='armed'
                """,
                (int(latch["revision"]) + 1, at, client_turn_id),
            )
            self.connection.execute(
                """
                INSERT INTO attempts(
                  client_turn_id,parent_operation_id,state,attempt_consumed,
                  readiness_state,readiness_stage,readiness_error_code,
                  generation2_effective,capability_issued,capability_consumed,
                  provider_dispatch_performed,external_transport_count,
                  denied_transport_count,endpoint_request_sha256,
                  generation1_identity_sha256,generation2_identity_sha256,
                  receipt_json,receipt_sha256,created_at,updated_at
                ) VALUES(
                  ?,?,'accepted_pending_readiness',1,'pending','not_started','none',
                  0,0,0,0,0,0,NULL,NULL,NULL,?,?,?,?
                )
                """,
                (
                    client_turn_id,
                    parent_operation_id,
                    encoded.decode("utf-8"),
                    _sha(encoded),
                    at,
                    at,
                ),
            )
            self.connection.execute("COMMIT")
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise
        with _PROCESS_BINDINGS_LOCK:
            _PROCESS_BINDINGS[client_turn_id] = self.root
        return deepcopy(receipt)

    def _update_receipt(self, client_turn_id: str) -> None:
        row = self.connection.execute(
            "SELECT * FROM attempts WHERE client_turn_id=?", (client_turn_id,)
        ).fetchone()
        if row is None:
            raise Gate12RControlError("gate12r_attempt_missing")
        receipt = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "gate_id": GATE_ID,
            "client_turn_id": client_turn_id,
            "attempt_consumed": bool(row["attempt_consumed"]),
            "generation2_readiness": row["readiness_state"],
            "generation2_effective": bool(row["generation2_effective"]),
            "readiness_stage": row["readiness_stage"],
            "readiness_error_code": row["readiness_error_code"],
            "capability_issued": bool(row["capability_issued"]),
            "capability_consumed": bool(row["capability_consumed"]),
            "provider_dispatch_performed": bool(
                row["provider_dispatch_performed"]
            ),
            "external_transport_count": int(row["external_transport_count"]),
            "denied_transport_count": int(row["denied_transport_count"]),
            "endpoint_request_sha256": row["endpoint_request_sha256"],
            "generation1_identity_sha256": row[
                "generation1_identity_sha256"
            ],
            "generation2_identity_sha256": row[
                "generation2_identity_sha256"
            ],
            "raw_material_present": False,
        }
        encoded = _canonical(receipt)
        self.connection.execute(
            """
            UPDATE attempts SET receipt_json=?,receipt_sha256=?,updated_at=?
            WHERE client_turn_id=?
            """,
            (encoded.decode("utf-8"), _sha(encoded), _now(), client_turn_id),
        )

    def record_readiness(
        self,
        client_turn_id: str,
        *,
        ready: bool,
        stage: str,
        error_code: str,
        endpoint_request_sha256: str | None = None,
        generation1_identity_sha256: str | None = None,
        generation2_identity_sha256: str | None = None,
    ) -> None:
        safe_endpoint_sha256 = _safe_sha256(endpoint_request_sha256)
        safe_generation1_sha256 = _safe_sha256(generation1_identity_sha256)
        safe_generation2_sha256 = _safe_sha256(generation2_identity_sha256)
        identity_evidence_complete = all(
            value is not None
            for value in (
                safe_endpoint_sha256,
                safe_generation1_sha256,
                safe_generation2_sha256,
            )
        )
        effective_ready = bool(ready and identity_evidence_complete)
        state = "ready" if effective_ready else "readiness_failed"
        safe_stage = (
            stage
            if stage in _READINESS_STAGES
            else "unknown_internal"
        )
        safe_error_code = (
            error_code
            if error_code in _READINESS_ERROR_CODES
            else "unknown_internal_validation_failure"
        )
        if ready and not identity_evidence_complete:
            safe_stage = "unknown_internal"
            safe_error_code = "unknown_internal_validation_failure"
        with self.connection:
            self.connection.execute(
                """
                UPDATE attempts SET state=?,readiness_state=?,
                  readiness_stage=?,readiness_error_code=?,
                  endpoint_request_sha256=?,generation1_identity_sha256=?,
                  generation2_identity_sha256=?,updated_at=?
                WHERE client_turn_id=?
                """,
                (
                    state,
                    "ready" if effective_ready else "failed",
                    safe_stage,
                    safe_error_code,
                    safe_endpoint_sha256,
                    safe_generation1_sha256,
                    safe_generation2_sha256,
                    _now(),
                    client_turn_id,
                ),
            )
            self._update_receipt(client_turn_id)

    def authorize_transport(self, client_turn_id: str, purpose: str) -> None:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT * FROM attempts WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            if row is None:
                self.connection.execute("ROLLBACK")
                raise Gate12RExternalCallDenied(
                    "gate12r_bound_attempt_missing"
                )
            if self.doctor()["state"] != "healthy":
                self.connection.execute("ROLLBACK")
                raise Gate12RExternalCallDenied(
                    "gate12r_store_unhealthy"
                )
            allowed = (
                purpose == ALLOWED_MAIN_PURPOSE
                and row["readiness_state"] == "ready"
                and bool(row["generation2_effective"])
                and bool(row["capability_issued"])
                and int(row["external_transport_count"]) == 0
            )
            if not allowed:
                self.connection.execute(
                    """
                    UPDATE attempts SET denied_transport_count=
                      denied_transport_count+1,updated_at=?
                    WHERE client_turn_id=?
                    """,
                    (_now(), client_turn_id),
                )
                self._update_receipt(client_turn_id)
                self.connection.execute("COMMIT")
                raise Gate12RExternalCallDenied(
                    "gate12r_external_transport_denied"
                )
            self.connection.execute(
                """
                UPDATE attempts SET state='dispatched',
                  provider_dispatch_performed=1,external_transport_count=1,
                  updated_at=? WHERE client_turn_id=?
                """,
                (_now(), client_turn_id),
            )
            self._update_receipt(client_turn_id)
            self.connection.execute("COMMIT")
        except Gate12RExternalCallDenied:
            raise
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def read_attempt(self, client_turn_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM attempts WHERE client_turn_id=?", (client_turn_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def latch_consumed_for(self, client_turn_id: str) -> bool:
        row = self.connection.execute(
            "SELECT state,client_turn_id FROM latch WHERE singleton=1"
        ).fetchone()
        return bool(
            row is not None
            and row["state"] == "consumed"
            and row["client_turn_id"] == client_turn_id
        )

    def record_inner_activation_for_local_proof(
        self,
        client_turn_id: str,
        *,
        generation2_effective: bool,
        capability_issued: bool,
    ) -> None:
        """Synthetic proof seam; real issuance requires later authority."""
        with self.connection:
            row = self.connection.execute(
                "SELECT readiness_state FROM attempts WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            if row is None or row["readiness_state"] != "ready":
                raise Gate12RControlError(
                    "gate12r_inner_activation_before_readiness"
                )
            self.connection.execute(
                """
                UPDATE attempts SET generation2_effective=?,
                  capability_issued=?,updated_at=? WHERE client_turn_id=?
                """,
                (
                    int(generation2_effective),
                    int(capability_issued),
                    _now(),
                    client_turn_id,
                ),
            )
            self._update_receipt(client_turn_id)

    def doctor(self) -> dict[str, Any]:
        integrity = self.connection.execute("PRAGMA integrity_check").fetchone()
        foreign_keys = self.connection.execute("PRAGMA foreign_key_check").fetchall()
        meta = {
            row["key"]: row["value"]
            for row in self.connection.execute(
                "SELECT key,value FROM meta"
            ).fetchall()
        }
        latch = self.connection.execute(
            "SELECT * FROM latch WHERE singleton=1"
        ).fetchone()
        rows = self.connection.execute(
            "SELECT * FROM attempts"
        ).fetchall()
        receipts_healthy = True
        for row in rows:
            hashes = (
                row["endpoint_request_sha256"],
                row["generation1_identity_sha256"],
                row["generation2_identity_sha256"],
            )
            hashes_valid = all(
                value is None or _safe_sha256(value) is not None
                for value in hashes
            )
            if row["readiness_state"] == "ready":
                hashes_valid = hashes_valid and all(
                    value is not None for value in hashes
                )
            try:
                receipt = json.loads(row["receipt_json"])
            except (TypeError, ValueError):
                receipt = None
            receipt_valid = (
                _receipt_is_field_closed(row, receipt)
                and str(row["receipt_json"])
                == _canonical(receipt).decode("utf-8")
                and _safe_sha256(row["receipt_sha256"])
                == _sha(str(row["receipt_json"]).encode("utf-8"))
            )
            receipts_healthy = (
                receipts_healthy
                and _attempt_row_is_bounded(row)
                and hashes_valid
                and receipt_valid
            )
        latch_healthy = False
        if latch is not None:
            latch_state = latch["state"]
            revision_valid = (
                type(latch["revision"]) is int and latch["revision"] >= 1
            )
            if latch_state == "unarmed":
                latch_healthy = (
                    revision_valid
                    and latch["armed_at"] is None
                    and latch["consumed_at"] is None
                    and latch["client_turn_id"] is None
                    and len(rows) == 0
                )
            elif latch_state == "armed":
                armed_at = _parsed_timestamp(latch["armed_at"])
                latch_healthy = (
                    revision_valid
                    and armed_at is not None
                    and latch["consumed_at"] is None
                    and latch["client_turn_id"] is None
                    and len(rows) == 0
                )
            elif latch_state == "consumed":
                armed_at = _parsed_timestamp(latch["armed_at"])
                consumed_at = _parsed_timestamp(latch["consumed_at"])
                matching = [
                    row
                    for row in rows
                    if row["client_turn_id"] == latch["client_turn_id"]
                ]
                latch_healthy = (
                    revision_valid
                    and armed_at is not None
                    and consumed_at is not None
                    and armed_at <= consumed_at
                    and _IDENTITY_RE.fullmatch(
                        str(latch["client_turn_id"] or "")
                    )
                    is not None
                    and len(rows) == 1
                    and len(matching) == 1
                    and matching[0]["attempt_consumed"] == 1
                    and consumed_at
                    == _parsed_timestamp(matching[0]["created_at"])
                )
        meta_healthy = (
            frozenset(meta) == {"schema_version", "store_id"}
            and meta.get("schema_version") == SCHEMA_VERSION
            and _STORE_ID_RE.fullmatch(str(meta.get("store_id") or ""))
            is not None
        )
        doctor_healthy = (
            integrity is not None
            and integrity[0] == "ok"
            and not foreign_keys
            and meta_healthy
            and latch_healthy
            and receipts_healthy
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "state": "healthy" if doctor_healthy else "unhealthy",
            "sqlite_integrity": integrity[0] if integrity else "unavailable",
            "foreign_key_violation_count": len(foreign_keys),
            "attempt_count": len(rows),
            "raw_material_detected": (
                not doctor_healthy
                or any(
                    any(
                        token in str(row["receipt_json"]).casefold()
                        for token in (
                            "authorization",
                            "current_input",
                            "provider_response",
                            "root_body",
                        )
                    )
                    for row in rows
                )
            ),
        }


def accept_natural_turn(
    *,
    env: Mapping[str, str],
    client_turn_id: str,
    parent_operation_id: str | None = None,
) -> dict[str, Any] | None:
    if not configured(env):
        return None
    store = Gate12RAttemptStore(root_from_env(env), require_existing=True)
    try:
        return store.accept(
            client_turn_id=client_turn_id,
            parent_operation_id=parent_operation_id,
        )
    finally:
        store.close()


def attempt_for_turn(
    env: Mapping[str, str], client_turn_id: str
) -> dict[str, Any] | None:
    if not configured(env):
        return None
    store = Gate12RAttemptStore(root_from_env(env), require_existing=True)
    try:
        value = store.read_attempt(client_turn_id)
        if value is not None:
            with _PROCESS_BINDINGS_LOCK:
                _PROCESS_BINDINGS[client_turn_id] = store.root
        return value
    finally:
        store.close()


def record_generation2_readiness(
    env: Mapping[str, str],
    client_turn_id: str,
    *,
    ready: bool,
    stage: str,
    error_code: str,
    endpoint_request_sha256: str | None = None,
    generation1_identity_sha256: str | None = None,
    generation2_identity_sha256: str | None = None,
) -> None:
    store = Gate12RAttemptStore(root_from_env(env), require_existing=True)
    try:
        store.record_readiness(
            client_turn_id,
            ready=ready,
            stage=stage,
            error_code=error_code,
            endpoint_request_sha256=endpoint_request_sha256,
            generation1_identity_sha256=generation1_identity_sha256,
            generation2_identity_sha256=generation2_identity_sha256,
        )
    finally:
        store.close()


def enforce_external_call_policy(
    causal_linkage: Mapping[str, Any] | None,
) -> None:
    if not isinstance(causal_linkage, Mapping):
        return
    house_turn_id = str(causal_linkage.get("house_turn_id") or "")
    purpose = str(causal_linkage.get("purpose") or "")
    if not house_turn_id:
        return
    with _PROCESS_BINDINGS_LOCK:
        root = _PROCESS_BINDINGS.get(house_turn_id)
    if root is None:
        try:
            if configured(None):
                candidate = root_from_env(None)
                probe = Gate12RAttemptStore(
                    candidate, require_existing=True
                )
                try:
                    if probe.read_attempt(house_turn_id) is not None:
                        if probe.doctor()["state"] != "healthy":
                            raise Gate12RExternalCallDenied(
                                "gate12r_store_unhealthy"
                            )
                        root = candidate
                    elif probe.latch_consumed_for(house_turn_id):
                        raise Gate12RExternalCallDenied(
                            "gate12r_bound_attempt_missing"
                        )
                finally:
                    probe.close()
        except Gate12RExternalCallDenied:
            raise
        except Gate12RControlError as exc:
            raise Gate12RExternalCallDenied(
                "gate12r_configured_store_unavailable"
            ) from exc
    if root is None:
        return
    store = Gate12RAttemptStore(root, require_existing=True)
    try:
        store.authorize_transport(house_turn_id, purpose)
    finally:
        store.close()


def build_no_provider_generation2_preflight(
    *,
    root: str | Path,
    client_turn_id: str,
    provider_operation_id: str,
    session_id: str,
    issued_at: str,
    expires_at: str,
    generation1_selection: Any,
    broker: Any,
) -> dict[str, Any]:
    """Construct and attest the complete Generation-2 endpoint without transport."""
    import house_continuity_v1_2_gate12_protected_shadow as gate12
    import house_continuity_v1_2_standing_root_generation2_local as generation2

    room_id = gate12._room_id(session_id)
    issued = _parsed_timestamp(issued_at)
    expires = _parsed_timestamp(expires_at)
    if (
        not provider_operation_id
        or provider_operation_id == client_turn_id
        or issued is None
        or expires is None
        or expires != issued + timedelta(minutes=60)
    ):
        raise Gate12RControlError(
            "unknown_internal_validation_failure"
        )
    command_context = gate12._command_context(
        room_id,
        provider_operation_id,
    )
    sentinel = "cwc_" + ("R" * 43)
    offer = generation2.continuity_offer(
        capability=sentinel,
        command_context=command_context,
        expires_at=expires_at,
        client_turn_id=client_turn_id,
        room_id=room_id,
        provider_operation_id=provider_operation_id,
        maximum_total_operations=1,
    )
    readiness = generation2.build_local_readiness_attestation(root)
    candidate = generation2.build_generation2_candidate(
        generation1_selection=generation1_selection,
        broker=broker,
        capability=sentinel,
        command_context=command_context,
        readiness=readiness,
        offer=offer,
    )
    attestation = generation2.attest_generation2_candidate(candidate)
    endpoint_sha = _sha(_canonical(candidate.generation2_request))
    return {
        "schema_version": "house_continuity_v1_2_gate12r_preflight_v1",
        "state": "ready",
        "effective_generation": generation2.GENERATION_2,
        "generation1_identity": deepcopy(candidate.generation1_identity),
        "generation2_identity": deepcopy(candidate.generation2_identity),
        "endpoint_request_sha256": endpoint_sha,
        "standing_root_card_count": attestation["standing_root_card_count"],
        "continuity_instruction_count": 1,
        "dynamic_offer_last_before_current_input": True,
        "capability_issued": False,
        "provider_calls_made": False,
        "raw_material_present": False,
    }


__all__ = [
    "CORRECTIVE_CANARY",
    "GATE_ID",
    "Gate12RAttemptStore",
    "Gate12RControlError",
    "Gate12RExternalCallDenied",
    "OFF",
    "ROOT_ENV",
    "SWITCH_ENV",
    "accept_natural_turn",
    "attempt_for_turn",
    "build_no_provider_generation2_preflight",
    "configured",
    "enforce_external_call_policy",
    "record_generation2_readiness",
]
