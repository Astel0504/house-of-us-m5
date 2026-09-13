from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import house_memory_durable_event_contract_v0 as durable


EVENT_SCHEMA_VERSION = "house_memory_durable_event_v1"
OBSERVATION_PAYLOAD_SCHEMA_VERSION = "house_memory_observation_payload_v1"
CORE_PAYLOAD_SCHEMA_VERSION = "house_memory_core_payload_v1"
LIFECYCLE_PAYLOAD_SCHEMA_VERSION = "house_memory_lifecycle_payload_v1"
AUTOMATIC_LIFECYCLE_PAYLOAD_SCHEMA_VERSION = "house_memory_automatic_lifecycle_payload_v0"
METADATA_REPAIR_RECONCILIATION_PAYLOAD_SCHEMA_VERSION = (
    "house_memory_metadata_repair_reconciliation_payload_v1"
)
RELATION_PAYLOAD_SCHEMA_VERSION = "house_memory_relation_payload_v1"
RELATION_PAYLOAD_V2_SCHEMA_VERSION = "house_memory_relation_payload_v2"
PROPOSAL_PAYLOAD_SCHEMA_VERSION = "house_memory_evolution_proposal_payload_v1"
EVOLUTION_APPLIED_PAYLOAD_SCHEMA_VERSION = "house_memory_reviewed_evolution_applied_payload_v1"
RELATION_IDENTITY_SCHEMA_VERSION = "house_memory_relation_identity_v1"
RELATION_IDENTITY_V2_SCHEMA_VERSION = "house_memory_relation_identity_v2"
PROPOSAL_IDENTITY_SCHEMA_VERSION = "house_memory_evolution_proposal_identity_v1"
EVOLUTION_APPLIED_IDENTITY_SCHEMA_VERSION = "house_memory_reviewed_evolution_applied_identity_v1"

ACTION_CODES = frozenset(
    {
        "record_observed",
        "record_version_observed",
        "set_core",
        "remove_core",
        "quiet",
        "restore_normal",
        "automatic_cooling",
        "automatic_quiet",
        "lifecycle_wakeup",
        "metadata_repair_reconciled",
        "relation_asserted",
        "relation_retracted",
        "evolution_proposal_created",
        "evolution_proposal_withdrawn",
        "reviewed_evolution_applied",
    }
)
PARTICIPANT_SCOPES = frozenset({"synthetic_test", "astel", "solen", "astel_solen", "house_group"})
AUTHORITY_SCOPES = frozenset(
    {"synthetic_test", "reviewed_memory", "solen_active_memory", "candidate_only"}
)
AUTHORITY_OWNERS = frozenset(
    {"synthetic_test", "astel", "solen", "astel_solen", "house_standing_consent"}
)
AUDIENCE_SCOPES = frozenset(
    {
        "synthetic_test",
        "astel_solen_private",
        "astel_only",
        "group_safe",
        "house_group_context",
    }
)
ACTOR_TYPES = frozenset({"synthetic_test", "astel", "solen", "astel_solen", "house_backend"})
INTENT_ACTOR_TYPES = frozenset({"synthetic_test", "astel", "solen", "astel_solen"})
REVIEW_STATES = frozenset({"reviewed", "standing_consent_active"})
CURATED_STATUS_CODES = frozenset({"approved", "superseded"})
CURATED_REVIEW_STATES = frozenset({*REVIEW_STATES, "stale"})
RELATION_TYPES = frozenset(
    {"same_event", "duplicate_of", "complements", "supports", "contradicts", "evolves_from"}
)
SYMMETRIC_RELATION_TYPES = frozenset({"same_event", "duplicate_of", "complements", "contradicts"})
PROPOSAL_KINDS = frozenset(
    {"merge_candidate", "supersede_candidate", "correction_candidate", "duplicate_resolution_candidate"}
)
PROPOSAL_BASES = frozenset(
    {
        "exact_duplicate",
        "semantic_overlap",
        "newer_reviewed_version",
        "contradiction_signal",
        "participant_requested",
        "operator_requested",
        "synthetic_fixture",
    }
)
EVOLUTION_KINDS = frozenset({"correction", "merge", "duplicate_resolution", "supersession"})
EVOLUTION_RESOLUTION_CODES = frozenset({
    "correction_accepted", "merge_accepted", "duplicate_resolved", "supersession_accepted",
})
EVOLUTION_KIND_RESOLUTION_CODES = {
    "correction": "correction_accepted",
    "merge": "merge_accepted",
    "duplicate_resolution": "duplicate_resolved",
    "supersession": "supersession_accepted",
}
EVOLUTION_DISPOSITION_CODES = frozenset({
    "primary_retained", "comparison_retained", "keep_separate", "check_needed",
})

EVENT_FIELDS = frozenset(
    {
        "schema_version", "event_id", "event_sequence", "previous_event_id", "occurred_at",
        "action_code", "memory_ref_hash", "canonical_record_version_hash", "actor_type",
        "actor_ref_hash", "action_ref_hash", "participant_scope_code", "authority_scope_code",
        "authority_owner_code", "audience_scope_code", "status_code", "review_state_code",
        "reason_code", "provenance_present", "blocker_flags", "safe_capability_flags", "payload",
    }
)

