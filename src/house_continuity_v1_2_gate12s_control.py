"""Gate-12S runtime activation, fresh one-shot ownership, and rehearsal isolation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from typing import Any, Mapping

import house_continuity_v1_2_gate12_protected_shadow as gate12
import house_continuity_v1_2_gate12r_control as gate12r
import house_continuity_v1_2_contract_schema_v0 as contracts
import house_continuity_v1_2_milestone2_authority_local as milestone2
import house_continuity_v1_2_milestone3_context_local as milestone3
import house_continuity_v1_2_milestone4_memory_integration_local as milestone4
import house_continuity_v1_2_milestone5_candidate as milestone5
import house_continuity_v1_2_route_binding_local as route_binding_local
import house_continuity_v1_2_standing_root_generation2_local as generation2
import house_continuity_v1_2_structured_terminal_result_v1 as structured_terminal


GATE_ID = (
    "HOUSE_CONTINUITY_V1_2_GATE12S_RUNTIME_INNER_ACTIVATION_AND_INTERCEPTED_REHEARSAL"
)
SWITCH_ENV = GATE_ID
ROOT_ENV = "HOUSE_CONTINUITY_V1_2_GATE12S_PRIVATE_ROOT"
DEPLOYED_COMMIT_ENV = "HOUSE_CONTINUITY_V1_2_GATE12S_DEPLOYED_COMMIT"
REHEARSAL_TURN_ENV = "HOUSE_CONTINUITY_V1_2_GATE12S_REHEARSAL_TURN_ID"
OFF = "off"
REHEARSAL = "intercepted_rehearsal"
LIVE_CANARY = "live_canary"
ALLOWED_MAIN_PURPOSE = "provider_agent_leg"
SCHEMA_VERSION = "house_continuity_v1_2_gate12s_control_v2"
RECEIPT_SCHEMA_VERSION = "house_continuity_v1_2_gate12s_receipt_v2"
_MODES = frozenset({REHEARSAL, LIVE_CANARY})
PREDECESSOR_ATTESTATION_SCHEMA_VERSION = (
    "house_m5_checkpoint_b_predecessor_attestation_v1"
)
_IDENTITY_RE = re.compile(r"[A-Za-z0-9_-]{1,180}")
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_PREDECESSOR_REVIEW_RE = re.compile(
    r"passed:predecessor-attestation:[0-9a-f]{64}"
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
        "gate12s_capability_issue_failed",
        "gate12s_activation_precondition_failed",
        "gate12s_exact_activation_identity_mismatch",
        "gate12s_operation_binding_mismatch",
        "gate12s_preflight_activation_endpoint_mismatch",
        "gate12s_final_request_endpoint_mismatch",
        "gate12s_activation_failed",
        "unknown_internal_validation_failure",
    }
)
_ATTEMPT_STATES = frozenset(
    {
        "accepted_pending_readiness",
        "readiness_failed",
        "ready",
        "activation_pending",
        "activated",
        "intercept_authorized",
        "dispatched",
        "completed",
    }
)
_READINESS_STATES = frozenset({"pending", "failed", "ready"})
_LATCH_STATES = frozenset({"unarmed", "armed", "consumed"})
_CAPABILITY_ID_RE = re.compile(r"cwcap_[0-9a-f]{32}")
_BOUNDED_ID_RE = re.compile(r"[A-Za-z0-9:_-]{1,180}")
_STORE_ID_RE = re.compile(r"gate12s_[0-9a-f]{32}")
_PREFIX_OR_CACHE_RE = re.compile(r"[A-Za-z0-9._:-]{1,180}")
_PRIVATE_TEXT_TOKENS = (
    "authorization",
    "bearer ",
    "current_input",
    "provider_response",
    "root_body",
    "cwc_",
)
_PROCESS_BINDINGS: dict[str, tuple[Path, str]] = {}
_RESERVATIONS: dict[str, gate12.Gate12Reservation] = {}
_PREPARED_CAPABILITIES: dict[str, tuple[str, str]] = {}
_PREPARED_SELECTIONS: dict[str, "Gate12SPreparedSelection"] = {}
_PREPARED_OPERATIONS: dict[str, "Gate12SPreparedOperation"] = {}
_LOCK = threading.RLock()


class Gate12SControlError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class Gate12SExternalCallDenied(Gate12SControlError):
    pass


_PREDECESSOR_ROOT_ALLOWED_ENTRIES = frozenset(
    {
        "gate12s_attempts.sqlite3",
        "gate12s_attempts.sqlite3-wal",
        "gate12s_attempts.sqlite3-shm",
    }
)


def _validate_predecessor_root_shape(root: Path) -> None:
    """Reject non-fresh roots before any attestation-store write is possible."""

    if root.is_symlink() or not root.is_dir():
        raise Gate12SControlError(
            "gate12s_predecessor_attestation_root_not_fresh"
        )
    try:
        paths = list(root.iterdir())
    except OSError:
        raise Gate12SControlError(
            "gate12s_predecessor_attestation_root_not_fresh"
        ) from None
    if any(
        path.name not in _PREDECESSOR_ROOT_ALLOWED_ENTRIES
        or path.is_symlink()
        or not path.is_file()
        for path in paths
    ):
        raise Gate12SControlError(
            "gate12s_predecessor_attestation_root_not_fresh"
        )
    database = root / "gate12s_attempts.sqlite3"
    if database.is_symlink() or not database.is_file():
        raise Gate12SControlError(
            "gate12s_predecessor_attestation_root_not_fresh"
        )


@dataclass(frozen=True)
class Gate12SPreparedSelection:
    client_turn_id: str
    provider_operation_id: str
    operation_binding_sha256: str
    reservation: gate12.Gate12Reservation = field(repr=False)
    candidate: Any = field(repr=False)
    selection: Any = field(repr=False)
    milestone5_artifact_sha256: str | None = None


@dataclass(frozen=True)
class Gate12SPreparedOperation:
    client_turn_id: str
    provider_operation_id: str
    operation_binding_sha256: str
    reservation: gate12.Gate12Reservation = field(repr=False)
    selection: Any = field(repr=False)
    endpoint_request_body: bytes = field(repr=False)
    endpoint_request_sha256: str
    runtime_artifact: Any = field(repr=False)
    milestone5_artifact_sha256: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _parsed_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timezone.utc.utcoffset(parsed)
        or _now_from_datetime(parsed) != value
    ):
        return None
    return parsed


def _now_from_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _contains_private_text(value: Any) -> bool:
    return isinstance(value, str) and any(
        token in value.casefold() for token in _PRIVATE_TEXT_TOKENS
    )


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha(value: bytes | str) -> str:
    body = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(body).hexdigest()


def configured(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return str(source.get(SWITCH_ENV) or OFF).strip() in _MODES


def mode_from_env(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    value = str(source.get(SWITCH_ENV) or OFF).strip()
    return value if value in _MODES else OFF


def effective_mode(env: Mapping[str, str] | None = None) -> str:
    requested = mode_from_env(env)
    if requested == OFF:
        return OFF
    try:
        store = Gate12SAttemptStore(
            root_from_env(env), require_existing=True
        )
        try:
            latch = store.connection.execute(
                "SELECT state FROM latches WHERE mode=?", (requested,)
            ).fetchone()
            return (
                requested
                if latch is not None and latch["state"] == "armed"
                else OFF
            )
        finally:
            store.close()
    except Exception:
        return OFF


def root_from_env(env: Mapping[str, str] | None = None) -> Path:
    source = env if env is not None else os.environ
    raw = str(source.get(ROOT_ENV) or "").strip()
    if not raw:
        raise Gate12SControlError("gate12s_root_unconfigured")
    root = Path(raw).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        root.chmod(0o700)
    return root


def _requested_root_from_env(env: Mapping[str, str] | None = None) -> Path:
    """Read a root for preflight without creating or chmod-ing it."""

    source = env if env is not None else os.environ
    raw = str(source.get(ROOT_ENV) or "").strip()
    if not raw:
        raise Gate12SControlError("gate12s_root_unconfigured")
    return Path(raw)


def semantic_root(root: str | Path, mode: str) -> Path:
    if mode not in _MODES:
        raise Gate12SControlError("gate12s_mode_invalid")
    value = Path(root).resolve() / ("semantic_rehearsal" if mode == REHEARSAL else "semantic_live")
    value.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        value.chmod(0o700)
    return value


def _gate12_terminal_state(
    root: str | Path, mode: str, provider_operation_id: str
) -> str | None:
    control_path = Path(root).resolve() / (
        "semantic_rehearsal" if mode == REHEARSAL else "semantic_live"
    ) / "gate12_control.sqlite3"
    if not control_path.is_file():
        return None
    connection = sqlite3.connect(
        f"file:{control_path.as_posix()}?mode=ro", uri=True
    )
    try:
        row = connection.execute(
            "SELECT state FROM turns WHERE operation_id=?",
            (provider_operation_id,),
        ).fetchone()
        return None if row is None else str(row[0])
    finally:
        connection.close()


def _gate12_env(
    env: Mapping[str, str], root: str | Path, mode: str
) -> dict[str, str]:
    value = dict(env)
    value[gate12.SWITCH_ENV] = gate12.PROTECTED_SHADOW
    value[gate12.ROOT_ENV] = str(semantic_root(root, mode))
    value[gate12.DEPLOYED_COMMIT_ENV] = str(
        env.get(DEPLOYED_COMMIT_ENV) or env.get(gate12.DEPLOYED_COMMIT_ENV) or ""
    )
    value[generation2.GENERATION_SELECTOR] = generation2.GENERATION_2
    return value


def _semantic_activation_valid(
    root: Path, row: Mapping[str, Any], *, require_issued: bool
) -> bool:
    semantic = Path(root).resolve() / (
        "semantic_rehearsal"
        if row["mode"] == REHEARSAL
        else "semantic_live"
    )
    if not (
        (semantic / "gate12_control.sqlite3").is_file()
        and (
            semantic
            / "continuity_capability_terminal_parser_local.sqlite3"
        ).is_file()
    ):
        return False
    control = gate12.Gate12ControlStore(semantic)
    registry = gate12.HouseContinuityCapabilityRegistryLocal(
        semantic, protected_shadow_only=True
    )
    try:
        control_row = control.connection.execute(
            "SELECT * FROM turns WHERE operation_id=?",
            (row["provider_operation_id"],),
        ).fetchone()
        if control_row is None:
            return False
        control_receipt = json.loads(control_row["receipt_json"])
        capability = registry.read(str(row["capability_id"] or ""))
        registry_doctor = registry.doctor(require_outbox_links=True)
        allowed_capability_states = (
            {"issued"} if require_issued else {
                "issued",
                "prepared_consumed",
                "closed_unused",
                "invalid_consumed",
                "invalidated",
                "rejected_consumed",
            }
        )
        return bool(
            control.doctor(require_current_boot=require_issued)["state"]
            == "healthy"
            and registry_doctor.get("sqlite_integrity") == "ok"
            and registry_doctor.get("raw_private_material_detected") is False
            and control_receipt.get("client_turn_id")
            == row["client_turn_id"]
            and control_receipt.get("provider_operation_id")
            == row["provider_operation_id"]
            and control_receipt.get("capability_id") == row["capability_id"]
            and isinstance(capability, Mapping)
            and capability.get("capability_id") == row["capability_id"]
            and capability.get("client_turn_id") == row["client_turn_id"]
            and capability.get("provider_operation_id")
            == row["provider_operation_id"]
            and capability.get("state") in allowed_capability_states
        )
    except Exception:
        return False
    finally:
        registry.close()
        control.close()


class Gate12SAttemptStore:
    def __init__(self, root: str | Path, *, require_existing: bool = False) -> None:
        self._requested_root = Path(root)
        self.root = self._requested_root.resolve()
        self.path = self.root / "gate12s_attempts.sqlite3"
        if require_existing and not self.path.exists():
            raise Gate12SControlError("gate12s_store_missing")
        self.connection = sqlite3.connect(
            str(self.path), timeout=1.0, isolation_level=None
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
            CREATE TABLE IF NOT EXISTS predecessor_attestations(
              attestation_sha256 TEXT PRIMARY KEY,
              attestation_body_json TEXT NOT NULL,
              schema_version TEXT NOT NULL,
              target_batch_id TEXT NOT NULL UNIQUE,
              target_manifest_sha256 TEXT NOT NULL,
              target_package_commit TEXT NOT NULL,
              target_package_tree TEXT NOT NULL,
              target_operator_wrapper_commit TEXT NOT NULL,
              target_operator_wrapper_tree TEXT NOT NULL,
              target_row_order_json TEXT NOT NULL,
              target_row_identity_sha256 TEXT NOT NULL,
              first_row_predecessor_json TEXT NOT NULL,
              accepted_current_deployment_json TEXT NOT NULL,
              historical_predecessor_json TEXT NOT NULL,
              durable_marker TEXT NOT NULL,
              recorded_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS predecessor_attestations_immutable_update
            BEFORE UPDATE ON predecessor_attestations
            BEGIN
              SELECT RAISE(ABORT, 'predecessor_attestation_immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS predecessor_attestations_immutable_delete
            BEFORE DELETE ON predecessor_attestations
            BEGIN
              SELECT RAISE(ABORT, 'predecessor_attestation_immutable');
            END;
            CREATE TABLE IF NOT EXISTS latches(
              mode TEXT PRIMARY KEY,
              state TEXT NOT NULL,
              revision INTEGER NOT NULL,
              armed_at TEXT,
              consumed_at TEXT,
              client_turn_id TEXT
            );
            CREATE TABLE IF NOT EXISTS operation_bindings(
              client_turn_id TEXT PRIMARY KEY,
              provider_operation_id TEXT NOT NULL UNIQUE,
              session_id TEXT NOT NULL,
              room_id TEXT NOT NULL,
              issued_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              capability_id TEXT NOT NULL,
              capability_sha256 TEXT NOT NULL,
              capability_creation_seed_sha256 TEXT NOT NULL,
              route_binding_json TEXT,
              route_binding_sha256 TEXT,
              command_context_json TEXT,
              command_context_sha256 TEXT,
              binding_sha256 TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS operation_bindings_immutable_update
            BEFORE UPDATE ON operation_bindings
            BEGIN
              SELECT RAISE(ABORT, 'operation_binding_immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS operation_bindings_immutable_delete
            BEFORE DELETE ON operation_bindings
            BEGIN
              SELECT RAISE(ABORT, 'operation_binding_immutable');
            END;
            CREATE TABLE IF NOT EXISTS attempts(
              client_turn_id TEXT PRIMARY KEY,
              mode TEXT NOT NULL,
              state TEXT NOT NULL,
              readiness_state TEXT NOT NULL,
              readiness_error_code TEXT NOT NULL,
              generation2_effective INTEGER NOT NULL CHECK(generation2_effective IN (0,1)),
              capability_issued INTEGER NOT NULL CHECK(capability_issued IN (0,1)),
              capability_consumed INTEGER NOT NULL CHECK(capability_consumed IN (0,1)),
              main_transport_authorized INTEGER NOT NULL CHECK(main_transport_authorized IN (0,1)),
              provider_dispatch_performed INTEGER NOT NULL CHECK(provider_dispatch_performed IN (0,1)),
              external_transport_count INTEGER NOT NULL,
              denied_transport_count INTEGER NOT NULL,
              intercepted_transport_count INTEGER NOT NULL,
              endpoint_request_sha256 TEXT,
              activation_endpoint_sha256 TEXT,
              final_request_sha256 TEXT,
              generation1_identity_sha256 TEXT,
              generation2_identity_sha256 TEXT,
              provider_operation_id TEXT NOT NULL,
              operation_binding_sha256 TEXT NOT NULL,
              effective_assembly_version TEXT,
              generation2_prefix_version TEXT,
              generation2_cache_key TEXT,
              exact_stable_messages_sha256 TEXT,
              exact_tool_block_sha256 TEXT,
              milestone5_artifact_required INTEGER NOT NULL DEFAULT 0
                CHECK(milestone5_artifact_required IN (0,1)),
              milestone5_artifact_sha256 TEXT,
              capability_id TEXT,
              outbox_bundle_id TEXT,
              complete_unit_id TEXT,
              receipt_json TEXT NOT NULL,
              receipt_sha256 TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(client_turn_id)
                REFERENCES operation_bindings(client_turn_id),
              FOREIGN KEY(operation_binding_sha256)
                REFERENCES operation_bindings(binding_sha256)
            );
            """
        )
        attempt_columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(attempts)")
        }
        operation_binding_columns = {
            row["name"]
            for row in self.connection.execute(
                "PRAGMA table_info(operation_bindings)"
            )
        }
        with self.connection:
            for column_name in (
                "route_binding_json",
                "route_binding_sha256",
                "command_context_json",
                "command_context_sha256",
            ):
                if column_name not in operation_binding_columns:
                    self.connection.execute(
                        "ALTER TABLE operation_bindings ADD COLUMN "
                        + column_name
                        + " TEXT"
                    )
            if "milestone5_artifact_required" not in attempt_columns:
                self.connection.execute(
                    "ALTER TABLE attempts ADD COLUMN milestone5_artifact_required "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            if "milestone5_artifact_sha256" not in attempt_columns:
                self.connection.execute(
                    "ALTER TABLE attempts ADD COLUMN milestone5_artifact_sha256 TEXT"
                )
            self.connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS
                  attempts_milestone5_requirement_immutable_update
                BEFORE UPDATE OF milestone5_artifact_required,
                  milestone5_artifact_sha256 ON attempts
                WHEN OLD.milestone5_artifact_required=1 AND (
                  NEW.milestone5_artifact_required<>1 OR
                  NEW.milestone5_artifact_sha256<>OLD.milestone5_artifact_sha256
                )
                BEGIN
                  SELECT RAISE(ABORT, 'milestone5_artifact_requirement_immutable');
                END
                """
            )
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO meta VALUES('schema_version',?)",
                (SCHEMA_VERSION,),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO meta VALUES('store_id',?)",
                ("gate12s_" + secrets.token_hex(16),),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO meta VALUES('rehearsal_review_state','pending')"
            )
            for mode in sorted(_MODES):
                self.connection.execute(
                    "INSERT OR IGNORE INTO latches VALUES(?,'unarmed',1,NULL,NULL,NULL)",
                    (mode,),
                )
        self._secure()

    def _secure(self) -> None:
        if os.name == "posix":
            for value in (
                self.path,
                Path(str(self.path) + "-wal"),
                Path(str(self.path) + "-shm"),
            ):
                if value.exists():
                    value.chmod(0o600)

    def close(self) -> None:
        self.connection.close()

    def _receipt(self, client_turn_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM attempts WHERE client_turn_id=?", (client_turn_id,)
        ).fetchone()
        if row is None:
            raise Gate12SControlError("gate12s_attempt_missing")
        return {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "gate_id": GATE_ID,
            "client_turn_id": client_turn_id,
            "mode": row["mode"],
            "attempt_consumed": True,
            "generation2_readiness": row["readiness_state"],
            "readiness_error_code": row["readiness_error_code"],
            "generation2_effective": bool(row["generation2_effective"]),
            "capability_issued": bool(row["capability_issued"]),
            "capability_consumed": bool(row["capability_consumed"]),
            "main_transport_authorized": bool(row["main_transport_authorized"]),
            "provider_dispatch_performed": bool(row["provider_dispatch_performed"]),
            "external_transport_count": int(row["external_transport_count"]),
            "denied_transport_count": int(row["denied_transport_count"]),
            "intercepted_transport_count": int(row["intercepted_transport_count"]),
            "endpoint_request_sha256": row["endpoint_request_sha256"],
            "activation_endpoint_sha256": row[
                "activation_endpoint_sha256"
            ],
            "final_request_sha256": row["final_request_sha256"],
            "generation1_identity_sha256": row["generation1_identity_sha256"],
            "generation2_identity_sha256": row["generation2_identity_sha256"],
            "provider_operation_id": row["provider_operation_id"],
            "operation_binding_sha256": row[
                "operation_binding_sha256"
            ],
            "effective_assembly_version": row["effective_assembly_version"],
            "generation2_prefix_version": row["generation2_prefix_version"],
            "generation2_cache_key": row["generation2_cache_key"],
            "exact_stable_messages_sha256": row[
                "exact_stable_messages_sha256"
            ],
            "exact_tool_block_sha256": row["exact_tool_block_sha256"],
            "milestone5_artifact_required": bool(
                row["milestone5_artifact_required"]
            ),
            "milestone5_artifact_sha256": row[
                "milestone5_artifact_sha256"
            ],
            "capability_id": row["capability_id"],
            "outbox_bundle_id": row["outbox_bundle_id"],
            "complete_unit_id": row["complete_unit_id"],
            "semantic_application_enabled": False,
            "safe_for_source_eviction": False,
            "raw_material_present": False,
        }

    def _update_receipt(self, client_turn_id: str) -> dict[str, Any]:
        receipt = self._receipt(client_turn_id)
        encoded = _canonical(receipt)
        self.connection.execute(
            "UPDATE attempts SET receipt_json=?,receipt_sha256=?,updated_at=? WHERE client_turn_id=?",
            (encoded.decode("utf-8"), _sha(encoded), _now(), client_turn_id),
        )
        self._secure()
        return receipt

    def arm(self, mode: str) -> dict[str, Any]:
        if mode not in _MODES:
            raise Gate12SControlError("gate12s_mode_invalid")
        if self.doctor()["state"] != "healthy":
            raise Gate12SControlError("gate12s_store_unhealthy")
        with self.connection:
            row = self.connection.execute(
                "SELECT * FROM latches WHERE mode=?", (mode,)
            ).fetchone()
            rearming_completed_live = False
            if (
                row is not None
                and mode == LIVE_CANARY
                and row["state"] == "consumed"
                and row["client_turn_id"]
            ):
                prior = self.connection.execute(
                    "SELECT * FROM attempts WHERE client_turn_id=?",
                    (row["client_turn_id"],),
                ).fetchone()
                prior_terminal_state = (
                    _gate12_terminal_state(
                        self.root,
                        LIVE_CANARY,
                        str(prior["provider_operation_id"]),
                    )
                    if prior is not None
                    else None
                )
                terminal_contract_valid = bool(
                    prior is not None
                    and (
                        (
                            bool(prior["outbox_bundle_id"])
                            and bool(prior["complete_unit_id"])
                            and prior_terminal_state
                            == "ready_to_apply_shadow_only"
                        )
                        or (
                            not prior["outbox_bundle_id"]
                            and not prior["complete_unit_id"]
                            and prior_terminal_state
                            == "explicit_solen_no_semantic_delta"
                        )
                    )
                )
                rearming_completed_live = bool(
                    prior is not None
                    and prior["mode"] == LIVE_CANARY
                    and prior["state"] == "completed"
                    and prior["generation2_effective"]
                    and prior["capability_issued"]
                    and prior["capability_consumed"]
                    and prior["main_transport_authorized"]
                    and prior["provider_dispatch_performed"]
                    and prior["external_transport_count"] == 1
                    and prior["intercepted_transport_count"] == 0
                    and terminal_contract_valid
                )
            if row is None or not (
                row["state"] == "unarmed" or rearming_completed_live
            ):
                raise Gate12SControlError("gate12s_latch_not_armable")
            other = self.connection.execute(
                "SELECT state FROM latches WHERE mode<>?", (mode,)
            ).fetchone()
            if other is not None and other["state"] == "armed":
                raise Gate12SControlError("gate12s_modes_cannot_coexist")
            if mode == LIVE_CANARY:
                review = self.connection.execute(
                    "SELECT value FROM meta WHERE key='rehearsal_review_state'"
                ).fetchone()
                if review is None or not str(review["value"]).startswith("passed:"):
                    raise Gate12SControlError(
                        "gate12s_live_requires_rehearsal_review_pass"
                    )
            self.connection.execute(
                "UPDATE latches SET state='armed',revision=?,armed_at=?,"
                "consumed_at=NULL,client_turn_id=NULL WHERE mode=?",
                (int(row["revision"]) + 1, _now(), mode),
            )
        return {"mode": mode, "state": "armed", "raw_material_present": False}

    def read_latch(self, mode: str) -> dict[str, Any]:
        if mode not in _MODES:
            raise Gate12SControlError("gate12s_mode_invalid")
        row = self.connection.execute(
            "SELECT * FROM latches WHERE mode=?", (mode,)
        ).fetchone()
        if row is None:
            raise Gate12SControlError("gate12s_latch_missing")
        return dict(row)

    def restore_latch_after_failed_inner_arm(
        self,
        mode: str,
        *,
        prior_latch: Mapping[str, Any],
        expected_armed_latch: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            current = self.read_latch(mode)
            if current != dict(expected_armed_latch):
                raise Gate12SControlError(
                    "gate12s_failed_inner_arm_latch_drift"
                )
            if (
                current["state"] != "armed"
                or int(current["revision"])
                != int(prior_latch["revision"]) + 1
            ):
                raise Gate12SControlError(
                    "gate12s_failed_inner_arm_revision_mismatch"
                )
            self.connection.execute(
                "UPDATE latches SET state=?,revision=?,armed_at=?,"
                "consumed_at=?,client_turn_id=? WHERE mode=? AND state=? "
                "AND revision=?",
                (
                    prior_latch["state"],
                    prior_latch["revision"],
                    prior_latch["armed_at"],
                    prior_latch["consumed_at"],
                    prior_latch["client_turn_id"],
                    mode,
                    current["state"],
                    current["revision"],
                ),
            )
            if self.connection.execute(
                "SELECT changes()"
            ).fetchone()[0] != 1:
                raise Gate12SControlError(
                    "gate12s_failed_inner_arm_restore_missed"
                )
            restored = self.read_latch(mode)
            if restored != dict(prior_latch):
                raise Gate12SControlError(
                    "gate12s_failed_inner_arm_restore_mismatch"
                )
            self.connection.execute("COMMIT")
            return restored
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def mark_rehearsal_review_pass(self, review_sha256: str) -> dict[str, Any]:
        if _SHA_RE.fullmatch(str(review_sha256 or "")) is None:
            raise Gate12SControlError("gate12s_review_identity_invalid")
        if self.doctor()["state"] != "healthy":
            raise Gate12SControlError("gate12s_store_unhealthy")
        latch = self.connection.execute(
            "SELECT * FROM latches WHERE mode=?", (REHEARSAL,)
        ).fetchone()
        attempt = (
            self.connection.execute(
                "SELECT * FROM attempts WHERE client_turn_id=?",
                (latch["client_turn_id"],),
            ).fetchone()
            if latch is not None and latch["client_turn_id"]
            else None
        )
        if not (
            latch is not None
            and latch["state"] == "consumed"
            and attempt is not None
            and attempt["state"] == "completed"
            and attempt["generation2_effective"]
            and attempt["capability_issued"]
            and attempt["capability_consumed"]
            and attempt["main_transport_authorized"]
            and attempt["external_transport_count"] == 0
            and attempt["intercepted_transport_count"] == 1
            and attempt["outbox_bundle_id"]
            and attempt["complete_unit_id"]
        ):
            raise Gate12SControlError(
                "gate12s_rehearsal_not_passable"
            )
        semantic = semantic_root(self.root, REHEARSAL)
        control = gate12.Gate12ControlStore(semantic)
        registry = gate12.HouseContinuityCapabilityRegistryLocal(
            semantic, protected_shadow_only=True
        )
        outbox = gate12.HouseContinuityDurablePreparationOutboxLocal(
            semantic, protected_shadow_only=True
        )
        try:
            turn = control.connection.execute(
                "SELECT receipt_json FROM turns WHERE operation_id=?",
                (attempt["provider_operation_id"],),
            ).fetchone()
            turn_receipt = (
                json.loads(turn["receipt_json"]) if turn is not None else {}
            )
            capability = registry.read(str(attempt["capability_id"] or ""))
            bundle = outbox.read_bundle(str(attempt["outbox_bundle_id"] or ""))
            registry_doctor = registry.doctor(require_outbox_links=True)
            outbox_doctor = outbox.doctor()
            semantic_healthy = bool(
                control.doctor(require_current_boot=False)["state"]
                == "healthy"
                and registry_doctor.get("sqlite_integrity") == "ok"
                and registry_doctor.get("raw_private_material_detected")
                is False
                and outbox_doctor.get("foreign_keys_enabled") is True
                and outbox_doctor.get("raw_body_detected") is False
                and turn_receipt.get("completion_state")
                == "ready_to_apply_shadow_only"
                and turn_receipt.get("outbox_bundle_id")
                == attempt["outbox_bundle_id"]
                and turn_receipt.get("complete_unit_id")
                == attempt["complete_unit_id"]
                and turn_receipt.get("unit_binding_state") == "bound"
                and turn_receipt.get("semantic_application_enabled") is False
                and turn_receipt.get("safe_for_source_eviction") is False
                and isinstance(capability, Mapping)
                and capability.get("state") == "prepared_consumed"
                and capability.get("outbox_bundle_id")
                == attempt["outbox_bundle_id"]
                and isinstance(bundle, Mapping)
                and bundle.get("bundle_id") == attempt["outbox_bundle_id"]
                and bundle.get("unit_binding_state") == "bound"
            )
            if not semantic_healthy:
                raise Gate12SControlError(
                    "gate12s_semantic_rehearsal_evidence_invalid"
                )
        finally:
            outbox.close()
            registry.close()
            control.close()
        with self.connection:
            self.connection.execute(
                "UPDATE meta SET value=? WHERE key='rehearsal_review_state'",
                ("passed:" + review_sha256,),
            )
        return {
            "state": "passed",
            "review_sha256": review_sha256,
            "raw_material_present": False,
        }

    def mark_predecessor_attestation_pass(
        self,
        attestation: Mapping[str, Any],
        *,
        target_manifest_sha256: str,
    ) -> dict[str, Any]:
        """Record an accepted historical proof on a genuinely fresh root.

        This is a distinct control-plane transition from
        ``mark_rehearsal_review_pass``. It records only the reviewed,
        hash-bound attestation and a durable projection of its authority
        inputs; it never imports historical attempt contents or arms a latch.
        """

        _validate_predecessor_root_shape(self._requested_root)
        if self.root != self._requested_root.resolve():
            raise Gate12SControlError(
                "gate12s_predecessor_attestation_root_not_fresh"
            )
        try:
            import house_m5_checkpoint_b_predecessor_attestation_v1 as contract

            validated = contract.validate_attestation(attestation)
        except Exception:
            raise Gate12SControlError(
                "gate12s_predecessor_attestation_invalid"
            ) from None
        if (
            _SHA_RE.fullmatch(str(target_manifest_sha256 or "")) is None
            or validated["target"]["manifest_sha256"]
            != target_manifest_sha256
        ):
            raise Gate12SControlError(
                "gate12s_predecessor_attestation_manifest_mismatch"
            )

        target = validated["target"]
        marker = (
            "passed:predecessor-attestation:"
            + validated["attestation_sha256"]
        )
        body_json = _canonical(validated).decode("utf-8")
        target_row_order_json = _canonical(target["row_order"]).decode(
            "utf-8"
        )
        first_row_predecessor_json = _canonical(
            target["first_row_predecessor"]
        ).decode("utf-8")
        accepted_deployment_json = _canonical(
            validated["accepted_current_deployment"]
        ).decode("utf-8")
        historical_predecessor_json = _canonical(
            validated["historical_predecessor"]
        ).decode("utf-8")

        doctor = self.doctor()
        if doctor["state"] != "healthy":
            raise Gate12SControlError("gate12s_store_unhealthy")
        meta = dict(
            self.connection.execute("SELECT key,value FROM meta").fetchall()
        )
        review = str(meta.get("rehearsal_review_state") or "")
        latches = {
            row["mode"]: dict(row)
            for row in self.connection.execute(
                "SELECT * FROM latches ORDER BY mode"
            ).fetchall()
        }
        attempt_count = int(
            self.connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        )
        binding_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM operation_bindings"
            ).fetchone()[0]
        )
        existing = self.connection.execute(
            "SELECT * FROM predecessor_attestations "
            "WHERE target_batch_id=?",
            (target["batch_id"],),
        ).fetchone()
        fresh_latches = (
            set(latches) == _MODES
            and all(
                latch["state"] == "unarmed"
                and int(latch["revision"]) == 1
                and latch["armed_at"] is None
                and latch["consumed_at"] is None
                and latch["client_turn_id"] is None
                for latch in latches.values()
            )
        )
        expected = {
            "attestation_sha256": validated["attestation_sha256"],
            "attestation_body_json": body_json,
            "schema_version": validated["schema_version"],
            "target_batch_id": target["batch_id"],
            "target_manifest_sha256": target["manifest_sha256"],
            "target_package_commit": target["package_commit"],
            "target_package_tree": target["package_tree"],
            "target_operator_wrapper_commit": target[
                "operator_wrapper_commit"
            ],
            "target_operator_wrapper_tree": target[
                "operator_wrapper_tree"
            ],
            "target_row_order_json": target_row_order_json,
            "target_row_identity_sha256": target["row_identity_sha256"],
            "first_row_predecessor_json": first_row_predecessor_json,
            "accepted_current_deployment_json": accepted_deployment_json,
            "historical_predecessor_json": historical_predecessor_json,
            "durable_marker": marker,
        }
        if existing is not None:
            if any(existing[key] != value for key, value in expected.items()):
                raise Gate12SControlError(
                    "gate12s_predecessor_attestation_conflict"
                )
            if (
                review != marker
                or attempt_count != 0
                or binding_count != 0
                or not fresh_latches
            ):
                raise Gate12SControlError(
                    "gate12s_predecessor_attestation_replay_state_invalid"
                )
            return {
                "state": "passed",
                "attestation_sha256": validated["attestation_sha256"],
                "target_batch_id": target["batch_id"],
                "target_manifest_sha256": target["manifest_sha256"],
                "marker": marker,
                "replayed": True,
                "recorded_at": existing["recorded_at"],
                "raw_material_present": False,
            }

        if (
            review != "pending"
            or attempt_count != 0
            or binding_count != 0
            or not fresh_latches
        ):
            raise Gate12SControlError(
                "gate12s_predecessor_attestation_requires_fresh_root"
            )

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            current_review = self.connection.execute(
                "SELECT value FROM meta WHERE key='rehearsal_review_state'"
            ).fetchone()
            current_attempt_count = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM attempts"
                ).fetchone()[0]
            )
            current_binding_count = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM operation_bindings"
                ).fetchone()[0]
            )
            current_existing = self.connection.execute(
                "SELECT attestation_sha256 FROM predecessor_attestations "
                "WHERE target_batch_id=?",
                (target["batch_id"],),
            ).fetchone()
            if (
                current_review is None
                or current_review["value"] != "pending"
                or current_attempt_count != 0
                or current_binding_count != 0
                or current_existing is not None
            ):
                raise Gate12SControlError(
                    "gate12s_predecessor_attestation_state_changed"
                )
            recorded_at = _now()
            self.connection.execute(
                """
                INSERT INTO predecessor_attestations(
                  attestation_sha256,attestation_body_json,schema_version,
                  target_batch_id,target_manifest_sha256,target_package_commit,
                  target_package_tree,target_operator_wrapper_commit,
                  target_operator_wrapper_tree,target_row_order_json,
                  target_row_identity_sha256,first_row_predecessor_json,
                  accepted_current_deployment_json,historical_predecessor_json,
                  durable_marker,recorded_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    validated["attestation_sha256"],
                    body_json,
                    validated["schema_version"],
                    target["batch_id"],
                    target["manifest_sha256"],
                    target["package_commit"],
                    target["package_tree"],
                    target["operator_wrapper_commit"],
                    target["operator_wrapper_tree"],
                    target_row_order_json,
                    target["row_identity_sha256"],
                    first_row_predecessor_json,
                    accepted_deployment_json,
                    historical_predecessor_json,
                    marker,
                    recorded_at,
                ),
            )
            self.connection.execute(
                "UPDATE meta SET value=? "
                "WHERE key='rehearsal_review_state' AND value='pending'",
                (marker,),
            )
            if self.connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise Gate12SControlError(
                    "gate12s_predecessor_attestation_marker_missed"
                )
            self.connection.execute("COMMIT")
        except Gate12SControlError:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise Gate12SControlError(
                "gate12s_predecessor_attestation_write_failed"
            ) from None
        self._secure()
        return {
            "state": "passed",
            "attestation_sha256": validated["attestation_sha256"],
            "target_batch_id": target["batch_id"],
            "target_manifest_sha256": target["manifest_sha256"],
            "marker": marker,
            "replayed": False,
            "recorded_at": recorded_at,
            "raw_material_present": False,
        }

    def accept(
        self,
        client_turn_id: str,
        mode: str,
        *,
        provider_operation_id: str,
        session_id: str,
        route_binding_request: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if (
            _IDENTITY_RE.fullmatch(client_turn_id) is None
            or _IDENTITY_RE.fullmatch(provider_operation_id) is None
            or provider_operation_id == client_turn_id
            or not provider_operation_id.startswith("hpaop_")
            or _IDENTITY_RE.fullmatch(session_id) is None
            or mode not in _MODES
        ):
            raise Gate12SControlError("gate12s_turn_identity_invalid")
        at = _now()
        issued_at = at
        expires_at = _now_from_datetime(
            _parsed_timestamp(issued_at) + timedelta(minutes=60)
        )
        if route_binding_request is None:
            route_binding = None
            command_context = None
            room_id = gate12._room_id(session_id)
        else:
            route_binding, command_context = (
                route_binding_local.resolve_operation_binding(
                    working_set_root=(
                        semantic_root(self.root, mode) / "working_set"
                    ),
                    route_request=route_binding_request,
                    operation_id=provider_operation_id,
                    now=issued_at,
                )
            )
            if route_binding["transient_session_id"] != session_id:
                raise Gate12SControlError(
                    "gate12s_operation_binding_mismatch"
                )
            room_id = route_binding["room_id"]
        route_binding_json = (
            None
            if route_binding is None
            else _canonical(route_binding).decode("utf-8")
        )
        route_binding_sha256 = (
            None
            if route_binding is None
            else _sha(_canonical(route_binding))
        )
        command_context_json = (
            None
            if command_context is None
            else _canonical(command_context).decode("utf-8")
        )
        command_context_sha256 = (
            None
            if command_context is None
            else _sha(_canonical(command_context))
        )
        clear_capability = "cwc_" + secrets.token_urlsafe(32)[:43]
        capability_id = "cwcap_" + secrets.token_hex(16)
        capability_sha256 = _sha(clear_capability)
        capability_creation_seed_sha256 = _sha(
            "gate12-capability:" + provider_operation_id
        )
        binding = {
            "schema_version": (
                "house_continuity_v1_2_gate12s_operation_binding_v2"
                if route_binding is not None
                else "house_continuity_v1_2_gate12s_operation_binding_v1"
            ),
            "client_turn_id": client_turn_id,
            "provider_operation_id": provider_operation_id,
            "session_id": session_id,
            "room_id": room_id,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "capability_id": capability_id,
            "capability_sha256": capability_sha256,
            "capability_creation_seed_sha256": (
                capability_creation_seed_sha256
            ),
        }
        if route_binding is not None:
            binding.update(
                {
                    "route_binding": route_binding,
                    "route_binding_sha256": route_binding_sha256,
                    "command_context": command_context,
                    "command_context_sha256": command_context_sha256,
                }
            )
        binding_sha256 = _sha(_canonical(binding))
        initial = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "gate_id": GATE_ID,
            "client_turn_id": client_turn_id,
            "mode": mode,
            "provider_operation_id": provider_operation_id,
            "operation_binding_sha256": binding_sha256,
            "attempt_consumed": True,
            "generation2_readiness": "pending",
            "raw_material_present": False,
        }
        encoded = _canonical(initial)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            latch = self.connection.execute(
                "SELECT * FROM latches WHERE mode=?", (mode,)
            ).fetchone()
            if latch is None or latch["state"] != "armed":
                self.connection.execute("ROLLBACK")
                return None
            self.connection.execute(
                "UPDATE latches SET state='consumed',revision=?,consumed_at=?,client_turn_id=? WHERE mode=? AND state='armed'",
                (int(latch["revision"]) + 1, at, client_turn_id, mode),
            )
            self.connection.execute(
                """
                INSERT INTO operation_bindings(
                  client_turn_id,provider_operation_id,session_id,room_id,
                  issued_at,expires_at,capability_id,capability_sha256,
                  capability_creation_seed_sha256,route_binding_json,
                  route_binding_sha256,command_context_json,
                  command_context_sha256,binding_sha256,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    client_turn_id,
                    provider_operation_id,
                    session_id,
                    room_id,
                    issued_at,
                    expires_at,
                    capability_id,
                    capability_sha256,
                    capability_creation_seed_sha256,
                    route_binding_json,
                    route_binding_sha256,
                    command_context_json,
                    command_context_sha256,
                    binding_sha256,
                    at,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO attempts(
                  client_turn_id,mode,state,readiness_state,
                  readiness_error_code,generation2_effective,
                  capability_issued,capability_consumed,
                  main_transport_authorized,provider_dispatch_performed,
                  external_transport_count,denied_transport_count,
                  intercepted_transport_count,endpoint_request_sha256,
                  activation_endpoint_sha256,final_request_sha256,
                  generation1_identity_sha256,generation2_identity_sha256,
                  provider_operation_id,operation_binding_sha256,
                  effective_assembly_version,
                  generation2_prefix_version,generation2_cache_key,
                  exact_stable_messages_sha256,exact_tool_block_sha256,
                  capability_id,outbox_bundle_id,complete_unit_id,
                  receipt_json,receipt_sha256,created_at,updated_at
                ) VALUES(
                  ?,?,'accepted_pending_readiness','pending','none',
                  0,0,0,0,0,0,0,0,NULL,NULL,NULL,NULL,NULL,?,?,NULL,
                  NULL,NULL,NULL,NULL,NULL,NULL,NULL,?,?,?,?
                )
                """,
                (
                    client_turn_id,
                    mode,
                    provider_operation_id,
                    binding_sha256,
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
        self._secure()
        with _LOCK:
            _PROCESS_BINDINGS[client_turn_id] = (self.root, mode)
            _PREPARED_CAPABILITIES[client_turn_id] = (
                clear_capability,
                capability_id,
            )
        return deepcopy(initial)

    def read_operation_binding(
        self, client_turn_id: str
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM operation_bindings WHERE client_turn_id=?",
            (client_turn_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def read_attempt(self, client_turn_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM attempts WHERE client_turn_id=?", (client_turn_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def bind_milestone5_artifact_requirement(
        self,
        client_turn_id: str,
        *,
        provider_operation_id: str,
        artifact_sha256: str,
    ) -> dict[str, Any]:
        if _SHA_RE.fullmatch(str(artifact_sha256 or "")) is None:
            raise Gate12SControlError(
                "gate12s_milestone5_artifact_requirement_invalid"
            )
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT state,provider_operation_id,"
                "milestone5_artifact_required,milestone5_artifact_sha256 "
                "FROM attempts WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            if (
                row is None
                or row["provider_operation_id"] != provider_operation_id
                or row["state"] != "accepted_pending_readiness"
            ):
                raise Gate12SControlError(
                    "gate12s_milestone5_artifact_requirement_binding_failed"
                )
            if row["milestone5_artifact_required"]:
                if row["milestone5_artifact_sha256"] != artifact_sha256:
                    raise Gate12SControlError(
                        "gate12s_milestone5_artifact_requirement_mismatch"
                    )
            elif row["milestone5_artifact_sha256"] is not None:
                raise Gate12SControlError(
                    "gate12s_milestone5_artifact_requirement_mismatch"
                )
            else:
                self.connection.execute(
                    "UPDATE attempts SET milestone5_artifact_required=1,"
                    "milestone5_artifact_sha256=?,updated_at=? "
                    "WHERE client_turn_id=?",
                    (artifact_sha256, _now(), client_turn_id),
                )
            self.connection.commit()
        except Exception:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise
        receipt = self._update_receipt(client_turn_id)
        self._secure()
        return receipt

    def recover_incomplete_activation(
        self, client_turn_id: str
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM attempts WHERE client_turn_id=?",
            (client_turn_id,),
        ).fetchone()
        if row is None or row["state"] != "activation_pending":
            return dict(row) if row is not None else None
        semantic = Path(self.root).resolve() / (
            "semantic_rehearsal"
            if row["mode"] == REHEARSAL
            else "semantic_live"
        )
        control = None
        registry = None
        try:
            if (
                (semantic / "gate12_control.sqlite3").is_file()
                and (
                    semantic
                    / "continuity_capability_terminal_parser_local.sqlite3"
                ).is_file()
            ):
                control = gate12.Gate12ControlStore(semantic)
                inner = control.connection.execute(
                    "SELECT * FROM turns WHERE operation_id=?",
                    (row["provider_operation_id"],),
                ).fetchone()
                if inner is not None:
                    receipt = json.loads(inner["receipt_json"])
                    capability_id = str(receipt.get("capability_id") or "")
                    registry = gate12.HouseContinuityCapabilityRegistryLocal(
                        semantic, protected_shadow_only=True
                    )
                    capability = registry.read(capability_id)
                    if (
                        isinstance(capability, Mapping)
                        and capability.get("state") == "issued"
                    ):
                        registry.invalidate(
                            capability_id,
                            client_turn_id=row["client_turn_id"],
                            room_id=capability["room_id"],
                            provider_operation_id=row[
                                "provider_operation_id"
                            ],
                            protocol_version=capability["protocol_version"],
                            terminal_response_sha256=_sha(b""),
                            at=_now(),
                        )
                    control.update_turn(
                        row["provider_operation_id"],
                        state="activation_failed",
                        values={
                            "error_code": "gate12s_activation_crash_recovered",
                            "semantic_application_enabled": False,
                            "safe_for_source_eviction": False,
                        },
                    )
        finally:
            if registry is not None:
                registry.close()
            if control is not None:
                control.close()
        with self.connection:
            self.connection.execute(
                """
                UPDATE attempts SET state='readiness_failed',
                   readiness_state='failed',
                   readiness_error_code='gate12s_activation_failed',
                   endpoint_request_sha256=NULL,
                   activation_endpoint_sha256=NULL,
                   final_request_sha256=NULL,
                  generation1_identity_sha256=NULL,
                  generation2_identity_sha256=NULL,
                  effective_assembly_version=NULL,
                  generation2_prefix_version=NULL,
                  generation2_cache_key=NULL,
                  exact_stable_messages_sha256=NULL,
                  exact_tool_block_sha256=NULL
                WHERE client_turn_id=? AND state='activation_pending'
                """,
                (client_turn_id,),
            )
            self._update_receipt(client_turn_id)
        return self.read_attempt(client_turn_id)

    def record_readiness(
        self,
        client_turn_id: str,
        *,
        ready: bool,
        error_code: str,
        endpoint_request_sha256: str | None = None,
        generation1_identity_sha256: str | None = None,
        generation2_identity_sha256: str | None = None,
        provider_operation_id: str | None = None,
        effective_assembly_version: str | None = None,
        generation2_prefix_version: str | None = None,
        generation2_cache_key: str | None = None,
        exact_stable_messages_sha256: str | None = None,
        exact_tool_block_sha256: str | None = None,
    ) -> dict[str, Any]:
        hashes = (
            endpoint_request_sha256,
            generation1_identity_sha256,
            generation2_identity_sha256,
            exact_stable_messages_sha256,
            exact_tool_block_sha256,
        )
        identities = (
            effective_assembly_version,
            generation2_prefix_version,
            generation2_cache_key,
        )
        valid = bool(
            all(
                isinstance(value, str) and _SHA_RE.fullmatch(value)
                for value in hashes
            )
            and _IDENTITY_RE.fullmatch(str(provider_operation_id or ""))
            is not None
            and all(
                isinstance(value, str)
                and _PREFIX_OR_CACHE_RE.fullmatch(value) is not None
                for value in identities
            )
        )
        safe_error_code = (
            error_code
            if error_code in _READINESS_ERROR_CODES
            else "unknown_internal_validation_failure"
        )
        effective = bool(ready and valid and safe_error_code == "none")
        with self.connection:
            current = self.connection.execute(
                "SELECT state,provider_operation_id FROM attempts"
                " WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            allowed_states = (
                {"accepted_pending_readiness"}
                if effective
                else {
                    "accepted_pending_readiness",
                    "ready",
                    "activation_pending",
                }
            )
            if (
                current is None
                or current["state"] not in allowed_states
                or current["provider_operation_id"]
                != provider_operation_id
            ):
                raise Gate12SControlError(
                    "gate12s_readiness_transition_invalid"
                )
            self.connection.execute(
                """
                UPDATE attempts SET state=?,readiness_state=?,readiness_error_code=?,
                  endpoint_request_sha256=?,generation1_identity_sha256=?,
                  generation2_identity_sha256=?,
                  effective_assembly_version=?,generation2_prefix_version=?,
                  generation2_cache_key=?,exact_stable_messages_sha256=?,
                  exact_tool_block_sha256=? WHERE client_turn_id=?
                """,
                (
                    "ready" if effective else "readiness_failed",
                    "ready" if effective else "failed",
                    "none" if effective else safe_error_code,
                    hashes[0] if effective else None,
                    hashes[1] if effective else None,
                    hashes[2] if effective else None,
                    identities[0] if effective else None,
                    identities[1] if effective else None,
                    identities[2] if effective else None,
                    hashes[3] if effective else None,
                    hashes[4] if effective else None,
                    client_turn_id,
                ),
            )
            return self._update_receipt(client_turn_id)

    def record_activation(
        self,
        client_turn_id: str,
        *,
        capability_id: str,
        generation2_identity_sha256: str,
        operation_binding_sha256: str,
        activation_endpoint_sha256: str,
    ) -> dict[str, Any]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT * FROM attempts WHERE client_turn_id=?", (client_turn_id,)
            ).fetchone()
            if (
                row is None
                or row["state"] != "activation_pending"
                or row["readiness_state"] != "ready"
                or row["generation2_identity_sha256"] != generation2_identity_sha256
                or row["operation_binding_sha256"]
                != operation_binding_sha256
                or row["endpoint_request_sha256"]
                != activation_endpoint_sha256
                or row["generation2_effective"]
                or row["capability_issued"]
            ):
                self.connection.execute("ROLLBACK")
                raise Gate12SControlError("gate12s_activation_precondition_failed")
            self.connection.execute(
                """
                UPDATE attempts SET state='activated',generation2_effective=1,
                  capability_issued=1,capability_id=?,
                  activation_endpoint_sha256=? WHERE client_turn_id=?
                """,
                (
                    capability_id,
                    activation_endpoint_sha256,
                    client_turn_id,
                ),
            )
            receipt = self._update_receipt(client_turn_id)
            self.connection.execute("COMMIT")
            return receipt
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def record_final_request_boundary(
        self,
        client_turn_id: str,
        *,
        provider_operation_id: str,
        final_request_sha256: str,
    ) -> dict[str, Any]:
        if _SHA_RE.fullmatch(final_request_sha256) is None:
            raise Gate12SControlError(
                "gate12s_final_request_endpoint_mismatch"
            )
        with self.connection:
            row = self.connection.execute(
                "SELECT * FROM attempts WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            if (
                row is None
                or row["state"] != "activated"
                or row["provider_operation_id"] != provider_operation_id
                or row["endpoint_request_sha256"] != final_request_sha256
                or row["activation_endpoint_sha256"]
                != final_request_sha256
                or row["final_request_sha256"] is not None
            ):
                raise Gate12SControlError(
                    "gate12s_final_request_endpoint_mismatch"
                )
            self.connection.execute(
                "UPDATE attempts SET final_request_sha256=?"
                " WHERE client_turn_id=?",
                (final_request_sha256, client_turn_id),
            )
            return self._update_receipt(client_turn_id)

    def begin_activation(self, client_turn_id: str) -> dict[str, Any]:
        with self.connection:
            row = self.connection.execute(
                "SELECT * FROM attempts WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            if (
                row is None
                or row["state"] != "ready"
                or row["readiness_state"] != "ready"
            ):
                raise Gate12SControlError(
                    "gate12s_activation_precondition_failed"
                )
            self.connection.execute(
                "UPDATE attempts SET state='activation_pending'"
                " WHERE client_turn_id=?",
                (client_turn_id,),
            )
            return self._update_receipt(client_turn_id)

    def authorize_transport(self, client_turn_id: str, purpose: str) -> None:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT * FROM attempts WHERE client_turn_id=?", (client_turn_id,)
            ).fetchone()
            if self.doctor()["state"] != "healthy":
                self.connection.execute("ROLLBACK")
                raise Gate12SExternalCallDenied("gate12s_store_unhealthy")
            allowed = bool(
                row is not None
                and purpose == ALLOWED_MAIN_PURPOSE
                and row["state"] == "activated"
                and row["readiness_state"] == "ready"
                and row["generation2_effective"]
                and row["capability_issued"]
                and row["endpoint_request_sha256"]
                == row["activation_endpoint_sha256"]
                == row["final_request_sha256"]
                and not row["main_transport_authorized"]
                and row["external_transport_count"] == 0
                and _semantic_activation_valid(
                    self.root, row, require_issued=True
                )
            )
            if not allowed:
                if row is not None:
                    self.connection.execute(
                        "UPDATE attempts SET denied_transport_count=denied_transport_count+1 WHERE client_turn_id=?",
                        (client_turn_id,),
                    )
                    self._update_receipt(client_turn_id)
                self.connection.execute("COMMIT")
                raise Gate12SExternalCallDenied("gate12s_external_transport_denied")
            if row["mode"] == REHEARSAL:
                self.connection.execute(
                    """
                    UPDATE attempts SET state='intercept_authorized',
                      main_transport_authorized=1,intercepted_transport_count=1
                    WHERE client_turn_id=?
                    """,
                    (client_turn_id,),
                )
            else:
                self.connection.execute(
                    """
                    UPDATE attempts SET state='dispatched',main_transport_authorized=1,
                      provider_dispatch_performed=1,external_transport_count=1
                    WHERE client_turn_id=?
                    """,
                    (client_turn_id,),
                )
            self._update_receipt(client_turn_id)
            self.connection.execute("COMMIT")
        except Gate12SExternalCallDenied:
            raise
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def record_denied_transport(self, client_turn_id: str) -> None:
        with self.connection:
            row = self.connection.execute(
                "SELECT state FROM attempts WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            if row is None or self.doctor()["state"] != "healthy":
                raise Gate12SExternalCallDenied(
                    "gate12s_store_unhealthy"
                )
            self.connection.execute(
                "UPDATE attempts SET denied_transport_count="
                "denied_transport_count+1 WHERE client_turn_id=?",
                (client_turn_id,),
            )
            self._update_receipt(client_turn_id)

    def record_completion(
        self,
        client_turn_id: str,
        *,
        capability_consumed: bool,
        outbox_bundle_id: str | None,
    ) -> dict[str, Any]:
        with self.connection:
            row = self.connection.execute(
                "SELECT * FROM attempts WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            if (
                row is None
                or row["state"] not in {"intercept_authorized", "dispatched"}
                or not row["generation2_effective"]
                or not row["capability_issued"]
                or not row["main_transport_authorized"]
                or (
                    outbox_bundle_id is not None
                    and _BOUNDED_ID_RE.fullmatch(outbox_bundle_id) is None
                )
                or (outbox_bundle_id is not None and not capability_consumed)
            ):
                raise Gate12SControlError(
                    "gate12s_completion_transition_invalid"
                )
            self.connection.execute(
                """
                UPDATE attempts SET state='completed',capability_consumed=?,
                  outbox_bundle_id=? WHERE client_turn_id=?
                """,
                (int(capability_consumed), outbox_bundle_id, client_turn_id),
            )
            return self._update_receipt(client_turn_id)

    def record_complete_unit(
        self, client_turn_id: str, complete_unit_id: str
    ) -> dict[str, Any]:
        with self.connection:
            row = self.connection.execute(
                "SELECT * FROM attempts WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
            if (
                row is None
                or row["state"] != "completed"
                or not row["capability_consumed"]
                or row["outbox_bundle_id"] is None
                or row["complete_unit_id"] is not None
                or _BOUNDED_ID_RE.fullmatch(complete_unit_id) is None
            ):
                raise Gate12SControlError(
                    "gate12s_complete_unit_transition_invalid"
                )
            self.connection.execute(
                "UPDATE attempts SET complete_unit_id=? WHERE client_turn_id=?",
                (complete_unit_id, client_turn_id),
            )
            return self._update_receipt(client_turn_id)

    def doctor(self) -> dict[str, Any]:
        integrity = self.connection.execute("PRAGMA integrity_check").fetchone()
        foreign = self.connection.execute("PRAGMA foreign_key_check").fetchall()
        meta = dict(self.connection.execute("SELECT key,value FROM meta").fetchall())
        latches = self.connection.execute(
            "SELECT * FROM latches ORDER BY mode"
        ).fetchall()
        bindings = self.connection.execute(
            "SELECT * FROM operation_bindings"
        ).fetchall()
        rows = self.connection.execute("SELECT * FROM attempts").fetchall()
        healthy = bool(
            integrity
            and integrity[0] == "ok"
            and not foreign
            and set(meta)
            == {"schema_version", "store_id", "rehearsal_review_state"}
            and meta.get("schema_version") == SCHEMA_VERSION
            and _STORE_ID_RE.fullmatch(str(meta.get("store_id") or ""))
            is not None
            and (
                meta.get("rehearsal_review_state") == "pending"
                or re.fullmatch(
                    r"passed:[0-9a-f]{64}",
                    str(meta.get("rehearsal_review_state") or ""),
                )
                is not None
                or _PREDECESSOR_REVIEW_RE.fullmatch(
                    str(meta.get("rehearsal_review_state") or "")
                )
                is not None
            )
            and len(latches) == 2
            and {row["mode"] for row in latches} == _MODES
            and not any(_contains_private_text(value) for value in meta.values())
            and len(bindings) == len(rows)
        )
        binding_by_turn = {
            row["client_turn_id"]: row for row in bindings
        }
        for binding in bindings:
            issued_at = _parsed_timestamp(binding["issued_at"])
            expires_at = _parsed_timestamp(binding["expires_at"])
            route_columns = (
                binding["route_binding_json"],
                binding["route_binding_sha256"],
                binding["command_context_json"],
                binding["command_context_sha256"],
            )
            has_route_binding = any(
                value is not None for value in route_columns
            )
            route_healthy = not has_route_binding
            route_binding = None
            command_context = None
            if has_route_binding and all(
                isinstance(value, str) and bool(value)
                for value in route_columns
            ):
                try:
                    route_binding = (
                        route_binding_local.validate_operation_binding(
                            json.loads(binding["route_binding_json"])
                        )
                    )
                    command_context = contracts.validate_command_context(
                        json.loads(binding["command_context_json"])
                    )
                    route_healthy = bool(
                        _sha(_canonical(route_binding))
                        == binding["route_binding_sha256"]
                        and _sha(_canonical(command_context))
                        == binding["command_context_sha256"]
                        and route_binding["transient_session_id"]
                        == binding["session_id"]
                        and route_binding["room_id"]
                        == binding["room_id"]
                        and command_context["room_id"]
                        == binding["room_id"]
                    )
                except Exception:
                    route_healthy = False
            canonical_binding = {
                "schema_version": (
                    "house_continuity_v1_2_gate12s_operation_binding_v2"
                    if has_route_binding
                    else "house_continuity_v1_2_gate12s_operation_binding_v1"
                ),
                "client_turn_id": binding["client_turn_id"],
                "provider_operation_id": binding[
                    "provider_operation_id"
                ],
                "session_id": binding["session_id"],
                "room_id": binding["room_id"],
                "issued_at": binding["issued_at"],
                "expires_at": binding["expires_at"],
                "capability_id": binding["capability_id"],
                "capability_sha256": binding["capability_sha256"],
                "capability_creation_seed_sha256": binding[
                    "capability_creation_seed_sha256"
                ],
            }
            if has_route_binding:
                canonical_binding.update(
                    {
                        "route_binding": route_binding,
                        "route_binding_sha256": binding[
                            "route_binding_sha256"
                        ],
                        "command_context": command_context,
                        "command_context_sha256": binding[
                            "command_context_sha256"
                        ],
                    }
                )
            healthy = healthy and bool(
                _IDENTITY_RE.fullmatch(binding["client_turn_id"])
                and _IDENTITY_RE.fullmatch(
                    binding["provider_operation_id"]
                )
                and binding["provider_operation_id"].startswith(
                    "hpaop_"
                )
                and binding["provider_operation_id"]
                != binding["client_turn_id"]
                and _IDENTITY_RE.fullmatch(binding["session_id"])
                and _BOUNDED_ID_RE.fullmatch(binding["room_id"])
                and _CAPABILITY_ID_RE.fullmatch(
                    binding["capability_id"]
                )
                and _SHA_RE.fullmatch(binding["capability_sha256"])
                and _SHA_RE.fullmatch(
                    binding["capability_creation_seed_sha256"]
                )
                and _SHA_RE.fullmatch(binding["binding_sha256"])
                and _sha(_canonical(canonical_binding))
                == binding["binding_sha256"]
                and route_healthy
                and (
                    has_route_binding
                    or gate12._room_id(binding["session_id"])
                    == binding["room_id"]
                )
                and issued_at is not None
                and expires_at is not None
                and expires_at == issued_at + timedelta(minutes=60)
                and _parsed_timestamp(binding["created_at"])
                == issued_at
            )
        latch_by_mode = {row["mode"]: row for row in latches}
        for latch in latches:
            state = latch["state"]
            healthy = healthy and state in _LATCH_STATES
            healthy = healthy and isinstance(latch["revision"], int)
            healthy = healthy and int(latch["revision"]) >= 1
            if state == "unarmed":
                healthy = healthy and all(
                    latch[name] is None
                    for name in ("armed_at", "consumed_at", "client_turn_id")
                )
            elif state == "armed":
                healthy = healthy and _parsed_timestamp(latch["armed_at"]) is not None
                healthy = healthy and latch["consumed_at"] is None
                healthy = healthy and latch["client_turn_id"] is None
            elif state == "consumed":
                armed_at = _parsed_timestamp(latch["armed_at"])
                consumed_at = _parsed_timestamp(latch["consumed_at"])
                healthy = healthy and armed_at is not None
                healthy = healthy and consumed_at is not None
                healthy = healthy and bool(
                    armed_at is not None
                    and consumed_at is not None
                    and armed_at <= consumed_at
                )
                healthy = healthy and (
                    isinstance(latch["client_turn_id"], str)
                    and _IDENTITY_RE.fullmatch(latch["client_turn_id"])
                    is not None
                )
            healthy = healthy and not any(
                _contains_private_text(latch[name])
                for name in latch.keys()
                if isinstance(latch[name], str)
            )
        healthy = healthy and sum(
            latch["state"] == "armed" for latch in latches
        ) <= 1
        live_latch = latch_by_mode.get(LIVE_CANARY)
        if live_latch is not None and live_latch["state"] == "armed":
            healthy = healthy and str(
                meta.get("rehearsal_review_state") or ""
            ).startswith("passed:")
        for mode, latch in latch_by_mode.items():
            matching = [row for row in rows if row["mode"] == mode]
            if mode == REHEARSAL:
                healthy = healthy and (
                    (
                        latch["state"] == "consumed"
                        and len(matching) == 1
                    )
                    or (
                        latch["state"] != "consumed"
                        and not matching
                    )
                )
            elif latch["state"] == "unarmed":
                healthy = healthy and not matching
            elif latch["state"] == "consumed":
                healthy = healthy and bool(
                    matching
                    and sum(
                        row["client_turn_id"]
                        == latch["client_turn_id"]
                        for row in matching
                    )
                    == 1
                )
            else:
                healthy = healthy and all(
                    row["state"] == "completed" for row in matching
                )
        for row in rows:
            try:
                bool_columns = (
                    "generation2_effective",
                    "capability_issued",
                    "capability_consumed",
                    "main_transport_authorized",
                    "provider_dispatch_performed",
                    "milestone5_artifact_required",
                )
                count_columns = (
                    "external_transport_count",
                    "denied_transport_count",
                    "intercepted_transport_count",
                )
                row_mode = row["mode"]
                latch = latch_by_mode.get(row_mode)
                operation_binding = binding_by_turn.get(
                    row["client_turn_id"]
                )
                healthy = healthy and row_mode in _MODES
                healthy = healthy and (
                    _IDENTITY_RE.fullmatch(
                        str(row["provider_operation_id"] or "")
                    )
                    is not None
                )
                healthy = healthy and row["state"] in _ATTEMPT_STATES
                healthy = healthy and row["readiness_state"] in _READINESS_STATES
                healthy = healthy and (
                    row["readiness_error_code"] in _READINESS_ERROR_CODES
                )
                healthy = healthy and all(
                    row[name] in (0, 1) for name in bool_columns
                )
                healthy = healthy and all(
                    isinstance(row[name], int) and row[name] >= 0
                    for name in count_columns
                )
                current_latch_attempt = bool(
                    latch is not None
                    and latch["state"] == "consumed"
                    and latch["client_turn_id"]
                    == row["client_turn_id"]
                )
                historical_live_attempt = bool(
                    row_mode == LIVE_CANARY
                    and latch is not None
                    and row["state"] == "completed"
                    and not current_latch_attempt
                )
                healthy = healthy and (
                    current_latch_attempt
                    or historical_live_attempt
                )
                healthy = healthy and (
                    operation_binding is not None
                    and operation_binding["provider_operation_id"]
                    == row["provider_operation_id"]
                    and operation_binding["binding_sha256"]
                    == row["operation_binding_sha256"]
                )
                hashes = (
                    row["endpoint_request_sha256"],
                    row["activation_endpoint_sha256"],
                    row["final_request_sha256"],
                    row["generation1_identity_sha256"],
                    row["generation2_identity_sha256"],
                    row["exact_stable_messages_sha256"],
                    row["exact_tool_block_sha256"],
                )
                healthy = healthy and all(
                    value is None
                    or (
                        isinstance(value, str)
                        and _SHA_RE.fullmatch(value) is not None
                    )
                    for value in hashes
                )
                healthy = healthy and (
                    bool(row["milestone5_artifact_required"])
                    == (row["milestone5_artifact_sha256"] is not None)
                )
                healthy = healthy and (
                    row["milestone5_artifact_sha256"] is None
                    or _SHA_RE.fullmatch(
                        row["milestone5_artifact_sha256"]
                    )
                    is not None
                )
                if row["readiness_state"] == "ready":
                    healthy = healthy and row["readiness_error_code"] == "none"
                    healthy = healthy and all(
                        row[name] is not None
                        for name in (
                            "endpoint_request_sha256",
                            "generation1_identity_sha256",
                            "generation2_identity_sha256",
                            "exact_stable_messages_sha256",
                            "exact_tool_block_sha256",
                        )
                    )
                    healthy = healthy and (
                        _IDENTITY_RE.fullmatch(
                            str(row["provider_operation_id"] or "")
                        )
                        is not None
                        and _PREFIX_OR_CACHE_RE.fullmatch(
                            str(row["effective_assembly_version"] or "")
                        )
                        is not None
                        and _PREFIX_OR_CACHE_RE.fullmatch(
                            str(row["generation2_prefix_version"] or "")
                        )
                        is not None
                        and _PREFIX_OR_CACHE_RE.fullmatch(
                            str(row["generation2_cache_key"] or "")
                        )
                        is not None
                    )
                else:
                    healthy = healthy and not row["generation2_effective"]
                    healthy = healthy and not row["capability_issued"]
                    healthy = healthy and not row["main_transport_authorized"]
                    healthy = healthy and all(value is None for value in hashes)
                    healthy = healthy and all(
                        row[name] is None
                        for name in (
                            "effective_assembly_version",
                            "generation2_prefix_version",
                            "generation2_cache_key",
                        )
                    )
                healthy = healthy and (
                    row["generation2_effective"] == row["capability_issued"]
                )
                if row["generation2_effective"]:
                    healthy = healthy and (
                        row["activation_endpoint_sha256"]
                        == row["endpoint_request_sha256"]
                    )
                else:
                    healthy = healthy and (
                        row["activation_endpoint_sha256"] is None
                    )
                if row["final_request_sha256"] is not None:
                    healthy = healthy and (
                        row["final_request_sha256"]
                        == row["activation_endpoint_sha256"]
                    )
                if row["main_transport_authorized"]:
                    healthy = healthy and (
                        row["endpoint_request_sha256"]
                        == row["activation_endpoint_sha256"]
                        == row["final_request_sha256"]
                    )
                healthy = healthy and (
                    row["capability_consumed"] <= row["capability_issued"]
                )
                healthy = healthy and (
                    (row["capability_id"] is None and not row["capability_issued"])
                    or (
                        row["capability_issued"]
                        and isinstance(row["capability_id"], str)
                        and _CAPABILITY_ID_RE.fullmatch(row["capability_id"])
                        is not None
                    )
                )
                if row["main_transport_authorized"]:
                    if row_mode == REHEARSAL:
                        healthy = healthy and (
                            row["external_transport_count"] == 0
                            and row["intercepted_transport_count"] == 1
                            and not row["provider_dispatch_performed"]
                        )
                    else:
                        healthy = healthy and (
                            row["external_transport_count"] == 1
                            and row["intercepted_transport_count"] == 0
                            and row["provider_dispatch_performed"]
                        )
                else:
                    healthy = healthy and (
                        row["external_transport_count"] == 0
                        and row["intercepted_transport_count"] == 0
                        and not row["provider_dispatch_performed"]
                    )
                for name in ("outbox_bundle_id", "complete_unit_id"):
                    healthy = healthy and (
                        row[name] is None
                        or (
                            isinstance(row[name], str)
                            and _BOUNDED_ID_RE.fullmatch(row[name]) is not None
                        )
                    )
                healthy = healthy and (
                    row["outbox_bundle_id"] is None
                    or row["capability_consumed"]
                )
                healthy = healthy and (
                    row["complete_unit_id"] is None
                    or row["outbox_bundle_id"] is not None
                )
                created_at = _parsed_timestamp(row["created_at"])
                updated_at = _parsed_timestamp(row["updated_at"])
                healthy = healthy and created_at is not None
                healthy = healthy and updated_at is not None
                healthy = healthy and bool(
                    created_at is not None
                    and updated_at is not None
                    and created_at <= updated_at
                )
                if current_latch_attempt:
                    healthy = healthy and (
                        _parsed_timestamp(latch["consumed_at"]) == created_at
                    )
                no_activation = bool(
                    not row["generation2_effective"]
                    and not row["capability_issued"]
                    and not row["capability_consumed"]
                    and not row["main_transport_authorized"]
                    and not row["provider_dispatch_performed"]
                    and row["external_transport_count"] == 0
                    and row["intercepted_transport_count"] == 0
                    and row["capability_id"] is None
                    and row["outbox_bundle_id"] is None
                    and row["complete_unit_id"] is None
                )
                state = row["state"]
                if state == "accepted_pending_readiness":
                    healthy = healthy and (
                        row["readiness_state"] == "pending"
                        and row["readiness_error_code"] == "none"
                        and no_activation
                    )
                elif state == "readiness_failed":
                    healthy = healthy and (
                        row["readiness_state"] == "failed"
                        and row["readiness_error_code"] != "none"
                        and no_activation
                    )
                elif state in {"ready", "activation_pending"}:
                    healthy = healthy and (
                        row["readiness_state"] == "ready" and no_activation
                    )
                elif state == "activated":
                    healthy = healthy and (
                        row["readiness_state"] == "ready"
                        and row["generation2_effective"]
                        and row["capability_issued"]
                        and not row["capability_consumed"]
                        and not row["main_transport_authorized"]
                        and _semantic_activation_valid(
                            self.root, row, require_issued=True
                        )
                    )
                elif state == "intercept_authorized":
                    healthy = healthy and (
                        row_mode == REHEARSAL
                        and row["main_transport_authorized"]
                        and not row["capability_consumed"]
                        and _semantic_activation_valid(
                            self.root, row, require_issued=True
                        )
                    )
                elif state == "dispatched":
                    healthy = healthy and (
                        row_mode == LIVE_CANARY
                        and row["main_transport_authorized"]
                        and not row["capability_consumed"]
                        and _semantic_activation_valid(
                            self.root, row, require_issued=True
                        )
                    )
                elif state == "completed":
                    healthy = healthy and (
                        row["main_transport_authorized"]
                        and _semantic_activation_valid(
                            self.root, row, require_issued=False
                        )
                    )
                receipt = json.loads(row["receipt_json"])
                initial = {
                    "schema_version": RECEIPT_SCHEMA_VERSION,
                    "gate_id": GATE_ID,
                    "client_turn_id": row["client_turn_id"],
                    "mode": row["mode"],
                    "provider_operation_id": row[
                        "provider_operation_id"
                    ],
                    "operation_binding_sha256": row[
                        "operation_binding_sha256"
                    ],
                    "attempt_consumed": True,
                    "generation2_readiness": "pending",
                    "raw_material_present": False,
                }
                expected = self._receipt(row["client_turn_id"])
                healthy = healthy and _sha(_canonical(receipt)) == row["receipt_sha256"]
                healthy = healthy and receipt.get("raw_material_present") is False
                healthy = healthy and receipt in (initial, expected)
                healthy = healthy and not any(
                    _contains_private_text(row[name])
                    for name in row.keys()
                    if isinstance(row[name], str)
                )
            except Exception:
                healthy = False
        review_state = str(meta.get("rehearsal_review_state") or "")
        if review_state.startswith("passed:") and not _PREDECESSOR_REVIEW_RE.fullmatch(
            review_state
        ):
            rehearsal_latch = latch_by_mode.get(REHEARSAL)
            rehearsal_rows = [
                row for row in rows if row["mode"] == REHEARSAL
            ]
            healthy = healthy and bool(
                rehearsal_latch is not None
                and rehearsal_latch["state"] == "consumed"
                and len(rehearsal_rows) == 1
                and rehearsal_rows[0]["state"] == "completed"
                and rehearsal_rows[0]["capability_consumed"]
                and rehearsal_rows[0]["outbox_bundle_id"]
                and rehearsal_rows[0]["complete_unit_id"]
                and rehearsal_rows[0]["external_transport_count"] == 0
                and rehearsal_rows[0]["intercepted_transport_count"] == 1
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "state": "healthy" if healthy else "unhealthy",
            "attempt_count": len(rows),
            "foreign_key_violation_count": len(foreign),
            "raw_material_detected": not healthy,
        }


def arm(env: Mapping[str, str], mode: str) -> dict[str, Any]:
    root = root_from_env(env)
    store = Gate12SAttemptStore(root)
    prior_latch = store.read_latch(mode)
    try:
        result = store.arm(mode)
        armed_latch = store.read_latch(mode)
        inner_env = _gate12_env(env, root, mode)
        try:
            gate12.doctor(inner_env)
            gate12.arm(inner_env)
        except Exception:
            store.restore_latch_after_failed_inner_arm(
                mode,
                prior_latch=prior_latch,
                expected_armed_latch=armed_latch,
            )
            raise
        return result
    finally:
        store.close()


def mark_rehearsal_review_pass(
    env: Mapping[str, str], review_sha256: str
) -> dict[str, Any]:
    store = Gate12SAttemptStore(root_from_env(env), require_existing=True)
    try:
        return store.mark_rehearsal_review_pass(review_sha256)
    finally:
        store.close()


def mark_predecessor_attestation_pass(
    env: Mapping[str, str],
    attestation: Mapping[str, Any],
    *,
    target_manifest_sha256: str,
) -> dict[str, Any]:
    """Record the reviewed predecessor proof on an already-created fresh root."""

    requested_root = _requested_root_from_env(env)
    _validate_predecessor_root_shape(requested_root)
    store = Gate12SAttemptStore(requested_root, require_existing=True)
    try:
        return store.mark_predecessor_attestation_pass(
            attestation,
            target_manifest_sha256=target_manifest_sha256,
        )
    finally:
        store.close()


def accept_natural_turn(
    *,
    env: Mapping[str, str],
    client_turn_id: str,
    provider_operation_id: str,
    session_id: str,
    route_binding_request: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    mode = mode_from_env(env)
    if mode == OFF:
        return None
    if (
        str(env.get(gate12.SWITCH_ENV) or gate12.OFF).strip() != gate12.OFF
        or str(env.get(gate12r.SWITCH_ENV) or gate12r.OFF).strip() != gate12r.OFF
    ):
        raise Gate12SControlError("gate12s_historical_gate_conflict")
    if mode == REHEARSAL and client_turn_id != str(env.get(REHEARSAL_TURN_ENV) or ""):
        return None
    store = Gate12SAttemptStore(root_from_env(env), require_existing=True)
    try:
        return store.accept(
            client_turn_id,
            mode,
            provider_operation_id=provider_operation_id,
            session_id=session_id,
            route_binding_request=route_binding_request,
        )
    finally:
        store.close()


def attempt_for_turn(
    env: Mapping[str, str], client_turn_id: str
) -> dict[str, Any] | None:
    if not configured(env):
        return None
    store = Gate12SAttemptStore(root_from_env(env), require_existing=True)
    try:
        store.recover_incomplete_activation(client_turn_id)
        attempt = store.read_attempt(client_turn_id)
        if attempt is not None:
            with _LOCK:
                _PROCESS_BINDINGS[client_turn_id] = (store.root, attempt["mode"])
        return attempt
    finally:
        store.close()


def receipt_for_turn(
    env: Mapping[str, str], client_turn_id: str
) -> dict[str, Any] | None:
    if not configured(env):
        return None
    store = Gate12SAttemptStore(root_from_env(env), require_existing=True)
    try:
        if store.read_attempt(client_turn_id) is None:
            return None
        return store._receipt(client_turn_id)
    finally:
        store.close()


def _validated_operation_binding(
    store: Gate12SAttemptStore,
    *,
    client_turn_id: str,
    provider_operation_id: str,
    session_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    attempt = store.read_attempt(client_turn_id)
    binding = store.read_operation_binding(client_turn_id)
    if attempt is None or binding is None:
        raise Gate12SControlError("gate12s_attempt_missing")
    route_values = (
        binding.get("route_binding_json"),
        binding.get("route_binding_sha256"),
        binding.get("command_context_json"),
        binding.get("command_context_sha256"),
    )
    has_route_binding = any(value is not None for value in route_values)
    if has_route_binding and not all(
        isinstance(value, str) and bool(value) for value in route_values
    ):
        raise Gate12SControlError("gate12s_operation_binding_mismatch")
    route_binding = None
    command_context = None
    if has_route_binding:
        try:
            route_binding = route_binding_local.validate_operation_binding(
                json.loads(binding["route_binding_json"])
            )
            command_context = contracts.validate_command_context(
                json.loads(binding["command_context_json"])
            )
        except Exception as exc:
            raise Gate12SControlError(
                "gate12s_operation_binding_mismatch"
            ) from exc
        if (
            _sha(_canonical(route_binding))
            != binding["route_binding_sha256"]
            or _sha(_canonical(command_context))
            != binding["command_context_sha256"]
            or route_binding["transient_session_id"] != session_id
            or route_binding["room_id"] != binding["room_id"]
            or command_context["room_id"] != binding["room_id"]
            or command_context["scope_binding_revision"]
            != route_binding["scope_binding_revision"]
        ):
            raise Gate12SControlError(
                "gate12s_operation_binding_mismatch"
            )
    canonical_binding = {
        "schema_version": (
            "house_continuity_v1_2_gate12s_operation_binding_v2"
            if has_route_binding
            else "house_continuity_v1_2_gate12s_operation_binding_v1"
        ),
        "client_turn_id": binding["client_turn_id"],
        "provider_operation_id": binding["provider_operation_id"],
        "session_id": binding["session_id"],
        "room_id": binding["room_id"],
        "issued_at": binding["issued_at"],
        "expires_at": binding["expires_at"],
        "capability_id": binding["capability_id"],
        "capability_sha256": binding["capability_sha256"],
        "capability_creation_seed_sha256": binding[
            "capability_creation_seed_sha256"
        ],
    }
    if has_route_binding:
        canonical_binding.update(
            {
                "route_binding": route_binding,
                "route_binding_sha256": binding[
                    "route_binding_sha256"
                ],
                "command_context": command_context,
                "command_context_sha256": binding[
                    "command_context_sha256"
                ],
            }
        )
    if (
        client_turn_id != binding["client_turn_id"]
        or provider_operation_id != binding["provider_operation_id"]
        or session_id != binding["session_id"]
        or attempt["provider_operation_id"] != provider_operation_id
        or attempt["operation_binding_sha256"]
        != binding["binding_sha256"]
        or _sha(_canonical(canonical_binding))
        != binding["binding_sha256"]
        or (
            not has_route_binding
            and gate12._room_id(session_id) != binding["room_id"]
        )
        or _parsed_timestamp(binding["issued_at"]) is None
        or _parsed_timestamp(binding["expires_at"])
        != _parsed_timestamp(binding["issued_at"]) + timedelta(minutes=60)
    ):
        raise Gate12SControlError("gate12s_operation_binding_mismatch")
    binding["route_binding"] = route_binding
    binding["command_context"] = command_context
    return attempt, binding


def prepare_generation2_selection(
    *,
    env: Mapping[str, str],
    client_turn_id: str,
    provider_operation_id: str,
    session_id: str,
    generation1_selection: Any,
    broker: Any,
    intent_query: str | None = None,
) -> Any:
    root = root_from_env(env)
    store = Gate12SAttemptStore(root, require_existing=True)
    try:
        attempt, binding = _validated_operation_binding(
            store,
            client_turn_id=client_turn_id,
            provider_operation_id=provider_operation_id,
            session_id=session_id,
        )
    finally:
        store.close()
    with _LOCK:
        capability_material = _PREPARED_CAPABILITIES.get(client_turn_id)
    if capability_material is None:
        raise Gate12SControlError("gate12s_operation_binding_mismatch")
    clear_capability, capability_id = capability_material
    if (
        capability_id != binding["capability_id"]
        or _sha(clear_capability) != binding["capability_sha256"]
        or _sha("gate12-capability:" + provider_operation_id)
        != binding["capability_creation_seed_sha256"]
    ):
        raise Gate12SControlError("gate12s_operation_binding_mismatch")
    inner_env = _gate12_env(env, root, attempt["mode"])
    reservation = gate12.prepare_turn(
        env=inner_env,
        client_turn_id=client_turn_id,
        session_id=session_id,
        provider_operation_id=provider_operation_id,
        clear_capability=clear_capability,
        capability_id=capability_id,
        issued_at=binding["issued_at"],
        expires_at=binding["expires_at"],
        route_binding=binding.get("route_binding"),
        command_context=binding.get("command_context"),
    )
    if reservation is None:
        raise Gate12SControlError("gate12s_operation_binding_mismatch")
    milestone5_projection = milestone5.prepare_operation_artifact(
        env=env,
        gate12_root=semantic_root(root, attempt["mode"]),
        operation_id=provider_operation_id,
        room_id=binding["room_id"],
        client_turn_id=client_turn_id,
        provider_operation_id=provider_operation_id,
        generation1_selection=generation1_selection,
        now=_now(),
        budget_chars=milestone4.DEFAULT_BUDGET_CHARS,
        intent_query=intent_query,
        preserved_dynamic_context=(
            generation2.generation1_dynamic_context_without_m4_managed(
                generation1_selection
            )
        ),
        final_dynamic_context_suffix=(
            milestone4.canonical_json_bytes(reservation.offer).decode("utf-8"),
        ),
    )
    if milestone5_projection is not None:
        working_set_section = milestone5_projection[
            "required_m2_section"
        ]
        context_sections = milestone5_projection["m3_sections"]
        milestone4_projection = None
        integrated_context_sections = milestone5_projection["sections"]
        milestone5_artifact_sha256 = milestone5_projection["artifact"][
            "artifact_sha256"
        ]
    else:
        working_set_section = milestone2.generation2_section_from_env(
            env,
            room_id=binding["room_id"],
        )
        context_sections = milestone3.generation2_sections_from_env(
            env,
            room_id=binding["room_id"],
            required_m2_section=working_set_section,
        )
        milestone4_projection = milestone4.generation2_projection_from_env(
            env,
            room_id=binding["room_id"],
            required_m2_section=working_set_section,
            m3_sections=context_sections,
            preserved_dynamic_context=(
                generation2.generation1_dynamic_context_without_m4_managed(
                    generation1_selection
                )
            ),
            final_dynamic_context_suffix=(
                milestone4.canonical_json_bytes(reservation.offer).decode("utf-8"),
            ),
        )
        integrated_context_sections = (
            None
            if milestone4_projection is None
            else milestone4_projection.sections
        )
        milestone5_artifact_sha256 = None
    candidate, selection = gate12.prepare_generation2_operation(
        reservation,
        generation1_selection,
        broker=broker,
        working_set_section=working_set_section,
        context_sections=context_sections,
        integrated_context_sections=integrated_context_sections,
    )
    if milestone4_projection is not None:
        milestone4.attest_generation2_dynamic_context(
            milestone4_projection,
            generation2.generation2_dynamic_context_from_candidate(candidate),
        )
    if milestone5_projection is not None:
        artifact = milestone5_projection["artifact"]
        milestone4.attest_generation2_dynamic_context(
            milestone4.Milestone4Generation2Projection(
                selection_attempt_id=artifact["m4_selection_attempt_id"],
                budget_chars=artifact["m4_budget_chars"],
                emitted_representation_chars=artifact[
                    "m4_emitted_representation_chars"
                ],
                emitted_representation_sha256=artifact[
                    "m4_emitted_representation_sha256"
                ],
                sections=tuple(artifact["sections"]),
            ),
            generation2.generation2_dynamic_context_from_candidate(candidate),
        )
        requirement_store = Gate12SAttemptStore(
            root,
            require_existing=True,
        )
        try:
            requirement_store.bind_milestone5_artifact_requirement(
                client_turn_id,
                provider_operation_id=provider_operation_id,
                artifact_sha256=milestone5_artifact_sha256,
            )
        finally:
            requirement_store.close()
    prepared = Gate12SPreparedSelection(
        client_turn_id=client_turn_id,
        provider_operation_id=provider_operation_id,
        operation_binding_sha256=binding["binding_sha256"],
        reservation=reservation,
        candidate=candidate,
        selection=selection,
        milestone5_artifact_sha256=milestone5_artifact_sha256,
    )
    with _LOCK:
        if client_turn_id in _PREPARED_SELECTIONS:
            raise Gate12SControlError(
                "gate12s_operation_binding_mismatch"
            )
        _PREPARED_SELECTIONS[client_turn_id] = prepared
    return selection


def build_no_provider_generation2_preflight(
    *,
    env: Mapping[str, str],
    client_turn_id: str,
    provider_operation_id: str,
    session_id: str,
    runtime_request: Mapping[str, Any],
    broker: Any,
) -> dict[str, Any]:
    import house_provider_agent_live_runtime_v0 as live_runtime

    root = root_from_env(env)
    store = Gate12SAttemptStore(root, require_existing=True)
    try:
        attempt, binding = _validated_operation_binding(
            store,
            client_turn_id=client_turn_id,
            provider_operation_id=provider_operation_id,
            session_id=session_id,
        )
    finally:
        store.close()
    with _LOCK:
        prepared_selection = _PREPARED_SELECTIONS.get(client_turn_id)
    if (
        prepared_selection is None
        or prepared_selection.provider_operation_id
        != provider_operation_id
        or prepared_selection.operation_binding_sha256
        != binding["binding_sha256"]
    ):
        raise Gate12SControlError("gate12s_operation_binding_mismatch")
    runtime_artifact = live_runtime.prepare_initial_provider_request(
        runtime_request,
        stable_operation_id=client_turn_id,
        provider_operation_id=provider_operation_id,
        broker=broker,
        env=env,
        reviewed_read_only_capabilities=(
            prepared_selection.selection.reviewed_read_only_capabilities
        ),
        operation_bound_tool_surface=(
            prepared_selection.candidate.generation2_tool_surface
        ),
    )
    if runtime_artifact.parent_operation_id != provider_operation_id:
        raise Gate12SControlError("gate12s_operation_binding_mismatch")
    try:
        prepared_body = json.loads(
            runtime_artifact.request_body.decode("utf-8")
        )
        prepared_tools = prepared_body["tools"]
        prepared_tool_sha256 = _sha(json.dumps(
            prepared_tools,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8"))
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise Gate12SControlError(
            "gate12s_exact_activation_identity_mismatch"
        ) from exc
    candidate = prepared_selection.candidate
    if (
        prepared_tools != candidate.generation2_request["tools"]
        or prepared_tool_sha256
        != candidate.generation2_identity[
            "exact_serialized_tool_block_sha256"
        ]
    ):
        raise Gate12SControlError(
            "gate12s_exact_activation_identity_mismatch"
        )
    prepared = Gate12SPreparedOperation(
        client_turn_id=client_turn_id,
        provider_operation_id=provider_operation_id,
        operation_binding_sha256=binding["binding_sha256"],
        reservation=prepared_selection.reservation,
        selection=prepared_selection.selection,
        endpoint_request_body=runtime_artifact.request_body,
        endpoint_request_sha256=(
            runtime_artifact.request_body_sha256
        ),
        runtime_artifact=runtime_artifact,
        milestone5_artifact_sha256=(
            prepared_selection.milestone5_artifact_sha256
        ),
    )
    if prepared.milestone5_artifact_sha256 is not None:
        milestone5.bind_operation_phase(
            env=env,
            gate12_root=semantic_root(root, attempt["mode"]),
            operation_id=provider_operation_id,
            phase="preflight",
            artifact_sha256=prepared.milestone5_artifact_sha256,
            phase_input_sha256=runtime_artifact.request_body_sha256,
        )
    with _LOCK:
        if client_turn_id in _PREPARED_OPERATIONS:
            raise Gate12SControlError(
                "gate12s_operation_binding_mismatch"
            )
        _PREPARED_OPERATIONS[client_turn_id] = prepared
    attestation = generation2.attest_generation2_candidate(candidate)
    return {
        "schema_version": (
            "house_continuity_v1_2_gate12s_c1_preflight_v1"
        ),
        "state": "ready",
        "effective_generation": generation2.GENERATION_2,
        "provider_operation_id": provider_operation_id,
        "operation_binding_sha256": binding["binding_sha256"],
        "generation1_identity": deepcopy(
            candidate.generation1_identity
        ),
        "generation2_identity": deepcopy(
            candidate.generation2_identity
        ),
        "endpoint_request_sha256": (
            runtime_artifact.request_body_sha256
        ),
        "standing_root_card_count": attestation[
            "standing_root_card_count"
        ],
        "continuity_instruction_count": 1,
        "dynamic_offer_last_before_current_input": True,
        "capability_issued": False,
        "provider_calls_made": False,
        "raw_material_present": False,
    }


def record_generation2_readiness(
    env: Mapping[str, str],
    client_turn_id: str,
    *,
    ready: bool,
    error_code: str,
    endpoint_request_sha256: str | None = None,
    generation1_identity_sha256: str | None = None,
    generation2_identity_sha256: str | None = None,
    provider_operation_id: str,
    effective_assembly_version: str | None = None,
    generation2_prefix_version: str | None = None,
    generation2_cache_key: str | None = None,
    exact_stable_messages_sha256: str | None = None,
    exact_tool_block_sha256: str | None = None,
) -> dict[str, Any]:
    store = Gate12SAttemptStore(root_from_env(env), require_existing=True)
    try:
        return store.record_readiness(
            client_turn_id,
            ready=ready,
            error_code=error_code,
            endpoint_request_sha256=endpoint_request_sha256,
            generation1_identity_sha256=generation1_identity_sha256,
            generation2_identity_sha256=generation2_identity_sha256,
            provider_operation_id=provider_operation_id,
            effective_assembly_version=effective_assembly_version,
            generation2_prefix_version=generation2_prefix_version,
            generation2_cache_key=generation2_cache_key,
            exact_stable_messages_sha256=exact_stable_messages_sha256,
            exact_tool_block_sha256=exact_tool_block_sha256,
        )
    finally:
        store.close()


def activate_runtime(
    *,
    env: Mapping[str, str],
    client_turn_id: str,
    provider_operation_id: str,
    session_id: str,
) -> tuple[gate12.Gate12Reservation, Any]:
    root = root_from_env(env)
    store = Gate12SAttemptStore(root, require_existing=True)
    reservation = None
    try:
        attempt = store.read_attempt(client_turn_id)
        if attempt is None or attempt["readiness_state"] != "ready":
            raise Gate12SControlError("gate12s_activation_before_readiness")
        _, binding = _validated_operation_binding(
            store,
            client_turn_id=client_turn_id,
            provider_operation_id=provider_operation_id,
            session_id=session_id,
        )
        with _LOCK:
            prepared = _PREPARED_OPERATIONS.get(client_turn_id)
        if (
            prepared is None
            or prepared.provider_operation_id != provider_operation_id
            or prepared.operation_binding_sha256
            != binding["binding_sha256"]
            or prepared.endpoint_request_sha256
            != attempt["endpoint_request_sha256"]
        ):
            raise Gate12SControlError(
                "gate12s_preflight_activation_endpoint_mismatch"
            )
        store.begin_activation(client_turn_id)
        inner_env = _gate12_env(env, root, attempt["mode"])
        reservation = gate12.commit_prepared_turn(
            env=inner_env,
            reservation=prepared.reservation,
        )
        if reservation is None:
            raise Gate12SControlError("gate12s_capability_issue_failed")
        selection = prepared.selection
        identity = str(
            (reservation.generation_identity or {}).get(
                "canonical_semantic_stable_surface_sha256"
            )
            or ""
        )
        attested_identity = reservation.generation_identity or {}
        exact_bindings = {
            "canonical_semantic_stable_surface_sha256": attempt[
                "generation2_identity_sha256"
            ],
            "assembly_version": attempt["effective_assembly_version"],
            "prefix_version": attempt["generation2_prefix_version"],
            "cache_key": attempt["generation2_cache_key"],
            "exact_serialized_stable_messages_sha256": attempt[
                "exact_stable_messages_sha256"
            ],
            "exact_serialized_tool_block_sha256": attempt[
                "exact_tool_block_sha256"
            ],
        }
        if (
            reservation.provider_operation_id
            != attempt["provider_operation_id"]
            or reservation.session_id != session_id
            or any(
                str(attested_identity.get(name) or "") != str(value or "")
                for name, value in exact_bindings.items()
            )
        ):
            raise Gate12SControlError(
                "gate12s_exact_activation_identity_mismatch"
            )
        if prepared.milestone5_artifact_sha256 is not None:
            milestone5.bind_operation_phase(
                env=env,
                gate12_root=semantic_root(root, attempt["mode"]),
                operation_id=provider_operation_id,
                phase="activation",
                artifact_sha256=prepared.milestone5_artifact_sha256,
                phase_input_sha256=prepared.endpoint_request_sha256,
            )
        store.record_activation(
            client_turn_id,
            capability_id=reservation.capability_id,
            generation2_identity_sha256=identity,
            operation_binding_sha256=binding["binding_sha256"],
            activation_endpoint_sha256=(
                prepared.endpoint_request_sha256
            ),
        )
        with _LOCK:
            _PROCESS_BINDINGS[client_turn_id] = (root, attempt["mode"])
            _RESERVATIONS[client_turn_id] = reservation
        return reservation, selection
    except Exception as exc:
        with _LOCK:
            failed_prepared = _PREPARED_OPERATIONS.get(client_turn_id)
        if (
            failed_prepared is not None
            and failed_prepared.milestone5_artifact_sha256 is not None
        ):
            try:
                milestone5.bind_operation_phase(
                    env=env,
                    gate12_root=semantic_root(root, attempt["mode"]),
                    operation_id=provider_operation_id,
                    phase="rollback",
                    artifact_sha256=(
                        failed_prepared.milestone5_artifact_sha256
                    ),
                    phase_input_sha256=_sha(
                        str(
                            getattr(
                                exc,
                                "error_code",
                                "gate12s_activation_failed",
                            )
                        ).encode("utf-8")
                    ),
                )
            except Exception:
                pass
        if reservation is not None:
            try:
                gate12.abort_reservation(
                    reservation, error_code="gate12s_activation_failed"
                )
            except Exception:
                pass
        with _LOCK:
            _PREPARED_CAPABILITIES.pop(client_turn_id, None)
            _PREPARED_SELECTIONS.pop(client_turn_id, None)
            _PREPARED_OPERATIONS.pop(client_turn_id, None)
        raise
    finally:
        store.close()


def prepared_initial_request_for_turn(
    env: Mapping[str, str],
    client_turn_id: str,
    *,
    provider_operation_id: str,
) -> Any:
    store = Gate12SAttemptStore(
        root_from_env(env),
        require_existing=True,
    )
    try:
        attempt = store.read_attempt(client_turn_id)
    finally:
        store.close()
    with _LOCK:
        prepared = _PREPARED_OPERATIONS.get(client_turn_id)
    if (
        attempt is None
        or attempt["state"] != "activated"
        or attempt["provider_operation_id"] != provider_operation_id
        or attempt["endpoint_request_sha256"]
        != attempt["activation_endpoint_sha256"]
        or prepared is None
        or prepared.provider_operation_id != provider_operation_id
        or prepared.endpoint_request_sha256
        != attempt["activation_endpoint_sha256"]
    ):
        raise Gate12SControlError(
            "gate12s_preflight_activation_endpoint_mismatch"
        )
    return prepared.runtime_artifact


def process_provider_response(
    env: Mapping[str, str],
    reservation: gate12.Gate12Reservation,
    adapter_response: Mapping[str, Any],
    *,
    completed_at: str,
    structured_result: Any = None,
) -> dict[str, Any]:
    result = gate12.process_provider_response(
        reservation,
        adapter_response,
        completed_at=completed_at,
        structured_result=structured_result,
    )
    receipt = result.get("receipt") if isinstance(result.get("receipt"), Mapping) else {}
    store = Gate12SAttemptStore(root_from_env(env), require_existing=True)
    try:
        outbox_bundle_id = (
            str(receipt.get("outbox_bundle_id"))
            if receipt.get("outbox_bundle_id")
            else None
        )
        store.record_completion(
            reservation.client_turn_id,
            capability_consumed=bool(
                outbox_bundle_id
                or str(receipt.get("capability_effect") or "")
                in {"rejected_consumed", "explicit_no_delta_consumed"}
            ),
            outbox_bundle_id=outbox_bundle_id,
        )
    finally:
        store.close()
    with _LOCK:
        _RESERVATIONS.pop(reservation.client_turn_id, None)
        _PROCESS_BINDINGS.pop(reservation.client_turn_id, None)
        _PREPARED_CAPABILITIES.pop(
            reservation.client_turn_id,
            None,
        )
        _PREPARED_SELECTIONS.pop(reservation.client_turn_id, None)
        _PREPARED_OPERATIONS.pop(reservation.client_turn_id, None)
    return result


def record_non_authoritative_semantic_operation(
    env: Mapping[str, str],
    client_turn_id: str,
    provider_operation_id: str,
    *,
    reason_code: str,
    recorded_at: str,
) -> dict[str, Any] | None:
    """Finalize a completed M5 operation's persisted semantic authority.

    Gate-12S owns the immutable operation binding; the M5 candidate owns the
    copy-backed semantic Working Set.  This boundary is called by the M5
    postcondition owner only after a completed operation is judged failed or
    rejected.  It never changes the attempt, latch, capability, outbox, or
    append-only item/event/history rows.
    """

    if not configured(env):
        return None
    root = root_from_env(env)
    control = Gate12SAttemptStore(root, require_existing=True)
    try:
        attempt = control.read_attempt(client_turn_id)
        if (
            attempt is None
            or attempt["state"] != "completed"
            or attempt["provider_operation_id"] != provider_operation_id
        ):
            raise Gate12SControlError(
                "gate12s_non_authoritative_operation_not_completed"
            )
        mode = attempt["mode"]
    finally:
        control.close()
    return milestone5.record_non_authoritative_operation(
        env=env,
        gate12_root=semantic_root(root, mode),
        source_operation_id=provider_operation_id,
        reason_code=reason_code,
        recorded_at=recorded_at,
    )


def bind_android_session_sync(
    payload: Any, *, env: Mapping[str, str]
) -> dict[str, Any] | None:
    if not configured(env) or not isinstance(payload, Mapping):
        return None
    root = root_from_env(env)
    store = Gate12SAttemptStore(root, require_existing=True)
    try:
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return None
        ids = [
            str(value.get("message_id") or "")
            for value in messages
            if isinstance(value, Mapping) and value.get("from_astel") is True
        ]
        for client_turn_id in reversed(ids):
            attempt = store.read_attempt(client_turn_id)
            if attempt is None:
                continue
            binding = store.read_operation_binding(client_turn_id)
            if binding is None:
                raise Gate12SControlError(
                    "gate12s_operation_binding_mismatch"
                )
            try:
                result = gate12.bind_android_session_sync(
                    payload, env=_gate12_env(env, root, attempt["mode"])
                )
                if isinstance(result, Mapping) and result.get("complete_unit_id"):
                    milestone5_receipt = milestone5.apply_bound_sync(
                        env=env,
                        gate12_root=semantic_root(root, attempt["mode"]),
                        payload=payload,
                        client_turn_id=client_turn_id,
                        provider_operation_id=binding["provider_operation_id"],
                        room_id=binding["room_id"],
                        bundle_id=str(result.get("outbox_bundle_id") or ""),
                        now=_now(),
                    )
                    store.record_complete_unit(
                        client_turn_id, str(result["complete_unit_id"])
                    )
                    if milestone5_receipt is not None:
                        return {
                            **dict(result),
                            "milestone5_candidate": milestone5_receipt,
                        }
                return result
            except Exception:
                # The provider operation is terminal only after the outer
                # Gate-12S completion receipt is durable.  Preserve the
                # original pre-completion failure and keep that path a
                # deterministic no-op; only a completed operation may have
                # its persisted semantic lineage finalized below.
                completed = store.read_attempt(client_turn_id)
                if (
                    completed is not None
                    and completed["state"] == "completed"
                    and completed["provider_operation_id"]
                    == binding["provider_operation_id"]
                ):
                    # If M2 appended semantic history before a later M5
                    # lifecycle step failed, preserve those rows but remove
                    # their authority through the canonical operation-bound
                    # lineage owner.  This is idempotent on crash/replay and
                    # a no-op before persistence.
                    record_non_authoritative_semantic_operation(
                        env=env,
                        client_turn_id=client_turn_id,
                        provider_operation_id=binding["provider_operation_id"],
                        reason_code="m5_semantic_operation_failed",
                        recorded_at=_now(),
                    )
                raise
        return None
    finally:
        store.close()


def enforce_external_call_policy(linkage: Mapping[str, Any] | None) -> None:
    if not isinstance(linkage, Mapping):
        return
    turn = str(linkage.get("house_turn_id") or "")
    purpose = str(linkage.get("purpose") or "")
    provider_operation_id = str(
        linkage.get("provider_operation_id")
        or linkage.get("operation_id")
        or ""
    )
    if not turn:
        return
    with _LOCK:
        binding = _PROCESS_BINDINGS.get(turn)
    if binding is None and configured(None):
        try:
            root = root_from_env(None)
            store = Gate12SAttemptStore(root, require_existing=True)
            try:
                attempt = store.read_attempt(turn)
                if attempt is not None:
                    binding = (root, attempt["mode"])
                    with _LOCK:
                        _PROCESS_BINDINGS[turn] = binding
            finally:
                store.close()
        except Gate12SControlError:
            raise Gate12SExternalCallDenied("gate12s_store_unavailable")
    if binding is None:
        return
    store = Gate12SAttemptStore(binding[0], require_existing=True)
    try:
        attempt = store.read_attempt(turn)
        if (
            attempt is None
            or provider_operation_id
            != attempt["provider_operation_id"]
        ):
            if attempt is not None:
                store.record_denied_transport(turn)
            raise Gate12SExternalCallDenied(
                "gate12s_provider_operation_mismatch"
            )
        store.authorize_transport(turn, purpose)
    finally:
        store.close()


def _bind_required_milestone5_phase(
    *,
    root: Path,
    mode: str,
    attempt: Mapping[str, Any] | None,
    operation_binding: Mapping[str, Any] | None,
    prepared_operation: Gate12SPreparedOperation | None,
    provider_operation_id: str,
    phase: str,
    request_body: bytes,
) -> None:
    if attempt is None or operation_binding is None:
        raise Gate12SExternalCallDenied(
            "gate12s_milestone5_artifact_requirement_missing"
        )
    required_value = attempt.get("milestone5_artifact_required")
    expected_sha256 = attempt.get("milestone5_artifact_sha256")
    prepared_sha256 = (
        prepared_operation.milestone5_artifact_sha256
        if prepared_operation is not None
        else None
    )
    if required_value not in {0, 1, False, True}:
        raise Gate12SExternalCallDenied(
            "gate12s_milestone5_artifact_requirement_invalid"
        )
    if not bool(required_value):
        if expected_sha256 is not None or prepared_sha256 is not None:
            raise Gate12SExternalCallDenied(
                "gate12s_milestone5_artifact_requirement_mismatch"
            )
        return
    if (
        _SHA_RE.fullmatch(str(expected_sha256 or "")) is None
        or prepared_sha256 not in {None, expected_sha256}
    ):
        raise Gate12SExternalCallDenied(
            "gate12s_milestone5_artifact_requirement_mismatch"
        )
    try:
        persisted_artifact = milestone5.persisted_operation_artifact(
            gate12_root=semantic_root(root, mode),
            operation_id=provider_operation_id,
        )
    except Exception as exc:
        raise Gate12SExternalCallDenied(
            "gate12s_milestone5_artifact_integrity_invalid"
        ) from exc
    if persisted_artifact is None:
        raise Gate12SExternalCallDenied(
            "gate12s_milestone5_required_artifact_missing"
        )
    if (
        persisted_artifact.get("artifact_sha256") != expected_sha256
        or persisted_artifact.get("client_turn_id")
        != attempt.get("client_turn_id")
        or persisted_artifact.get("provider_operation_id")
        != provider_operation_id
        or persisted_artifact.get("room_id")
        != operation_binding.get("room_id")
    ):
        raise Gate12SExternalCallDenied(
            "gate12s_milestone5_artifact_mismatch"
        )
    try:
        milestone5.bind_operation_phase(
            env={milestone5.SWITCH_ENV: milestone5.CANDIDATE},
            gate12_root=semantic_root(root, mode),
            operation_id=provider_operation_id,
            phase=phase,
            artifact_sha256=expected_sha256,
            phase_input_sha256=_sha(request_body),
        )
    except Exception as exc:
        raise Gate12SExternalCallDenied(
            f"gate12s_milestone5_{phase}_binding_failed"
        ) from exc


def validate_final_request_boundary(
    *,
    house_turn_id: str | None,
    purpose: str | None,
    provider_operation_id: str | None,
    request_body: bytes,
) -> None:
    if not house_turn_id:
        return
    with _LOCK:
        binding = _PROCESS_BINDINGS.get(house_turn_id)
        prepared_operation = _PREPARED_OPERATIONS.get(house_turn_id)
    if binding is None and configured(None):
        try:
            root = root_from_env(None)
            store = Gate12SAttemptStore(
                root,
                require_existing=True,
            )
            try:
                attempt = store.read_attempt(house_turn_id)
                if attempt is not None:
                    binding = (root, attempt["mode"])
                    with _LOCK:
                        _PROCESS_BINDINGS[house_turn_id] = binding
            finally:
                store.close()
        except Gate12SControlError as exc:
            raise Gate12SExternalCallDenied(
                "gate12s_store_unavailable"
            ) from exc
    if binding is None:
        return
    if purpose != ALLOWED_MAIN_PURPOSE:
        raise Gate12SExternalCallDenied(
            "gate12s_rehearsal_purpose_invalid"
        )
    store = Gate12SAttemptStore(binding[0], require_existing=True)
    try:
        attempt = store.read_attempt(house_turn_id)
        operation_binding = store.read_operation_binding(house_turn_id)
        store.record_final_request_boundary(
            house_turn_id,
            provider_operation_id=str(provider_operation_id or ""),
            final_request_sha256=_sha(request_body),
        )
    except Gate12SControlError as exc:
        raise Gate12SExternalCallDenied(exc.error_code) from exc
    finally:
        store.close()
    _bind_required_milestone5_phase(
        root=binding[0],
        mode=binding[1],
        attempt=attempt,
        operation_binding=operation_binding,
        prepared_operation=prepared_operation,
        provider_operation_id=str(provider_operation_id or ""),
        phase="interception",
        request_body=request_body,
    )


def intercept_final_transport(
    *,
    house_turn_id: str | None,
    purpose: str | None,
    provider_operation_id: str | None,
    request_body: bytes,
) -> tuple[int, bytes] | None:
    if not house_turn_id:
        return None
    with _LOCK:
        binding = _PROCESS_BINDINGS.get(house_turn_id)
        reservation = _RESERVATIONS.get(house_turn_id)
        prepared_operation = _PREPARED_OPERATIONS.get(house_turn_id)
    if binding is None:
        return None
    store = Gate12SAttemptStore(binding[0], require_existing=True)
    try:
        attempt = store.read_attempt(house_turn_id)
        operation_binding = store.read_operation_binding(house_turn_id)
        if (
            attempt is None
            or attempt["provider_operation_id"]
            != provider_operation_id
            or attempt["endpoint_request_sha256"]
            != attempt["activation_endpoint_sha256"]
            or attempt["activation_endpoint_sha256"]
            != attempt["final_request_sha256"]
            or attempt["final_request_sha256"] != _sha(request_body)
        ):
            raise Gate12SExternalCallDenied(
                "gate12s_final_request_endpoint_mismatch"
            )
    finally:
        store.close()
    if binding[1] != REHEARSAL:
        _bind_required_milestone5_phase(
            root=binding[0],
            mode=binding[1],
            attempt=attempt,
            operation_binding=operation_binding,
            prepared_operation=prepared_operation,
            provider_operation_id=str(provider_operation_id or ""),
            phase="dispatch",
            request_body=request_body,
        )
        return None
    if purpose != ALLOWED_MAIN_PURPOSE:
        raise Gate12SExternalCallDenied("gate12s_rehearsal_purpose_invalid")
    if reservation is None or reservation.client_turn_id != house_turn_id:
        raise Gate12SExternalCallDenied(
            "gate12s_rehearsal_fixture_binding_failed"
        )
    try:
        body = json.loads(request_body.decode("utf-8"))
        text = "\n".join(
            str(item.get("content") or "")
            for item in body.get("messages", [])
            if isinstance(item, Mapping)
        )
        capability = reservation.clear_capability
        room_id = reservation.room_id
        if text.count(capability) != 1 or text.count(room_id) < 1:
            raise ValueError("exact reservation binding absent")
        if (
            body.get("tool_choice")
            != structured_terminal.forced_tool_choice()
            or body.get("parallel_tool_calls") is not False
            or not isinstance(body.get("tools"), list)
            or body["tools"][-1]
            != structured_terminal.provider_tool_definition()
        ):
            raise ValueError("structured terminal request absent")
    except Exception as exc:
        raise Gate12SExternalCallDenied(
            "gate12s_rehearsal_fixture_binding_failed"
        ) from exc
    arguments = {
        "visible_response": "Visible Gate 12S rehearsal reply.",
        "capability": capability,
        "continuity_decision": "apply_operation",
        "semantic_operations": [
            {
                "operation_key": "gate12s-rehearsal-create-1",
                "operation_kind": "create",
                "item_id": None,
                "expected_revision": 0,
                "item_kind": "active_topic",
                "scope": {
                    "scope_kind": "room",
                    "room_id": room_id,
                    "project_id": None,
                    "thread_id": None,
                },
                "summary": "Keep the Gate 12S rehearsal bounded.",
                "kind_payload": {"topic_state": "current", "linked_item_ids": []},
                "reason_code": (
                    "I am keeping this open through final review because "
                    "that is the meaning I choose."
                ),
                "superseded_by_item_id": None,
                "source_proposal_ids": [],
            }
        ],
    }
    response = {
        "id": "chatcmpl-gate12s-intercepted",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "gate12s-terminal-result-1",
                            "type": "function",
                            "function": {
                                "name": structured_terminal.TOOL_NAME,
                                "arguments": json.dumps(
                                    arguments,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    return 200, json.dumps(response, separators=(",", ":")).encode("utf-8")


def doctor(env: Mapping[str, str]) -> dict[str, Any]:
    raw_switch = str(env.get(SWITCH_ENV) or OFF).strip()
    configured_switch = mode_from_env(env)
    configured_root = str(env.get(ROOT_ENV) or "").strip()
    root = Path(configured_root).resolve() if configured_root else None
    store_path = (
        root / "gate12s_attempts.sqlite3" if root is not None else None
    )
    if (
        raw_switch == OFF
        and (store_path is None or not store_path.exists())
    ):
        return {
            "schema_version": SCHEMA_VERSION,
            "state": "healthy",
            "attempt_count": 0,
            "foreign_key_violation_count": 0,
            "raw_material_detected": False,
            "store_state": "absent_uninitialized",
            "configured_switch": configured_switch,
            "effective_switch": OFF,
            "effective_enabled": False,
            "semantic_application_enabled": False,
            "safe_for_source_eviction": False,
        }
    if root is None:
        raise Gate12SControlError("gate12s_root_unconfigured")
    store = Gate12SAttemptStore(root, require_existing=True)
    try:
        return {
            **store.doctor(),
            "store_state": "present",
            "configured_switch": configured_switch,
            "effective_switch": effective_mode(env),
            "effective_enabled": effective_mode(env) != OFF,
            "semantic_application_enabled": False,
            "safe_for_source_eviction": False,
        }
    finally:
        store.close()


__all__ = [
    "DEPLOYED_COMMIT_ENV",
    "GATE_ID",
    "Gate12SAttemptStore",
    "Gate12SControlError",
    "Gate12SExternalCallDenied",
    "LIVE_CANARY",
    "OFF",
    "REHEARSAL",
    "REHEARSAL_TURN_ENV",
    "ROOT_ENV",
    "SWITCH_ENV",
    "accept_natural_turn",
    "activate_runtime",
    "arm",
    "attempt_for_turn",
    "bind_android_session_sync",
    "build_no_provider_generation2_preflight",
    "configured",
    "doctor",
    "enforce_external_call_policy",
    "intercept_final_transport",
    "mark_predecessor_attestation_pass",
    "mark_rehearsal_review_pass",
    "mode_from_env",
    "process_provider_response",
    "record_non_authoritative_semantic_operation",
    "record_generation2_readiness",
    "receipt_for_turn",
    "root_from_env",
    "semantic_root",
]
