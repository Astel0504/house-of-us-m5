"""Protected Gate-12 carrier preparation with no semantic application."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
from typing import Any, Mapping, Sequence

from house_continuity_v1_2_capability_terminal_parser_local import (
    HouseContinuityCapabilityRegistryLocal,
    HouseContinuityTerminalParserLocal,
)
import house_continuity_v1_2_contract_schema_v0 as contracts
from house_continuity_v1_2_durable_preparation_outbox_local import (
    HouseContinuityDurablePreparationOutboxLocal,
)
from house_continuity_v1_2_provider_completion_replay_local import (
    HouseContinuityProviderCompletionReplayLocal,
)
import house_continuity_v1_2_standing_root_generation2_local as generation2
import house_continuity_v1_2_structured_terminal_result_v1 as structured_terminal
import house_continuity_v1_2_route_binding_local as route_binding_local
from house_complete_continuity_unit_v1_facade import (
    build_visible_exchange_from_android_sync,
)
import api_talk_response_shape_v0 as response_shape
import house_prompt_cache_production_v1 as prompt_cache
import house_provider_chat_serialization_v0 as chat_serialization
import house_standing_root_v2_production_v1 as production
import talk_continuity_authorship_intent_v1 as continuity_law
import talk_memory_authorship_intent_v0 as memory_law


GATE_ID = "HOUSE_CONTINUITY_V1_2_AUTHORED_CARRIER_PROTECTED_SHADOW"
SWITCH_ENV = GATE_ID
ROOT_ENV = "HOUSE_CONTINUITY_V1_2_GATE12_PRIVATE_ROOT"
DEPLOYED_COMMIT_ENV = "HOUSE_CONTINUITY_V1_2_GATE12_DEPLOYED_COMMIT"
OFF = "off"
PROTECTED_SHADOW = "protected_shadow"
CONTROL_SCHEMA_VERSION = "house_continuity_v1_2_gate12_control_v1"
RECEIPT_SCHEMA_VERSION = "house_continuity_v1_2_gate12_receipt_v1"
SERVICE_BOOT_ID = "cws_boot_" + secrets.token_hex(16)
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
_IDENTITY_RE = re.compile(r"[A-Za-z0-9_-]{1,180}")


class Gate12ProtectedShadowError(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _fail(code: str) -> None:
    raise Gate12ProtectedShadowError(code)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha(value: bytes | str) -> str:
    body = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(body).hexdigest()


def _now(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _millisecond_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise Gate12ProtectedShadowError("gate12_time_invalid") from exc
    return _now(parsed)


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
        or _now(parsed) != value
    ):
        return None
    return parsed


def _configured(env: Mapping[str, str]) -> bool:
    return str(env.get(SWITCH_ENV) or OFF).strip() == PROTECTED_SHADOW


def _deployed_commit(env: Mapping[str, str]) -> str:
    value = str(env.get(DEPLOYED_COMMIT_ENV) or "").strip()
    if (
        len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail("gate12_deployed_commit_required")
    return value


def root_from_env(env: Mapping[str, str]) -> Path:
    raw = str(env.get(ROOT_ENV) or "").strip()
    if not raw:
        _fail("gate12_private_root_unconfigured")
    root = Path(raw).resolve()
    if not root.exists() or not root.is_dir():
        _fail("gate12_private_root_unavailable")
    if os.name != "nt":
        info = root.stat()
        if stat.S_IMODE(info.st_mode) != PRIVATE_DIRECTORY_MODE:
            _fail("gate12_private_root_mode_invalid")
        if info.st_uid != os.geteuid():
            _fail("gate12_private_root_owner_invalid")
    return root


def _secure_children(root: Path) -> None:
    if os.name == "nt":
        return
    for child in root.iterdir():
        os.chmod(
            child,
            PRIVATE_DIRECTORY_MODE if child.is_dir() else PRIVATE_FILE_MODE,
        )


class Gate12ControlStore:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "gate12_control.sqlite3"
        self.connection = sqlite3.connect(
            str(self.path), timeout=0.2, isolation_level=None
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
              operation_id TEXT
            );
            CREATE TABLE IF NOT EXISTS turns(
              operation_id TEXT PRIMARY KEY,
              client_turn_id TEXT NOT NULL UNIQUE,
              state TEXT NOT NULL,
              receipt_json TEXT NOT NULL,
              receipt_sha256 TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS service_boots(
              service_boot_id TEXT PRIMARY KEY,
              deployed_commit TEXT NOT NULL,
              first_seen_at TEXT NOT NULL
            );
            """
        )
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO meta VALUES('schema_version',?)",
                (CONTROL_SCHEMA_VERSION,),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO meta VALUES('store_id',?)",
                ("gate12_" + secrets.token_hex(16),),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO latch VALUES(1,'unarmed',1,NULL,NULL,NULL)"
            )
        _secure_children(root)

    def close(self) -> None:
        self.connection.close()

    def register_boot(
        self, *, deployed_commit: str, at: str
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO service_boots VALUES(?,?,?)",
                (SERVICE_BOOT_ID, deployed_commit, at),
            )

    def arm(self, *, at: str) -> dict[str, Any]:
        self.connection.execute("BEGIN IMMEDIATE")
        row = self.connection.execute(
            "SELECT * FROM latch WHERE singleton=1"
        ).fetchone()
        if row["state"] == "consumed":
            prior = self.connection.execute(
                "SELECT state FROM turns WHERE operation_id=?",
                (row["operation_id"],),
            ).fetchone()
            if prior is None or prior["state"] not in {
                "ready_to_apply_shadow_only",
                "explicit_solen_no_semantic_delta",
            }:
                self.connection.rollback()
                _fail("gate12_latch_already_consumed")
        self.connection.execute(
            "UPDATE latch SET state='armed',revision=revision+1,armed_at=?,"
            "consumed_at=NULL,operation_id=NULL WHERE singleton=1",
            (at,),
        )
        self.connection.commit()
        return self.latch()

    def latch(self) -> dict[str, Any]:
        return dict(
            self.connection.execute(
                "SELECT state,revision,armed_at,consumed_at,operation_id"
                " FROM latch WHERE singleton=1"
            ).fetchone()
        )

    def consume(
        self,
        *,
        operation_id: str,
        client_turn_id: str,
        receipt: Mapping[str, Any],
        at: str,
    ) -> bool:
        encoded = _canonical(receipt).decode("ascii")
        self.connection.execute("BEGIN IMMEDIATE")
        changed = self.connection.execute(
            "UPDATE latch SET state='consumed',revision=revision+1,"
            "consumed_at=?,operation_id=? WHERE singleton=1 AND state='armed'",
            (at, operation_id),
        ).rowcount
        if changed != 1:
            self.connection.rollback()
            return False
        self.connection.execute(
            "INSERT INTO turns VALUES(?,?,?,?,?)",
            (
                operation_id,
                client_turn_id,
                "reserved",
                encoded,
                _sha(encoded),
            ),
        )
        self.connection.commit()
        return True

    def update_turn(
        self, operation_id: str, *, state: str, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM turns WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            _fail("gate12_turn_not_found")
        if self._turn_integrity_error(row) is not None:
            _fail("gate12_control_turn_integrity_failed")
        receipt = json.loads(row["receipt_json"])
        receipt.update(copy.deepcopy(dict(values)))
        receipt["completion_state"] = state
        encoded = _canonical(receipt).decode("ascii")
        with self.connection:
            self.connection.execute(
                "UPDATE turns SET state=?,receipt_json=?,receipt_sha256=?"
                " WHERE operation_id=?",
                (state, encoded, _sha(encoded), operation_id),
            )
        return receipt

    def awaiting_for_client_turn(
        self, client_turn_id: str
    ) -> tuple[str, dict[str, Any]] | None:
        row = self.connection.execute(
            "SELECT * FROM turns"
            " WHERE client_turn_id=? AND state='visible_released_waiting_unit'",
            (client_turn_id,),
        ).fetchone()
        if row is None:
            return None
        if self._turn_integrity_error(row) is not None:
            _fail("gate12_control_turn_integrity_failed")
        return row["operation_id"], json.loads(row["receipt_json"])

    @staticmethod
    def _turn_integrity_error(row: Mapping[str, Any]) -> str | None:
        try:
            receipt = json.loads(row["receipt_json"])
        except (TypeError, json.JSONDecodeError):
            return "receipt_json_invalid"
        if not isinstance(receipt, Mapping):
            return "receipt_json_invalid"
        encoded = _canonical(receipt).decode("ascii")
        if not secrets.compare_digest(
            str(row["receipt_sha256"]), _sha(encoded)
        ):
            return "receipt_sha256_mismatch"
        if (
            receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION
            or receipt.get("provider_operation_id")
            != row["operation_id"]
            or receipt.get("client_turn_id") != row["client_turn_id"]
            or receipt.get("completion_state") != row["state"]
        ):
            return "receipt_identity_or_state_mismatch"
        return None

    @staticmethod
    def _latch_integrity_error(
        latch: Mapping[str, Any],
    ) -> str | None:
        state = latch.get("state")
        if (
            state not in {"unarmed", "armed", "consumed"}
            or not isinstance(latch.get("revision"), int)
            or latch["revision"] < 1
        ):
            return "latch_shape_invalid"
        armed_at = latch.get("armed_at")
        consumed_at = latch.get("consumed_at")
        operation_id = latch.get("operation_id")
        if state == "unarmed":
            return (
                None
                if armed_at is None
                and consumed_at is None
                and operation_id is None
                else "latch_unarmed_fields_invalid"
            )
        if not isinstance(armed_at, str):
            return "latch_armed_at_invalid"
        try:
            _millisecond_time(armed_at)
        except Gate12ProtectedShadowError:
            return "latch_armed_at_invalid"
        if state == "armed":
            return (
                None
                if consumed_at is None and operation_id is None
                else "latch_armed_fields_invalid"
            )
        if not isinstance(consumed_at, str):
            return "latch_consumed_at_invalid"
        try:
            _millisecond_time(consumed_at)
        except Gate12ProtectedShadowError:
            return "latch_consumed_at_invalid"
        if not isinstance(operation_id, str) or not operation_id:
            return "latch_operation_id_invalid"
        return None

    def doctor(
        self, *, require_current_boot: bool = True
    ) -> dict[str, Any]:
        integrity = self.connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        foreign = self.connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        meta = dict(self.connection.execute("SELECT key,value FROM meta"))
        meta_valid = (
            set(meta) == {"schema_version", "store_id"}
            and meta.get("schema_version") == CONTROL_SCHEMA_VERSION
            and isinstance(meta.get("store_id"), str)
            and len(meta["store_id"]) == 39
            and meta["store_id"].startswith("gate12_")
            and all(
                character in "0123456789abcdef"
                for character in meta["store_id"][7:]
            )
        )
        latch = self.latch()
        latch_error = self._latch_integrity_error(latch)
        turn_errors = [
            error
            for row in self.connection.execute("SELECT * FROM turns")
            if (error := self._turn_integrity_error(row)) is not None
        ]
        service_boot_errors = []
        service_boot_ids = set()
        for row in self.connection.execute("SELECT * FROM service_boots"):
            service_boot_ids.add(row["service_boot_id"])
            if not isinstance(row["first_seen_at"], str):
                service_boot_errors.append("service_boot_time_invalid")
            else:
                try:
                    _millisecond_time(row["first_seen_at"])
                except Gate12ProtectedShadowError:
                    service_boot_errors.append(
                        "service_boot_time_invalid"
                    )
            if (
                not isinstance(row["service_boot_id"], str)
                or not row["service_boot_id"].startswith("cws_boot_")
                or len(row["service_boot_id"]) != 41
                or len(row["deployed_commit"]) != 40
                or any(
                    character not in "0123456789abcdef"
                    for character in row["deployed_commit"]
                )
            ):
                service_boot_errors.append("service_boot_identity_invalid")
        current_boot_registered = SERVICE_BOOT_ID in service_boot_ids
        healthy = (
            integrity == "ok"
            and not foreign
            and meta_valid
            and latch_error is None
            and not turn_errors
            and not service_boot_errors
            and (not require_current_boot or current_boot_registered)
        )
        return {
            "schema_version": CONTROL_SCHEMA_VERSION,
            "store_id": meta.get("store_id"),
            "integrity": integrity,
            "foreign_key_violation_count": len(foreign),
            "meta_valid": meta_valid,
            "latch": latch,
            "latch_integrity_error": latch_error,
            "turn_count": self.connection.execute(
                "SELECT COUNT(*) FROM turns"
            ).fetchone()[0],
            "turn_integrity_violation_count": len(turn_errors),
            "turn_integrity_errors": sorted(set(turn_errors)),
            "service_boot_count": self.connection.execute(
                "SELECT COUNT(*) FROM service_boots"
            ).fetchone()[0],
            "service_boot_integrity_violation_count": len(
                service_boot_errors
            ),
            "current_service_boot_required": require_current_boot,
            "current_service_boot_registered": current_boot_registered,
            "state": "healthy" if healthy else "corrupt_or_incomplete",
            "required_directory_mode_octal": "0700",
            "required_file_mode_octal": "0600",
            "raw_body_included": False,
        }


@dataclass
class Gate12Reservation:
    root: Path
    client_turn_id: str
    session_id: str
    room_id: str
    provider_operation_id: str
    capability_id: str
    clear_capability: str = field(repr=False)
    issued_at: str
    expires_at: str
    command_context: Mapping[str, Any] = field(repr=False)
    offer: Mapping[str, Any] = field(repr=False)
    route_binding: Mapping[str, Any] | None = field(
        default=None, repr=False
    )
    initial_request_capture: list[bytes] = field(
        default_factory=list, repr=False
    )
    generation_identity: Mapping[str, Any] | None = None
    provider_stable_message_count: int = 0


def _room_id(session_id: str) -> str:
    return route_binding_local.derive_room_id(session_id)


def _command_context(room_id: str, operation_id: str) -> dict[str, Any]:
    scope = {
        "scope_kind": "room",
        "room_id": room_id,
        "project_id": None,
        "thread_id": None,
    }
    seed = _sha("gate12-context:" + operation_id)
    value = {
        "schema_version": contracts.COMMAND_CONTEXT_SCHEMA_VERSION,
        "context_id": "cws_ctx_" + seed[:32],
        "creation_seed_sha256": seed,
        "snapshot_global_event_sequence": 0,
        "snapshot_global_event_sha256": _sha("gate12-empty-snapshot"),
        "room_id": room_id,
        "scope_binding_revision": 1,
        "items": [],
        "create_offers": [
            {
                "offer_id": "cws_offer_" + _sha(
                    "gate12-offer:" + operation_id
                )[:32],
                "scope": scope,
                "allowed_item_kinds": [
                    "active_topic",
                    "active_task",
                    "question",
                    "commitment",
                    "decision",
                    "temporary_fact",
                    "emotional_thread",
                    "pending_review",
                ],
            }
        ],
        "provisional_scope_binding_choices": [],
        "authority": dict(contracts.COMMAND_CONTEXT_AUTHORITY),
    }
    return contracts.validate_command_context(value)


def _readiness(root: Path) -> dict[str, Any]:
    registry = HouseContinuityCapabilityRegistryLocal(
        root, protected_shadow_only=True
    )
    outbox = HouseContinuityDurablePreparationOutboxLocal(
        root, protected_shadow_only=True
    )
    replay = HouseContinuityProviderCompletionReplayLocal(
        root, protected_shadow_only=True
    )
    try:
        gate4 = registry.doctor(require_outbox_links=True)
        gate5 = outbox.doctor()
        gate5_replay = replay.doctor()
        return generation2.validate_readiness(
            {
                "schema_version": generation2.READINESS_SCHEMA_VERSION,
                "protocol_version": structured_terminal.PROTOCOL_VERSION,
                "instruction_owner_available": True,
                "issuer_registry_available": True,
                "parser_available": True,
                "stripper_available": True,
                "recovery_owner_available": True,
                "outbox_available": True,
                "gate4_doctor_ok": (
                    gate4.get("sqlite_integrity") == "ok"
                    and gate4.get("raw_private_material_detected") is False
                ),
                "gate5_doctor_ok": (
                    gate5.get("foreign_keys_enabled") is True
                    and gate5.get("raw_body_detected") is False
                ),
                "replay_doctor_ok": (
                    gate5_replay.get("private_response_owner_separate")
                    is True
                ),
                "memory_route_attested": True,
                "standing_roots_attested": True,
                "tools_attested": True,
                "raw_body_included": False,
            }
        )
    finally:
        replay.close()
        outbox.close()
        registry.close()


def prepare_turn(
    *,
    env: Mapping[str, str],
    client_turn_id: str,
    session_id: str,
    provider_operation_id: str,
    clear_capability: str,
    capability_id: str,
    issued_at: str,
    expires_at: str,
    route_binding: Mapping[str, Any] | None = None,
    command_context: Mapping[str, Any] | None = None,
) -> Gate12Reservation | None:
    if (
        not _configured(env)
        or str(env.get(generation2.GENERATION_SELECTOR) or "").strip()
        != generation2.GENERATION_2
    ):
        return None
    root = root_from_env(env)
    issued = _parsed_timestamp(issued_at)
    expires = _parsed_timestamp(expires_at)
    if (
        _IDENTITY_RE.fullmatch(client_turn_id) is None
        or _IDENTITY_RE.fullmatch(provider_operation_id) is None
        or not re.fullmatch(r"cwcap_[0-9a-f]{32}", capability_id)
        or not re.fullmatch(r"cwc_[A-Za-z0-9_-]{43}", clear_capability)
        or issued is None
        or expires is None
        or expires != issued + timedelta(minutes=60)
    ):
        _fail("gate12_prepared_binding_invalid")
    if route_binding is None:
        room_id = _room_id(session_id)
        normalized_route_binding = None
    else:
        normalized_route_binding = (
            route_binding_local.validate_operation_binding(route_binding)
        )
        if normalized_route_binding["transient_session_id"] != session_id:
            _fail("gate12_prepared_route_binding_mismatch")
        room_id = normalized_route_binding["room_id"]
    context = (
        _command_context(room_id, provider_operation_id)
        if command_context is None
        else contracts.validate_command_context(command_context)
    )
    if context["room_id"] != room_id:
        _fail("gate12_prepared_route_binding_mismatch")
    offer = generation2.continuity_offer(
        capability=clear_capability,
        command_context=context,
        expires_at=expires_at,
        maximum_total_operations=1,
        client_turn_id=client_turn_id,
        room_id=room_id,
        provider_operation_id=provider_operation_id,
    )
    return Gate12Reservation(
        root=root,
        client_turn_id=client_turn_id,
        session_id=session_id,
        room_id=room_id,
        provider_operation_id=provider_operation_id,
        capability_id=capability_id,
        clear_capability=clear_capability,
        issued_at=issued_at,
        expires_at=expires_at,
        command_context=context,
        offer=offer,
        route_binding=normalized_route_binding,
    )


def commit_prepared_turn(
    *,
    env: Mapping[str, str],
    reservation: Gate12Reservation,
) -> Gate12Reservation | None:
    if (
        not _configured(env)
        or str(env.get(generation2.GENERATION_SELECTOR) or "").strip()
        != generation2.GENERATION_2
    ):
        return None
    if reservation.root != root_from_env(env):
        _fail("gate12_prepared_root_mismatch")
    expected = prepare_turn(
        env=env,
        client_turn_id=reservation.client_turn_id,
        session_id=reservation.session_id,
        provider_operation_id=reservation.provider_operation_id,
        clear_capability=reservation.clear_capability,
        capability_id=reservation.capability_id,
        issued_at=reservation.issued_at,
        expires_at=reservation.expires_at,
        route_binding=reservation.route_binding,
        command_context=reservation.command_context,
    )
    if expected is None:
        return None
    if (
        expected.root != reservation.root
        or expected.provider_operation_id != reservation.provider_operation_id
        or expected.client_turn_id != reservation.client_turn_id
        or expected.session_id != reservation.session_id
        or expected.capability_id != reservation.capability_id
        or expected.clear_capability != reservation.clear_capability
        or expected.issued_at != reservation.issued_at
        or expected.expires_at != reservation.expires_at
        or dict(expected.command_context) != dict(reservation.command_context)
        or dict(expected.offer) != dict(reservation.offer)
        or (
            None
            if expected.route_binding is None
            else dict(expected.route_binding)
        )
        != (
            None
            if reservation.route_binding is None
            else dict(reservation.route_binding)
        )
    ):
        _fail("gate12_prepared_binding_mismatch")
    deployed_commit = _deployed_commit(env)
    control = Gate12ControlStore(reservation.root)
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "gate_id": GATE_ID,
        "service_boot_id": SERVICE_BOOT_ID,
        "deployed_commit": deployed_commit,
        "client_turn_id": reservation.client_turn_id,
        "room_id": reservation.room_id,
        "provider_operation_id": reservation.provider_operation_id,
        "capability_id": reservation.capability_id,
        "capability_sha256": _sha(reservation.clear_capability),
        "maximum_total_operations": 1,
        "semantic_application_enabled": False,
        "safe_for_source_eviction": False,
        "completion_state": "reserved",
    }
    try:
        control.register_boot(
            deployed_commit=deployed_commit,
            at=reservation.issued_at,
        )
        if control.doctor()["state"] != "healthy":
            _fail("gate12_control_store_unhealthy")
        if not control.consume(
            operation_id=reservation.provider_operation_id,
            client_turn_id=reservation.client_turn_id,
            receipt=receipt,
            at=reservation.issued_at,
        ):
            return None
    finally:
        control.close()
    registry = HouseContinuityCapabilityRegistryLocal(
        reservation.root, protected_shadow_only=True
    )
    try:
        capability_record = {
                "schema_version": contracts.CAPABILITY_SCHEMA_VERSION,
                "capability_id": reservation.capability_id,
                "creation_seed_sha256": _sha(
                    "gate12-capability:" + reservation.provider_operation_id
                ),
                "capability_sha256": _sha(reservation.clear_capability),
                "client_turn_id": reservation.client_turn_id,
                "room_id": reservation.room_id,
                "provider_operation_id": reservation.provider_operation_id,
                "protocol_version": structured_terminal.PROTOCOL_VERSION,
                "command_context_id": reservation.command_context["context_id"],
                "command_context_sha256": contracts.canonical_sha256(
                    reservation.command_context
                ),
                "snapshot_global_event_sequence": (
                    reservation.command_context[
                        "snapshot_global_event_sequence"
                    ]
                ),
                "snapshot_global_event_sha256": reservation.command_context[
                    "snapshot_global_event_sha256"
                ],
                "scope_binding_revision": reservation.command_context[
                    "scope_binding_revision"
                ],
                "coverage_binding_state": "pending_complete_unit",
                "covered_complete_unit_ids": [],
                "covered_complete_unit_sha256s": [],
                "state": "issued",
                "issued_at": reservation.issued_at,
                "expires_at": reservation.expires_at,
                "consumed_at": None,
                "outbox_bundle_id": None,
                "terminal_response_sha256": None,
                "replay_attempt_count": 0,
            }
        try:
            registry.issue(
                capability_record,
                clear_capability=reservation.clear_capability,
            )
        except Exception as exc:
            existing = registry.read(reservation.capability_id)
            if existing is not None and existing["state"] == "issued":
                registry.invalidate(
                    reservation.capability_id,
                    client_turn_id=reservation.client_turn_id,
                    room_id=reservation.room_id,
                    provider_operation_id=reservation.provider_operation_id,
                    protocol_version=structured_terminal.PROTOCOL_VERSION,
                    terminal_response_sha256=_sha(b""),
                    at=reservation.issued_at,
                )
            failed_control = Gate12ControlStore(reservation.root)
            try:
                failed_control.update_turn(
                    reservation.provider_operation_id,
                    state="activation_failed",
                    values={
                        "error_code": str(
                            getattr(
                                exc,
                                "error_code",
                                "gate12_capability_issue_failed",
                            )
                        )[:120],
                        "semantic_application_enabled": False,
                        "safe_for_source_eviction": False,
                    },
                )
            finally:
                failed_control.close()
            raise
    finally:
        registry.close()
    return reservation


