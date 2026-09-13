"""Outbox, application-fence, and unit-coverage contracts for Continuity V1.2."""

from __future__ import annotations

from _house_continuity_v1_2_contract_primitives_v0 import *
from _house_continuity_v1_2_contract_capabilities_context_v0 import (
    INTENT_PROTOCOL_VERSION,
    INTENT_SCHEMA_VERSION,
    _context_binding_fields,
    validate_continuity_intent,
    validate_intent_capability,
)

UNIT_COVERAGE_SCHEMA_VERSION = "house_continuity_unit_coverage_v1"

OUTBOX_SCHEMA_VERSION = "house_continuity_command_outbox_bundle_v1"

APPLICATION_FENCE_SCHEMA_VERSION = "house_continuity_application_fence_v1"

APPLICATION_FENCE_RECEIPT_SCHEMA_VERSION = (
    "house_continuity_application_fence_receipt_v1"
)

OUTBOX_STATES = (
    "prepared_waiting_visible",
    "visible_released_waiting_unit",
    "ready_to_apply",
    "applying",
    "retryable_failure",
    "conflict_recorded",
    "applied",
    "cancelled_before_visible",
)

COVERAGE_EVICTION_MATRIX = {
    "participant_semantic_coverage": {
        "coverage_finalized": True,
        "safe_for_source_eviction": True,
    },
    "structured_semantic_coverage": {
        "coverage_finalized": True,
        "safe_for_source_eviction": True,
    },
    "solen_no_semantic_delta": {
        "coverage_finalized": True,
        "safe_for_source_eviction": True,
    },
    "verified_exact_history_survival": {
        "coverage_finalized": True,
        "safe_for_source_eviction": True,
    },
    "coverage_only": {
        "coverage_finalized": False,
        "safe_for_source_eviction": False,
    },
    "curator_only": {
        "coverage_finalized": False,
        "safe_for_source_eviction": False,
    },
    "heuristic_only": {
        "coverage_finalized": False,
        "safe_for_source_eviction": False,
    },
    "authorship_not_supplied": {
        "coverage_finalized": False,
        "safe_for_source_eviction": False,
    },
    "preparation_pending": {
        "coverage_finalized": False,
        "safe_for_source_eviction": False,
    },
    "application_pending": {
        "coverage_finalized": False,
        "safe_for_source_eviction": False,
    },
    "application_failed_retryable": {
        "coverage_finalized": False,
        "safe_for_source_eviction": False,
    },
    "application_conflict_recorded": {
        "coverage_finalized": False,
        "safe_for_source_eviction": False,
    },
}

_OUTBOX_TRANSITION_TARGETS = {
    (None, "atomic_prepare_before_visible"): "prepared_waiting_visible",
    (None, "atomic_retry_after_visible"): "visible_released_waiting_unit",
    (
        "prepared_waiting_visible",
        "visible_released",
    ): "visible_released_waiting_unit",
    (
        "visible_released_waiting_unit",
        "exact_unit_bound",
    ): "ready_to_apply",
    ("ready_to_apply", "lease"): "applying",
    ("applying", "all_receipts_committed"): "applied",
    ("applying", "infrastructure_failure"): "retryable_failure",
    ("retryable_failure", "retry"): "applying",
    (
        "applying",
        "authoritative_conflict_receipt",
    ): "conflict_recorded",
    (
        "prepared_waiting_visible",
        "visible_delivery_permanently_cancelled",
    ): "cancelled_before_visible",
}

