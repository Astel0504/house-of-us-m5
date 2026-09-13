"""Machine-readable approved-design to Gate-0 execution ledger."""

from __future__ import annotations

from house_continuity_v1_2_contract_schema_v0 import APPROVED_SCHEMA_REGISTRY


GATE1_CARRY_FORWARD_OBLIGATIONS = (
    {
        "obligation_id": "gate1_exact_lifecycle_transitions_by_event_kind",
        "required_proof": "exact lifecycle transitions for every event kind",
        "implemented_in_gate0": False,
    },
    {
        "obligation_id": "gate1_event_patch_allowlists",
        "required_proof": (
            "immutable-field and operation-specific event patch allowlists"
        ),
        "implemented_in_gate0": False,
    },
    {
        "obligation_id": "gate1_actor_transition_compatibility",
        "required_proof": "actor and transition compatibility",
        "implemented_in_gate0": False,
    },
    {
        "obligation_id": "gate1_binding_event_compatibility",
        "required_proof": (
            "binding-event kind compatibility with from and to bindings"
        ),
        "implemented_in_gate0": False,
    },
    {
        "obligation_id": "gate1_no_resolve_active_to_active",
        "required_proof": "resolve cannot transition active to active",
        "implemented_in_gate0": False,
    },
    {
        "obligation_id": "gate1_no_decline_bound_target",
        "required_proof": "decline cannot leave a bound target",
        "implemented_in_gate0": False,
    },
)


GATE2_CARRY_FORWARD_OBLIGATIONS = (
    {
        "obligation_id": "gate2_android_source_payload_digest_bytes",
        "required_proof": (
            "exact actual Android producer-shaped bytes bound by "
            "source_payload_sha256"
        ),
        "implemented_in_gate0": False,
        "gate0_canonical_substitute_forbidden": True,
    },
    {
        "obligation_id": "gate2_android_stale_source_digest_rejection",
        "required_proof": (
            "changed exact message or source bytes cannot retain a stale digest"
        ),
        "implemented_in_gate0": False,
        "gate0_canonical_substitute_forbidden": True,
    },
    {
        "obligation_id": "gate2_visible_exchange_anatomy",
        "required_proof": "visible-exchange participant and order anatomy",
        "implemented_in_gate0": False,
        "gate0_canonical_substitute_forbidden": True,
    },
    {
        "obligation_id": "gate2_source_rendered_source_order",
        "required_proof": "source and rendered-source ordering",
        "implemented_in_gate0": False,
        "gate0_canonical_substitute_forbidden": True,
    },
    {
        "obligation_id": "gate2_split_sibling_completeness",
        "required_proof": "split-sibling completeness",
        "implemented_in_gate0": False,
        "gate0_canonical_substitute_forbidden": True,
    },
    {
        "obligation_id": "gate2_provider_operation_finality",
        "required_proof": (
            "provider-operation acknowledgement supersession and terminal "
            "finality"
        ),
        "implemented_in_gate0": False,
        "gate0_canonical_substitute_forbidden": True,
    },
)