OBSERVATION_PAYLOAD_FIELDS = frozenset({"payload_schema_version"})
CORE_PAYLOAD_FIELDS = frozenset(
    {
        "payload_schema_version",
        "requested_by_actor_type", "requested_by_actor_ref_hash", "request_intent_hash",
        "approved_by_actor_type", "approved_by_actor_ref_hash", "approval_intent_hash", "confirmed",
    }
)
LIFECYCLE_PAYLOAD_FIELDS = frozenset({"payload_schema_version"})
AUTOMATIC_LIFECYCLE_PAYLOAD_FIELDS = frozenset({
    "payload_schema_version", "policy_version", "transition_proposal_id",
    "transition_proposal_ref_hash", "prior_lifecycle_state", "next_lifecycle_state",
    "policy_evaluated_at", "reason_inputs", "reason_codes",
})
AUTOMATIC_LIFECYCLE_REASON_INPUT_FIELDS = frozenset({
    "record_age_seconds", "lifecycle_state_age_seconds", "last_eligible_use_age_seconds",
    "eligible_use_observed", "inactivity_age_seconds", "use_count", "ignored_count",
    "unknown_use", "wakeup_evidence", "protected_class_codes",
})
AUTOMATIC_LIFECYCLE_STATES = frozenset({"active", "cooling", "quiet"})
AUTOMATIC_LIFECYCLE_REASONS = frozenset({
    "stale_canonical_version", "explicit_wakeup_evidence", "age_threshold_reached",
    "protected_slow_cooling", "active_retained", "protected_from_automatic_quiet",
    "quiet_threshold_reached", "cooling_retained", "quiet_retained", "unknown_use_neutral",
    "repeated_use_slows_cooling", "repeated_ignore_supports_cooling",
})
AUTOMATIC_PROTECTED_CLASSES = frozenset({
    "core", "identity", "relationship", "standing_footing", "contradiction_check_needed",
    "open_loop", "unique_detail",
})
METADATA_REPAIR_RECONCILIATION_PAYLOAD_FIELDS = frozenset(
    {
        "payload_schema_version", "prior_canonical_record_version_hash",
        "new_canonical_record_version_hash", "operation_ref_hash", "audit_ref_hash",
        "marker_ref_hash",
    }
)
RELATION_PAYLOAD_FIELDS = frozenset(
    {
        "payload_schema_version",
        "relation_ref_hash", "left_memory_ref_hash", "left_canonical_record_version_hash",
        "right_memory_ref_hash", "right_canonical_record_version_hash", "relation_type",
        "strength_milli", "evidence_ref_hash",
    }
)
RELATION_PAYLOAD_V2_FIELDS = frozenset({
    "payload_schema_version", "relation_ref_hash", "left_memory_ref_hash",
    "left_canonical_record_version_hash", "left_authority_scope_code", "left_authority_owner_code",
    "right_memory_ref_hash", "right_canonical_record_version_hash", "right_authority_scope_code",
    "right_authority_owner_code", "relation_type", "participant_scope_code", "audience_scope_code",
    "strength_milli", "evidence_class", "evidence_ref_hash",
})
PROPOSAL_PAYLOAD_FIELDS = frozenset(
    {
        "payload_schema_version",
        "proposal_ref_hash", "proposal_kind", "proposal_basis", "primary_memory_ref_hash",
        "primary_canonical_record_version_hash", "comparison_memory_ref_hash",
        "comparison_canonical_record_version_hash", "candidate_ref_hash", "proposal_origin_action_ref_hash",
    }
)
EVOLUTION_APPLIED_PAYLOAD_FIELDS = frozenset({
    "payload_schema_version", "resolution_ref_hash", "candidate_id", "candidate_version_hash",
    "evolution_kind", "primary_memory_ref_hash", "primary_applied_version_hash",
    "comparison_memory_ref_hash", "comparison_applied_version_hash",
    "approved_by_actor_type", "approved_by_actor_ref_hash", "approval_authority_scope_code",
    "approval_authority_owner_code", "approval_evidence_ref_hash", "source_evidence_ref_hash",
    "provenance_evidence_ref_hash", "resolution_code", "disposition_code", "core_involved",
    "core_check_needed", "canonical_record_changed", "core_moved_or_removed",
})