def _outbox_state_invariants(
    raw: Mapping[str, Any],
    *,
    unit_binding: str,
    units: list[str],
    unit_hashes: list[str],
    state: str,
    operations: list[dict[str, Any]],
    has_scope_binding_operation: bool,
) -> dict[str, Any]:
    visible = (
        None
        if raw["visible_released_at"] is None
        else _timestamp(raw["visible_released_at"], name="visible_released_at")
    )
    applied = (
        None
        if raw["applied_at"] is None
        else _timestamp(raw["applied_at"], name="applied_at")
    )
    retry = (
        None
        if raw["next_retry_at"] is None
        else _timestamp(raw["next_retry_at"], name="next_retry_at")
    )
    error = (
        None
        if raw["last_error_code"] is None
        else _code(
            raw["last_error_code"],
            name="last_error_code",
            allowed=(
                "working_set_unavailable",
                "cas_dependency_unavailable",
                "lease_expired",
            ),
        )
    )
    terminal = (
        None
        if raw["terminal_code"] is None
        else _code(
            raw["terminal_code"],
            name="terminal_code",
            allowed=("applied", "authoritative_conflict", "cancelled_before_visible"),
        )
    )
    attempts = _integer(
        raw["application_attempt_count"], name="application_attempt_count"
    )
    ws_receipts = _id_list(
        raw["working_set_receipt_ids"],
        name="working_set_receipt_ids",
        maximum=MAX_RECEIPT_IDS,
    )
    coverage_receipts = _id_list(
        raw["coverage_receipt_ids"],
        name="coverage_receipt_ids",
        maximum=MAX_RECEIPT_IDS,
    )
    bound_states = {
        "ready_to_apply",
        "applying",
        "retryable_failure",
        "conflict_recorded",
        "applied",
    }
    if state in bound_states and (unit_binding != "bound" or not units):
        _error("outbox_bound_unit_required", f"{state} requires exact bound units.")
    if state in {"prepared_waiting_visible", "visible_released_waiting_unit", "cancelled_before_visible"} and unit_binding != "pending_complete_unit":
        _error("outbox_pending_unit_required", f"{state} requires pending binding.")
    if state == "prepared_waiting_visible":
        expected = (visible is None, applied is None, attempts == 0, not ws_receipts, not coverage_receipts, retry is None, error is None, terminal is None)
    elif state == "visible_released_waiting_unit":
        expected = (visible is not None, applied is None, attempts == 0, not ws_receipts, not coverage_receipts, retry is None, error is None, terminal is None)
    elif state == "ready_to_apply":
        expected = (visible is not None, applied is None, attempts == 0, not ws_receipts, not coverage_receipts, retry is None, error is None, terminal is None)
    elif state == "applying":
        expected = (visible is not None, applied is None, attempts >= 1, not ws_receipts, not coverage_receipts, retry is None, error is None, terminal is None)
    elif state == "retryable_failure":
        expected = (visible is not None, applied is None, attempts >= 1, not ws_receipts, not coverage_receipts, retry is not None, error is not None, terminal is None)
    elif state == "conflict_recorded":
        expected = (visible is not None, applied is None, attempts >= 1, len(ws_receipts) == 1, not coverage_receipts, retry is None, error is None, terminal == "authoritative_conflict")
    elif state == "applied":
        required_working_set_receipts = len(operations) + (
            1 if has_scope_binding_operation else 0
        )
        semantic_receipt_ok = len(ws_receipts) == required_working_set_receipts
        expected = (visible is not None, applied is not None, attempts >= 1, semantic_receipt_ok, len(coverage_receipts) == 1, retry is None, error is None, terminal == "applied")
    else:
        expected = (visible is None, applied is None, attempts == 0, not ws_receipts, not coverage_receipts, retry is None, error is None, terminal == "cancelled_before_visible")
    if not all(expected):
        _error("invalid_outbox_state_invariants", f"{state} fields contradict state.")
    return {
        "visible_released_at": visible,
        "applied_at": applied,
        "next_retry_at": retry,
        "last_error_code": error,
        "terminal_code": terminal,
        "application_attempt_count": attempts,
        "working_set_receipt_ids": ws_receipts,
        "coverage_receipt_ids": coverage_receipts,
    }

