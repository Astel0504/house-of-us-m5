"""Explicit default-off orchestration for the Milestone-5 production candidate."""

from __future__ import annotations

from contextlib import ExitStack, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from house_complete_continuity_unit_v1_facade import (
    build_visible_exchange_from_android_sync,
)
from house_continuity_v1_2_durable_preparation_outbox_local import (
    HouseContinuityDurablePreparationOutboxLocal,
)
from house_continuity_v1_2_executable_contracts_v0 import canonical_sha256
from house_continuity_v1_2_local_store_v1 import HouseContinuityV12LocalStore
import house_continuity_v1_2_milestone3_context_local as milestone3
from house_continuity_v1_2_milestone5_m2_application_bridge import (
    Milestone5M2ApplicationBridge,
)
from house_continuity_v1_2_milestone5_m3_producer_bridge import (
    Milestone5M3ProducerBridge,
)
from house_continuity_v1_2_milestone5_m4_producer_bridge import (
    Milestone5M4ProducerBridge,
)
import house_standing_root_v2_production_v1 as production


SCHEMA_VERSION = "house_continuity_v1_2_milestone5_candidate_v1"
SWITCH_ENV = "HOUSE_CONTINUITY_V1_2_MILESTONE5_CANDIDATE"
OFF = "off"
CANDIDATE = "candidate"
EVIDENCE_SUCCESSOR_SCHEMA_VERSION = (
    "house_continuity_v1_2_milestone5_evidence_domain_successor_v1"
)


class Milestone5CandidateError(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _fail(code: str) -> None:
    raise Milestone5CandidateError(code)


def mode(env: Mapping[str, str] | None) -> str:
    value = str((env or {}).get(SWITCH_ENV) or OFF).strip().casefold()
    if value not in {OFF, CANDIDATE}:
        _fail("m5_candidate_switch_invalid")
    return value


def enabled(env: Mapping[str, str] | None) -> bool:
    return mode(env) == CANDIDATE


def evidence_domain_successor_receipt(
    *,
    visible_text_sha256: str,
    synchronized_message_list_sha256: str,
    semantic_cache_key: str,
    provider_policy_cache_key: str,
) -> dict[str, Any]:
    hashes = (visible_text_sha256, synchronized_message_list_sha256)
    if any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in hashes
    ):
        _fail("m5_evidence_sha256_invalid")
    if not isinstance(semantic_cache_key, str) or len(semantic_cache_key) != 48:
        _fail("m5_semantic_cache_key_invalid")
    if (
        not isinstance(provider_policy_cache_key, str)
        or len(provider_policy_cache_key) != 40
    ):
        _fail("m5_provider_policy_cache_key_invalid")
    body = {
        "schema_version": EVIDENCE_SUCCESSOR_SCHEMA_VERSION,
        "visible_projection_binding": {
            "visible_identity": {
                "domain": "visible_response_text_utf8_sha256_v1",
                "sha256": visible_text_sha256,
            },
            "synchronized_identity": {
                "domain": (
                    "android_synchronized_message_list_sorted_json_sha256_v1"
                ),
                "sha256": synchronized_message_list_sha256,
            },
            "comparison_state": "different_domains_not_comparable",
            "equal": None,
            "binding_evidence_owner": (
                "house_complete_continuity_unit_v1_facade"
            ),
            "historical_visible_projection_preserved_reused": False,
        },
        "cache_key_dispatch_binding": {
            "semantic_identity": {
                "domain": "generation2_semantic_cache_key_48char_v1",
                "length": len(semantic_cache_key),
                "sha256": canonical_sha256(semantic_cache_key),
            },
            "provider_policy_identity": {
                "domain": "provider_prompt_cache_policy_key_40char_v1",
                "length": len(provider_policy_cache_key),
                "sha256": canonical_sha256(provider_policy_cache_key),
            },
            "comparison_state": "different_domains_not_comparable",
            "equal": None,
            "behavioral_effect": "cache_cost_only",
            "historical_cache_key_dispatch_equal_reused": False,
        },
    }
    return {**body, "receipt_sha256": canonical_sha256(body)}


