"""Canonical synthetic fixtures for House Continuity V1.2 Gate 0.

All values are invented, body-free, local contract data. Importing this
module performs no I/O and cannot issue capabilities or write continuity.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from house_continuity_v1_2_dependency_fixtures_v0 import (
    ADVERSARIAL_DEPENDENCY_FIXTURES,
    EVENT_CHAIN_FIXTURES,
    POSITIVE_DEPENDENCY_FIXTURES,
)
from house_continuity_v1_2_literal_conformance_fixtures_v0 import (
    CLOSURE_ADVERSARIAL_FIXTURES,
    ITEM_KIND_PAYLOADS as LITERAL_ITEM_KIND_PAYLOADS,
)
from house_continuity_v1_2_terminal_tail_fixtures_v0 import (
    TERMINAL_FIXTURE_BUNDLE_SHA256,
    TERMINAL_PRIVATE_TAIL_FIXTURES,
)
from house_continuity_v1_2_gate0_conformance_ledger_v0 import (
    GATE1_CARRY_FORWARD_OBLIGATIONS,
    GATE2_CARRY_FORWARD_OBLIGATIONS,
    GATE0_CONFORMANCE_LEDGER,
)
from house_continuity_v1_2_contract_schema_v0 import (
    APPLICATION_FENCE_SCHEMA_VERSION,
    ASTEL_COMMAND_SCHEMA_VERSION,
    ASTEL_CONFIRMATION_SCHEMA_VERSION,
    CAPABILITY_OFFER_SCHEMA_VERSION,
    CAPABILITY_SCHEMA_VERSION,
    COMMAND_CONTEXT_AUTHORITY,
    COMMAND_CONTEXT_SCHEMA_VERSION,
    GENERATION_IDENTITY_SCHEMA_VERSION,
    INTENT_PROTOCOL_VERSION,
    INTENT_SCHEMA_VERSION,
    JOINT_ATTESTATION_SCHEMA_VERSION,
    OUTBOX_SCHEMA_VERSION,
    UNIT_COVERAGE_SCHEMA_VERSION,
    canonical_sha256,
    canonical_astel_semantic_command,
    contract_matrix_bundle,
    derived_house_cache_signature,
    synthetic_sha256,
)
from house_continuity_v1_2_executable_contracts_v0 import OUTBOX_STATES


ROOM_A = "cws_room_" + ("a" * 32)
ROOM_B = "cws_room_" + ("b" * 32)
PROJECT_A = "cws_prj_" + ("a" * 32)
THREAD_A = "cws_thr_" + ("a" * 32)
ITEM_TASK = "cws_item_" + ("1" * 32)
ITEM_THREAD = "cws_item_" + ("2" * 32)
ITEM_TASK_SUCCESSOR = "cws_item_" + ("3" * 32)
ITEM_UNKNOWN = "cws_item_" + ("9" * 32)
CONTEXT_ID = "cws_ctx_" + ("1" * 32)
OFFER_ID = "cws_offer_" + ("1" * 32)
CAPABILITY_ID = "cwcap_" + ("1" * 32)
CAPABILITY = "cwc_" + ("A" * 43)
BUNDLE_ID = "cws_out_" + ("1" * 32)
COMPLETE_UNIT_ID = "complete-unit-a-0001"
CLIENT_TURN_ID = "client-turn-a-0001"
NEXT_CLIENT_TURN_ID = "client-turn-a-0002"
FRESH_CLIENT_TURN_ID = "client-turn-b-0001"
PROVIDER_OPERATION_ID = "provider-operation-a-0001"
TIMESTAMP = "2026-07-28T00:00:00.000Z"
EXPIRES_AT = "2026-07-28T01:00:00.000Z"

PROJECT_SCOPE = {
    "scope_kind": "project",
    "room_id": None,
    "project_id": PROJECT_A,
    "thread_id": THREAD_A,
}
ROOM_SCOPE = {
    "scope_kind": "room",
    "room_id": ROOM_A,
    "project_id": None,
    "thread_id": None,
}


COMMAND_CONTEXT = {
    "schema_version": COMMAND_CONTEXT_SCHEMA_VERSION,
    "context_id": CONTEXT_ID,
    "creation_seed_sha256": synthetic_sha256("command-context-creation-seed"),
    "snapshot_global_event_sequence": 41,
    "snapshot_global_event_sha256": synthetic_sha256("event-sequence-41"),
    "room_id": ROOM_A,
    "scope_binding_revision": 7,
    "items": [
        {
            "item_id": ITEM_TASK,
            "revision": 3,
            "item_kind": "active_task",
            "lifecycle_state": "active",
            "scope": PROJECT_SCOPE,
            "summary": "Finish the bounded continuity contract review.",
            "kind_payload": {
                "task_state": "in_progress",
                "linked_item_ids": [],
                "completion_evidence_refs": [],
            },
            "content_sha256": "",
            "allowed_operations": [
                "confirm",
                "revise",
                "resolve",
                "supersede",
            ],
            "offered_successor_item_ids": [ITEM_TASK_SUCCESSOR],
        },
        {
            "item_id": ITEM_THREAD,
            "revision": 2,
            "item_kind": "emotional_thread",
            "lifecycle_state": "resolved",
            "scope": PROJECT_SCOPE,
            "summary": "The earlier uncertainty was acknowledged and settled.",
            "kind_payload": {
                "thread_state": "held",
                "expressed_by": "shared",
                "linked_item_ids": [],
            },
            "content_sha256": "",
            "allowed_operations": ["reopen", "supersede"],
            "offered_successor_item_ids": [],
        },
        {
            "item_id": ITEM_TASK_SUCCESSOR,
            "revision": 1,
            "item_kind": "active_task",
            "lifecycle_state": "active",
            "scope": PROJECT_SCOPE,
            "summary": "Use the corrected Gate-0 contract as the review basis.",
            "kind_payload": {
                "task_state": "not_started",
                "linked_item_ids": [ITEM_TASK],
                "completion_evidence_refs": [],
            },
            "content_sha256": "",
            "allowed_operations": ["confirm", "revise", "resolve"],
            "offered_successor_item_ids": [],
        },
    ],
    "create_offers": [
        {
            "offer_id": OFFER_ID,
            "scope": PROJECT_SCOPE,
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
    "provisional_scope_binding_choices": [
        {
            "choice_code": "inherit_predecessor_project_thread",
            "predecessor_room_id": ROOM_A,
            "target_scope": PROJECT_SCOPE,
            "expected_binding_revision": 7,
        },
        {
            "choice_code": "decline_predecessor",
            "predecessor_room_id": ROOM_A,
            "target_scope": None,
            "expected_binding_revision": 7,
        },
    ],
    "authority": dict(COMMAND_CONTEXT_AUTHORITY),
}
for _offered_item in COMMAND_CONTEXT["items"]:
    _offered_item["content_sha256"] = canonical_sha256(
        {
            "item_kind": _offered_item["item_kind"],
            "scope": _offered_item["scope"],
            "summary": _offered_item["summary"],
            "kind_payload": _offered_item["kind_payload"],
        }
    )

ITEM_KIND_PAYLOAD_FIXTURES = deepcopy(LITERAL_ITEM_KIND_PAYLOADS)


def semantic_operation(
    *,
    operation_kind: str = "revise",
    item_id: str | None = ITEM_TASK,
    expected_revision: int = 3,
    item_kind: str = "active_task",
    scope: dict[str, Any] = PROJECT_SCOPE,
    summary: str = "Finish and independently verify the Gate-0 contract.",
    kind_payload: dict[str, Any] | None = None,
    reason_code: str | None = None,
    superseded_by_item_id: str | None = None,
) -> dict[str, Any]:
    if kind_payload is None:
        if operation_kind == "create" and item_kind == "question":
            kind_payload = {
                "question_owner": "unknown",
                "answer_state": "unanswered",
                "linked_item_ids": [],
            }
        elif operation_kind == "create":
            kind_payload = {
                "task_state": "not_started",
                "linked_item_ids": [],
                "completion_evidence_refs": [],
            }
        elif operation_kind == "revise":
            kind_payload = {"task_state": "in_progress"}
        else:
            kind_payload = {}
    return {
        "operation_key": f"op-{operation_kind}-001",
        "operation_kind": operation_kind,
        "item_id": item_id,
        "expected_revision": expected_revision,
        "item_kind": item_kind,
        "scope": deepcopy(scope),
        "summary": summary,
        "kind_payload": kind_payload,
        "reason_code": reason_code,
        "superseded_by_item_id": superseded_by_item_id,
        "source_proposal_ids": [],
    }


REVISE_INTENT = {
    "capability": CAPABILITY,
    "schema_version": INTENT_SCHEMA_VERSION,
    "protocol_version": INTENT_PROTOCOL_VERSION,
    "coverage_decision": "semantic_operations",
    "semantic_operations": [semantic_operation()],
    "scope_binding_operation": None,
}

CREATE_INTENT = {
    "capability": CAPABILITY,
    "schema_version": INTENT_SCHEMA_VERSION,
    "protocol_version": INTENT_PROTOCOL_VERSION,
    "coverage_decision": "semantic_operations",
    "semantic_operations": [
        semantic_operation(
            operation_kind="create",
            item_id=None,
            expected_revision=0,
            item_kind="question",
            summary="Which acceptance receipt should close the review?",
        )
    ],
    "scope_binding_operation": {
        "choice_code": "inherit_predecessor_project_thread",
        "expected_binding_revision": 7,
    },
}

NO_DELTA_INTENT = {
    "capability": CAPABILITY,
    "schema_version": INTENT_SCHEMA_VERSION,
    "protocol_version": INTENT_PROTOCOL_VERSION,
    "coverage_decision": "no_semantic_delta",
    "semantic_operations": [],
    "scope_binding_operation": None,
}


def intent_with_operation(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        "capability": CAPABILITY,
        "schema_version": INTENT_SCHEMA_VERSION,
        "protocol_version": INTENT_PROTOCOL_VERSION,
        "coverage_decision": "semantic_operations",
        "semantic_operations": [operation],
        "scope_binding_operation": None,
    }


SEMANTIC_OPERATION_FIXTURES = {
    "create": CREATE_INTENT,
    "revise": REVISE_INTENT,
    "confirm": intent_with_operation(
        semantic_operation(
            operation_kind="confirm",
            summary="",
            kind_payload={},
        )
    ),
    "resolve": intent_with_operation(
        semantic_operation(
            operation_kind="resolve",
            summary="",
            kind_payload={},
            reason_code="completed",
        )
    ),
    "supersede": intent_with_operation(
        semantic_operation(
            operation_kind="supersede",
            summary="",
            kind_payload={},
            reason_code="replaced",
            superseded_by_item_id=ITEM_TASK_SUCCESSOR,
        )
    ),
    "reopen": intent_with_operation(
        semantic_operation(
            operation_kind="reopen",
            item_id=ITEM_THREAD,
            expected_revision=2,
            item_kind="emotional_thread",
            summary="",
            kind_payload={},
            reason_code="participant_reopened",
        )
    ),
}

CAPABILITY_OFFER = {
    "schema_version": CAPABILITY_OFFER_SCHEMA_VERSION,
    "state": "offered",
    "protocol_version": INTENT_PROTOCOL_VERSION,
    "capability": CAPABILITY,
    "coverage_decision_required": True,
    "maximum_total_operations": 4,
    "expires_at": EXPIRES_AT,
}

CAPABILITY_UNAVAILABLE = {
    "schema_version": CAPABILITY_OFFER_SCHEMA_VERSION,
    "state": "unavailable",
    "protocol_version": INTENT_PROTOCOL_VERSION,
    "capability": None,
    "coverage_decision_required": False,
    "maximum_total_operations": 0,
    "expires_at": None,
}

INTENT_CAPABILITY_ISSUED = {
    "schema_version": CAPABILITY_SCHEMA_VERSION,
    "capability_id": CAPABILITY_ID,
    "creation_seed_sha256": synthetic_sha256("capability-creation-seed"),
    "capability_sha256": synthetic_sha256(CAPABILITY),
    "client_turn_id": CLIENT_TURN_ID,
    "room_id": ROOM_A,
    "provider_operation_id": PROVIDER_OPERATION_ID,
    "protocol_version": INTENT_PROTOCOL_VERSION,
    "command_context_id": CONTEXT_ID,
    "command_context_sha256": canonical_sha256(COMMAND_CONTEXT),
    "snapshot_global_event_sequence": 41,
    "snapshot_global_event_sha256": COMMAND_CONTEXT[
        "snapshot_global_event_sha256"
    ],
    "scope_binding_revision": 7,
    "coverage_binding_state": "pending_complete_unit",
    "covered_complete_unit_ids": [],
    "covered_complete_unit_sha256s": [],
    "state": "issued",
    "issued_at": TIMESTAMP,
    "expires_at": EXPIRES_AT,
    "consumed_at": None,
    "outbox_bundle_id": None,
    "terminal_response_sha256": None,
    "replay_attempt_count": 0,
}

OUTBOX_PREPARED = {
    "schema_version": OUTBOX_SCHEMA_VERSION,
    "bundle_id": BUNDLE_ID,
    "creation_seed_sha256": synthetic_sha256("outbox-creation-seed"),
    "capability_id": CAPABILITY_ID,
    "capability_sha256": synthetic_sha256(CAPABILITY),
    "client_turn_id": CLIENT_TURN_ID,
    "room_id": ROOM_A,
    "provider_operation_id": PROVIDER_OPERATION_ID,
    "protocol_version": INTENT_PROTOCOL_VERSION,
    "command_context_id": CONTEXT_ID,
    "command_context_sha256": canonical_sha256(COMMAND_CONTEXT),
    "snapshot_global_event_sequence": 41,
    "snapshot_global_event_sha256": COMMAND_CONTEXT[
        "snapshot_global_event_sha256"
    ],
    "scope_binding_revision": 7,
    "terminal_response_sha256": synthetic_sha256("terminal-response"),
    "visible_response_sha256": synthetic_sha256("visible-response"),
    "unit_binding_state": "pending_complete_unit",
    "covered_complete_unit_ids": [],
    "covered_complete_unit_sha256s": [],
    "coverage_decision": "semantic_operations",
    "normalized_semantic_operations": deepcopy(
        REVISE_INTENT["semantic_operations"]
    ),
    "normalized_scope_binding_operation": None,
    "command_bundle_sha256": synthetic_sha256("normalized-command-bundle"),
    "idempotency_identity": "outbox-command-stable-identity-001",
    "state": "prepared_waiting_visible",
    "application_attempt_count": 0,
    "next_retry_at": None,
    "last_error_code": None,
    "terminal_code": None,
    "working_set_receipt_ids": [],
    "coverage_receipt_ids": [],
    "prepared_at": TIMESTAMP,
    "visible_released_at": None,
    "applied_at": None,
    "updated_at": TIMESTAMP,
}
OUTBOX_PREPARED["command_bundle_sha256"] = canonical_sha256(
    {
        "command_context_id": OUTBOX_PREPARED["command_context_id"],
        "command_context_sha256": OUTBOX_PREPARED[
            "command_context_sha256"
        ],
        "snapshot_global_event_sequence": OUTBOX_PREPARED[
            "snapshot_global_event_sequence"
        ],
        "snapshot_global_event_sha256": OUTBOX_PREPARED[
            "snapshot_global_event_sha256"
        ],
        "scope_binding_revision": OUTBOX_PREPARED[
            "scope_binding_revision"
        ],
        "coverage_decision": OUTBOX_PREPARED["coverage_decision"],
        "normalized_semantic_operations": OUTBOX_PREPARED[
            "normalized_semantic_operations"
        ],
        "normalized_scope_binding_operation": OUTBOX_PREPARED[
            "normalized_scope_binding_operation"
        ],
    }
)
INTENT_CAPABILITY_PREPARED = deepcopy(INTENT_CAPABILITY_ISSUED)
INTENT_CAPABILITY_PREPARED.update(
    {
        "state": "prepared_consumed",
        "consumed_at": "2026-07-28T00:00:00.500Z",
        "outbox_bundle_id": BUNDLE_ID,
        "terminal_response_sha256": OUTBOX_PREPARED[
            "terminal_response_sha256"
        ],
    }
)


def outbox_fixture(state: str) -> dict[str, Any]:
    if state not in OUTBOX_STATES:
        raise ValueError(state)
    value = deepcopy(OUTBOX_PREPARED)
    value["state"] = state
    if state in {
        "ready_to_apply",
        "applying",
        "retryable_failure",
        "conflict_recorded",
        "applied",
    }:
        value["unit_binding_state"] = "bound"
        value["covered_complete_unit_ids"] = [COMPLETE_UNIT_ID]
        value["covered_complete_unit_sha256s"] = [
            synthetic_sha256("complete-unit-a-0001")
        ]
    if state in {
        "visible_released_waiting_unit",
        "ready_to_apply",
        "applying",
        "retryable_failure",
        "conflict_recorded",
        "applied",
    }:
        value["visible_released_at"] = "2026-07-28T00:00:01.000Z"
        value["updated_at"] = "2026-07-28T00:00:01.000Z"
    if state in {
        "applying",
        "retryable_failure",
        "conflict_recorded",
        "applied",
    }:
        value["application_attempt_count"] = 1
        value["updated_at"] = "2026-07-28T00:00:02.000Z"
    if state == "retryable_failure":
        value["next_retry_at"] = "2026-07-28T00:00:03.000Z"
        value["last_error_code"] = "working_set_unavailable"
    if state == "conflict_recorded":
        value["working_set_receipt_ids"] = ["working-set-conflict-receipt"]
        value["terminal_code"] = "authoritative_conflict"
    if state == "applied":
        value["working_set_receipt_ids"] = ["working-set-applied-receipt"]
        value["coverage_receipt_ids"] = ["coverage-applied-receipt"]
        value["terminal_code"] = "applied"
        value["applied_at"] = "2026-07-28T00:00:02.000Z"
    if state == "cancelled_before_visible":
        value["terminal_code"] = "cancelled_before_visible"
        value["updated_at"] = "2026-07-28T00:00:01.000Z"
    return value


OUTBOX_STATE_FIXTURES = {
    state: outbox_fixture(state) for state in OUTBOX_STATES
}

OUTBOX_TRANSITION_EDGE_FIXTURES = (
    {
        "from": None,
        "event": "atomic_prepare_before_visible",
        "to": "prepared_waiting_visible",
    },
    {
        "from": None,
        "event": "atomic_retry_after_visible",
        "to": "visible_released_waiting_unit",
    },
    {
        "from": "prepared_waiting_visible",
        "event": "visible_released",
        "to": "visible_released_waiting_unit",
    },
    {
        "from": "visible_released_waiting_unit",
        "event": "exact_unit_bound",
        "to": "ready_to_apply",
    },
    {"from": "ready_to_apply", "event": "lease", "to": "applying"},
    {
        "from": "applying",
        "event": "all_receipts_committed",
        "to": "applied",
    },
    {
        "from": "applying",
        "event": "infrastructure_failure",
        "to": "retryable_failure",
    },
    {"from": "retryable_failure", "event": "retry", "to": "applying"},
    {
        "from": "applying",
        "event": "authoritative_conflict_receipt",
        "to": "conflict_recorded",
    },
    {
        "from": "prepared_waiting_visible",
        "event": "visible_delivery_permanently_cancelled",
        "to": "cancelled_before_visible",
    },
)
for _edge in OUTBOX_TRANSITION_EDGE_FIXTURES:
    _edge["previous"] = (
        None
        if _edge["from"] is None
        else OUTBOX_STATE_FIXTURES[_edge["from"]]
    )
    _edge["candidate"] = OUTBOX_STATE_FIXTURES[_edge["to"]]

OUTBOX_TRANSITION_ADVERSARIAL_FIXTURES = tuple(
    {
        "from": edge["from"],
        "event": edge["event"],
        "previous": edge["previous"],
        "candidate": OUTBOX_STATE_FIXTURES[
            (
                "cancelled_before_visible"
                if edge["to"] != "cancelled_before_visible"
                else "prepared_waiting_visible"
            )
        ],
        "expected_error": "wrong_outbox_transition_target",
    }
    for edge in OUTBOX_TRANSITION_EDGE_FIXTURES
)

ASTEL_DIRECT_COMMAND = {
    "schema_version": ASTEL_COMMAND_SCHEMA_VERSION,
    "client_command_id": "astel-command-001",
    "client_turn_id": CLIENT_TURN_ID,
    "room_id": ROOM_A,
    "participant_id": "astel",
    "confirmation_mode": "direct_structured_action",
    "confirmation_capability": None,
    "operation_kind": "create",
    "item_id": None,
    "expected_revision": 0,
    "item_kind": "decision",
    "scope": PROJECT_SCOPE,
    "summary": "Keep Gate 0 synthetic and stop before runtime integration.",
    "kind_payload": {
        "decision_state": "accepted",
        "decision_scope": "project",
        "linked_item_ids": [],
    },
    "semantic_patch": {},
    "reason_code": None,
    "successor_item_id": None,
    "candidate_content_sha256": "",
    "idempotency_key": "astel-command-idempotency-001",
    "created_at": TIMESTAMP,
}
ASTEL_DIRECT_COMMAND["candidate_content_sha256"] = canonical_sha256(
    canonical_astel_semantic_command(ASTEL_DIRECT_COMMAND)
)


def astel_lifecycle_command(operation_kind: str) -> dict[str, Any]:
    command = {
        "schema_version": ASTEL_COMMAND_SCHEMA_VERSION,
        "client_command_id": f"astel-command-{operation_kind}-001",
        "client_turn_id": CLIENT_TURN_ID,
        "room_id": ROOM_A,
        "participant_id": "astel",
        "confirmation_mode": "direct_structured_action",
        "confirmation_capability": None,
        "operation_kind": operation_kind,
        "item_id": ITEM_TASK,
        "expected_revision": 3,
        "item_kind": None,
        "scope": None,
        "summary": None,
        "kind_payload": None,
        "semantic_patch": {},
        "reason_code": None,
        "successor_item_id": None,
        "candidate_content_sha256": "",
        "idempotency_key": f"astel-{operation_kind}-idempotency-001",
        "created_at": TIMESTAMP,
    }
    if operation_kind == "revise":
        command["item_kind"] = "active_task"
        command["semantic_patch"] = {
            "summary": "Astel's exact structured task revision."
        }
    elif operation_kind == "resolve":
        command["reason_code"] = "completed"
    elif operation_kind == "supersede":
        command["successor_item_id"] = ITEM_TASK_SUCCESSOR
    elif operation_kind == "abandon":
        command["reason_code"] = "no_longer_wanted"
    command["candidate_content_sha256"] = canonical_sha256(
        canonical_astel_semantic_command(command)
    )
    return command


ASTEL_LIFECYCLE_COMMANDS = {
    operation_kind: astel_lifecycle_command(operation_kind)
    for operation_kind in (
        "confirm",
        "revise",
        "resolve",
        "supersede",
        "reopen",
        "abandon",
    )
}

ASTEL_REVIEW_CAPABILITY_VALUE = "cac_" + ("A" * 43)
ASTEL_REVIEWED_COMMAND = deepcopy(ASTEL_DIRECT_COMMAND)
ASTEL_REVIEWED_COMMAND.update(
    {
        "client_command_id": "astel-command-reviewed-001",
        "confirmation_mode": "reviewed_candidate_confirmation",
        "confirmation_capability": ASTEL_REVIEW_CAPABILITY_VALUE,
        "idempotency_key": "astel-reviewed-idempotency-001",
    }
)
ASTEL_REVIEWED_COMMAND["candidate_content_sha256"] = canonical_sha256(
    canonical_astel_semantic_command(ASTEL_REVIEWED_COMMAND)
)

ASTEL_CONFIRMATION_CAPABILITY = {
    "schema_version": ASTEL_CONFIRMATION_SCHEMA_VERSION,
    "confirmation_capability_id": "cwaconf_" + ("a" * 32),
    "creation_seed_sha256": synthetic_sha256(
        "astel-confirmation-capability-seed"
    ),
    "capability_sha256": synthetic_sha256(ASTEL_REVIEW_CAPABILITY_VALUE),
    "candidate_content_sha256": ASTEL_REVIEWED_COMMAND[
        "candidate_content_sha256"
    ],
    "canonical_candidate": canonical_astel_semantic_command(
        ASTEL_REVIEWED_COMMAND
    ),
    "client_turn_id": CLIENT_TURN_ID,
    "room_id": ROOM_A,
    "target_item_id": None,
    "target_revision": 0,
    "create_scope": PROJECT_SCOPE,
    "state": "issued",
    "issued_at": TIMESTAMP,
    "expires_at": EXPIRES_AT,
    "consumed_at": None,
    "replay_attempt_count": 0,
}

JOINT_ATTESTATION = {
    "schema_version": JOINT_ATTESTATION_SCHEMA_VERSION,
    "attestation_id": "cws_jat_" + ("1" * 32),
    "creation_seed_sha256": synthetic_sha256("joint-attestation-seed"),
    "item_id": ITEM_TASK,
    "expected_revision": 3,
    "canonical_semantic_sha256": synthetic_sha256("joint-semantics"),
    "scope_sha256": canonical_sha256(PROJECT_SCOPE),
    "astel_evidence": {
        "evidence_id": "astel-evidence-001",
        "event_id": "cws_evt_" + ("1" * 32),
        "participant": "astel",
        "content_sha256": synthetic_sha256("joint-semantics"),
    },
    "solen_evidence": {
        "evidence_id": "solen-evidence-001",
        "event_id": "cws_evt_" + ("2" * 32),
        "participant": "solen",
        "content_sha256": synthetic_sha256("joint-semantics"),
    },
    "idempotency_key": "joint-attestation-idempotency-001",
    "created_at": TIMESTAMP,
}


def coverage_fixture(state: str) -> dict[str, Any]:
    safe = state in {
        "participant_semantic_coverage",
        "structured_semantic_coverage",
        "solen_no_semantic_delta",
        "verified_exact_history_survival",
    }
    return {
        "schema_version": UNIT_COVERAGE_SCHEMA_VERSION,
        "coverage_id": "cws_cov_" + canonical_sha256(state)[:32],
        "creation_seed_sha256": synthetic_sha256(f"coverage-seed-{state}"),
        "room_id": ROOM_A,
        "complete_unit_id": COMPLETE_UNIT_ID,
        "complete_unit_sha256": synthetic_sha256("complete-unit-a-0001"),
        "coverage_state": state,
        "authority_refs": [f"coverage-authority-{state}"] if safe else [],
        "exact_survival_ref": (
            synthetic_sha256("exact-survival-receipt")
            if state == "verified_exact_history_survival"
            else None
        ),
        "coverage_finalized": safe,
        "safe_for_source_eviction": safe,
        "snapshot_global_event_sequence": 41,
        "created_at": TIMESTAMP,
    }


def application_fence(
    *,
    relation: str,
    outcome: str,
    exact_fallback_state: str,
) -> dict[str, Any]:
    fallback_available = exact_fallback_state == "available"
    current_room = ROOM_A if relation == "same_room" else ROOM_B
    return {
        "schema_version": APPLICATION_FENCE_SCHEMA_VERSION,
        "fence_id": "cws_fence_"
        + canonical_sha256(
            [relation, outcome, exact_fallback_state]
        )[:32],
        "creation_seed_sha256": synthetic_sha256(
            f"fence-{relation}-{outcome}-{exact_fallback_state}"
        ),
        "room_relation": relation,
        "current_room_id": current_room,
        "current_client_turn_id": (
            NEXT_CLIENT_TURN_ID
            if relation == "same_room"
            else FRESH_CLIENT_TURN_ID
        ),
        "prior_room_id": ROOM_A,
        "prior_client_turn_id": CLIENT_TURN_ID,
        "prior_provider_operation_id": PROVIDER_OPERATION_ID,
        "continuity_outcome": outcome,
        "outbox_bundle_id": (
            BUNDLE_ID
            if outcome
            in {
                "pending_preparation_or_application",
                "applied",
                "conflict_or_rejected",
            }
            else None
        ),
        "working_set_receipt_ids": (
            ["working-set-receipt-001"]
            if outcome in {"applied", "conflict_or_rejected"}
            else []
        ),
        "coverage_receipt_ids": (
            ["coverage-receipt-001"] if outcome == "applied" else []
        ),
        "exact_fallback": {
            "state": exact_fallback_state,
            "owner_code": (
                "house_complete_continuity_unit_v1"
                if fallback_available
                else None
            ),
            "complete_unit_id": COMPLETE_UNIT_ID if fallback_available else None,
            "complete_unit_sha256": (
                synthetic_sha256("complete-unit-a-0001")
                if fallback_available
                else None
            ),
            "exact_body_included": False,
        },
        "selection_requires_prior_authored_state": True,
        "maximum_local_wait_millis": 750,
    }


FENCE_SCENARIOS = {
    "immediate_second_turn": {
        "fence": application_fence(
            relation="same_room",
            outcome="pending_preparation_or_application",
            exact_fallback_state="available",
        ),
        "post_wait_outcome": None,
        "wait_millis": 0,
        "expected_behavior": "same_room_exact_recent_fallback",
    },
    "abrupt_window_switch": {
        "fence": application_fence(
            relation="fresh_room",
            outcome="pending_preparation_or_application",
            exact_fallback_state="available",
        ),
        "post_wait_outcome": None,
        "wait_millis": 0,
        "expected_behavior": "fresh_room_exact_predecessor_fallback",
    },
    "delayed_outbox_application": {
        "fence": application_fence(
            relation="fresh_room",
            outcome="pending_preparation_or_application",
            exact_fallback_state="missing",
        ),
        "post_wait_outcome": None,
        "wait_millis": 0,
        "expected_behavior": "provisional_handoff_pending",
    },
    "crash_restart_recovery": {
        "fence": application_fence(
            relation="fresh_room",
            outcome="pending_preparation_or_application",
            exact_fallback_state="available",
        ),
        "post_wait_outcome": "applied",
        "wait_millis": 500,
        "expected_behavior": "applied_working_set",
    },
    "conflict": {
        "fence": application_fence(
            relation="fresh_room",
            outcome="conflict_or_rejected",
            exact_fallback_state="not_needed",
        ),
        "post_wait_outcome": None,
        "wait_millis": 0,
        "expected_behavior": "conflict_or_rejected_state",
    },
    "missing_exact_fallback": {
        "fence": application_fence(
            relation="fresh_room",
            outcome="pending_preparation_or_application",
            exact_fallback_state="unavailable",
        ),
        "post_wait_outcome": None,
        "wait_millis": 0,
        "expected_behavior": "authoritative_unavailable",
    },
    "eventual_idempotent_convergence": {
        "fence": application_fence(
            relation="fresh_room",
            outcome="pending_preparation_or_application",
            exact_fallback_state="missing",
        ),
        "post_wait_outcome": "applied",
        "wait_millis": 750,
        "expected_behavior": "applied_working_set",
    },
}
for _fence_case in FENCE_SCENARIOS.values():
    if _fence_case["post_wait_outcome"] == "applied":
        _fence_case["post_wait_outbox_bundle_id"] = BUNDLE_ID
        _fence_case["post_wait_working_set_receipt_ids"] = [
            "working-set-receipt-post-wait"
        ]
        _fence_case["post_wait_coverage_receipt_ids"] = [
            "coverage-receipt-post-wait"
        ]
    else:
        _fence_case["post_wait_outbox_bundle_id"] = None
        _fence_case["post_wait_working_set_receipt_ids"] = None
        _fence_case["post_wait_coverage_receipt_ids"] = None

_SEMANTIC_BYTES = b"synthetic semantic stable surface v1"
_MESSAGE_BYTES = b'[{"role":"developer","content":"synthetic stable"}]'
_TOOL_BYTES = b'[{"name":"tool_b"},{"name":"tool_a"}]'
GENERATION_IDENTITY_EVIDENCE = {
    "schema_version": GENERATION_IDENTITY_SCHEMA_VERSION,
    "evidence_scope": "synthetic_gate0_contract",
    "generation": "house_standing_root_v2_generation_2",
    "profile": "house_prompt_cache_standing_root_v2_prefix_v1",
    "canonical_semantic_stable_surface": {
        "utf8_bytes": len(_SEMANTIC_BYTES),
        "sha256": synthetic_sha256(_SEMANTIC_BYTES.decode("ascii")),
    },
    "serialized_stable_messages": {
        "utf8_bytes": len(_MESSAGE_BYTES),
        "sha256": synthetic_sha256(_MESSAGE_BYTES.decode("ascii")),
    },
    "serialized_tool_block": {
        "utf8_bytes": len(_TOOL_BYTES),
        "sha256": synthetic_sha256(_TOOL_BYTES.decode("ascii")),
        "tool_count": 2,
    },
    "house_cache_signature": {
        "algorithm": "house_cache_signature_v1",
        "value": "",
    },
    "semantic_equality_proves_wire_byte_equality": False,
    "tool_order_preserved": True,
    "tool_order_normalized": False,
    "provider_call_made": False,
    "prefix_generation_2_generated": False,
}
GENERATION_IDENTITY_EVIDENCE["house_cache_signature"]["value"] = (
    derived_house_cache_signature(
        generation=GENERATION_IDENTITY_EVIDENCE["generation"],
        profile=GENERATION_IDENTITY_EVIDENCE["profile"],
        semantic_sha256=GENERATION_IDENTITY_EVIDENCE[
            "canonical_semantic_stable_surface"
        ]["sha256"],
        stable_messages_sha256=GENERATION_IDENTITY_EVIDENCE[
            "serialized_stable_messages"
        ]["sha256"],
        tool_block_sha256=GENERATION_IDENTITY_EVIDENCE[
            "serialized_tool_block"
        ]["sha256"],
        tool_count=GENERATION_IDENTITY_EVIDENCE["serialized_tool_block"][
            "tool_count"
        ],
    )
)

UNICODE_CANONICAL_EQUIVALENCE_FIXTURE = {
    "nfc_utf8_hex": "Café review.".encode("utf-8").hex(),
    "nfd_utf8_hex": "Cafe\u0301 review.".encode("utf-8").hex(),
    "accepted_normalization": "NFC",
    "nfc_semantic_sha256": canonical_sha256("Café review."),
    "nfd_must_be_rejected_before_hashing": True,
    "unpaired_surrogate_code_point": 0xD800,
}


def adversarial_fixtures() -> dict[str, dict[str, Any]]:
    fixtures: dict[str, dict[str, Any]] = {}

    stale_snapshot = deepcopy(REVISE_INTENT)
    fixtures["stale_snapshot"] = {
        "validator": "intent_against_context",
        "value": stale_snapshot,
        "current_snapshot_sequence": 42,
        "expected_error": "stale_command_context_snapshot",
    }
    fixtures["stale_scope_binding"] = {
        "validator": "intent_against_context",
        "value": deepcopy(REVISE_INTENT),
        "current_binding_revision": 8,
        "expected_error": "stale_scope_binding_revision",
    }
    wrong_revision = deepcopy(REVISE_INTENT)
    wrong_revision["semantic_operations"][0]["expected_revision"] = 2
    fixtures["wrong_revision"] = {
        "validator": "intent_against_context",
        "value": wrong_revision,
        "expected_error": "wrong_item_revision",
    }
    unoffered_item = deepcopy(REVISE_INTENT)
    unoffered_item["semantic_operations"][0]["item_id"] = ITEM_UNKNOWN
    fixtures["unoffered_item"] = {
        "validator": "intent_against_context",
        "value": unoffered_item,
        "expected_error": "unoffered_item",
    }
    unoffered_operation = deepcopy(REVISE_INTENT)
    unoffered_operation["semantic_operations"][0][
        "operation_kind"
    ] = "reopen"
    unoffered_operation["semantic_operations"][0][
        "operation_key"
    ] = "op-reopen-001"
    unoffered_operation["semantic_operations"][0]["summary"] = ""
    unoffered_operation["semantic_operations"][0]["kind_payload"] = {}
    unoffered_operation["semantic_operations"][0][
        "reason_code"
    ] = "participant_reopened"
    fixtures["unoffered_operation"] = {
        "validator": "intent_against_context",
        "value": unoffered_operation,
        "expected_error": "unoffered_operation",
    }
    unoffered_scope = deepcopy(CREATE_INTENT)
    unoffered_scope["semantic_operations"][0]["scope"] = ROOM_SCOPE
    fixtures["unoffered_scope"] = {
        "validator": "intent_against_context",
        "value": unoffered_scope,
        "expected_error": "unoffered_create_scope",
    }
    task_with_question_payload = deepcopy(REVISE_INTENT)
    task_with_question_payload["semantic_operations"][0][
        "kind_payload"
    ] = {"question_state": "open"}
    fixtures["active_task_with_question_payload"] = {
        "validator": "continuity_intent",
        "value": task_with_question_payload,
        "expected_error": "invalid_kind_payload_fields",
    }
    confirm_changes_summary = deepcopy(REVISE_INTENT)
    confirm_changes_summary["semantic_operations"][0].update(
        {
            "operation_kind": "confirm",
            "operation_key": "op-confirm-changing-summary",
            "kind_payload": {},
        }
    )
    fixtures["confirm_changes_summary"] = {
        "validator": "continuity_intent",
        "value": confirm_changes_summary,
        "expected_error": "confirm_semantic_rewrite_forbidden",
    }
    resolve_changes_payload = deepcopy(REVISE_INTENT)
    resolve_changes_payload["semantic_operations"][0].update(
        {
            "operation_kind": "resolve",
            "operation_key": "op-resolve-changing-payload",
            "summary": "",
            "kind_payload": {"task_state": "in_progress"},
            "reason_code": "completed",
        }
    )
    fixtures["resolve_changes_payload"] = {
        "validator": "continuity_intent",
        "value": resolve_changes_payload,
        "expected_error": "resolve_semantic_rewrite_forbidden",
    }
    duplicate_keys = deepcopy(REVISE_INTENT)
    second_operation = semantic_operation(
        item_id=ITEM_TASK_SUCCESSOR,
        expected_revision=1,
        summary="Correct the successor fixture.",
    )
    second_operation["operation_key"] = duplicate_keys["semantic_operations"][
        0
    ]["operation_key"]
    duplicate_keys["semantic_operations"].append(second_operation)
    fixtures["duplicate_operation_keys"] = {
        "validator": "continuity_intent",
        "value": duplicate_keys,
        "expected_error": "duplicate_operation_key",
    }
    duplicate_scopes = deepcopy(COMMAND_CONTEXT)
    duplicate_offer = deepcopy(duplicate_scopes["create_offers"][0])
    duplicate_offer["offer_id"] = "cws_offer_" + ("2" * 32)
    duplicate_scopes["create_offers"].append(duplicate_offer)
    fixtures["duplicate_create_scopes"] = {
        "validator": "command_context",
        "value": duplicate_scopes,
        "expected_error": "duplicate_create_scope",
    }
    duplicate_offer_ids = deepcopy(COMMAND_CONTEXT)
    second_offer = deepcopy(duplicate_offer_ids["create_offers"][0])
    second_offer["scope"] = ROOM_SCOPE
    duplicate_offer_ids["create_offers"].append(second_offer)
    fixtures["duplicate_offer_ids"] = {
        "validator": "command_context",
        "value": duplicate_offer_ids,
        "expected_error": "duplicate_offer_id",
    }
    stale_item_hash = deepcopy(COMMAND_CONTEXT)
    stale_item_hash["items"][0]["summary"] = (
        "Altered summary with the old provider-offered content digest."
    )
    fixtures["command_context_stale_item_content_hash"] = {
        "validator": "command_context",
        "value": stale_item_hash,
        "expected_error": "command_context_content_sha256_mismatch",
    }
    incompatible_supersede_context = deepcopy(COMMAND_CONTEXT)
    incompatible_supersede_context["items"][0][
        "offered_successor_item_ids"
    ] = [ITEM_THREAD]
    fixtures["supersede_incompatible_offered_item"] = {
        "validator": "command_context",
        "value": incompatible_supersede_context,
        "expected_error": "incompatible_successor",
    }
    solen_tool_result_create = deepcopy(CREATE_INTENT)
    solen_tool_result_create["semantic_operations"][0].update(
        {
            "item_kind": "completed_tool_result_ref",
            "kind_payload": {
                "task_item_id": ITEM_TASK,
                "operation_ref": "operation-completed-001",
                "operation_state": "completed",
                "result_summary": "Bounded synthetic tool result.",
                "result_ref_sha256": synthetic_sha256(
                    "bounded-tool-result-reference"
                ),
            },
        }
    )
    fixtures["solen_creates_completed_tool_result_ref"] = {
        "validator": "continuity_intent",
        "value": solen_tool_result_create,
        "expected_error": "solen_completed_tool_result_create_forbidden",
    }
    too_many_items = deepcopy(COMMAND_CONTEXT)
    too_many_items["items"] = [
        {
            **deepcopy(COMMAND_CONTEXT["items"][0]),
            "item_id": "cws_item_" + f"{index:032x}",
        }
        for index in range(1, 10)
    ]
    fixtures["more_than_eight_items"] = {
        "validator": "command_context",
        "value": too_many_items,
        "expected_error": "invalid_items",
    }
    for field in (
        "memory_body",
        "vault_body",
        "self_state_body",
        "raw_history",
        "exact_quote",
        "tool_permission",
        "secret",
    ):
        unsafe = deepcopy(COMMAND_CONTEXT)
        unsafe[field] = "forbidden"
        fixtures[f"forbidden_{field}"] = {
            "validator": "command_context",
            "value": unsafe,
            "expected_error": "forbidden_field",
        }
    minted_authorship = deepcopy(REVISE_INTENT)
    minted_authorship["authorship_kind"] = "astel_explicit"
    fixtures["solen_mints_astel_authorship"] = {
        "validator": "continuity_intent",
        "value": minted_authorship,
        "expected_error": "invalid_continuity_intent_fields",
    }
    minted_joint = deepcopy(REVISE_INTENT)
    minted_joint["authorship_kind"] = "joint_explicit"
    minted_joint["author_participants"] = ["astel", "solen"]
    fixtures["solen_mints_joint_authorship"] = {
        "validator": "continuity_intent",
        "value": minted_joint,
        "expected_error": "invalid_continuity_intent_fields",
    }
    no_delta_with_item = deepcopy(REVISE_INTENT)
    no_delta_with_item["coverage_decision"] = "no_semantic_delta"
    fixtures["no_delta_with_operations"] = {
        "validator": "continuity_intent",
        "value": no_delta_with_item,
        "expected_error": "no_delta_with_operations",
    }
    changed_astel_candidate = deepcopy(ASTEL_DIRECT_COMMAND)
    changed_astel_candidate["summary"] = "Changed candidate bytes."
    fixtures["astel_candidate_digest_mismatch"] = {
        "validator": "astel_explicit_command",
        "value": changed_astel_candidate,
        "expected_error": "candidate_content_sha256_mismatch",
    }
    changed_confirmation_candidate = deepcopy(ASTEL_CONFIRMATION_CAPABILITY)
    changed_confirmation_candidate["canonical_candidate"][
        "summary"
    ] = "Changed reviewed bytes."
    fixtures["review_capability_candidate_mismatch"] = {
        "validator": "astel_confirmation_capability",
        "value": changed_confirmation_candidate,
        "expected_error": "candidate_content_sha256_mismatch",
    }
    impossible_date = deepcopy(ASTEL_DIRECT_COMMAND)
    impossible_date["created_at"] = "2026-02-30T00:00:00.000Z"
    fixtures["impossible_utc_date"] = {
        "validator": "astel_explicit_command",
        "value": impossible_date,
        "expected_error": "invalid_created_at",
    }
    for outbox_state, valid_outbox in OUTBOX_STATE_FIXTURES.items():
        invalid_outbox = deepcopy(valid_outbox)
        if outbox_state == "prepared_waiting_visible":
            invalid_outbox["visible_released_at"] = (
                "2026-07-28T00:00:01.000Z"
            )
        elif outbox_state == "visible_released_waiting_unit":
            invalid_outbox["working_set_receipt_ids"] = ["false-receipt"]
        elif outbox_state == "ready_to_apply":
            invalid_outbox["unit_binding_state"] = "pending_complete_unit"
            invalid_outbox["covered_complete_unit_ids"] = []
            invalid_outbox["covered_complete_unit_sha256s"] = []
        elif outbox_state == "applying":
            invalid_outbox["application_attempt_count"] = 0
        elif outbox_state == "retryable_failure":
            invalid_outbox["next_retry_at"] = None
        elif outbox_state == "conflict_recorded":
            invalid_outbox["working_set_receipt_ids"] = []
        elif outbox_state == "applied":
            invalid_outbox["coverage_receipt_ids"] = []
        else:
            invalid_outbox["visible_released_at"] = (
                "2026-07-28T00:00:01.000Z"
            )
        fixtures[f"outbox_{outbox_state}_contradiction"] = {
            "validator": "outbox_bundle",
            "value": invalid_outbox,
            "expected_error": (
                "outbox_bound_unit_required"
                if outbox_state == "ready_to_apply"
                else "invalid_outbox_state_invariants"
            ),
        }
    applied_without_receipts = application_fence(
        relation="fresh_room",
        outcome="applied",
        exact_fallback_state="not_needed",
    )
    applied_without_receipts["working_set_receipt_ids"] = []
    applied_without_receipts["coverage_receipt_ids"] = []
    fixtures["fence_applied_without_receipts"] = {
        "validator": "application_fence",
        "value": applied_without_receipts,
        "expected_error": "contradictory_application_fence",
    }
    false_wire_claim = deepcopy(GENERATION_IDENTITY_EVIDENCE)
    false_wire_claim["semantic_equality_proves_wire_byte_equality"] = True
    fixtures["semantic_equality_claims_wire_equality"] = {
        "validator": "generation_identity",
        "value": false_wire_claim,
        "expected_error": (
            "invalid_semantic_equality_proves_wire_byte_equality"
        ),
    }
    normalized_tools = deepcopy(GENERATION_IDENTITY_EVIDENCE)
    normalized_tools["tool_order_preserved"] = False
    normalized_tools["tool_order_normalized"] = True
    fixtures["tool_order_normalized"] = {
        "validator": "generation_identity",
        "value": normalized_tools,
        "expected_error": "invalid_tool_order_normalized",
    }
    pending_as_truth = application_fence(
        relation="fresh_room",
        outcome="pending_preparation_or_application",
        exact_fallback_state="missing",
    )
    pending_as_truth["pending_commands_selected_as_truth"] = True
    fixtures["pending_selected_as_truth"] = {
        "validator": "application_fence",
        "value": pending_as_truth,
        "expected_error": "invalid_application_fence_fields",
    }
    global_digest = deepcopy(pending_as_truth)
    global_digest.pop("pending_commands_selected_as_truth")
    global_digest["global_newest_digest_used"] = True
    fixtures["global_newest_digest_substitution"] = {
        "validator": "application_fence",
        "value": global_digest,
        "expected_error": "invalid_application_fence_fields",
    }
    return fixtures


POSITIVE_FIXTURE_BUNDLE = {
    "command_context": COMMAND_CONTEXT,
    "item_kind_payloads": ITEM_KIND_PAYLOAD_FIXTURES,
    "semantic_operation_fixtures": SEMANTIC_OPERATION_FIXTURES,
    "revise_intent": REVISE_INTENT,
    "create_intent": CREATE_INTENT,
    "no_delta_intent": NO_DELTA_INTENT,
    "capability_offer": CAPABILITY_OFFER,
    "capability_unavailable": CAPABILITY_UNAVAILABLE,
    "intent_capability_issued": INTENT_CAPABILITY_ISSUED,
    "intent_capability_prepared": INTENT_CAPABILITY_PREPARED,
    "outbox_prepared": OUTBOX_PREPARED,
    "outbox_states": OUTBOX_STATE_FIXTURES,
    "outbox_transition_edges": OUTBOX_TRANSITION_EDGE_FIXTURES,
    "astel_direct_command": ASTEL_DIRECT_COMMAND,
    "astel_lifecycle_commands": ASTEL_LIFECYCLE_COMMANDS,
    "astel_reviewed_command": ASTEL_REVIEWED_COMMAND,
    "astel_confirmation_capability": ASTEL_CONFIRMATION_CAPABILITY,
    "joint_attestation": JOINT_ATTESTATION,
    "safe_no_delta_coverage": coverage_fixture("solen_no_semantic_delta"),
    "unsafe_missing_authorship_coverage": coverage_fixture(
        "authorship_not_supplied"
    ),
    "fence_scenarios": FENCE_SCENARIOS,
    "generation_identity_evidence": GENERATION_IDENTITY_EVIDENCE,
    "unicode_canonical_equivalence": UNICODE_CANONICAL_EQUIVALENCE_FIXTURE,
    "executable_dependency_fixtures": POSITIVE_DEPENDENCY_FIXTURES,
    "event_chain_fixtures": EVENT_CHAIN_FIXTURES,
    "terminal_private_tail_fixtures": TERMINAL_PRIVATE_TAIL_FIXTURES,
    "terminal_fixture_bundle_sha256": TERMINAL_FIXTURE_BUNDLE_SHA256,
    "gate0_conformance_ledger": GATE0_CONFORMANCE_LEDGER,
    "gate1_carry_forward_obligations": GATE1_CARRY_FORWARD_OBLIGATIONS,
    "gate2_carry_forward_obligations": GATE2_CARRY_FORWARD_OBLIGATIONS,
}

MACHINE_READABLE_CONTRACT_BUNDLE = {
    "matrices": contract_matrix_bundle(),
    "positive_fixtures": POSITIVE_FIXTURE_BUNDLE,
    "adversarial_fixtures": adversarial_fixtures(),
    "adversarial_dependency_fixtures": ADVERSARIAL_DEPENDENCY_FIXTURES,
    "adversarial_outbox_transition_fixtures": (
        OUTBOX_TRANSITION_ADVERSARIAL_FIXTURES
    ),
    "closure_adversarial_fixtures": CLOSURE_ADVERSARIAL_FIXTURES,
    "conformance_ledger": GATE0_CONFORMANCE_LEDGER,
    "gate1_carry_forward_obligations": GATE1_CARRY_FORWARD_OBLIGATIONS,
    "gate2_carry_forward_obligations": GATE2_CARRY_FORWARD_OBLIGATIONS,
}

# Locked after the focused fixture suite validates all normalized values.
EXPECTED_HASHES = {
    "contract_matrices": (
        "9c24db250326b8179a2aec5cb6304e123e39feff2a6a7af414b4f81076113bd9"
    ),
    "positive_fixtures": (
        "a9c1e85fab56b01c793bbab237204bb5f40fcfffe4e923311ccb58c7671e0ce6"
    ),
    "adversarial_fixtures": (
        "2c59d2ef48aa930efc3519af4d75e000be0c4c9c15dac22449e628878844cfdf"
    ),
    "adversarial_dependency_fixtures": (
        "b82b739d2df38430e1783d44a7b1d64067dd27553810a731b5e4c32d6bd5df40"
    ),
    "adversarial_outbox_transition_fixtures": (
        "6c714a07b9574c61e5ea01a8a36b958a5e61f0fe6a3b4a582747a4493f7000a9"
    ),
    "closure_adversarial_fixtures": (
        "7a8f26b7a7ddd692d41a10c8cb73736c33540d8145a968827341b582c296eb82"
    ),
    "conformance_ledger": (
        "efa16ea04b97af861fb4096a6f0440b7da6edfd2620e29cf4fa6249595f7c423"
    ),
    "complete_gate0_bundle": (
        "6930487bc827a383c072bef3c726d153f2bea28bf7ebc74052dd7b2464898129"
    ),
}


def computed_hashes() -> dict[str, str]:
    return {
        "contract_matrices": canonical_sha256(
            MACHINE_READABLE_CONTRACT_BUNDLE["matrices"]
        ),
        "positive_fixtures": canonical_sha256(
            MACHINE_READABLE_CONTRACT_BUNDLE["positive_fixtures"]
        ),
        "adversarial_fixtures": canonical_sha256(
            MACHINE_READABLE_CONTRACT_BUNDLE["adversarial_fixtures"]
        ),
        "adversarial_dependency_fixtures": canonical_sha256(
            MACHINE_READABLE_CONTRACT_BUNDLE[
                "adversarial_dependency_fixtures"
            ]
        ),
        "adversarial_outbox_transition_fixtures": canonical_sha256(
            MACHINE_READABLE_CONTRACT_BUNDLE[
                "adversarial_outbox_transition_fixtures"
            ]
        ),
        "closure_adversarial_fixtures": canonical_sha256(
            MACHINE_READABLE_CONTRACT_BUNDLE[
                "closure_adversarial_fixtures"
            ]
        ),
        "conformance_ledger": canonical_sha256(
            MACHINE_READABLE_CONTRACT_BUNDLE["conformance_ledger"]
        ),
        "complete_gate0_bundle": canonical_sha256(
            MACHINE_READABLE_CONTRACT_BUNDLE
        ),
    }


__all__ = [
    "ADVERSARIAL_FIXTURES",
    "COMMAND_CONTEXT",
    "CREATE_INTENT",
    "EXPECTED_HASHES",
    "FENCE_SCENARIOS",
    "GATE0_CONFORMANCE_LEDGER",
    "GATE1_CARRY_FORWARD_OBLIGATIONS",
    "GATE2_CARRY_FORWARD_OBLIGATIONS",
    "GENERATION_IDENTITY_EVIDENCE",
    "MACHINE_READABLE_CONTRACT_BUNDLE",
    "NO_DELTA_INTENT",
    "POSITIVE_FIXTURE_BUNDLE",
    "REVISE_INTENT",
    "adversarial_fixtures",
    "application_fence",
    "computed_hashes",
    "coverage_fixture",
]

ADVERSARIAL_FIXTURES = MACHINE_READABLE_CONTRACT_BUNDLE[
    "adversarial_fixtures"
]