def validate_outbox_bundle(value: Any) -> dict[str, Any]:
    fields = (
        "schema_version",
        "bundle_id",
        "creation_seed_sha256",
        "capability_id",
        "capability_sha256",
        "client_turn_id",
        "room_id",
        "provider_operation_id",
        "protocol_version",
        "command_context_id",
        "command_context_sha256",
        "snapshot_global_event_sequence",
        "snapshot_global_event_sha256",
        "scope_binding_revision",
        "terminal_response_sha256",
        "visible_response_sha256",
        "unit_binding_state",
        "covered_complete_unit_ids",
        "covered_complete_unit_sha256s",
        "coverage_decision",
        "normalized_semantic_operations",
        "normalized_scope_binding_operation",
        "command_bundle_sha256",
        "idempotency_identity",
        "state",
        "application_attempt_count",
        "next_retry_at",
        "last_error_code",
        "terminal_code",
        "working_set_receipt_ids",
        "coverage_receipt_ids",
        "prepared_at",
        "visible_released_at",
        "applied_at",
        "updated_at",
    )
    raw = _exact(value, fields, path="outbox_bundle")
    if raw["schema_version"] != OUTBOX_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported outbox schema.")
    if raw["protocol_version"] != INTENT_PROTOCOL_VERSION:
        _error("invalid_protocol_version", "Outbox protocol differs.")
    intent = validate_continuity_intent(
        {
            "capability": "cwc_" + ("A" * 43),
            "schema_version": INTENT_SCHEMA_VERSION,
            "protocol_version": INTENT_PROTOCOL_VERSION,
            "coverage_decision": raw["coverage_decision"],
            "semantic_operations": raw["normalized_semantic_operations"],
            "scope_binding_operation": raw["normalized_scope_binding_operation"],
        }
    )
    context_binding = _context_binding_fields(raw)
    expected_command_bundle_sha256 = canonical_sha256(
        {
            **context_binding,
            "coverage_decision": intent["coverage_decision"],
            "normalized_semantic_operations": intent["semantic_operations"],
            "normalized_scope_binding_operation": intent[
                "scope_binding_operation"
            ],
        }
    )
    if raw["command_bundle_sha256"] != expected_command_bundle_sha256:
        _error(
            "command_bundle_sha256_mismatch",
            "Command bundle digest does not bind normalized commands and context.",
        )
    unit_binding = _code(
        raw["unit_binding_state"],
        name="unit_binding_state",
        allowed=("pending_complete_unit", "bound", "binding_failed"),
    )
    units = _id_list(
        raw["covered_complete_unit_ids"],
        name="covered_complete_unit_ids",
        maximum=MAX_COMPLETE_UNIT_IDS,
    )
    if not isinstance(raw["covered_complete_unit_sha256s"], list):
        _error("invalid_complete_unit_hashes", "Unit hashes must be a list.")
    unit_hashes = [
        _hash(item, name="covered_complete_unit_sha256")
        for item in raw["covered_complete_unit_sha256s"]
    ]
    if (
        len(unit_hashes) > MAX_COMPLETE_UNIT_IDS
        or len(unit_hashes) != len(set(unit_hashes))
        or len(units) != len(unit_hashes)
        or (unit_binding == "bound") != bool(units)
    ):
        _error("invalid_complete_unit_binding", "Unit evidence is inconsistent.")
    state = _code(raw["state"], name="state", allowed=OUTBOX_STATES)
    state_fields = _outbox_state_invariants(
        raw,
        unit_binding=unit_binding,
        units=units,
        unit_hashes=unit_hashes,
        state=state,
        operations=intent["semantic_operations"],
        has_scope_binding_operation=intent["scope_binding_operation"] is not None,
    )
    prepared = _timestamp(raw["prepared_at"], name="prepared_at")
    updated = _timestamp(raw["updated_at"], name="updated_at")
    ordered = [
        prepared,
        state_fields["visible_released_at"],
        state_fields["applied_at"],
        updated,
    ]
    values = [_timestamp_value(item) for item in ordered if item is not None]
    if values != sorted(values):
        _error("nonmonotonic_outbox_timestamps", "Outbox timestamps regress.")
    if (
        state_fields["next_retry_at"] is not None
        and _timestamp_value(state_fields["next_retry_at"])
        < _timestamp_value(updated)
    ):
        _error(
            "nonmonotonic_outbox_timestamps",
            "Retry time precedes the latest state update.",
        )
    return {
        **raw,
        "bundle_id": _id(raw["bundle_id"], name="bundle_id", kind="bundle_id"),
        "creation_seed_sha256": _hash(
            raw["creation_seed_sha256"], name="creation_seed_sha256"
        ),
        "capability_id": _id(
            raw["capability_id"], name="capability_id", kind="capability_id"
        ),
        "capability_sha256": _hash(
            raw["capability_sha256"], name="capability_sha256"
        ),
        "client_turn_id": _id(
            raw["client_turn_id"], name="client_turn_id"
        ),
        "room_id": _id(raw["room_id"], name="room_id", kind="room_id"),
        "provider_operation_id": _id(
            raw["provider_operation_id"], name="provider_operation_id"
        ),
        **context_binding,
        "terminal_response_sha256": _hash(
            raw["terminal_response_sha256"], name="terminal_response_sha256"
        ),
        "visible_response_sha256": _hash(
            raw["visible_response_sha256"], name="visible_response_sha256"
        ),
        "unit_binding_state": unit_binding,
        "covered_complete_unit_ids": units,
        "covered_complete_unit_sha256s": unit_hashes,
        "coverage_decision": intent["coverage_decision"],
        "normalized_semantic_operations": intent["semantic_operations"],
        "normalized_scope_binding_operation": intent["scope_binding_operation"],
        "command_bundle_sha256": expected_command_bundle_sha256,
        "idempotency_identity": _string(
            raw["idempotency_identity"],
            name="idempotency_identity",
            maximum=160,
        ),
        "state": state,
        **state_fields,
        "prepared_at": prepared,
        "updated_at": updated,
    }