def reserve_turn(
    *,
    env: Mapping[str, str],
    client_turn_id: str,
    session_id: str,
    provider_operation_id: str,
    now: datetime | None = None,
) -> Gate12Reservation | None:
    current = now or datetime.now(timezone.utc)
    reservation = prepare_turn(
        env=env,
        client_turn_id=client_turn_id,
        session_id=session_id,
        provider_operation_id=provider_operation_id,
        clear_capability="cwc_" + secrets.token_urlsafe(32)[:43],
        capability_id="cwcap_" + secrets.token_hex(16),
        issued_at=_now(current),
        expires_at=_now(current + timedelta(minutes=60)),
    )
    if reservation is None:
        return None
    return commit_prepared_turn(env=env, reservation=reservation)


def prepare_generation2_operation(
    reservation: Gate12Reservation,
    generation1_selection: production.ProductionPromptSelection,
    *,
    broker: Any,
    working_set_section: Mapping[str, Any] | None = None,
    context_sections: Sequence[Mapping[str, Any]] | None = None,
    integrated_context_sections: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[
    generation2.StandingRootGeneration2Candidate,
    production.ProductionPromptSelection,
]:
    candidate = generation2.build_generation2_candidate(
        generation1_selection=generation1_selection,
        broker=broker,
        capability=reservation.clear_capability,
        command_context=reservation.command_context,
        readiness=_readiness(reservation.root),
        offer=reservation.offer,
        working_set_section=working_set_section,
        context_sections=context_sections,
        integrated_context_sections=integrated_context_sections,
    )
    generation2.attest_generation2_candidate(candidate)
    selection = generation2.production_selection_from_candidate(
        candidate,
        generation1_selection,
    )
    if (
        candidate.generation2_identity[
            "canonical_semantic_stable_surface_sha256"
        ]
        != "2b9a0129829dfa24950a0f36c5b79e6ac0553170356f4b897197bd1a668c9dff"
    ):
        _fail("gate12_generation2_identity_mismatch")
    reservation.generation_identity = copy.deepcopy(
        candidate.generation2_identity
    )
    reservation.provider_stable_message_count = (
        candidate.generation2_assembly.request_observability[
            "stable_message_count"
        ]
        + 1
    )
    return candidate, selection


def generation2_selection(
    reservation: Gate12Reservation,
    generation1_selection: production.ProductionPromptSelection,
    *,
    broker: Any,
    working_set_section: Mapping[str, Any] | None = None,
    context_sections: Sequence[Mapping[str, Any]] | None = None,
    integrated_context_sections: Sequence[Mapping[str, Any]] | None = None,
) -> production.ProductionPromptSelection:
    return prepare_generation2_operation(
        reservation,
        generation1_selection,
        broker=broker,
        working_set_section=working_set_section,
        context_sections=context_sections,
        integrated_context_sections=integrated_context_sections,
    )[1]


def abort_reservation(
    reservation: Gate12Reservation, *, error_code: str
) -> None:
    at = _now()
    registry = HouseContinuityCapabilityRegistryLocal(
        reservation.root, protected_shadow_only=True
    )
    control = Gate12ControlStore(reservation.root)
    try:
        capability = registry.read(reservation.capability_id)
        if capability is not None and capability["state"] == "issued":
            registry.invalidate(
                reservation.capability_id,
                client_turn_id=reservation.client_turn_id,
                room_id=reservation.room_id,
                provider_operation_id=reservation.provider_operation_id,
                protocol_version=structured_terminal.PROTOCOL_VERSION,
                terminal_response_sha256=_sha(b""),
                at=at,
            )
        control.update_turn(
            reservation.provider_operation_id,
            state="activation_failed",
            values={
                "error_code": str(error_code)[:120],
                "semantic_application_enabled": False,
                "safe_for_source_eviction": False,
            },
        )
    finally:
        control.close()
        registry.close()


def emergency_strip(
    reservation: Gate12Reservation, assistant_text: Any
) -> dict[str, Any]:
    """Never expose a current offered private tail after a local failure."""

    text = str(assistant_text or "")
    response_bytes = text.encode("utf-8")
    memory_marker = b"\n<house-memory-intent>"
    memory_start = response_bytes.rfind(memory_marker)
    protected_end = (
        len(response_bytes) if memory_start < 0 else memory_start
    )
    memory = (
        None
        if memory_start < 0
        else response_bytes[memory_start + 1 :].decode("utf-8")
    )

    class CurrentCapabilityLookup:
        def lookup_clear(self, candidate: str) -> dict[str, bool] | None:
            return (
                {"current": True}
                if secrets.compare_digest(
                    candidate, reservation.clear_capability
                )
                else None
            )

    parser = HouseContinuityTerminalParserLocal(CurrentCapabilityLookup())
    attempt = parser._privacy_current_capability_attempt(
        response_bytes,
        terminal_content_end=protected_end,
    )
    if attempt is None:
        return {
            "visible_text": text,
            "memory_candidate_text": memory,
            "completion_state": "emergency_no_private_tail_found",
        }
    return {
        "visible_text": response_bytes[: attempt["start"]].decode("utf-8"),
        "memory_candidate_text": memory,
        "completion_state": "emergency_private_tail_stripped",
    }


def _pending_expectation(
    reservation: Gate12Reservation,
    *,
    expected_solen_visible_sha256: str,
) -> dict[str, Any]:
    body = {
        "expectation_state": "pending_android_sync",
        "client_turn_id": reservation.client_turn_id,
        "room_id": reservation.room_id,
        "permitted_unit_kinds": ["visible_exchange"],
        "expected_source_start_id": reservation.client_turn_id,
        "expected_source_end_id": None,
        "expected_astel_message_id": reservation.client_turn_id,
        "expected_solen_message_ids": [],
        "expected_solen_visible_sha256": (
            expected_solen_visible_sha256
        ),
        "expected_provider_operation_id": None,
        "raw_body_included": False,
    }
    return {**body, "expectation_sha256": contracts.canonical_sha256(body)}


def process_provider_response(
    reservation: Gate12Reservation,
    adapter_response: Mapping[str, Any],
    *,
    completed_at: str,
    structured_result: (
        structured_terminal.StructuredTerminalResult | None
    ) = None,
) -> dict[str, Any]:
    completed_at = _millisecond_time(completed_at)
    if not adapter_response.get("ok") or not isinstance(
        adapter_response.get("assistant_text"), str
    ):
        control = Gate12ControlStore(reservation.root)
        registry = HouseContinuityCapabilityRegistryLocal(
            reservation.root, protected_shadow_only=True
        )
        try:
            capability = registry.read(reservation.capability_id)
            if capability is not None and capability["state"] == "issued":
                registry.invalidate(
                    reservation.capability_id,
                    client_turn_id=reservation.client_turn_id,
                    room_id=reservation.room_id,
                    provider_operation_id=reservation.provider_operation_id,
                    protocol_version=structured_terminal.PROTOCOL_VERSION,
                    terminal_response_sha256=_sha(b""),
                    at=completed_at,
                )
            control.update_turn(
                reservation.provider_operation_id,
                state="provider_failed",
                values={
                    "provider_dispatch_count": int(
                        adapter_response.get("provider_leg_count") or 0
                    ),
                    "semantic_application_enabled": False,
                    "safe_for_source_eviction": False,
                },
            )
        finally:
            registry.close()
            control.close()
        return {
            "completion_state": "provider_failed",
            "visible_text": str(adapter_response.get("assistant_text") or ""),
            "memory_candidate_text": None,
        }
    structured_mode = reservation.generation_identity is not None
    if structured_mode and structured_result is None:
        failed = dict(adapter_response)
        failed["ok"] = False
        failed["assistant_text"] = ""
        return process_provider_response(
            reservation,
            failed,
            completed_at=completed_at,
        )
    response_bytes = (
        structured_result.raw_arguments
        if structured_result is not None
        else adapter_response["assistant_text"].encode("utf-8")
    )
    dispatch_facts = (
        adapter_response.get("_house_provider_dispatch_facts")
        if isinstance(
            adapter_response.get("_house_provider_dispatch_facts"),
            Mapping,
        )
        else {}
    )
    dispatched_sha = str(
        dispatch_facts.get("exact_dispatched_request_sha256") or ""
    )
    captured_shas = [
        _sha(value) for value in reservation.initial_request_capture
    ]
    request_bytes_invariant = (
        len(captured_shas) == 1
        and bool(dispatched_sha)
        and captured_shas[0] == dispatched_sha
        and int(dispatch_facts.get("provider_dispatch_count") or 0) == 1
        and int(dispatch_facts.get("provider_retry_count") or 0) == 0
        and int(dispatch_facts.get("provider_fallback_count") or 0) == 0
    )
    registry = HouseContinuityCapabilityRegistryLocal(
        reservation.root, protected_shadow_only=True
    )
    outbox = HouseContinuityDurablePreparationOutboxLocal(
        reservation.root, protected_shadow_only=True
    )
    replay = HouseContinuityProviderCompletionReplayLocal(
        reservation.root, protected_shadow_only=True
    )
    parser = HouseContinuityTerminalParserLocal(registry)
    arguments = {
        "client_turn_id": reservation.client_turn_id,
        "room_id": reservation.room_id,
        "provider_operation_id": reservation.provider_operation_id,
        "protocol_version": structured_terminal.PROTOCOL_VERSION,
        "command_context": reservation.command_context,
        "current_snapshot_sequence": reservation.command_context[
            "snapshot_global_event_sequence"
        ],
        "current_snapshot_sha256": reservation.command_context[
            "snapshot_global_event_sha256"
        ],
        "current_binding_revision": reservation.command_context[
            "scope_binding_revision"
        ],
    }
    try:
        replay.record_completion(
            provider_operation_id=reservation.provider_operation_id,
            client_turn_id=reservation.client_turn_id,
            room_id=reservation.room_id,
            terminal_response=response_bytes,
            completed_at=completed_at,
            projection_mode=(
                "structured_terminal_result"
                if structured_result is not None
                else "carrier_tail"
            ),
        )
        parsed = (
            structured_terminal.authority_parse_result(
                structured_result,
                registry=registry,
                capability_id=reservation.capability_id,
                expected_clear_capability=reservation.clear_capability,
                provider_request_bytes_invariant=(
                    request_bytes_invariant
                ),
                now=completed_at,
                **arguments,
            )
            if structured_result is not None
            else parser.parse(
                response_bytes, now=completed_at, **arguments
            )
        )
        visible_projection_sha256 = contracts.canonical_sha256(
            response_shape.split_visible_reply_segments(
                parsed["visible_bytes"].decode("utf-8")
            )["segments"]
        )
        normalized_intent = (
            parsed.get("normalized_intent")
            if isinstance(parsed.get("normalized_intent"), Mapping)
            else {}
        )
        operations = (
            normalized_intent.get("semantic_operations", [])
            if isinstance(
                normalized_intent.get("semantic_operations", []), list
            )
            else []
        )
        if parsed["continuity_write_permitted"] and len(operations) > 1:
            record = registry.read(reservation.capability_id)
            registry.reject_consumed(
                record,
                response_sha256=parsed["response_sha256"],
                result_code="rejected_gate12_operation_limit",
                at=completed_at,
            )
            parsed["continuity_state"] = "rejected_gate12_operation_limit"
            parsed["continuity_write_permitted"] = False
            parsed["any_write_permitted"] = bool(
                parsed["memory_write_permitted"]
            )
            parsed["capability_effect"] = "rejected_consumed"
        if (
            parsed["continuity_write_permitted"]
            and reservation.generation_identity is not None
            and not request_bytes_invariant
        ):
            record = registry.read(reservation.capability_id)
            registry.reject_consumed(
                record,
                response_sha256=parsed["response_sha256"],
                result_code="provider_request_byte_mismatch",
                at=completed_at,
            )
            parsed["continuity_state"] = "provider_request_byte_mismatch"
            parsed["continuity_write_permitted"] = False
            parsed["any_write_permitted"] = bool(
                parsed["memory_write_permitted"]
            )
            parsed["capability_effect"] = "rejected_consumed"
        outbox.record_provider_operation(
            provider_operation_id=reservation.provider_operation_id,
            client_turn_id=reservation.client_turn_id,
            room_id=reservation.room_id,
            terminal_response_sha256=parsed["response_sha256"],
            visible_response_sha256=parsed["visible_sha256"],
            completed_at=completed_at,
            complete_unit_expectation=_pending_expectation(
                reservation,
                expected_solen_visible_sha256=(
                    visible_projection_sha256
                ),
            ),
        )
        replay_state = replay.replay_parse_and_prepare(
            reservation.provider_operation_id,
            parser=parser,
            outbox=outbox,
            parser_arguments=arguments,
            now=completed_at,
            capability_id=reservation.capability_id,
            parsed_result=parsed,
        )
        visible = replay.release_visible(
            reservation.provider_operation_id,
            outbox=outbox,
            at=completed_at,
        )
        bundle_id = replay_state.get("outbox_bundle_id")
        state = (
            "visible_released_waiting_unit"
            if replay_state.get("state") == "prepared"
            else parsed["continuity_state"]
        )
        exact_stable_messages_sha256 = None
        exact_tool_block_sha256 = None
        dispatched_cache_key = None
        if len(reservation.initial_request_capture) == 1:
            try:
                captured_body = json.loads(
                    reservation.initial_request_capture[0].decode("utf-8")
                )
                exact_stable_messages_sha256 = _sha(
                    json.dumps(
                        captured_body["messages"][
                            : reservation.provider_stable_message_count
                        ],
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                exact_tool_block_sha256 = _sha(
                    json.dumps(
                        captured_body.get("tools", []),
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                dispatched_cache_key = captured_body.get(
                    "prompt_cache_key"
                )
            except (KeyError, TypeError, ValueError, UnicodeDecodeError):
                pass
        control = Gate12ControlStore(reservation.root)
        try:
            receipt = control.update_turn(
                reservation.provider_operation_id,
                state=state,
                values={
                    "terminal_response_sha256": parsed["response_sha256"],
                    "visible_response_sha256": parsed["visible_sha256"],
                    "expected_solen_visible_projection_sha256": (
                        visible_projection_sha256
                    ),
                    "continuity_state": (
                        normalized_intent.get("coverage_decision")
                        if bundle_id is not None
                        else parsed["continuity_state"]
                    ),
                    "capability_effect": parsed["capability_effect"],
                    "outbox_bundle_id": bundle_id,
                    "private_range_count": len(
                        parsed["stripped_private_ranges"]
                    ),
                    "semantic_operation_count": len(operations),
                    "authorship_kind": (
                        "solen_explicit"
                        if bundle_id is not None
                        or parsed["capability_effect"]
                        == "explicit_no_delta_consumed"
                        else "authorship_not_supplied"
                    ),
                    "provider_dispatch_count": int(
                        dispatch_facts.get("provider_dispatch_count")
                        or adapter_response.get("provider_leg_count")
                        or 0
                    ),
                    "provider_retry_count": int(
                        dispatch_facts.get("provider_retry_count") or 0
                    ),
                    "provider_fallback_count": int(
                        dispatch_facts.get("provider_fallback_count") or 0
                    ),
                    "tool_call_count": int(
                        adapter_response.get("tool_call_count") or 0
                    ),
                    "endpoint_request_before_shadow_sha256": (
                        captured_shas[0] if captured_shas else None
                    ),
                    "endpoint_request_after_shadow_sha256": (
                        captured_shas[0] if captured_shas else None
                    ),
                    "exact_dispatched_request_sha256": dispatched_sha or None,
                    "provider_request_bytes_invariant": (
                        request_bytes_invariant
                    ),
                    "effective_generation": generation2.GENERATION_2,
                    "generation2_prefix_sha256": (
                        reservation.generation_identity or {}
                    ).get("canonical_semantic_stable_surface_sha256"),
                    "generation2_prefix_version": (
                        reservation.generation_identity or {}
                    ).get("prefix_version"),
                    "generation2_cache_key": (
                        reservation.generation_identity or {}
                    ).get("cache_key"),
                    "exact_stable_messages_sha256": (
                        exact_stable_messages_sha256
                    ),
                    "exact_tool_block_sha256": exact_tool_block_sha256,
                    "dispatched_cache_key": dispatched_cache_key,
                    "semantic_application_enabled": False,
                    "safe_for_source_eviction": False,
                },
            )
        finally:
            control.close()
        return {
            "completion_state": state,
            "visible_text": visible.decode("utf-8"),
            "memory_candidate_text": (
                parsed["memory_candidate_bytes"].decode("utf-8")
                if isinstance(parsed.get("memory_candidate_bytes"), bytes)
                else None
            ),
            "receipt": receipt,
        }
    finally:
        replay.close()
        outbox.close()
        registry.close()
        _secure_children(reservation.root)


def _sync_unit(
    payload: Mapping[str, Any], client_turn_id: str
) -> tuple[bytes, dict[str, Any]]:
    try:
        return build_visible_exchange_from_android_sync(
            payload, client_turn_id=client_turn_id
        )
    except Exception as exc:
        code = getattr(exc, "code", "gate12_sync_unit_invalid")
        _fail(str(code))


def bind_android_session_sync(
    payload: Any, *, env: Mapping[str, str]
) -> dict[str, Any] | None:
    if not _configured(env) or not isinstance(payload, Mapping):
        return None
    root = root_from_env(env)
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return None
    astel_ids = [
        str(value.get("message_id") or "")
        for value in messages
        if isinstance(value, Mapping) and value.get("from_astel") is True
    ]
    control = Gate12ControlStore(root)
    awaiting = None
    try:
        for client_turn_id in reversed(astel_ids):
            awaiting = control.awaiting_for_client_turn(client_turn_id)
            if awaiting is not None:
                break
        if awaiting is None:
            return None
        operation_id, receipt = awaiting
        _, facade = _sync_unit(payload, client_turn_id)
        solen = facade["messages"][1:]
        actual_visible_projection_sha256 = contracts.canonical_sha256(
            [value["text"] for value in solen]
        )
        if (
            actual_visible_projection_sha256
            != receipt.get(
                "expected_solen_visible_projection_sha256"
            )
        ):
            _fail("gate12_sync_visible_projection_mismatch")
        body = {
            "expectation_state": "finalized",
            "client_turn_id": client_turn_id,
            "room_id": receipt["room_id"],
            "permitted_unit_kinds": ["visible_exchange"],
            "expected_source_start_id": facade["source_start_id"],
            "expected_source_end_id": facade["source_end_id"],
            "expected_astel_message_id": facade["messages"][0]["message_id"],
            "expected_solen_message_ids": [
                value["message_id"] for value in solen
            ],
            "expected_solen_visible_sha256": receipt[
                "expected_solen_visible_projection_sha256"
            ],
            "expected_provider_operation_id": None,
            "raw_body_included": False,
        }
        expectation = {
            **body,
            "expectation_sha256": contracts.canonical_sha256(body),
        }
        outbox = HouseContinuityDurablePreparationOutboxLocal(
            root, protected_shadow_only=True
        )
        try:
            outbox.finalize_complete_unit_expectation(
                operation_id,
                complete_unit_expectation=expectation,
            )
            outbox.publish_complete_unit(operation_id, facade)
            bound = outbox.bind_complete_unit(
                receipt["outbox_bundle_id"], now=_now()
            )
        finally:
            outbox.close()
        return control.update_turn(
            operation_id,
            state="ready_to_apply_shadow_only",
            values={
                "unit_binding_state": "bound",
                "complete_unit_id": facade["unit_id"],
                "complete_unit_sha256": facade["source_payload_sha256"],
                "outbox_state": bound["state"],
                "semantic_application_enabled": False,
                "safe_for_source_eviction": False,
            },
        )
    finally:
        control.close()
        _secure_children(root)


def doctor(env: Mapping[str, str]) -> dict[str, Any]:
    deployed_commit = _deployed_commit(env)
    root = root_from_env(env)
    control = Gate12ControlStore(root)
    try:
        control.register_boot(
            deployed_commit=deployed_commit,
            at=_now(),
        )
        result = {
            "schema_version": "house_continuity_v1_2_gate12_doctor_v1",
            "control": control.doctor(),
            "readiness": _readiness(root),
            "switch": str(env.get(SWITCH_ENV) or OFF),
            "service_boot_id": SERVICE_BOOT_ID,
            "deployed_commit": deployed_commit,
            "semantic_application_enabled": False,
            "safe_for_source_eviction": False,
            "raw_body_included": False,
        }
        return result
    finally:
        control.close()
        _secure_children(root)


def arm(env: Mapping[str, str]) -> dict[str, Any]:
    deployed_commit = _deployed_commit(env)
    root = root_from_env(env)
    control = Gate12ControlStore(root)
    try:
        control.register_boot(
            deployed_commit=deployed_commit,
            at=_now(),
        )
        if control.doctor()["state"] != "healthy":
            _fail("gate12_control_store_unhealthy")
        return control.arm(at=_now())
    finally:
        control.close()
        _secure_children(root)


__all__ = [
    "DEPLOYED_COMMIT_ENV",
    "GATE_ID",
    "Gate12ProtectedShadowError",
    "Gate12Reservation",
    "OFF",
    "PROTECTED_SHADOW",
    "ROOT_ENV",
    "SERVICE_BOOT_ID",
    "SWITCH_ENV",
    "abort_reservation",
    "arm",
    "bind_android_session_sync",
    "doctor",
    "emergency_strip",
    "generation2_selection",
    "process_provider_response",
    "prepare_turn",
    "prepare_generation2_operation",
    "commit_prepared_turn",
    "reserve_turn",
]