def _candidate_root(gate12_root: str | Path) -> Path:
    return Path(gate12_root).resolve() / "milestone5_candidate"


def _working_store(gate12_root: Path) -> HouseContinuityV12LocalStore:
    root = gate12_root / "working_set"
    root.mkdir(parents=True, exist_ok=True)
    return HouseContinuityV12LocalStore(
        root,
        synthetic_only=False,
        production_candidate=True,
    )


def prepare_operation_artifact(
    *,
    env: Mapping[str, str],
    gate12_root: str | Path,
    operation_id: str,
    room_id: str,
    client_turn_id: str,
    provider_operation_id: str,
    generation1_selection: production.ProductionPromptSelection,
    now: str,
    budget_chars: int,
    intent_query: str | None,
    preserved_dynamic_context: tuple[str, ...] = (),
    final_dynamic_context_suffix: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    if not enabled(env):
        return None
    root = Path(gate12_root).resolve()
    candidate_root = _candidate_root(root)
    with ExitStack() as stack:
        working = stack.enter_context(_working_store(root))
        context = stack.enter_context(
            closing(
                milestone3.Milestone3ContextStore(
                    candidate_root / "m3" / "context"
                )
            )
        )
        bridge = stack.enter_context(
            closing(Milestone5M4ProducerBridge(candidate_root / "m4"))
        )
        artifact = bridge.build_operation_artifact(
            operation_id=operation_id,
            room_id=room_id,
            client_turn_id=client_turn_id,
            provider_operation_id=provider_operation_id,
            generation1_selection=generation1_selection,
            working_set_store=working,
            context_store=context,
            now=now,
            budget_chars=budget_chars,
            intent_query=intent_query,
            preserved_dynamic_context=preserved_dynamic_context,
            final_dynamic_context_suffix=final_dynamic_context_suffix,
        )
        return {
            "artifact": artifact,
            "required_m2_section": artifact["required_m2_section"],
            "m3_sections": artifact["m3_sections"],
            "sections": artifact["sections"],
        }


def bind_operation_phase(
    *,
    env: Mapping[str, str],
    gate12_root: str | Path,
    operation_id: str,
    phase: str,
    artifact_sha256: str,
    phase_input_sha256: str,
) -> dict[str, Any] | None:
    if not enabled(env):
        return None
    bridge = Milestone5M4ProducerBridge(
        _candidate_root(gate12_root) / "m4"
    )
    try:
        return bridge.bind_phase(
            operation_id=operation_id,
            phase=phase,
            artifact_sha256=artifact_sha256,
            phase_input_sha256=phase_input_sha256,
        )
    finally:
        bridge.close()


def persisted_operation_artifact(
    *,
    gate12_root: str | Path,
    operation_id: str,
) -> dict[str, Any] | None:
    root = _candidate_root(gate12_root) / "m4"
    if not (root / "milestone5_m4_operations.sqlite3").is_file():
        return None
    bridge = Milestone5M4ProducerBridge(root)
    try:
        return bridge.artifact(operation_id)
    finally:
        bridge.close()


def apply_bound_sync(
    *,
    env: Mapping[str, str],
    gate12_root: str | Path,
    payload: Mapping[str, Any],
    client_turn_id: str,
    provider_operation_id: str,
    room_id: str,
    bundle_id: str,
    now: str,
) -> dict[str, Any] | None:
    if not enabled(env):
        return None
    root = Path(gate12_root).resolve()
    candidate_root = _candidate_root(root)
    _, facade = build_visible_exchange_from_android_sync(
        payload,
        client_turn_id=client_turn_id,
    )
    parsed_now = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if parsed_now.tzinfo is None:
        _fail("m5_candidate_now_invalid")
    lease_expires_at = (
        parsed_now.astimezone(timezone.utc) + timedelta(minutes=5)
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    with ExitStack() as stack:
        working = stack.enter_context(_working_store(root))
        outbox = stack.enter_context(
            closing(
                HouseContinuityDurablePreparationOutboxLocal(
                    root,
                    protected_shadow_only=True,
                )
            )
        )
        m2_bridge = stack.enter_context(
            closing(Milestone5M2ApplicationBridge(candidate_root / "m2"))
        )
        m3_bridge = stack.enter_context(
            closing(Milestone5M3ProducerBridge(candidate_root / "m3"))
        )
        m2_receipt = m2_bridge.apply_bound_bundle(
            operation_id=provider_operation_id,
            bundle_id=bundle_id,
            room_id=room_id,
            complete_unit_id=facade["unit_id"],
            complete_unit_sha256=facade["source_payload_sha256"],
            outbox=outbox,
            working_set_store=working,
            now=now,
            lease_expires_at=lease_expires_at,
        )
        if m2_receipt["application_state"] == "rejected_fail_closed":
            _fail("m5_candidate_m2_application_rejected")
        m3_receipt = m3_bridge.ingest_complete_unit(
            operation_id=provider_operation_id,
            room_id=room_id,
            complete_unit=facade,
            working_set_store=working,
            now=now,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "state": "applied",
            "provider_operation_id": provider_operation_id,
            "room_id": room_id,
            "complete_unit_id": facade["unit_id"],
            "complete_unit_sha256": facade["source_payload_sha256"],
            "m2_application_receipt_sha256": m2_receipt["receipt_sha256"],
            "m2_projection_sha256": m2_receipt["m2_projection_sha256"],
            "m3_ingestion_receipt_sha256": m3_receipt["receipt_sha256"],
            "m3_projection_sha256": m3_receipt["successor_projection_sha256"],
            "provider_calls_made": False,
            "memory_writes": 0,
            "vault_writes": 0,
            "source_writes": 0,
            "self_state_writes": 0,
            "source_eviction_enabled": False,
            "raw_material_present": False,
        }


def record_non_authoritative_operation(
    *,
    env: Mapping[str, str],
    gate12_root: str | Path,
    source_operation_id: str,
    reason_code: str,
    recorded_at: str,
) -> dict[str, Any] | None:
    """Finalize a persisted semantic operation as non-authoritative.

    M5 postcondition owners can call this after a completed operation is
    judged failed or rejected.  It operates only on the copy-backed M5
    Working-Set store, delegates to the canonical append-only lineage writer,
    and is idempotent on replay.  Operations that failed before a semantic
    revision was persisted produce a raw-free, write-free no-op result.
    """

    if not enabled(env):
        return None
    root = Path(gate12_root).resolve()
    with closing(_working_store(root)) as working:
        records = working.record_non_authoritative_operation(
            source_operation_id=source_operation_id,
            reason_code=reason_code,
            recorded_at=recorded_at,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "state": (
                "recorded"
                if records
                else "no_persisted_semantic_revision"
            ),
            "source_operation_id": source_operation_id,
            "lineage_count": len(records),
            "lineage_ids": [record["lineage_id"] for record in records],
            "working_set_store_id": working.store_id,
            "provider_calls_made": False,
            "memory_writes": 0,
            "vault_writes": 0,
            "source_writes": 0,
            "self_state_writes": 0,
            "source_eviction_enabled": False,
            "raw_material_present": False,
        }


def doctor(env: Mapping[str, str], *, gate12_root: str | Path) -> dict[str, Any]:
    current_mode = mode(env)
    root = _candidate_root(gate12_root)
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": current_mode,
        "default_off": current_mode == OFF,
        "candidate_root_exists": root.exists(),
        "daily_default_enabled": False,
        "generation1_rollback_immediate": True,
        "provider_calls_made": False,
        "source_eviction_enabled": False,
    }


__all__ = [
    "CANDIDATE",
    "Milestone5CandidateError",
    "OFF",
    "SCHEMA_VERSION",
    "SWITCH_ENV",
    "apply_bound_sync",
    "bind_operation_phase",
    "doctor",
    "enabled",
    "mode",
    "prepare_operation_artifact",
    "record_non_authoritative_operation",
]