def validate_outbox_against_capability(
    outbox: Any,
    capability: Any,
) -> dict[str, Any]:
    normalized_outbox = validate_outbox_bundle(outbox)
    normalized_capability = validate_intent_capability(capability)
    if (
        normalized_capability["state"] != "prepared_consumed"
        or normalized_capability["outbox_bundle_id"]
        != normalized_outbox["bundle_id"]
        or normalized_capability["terminal_response_sha256"]
        != normalized_outbox["terminal_response_sha256"]
    ):
        _error(
            "outbox_capability_preparation_mismatch",
            "Capability does not own this prepared terminal bundle.",
        )
    fields = (
        "capability_id",
        "capability_sha256",
        "client_turn_id",
        "room_id",
        "provider_operation_id",
        "protocol_version",
        "command_context_id",
        "command_context_sha256",
        "snapshot_global_event_sequence",
        "snapshot_global_event_sha256",
        "scope_binding_revision",
    )
    if any(
        normalized_outbox[field] != normalized_capability[field]
        for field in fields
    ):
        _error(
            "outbox_capability_binding_mismatch",
            "Prepared bundle differs from its capability/context binding.",
        )
    return normalized_outbox

def validate_exact_outbox_retry(existing: Any, candidate: Any) -> dict[str, Any]:
    normalized_existing = validate_outbox_bundle(existing)
    normalized_candidate = validate_outbox_bundle(candidate)
    retry_identity_fields = (
        "bundle_id",
        "capability_id",
        "capability_sha256",
        "terminal_response_sha256",
        "visible_response_sha256",
        "command_bundle_sha256",
        "idempotency_identity",
        "command_context_id",
        "command_context_sha256",
        "snapshot_global_event_sequence",
        "snapshot_global_event_sha256",
        "scope_binding_revision",
        "coverage_decision",
        "normalized_semantic_operations",
        "normalized_scope_binding_operation",
    )
    if any(
        normalized_existing[field] != normalized_candidate[field]
        for field in retry_identity_fields
    ):
        _error(
            "outbox_retry_identity_mismatch",
            "Exact retry changed command or command-context identity.",
        )
    return normalized_existing

def validate_outbox_transition(
    previous: Any | None,
    candidate: Any,
    *,
    event: str,
) -> dict[str, Any]:
    normalized_candidate = validate_outbox_bundle(candidate)
    normalized_previous = (
        None if previous is None else validate_outbox_bundle(previous)
    )
    from_state = (
        None if normalized_previous is None else normalized_previous["state"]
    )
    expected = _OUTBOX_TRANSITION_TARGETS.get((from_state, event))
    if expected is None:
        _error("unsupported_outbox_transition", "Transition edge is not defined.")
    if normalized_candidate["state"] != expected:
        _error(
            "wrong_outbox_transition_target",
            "Transition target differs from the exact state machine.",
        )
    if normalized_previous is not None:
        validate_exact_outbox_retry(normalized_previous, normalized_candidate)
        if (
            normalized_candidate["application_attempt_count"]
            < normalized_previous["application_attempt_count"]
        ):
            _error(
                "outbox_attempt_count_regression",
                "Transition cannot reduce attempt count.",
            )
        if _timestamp_value(normalized_candidate["updated_at"]) < _timestamp_value(
            normalized_previous["updated_at"]
        ):
            _error(
                "outbox_transition_time_regression",
                "Transition update time regresses.",
            )
    return {
        "from_state": from_state,
        "event": event,
        "to_state": normalized_candidate["state"],
        "bundle_id": normalized_candidate["bundle_id"],
        "command_context_sha256": normalized_candidate[
            "command_context_sha256"
        ],
    }