def _require_fields(value: Any, fields: frozenset[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise durable.HouseMemoryDurableEventError(
            f"invalid_{name}_fields", f"{name} fields must exactly match the Gate 2 allowlist."
        )
    return value


def _hash(name: str, value: Any) -> str:
    return durable._require_hash(name, value)


def _code(name: str, value: Any, allowed: frozenset[str] | None = None) -> str:
    return durable._require_code(name, value, allowed)


def canonical_relation_endpoints(
    left_memory_ref_hash: str, right_memory_ref_hash: str, relation_type: str
) -> tuple[str, str]:
    left = _hash("left_memory_ref_hash", left_memory_ref_hash)
    right = _hash("right_memory_ref_hash", right_memory_ref_hash)
    kind = _code("relation_type", relation_type, RELATION_TYPES)
    if left == right:
        raise durable.HouseMemoryDurableEventError("relation_self_edge", "A relation cannot join a record to itself.")
    if kind in SYMMETRIC_RELATION_TYPES and right < left:
        return right, left
    return left, right


def compute_relation_ref(
    *, left_memory_ref_hash: str, right_memory_ref_hash: str, relation_type: str,
    participant_scope_code: str, authority_scope_code: str, authority_owner_code: str,
    audience_scope_code: str,
) -> str:
    left, right = canonical_relation_endpoints(left_memory_ref_hash, right_memory_ref_hash, relation_type)
    basis = {
        "identity_schema_version": RELATION_IDENTITY_SCHEMA_VERSION,
        "audience_scope_code": _code("audience_scope_code", audience_scope_code, AUDIENCE_SCOPES),
        "authority_owner_code": _code("authority_owner_code", authority_owner_code, AUTHORITY_OWNERS),
        "authority_scope_code": _code("authority_scope_code", authority_scope_code, AUTHORITY_SCOPES),
        "left_memory_ref_hash": left,
        "participant_scope_code": _code("participant_scope_code", participant_scope_code, PARTICIPANT_SCOPES),
        "relation_type": _code("relation_type", relation_type, RELATION_TYPES),
        "right_memory_ref_hash": right,
    }
    return durable.canonical_sha256(basis)


def compute_relation_ref_v2(*, left_memory_ref_hash: str, right_memory_ref_hash: str, relation_type: str,
                            participant_scope_code: str, audience_scope_code: str,
                            left_authority_scope_code: str, left_authority_owner_code: str,
                            right_authority_scope_code: str, right_authority_owner_code: str) -> str:
    left, right = canonical_relation_endpoints(left_memory_ref_hash, right_memory_ref_hash, relation_type)
    left_scope, left_owner = left_authority_scope_code, left_authority_owner_code
    right_scope, right_owner = right_authority_scope_code, right_authority_owner_code
    if left != left_memory_ref_hash:
        left_scope, right_scope = right_scope, left_scope
        left_owner, right_owner = right_owner, left_owner
    return durable.canonical_sha256({
        "identity_schema_version": RELATION_IDENTITY_V2_SCHEMA_VERSION,
        "left_memory_ref_hash": left, "right_memory_ref_hash": right,
        "relation_type": _code("relation_type", relation_type, RELATION_TYPES),
        "participant_scope_code": _code("participant_scope_code", participant_scope_code, PARTICIPANT_SCOPES),
        "audience_scope_code": _code("audience_scope_code", audience_scope_code, AUDIENCE_SCOPES),
        "left_authority_scope_code": _code("left_authority_scope_code", left_scope, AUTHORITY_SCOPES),
        "left_authority_owner_code": _code("left_authority_owner_code", left_owner, AUTHORITY_OWNERS),
        "right_authority_scope_code": _code("right_authority_scope_code", right_scope, AUTHORITY_SCOPES),
        "right_authority_owner_code": _code("right_authority_owner_code", right_owner, AUTHORITY_OWNERS),
    })


def compute_proposal_ref(
    *, action_ref_hash: str, proposal_kind: str, primary_memory_ref_hash: str,
    primary_canonical_record_version_hash: str, comparison_memory_ref_hash: str,
    comparison_canonical_record_version_hash: str, candidate_ref_hash: str,
) -> str:
    return durable.canonical_sha256(
        {
            "identity_schema_version": PROPOSAL_IDENTITY_SCHEMA_VERSION,
            "action_ref_hash": _hash("action_ref_hash", action_ref_hash),
            "candidate_ref_hash": _hash("candidate_ref_hash", candidate_ref_hash),
            "comparison_canonical_record_version_hash": _hash(
                "comparison_canonical_record_version_hash", comparison_canonical_record_version_hash
            ),
            "comparison_memory_ref_hash": _hash("comparison_memory_ref_hash", comparison_memory_ref_hash),
            "primary_canonical_record_version_hash": _hash(
                "primary_canonical_record_version_hash", primary_canonical_record_version_hash
            ),
            "primary_memory_ref_hash": _hash("primary_memory_ref_hash", primary_memory_ref_hash),
            "proposal_kind": _code("proposal_kind", proposal_kind, PROPOSAL_KINDS),
        }
    )


def compute_evolution_resolution_ref(*, candidate_id: str, candidate_version_hash: str,
                                     evolution_kind: str, primary_memory_ref_hash: str,
                                     primary_applied_version_hash: str,
                                     comparison_memory_ref_hash: str,
                                     comparison_applied_version_hash: str,
                                     resolution_code: str, disposition_code: str) -> str:
    return durable.canonical_sha256({
        "identity_schema_version": EVOLUTION_APPLIED_IDENTITY_SCHEMA_VERSION,
        "candidate_id": _hash("candidate_id", candidate_id),
        "candidate_version_hash": _hash("candidate_version_hash", candidate_version_hash),
        "evolution_kind": _code("evolution_kind", evolution_kind, EVOLUTION_KINDS),
        "primary_memory_ref_hash": _hash("primary_memory_ref_hash", primary_memory_ref_hash),
        "primary_applied_version_hash": _hash("primary_applied_version_hash", primary_applied_version_hash),
        "comparison_memory_ref_hash": _hash("comparison_memory_ref_hash", comparison_memory_ref_hash),
        "comparison_applied_version_hash": _hash("comparison_applied_version_hash", comparison_applied_version_hash),
        "resolution_code": _code("resolution_code", resolution_code, EVOLUTION_RESOLUTION_CODES),
        "disposition_code": _code("disposition_code", disposition_code, EVOLUTION_DISPOSITION_CODES),
    })


def _normalize_payload(action: str, value: Any, event: Mapping[str, Any]) -> dict[str, Any]:
    if action in {"record_observed", "record_version_observed"}:
        payload = _require_fields(value, OBSERVATION_PAYLOAD_FIELDS, "observation_payload")
        if payload["payload_schema_version"] != OBSERVATION_PAYLOAD_SCHEMA_VERSION:
            raise durable.HouseMemoryDurableEventError("payload_schema_mismatch", "Observation payload schema is unsupported.")
        return {"payload_schema_version": OBSERVATION_PAYLOAD_SCHEMA_VERSION}
    if action in {"set_core", "remove_core"}:
        payload = _require_fields(value, CORE_PAYLOAD_FIELDS, "core_payload")
        if payload["payload_schema_version"] != CORE_PAYLOAD_SCHEMA_VERSION:
            raise durable.HouseMemoryDurableEventError("payload_schema_mismatch", "Core payload schema is unsupported.")
        if not isinstance(payload["confirmed"], bool) or not payload["confirmed"]:
            raise durable.HouseMemoryDurableEventError("core_not_confirmed", "Core actions require confirmed intent.")
        return {
            "payload_schema_version": CORE_PAYLOAD_SCHEMA_VERSION,
            "approved_by_actor_ref_hash": _hash("approved_by_actor_ref_hash", payload["approved_by_actor_ref_hash"]),
            "approved_by_actor_type": _code("approved_by_actor_type", payload["approved_by_actor_type"], INTENT_ACTOR_TYPES),
            "approval_intent_hash": _hash("approval_intent_hash", payload["approval_intent_hash"]),
            "confirmed": True,
            "request_intent_hash": _hash("request_intent_hash", payload["request_intent_hash"]),
            "requested_by_actor_ref_hash": _hash("requested_by_actor_ref_hash", payload["requested_by_actor_ref_hash"]),
            "requested_by_actor_type": _code("requested_by_actor_type", payload["requested_by_actor_type"], INTENT_ACTOR_TYPES),
        }
    if action in {"quiet", "restore_normal"}:
        payload = _require_fields(value, LIFECYCLE_PAYLOAD_FIELDS, "lifecycle_payload")
        if payload["payload_schema_version"] != LIFECYCLE_PAYLOAD_SCHEMA_VERSION:
            raise durable.HouseMemoryDurableEventError(
                "payload_schema_mismatch", "Lifecycle payload schema is unsupported."
            )
        return {"payload_schema_version": LIFECYCLE_PAYLOAD_SCHEMA_VERSION}
    if action in {"automatic_cooling", "automatic_quiet", "lifecycle_wakeup"}:
        payload = _require_fields(value, AUTOMATIC_LIFECYCLE_PAYLOAD_FIELDS, "automatic_lifecycle_payload")
        if payload["payload_schema_version"] != AUTOMATIC_LIFECYCLE_PAYLOAD_SCHEMA_VERSION:
            raise durable.HouseMemoryDurableEventError("payload_schema_mismatch", "Automatic lifecycle payload schema is unsupported.")
        inputs = _require_fields(payload["reason_inputs"], AUTOMATIC_LIFECYCLE_REASON_INPUT_FIELDS, "automatic_lifecycle_reason_inputs")
        normalized_inputs: dict[str, Any] = {}
        for field in ("record_age_seconds", "lifecycle_state_age_seconds", "last_eligible_use_age_seconds",
                      "inactivity_age_seconds", "use_count", "ignored_count"):
            value = inputs[field]
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 3_153_600_000:
                raise durable.HouseMemoryDurableEventError("invalid_lifecycle_reason_input", "Lifecycle reason input is outside its bound.")
            normalized_inputs[field] = value
        for field in ("eligible_use_observed", "unknown_use", "wakeup_evidence"):
            if not isinstance(inputs[field], bool):
                raise durable.HouseMemoryDurableEventError("invalid_lifecycle_reason_input", "Lifecycle reason input must be boolean.")
            normalized_inputs[field] = inputs[field]
        classes = inputs["protected_class_codes"]
        if (not isinstance(classes, list) or classes != sorted(set(classes))
                or any(item not in AUTOMATIC_PROTECTED_CLASSES for item in classes)):
            raise durable.HouseMemoryDurableEventError("invalid_lifecycle_reason_input", "Protected class codes are invalid.")
        normalized_inputs["protected_class_codes"] = list(classes)
        reasons = payload["reason_codes"]
        if (not isinstance(reasons, list) or not reasons or len(reasons) > 8
                or reasons != list(dict.fromkeys(reasons))
                or any(reason not in AUTOMATIC_LIFECYCLE_REASONS for reason in reasons)):
            raise durable.HouseMemoryDurableEventError("invalid_lifecycle_reason_codes", "Lifecycle reason codes are invalid.")
        prior = _code("prior_lifecycle_state", payload["prior_lifecycle_state"], AUTOMATIC_LIFECYCLE_STATES)
        next_state = _code("next_lifecycle_state", payload["next_lifecycle_state"], AUTOMATIC_LIFECYCLE_STATES)
        expected = {"automatic_cooling": ("active", "cooling"), "automatic_quiet": ("cooling", "quiet")}
        if action in expected and (prior, next_state) != expected[action]:
            raise durable.HouseMemoryDurableEventError("invalid_lifecycle_transition", "Automatic lifecycle transition is invalid.")
        if action == "lifecycle_wakeup" and (prior not in {"cooling", "quiet"} or next_state != "active"):
            raise durable.HouseMemoryDurableEventError("invalid_lifecycle_transition", "Lifecycle wakeup transition is invalid.")
        proposal_id = payload["transition_proposal_id"]
        if (not isinstance(proposal_id, str) or len(proposal_id) != 73 or not proposal_id.startswith("lifeprop_")
                or any(c not in "0123456789abcdef" for c in proposal_id[9:])):
            raise durable.HouseMemoryDurableEventError("invalid_transition_proposal_id", "Transition proposal identity is invalid.")
        proposal_ref = _hash("transition_proposal_ref_hash", payload["transition_proposal_ref_hash"])
        if proposal_ref != durable.canonical_sha256({"transition_proposal_id": proposal_id}):
            raise durable.HouseMemoryDurableEventError("transition_proposal_ref_mismatch", "Transition proposal ref is invalid.")
        if event["action_ref_hash"] != proposal_ref:
            raise durable.HouseMemoryDurableEventError("transition_action_ref_mismatch", "Lifecycle action must bind the proposal ref.")
        policy_time = payload["policy_evaluated_at"]
        if not isinstance(policy_time, str) or len(policy_time) > 40 or not policy_time.endswith("Z"):
            raise durable.HouseMemoryDurableEventError("invalid_policy_time", "Policy evaluation time is invalid.")
        try:
            parsed_policy_time = datetime.fromisoformat(policy_time.replace("Z", "+00:00"))
        except ValueError as exc:
            raise durable.HouseMemoryDurableEventError("invalid_policy_time", "Policy evaluation time is invalid.") from exc
        if (parsed_policy_time.tzinfo is None
                or parsed_policy_time.utcoffset() != timezone.utc.utcoffset(parsed_policy_time)
                or parsed_policy_time.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z") != policy_time):
            raise durable.HouseMemoryDurableEventError("invalid_policy_time", "Policy evaluation time must be canonical UTC.")
        return {"payload_schema_version": AUTOMATIC_LIFECYCLE_PAYLOAD_SCHEMA_VERSION,
                "policy_version": _code("policy_version", payload["policy_version"]),
                "transition_proposal_id": proposal_id, "transition_proposal_ref_hash": proposal_ref,
                "prior_lifecycle_state": prior, "next_lifecycle_state": next_state,
                "policy_evaluated_at": policy_time, "reason_inputs": normalized_inputs,
                "reason_codes": list(reasons)}
    if action == "metadata_repair_reconciled":
        payload = _require_fields(
            value, METADATA_REPAIR_RECONCILIATION_PAYLOAD_FIELDS,
            "metadata_repair_reconciliation_payload",
        )
        if payload["payload_schema_version"] != METADATA_REPAIR_RECONCILIATION_PAYLOAD_SCHEMA_VERSION:
            raise durable.HouseMemoryDurableEventError(
                "payload_schema_mismatch", "Metadata repair reconciliation payload schema is unsupported."
            )
        normalized = {
            "payload_schema_version": METADATA_REPAIR_RECONCILIATION_PAYLOAD_SCHEMA_VERSION,
            "prior_canonical_record_version_hash": _hash(
                "prior_canonical_record_version_hash", payload["prior_canonical_record_version_hash"]
            ),
            "new_canonical_record_version_hash": _hash(
                "new_canonical_record_version_hash", payload["new_canonical_record_version_hash"]
            ),
            "operation_ref_hash": _hash("operation_ref_hash", payload["operation_ref_hash"]),
            "audit_ref_hash": _hash("audit_ref_hash", payload["audit_ref_hash"]),
            "marker_ref_hash": _hash("marker_ref_hash", payload["marker_ref_hash"]),
        }
        if normalized["new_canonical_record_version_hash"] != event["canonical_record_version_hash"]:
            raise durable.HouseMemoryDurableEventError(
                "repair_version_mismatch", "Reconciliation event must bind the repaired canonical version."
            )
        if normalized["operation_ref_hash"] != event["action_ref_hash"]:
            raise durable.HouseMemoryDurableEventError(
                "repair_operation_ref_mismatch", "Reconciliation operation must bind its durable action."
            )
        if normalized["prior_canonical_record_version_hash"] == normalized["new_canonical_record_version_hash"]:
            raise durable.HouseMemoryDurableEventError(
                "repair_version_unchanged", "Reconciliation requires an actual canonical version change."
            )
        return normalized
    if action in {"relation_asserted", "relation_retracted"}:
        if isinstance(value, Mapping) and value.get("payload_schema_version") == RELATION_PAYLOAD_V2_SCHEMA_VERSION:
            payload = _require_fields(value, RELATION_PAYLOAD_V2_FIELDS, "relation_payload_v2")
            left, right = canonical_relation_endpoints(payload["left_memory_ref_hash"], payload["right_memory_ref_hash"], payload["relation_type"])
            fields = {key: payload[key] for key in payload}
            if left != payload["left_memory_ref_hash"]:
                for suffix in ("canonical_record_version_hash", "authority_scope_code", "authority_owner_code"):
                    fields[f"left_{suffix}"], fields[f"right_{suffix}"] = fields[f"right_{suffix}"], fields[f"left_{suffix}"]
            fields["left_memory_ref_hash"], fields["right_memory_ref_hash"] = left, right
            for name in ("left_canonical_record_version_hash", "right_canonical_record_version_hash", "evidence_ref_hash"):
                fields[name] = _hash(name, fields[name])
            for name in ("left_authority_scope_code", "right_authority_scope_code"):
                fields[name] = _code(name, fields[name], AUTHORITY_SCOPES)
            for name in ("left_authority_owner_code", "right_authority_owner_code"):
                fields[name] = _code(name, fields[name], AUTHORITY_OWNERS)
            fields["participant_scope_code"] = _code("participant_scope_code", fields["participant_scope_code"], PARTICIPANT_SCOPES)
            fields["audience_scope_code"] = _code("audience_scope_code", fields["audience_scope_code"], AUDIENCE_SCOPES)
            fields["relation_type"] = _code("relation_type", fields["relation_type"], RELATION_TYPES)
            fields["evidence_class"] = _code("evidence_class", fields["evidence_class"])
            if isinstance(fields["strength_milli"], bool) or not isinstance(fields["strength_milli"], int) or not 0 <= fields["strength_milli"] <= 1000:
                raise durable.HouseMemoryDurableEventError("invalid_relation_strength", "Relation strength must be 0..1000.")
            expected = compute_relation_ref_v2(
                left_memory_ref_hash=left, right_memory_ref_hash=right, relation_type=fields["relation_type"],
                participant_scope_code=fields["participant_scope_code"], audience_scope_code=fields["audience_scope_code"],
                left_authority_scope_code=fields["left_authority_scope_code"], left_authority_owner_code=fields["left_authority_owner_code"],
                right_authority_scope_code=fields["right_authority_scope_code"], right_authority_owner_code=fields["right_authority_owner_code"])
            if fields["relation_ref_hash"] != expected:
                raise durable.HouseMemoryDurableEventError("relation_ref_mismatch", "Relation ref does not match its logical identity.")
            fields["relation_ref_hash"] = expected
            return {key: fields[key] for key in sorted(fields)}
        payload = _require_fields(value, RELATION_PAYLOAD_FIELDS, "relation_payload")
        if payload["payload_schema_version"] != RELATION_PAYLOAD_SCHEMA_VERSION:
            raise durable.HouseMemoryDurableEventError("payload_schema_mismatch", "Relation payload schema is unsupported.")
        left, right = canonical_relation_endpoints(
            payload["left_memory_ref_hash"], payload["right_memory_ref_hash"], payload["relation_type"]
        )
        left_version = _hash("left_canonical_record_version_hash", payload["left_canonical_record_version_hash"])
        right_version = _hash("right_canonical_record_version_hash", payload["right_canonical_record_version_hash"])
        if left != payload["left_memory_ref_hash"]:
            left_version, right_version = right_version, left_version
        strength = payload["strength_milli"]
        if isinstance(strength, bool) or not isinstance(strength, int) or not 0 <= strength <= 1000:
            raise durable.HouseMemoryDurableEventError("invalid_relation_strength", "Relation strength must be 0..1000.")
        expected_ref = compute_relation_ref(
            left_memory_ref_hash=left, right_memory_ref_hash=right, relation_type=payload["relation_type"],
            participant_scope_code=event["participant_scope_code"], authority_scope_code=event["authority_scope_code"],
            authority_owner_code=event["authority_owner_code"], audience_scope_code=event["audience_scope_code"],
        )
        if payload["relation_ref_hash"] != expected_ref:
            raise durable.HouseMemoryDurableEventError("relation_ref_mismatch", "Relation ref does not match its logical identity.")
        return {
            "payload_schema_version": RELATION_PAYLOAD_SCHEMA_VERSION,
            "evidence_ref_hash": _hash("evidence_ref_hash", payload["evidence_ref_hash"]),
            "left_canonical_record_version_hash": left_version,
            "left_memory_ref_hash": left,
            "relation_ref_hash": expected_ref,
            "relation_type": _code("relation_type", payload["relation_type"], RELATION_TYPES),
            "right_canonical_record_version_hash": right_version,
            "right_memory_ref_hash": right,
            "strength_milli": strength,
        }
    if action == "reviewed_evolution_applied":
        payload = _require_fields(value, EVOLUTION_APPLIED_PAYLOAD_FIELDS, "evolution_applied_payload")
        if payload["payload_schema_version"] != EVOLUTION_APPLIED_PAYLOAD_SCHEMA_VERSION:
            raise durable.HouseMemoryDurableEventError("payload_schema_mismatch", "Evolution applied payload schema is unsupported.")
        normalized = {
            "payload_schema_version": EVOLUTION_APPLIED_PAYLOAD_SCHEMA_VERSION,
            "candidate_id": _hash("candidate_id", payload["candidate_id"]),
            "candidate_version_hash": _hash("candidate_version_hash", payload["candidate_version_hash"]),
            "evolution_kind": _code("evolution_kind", payload["evolution_kind"], EVOLUTION_KINDS),
            "primary_memory_ref_hash": _hash("primary_memory_ref_hash", payload["primary_memory_ref_hash"]),
            "primary_applied_version_hash": _hash("primary_applied_version_hash", payload["primary_applied_version_hash"]),
            "comparison_memory_ref_hash": _hash("comparison_memory_ref_hash", payload["comparison_memory_ref_hash"]),
            "comparison_applied_version_hash": _hash("comparison_applied_version_hash", payload["comparison_applied_version_hash"]),
            "approved_by_actor_type": _code("approved_by_actor_type", payload["approved_by_actor_type"], frozenset({"astel", "solen"})),
            "approved_by_actor_ref_hash": _hash("approved_by_actor_ref_hash", payload["approved_by_actor_ref_hash"]),
            "approval_authority_scope_code": _code("approval_authority_scope_code", payload["approval_authority_scope_code"], AUTHORITY_SCOPES),
            "approval_authority_owner_code": _code("approval_authority_owner_code", payload["approval_authority_owner_code"], AUTHORITY_OWNERS),
            "approval_evidence_ref_hash": _hash("approval_evidence_ref_hash", payload["approval_evidence_ref_hash"]),
            "source_evidence_ref_hash": _hash("source_evidence_ref_hash", payload["source_evidence_ref_hash"]),
            "provenance_evidence_ref_hash": _hash("provenance_evidence_ref_hash", payload["provenance_evidence_ref_hash"]),
            "resolution_code": _code("resolution_code", payload["resolution_code"], EVOLUTION_RESOLUTION_CODES),
            "disposition_code": _code("disposition_code", payload["disposition_code"], EVOLUTION_DISPOSITION_CODES),
        }
        if normalized["primary_memory_ref_hash"] == normalized["comparison_memory_ref_hash"]:
            raise durable.HouseMemoryDurableEventError("evolution_self_comparison", "Evolution resolution requires two records.")
        if normalized["resolution_code"] != EVOLUTION_KIND_RESOLUTION_CODES[normalized["evolution_kind"]]:
            raise durable.HouseMemoryDurableEventError(
                "evolution_kind_resolution_mismatch", "Evolution kind and resolution must describe the same reviewed action."
            )
        expected_approval = (("reviewed_memory", "astel") if normalized["approved_by_actor_type"] == "astel"
                             else ("solen_active_memory", normalized["approval_authority_owner_code"]))
        if ((normalized["approval_authority_scope_code"], normalized["approval_authority_owner_code"]) != expected_approval
                or (normalized["approved_by_actor_type"] == "solen"
                    and normalized["approval_authority_owner_code"] not in {"solen", "house_standing_consent"})
                or event["actor_type"] != normalized["approved_by_actor_type"]
                or event["actor_ref_hash"] != normalized["approved_by_actor_ref_hash"]
                or event["authority_scope_code"] != normalized["approval_authority_scope_code"]
                or event["authority_owner_code"] != normalized["approval_authority_owner_code"]):
            raise durable.HouseMemoryDurableEventError("evolution_approval_authority_invalid", "Evolution approval authority is invalid.")
        for name in ("core_involved", "core_check_needed", "canonical_record_changed", "core_moved_or_removed"):
            if not isinstance(payload[name], bool):
                raise durable.HouseMemoryDurableEventError("invalid_evolution_boolean", "Evolution safety flags must be boolean.")
            normalized[name] = payload[name]
        if normalized["canonical_record_changed"] or normalized["core_moved_or_removed"]:
            raise durable.HouseMemoryDurableEventError("evolution_projection_mutation_forbidden", "Applied-resolution evidence cannot claim canonical or Core mutation.")
        if normalized["core_involved"] != normalized["core_check_needed"]:
            raise durable.HouseMemoryDurableEventError("evolution_core_state_invalid", "Core involvement must remain check-needed.")
        if normalized["core_check_needed"] and normalized["disposition_code"] != "check_needed":
            raise durable.HouseMemoryDurableEventError("evolution_core_disposition_invalid", "Core evolution must remain check-needed.")
        expected_ref = compute_evolution_resolution_ref(**{key: normalized[key] for key in (
            "candidate_id", "candidate_version_hash", "evolution_kind", "primary_memory_ref_hash",
            "primary_applied_version_hash", "comparison_memory_ref_hash", "comparison_applied_version_hash",
            "resolution_code", "disposition_code")})
        if payload["resolution_ref_hash"] != expected_ref:
            raise durable.HouseMemoryDurableEventError("evolution_resolution_ref_mismatch", "Evolution resolution ref does not match its identity.")
        if event["action_ref_hash"] != expected_ref or event["memory_ref_hash"] != normalized["primary_memory_ref_hash"]:
            raise durable.HouseMemoryDurableEventError("evolution_envelope_mismatch", "Evolution envelope must bind its resolution and primary record.")
        return {"resolution_ref_hash": expected_ref, **normalized}
    payload = _require_fields(value, PROPOSAL_PAYLOAD_FIELDS, "proposal_payload")
    if payload["payload_schema_version"] != PROPOSAL_PAYLOAD_SCHEMA_VERSION:
        raise durable.HouseMemoryDurableEventError("payload_schema_mismatch", "Proposal payload schema is unsupported.")
    normalized = {
        "payload_schema_version": PROPOSAL_PAYLOAD_SCHEMA_VERSION,
        "candidate_ref_hash": _hash("candidate_ref_hash", payload["candidate_ref_hash"]),
        "comparison_canonical_record_version_hash": _hash("comparison_canonical_record_version_hash", payload["comparison_canonical_record_version_hash"]),
        "comparison_memory_ref_hash": _hash("comparison_memory_ref_hash", payload["comparison_memory_ref_hash"]),
        "primary_canonical_record_version_hash": _hash("primary_canonical_record_version_hash", payload["primary_canonical_record_version_hash"]),
        "primary_memory_ref_hash": _hash("primary_memory_ref_hash", payload["primary_memory_ref_hash"]),
        "proposal_basis": _code("proposal_basis", payload["proposal_basis"], PROPOSAL_BASES),
        "proposal_kind": _code("proposal_kind", payload["proposal_kind"], PROPOSAL_KINDS),
        "proposal_origin_action_ref_hash": _hash("proposal_origin_action_ref_hash", payload["proposal_origin_action_ref_hash"]),
    }
    if normalized["primary_memory_ref_hash"] == normalized["comparison_memory_ref_hash"]:
        raise durable.HouseMemoryDurableEventError("proposal_self_comparison", "A proposal requires two records.")
    if normalized["candidate_ref_hash"] in {
        normalized["primary_memory_ref_hash"], normalized["comparison_memory_ref_hash"]
    }:
        raise durable.HouseMemoryDurableEventError(
            "proposal_candidate_endpoint_collision", "Proposal candidate ref must differ from both endpoints."
        )
    if action == "evolution_proposal_created" and normalized["proposal_origin_action_ref_hash"] != event["action_ref_hash"]:
        raise durable.HouseMemoryDurableEventError(
            "proposal_origin_action_mismatch", "A created proposal must bind its creating action ref."
        )
    expected_ref = compute_proposal_ref(action_ref_hash=normalized["proposal_origin_action_ref_hash"], **{
        key: normalized[key] for key in (
            "proposal_kind", "primary_memory_ref_hash", "primary_canonical_record_version_hash",
            "comparison_memory_ref_hash", "comparison_canonical_record_version_hash", "candidate_ref_hash"
        )
    })
    if payload["proposal_ref_hash"] != expected_ref:
        raise durable.HouseMemoryDurableEventError("proposal_ref_mismatch", "Proposal ref does not match its identity.")
    return {"proposal_ref_hash": expected_ref, **normalized}


def _identity_basis(event: Mapping[str, Any]) -> dict[str, Any]:
    return {key: event[key] for key in sorted(EVENT_FIELDS - {"event_id"})}


def compute_event_id(event: Mapping[str, Any]) -> str:
    return durable.EVENT_ID_PREFIX + durable.canonical_sha256(_identity_basis(event))[:32]


def _validate_scope_combination(event: Mapping[str, Any]) -> None:
    axes = (
        event["participant_scope_code"], event["authority_scope_code"],
        event["authority_owner_code"], event["audience_scope_code"], event["actor_type"],
    )
    has_synthetic = "synthetic_test" in axes
    payload = event["payload"]
    intent_types = (
        payload.get("requested_by_actor_type"), payload.get("approved_by_actor_type")
    )
    historical_tuple = event["status_code"] == "superseded" or event["review_state_code"] == "stale"
    historical_observation = (
        event["action_code"] == "record_version_observed"
        and event["status_code"] == "superseded"
        and event["review_state_code"] == "stale"
    )
    if historical_tuple and not historical_observation:
        raise durable.HouseMemoryDurableEventError(
            "invalid_historical_state", "Historical state requires one superseded stale version observation."
        )
    if historical_observation:
        if "stale_or_superseded" not in event["blocker_flags"]:
            raise durable.HouseMemoryDurableEventError(
                "historical_blocker_missing", "A superseded observation requires its historical blocker."
            )
        forbidden = {
            "standing_footing_eligible", "default_surfacing_eligible", "explicit_search_eligible",
            "manual_lookup_eligible", "exact_recall_eligible",
        }.intersection(event["safe_capability_flags"])
        if forbidden:
            raise durable.HouseMemoryDurableEventError(
                "historical_capability_forbidden", "A superseded observation cannot claim active or lookup capability."
            )
    if has_synthetic or "synthetic_test" in intent_types:
        if any(value != "synthetic_test" for value in axes) or any(
            value is not None and value != "synthetic_test" for value in intent_types
        ):
            raise durable.HouseMemoryDurableEventError(
                "synthetic_real_scope_mismatch", "Synthetic identities cannot be mixed with real scopes."
            )
        return
    accepted_historical_authority = (
        historical_observation
        and event["authority_scope_code"] == "reviewed_memory"
        and event["authority_owner_code"] in {"astel", "solen", "astel_solen"}
    )
    accepted_authority = accepted_historical_authority or (
        event["authority_scope_code"] == "reviewed_memory"
        and event["review_state_code"] == "reviewed"
        and event["authority_owner_code"] in {"astel", "solen", "astel_solen"}
    ) or (
        event["authority_scope_code"] == "solen_active_memory"
        and event["review_state_code"] == "standing_consent_active"
        and event["authority_owner_code"] in {"solen", "house_standing_consent"}
    ) or (
        event["authority_scope_code"] == "candidate_only"
        and event["review_state_code"] == "reviewed"
        and event["authority_owner_code"] in {"astel", "solen", "astel_solen"}
    )
    if not accepted_authority:
        raise durable.HouseMemoryDurableEventError(
            "invalid_authority_review_combination", "Authority and review state combination is invalid."
        )
    if event["action_code"] in {"set_core", "remove_core"}:
        if "house_backend" in intent_types:
            raise durable.HouseMemoryDurableEventError(
                "backend_core_intent_forbidden", "The backend cannot request or approve Core."
            )
        actor_identity = (event["actor_type"], event["actor_ref_hash"])
        intent_identities = {
            (payload["requested_by_actor_type"], payload["requested_by_actor_ref_hash"]),
            (payload["approved_by_actor_type"], payload["approved_by_actor_ref_hash"]),
        }
        if event["actor_type"] != "house_backend" and actor_identity not in intent_identities:
            raise durable.HouseMemoryDurableEventError(
                "unrelated_core_executor", "Core executor must be the backend or a bound intent actor."
            )


def normalize_event(value: Any, *, verify_identity: bool = True) -> dict[str, Any]:
    source = _require_fields(value, EVENT_FIELDS, "event")
    if source["schema_version"] != EVENT_SCHEMA_VERSION:
        raise durable.HouseMemoryDurableEventError("invalid_schema_version", "Event schema version is unsupported.")
    # Reuse Gate 1's strict scalar validation through a temporary v0-shaped event.
    base = durable.normalize_event(
        {
            key: source[key] for key in durable.EVENT_FIELDS
        } | {"schema_version": durable.EVENT_SCHEMA_VERSION, "event_id": durable.EVENT_ID_PREFIX + "0" * 32,
             "participant_scope_code": "synthetic_test", "authority_scope_code": "synthetic_test",
             "audience_scope_code": "synthetic_test", "actor_type": "synthetic_test",
             "status_code": "approved", "review_state_code": "reviewed", "action_code": "record_observed"},
        verify_identity=False,
    )
    event = {
        **{key: base[key] for key in durable.EVENT_FIELDS if key not in {
            "schema_version", "event_id", "action_code", "actor_type", "participant_scope_code",
            "authority_scope_code", "audience_scope_code", "status_code", "review_state_code"
        }},
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": str(source["event_id"]),
        "action_code": _code("action_code", source["action_code"], ACTION_CODES),
        "actor_type": _code("actor_type", source["actor_type"], ACTOR_TYPES),
        "participant_scope_code": _code("participant_scope_code", source["participant_scope_code"], PARTICIPANT_SCOPES),
        "authority_scope_code": _code("authority_scope_code", source["authority_scope_code"], AUTHORITY_SCOPES),
        "authority_owner_code": _code("authority_owner_code", source["authority_owner_code"], AUTHORITY_OWNERS),
        "audience_scope_code": _code("audience_scope_code", source["audience_scope_code"], AUDIENCE_SCOPES),
        "status_code": _code("status_code", source["status_code"], CURATED_STATUS_CODES),
        "review_state_code": _code("review_state_code", source["review_state_code"], CURATED_REVIEW_STATES),
    }
    event["payload"] = _normalize_payload(event["action_code"], source["payload"], event)
    _validate_scope_combination(event)
    expected = compute_event_id(event)
    if durable._EVENT_ID_RE.fullmatch(event["event_id"]) is None:
        raise durable.HouseMemoryDurableEventError("invalid_event_id", "Event id is invalid.")
    if verify_identity and event["event_id"] != expected:
        raise durable.HouseMemoryDurableEventError("event_identity_mismatch", "Event identity does not match its fields.")
    return {key: event[key] for key in sorted(EVENT_FIELDS)}


def build_event(**values: Any) -> dict[str, Any]:
    candidate = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": durable.EVENT_ID_PREFIX + "0" * 32,
        "participant_scope_code": "synthetic_test", "authority_scope_code": "synthetic_test",
        "authority_owner_code": "synthetic_test", "audience_scope_code": "synthetic_test",
        "status_code": "approved", "review_state_code": "reviewed", "reason_code": "synthetic_observation",
        "provenance_present": True, "blocker_flags": [], "safe_capability_flags": [],
        "payload": {"payload_schema_version": OBSERVATION_PAYLOAD_SCHEMA_VERSION},
        **values,
    }
    normalized = normalize_event(candidate, verify_identity=False)
    normalized["event_id"] = compute_event_id(normalized)
    return normalize_event(normalized)
