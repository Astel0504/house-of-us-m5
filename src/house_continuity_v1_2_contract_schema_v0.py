"""Registry, matrices, and compatibility exports for Continuity V1.2 Gate 0.

Executable validators live in the private contract-family modules behind
``house_continuity_v1_2_executable_contracts_v0``. This historical owner keeps
its registry and machine-readable matrices without shadow validator bodies.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from house_continuity_v1_2_executable_contracts_v0 import (
    APPLICATION_FENCE_RECEIPT_SCHEMA_VERSION,
    APPLICATION_FENCE_SCHEMA_VERSION,
    ASTEL_COMMAND_SCHEMA_VERSION,
    ASTEL_CONFIRMATION_SCHEMA_VERSION,
    CAPABILITY_OFFER_SCHEMA_VERSION,
    CAPABILITY_SCHEMA_VERSION,
    COMMANDABLE_OPERATION_KINDS,
    COMMAND_CONTEXT_AUTHORITY,
    COMMAND_CONTEXT_MAX_BINDING_CHOICES,
    COMMAND_CONTEXT_MAX_CREATE_OFFERS,
    COMMAND_CONTEXT_MAX_ITEMS,
    COMMAND_CONTEXT_MAX_UTF8_BYTES,
    COMMAND_CONTEXT_SCHEMA_VERSION,
    CONTEXTUAL_RESTATEMENT_CANONICALIZATION_CODE,
    FALSE_SCOPE_CONFLICT_CANONICALIZATION_CODE,
    COVERAGE_EVICTION_MATRIX,
    EXECUTABLE_SCHEMA_VERSIONS,
    GENERATION_IDENTITY_SCHEMA_VERSION,
    HouseContinuityV12ContractError,
    INTENT_PROTOCOL_VERSION,
    INTENT_SCHEMA_VERSION,
    ITEM_KINDS,
    JOINT_ATTESTATION_SCHEMA_VERSION,
    LIFECYCLE_STATES,
    MAX_COMPLETE_UNIT_IDS,
    MAX_RECEIPT_IDS,
    MAX_TOTAL_OPERATIONS,
    NO_DELTA_CANONICALIZATION_CODES,
    OUTBOX_SCHEMA_VERSION,
    PROVISIONAL_BINDING_CHOICES,
    LEGACY_FALSE_SCOPE_CANONICALIZATION_CODE,
    SCOPE_KINDS,
    SEMANTIC_NOVELTY_COMPARISON_VERSION,
    SEMANTIC_NOVELTY_EVIDENCE_SCHEMA_VERSION,
    SEMANTIC_NOVELTY_MARKER_NAMESPACE,
    SEMANTIC_NOVELTY_MARKER_VERSION,
    SEMANTIC_NOVELTY_POLICY_FIELD,
    SEMANTIC_NOVELTY_POLICY_VERSION,
    SEMANTIC_EVALUATION_FIELD,
    SEMANTIC_EVALUATION_SCHEMA_VERSION,
    SEMANTIC_EVALUATION_REQUEST_SCHEMA_VERSION,
    SEMANTIC_EVALUATION_RELATIONS,
    AUTHORITATIVE_REAFFIRMATION_CANONICALIZATION_CODE,
    authoritative_projection_sha256,
    validate_semantic_evaluation_request,
    CANONICALIZATION_MARKER_COMPATIBILITY,
    SEMANTIC_OPERATION_KINDS,
    SUMMARY_MAX_CHARS,
    UNIT_COVERAGE_SCHEMA_VERSION,
    canonical_astel_semantic_command,
    canonical_json_bytes,
    canonical_sha256,
    decide_application_fence,
    derived_house_cache_signature,
    validate_application_fence,
    validate_astel_confirmation_capability,
    validate_astel_explicit_command,
    validate_astel_reviewed_command_against_capability,
    validate_capability_offer,
    validate_command_context,
    validate_complete_continuity_unit,
    validate_continuity_intent,
    validate_creation_seed_collision,
    validate_creation_seed_registry,
    validate_event_chains,
    validate_exact_anchor_ref,
    validate_exact_outbox_retry,
    validate_generation_identity_evidence,
    validate_intent_against_capability,
    validate_intent_against_context,
    validate_intent_capability,
    is_no_delta_canonicalization,
    validate_item_kind_payload,
    validate_joint_attestation,
    validate_outbox_against_capability,
    validate_outbox_bundle,
    validate_outbox_transition,
    validate_scope_binding,
    validate_scope_binding_event,
    validate_unit_coverage,
    validate_working_set_event,
    validate_working_set_item,
)

GATE_ID = "HOUSE_CONTINUITY_V1_2_CONTRACT_FIXTURES"
MODULE_SCHEMA_VERSION = "house_continuity_v1_2_contract_schema_v0"
MAX_SOURCE_PROPOSAL_IDS = 8
MAX_LOCAL_RECONCILIATION_WAIT_MILLIS = 1_000
TARGET_OPERATION_KINDS = (
    "confirm",
    "revise",
    "resolve",
    "supersede",
    "reopen",
)
COVERAGE_DECISIONS = ("semantic_operations", "no_semantic_delta")
APPLICATION_FENCE_OUTCOMES = (
    "applied",
    "no_carrier_or_closed_unused",
    "pending_preparation_or_application",
    "conflict_or_rejected",
    "unavailable",
)
EXACT_FALLBACK_STATES = ("not_needed", "available", "missing", "unavailable")
FENCE_ROOM_RELATIONS = ("same_room", "fresh_room")


def synthetic_sha256(label: str) -> str:
    if not isinstance(label, str) or not label:
        raise HouseContinuityV12ContractError(
            "invalid_synthetic_label",
            "Synthetic hash labels must be non-empty strings.",
        )
    return hashlib.sha256(label.encode("utf-8")).hexdigest()

APPROVED_SCHEMA_REGISTRY = (
    {
        "schema_version": "house_continuity_scope_binding_v1",
        "authority_class": "scope_binding",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_creation_seed_registry_v1",
        "authority_class": "identity_collision",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_complete_continuity_unit_v1",
        "authority_class": "exact_recent_facade",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_working_set_item_v1_2",
        "authority_class": "transient_semantic_projection",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_exact_anchor_ref_v1",
        "authority_class": "exact_reference_only",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_event_v1_1",
        "authority_class": "working_set_event",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_scope_binding_event_v1_1",
        "authority_class": "scope_binding_event",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_checkpoint_ack_v1",
        "authority_class": "coverage_receipt",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_episode_checkpoint_v1",
        "authority_class": "noncanonical_episode",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_projection_v1",
        "authority_class": "working_set_read_projection",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_provider_arbiter_request_v1",
        "authority_class": "selection_input",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_provider_projection_v1",
        "authority_class": "provider_dynamic_projection",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_selection_receipt_v1",
        "authority_class": "selection_receipt",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_proactive_read_request_v1",
        "authority_class": "proactive_read_request",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_proactive_read_v1",
        "authority_class": "proactive_read_result",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_curator_proposal_batch_v1",
        "authority_class": "proposal_only",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": "house_continuity_provisional_predecessor_projection_v1",
        "authority_class": "provisional_background",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": ASTEL_COMMAND_SCHEMA_VERSION,
        "authority_class": "astel_explicit_command",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": JOINT_ATTESTATION_SCHEMA_VERSION,
        "authority_class": "joint_evidence_attestation",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": CAPABILITY_OFFER_SCHEMA_VERSION,
        "authority_class": "dynamic_protocol_offer",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "authority_class": "one_use_capability_registry",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": INTENT_SCHEMA_VERSION,
        "authority_class": "solen_explicit_private_command",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": UNIT_COVERAGE_SCHEMA_VERSION,
        "authority_class": "unit_coverage_receipt",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": OUTBOX_SCHEMA_VERSION,
        "authority_class": "durable_preparation_outbox",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": COMMAND_CONTEXT_SCHEMA_VERSION,
        "authority_class": "descriptive_command_context",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": APPLICATION_FENCE_SCHEMA_VERSION,
        "authority_class": "prior_turn_application_fence",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": APPLICATION_FENCE_RECEIPT_SCHEMA_VERSION,
        "authority_class": "application_fence_receipt",
        "gate0_runtime_imported": False,
    },
    {
        "schema_version": GENERATION_IDENTITY_SCHEMA_VERSION,
        "authority_class": "synthetic_generation_identity_evidence",
        "gate0_runtime_imported": False,
    },
)

LEGACY_READ_ONLY_SCHEMA_REGISTRY = (
    "house_continuity_working_set_item_v1",
    "house_continuity_working_set_item_v1_1",
    "house_continuity_event_v1",
    "android_complete_unit",
)

AUTHORSHIP_SOURCE_MATRIX = {
    "solen_explicit": {
        "origin_owner": INTENT_SCHEMA_VERSION,
        "carrier_allowed": True,
        "requires_astel_client_evidence": False,
        "requires_solen_outbox_evidence": True,
        "curator_can_upgrade": False,
        "completed_tool_result_ref_create_allowed": False,
    },
    "astel_explicit": {
        "origin_owner": ASTEL_COMMAND_SCHEMA_VERSION,
        "carrier_allowed": False,
        "requires_astel_client_evidence": True,
        "requires_solen_outbox_evidence": False,
        "curator_can_upgrade": False,
        "completed_tool_result_ref_create_allowed": False,
    },
    "joint_explicit": {
        "origin_owner": JOINT_ATTESTATION_SCHEMA_VERSION,
        "carrier_allowed": False,
        "requires_astel_client_evidence": True,
        "requires_solen_outbox_evidence": True,
        "curator_can_upgrade": False,
        "completed_tool_result_ref_create_allowed": False,
    },
    "structured_client_event": {
        "origin_owner": "exact_structured_client_event",
        "carrier_allowed": False,
        "requires_astel_client_evidence": False,
        "requires_solen_outbox_evidence": False,
        "curator_can_upgrade": False,
        "completed_tool_result_ref_create_allowed": False,
    },
    "structured_tool_event": {
        "origin_owner": "exact_structured_tool_event",
        "carrier_allowed": False,
        "requires_astel_client_evidence": False,
        "requires_solen_outbox_evidence": False,
        "curator_can_upgrade": False,
        "completed_tool_result_ref_create_allowed": True,
    },
    "shadow_only": {
        "origin_owner": "curator_or_heuristic_proposal",
        "carrier_allowed": False,
        "requires_astel_client_evidence": False,
        "requires_solen_outbox_evidence": False,
        "curator_can_upgrade": False,
        "completed_tool_result_ref_create_allowed": False,
    },
}

ITEM_LIFECYCLE_TRANSITION_MATRIX = (
    {"from": "none", "event": "create", "to": "active"},
    {"from": "active", "event": "confirm", "to": "active"},
    {"from": "active", "event": "revise", "to": "active"},
    {"from": "active", "event": "resolve", "to": "resolved"},
    {"from": "active", "event": "supersede", "to": "superseded"},
    {"from": "active", "event": "abandon", "to": "abandoned"},
    {"from": "hard_expiry_active", "event": "expire", "to": "expired"},
    {"from": "resolved", "event": "reopen", "to": "active"},
    {"from": "abandoned", "event": "reopen", "to": "active"},
    {"from": "resolved", "event": "supersede", "to": "superseded"},
    {"from": "abandoned", "event": "supersede", "to": "superseded"},
)

CAPABILITY_TRANSITION_MATRIX = (
    {"from": "none", "event": "durable_issue", "to": "issued"},
    {
        "from": "issued",
        "event": "valid_carrier_atomic_prepare",
        "to": "prepared_consumed",
    },
    {
        "from": "issued",
        "event": "current_capability_terminal_rejection",
        "to": "rejected_consumed",
    },
    {
        "from": "issued",
        "event": "operation_closed_without_carrier",
        "to": "closed_unused",
    },
    {"from": "issued", "event": "ttl_elapsed", "to": "expired"},
    {"from": "issued", "event": "turn_cancelled", "to": "invalidated"},
)

OUTBOX_TRANSITION_MATRIX = (
    {
        "from": "none",
        "event": "atomic_prepare_before_visible",
        "to": "prepared_waiting_visible",
    },
    {
        "from": "none",
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
    {"from": "applying", "event": "all_receipts_committed", "to": "applied"},
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

APPLICATION_FENCE_STATE_MATRIX = {
    "applied": {
        "pending_truth_allowed": False,
        "default_behavior": "applied_working_set",
        "outbox_bundle_id": "required",
        "working_set_receipts": "required",
        "coverage_receipts": "required",
        "exact_fallback_states": ("not_needed",),
    },
    "no_carrier_or_closed_unused": {
        "pending_truth_allowed": False,
        "default_behavior": "no_new_authored_delta",
        "outbox_bundle_id": "forbidden",
        "working_set_receipts": "forbidden",
        "coverage_receipts": "forbidden",
        "exact_fallback_states": ("not_needed",),
    },
    "pending_preparation_or_application": {
        "pending_truth_allowed": False,
        "same_room_exact_behavior": "same_room_exact_recent_fallback",
        "fresh_room_exact_behavior": "fresh_room_exact_predecessor_fallback",
        "fresh_room_missing_behavior": "provisional_handoff_pending",
        "global_newest_fallback_allowed": False,
        "outbox_bundle_id": "optional_preparation_or_required_application",
        "working_set_receipts": "forbidden_until_applied_or_conflict",
        "coverage_receipts": "forbidden_until_applied",
        "same_room_exact_fallback_states": ("available", "unavailable"),
        "fresh_room_exact_fallback_states": (
            "available",
            "missing",
            "unavailable",
        ),
    },
    "conflict_or_rejected": {
        "pending_truth_allowed": False,
        "default_behavior": "conflict_or_rejected_state",
        "outbox_bundle_id": "required",
        "working_set_receipts": "required_conflict_receipt",
        "coverage_receipts": "forbidden",
        "exact_fallback_states": ("not_needed",),
    },
    "unavailable": {
        "pending_truth_allowed": False,
        "default_behavior": "authoritative_unavailable",
        "outbox_bundle_id": "forbidden",
        "working_set_receipts": "forbidden",
        "coverage_receipts": "forbidden",
        "exact_fallback_states": ("unavailable",),
    },
}

GENERATION_IDENTITY_MATRIX = {
    "canonical_semantic_stable_surface": {
        "identity_kind": "semantic_canonical_bytes",
        "proves_literal_wire_equality": False,
    },
    "serialized_stable_messages": {
        "identity_kind": "literal_message_bytes",
        "proves_literal_wire_equality": True,
    },
    "serialized_tool_block": {
        "identity_kind": "literal_tool_bytes",
        "proves_literal_wire_equality": True,
        "tool_order_preserved": True,
        "tool_order_normalized": False,
    },
    "house_cache_signature": {
        "identity_kind": "derived_house_signature",
        "proves_literal_wire_equality": False,
    },
}

KIND_DORMANCY_POLICY_MATRIX = {
    "active_topic": {
        "time_alone_semantically_terminal": False,
        "aging_state": "dormant",
        "relevance_can_resume": True,
    },
    "active_task": {
        "time_alone_semantically_terminal": False,
        "aging_state": "dormant",
        "relevance_can_resume": True,
    },
    "question": {
        "time_alone_semantically_terminal": False,
        "aging_state": "dormant",
        "relevance_can_resume": True,
    },
    "commitment": {
        "time_alone_semantically_terminal": False,
        "aging_state": "dormant",
        "relevance_can_resume": True,
    },
    "decision": {
        "time_alone_semantically_terminal": False,
        "aging_state": "dormant",
        "relevance_can_resume": True,
    },
    "emotional_thread": {
        "time_alone_semantically_terminal": False,
        "aging_state": "dormant",
        "relevance_can_resume": True,
    },
    "pending_review": {
        "time_alone_semantically_terminal": False,
        "aging_state": "dormant",
        "relevance_can_resume": True,
    },
    "temporary_fact": {
        "time_alone_semantically_terminal": True,
        "aging_state": "expired",
        "relevance_can_resume": False,
    },
    "completed_tool_result_ref": {
        "time_alone_semantically_terminal": True,
        "aging_state": "expired",
        "relevance_can_resume": False,
        "selection_requires_same_unresolved_task": True,
    },
    "imported_legacy_shadow": {
        "time_alone_semantically_terminal": True,
        "aging_state": "expired",
        "relevance_can_resume": False,
    },
    "uncertain_deterministic_derivation": {
        "time_alone_semantically_terminal": True,
        "aging_state": "expired",
        "relevance_can_resume": False,
    },
}

TERMINAL_CARRIER_GRAMMAR_MATRIX = {
    "canonical_order": (
        "visible_response",
        "optional_continuity_carrier",
        "optional_memory_carrier_final",
    ),
    "continuity_open_tag": "<house-continuity-intent>",
    "continuity_close_tag": "</house-continuity-intent>",
    "parse_direction": "from_response_end",
    "canonical_single_line_json_required": True,
    "exact_offered_capability_required": True,
    "literal_example_remains_visible": True,
    "quoted_tag_remains_visible": True,
    "code_block_remains_visible": True,
    "incidental_visible_prose_remains_visible": True,
    "duplicate_or_out_of_order_private_block_writes": False,
    "memory_carrier_owner_unchanged": True,
    "gate0_parser_implemented": False,
}

EVENT_CHAIN_AUTHORITY_MATRIX = {
    "global_chain": {
        "sequence_owner": "single_global_event_sequence",
        "hash_predecessor": "previous_global_event_sha256",
        "authoritative_order": True,
    },
    "per_item_chain": {
        "sequence_owner": "item_revision",
        "hash_predecessor": "previous_item_event_sha256",
        "authoritative_order": False,
        "purpose": "item_local_integrity_and_replay",
    },
    "raw_free_boundaries": {
        "event_bodies_are_bounded_semantic_values": True,
        "raw_transcript": False,
        "memory_vault_body": False,
        "self_state_body": False,
        "provider_body": False,
        "tool_body": False,
    },
}

PROVIDER_ASSEMBLY_BOUNDARY_MATRIX = {
    "wrapper": "HOUSE_CURRENT_TURN_V1",
    "command_context_location": "dynamic_context",
    "capability_offer_location": "dynamic_context",
    "provisional_predecessor_priority": "lower_priority_background",
    "current_input_structurally_separate": True,
    "current_input_last": True,
    "provider_material_after_current_input": False,
    "standing_root_v2_card_bodies_changed_in_gate0": False,
    "memory_gate_13_distinct": True,
    "vault_exact_recall_distinct": True,
    "self_state_distinct": True,
    "transient_auto_promotes_to_memory": False,
}

STABLE_PREFIX_READINESS_MATRIX = {
    "generation_1_immediate_rollback_preserved": True,
    "seven_standing_root_v2_card_bodies_unchanged": True,
    "continuity_authorship_available_requires_instruction": True,
    "continuity_authorship_available_requires_capability_issuance": True,
    "continuity_authorship_available_requires_terminal_parser": True,
    "continuity_authorship_available_requires_stripping": True,
    "continuity_authorship_available_requires_durable_preparation": True,
    "generation_2_local_activation_candidate_required": True,
    "gate0_generation_2_generated": False,
    "gate0_cache_key_changed": False,
}

PROPOSAL_AUTHORITY_MATRIX = {
    "continuity_curator": {
        "provider_neutral": True,
        "initial_provider": "deepseek_v4_flash",
        "initial_mode": "shadow",
        "may_propose": (
            "semantic_items",
            "episode_summaries",
            "scope_bindings",
            "duplicates",
            "conflicts",
        ),
        "may_mutate_working_set": False,
        "may_upgrade_authorship": False,
    },
    "heuristic_extraction": {
        "mode": "proposal_or_shadow_only",
        "may_mutate_working_set": False,
        "may_upgrade_authorship": False,
    },
}

GATE0_EXCLUDED_IMPLEMENTATION_MATRIX = {
    "real_astel_structured_authorship_ui_or_route": False,
    "live_joint_attestation": False,
    "curator_calls": False,
    "android_changes": False,
    "provider_visible_continuity": False,
    "working_set_storage": False,
    "capability_issuance": False,
    "prefix_generation_2": False,
    "runtime_route_import": False,
    "provider_call": False,
    "production_data_write": False,
}


def contract_matrix_bundle() -> dict[str, Any]:
    return {
        "schema_version": MODULE_SCHEMA_VERSION,
        "gate_id": GATE_ID,
        "approved_schema_registry": list(APPROVED_SCHEMA_REGISTRY),
        "legacy_read_only_schema_registry": list(
            LEGACY_READ_ONLY_SCHEMA_REGISTRY
        ),
        "authorship_source_matrix": AUTHORSHIP_SOURCE_MATRIX,
        "item_lifecycle_transition_matrix": list(
            ITEM_LIFECYCLE_TRANSITION_MATRIX
        ),
        "capability_transition_matrix": list(CAPABILITY_TRANSITION_MATRIX),
        "outbox_transition_matrix": list(OUTBOX_TRANSITION_MATRIX),
        "coverage_eviction_matrix": COVERAGE_EVICTION_MATRIX,
        "application_fence_state_matrix": APPLICATION_FENCE_STATE_MATRIX,
        "generation_identity_matrix": GENERATION_IDENTITY_MATRIX,
        "kind_dormancy_policy_matrix": KIND_DORMANCY_POLICY_MATRIX,
        "terminal_carrier_grammar_matrix": TERMINAL_CARRIER_GRAMMAR_MATRIX,
        "event_chain_authority_matrix": EVENT_CHAIN_AUTHORITY_MATRIX,
        "provider_assembly_boundary_matrix": (
            PROVIDER_ASSEMBLY_BOUNDARY_MATRIX
        ),
        "stable_prefix_readiness_matrix": STABLE_PREFIX_READINESS_MATRIX,
        "proposal_authority_matrix": PROPOSAL_AUTHORITY_MATRIX,
        "gate0_excluded_implementation_matrix": (
            GATE0_EXCLUDED_IMPLEMENTATION_MATRIX
        ),
    }

__all__ = [
    "APPLICATION_FENCE_OUTCOMES",
    "APPLICATION_FENCE_RECEIPT_SCHEMA_VERSION",
    "APPLICATION_FENCE_SCHEMA_VERSION",
    "APPROVED_SCHEMA_REGISTRY",
    "ASTEL_COMMAND_SCHEMA_VERSION",
    "AUTHORSHIP_SOURCE_MATRIX",
    "CAPABILITY_OFFER_SCHEMA_VERSION",
    "CAPABILITY_SCHEMA_VERSION",
    "COMMAND_CONTEXT_AUTHORITY",
    "COMMAND_CONTEXT_SCHEMA_VERSION",
    "COVERAGE_EVICTION_MATRIX",
    "GENERATION_IDENTITY_SCHEMA_VERSION",
    "GATE0_EXCLUDED_IMPLEMENTATION_MATRIX",
    "GATE_ID",
    "HouseContinuityV12ContractError",
    "INTENT_PROTOCOL_VERSION",
    "INTENT_SCHEMA_VERSION",
    "JOINT_ATTESTATION_SCHEMA_VERSION",
    "OUTBOX_SCHEMA_VERSION",
    "UNIT_COVERAGE_SCHEMA_VERSION",
    "canonical_json_bytes",
    "canonical_sha256",
    "contract_matrix_bundle",
    "decide_application_fence",
    "derived_house_cache_signature",
    "synthetic_sha256",
    "validate_application_fence",
    "validate_astel_explicit_command",
    "validate_capability_offer",
    "validate_command_context",
    "validate_semantic_evaluation_request",
    "validate_continuity_intent",
    "validate_generation_identity_evidence",
    "validate_intent_capability",
    "validate_intent_against_context",
    "validate_joint_attestation",
    "validate_outbox_bundle",
    "validate_unit_coverage",
    "ASTEL_CONFIRMATION_SCHEMA_VERSION",
    "SEMANTIC_EVALUATION_FIELD",
    "SEMANTIC_EVALUATION_SCHEMA_VERSION",
    "SEMANTIC_EVALUATION_REQUEST_SCHEMA_VERSION",
    "SEMANTIC_EVALUATION_RELATIONS",
    "AUTHORITATIVE_REAFFIRMATION_CANONICALIZATION_CODE",
    "authoritative_projection_sha256",
    "EXECUTABLE_SCHEMA_VERSIONS",
    "canonical_astel_semantic_command",
    "validate_astel_confirmation_capability",
    "validate_astel_reviewed_command_against_capability",
    "validate_complete_continuity_unit",
    "validate_creation_seed_collision",
    "validate_creation_seed_registry",
    "validate_exact_anchor_ref",
    "validate_exact_outbox_retry",
    "validate_event_chains",
    "validate_intent_against_capability",
    "validate_item_kind_payload",
    "validate_outbox_against_capability",
    "validate_outbox_transition",
    "validate_scope_binding",
    "validate_scope_binding_event",
    "validate_working_set_event",
    "validate_working_set_item",
]

_GATE0_EXECUTABLE_SCHEMA_VERSIONS = set(EXECUTABLE_SCHEMA_VERSIONS)
APPROVED_SCHEMA_REGISTRY = tuple(
    {
        **row,
        "gate0_execution_status": (
            "encoded_validated_executable_in_gate0"
            if row["schema_version"] in _GATE0_EXECUTABLE_SCHEMA_VERSIONS
            else "design_registered_not_executable_in_gate0"
        ),
    }
    for row in APPROVED_SCHEMA_REGISTRY
) + (
    {
        "schema_version": ASTEL_CONFIRMATION_SCHEMA_VERSION,
        "authority_class": "astel_review_confirmation_capability",
        "gate0_runtime_imported": False,
        "gate0_execution_status": "encoded_validated_executable_in_gate0",
    },
)