def validate_application_fence(value: Any) -> dict[str, Any]:
    fields = (
        "schema_version",
        "fence_id",
        "creation_seed_sha256",
        "room_relation",
        "current_room_id",
        "current_client_turn_id",
        "prior_room_id",
        "prior_client_turn_id",
        "prior_provider_operation_id",
        "continuity_outcome",
        "outbox_bundle_id",
        "working_set_receipt_ids",
        "coverage_receipt_ids",
        "exact_fallback",
        "selection_requires_prior_authored_state",
        "maximum_local_wait_millis",
    )
    raw = _exact(value, fields, path="application_fence")
    if raw["schema_version"] != APPLICATION_FENCE_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported application fence.")
    relation = _code(
        raw["room_relation"],
        name="room_relation",
        allowed=("same_room", "fresh_room"),
    )
    current_room = _id(
        raw["current_room_id"], name="current_room_id", kind="room_id"
    )
    prior_room = _id(
        raw["prior_room_id"], name="prior_room_id", kind="room_id"
    )
    if (relation == "same_room") != (current_room == prior_room):
        _error("invalid_room_relation", "Room relation contradicts IDs.")
    outcome = _code(
        raw["continuity_outcome"],
        name="continuity_outcome",
        allowed=(
            "applied",
            "no_carrier_or_closed_unused",
            "pending_preparation_or_application",
            "conflict_or_rejected",
            "unavailable",
        ),
    )
    bundle = _nullable_id(
        raw["outbox_bundle_id"], name="outbox_bundle_id", kind="bundle_id"
    )
    ws = _id_list(
        raw["working_set_receipt_ids"],
        name="working_set_receipt_ids",
        maximum=MAX_RECEIPT_IDS,
    )
    coverage = _id_list(
        raw["coverage_receipt_ids"],
        name="coverage_receipt_ids",
        maximum=MAX_RECEIPT_IDS,
    )
    fallback_raw = _exact(
        raw["exact_fallback"],
        (
            "state",
            "owner_code",
            "complete_unit_id",
            "complete_unit_sha256",
            "exact_body_included",
        ),
        path="application_fence.exact_fallback",
    )
    fallback_state = _code(
        fallback_raw["state"],
        name="exact_fallback_state",
        allowed=("not_needed", "available", "missing", "unavailable"),
    )
    if fallback_raw["exact_body_included"] is not False:
        _error("exact_body_forbidden", "Fence contains references only.")
    if fallback_state == "available":
        owner = _code(
            fallback_raw["owner_code"],
            name="owner_code",
            allowed=("house_complete_continuity_unit_v1",),
        )
        unit = _id(
            fallback_raw["complete_unit_id"], name="complete_unit_id"
        )
        unit_hash = _hash(
            fallback_raw["complete_unit_sha256"],
            name="complete_unit_sha256",
        )
    else:
        if any(
            fallback_raw[name] is not None
            for name in ("owner_code", "complete_unit_id", "complete_unit_sha256")
        ):
            _error("invalid_exact_fallback", "Nonavailable fallback has no refs.")
        owner = unit = unit_hash = None
    if outcome == "applied":
        valid = bundle is not None and bool(ws) and bool(coverage) and fallback_state == "not_needed"
    elif outcome == "no_carrier_or_closed_unused":
        valid = bundle is None and not ws and not coverage and fallback_state == "not_needed"
    elif outcome == "pending_preparation_or_application":
        valid = not ws and not coverage and fallback_state in (
            {"available", "unavailable"}
            if relation == "same_room"
            else {"available", "missing", "unavailable"}
        )
    elif outcome == "conflict_or_rejected":
        valid = bundle is not None and bool(ws) and not coverage and fallback_state == "not_needed"
    else:
        valid = bundle is None and not ws and not coverage and fallback_state == "unavailable"
    if not valid:
        _error(
            "contradictory_application_fence",
            "Fence evidence contradicts its outcome.",
        )
    if raw["selection_requires_prior_authored_state"] is not True:
        _error(
            "invalid_fence_requirement",
            "Fence is used only when prior authored state is required.",
        )
    return {
        **raw,
        "fence_id": _id(raw["fence_id"], name="fence_id", kind="fence_id"),
        "creation_seed_sha256": _hash(
            raw["creation_seed_sha256"], name="creation_seed_sha256"
        ),
        "room_relation": relation,
        "current_room_id": current_room,
        "current_client_turn_id": _id(
            raw["current_client_turn_id"], name="current_client_turn_id"
        ),
        "prior_room_id": prior_room,
        "prior_client_turn_id": _id(
            raw["prior_client_turn_id"], name="prior_client_turn_id"
        ),
        "prior_provider_operation_id": _id(
            raw["prior_provider_operation_id"],
            name="prior_provider_operation_id",
        ),
        "continuity_outcome": outcome,
        "outbox_bundle_id": bundle,
        "working_set_receipt_ids": ws,
        "coverage_receipt_ids": coverage,
        "exact_fallback": {
            "state": fallback_state,
            "owner_code": owner,
            "complete_unit_id": unit,
            "complete_unit_sha256": unit_hash,
            "exact_body_included": False,
        },
        "selection_requires_prior_authored_state": True,
        "maximum_local_wait_millis": _integer(
            raw["maximum_local_wait_millis"],
            name="maximum_local_wait_millis",
            maximum=1_000,
        ),
    }