_EXECUTABLE_ROWS = {
    "house_continuity_command_context_v1": {
        "executable_validator": "validate_command_context",
        "positive_fixture": "COMMAND_CONTEXT",
        "adversarial_fixtures": (
            "command_context_content_hash_mismatch",
            "duplicate_offer_id",
            "duplicate_create_scope",
        ),
        "test_names": (
            "test_command_context_recomputes_content_hash_and_unique_offers",
        ),
        "timestamp_paths": (),
    },
    "house_talk_continuity_authorship_intent_v1": {
        "executable_validator": "validate_continuity_intent",
        "positive_fixture": "REVISE_INTENT",
        "adversarial_fixtures": (
            "duplicate_operation_key",
            "solen_created_completed_tool_result",
        ),
        "test_names": ("test_operation_discriminators_and_content_preservation",),
        "timestamp_paths": (),
    },
    "house_continuity_astel_explicit_command_v1": {
        "executable_validator": "validate_astel_explicit_command",
        "positive_fixture": "ASTEL_DIRECT_COMMAND_AND_LIFECYCLE_COMMANDS",
        "adversarial_fixtures": (
            "astel_candidate_digest_mismatch",
            "astel_lifecycle_semantic_smuggling",
        ),
        "test_names": (
            "test_astel_all_authorized_lifecycle_shapes",
            "test_impossible_timestamps_rejected_by_every_timestamped_executable",
        ),
        "timestamp_paths": ("created_at",),
    },
    "house_continuity_astel_confirmation_capability_v1": {
        "executable_validator": "validate_astel_confirmation_capability",
        "positive_fixture": "ASTEL_CONFIRMATION_CAPABILITY",
        "adversarial_fixtures": (
            "changed_review_candidate_bytes",
            "replayed_astel_confirmation",
        ),
        "test_names": (
            "test_astel_direct_and_review_confirmation_digest_binding",
            "test_impossible_timestamps_rejected_by_every_timestamped_executable",
        ),
        "timestamp_paths": ("issued_at", "expires_at"),
    },
    "house_continuity_joint_authorship_attestation_v1": {
        "executable_validator": "validate_joint_attestation",
        "positive_fixture": "JOINT_ATTESTATION",
        "adversarial_fixtures": (
            "nonindependent_joint_evidence",
            "joint_semantic_hash_mismatch",
        ),
        "test_names": (
            "test_joint_attestation_requires_two_independent_sources",
            "test_impossible_timestamps_rejected_by_every_timestamped_executable",
        ),
        "timestamp_paths": ("created_at",),
    },
    "house_continuity_authorship_offer_v1": {
        "executable_validator": "validate_capability_offer",
        "positive_fixture": "CAPABILITY_OFFER",
        "adversarial_fixtures": ("impossible_capability_offer_expiry",),
        "test_names": (
            "test_impossible_timestamps_rejected_by_every_timestamped_executable",
        ),
        "timestamp_paths": ("expires_at",),
    },
    "house_continuity_intent_capability_v1": {
        "executable_validator": "validate_intent_capability",
        "positive_fixture": "INTENT_CAPABILITY_ISSUED",
        "adversarial_fixtures": (
            "wrong_turn_capability",
            "wrong_command_context_binding",
        ),
        "test_names": (
            "test_command_context_is_bound_to_capability_and_outbox",
            "test_impossible_timestamps_rejected_by_every_timestamped_executable",
        ),
        "timestamp_paths": ("issued_at", "expires_at"),
    },
    "house_continuity_unit_coverage_v1": {
        "executable_validator": "validate_unit_coverage",
        "positive_fixture": "coverage_fixture(solen_no_semantic_delta)",
        "adversarial_fixtures": ("impossible_unit_coverage_created_at",),
        "test_names": (
            "test_impossible_timestamps_rejected_by_every_timestamped_executable",
        ),
        "timestamp_paths": ("created_at",),
    },
    "house_continuity_command_outbox_bundle_v1": {
        "executable_validator": "validate_outbox_bundle",
        "positive_fixture": "OUTBOX_STATE_FIXTURES",
        "adversarial_fixtures": ("OUTBOX_STATE_ADVERSARIAL_FIXTURES",),
        "test_names": (
            "test_every_outbox_state_and_transition_edge_is_executable",
            "test_impossible_timestamps_rejected_by_every_timestamped_executable",
        ),
        "timestamp_paths": ("prepared_at",),
    },
    "house_continuity_application_fence_v1": {
        "executable_validator": "validate_application_fence",
        "positive_fixture": "FENCE_SCENARIOS",
        "adversarial_fixtures": ("contradictory_fence_evidence",),
        "test_names": (
            "test_fence_outcomes_require_coherent_evidence",
        ),
        "timestamp_paths": (),
    },
    "house_continuity_generation_2_identity_evidence_v1": {
        "executable_validator": "validate_generation_identity_evidence",
        "positive_fixture": "GENERATION_IDENTITY_EVIDENCE",
        "adversarial_fixtures": ("wire_identity_collapsed",),
        "test_names": ("test_generation_identity_keeps_four_identities_distinct",),
        "timestamp_paths": (),
    },
    "house_continuity_creation_seed_registry_v1": {
        "executable_validator": "validate_creation_seed_registry",
        "positive_fixture": "CREATION_SEED",
        "adversarial_fixtures": ("creation_seed_invalid_full_sha",),
        "test_names": (
            "test_literal_gate1_gate2_dependencies_and_chains",
            "test_impossible_timestamps_rejected_by_every_timestamped_executable",
        ),
        "timestamp_paths": ("created_at",),
    },
    "house_continuity_scope_binding_v1": {
        "executable_validator": "validate_scope_binding",
        "positive_fixture": "SCOPE_BINDING",
        "adversarial_fixtures": ("scope_binding_zero_revision",),
        "test_names": (
            "test_room_scope_preserves_valid_project_thread_lineage",
            "test_impossible_timestamps_rejected_by_every_timestamped_executable",
        ),
        "timestamp_paths": ("created_at", "updated_at"),
    },
    "house_continuity_working_set_item_v1_2": {
        "executable_validator": "validate_working_set_item",
        "positive_fixture": "WORKING_SET_ITEM_AUTHORSHIP_VARIANTS",
        "adversarial_fixtures": (
            "working_set_item_content_mismatch",
            "working_set_item_stored_freshness_forbidden",
            "shadow_authority_in_projection",
            "active_task_question_freshness_policy",
            "participant_pending_review_hard_expiry",
            "temporary_fact_without_hard_expiry",
            "completed_tool_result_without_hard_expiry",
            "active_item_cleanup_eligible",
            "terminal_cleanup_before_update",
            "resolved_timestamp_before_creation",
            "abandoned_timestamp_before_creation",
            "expired_update_precedes_expiry",
        ),
        "test_names": (
            "test_full_working_set_item_and_authorship_evidence",
            "test_working_set_item_closure_invariants",
            "test_impossible_timestamps_rejected_by_every_timestamped_executable",
        ),
        "timestamp_paths": (
            "created_at",
            "updated_at",
            "last_confirmed_at",
            "fresh_until",
            "aging_after",
            "dormant_after",
        ),
    },
    "house_continuity_event_v1_1": {
        "executable_validator": "validate_working_set_event",
        "positive_fixture": "WORKING_SET_EVENT_1",
        "adversarial_fixtures": (
            "collapsed_global_item_event_identity",
            "arbitrary_non_genesis_chain_start",
        ),
        "test_names": (
            "test_distinct_event_hash_formulas_and_chain_doctor",
            "test_inherited_item_event_kinds_remain_executable",
            "test_impossible_timestamps_rejected_by_every_timestamped_executable",
        ),
        "timestamp_paths": ("created_at",),
    },
    "house_continuity_scope_binding_event_v1_1": {
        "executable_validator": "validate_scope_binding_event",
        "positive_fixture": "SCOPE_BINDING_EVENT_1",
        "adversarial_fixtures": ("binding_chain_predecessor_mismatch",),
        "test_names": (
            "test_distinct_event_hash_formulas_and_chain_doctor",
            "test_impossible_timestamps_rejected_by_every_timestamped_executable",
        ),
        "timestamp_paths": (
            "created_at",
            "to_binding.created_at",
            "to_binding.updated_at",
        ),
    },
    "house_continuity_exact_anchor_ref_v1": {
        "executable_validator": "validate_exact_anchor_ref",
        "positive_fixture": "EXACT_ANCHOR_REF_AND_LEGACY_COMPATIBILITY",
        "adversarial_fixtures": ("exact_anchor_reversed_boundary",),
        "test_names": ("test_exact_anchor_legacy_read_and_new_writer_identity",),
        "timestamp_paths": (),
    },
    "house_complete_continuity_unit_v1": {
        "executable_validator": "validate_complete_continuity_unit",
        "positive_fixture": "VISIBLE_AND_OPERATION_COMPLETE_UNITS",
        "adversarial_fixtures": (
            "simplified_complete_unit_without_messages",
            "incomplete_complete_unit",
            "mixed_exact_derived_complete_unit",
            "missing_split_sibling",
            "acknowledgement_not_superseded",
            "future_complete_unit_producer",
        ),
        "test_names": ("test_full_complete_unit_facade_and_adversarial_cases",),
        "timestamp_paths": (),
    },
}


GATE0_CONFORMANCE_LEDGER = tuple(
    {
        "approved_design_schema": row["schema_version"],
        "executable_validator": (
            _EXECUTABLE_ROWS.get(row["schema_version"], {}).get(
                "executable_validator"
            )
        ),
        "positive_fixture": (
            _EXECUTABLE_ROWS.get(row["schema_version"], {}).get(
                "positive_fixture"
            )
        ),
        "adversarial_fixtures": list(
            _EXECUTABLE_ROWS.get(row["schema_version"], {}).get(
                "adversarial_fixtures", ()
            )
        ),
        "test_names": list(
            _EXECUTABLE_ROWS.get(row["schema_version"], {}).get(
                "test_names", ()
            )
        ),
        "timestamp_paths": list(
            _EXECUTABLE_ROWS.get(row["schema_version"], {}).get(
                "timestamp_paths", ()
            )
        ),
        "execution_status": row["gate0_execution_status"],
    }
    for row in APPROVED_SCHEMA_REGISTRY
)
