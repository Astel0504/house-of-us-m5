"""Milestone-2 authoritative Working-Set boundary, default-off and copy-only.

This owner composes the accepted Gate-5 outbox and Gate-1 event store.  It
does not create a second semantic store, make provider calls, write Memory,
touch Android state, or authorize source eviction.  The only enabled mode is
an explicitly configured copy-backed rehearsal; production application stays
outside this module's authority.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from house_continuity_v1_2_durable_preparation_outbox_local import (
    Gate1AtomicOutboxApplicationAdapter,
    HouseContinuityDurablePreparationOutboxLocal,
)
from house_continuity_v1_2_executable_contracts_v0 import canonical_sha256
from house_continuity_v1_2_local_store_v1 import (
    HouseContinuityV12LocalStore,
)
from house_continuity_v1_2_executable_contracts_v0 import (
    validate_scope_binding,
)


SCHEMA_VERSION = "house_continuity_milestone2_authority_local_v1"
PROJECTION_SCHEMA_VERSION = "house_continuity_milestone2_projection_v1"
REVIEW_SCHEMA_VERSION = "house_continuity_milestone2_review_receipt_v1"
APPLICATION_SCHEMA_VERSION = (
    "house_continuity_milestone2_application_receipt_v1"
)
ROLLBACK_SCHEMA_VERSION = "house_continuity_milestone2_rollback_receipt_v1"

SWITCH_ENV = "HOUSE_CONTINUITY_V1_2_MILESTONE2_AUTHORITY"
ROOT_ENV = "HOUSE_CONTINUITY_V1_2_MILESTONE2_ROOT"
WRITER_ENV = "HOUSE_CONTINUITY_V1_2_MILESTONE2_WORKING_SET_WRITER"
SELECTOR_ENV = "HOUSE_CONTINUITY_V1_2_MILESTONE2_WORKING_SET_SELECTOR"

OFF = "off"
COPY_REHEARSAL = "copy_rehearsal"
ON = "on"

_TERMINAL_LIFECYCLES = frozenset(
    {"resolved", "superseded", "abandoned", "expired"}
)
_SCOPE_ORDER = {"global": 0, "project": 1, "room": 2}
_ITEM_LABELS = {
    "active_topic": "Active topic",
    "active_task": "Active task",
    "question": "Open question",
    "commitment": "Solen intention or commitment",
    "decision": "Decision",
    "temporary_fact": "Temporary fact",
    "emotional_thread": "Unresolved relational or emotional thread",
    "pending_review": "Unresolved review",
    "completed_tool_result_ref": "Completed tool-result reference",
}


# Executable documentation for the M2 state machine.  Tests require every
# transition to retain the same complete field set.
STATE_MACHINE = (
    {
        "state": "prepared_but_unbound",
        "legal_predecessor": "none_or_prepared",
        "required_authority": "consumed_exact_turn_capability",
        "required_scope_binding": "outbox_room_and_operation_binding",
        "expected_revision": "captured_but_not_applied",
        "atomic_writes": "capability_plus_outbox_preparation_receipt",
        "durable_receipt": "preparation_receipt",
        "replay_result": "same_bundle_and_receipt",
        "rollback_behavior": "writer_off_leaves_bundle_inert",
        "projected_consequence": "none",
        "prohibited_side_effects": "working_set_projection_memory_source_eviction",
    },
    {
        "state": "bound_and_eligible",
        "legal_predecessor": "prepared_but_unbound",
        "required_authority": "reviewed_complete_unit_binding",
        "required_scope_binding": "exact_turn_room_operation_and_unit_hash",
        "expected_revision": "durable_operation_expectations",
        "atomic_writes": "complete_unit_binding_only",
        "durable_receipt": "bound_outbox_revision",
        "replay_result": "same_ready_bundle",
        "rollback_behavior": "writer_off_prevents_lease",
        "projected_consequence": "none_until_apply",
        "prohibited_side_effects": "early_selection_partial_unit_application",
    },
    {
        "state": "rejected_fail_closed",
        "legal_predecessor": "any_nonterminal",
        "required_authority": "deterministic_validator_or_cas",
        "required_scope_binding": "mismatch_is_never_repaired_by_inference",
        "expected_revision": "must_match_or_conflict",
        "atomic_writes": "conflict_receipt_without_semantic_commit",
        "durable_receipt": "conflict_or_rejection_receipt",
        "replay_result": "same_rejection",
        "rollback_behavior": "prior_projection_remains_selected",
        "projected_consequence": "none",
        "prohibited_side_effects": "last_writer_wins_synthetic_no_delta",
    },
    {
        "state": "applied",
        "legal_predecessor": "bound_and_eligible_or_applying",
        "required_authority": "fresh_m2_review_receipt",
        "required_scope_binding": "review_bound_outbox_store_unit_and_scope",
        "expected_revision": "all_operation_and_binding_cas_values",
        "atomic_writes": "one_gate1_bundle_transaction_then_outbox_receipts",
        "durable_receipt": "atomic_working_set_and_applied_receipts",
        "replay_result": "idempotent_replay",
        "rollback_behavior": "selector_off_restores_prior_render_only",
        "projected_consequence": "applied_items_become_eligible",
        "prohibited_side_effects": "memory_vault_self_state_android_source_eviction",
    },
    {
        "state": "idempotent_replay",
        "legal_predecessor": "applied",
        "required_authority": "same_review_and_bundle_identity",
        "required_scope_binding": "unchanged",
        "expected_revision": "same_application_input_digest",
        "atomic_writes": "none",
        "durable_receipt": "original_applied_receipt",
        "replay_result": "same_authoritative_result",
        "rollback_behavior": "same_as_applied",
        "projected_consequence": "unchanged",
        "prohibited_side_effects": "duplicate_event_receipt_or_coverage",
    },
    {
        "state": "superseded",
        "legal_predecessor": "active_or_other_allowed_lifecycle",
        "required_authority": "participant_operation_with_valid_successor",
        "required_scope_binding": "same_compatible_scope",
        "expected_revision": "latest_item_revision",
        "atomic_writes": "successor_and_supersession_events_in_bundle",
        "durable_receipt": "item_event_and_bundle_receipt",
        "replay_result": "terminal_history_only",
        "rollback_behavior": "old_render_only_via_selector_rollback",
        "projected_consequence": "successor_selected_predecessor_suppressed",
        "prohibited_side_effects": "history_deletion_or_stale_reopen",
    },
    {
        "state": "closed",
        "legal_predecessor": "active",
        "required_authority": "participant_resolve_or_abandon_operation",
        "required_scope_binding": "unchanged_item_scope",
        "expected_revision": "latest_item_revision",
        "atomic_writes": "terminal_item_event",
        "durable_receipt": "item_event_and_bundle_receipt",
        "replay_result": "terminal_history_only",
        "rollback_behavior": "old_render_only_via_selector_rollback",
        "projected_consequence": "closed_item_not_selected",
        "prohibited_side_effects": "silent_erasure_or_stale_active_override",
    },
    {
        "state": "rolled_back",
        "legal_predecessor": "selector_on",
        "required_authority": "independent_selector_switch",
        "required_scope_binding": "legacy_projection_identity_supplied",
        "expected_revision": "not_applicable_read_path_only",
        "atomic_writes": "none",
        "durable_receipt": "raw_free_rollback_receipt",
        "replay_result": "byte_identical_prior_projection",
        "rollback_behavior": "working_set_records_remain_append_only",
        "projected_consequence": "prior_projection_exactly_restored",
        "prohibited_side_effects": "record_rewrite_dual_render_hidden_fallback",
    },
    {
        "state": "authoritative_empty",
        "legal_predecessor": "successful_atomic_read",
        "required_authority": "canonical_working_set_reader",
        "required_scope_binding": "exact_room_and_optional_explicit_binding",
        "expected_revision": "snapshot_head_and_binding_revision",
        "atomic_writes": "none",
        "durable_receipt": "projection_identity",
        "replay_result": "same_snapshot_same_empty",
        "rollback_behavior": "prior_projection_when_selector_off",
        "projected_consequence": "honest_empty_without_fallback",
        "prohibited_side_effects": "memory_or_global_newest_substitution",
    },
)


class Milestone2AuthorityError(ValueError):
    def __init__(self, error_code: str):
        super().__init__(error_code)
        self.error_code = error_code


def _fail(error_code: str) -> None:
    raise Milestone2AuthorityError(error_code)


def _mode(env: Mapping[str, str]) -> str:
    value = str(env.get(SWITCH_ENV) or OFF).strip()
    if value not in {OFF, COPY_REHEARSAL}:
        _fail("m2_mode_invalid")
    return value


def _toggle(env: Mapping[str, str], name: str) -> str:
    value = str(env.get(name) or OFF).strip()
    if value not in {OFF, ON}:
        _fail("m2_toggle_invalid")
    return value


def _root(env: Mapping[str, str], *, require_existing: bool) -> Path | None:
    raw = str(env.get(ROOT_ENV) or "").strip()
    if not raw:
        if require_existing:
            _fail("m2_root_unconfigured")
        return None
    root = Path(raw).resolve()
    if require_existing and (not root.exists() or not root.is_dir()):
        _fail("m2_root_unavailable")
    return root


def _timestamp(value: Any, *, error_code: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        _fail(error_code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail(error_code)
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        _fail(error_code)
    return value


def control_state(env: Mapping[str, str]) -> dict[str, Any]:
    mode = _mode(env)
    writer = _toggle(env, WRITER_ENV)
    selector = _toggle(env, SELECTOR_ENV)
    if mode == OFF and (writer != OFF or selector != OFF):
        _fail("m2_off_with_enabled_child")
    if mode == COPY_REHEARSAL:
        _root(env, require_existing=True)
    return {
        "mode": mode,
        "writer": writer,
        "selector": selector,
        "copy_rehearsal_only": True,
        "production_application_authorized": False,
        "source_eviction_enabled": False,
    }


def _validate_copy_owners(
    env: Mapping[str, str],
    outbox: HouseContinuityDurablePreparationOutboxLocal,
    store: HouseContinuityV12LocalStore,
) -> None:
    state = control_state(env)
    if state["mode"] != COPY_REHEARSAL:
        _fail("m2_copy_rehearsal_required")
    root = _root(env, require_existing=True)
    expected_working_root = (root / "working_set").resolve()
    if outbox.root != root or store.root != expected_working_root:
        _fail("m2_copy_owner_root_mismatch")


def _review_body(
    env: Mapping[str, str],
    outbox: HouseContinuityDurablePreparationOutboxLocal,
    store: HouseContinuityV12LocalStore,
    bundle_id: str,
    *,
    review_id: str,
    reviewed_at: str,
    require_eligible: bool,
) -> dict[str, Any]:
    _validate_copy_owners(env, outbox, store)
    bundle = outbox.read_bundle(bundle_id)
    if bundle is None:
        _fail("m2_bundle_missing")
    allowed_states = {
        "ready_to_apply",
        "applying",
        "applied",
        "conflict_recorded",
    }
    if (
        require_eligible
        and bundle["state"] != "ready_to_apply"
        or not require_eligible
        and bundle["state"] not in allowed_states
    ):
        _fail("m2_bundle_not_bound_and_eligible")
    operation = outbox._operation(bundle["provider_operation_id"])
    unit = operation.get("complete_unit_binding")
    if not isinstance(unit, Mapping):
        _fail("m2_complete_unit_binding_missing")
    if not isinstance(review_id, str) or not review_id.startswith("m2review_"):
        _fail("m2_review_id_invalid")
    reviewed_at = _timestamp(reviewed_at, error_code="m2_reviewed_at_invalid")
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "review_id": review_id,
        "disposition": "approved_for_copy_rehearsal",
        "bundle_id": bundle_id,
        "command_bundle_sha256": bundle["command_bundle_sha256"],
        "outbox_store_id": outbox.doctor()["store_id"],
        "working_set_store_id": store.store_id,
        "room_id": bundle["room_id"],
        "provider_operation_id": bundle["provider_operation_id"],
        "complete_unit_id": unit["unit_id"],
        "complete_unit_sha256": unit["source_payload_sha256"],
        "reviewed_at": reviewed_at,
        "raw_body_included": False,
    }


def build_review_receipt(
    env: Mapping[str, str],
    outbox: HouseContinuityDurablePreparationOutboxLocal,
    store: HouseContinuityV12LocalStore,
    bundle_id: str,
    *,
    review_id: str,
    reviewed_at: str,
) -> dict[str, Any]:
    body = _review_body(
        env,
        outbox,
        store,
        bundle_id,
        review_id=review_id,
        reviewed_at=reviewed_at,
        require_eligible=True,
    )
    return {**body, "receipt_sha256": canonical_sha256(body)}


def _validate_review_receipt(
    value: Mapping[str, Any],
    env: Mapping[str, str],
    outbox: HouseContinuityDurablePreparationOutboxLocal,
    store: HouseContinuityV12LocalStore,
    bundle_id: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "review_id",
        "disposition",
        "bundle_id",
        "command_bundle_sha256",
        "outbox_store_id",
        "working_set_store_id",
        "room_id",
        "provider_operation_id",
        "complete_unit_id",
        "complete_unit_sha256",
        "reviewed_at",
        "raw_body_included",
        "receipt_sha256",
    }:
        _fail("m2_review_receipt_invalid")
    normalized = deepcopy(dict(value))
    receipt_sha = normalized.pop("receipt_sha256")
    expected = _review_body(
        env,
        outbox,
        store,
        bundle_id,
        review_id=normalized.get("review_id"),
        reviewed_at=normalized.get("reviewed_at"),
        require_eligible=False,
    )
    if normalized != expected or receipt_sha != canonical_sha256(expected):
        _fail("m2_review_binding_mismatch")
    return dict(value)


def apply_reviewed_bundle(
    env: Mapping[str, str],
    outbox: HouseContinuityDurablePreparationOutboxLocal,
    store: HouseContinuityV12LocalStore,
    bundle_id: str,
    review_receipt: Mapping[str, Any],
    *,
    clear_lease_token: str,
    now: str,
    lease_expires_at: str,
) -> dict[str, Any]:
    state = control_state(env)
    if state["mode"] != COPY_REHEARSAL or state["writer"] != ON:
        _fail("m2_writer_disabled")
    review = _validate_review_receipt(
        review_receipt, env, outbox, store, bundle_id
    )
    bundle = outbox.read_bundle(bundle_id)
    if bundle is None:
        _fail("m2_bundle_missing")
    prior_state = bundle["state"]
    if prior_state in {"prepared_waiting_visible", "visible_released_waiting_unit"}:
        _fail("m2_bundle_not_bound_and_eligible")
    if prior_state == "cancelled_before_visible":
        _fail("m2_bundle_rejected")
    if prior_state == "conflict_recorded":
        outcome = outbox.outcome(bundle_id)
        application_state = "rejected_fail_closed"
    elif prior_state == "applied":
        outcome = outbox.outcome(bundle_id)
        application_state = "idempotent_replay"
    else:
        if prior_state == "ready_to_apply":
            outbox.acquire_lease(
                bundle_id,
                clear_lease_token=clear_lease_token,
                now=now,
                expires_at=lease_expires_at,
            )
        elif prior_state != "applying":
            _fail("m2_bundle_not_bound_and_eligible")
        outcome = outbox.apply(
            bundle_id,
            Gate1AtomicOutboxApplicationAdapter(store),
            clear_lease_token=clear_lease_token,
            now=now,
        )
        application_state = (
            "rejected_fail_closed"
            if outcome.get("state") == "conflict_recorded"
            else "applied"
        )
    final_bundle = outbox.read_bundle(bundle_id)
    body = {
        "schema_version": APPLICATION_SCHEMA_VERSION,
        "application_state": application_state,
        "review_id": review["review_id"],
        "review_receipt_sha256": review["receipt_sha256"],
        "outbox_store_id": review["outbox_store_id"],
        "bundle_id": bundle_id,
        "command_bundle_sha256": final_bundle["command_bundle_sha256"],
        "room_id": final_bundle["room_id"],
        "provider_operation_id": final_bundle["provider_operation_id"],
        "complete_unit_id": review["complete_unit_id"],
        "complete_unit_sha256": review["complete_unit_sha256"],
        "outbox_state": final_bundle["state"],
        "working_set_receipt_ids": list(
            final_bundle["working_set_receipt_ids"]
        ),
        "coverage_receipt_ids": list(
            final_bundle["coverage_receipt_ids"]
        ),
        "outcome_receipt_sha256": outcome.get("receipt_sha256"),
        "working_set_store_id": store.store_id,
        "authorship_kind": "solen_explicit",
        "normalized_operation_count": len(
            final_bundle["normalized_semantic_operations"]
        ),
        "source_eviction_enabled": False,
        "provider_calls_made": False,
        "raw_body_included": False,
    }
    return {**body, "receipt_sha256": canonical_sha256(body)}


def _coverage_state(
    unit_coverage: list[Mapping[str, Any]], room_id: str
) -> tuple[str, str | None]:
    candidates = [
        value for value in unit_coverage if value.get("room_id") == room_id
    ]
    if not candidates:
        return "no_authored_result", None
    latest = max(
        candidates,
        key=lambda item: (item["created_at"], item["coverage_id"]),
    )
    state = (
        "explicit_no_delta"
        if latest["coverage_state"] == "solen_no_semantic_delta"
        else "authored_operations"
    )
    return state, latest["coverage_id"]


def _scope_matches(
    item: Mapping[str, Any],
    *,
    room_id: str,
    binding: Mapping[str, Any] | None,
) -> bool:
    if item["scope_kind"] == "global":
        return True
    if item["scope_kind"] == "room":
        return item["room_id"] == room_id
    return (
        binding is not None
        and item["project_id"] == binding["project_id"]
        and (
            item["thread_id"] is None
            or item["thread_id"] == binding["thread_id"]
        )
    )


def _terminal_history(
    terminal_items: list[Mapping[str, Any]],
    *,
    room_id: str,
    binding: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    history = []
    for item in terminal_items:
        if (
            item["lifecycle_state"] in _TERMINAL_LIFECYCLES
            and _scope_matches(item, room_id=room_id, binding=binding)
        ):
            history.append(
                {
                    "item_id": item["item_id"],
                    "lifecycle_state": item["lifecycle_state"],
                    "revision": item["revision"],
                    "base_event_id": item["base_event_id"],
                    "source_operation_ids": list(
                        item["source_operation_ids"]
                    ),
                    "superseded_by_item_id": item[
                        "superseded_by_item_id"
                    ],
                    "resolution_reason_code": item[
                        "resolution_reason_code"
                    ],
                }
            )
    return history


def _suppress_stale_local_decisions(
    selected: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    newest_global: dict[str, Mapping[str, Any]] = {}
    for entry in selected:
        item = entry["item"]
        if item["item_kind"] == "decision" and item["scope_kind"] == "global":
            key = item["kind_payload"]["decision_scope"]
            prior = newest_global.get(key)
            if prior is None or item["updated_at"] > prior["updated_at"]:
                newest_global[key] = item
    kept = []
    suppressed = []
    for entry in selected:
        item = entry["item"]
        key = (
            item["kind_payload"].get("decision_scope")
            if item["item_kind"] == "decision"
            else None
        )
        winner = newest_global.get(key) if key is not None else None
        if (
            winner is not None
            and item["scope_kind"] != "global"
            and item["updated_at"] < winner["updated_at"]
        ):
            suppressed.append(
                {
                    "item_id": item["item_id"],
                    "reason_code": "newer_global_decision_same_exact_scope",
                    "winning_item_id": winner["item_id"],
                }
            )
        else:
            kept.append(entry)
    kept.sort(
        key=lambda entry: (
            _SCOPE_ORDER[entry["item"]["scope_kind"]],
            entry["item"]["item_kind"],
            entry["item"]["item_id"],
        )
    )
    return kept, suppressed


def read_authoritative_projection(
    store: HouseContinuityV12LocalStore,
    *,
    room_id: str,
    now: str,
    predecessor_room_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(room_id, str) or not room_id.startswith("cws_room_"):
        _fail("m2_room_id_invalid")
    if predecessor_room_id is not None and (
        not isinstance(predecessor_room_id, str)
        or not predecessor_room_id.startswith("cws_room_")
        or predecessor_room_id == room_id
    ):
        _fail("m2_predecessor_room_id_invalid")
    snapshot = store.read_bound_projection(
        now=now,
        room_id=room_id,
        allow_unbound=True,
        include_authority_metadata=True,
    )
    binding = snapshot["binding"]
    current = snapshot["projection"]
    if (
        current["selection_state"] != "ready"
        or current["expiry_due_item_ids"]
    ):
        _fail("m2_projection_expiry_due")
    metadata = snapshot["authority_metadata"]
    predecessor_entries = []
    if predecessor_room_id is not None:
        predecessor = store.read_bound_projection(
            now=now,
            room_id=predecessor_room_id,
            allow_unbound=True,
        )["projection"]
        if (
            predecessor["selection_state"] != "ready"
            or predecessor["expiry_due_item_ids"]
        ):
            _fail("m2_projection_expiry_due")
        predecessor_entries = [
            entry
            for entry in predecessor["selected"]
            if entry["item"]["scope_kind"] != "global"
        ][:4]
    authorship_state, coverage_id = _coverage_state(
        metadata["unit_coverage"], room_id
    )
    terminal_history = _terminal_history(
        metadata["terminal_items"], room_id=room_id, binding=binding
    )
    selected, suppressed = _suppress_stale_local_decisions(
        list(current["selected"])
    )
    categories = {kind: [] for kind in _ITEM_LABELS}
    exact_anchor_refs = []
    for entry in selected:
        item = entry["item"]
        categories[item["item_kind"]].append(item["item_id"])
        exact_anchor_refs.extend(item["exact_anchor_refs"])
    authoritative_empty = not selected
    body = {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "room_id": room_id,
        "binding": binding,
        "selection_state": (
            "authoritative_empty" if authoritative_empty else "selected"
        ),
        "authoritative_empty": authoritative_empty,
        "authorship_result_state": authorship_state,
        "latest_coverage_id": coverage_id,
        "selected_items": selected,
        "provisional_predecessor_room_id": predecessor_room_id,
        "provisional_predecessor_items": predecessor_entries,
        "suppressed_items": suppressed,
        "categories": categories,
        "exact_anchor_refs": sorted(set(exact_anchor_refs)),
        "terminal_history": terminal_history,
        "snapshot_global_event_sequence": current[
            "snapshot_global_event_sequence"
        ],
        "snapshot_global_event_sha256": current[
            "snapshot_global_event_sha256"
        ],
        "source_eviction_enabled": False,
        "unrelated_global_newest_used": False,
        "raw_history_included": False,
    }
    return {**body, "projection_sha256": canonical_sha256(body)}


def validate_authoritative_projection(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    expected_fields = {
        "schema_version",
        "room_id",
        "binding",
        "selection_state",
        "authoritative_empty",
        "authorship_result_state",
        "latest_coverage_id",
        "selected_items",
        "provisional_predecessor_room_id",
        "provisional_predecessor_items",
        "suppressed_items",
        "categories",
        "exact_anchor_refs",
        "terminal_history",
        "snapshot_global_event_sequence",
        "snapshot_global_event_sha256",
        "source_eviction_enabled",
        "unrelated_global_newest_used",
        "raw_history_included",
        "projection_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        _fail("m2_projection_invalid")
    normalized = deepcopy(dict(value))
    projection_sha256 = normalized.pop("projection_sha256")
    if (
        normalized.get("schema_version") != PROJECTION_SCHEMA_VERSION
        or projection_sha256 != canonical_sha256(normalized)
    ):
        _fail("m2_projection_invalid")
    if normalized["binding"] is not None:
        validate_scope_binding(normalized["binding"])
    return dict(value)


def provider_section(projection: Mapping[str, Any]) -> dict[str, str]:
    projection = validate_authoritative_projection(projection)
    lines = [
        "Current continuity (structured summaries, not exact prior wording):"
    ]
    for entry in projection["selected_items"]:
        item = entry["item"]
        scope = {
            "global": "shared global",
            "project": "selected project",
            "room": "this room",
        }[item["scope_kind"]]
        lines.append(
            f"- {_ITEM_LABELS[item['item_kind']]} [{scope}]: "
            f"{item['summary']}"
        )
    if projection["provisional_predecessor_items"]:
        lines.append(
            "Background from the room just left (not yet inherited):"
        )
        for entry in projection["provisional_predecessor_items"]:
            item = entry["item"]
            lines.append(
                f"- {_ITEM_LABELS[item['item_kind']]}: {item['summary']}"
            )
    if projection["authoritative_empty"]:
        lines.append("- No active continuity is carried for this room or scope.")
    if projection["authorship_result_state"] == "explicit_no_delta":
        lines.append(
            "- The latest authored continuity result explicitly made no change."
        )
    elif projection["authorship_result_state"] == "no_authored_result":
        lines.append(
            "- No authored continuity result is available for this room."
        )
    return {
        "section_id": "continuity_working_set",
        "section_class": "continuity_working_set",
        "exactness": "derived",
        "update_frequency": "per_turn",
        "rendered_text": "\n".join(lines),
    }


def generation2_section_from_env(
    env: Mapping[str, str],
    *,
    room_id: str,
    now: str | None = None,
    predecessor_room_id: str | None = None,
) -> dict[str, str] | None:
    state = control_state(env)
    if state["mode"] == OFF or state["selector"] == OFF:
        return None
    root = _root(env, require_existing=True)
    working_root = root / "working_set"
    if not working_root.exists() or not working_root.is_dir():
        _fail("m2_working_set_root_unavailable")
    store = HouseContinuityV12LocalStore(
        working_root, synthetic_only=True
    )
    try:
        projection = read_authoritative_projection(
            store,
            room_id=room_id,
            now=(
                now
                or datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.%fZ"
                )
            ),
            predecessor_room_id=predecessor_room_id,
        )
        return provider_section(projection)
    finally:
        store.close()


def select_or_rollback(
    env: Mapping[str, str],
    *,
    working_set_projection: Mapping[str, Any],
    prior_projection: Mapping[str, Any],
) -> dict[str, Any]:
    state = control_state(env)
    selected = (
        deepcopy(dict(working_set_projection))
        if state["selector"] == ON
        else deepcopy(dict(prior_projection))
    )
    body = {
        "schema_version": ROLLBACK_SCHEMA_VERSION,
        "state": "selected" if state["selector"] == ON else "rolled_back",
        "selected_projection_sha256": canonical_sha256(selected),
        "working_set_records_rewritten": False,
        "dual_render": False,
        "raw_body_included": False,
    }
    return {
        "projection": selected,
        "receipt": {**body, "receipt_sha256": canonical_sha256(body)},
    }


def doctor(env: Mapping[str, str]) -> dict[str, Any]:
    state = control_state(env)
    root = _root(env, require_existing=False)
    if state["mode"] == OFF:
        return {
            "schema_version": SCHEMA_VERSION,
            "state": "healthy",
            **state,
            "working_set_state": "not_opened",
            "raw_material_present": False,
        }
    working_root = root / "working_set"
    if not working_root.exists() or not working_root.is_dir():
        _fail("m2_working_set_root_unavailable")
    store = HouseContinuityV12LocalStore(
        working_root, synthetic_only=True
    )
    try:
        store_state = store.doctor()
    finally:
        store.close()
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "healthy",
        **state,
        "working_set_state": "present",
        "working_set_store_id": store_state["store_id"],
        "working_set_replay_exact": store_state["replay_exact"],
        "raw_material_present": False,
    }


__all__ = [
    "APPLICATION_SCHEMA_VERSION",
    "COPY_REHEARSAL",
    "Milestone2AuthorityError",
    "OFF",
    "ON",
    "PROJECTION_SCHEMA_VERSION",
    "REVIEW_SCHEMA_VERSION",
    "ROOT_ENV",
    "SCHEMA_VERSION",
    "SELECTOR_ENV",
    "STATE_MACHINE",
    "SWITCH_ENV",
    "WRITER_ENV",
    "apply_reviewed_bundle",
    "build_review_receipt",
    "control_state",
    "doctor",
    "generation2_section_from_env",
    "provider_section",
    "read_authoritative_projection",
    "select_or_rollback",
    "validate_authoritative_projection",
]