def decide_application_fence(
    fence: Any,
    *,
    post_wait_outcome: str | None = None,
    wait_millis: int = 0,
    post_wait_outbox_bundle_id: str | None = None,
    post_wait_working_set_receipt_ids: list[str] | None = None,
    post_wait_coverage_receipt_ids: list[str] | None = None,
) -> dict[str, Any]:
    normalized = validate_application_fence(fence)
    initial = normalized["continuity_outcome"]
    final_fence = normalized
    waited = post_wait_outcome is not None
    if waited:
        if initial != "pending_preparation_or_application":
            _error("unexpected_reconciliation_wait", "Only pending fences wait.")
        if wait_millis < 0 or wait_millis > normalized["maximum_local_wait_millis"]:
            _error("invalid_wait_millis", "Reconciliation wait exceeds its cap.")
        updated = dict(normalized)
        updated["continuity_outcome"] = post_wait_outcome
        updated["outbox_bundle_id"] = post_wait_outbox_bundle_id
        updated["working_set_receipt_ids"] = (
            post_wait_working_set_receipt_ids or []
        )
        updated["coverage_receipt_ids"] = post_wait_coverage_receipt_ids or []
        if post_wait_outcome != "pending_preparation_or_application":
            updated["exact_fallback"] = {
                "state": (
                    "unavailable"
                    if post_wait_outcome == "unavailable"
                    else "not_needed"
                ),
                "owner_code": None,
                "complete_unit_id": None,
                "complete_unit_sha256": None,
                "exact_body_included": False,
            }
        final_fence = validate_application_fence(updated)
    elif wait_millis != 0:
        _error("unexpected_wait_millis", "No wait was attempted.")
    final = final_fence["continuity_outcome"]
    fallback = final_fence["exact_fallback"]["state"]
    relation = final_fence["room_relation"]
    if final == "applied":
        behavior = "applied_working_set"
    elif final == "no_carrier_or_closed_unused":
        behavior = "no_new_authored_delta"
    elif final == "conflict_or_rejected":
        behavior = "conflict_or_rejected_state"
    elif final == "unavailable":
        behavior = "authoritative_unavailable"
    elif relation == "same_room":
        behavior = (
            "same_room_exact_recent_fallback"
            if fallback == "available"
            else "working_set_not_yet_applied"
        )
    elif fallback == "available":
        behavior = "fresh_room_exact_predecessor_fallback"
    elif fallback == "missing":
        behavior = "provisional_handoff_pending"
    else:
        behavior = "authoritative_unavailable"
    basis = {
        "schema_version": APPLICATION_FENCE_RECEIPT_SCHEMA_VERSION,
        "fence_id": normalized["fence_id"],
        "initial_outcome": initial,
        "post_wait_outcome": final,
        "local_wait_attempted": waited,
        "wait_millis": wait_millis,
        "selection_behavior": behavior,
        "outbox_bundle_id": final_fence["outbox_bundle_id"],
        "working_set_receipt_ids": final_fence["working_set_receipt_ids"],
        "coverage_receipt_ids": final_fence["coverage_receipt_ids"],
        "exact_fallback_ref_sha256": (
            final_fence["exact_fallback"]["complete_unit_sha256"]
            if "fallback" in behavior
            else None
        ),
        "pending_commands_selected_as_truth": False,
        "global_newest_digest_used": False,
        "second_provider_call_made": False,
    }
    return {
        "receipt_id": "cws_frcpt_" + canonical_sha256(basis)[:32],
        **basis,
    }

def validate_unit_coverage(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "coverage_id",
            "creation_seed_sha256",
            "room_id",
            "complete_unit_id",
            "complete_unit_sha256",
            "coverage_state",
            "authority_refs",
            "exact_survival_ref",
            "coverage_finalized",
            "safe_for_source_eviction",
            "snapshot_global_event_sequence",
            "created_at",
        ),
        path="unit_coverage",
    )
    if raw["schema_version"] != UNIT_COVERAGE_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported unit coverage.")
    state = _code(
        raw["coverage_state"],
        name="coverage_state",
        allowed=tuple(COVERAGE_EVICTION_MATRIX),
    )
    expected = COVERAGE_EVICTION_MATRIX[state]
    if (
        raw["coverage_finalized"] is not expected["coverage_finalized"]
        or raw["safe_for_source_eviction"]
        is not expected["safe_for_source_eviction"]
    ):
        _error(
            "invalid_coverage_safety",
            "Coverage flags differ from the eviction matrix.",
        )
    authority_refs = _opaque_list(
        raw["authority_refs"], name="authority_refs", maximum=8
    )
    survival_ref = (
        None
        if raw["exact_survival_ref"] is None
        else _hash(raw["exact_survival_ref"], name="exact_survival_ref")
    )
    if state == "verified_exact_history_survival":
        if survival_ref is None:
            _error("missing_exact_survival_ref", "Exact survival requires receipt.")
    elif survival_ref is not None:
        _error(
            "unexpected_exact_survival_ref",
            "Only exact-survival coverage has this receipt.",
        )
    if expected["coverage_finalized"] and not authority_refs:
        _error(
            "missing_coverage_authority",
            "Finalized coverage requires authority evidence.",
        )
    return {
        "schema_version": UNIT_COVERAGE_SCHEMA_VERSION,
        "coverage_id": _id(raw["coverage_id"], name="coverage_id"),
        "creation_seed_sha256": _hash(
            raw["creation_seed_sha256"], name="creation_seed_sha256"
        ),
        "room_id": _id(raw["room_id"], name="room_id", kind="room_id"),
        "complete_unit_id": _id(
            raw["complete_unit_id"], name="complete_unit_id"
        ),
        "complete_unit_sha256": _hash(
            raw["complete_unit_sha256"], name="complete_unit_sha256"
        ),
        "coverage_state": state,
        "authority_refs": authority_refs,
        "exact_survival_ref": survival_ref,
        "coverage_finalized": expected["coverage_finalized"],
        "safe_for_source_eviction": expected["safe_for_source_eviction"],
        "snapshot_global_event_sequence": _integer(
            raw["snapshot_global_event_sequence"],
            name="snapshot_global_event_sequence",
        ),
        "created_at": _timestamp(raw["created_at"], name="created_at"),
    }

__all__ = [
    "UNIT_COVERAGE_SCHEMA_VERSION",
    "OUTBOX_SCHEMA_VERSION",
    "APPLICATION_FENCE_SCHEMA_VERSION",
    "APPLICATION_FENCE_RECEIPT_SCHEMA_VERSION",
    "OUTBOX_STATES",
    "COVERAGE_EVICTION_MATRIX",
    "_OUTBOX_TRANSITION_TARGETS",
    "_outbox_state_invariants",
    "validate_outbox_bundle",
    "validate_outbox_against_capability",
    "validate_exact_outbox_retry",
    "validate_outbox_transition",
    "validate_application_fence",
    "decide_application_fence",
    "validate_unit_coverage",
]
