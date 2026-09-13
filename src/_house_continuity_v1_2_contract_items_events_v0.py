"""Item, scope, creation-seed, and event-chain contracts for Continuity V1.2."""

from __future__ import annotations

from _house_continuity_v1_2_contract_primitives_v0 import *
from _house_continuity_v1_2_contract_primitives_v0 import validate_authored_reason

CREATION_SEED_SCHEMA_VERSION = "house_continuity_creation_seed_registry_v1"

SCOPE_BINDING_SCHEMA_VERSION = "house_continuity_scope_binding_v1"

WORKING_SET_ITEM_SCHEMA_VERSION = "house_continuity_working_set_item_v1_2"

WORKING_SET_EVENT_SCHEMA_VERSION = "house_continuity_event_v1_1"

SCOPE_BINDING_EVENT_SCHEMA_VERSION = (
    "house_continuity_scope_binding_event_v1_1"
)

ITEM_KINDS = (
    "active_topic",
    "active_task",
    "question",
    "commitment",
    "decision",
    "temporary_fact",
    "emotional_thread",
    "pending_review",
    "completed_tool_result_ref",
)

SOLEN_CREATABLE_KINDS = tuple(
    kind for kind in ITEM_KINDS if kind != "completed_tool_result_ref"
)

LIFECYCLE_STATES = (
    "active",
    "resolved",
    "superseded",
    "abandoned",
    "expired",
)

SEMANTIC_OPERATION_KINDS = (
    "create",
    "confirm",
    "revise",
    "resolve",
    "supersede",
    "reopen",
)

WORKING_SET_EVENT_KINDS = SEMANTIC_OPERATION_KINDS + (
    "abandon",
    "expire",
    "attest_joint",
    "mark_cleanup_eligible",
    "merge_disjoint",
    "conflict_recorded",
    "scope_rebind_reference",
)

RESOLUTION_REASONS = (
    "completed",
    "answered",
    "settled",
    "withdrawn",
    "no_longer_needed",
)

SUMMARY_MAX_CHARS = 700

MAX_LINKED_ITEM_IDS = 12

_PAYLOAD_FIELDS = {
    "active_topic": ("topic_state", "linked_item_ids"),
    "active_task": (
        "task_state",
        "linked_item_ids",
        "completion_evidence_refs",
    ),
    "question": ("question_owner", "answer_state", "linked_item_ids"),
    "commitment": ("committed_by", "commitment_state", "linked_item_ids"),
    "decision": ("decision_state", "decision_scope", "linked_item_ids"),
    "temporary_fact": ("fact_state", "source_class", "linked_item_ids"),
    "emotional_thread": ("thread_state", "expressed_by", "linked_item_ids"),
    "pending_review": (
        "review_kind",
        "conflicting_item_ids",
        "conflicting_event_ids",
        "linked_item_ids",
    ),
    "completed_tool_result_ref": (
        "task_item_id",
        "operation_ref",
        "operation_state",
        "result_summary",
        "result_ref_sha256",
    ),
}

_PAYLOAD_ENUMS = {
    "active_topic": {"topic_state": ("current", "paused")},
    "active_task": {
        "task_state": ("not_started", "in_progress", "blocked", "waiting")
    },
    "question": {
        "question_owner": ("astel", "solen", "shared", "unknown"),
        "answer_state": (
            "unanswered",
            "partially_answered",
            "awaiting_confirmation",
        ),
    },
    "commitment": {
        "committed_by": ("astel", "solen", "shared"),
        "commitment_state": ("pending", "in_progress", "blocked"),
    },
    "decision": {
        "decision_state": ("provisional", "accepted", "contested")
    },
    "temporary_fact": {
        "fact_state": ("observed", "reported", "uncertain")
    },
    "emotional_thread": {
        "thread_state": ("open", "held", "needs_return"),
        "expressed_by": ("astel", "solen", "shared", "uncertain"),
    },
    "pending_review": {
        "review_kind": (
            "parallel_conflict",
            "scope_conflict",
            "contradiction",
            "uncertain_resolution",
            "possible_duplicate",
        )
    },
    "completed_tool_result_ref": {
        "operation_state": ("completed", "failed", "cancelled")
    },
}

_EVENT_CHAIN_FIELDS = frozenset(
    {
        "event_payload_sha256",
        "global_event_sequence",
        "prior_global_event_sha256",
        "global_event_sha256",
        "item_event_sequence",
        "prior_item_event_sha256",
        "item_event_sha256",
        "binding_event_sequence",
        "prior_binding_event_sha256",
        "binding_event_sha256",
    }
)

def validate_item_kind_payload(
    item_kind: str,
    value: Any,
    *,
    partial: bool = False,
) -> dict[str, Any]:
    kind = _code(item_kind, name="item_kind", allowed=ITEM_KINDS)
    if not isinstance(value, Mapping):
        _error("invalid_kind_payload", "kind_payload must be an object.")
    _reject_private(value, path="kind_payload")
    allowed = set(_PAYLOAD_FIELDS[kind])
    if not set(value).issubset(allowed):
        _error("invalid_kind_payload_fields", "Unknown or cross-kind payload field.")
    if not partial and set(value) != allowed:
        _error("invalid_kind_payload_fields", "Kind payload fields are incomplete.")
    if partial and not value:
        return {}
    result: dict[str, Any] = {}
    for field, choices in _PAYLOAD_ENUMS[kind].items():
        if field in value:
            result[field] = _code(value[field], name=field, allowed=choices)
    for field in (
        "linked_item_ids",
        "completion_evidence_refs",
        "conflicting_item_ids",
    ):
        if field in value:
            result[field] = _id_list(
                value[field],
                name=field,
                maximum=MAX_LINKED_ITEM_IDS,
                kind="item_id" if field != "completion_evidence_refs" else None,
            )
    if "conflicting_event_ids" in value:
        result["conflicting_event_ids"] = _id_list(
            value["conflicting_event_ids"],
            name="conflicting_event_ids",
            maximum=MAX_LINKED_ITEM_IDS,
            kind="event_id",
        )
    if kind == "decision" and "decision_scope" in value:
        result["decision_scope"] = _string(
            value["decision_scope"],
            name="decision_scope",
            maximum=160,
        )
    if kind == "temporary_fact" and "source_class" in value:
        result["source_class"] = _string(
            value["source_class"], name="source_class", maximum=160
        )
    if kind == "completed_tool_result_ref":
        if "task_item_id" in value:
            result["task_item_id"] = _id(
                value["task_item_id"], name="task_item_id", kind="item_id"
            )
        if "operation_ref" in value:
            result["operation_ref"] = _id(
                value["operation_ref"], name="operation_ref"
            )
        if "result_summary" in value:
            result["result_summary"] = _string(
                value["result_summary"],
                name="result_summary",
                maximum=600,
            )
        if "result_ref_sha256" in value:
            result["result_ref_sha256"] = _hash(
                value["result_ref_sha256"],
                name="result_ref_sha256",
            )
    return result

def validate_creation_seed_registry(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "entity_kind",
            "entity_id",
            "creation_seed_sha256",
            "created_at",
        ),
        path="creation_seed_registry",
    )
    if raw["schema_version"] != CREATION_SEED_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported seed registry.")
    entity_kind = _code(
        raw["entity_kind"],
        name="entity_kind",
        allowed=(
            "project",
            "thread",
            "room",
            "item",
            "event",
            "checkpoint",
            "selection_receipt",
            "proposal_batch",
            "proposal",
            "anchor",
            "capability",
            "joint_attestation",
            "unit_coverage",
            "outbox",
        ),
    )
    entity_id_kind = {
        "project": "project_id",
        "thread": "thread_id",
        "room": "room_id",
        "item": "item_id",
        "event": "event_id",
        "anchor": "anchor_id",
        "capability": "capability_id",
        "outbox": "bundle_id",
    }.get(entity_kind)
    return {
        "schema_version": CREATION_SEED_SCHEMA_VERSION,
        "entity_kind": entity_kind,
        "entity_id": _id(
            raw["entity_id"], name="entity_id", kind=entity_id_kind
        ),
        "creation_seed_sha256": _hash(
            raw["creation_seed_sha256"], name="creation_seed_sha256"
        ),
        "created_at": _timestamp(raw["created_at"], name="created_at"),
    }

def validate_creation_seed_collision(existing: Any, candidate: Any) -> dict[str, Any]:
    normalized_existing = validate_creation_seed_registry(existing)
    normalized_candidate = validate_creation_seed_registry(candidate)
    same_identity = (
        normalized_existing["entity_id"] == normalized_candidate["entity_id"]
    )
    if same_identity and (
        normalized_existing["creation_seed_sha256"]
        != normalized_candidate["creation_seed_sha256"]
        or normalized_existing["entity_kind"]
        != normalized_candidate["entity_kind"]
        or normalized_existing["entity_id"]
        != normalized_candidate["entity_id"]
    ):
        _error(
            "creation_seed_collision",
            "Truncated identity collides with a different full creation seed.",
        )
    return normalized_existing if same_identity else normalized_candidate

def validate_scope_binding(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "room_id",
            "project_id",
            "thread_id",
            "predecessor_room_id",
            "binding_source",
            "binding_revision",
            "idempotency_key",
            "created_at",
            "updated_at",
        ),
        path="scope_binding",
    )
    if raw["schema_version"] != SCOPE_BINDING_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported scope binding.")
    project_id = _nullable_id(
        raw["project_id"], name="project_id", kind="project_id"
    )
    thread_id = _nullable_id(
        raw["thread_id"], name="thread_id", kind="thread_id"
    )
    predecessor_room_id = _nullable_id(
        raw["predecessor_room_id"],
        name="predecessor_room_id",
        kind="room_id",
    )
    binding_source = _code(
        raw["binding_source"],
        name="binding_source",
        allowed=(
            "new_unbound",
            "explicit_project",
            "explicit_thread",
            "explicit_inherit",
            "reviewed_rebind",
        ),
    )
    if thread_id is not None and project_id is None:
        _error("invalid_scope_binding", "Thread binding requires project.")
    if binding_source == "new_unbound" and (
        project_id is not None or thread_id is not None
    ):
        _error("invalid_scope_binding", "New unbound binding has no scope IDs.")
    if binding_source in ("explicit_project", "explicit_thread") and (
        project_id is None
    ):
        _error("invalid_scope_binding", "Explicit binding requires project.")
    if binding_source == "explicit_thread" and thread_id is None:
        _error("invalid_scope_binding", "Explicit thread binding requires thread.")
    if binding_source == "explicit_inherit" and predecessor_room_id is None:
        _error(
            "invalid_scope_binding",
            "Explicit inheritance requires predecessor room lineage.",
        )
    created = _timestamp(raw["created_at"], name="created_at")
    updated = _timestamp(raw["updated_at"], name="updated_at")
    if _timestamp_value(updated) < _timestamp_value(created):
        _error("nonmonotonic_binding_timestamps", "Binding timestamps regress.")
    return {
        "schema_version": SCOPE_BINDING_SCHEMA_VERSION,
        "room_id": _id(raw["room_id"], name="room_id", kind="room_id"),
        "project_id": project_id,
        "thread_id": thread_id,
        "predecessor_room_id": predecessor_room_id,
        "binding_source": binding_source,
        "binding_revision": _integer(
            raw["binding_revision"], name="binding_revision", minimum=1
        ),
        "idempotency_key": _string(
            raw["idempotency_key"], name="idempotency_key", maximum=160
        ),
        "created_at": created,
        "updated_at": updated,
    }

def _nullable_timestamp(value: Any, *, name: str) -> str | None:
    return None if value is None else _timestamp(value, name=name)

def _authorship_evidence_ref(value: Any, *, index: int) -> dict[str, str]:
    raw = _exact(
        value,
        ("participant", "evidence_id", "event_id", "content_sha256"),
        path=f"authorship_evidence_refs[{index}]",
    )
    return {
        "participant": _code(
            raw["participant"],
            name="participant",
            allowed=("astel", "solen"),
        ),
        "evidence_id": _id(raw["evidence_id"], name="evidence_id"),
        "event_id": _id(raw["event_id"], name="event_id", kind="event_id"),
        "content_sha256": _hash(
            raw["content_sha256"], name="evidence_content_sha256"
        ),
    }

def validate_working_set_item(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "item_id",
            "creation_seed_sha256",
            "scope_kind",
            "room_id",
            "project_id",
            "thread_id",
            "item_kind",
            "lifecycle_state",
            "summary",
            "kind_payload",
            "authorship_kind",
            "author_participants",
            "semantic_authority_code",
            "command_owner",
            "authorship_evidence_refs",
            "derivation_owner",
            "derivation_version",
            "confidence_millis",
            "source_turn_ids",
            "source_room_ids",
            "source_operation_ids",
            "source_proposal_ids",
            "exact_anchor_refs",
            "revision",
            "base_event_id",
            "content_sha256",
            "idempotency_key",
            "created_at",
            "updated_at",
            "last_confirmed_at",
            "fresh_until",
            "aging_after",
            "dormant_after",
            "expires_at",
            "freshness_policy_code",
            "resolved_at",
            "abandoned_at",
            "resolution_reason_code",
            "abandonment_reason_code",
            "supersedes_item_ids",
            "superseded_by_item_id",
            "reopens_item_id",
            "cleanup_state",
            "cleanup_eligible_at",
            "provider_visible_eligible",
            "memory_vault_truth",
            "exact_evidence",
            "self_state",
            "action_permission",
            "raw_history_included",
        ),
        path="working_set_item",
    )
    if raw["schema_version"] != WORKING_SET_ITEM_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported Working-Set item.")
    kind = _code(raw["item_kind"], name="item_kind", allowed=ITEM_KINDS)
    summary = _string(
        raw["summary"], name="summary", maximum=SUMMARY_MAX_CHARS
    )
    payload = validate_item_kind_payload(kind, raw["kind_payload"])
    scope = normalize_scope(
        {
            "scope_kind": raw["scope_kind"],
            "room_id": raw["room_id"],
            "project_id": raw["project_id"],
            "thread_id": raw["thread_id"],
        },
        path="working_set_item.scope",
    )
    semantic = {
        "item_kind": kind,
        "scope": scope,
        "summary": summary,
        "kind_payload": payload,
    }
    content_hash = _hash(raw["content_sha256"], name="content_sha256")
    if canonical_sha256(semantic) != content_hash:
        _error("item_content_sha256_mismatch", "Item content digest differs.")
    authorship = _code(
        raw["authorship_kind"],
        name="authorship_kind",
        allowed=(
            "solen_explicit",
            "astel_explicit",
            "joint_explicit",
            "structured_client_event",
            "structured_tool_event",
        ),
    )
    if kind == "completed_tool_result_ref" and authorship != "structured_tool_event":
        _error(
            "completed_tool_result_authority_mismatch",
            "Completed tool results require structured-tool authority.",
        )
    participants = raw["author_participants"]
    if not isinstance(participants, list):
        _error("invalid_author_participants", "Participants must be a list.")
    normalized_participants = [
        _code(
            participant,
            name="author_participant",
            allowed=("astel", "solen"),
        )
        for participant in participants
    ]
    if normalized_participants not in (
        [],
        ["astel"],
        ["solen"],
        ["astel", "solen"],
    ):
        _error(
            "invalid_author_participants",
            "Participants must be the canonical exact set.",
        )
    semantic_authority = _code(
        raw["semantic_authority_code"],
        name="semantic_authority_code",
        allowed=("participant_authored", "structured_event"),
    )
    command_owner = _string(
        raw["command_owner"], name="command_owner", maximum=160
    )
    if not isinstance(raw["authorship_evidence_refs"], list):
        _error("invalid_authorship_evidence", "Evidence refs must be a list.")
    if len(raw["authorship_evidence_refs"]) > 2:
        _error("invalid_authorship_evidence", "Evidence refs exceed cap.")
    evidence = [
        _authorship_evidence_ref(item, index=index)
        for index, item in enumerate(raw["authorship_evidence_refs"])
    ]
    evidence_participants = [item["participant"] for item in evidence]
    expected_authorship = {
        "solen_explicit": (
            ["solen"],
            "participant_authored",
            "house_talk_continuity_authorship_intent_v1",
            ["solen"],
        ),
        "astel_explicit": (
            ["astel"],
            "participant_authored",
            "house_continuity_astel_explicit_command_v1",
            ["astel"],
        ),
        "joint_explicit": (
            ["astel", "solen"],
            "participant_authored",
            "house_continuity_joint_authorship_attestation_v1",
            ["astel", "solen"],
        ),
        "structured_client_event": (
            [],
            "structured_event",
            "house_continuity_structured_client_event_v1",
            [],
        ),
        "structured_tool_event": (
            [],
            "structured_event",
            "house_continuity_structured_tool_event_v1",
            [],
        ),
    }[authorship]
    if (
        normalized_participants != expected_authorship[0]
        or semantic_authority != expected_authorship[1]
        or command_owner != expected_authorship[2]
        or evidence_participants != expected_authorship[3]
    ):
        _error(
            "authorship_evidence_mismatch",
            "Authorship owner, participants, and evidence must match exactly.",
        )
    base_event_id = _id(
        raw["base_event_id"], name="base_event_id", kind="event_id"
    )
    for ref in evidence:
        if ref["content_sha256"] != content_hash:
            _error(
                "stale_authorship_evidence",
                "Participant evidence must be current for this exact revision.",
            )
    if authorship == "joint_explicit" and (
        len({ref["evidence_id"] for ref in evidence}) != 2
        or len({ref["event_id"] for ref in evidence}) != 2
    ):
        _error(
            "nonindependent_joint_evidence",
            "Joint item requires independent participant evidence.",
        )
    derivation_owner = raw["derivation_owner"]
    derivation_version = raw["derivation_version"]
    if derivation_owner is not None or derivation_version is not None:
        _error(
            "authoritative_derivation_forbidden",
            "Authoritative projection cannot contain shadow derivation ownership.",
        )
    created = _timestamp(raw["created_at"], name="created_at")
    updated = _timestamp(raw["updated_at"], name="updated_at")
    confirmed = _timestamp(
        raw["last_confirmed_at"], name="last_confirmed_at"
    )
    fresh = _timestamp(raw["fresh_until"], name="fresh_until")
    aging = _timestamp(raw["aging_after"], name="aging_after")
    dormant = _timestamp(raw["dormant_after"], name="dormant_after")
    expires = _nullable_timestamp(raw["expires_at"], name="expires_at")
    update_axis = [
        _timestamp_value(created),
        _timestamp_value(confirmed),
        _timestamp_value(updated),
    ]
    freshness_axis = [
        _timestamp_value(confirmed),
        _timestamp_value(fresh),
        _timestamp_value(aging),
        _timestamp_value(dormant),
    ]
    if update_axis != sorted(update_axis) or freshness_axis != sorted(
        freshness_axis
    ):
        _error("nonmonotonic_item_timestamps", "Item timestamps regress.")
    if expires is not None and _timestamp_value(expires) < _timestamp_value(dormant):
        _error("invalid_item_expiry", "Expiry precedes dormancy.")
    freshness_policy = _code(
        raw["freshness_policy_code"],
        name="freshness_policy_code",
        allowed=tuple(f"{item}_v1_1" for item in ITEM_KINDS),
    )
    if freshness_policy != f"{kind}_v1_1":
        _error(
            "freshness_policy_kind_mismatch",
            "Freshness policy must match the exact item kind.",
        )
    if (
        kind
        in (
            "active_topic",
            "active_task",
            "question",
            "commitment",
            "decision",
            "emotional_thread",
            "pending_review",
        )
        and semantic_authority == "participant_authored"
        and expires is not None
    ):
        _error(
            "participant_semantic_hard_expiry_forbidden",
            "Participant semantic items become dormant, not time-terminal.",
        )
    if kind in ("temporary_fact", "completed_tool_result_ref") and expires is None:
        _error(
            "bounded_hard_expiry_required",
            "Bounded temporary and completed-result references require expiry.",
        )
    lifecycle = _code(
        raw["lifecycle_state"],
        name="lifecycle_state",
        allowed=LIFECYCLE_STATES,
    )
    resolved_at = _nullable_timestamp(raw["resolved_at"], name="resolved_at")
    abandoned_at = _nullable_timestamp(
        raw["abandoned_at"], name="abandoned_at"
    )
    resolution_reason = validate_authored_reason(
        raw["resolution_reason_code"],
        name="resolution_reason_code",
    )
    abandonment_reason = (
        None
        if raw["abandonment_reason_code"] is None
        else _code(
            raw["abandonment_reason_code"],
            name="abandonment_reason_code",
            allowed=(
                "explicitly_abandoned",
                "replaced",
                "out_of_scope",
                "no_longer_wanted",
            ),
        )
    )
    superseded_by = _nullable_id(
        raw["superseded_by_item_id"],
        name="superseded_by_item_id",
        kind="item_id",
    )
    if lifecycle == "resolved":
        if resolved_at is None:
            _error("invalid_resolved_item", "Resolved item requires its timestamp.")
    elif resolved_at is not None or resolution_reason is not None:
        _error("invalid_resolution_fields", "Only resolved item has resolution.")
    if resolved_at is not None and not (
        _timestamp_value(created)
        <= _timestamp_value(resolved_at)
        <= _timestamp_value(updated)
    ):
        _error(
            "invalid_resolved_timestamp",
            "Resolution timestamp must fall within the item update boundary.",
        )
    if lifecycle == "abandoned":
        if abandoned_at is None or abandonment_reason is None:
            _error("invalid_abandoned_item", "Abandoned item requires reason.")
    elif abandoned_at is not None or abandonment_reason is not None:
        _error("invalid_abandonment_fields", "Only abandoned item has abandonment.")
    if abandoned_at is not None and not (
        _timestamp_value(created)
        <= _timestamp_value(abandoned_at)
        <= _timestamp_value(updated)
    ):
        _error(
            "invalid_abandoned_timestamp",
            "Abandonment timestamp must fall within the item update boundary.",
        )
    if lifecycle == "superseded" and superseded_by is None:
        _error("invalid_superseded_item", "Superseded item requires successor.")
    if lifecycle != "superseded" and superseded_by is not None:
        _error("invalid_superseded_item", "Only superseded item has successor.")
    if lifecycle == "expired" and expires is None:
        _error("invalid_expired_item", "Expired item requires hard expiry.")
    if (
        lifecycle == "expired"
        and expires is not None
        and _timestamp_value(expires) > _timestamp_value(updated)
    ):
        _error(
            "invalid_expired_timestamp",
            "Expired lifecycle requires expiry no later than the update.",
        )
    cleanup_state = _code(
        raw["cleanup_state"],
        name="cleanup_state",
        allowed=("retained", "cleanup_eligible"),
    )
    cleanup_eligible_at = _nullable_timestamp(
        raw["cleanup_eligible_at"], name="cleanup_eligible_at"
    )
    if (cleanup_state == "cleanup_eligible") != (
        cleanup_eligible_at is not None
    ):
        _error(
            "invalid_cleanup_state",
            "Cleanup eligibility state and timestamp must agree.",
        )
    if cleanup_state == "cleanup_eligible":
        if lifecycle == "active":
            _error(
                "active_cleanup_eligible_forbidden",
                "Lifecycle-active items cannot be cleanup eligible.",
            )
        if _timestamp_value(cleanup_eligible_at) < _timestamp_value(updated):
            _error(
                "invalid_cleanup_eligible_timestamp",
                "Cleanup eligibility cannot precede the terminal update boundary.",
            )
    if raw["provider_visible_eligible"] is not True:
        _error(
            "invalid_provider_eligibility",
            "Authoritative Working-Set projection is provider-eligible.",
        )
    for field in (
        "memory_vault_truth",
        "exact_evidence",
        "self_state",
        "action_permission",
        "raw_history_included",
    ):
        if raw[field] is not False:
            _error("forbidden_authority_true", f"{field} must remain false.")
    return {
        "schema_version": WORKING_SET_ITEM_SCHEMA_VERSION,
        "item_id": _id(raw["item_id"], name="item_id", kind="item_id"),
        "creation_seed_sha256": _hash(
            raw["creation_seed_sha256"], name="creation_seed_sha256"
        ),
        **scope,
        "item_kind": kind,
        "lifecycle_state": lifecycle,
        "summary": summary,
        "kind_payload": payload,
        "authorship_kind": authorship,
        "author_participants": normalized_participants,
        "semantic_authority_code": semantic_authority,
        "command_owner": command_owner,
        "authorship_evidence_refs": evidence,
        "derivation_owner": None,
        "derivation_version": None,
        "confidence_millis": _integer(
            raw["confidence_millis"],
            name="confidence_millis",
            minimum=0,
            maximum=1000,
        ),
        "source_turn_ids": _opaque_list(
            raw["source_turn_ids"], name="source_turn_ids", maximum=16
        ),
        "source_room_ids": _opaque_list(
            raw["source_room_ids"],
            name="source_room_ids",
            maximum=4,
            kind="room_id",
        ),
        "source_operation_ids": _opaque_list(
            raw["source_operation_ids"],
            name="source_operation_ids",
            maximum=8,
        ),
        "source_proposal_ids": _opaque_list(
            raw["source_proposal_ids"],
            name="source_proposal_ids",
            maximum=8,
        ),
        "exact_anchor_refs": _opaque_list(
            raw["exact_anchor_refs"],
            name="exact_anchor_refs",
            maximum=8,
            kind="anchor_id",
        ),
        "revision": _integer(raw["revision"], name="revision", minimum=1),
        "base_event_id": base_event_id,
        "content_sha256": content_hash,
        "idempotency_key": _string(
            raw["idempotency_key"], name="idempotency_key", maximum=160
        ),
        "created_at": created,
        "updated_at": updated,
        "last_confirmed_at": confirmed,
        "fresh_until": fresh,
        "aging_after": aging,
        "dormant_after": dormant,
        "expires_at": expires,
        "freshness_policy_code": freshness_policy,
        "resolved_at": resolved_at,
        "abandoned_at": abandoned_at,
        "resolution_reason_code": resolution_reason,
        "abandonment_reason_code": abandonment_reason,
        "supersedes_item_ids": _opaque_list(
            raw["supersedes_item_ids"],
            name="supersedes_item_ids",
            maximum=8,
            kind="item_id",
        ),
        "superseded_by_item_id": superseded_by,
        "reopens_item_id": _nullable_id(
            raw["reopens_item_id"],
            name="reopens_item_id",
            kind="item_id",
        ),
        "cleanup_state": cleanup_state,
        "cleanup_eligible_at": cleanup_eligible_at,
        "provider_visible_eligible": True,
        "memory_vault_truth": False,
        "exact_evidence": False,
        "self_state": False,
        "action_permission": False,
        "raw_history_included": False,
    }

def _event_payload_hash(raw: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {key: value for key, value in raw.items() if key not in _EVENT_CHAIN_FIELDS}
    )

def _global_event_hash(raw: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "global_event_sequence": raw["global_event_sequence"],
            "prior_global_event_sha256": raw["prior_global_event_sha256"],
            "event_id": raw["event_id"],
            "event_payload_sha256": raw["event_payload_sha256"],
        }
    )

def _item_event_hash(raw: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "item_id": raw["item_id"],
            "item_event_sequence": raw["item_event_sequence"],
            "prior_item_event_sha256": raw["prior_item_event_sha256"],
            "event_id": raw["event_id"],
            "event_payload_sha256": raw["event_payload_sha256"],
        }
    )

def _binding_event_hash(raw: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "room_id": raw["room_id"],
            "binding_event_sequence": raw["binding_event_sequence"],
            "prior_binding_event_sha256": raw[
                "prior_binding_event_sha256"
            ],
            "event_id": raw["event_id"],
            "event_payload_sha256": raw["event_payload_sha256"],
        }
    )

def _nullable_hash(value: Any, *, name: str) -> str | None:
    return None if value is None else _hash(value, name=name)

def _validate_chain_link(
    sequence: int, predecessor: str | None, *, owner: str
) -> None:
    if sequence == 1 and predecessor is not None:
        _error(f"invalid_{owner}_genesis", "Genesis predecessor must be null.")
    if sequence > 1 and predecessor is None:
        _error(
            f"invalid_{owner}_predecessor",
            "Non-genesis predecessor must be present.",
        )

def validate_working_set_event(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "event_id",
            "creation_seed_sha256",
            "event_payload_sha256",
            "global_event_sequence",
            "prior_global_event_sha256",
            "global_event_sha256",
            "item_id",
            "item_event_sequence",
            "prior_item_event_sha256",
            "item_event_sha256",
            "event_kind",
            "from_lifecycle_state",
            "to_lifecycle_state",
            "expected_revision",
            "new_revision",
            "patch",
            "actor_kind",
            "actor_ref",
            "idempotency_key",
            "command_sha256",
            "source_turn_ids",
            "source_room_ids",
            "source_operation_ids",
            "source_proposal_ids",
            "created_at",
        ),
        path="working_set_event",
    )
    if raw["schema_version"] != WORKING_SET_EVENT_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported Working-Set event.")
    global_sequence = _integer(
        raw["global_event_sequence"], name="global_event_sequence", minimum=1
    )
    item_sequence = _integer(
        raw["item_event_sequence"], name="item_event_sequence", minimum=1
    )
    prior_global = _nullable_hash(
        raw["prior_global_event_sha256"],
        name="prior_global_event_sha256",
    )
    prior_item = _nullable_hash(
        raw["prior_item_event_sha256"],
        name="prior_item_event_sha256",
    )
    _validate_chain_link(global_sequence, prior_global, owner="global")
    _validate_chain_link(item_sequence, prior_item, owner="item")
    expected_revision = _integer(
        raw["expected_revision"], name="expected_revision", minimum=0
    )
    new_revision = _integer(
        raw["new_revision"], name="new_revision", minimum=1
    )
    if new_revision != expected_revision + 1:
        _error("invalid_event_revision", "Event revision must increment by one.")
    if not isinstance(raw["patch"], Mapping):
        _error("invalid_event_patch", "Event patch must be an object.")
    _reject_private(raw["patch"], path="working_set_event.patch")
    if len(canonical_json_bytes(raw["patch"])) > 8_000:
        _error("event_patch_too_large", "Event patch exceeds its cap.")
    normalized = {
        "schema_version": WORKING_SET_EVENT_SCHEMA_VERSION,
        "event_id": _id(raw["event_id"], name="event_id", kind="event_id"),
        "creation_seed_sha256": _hash(
            raw["creation_seed_sha256"], name="creation_seed_sha256"
        ),
        "event_payload_sha256": _hash(
            raw["event_payload_sha256"], name="event_payload_sha256"
        ),
        "global_event_sequence": global_sequence,
        "prior_global_event_sha256": prior_global,
        "global_event_sha256": _hash(
            raw["global_event_sha256"], name="global_event_sha256"
        ),
        "item_id": _id(raw["item_id"], name="item_id", kind="item_id"),
        "item_event_sequence": item_sequence,
        "prior_item_event_sha256": prior_item,
        "item_event_sha256": _hash(
            raw["item_event_sha256"], name="item_event_sha256"
        ),
        "event_kind": _code(
            raw["event_kind"],
            name="event_kind",
            allowed=WORKING_SET_EVENT_KINDS,
        ),
        "from_lifecycle_state": (
            None
            if raw["from_lifecycle_state"] is None
            else _code(
                raw["from_lifecycle_state"],
                name="from_lifecycle_state",
                allowed=LIFECYCLE_STATES,
            )
        ),
        "to_lifecycle_state": _code(
            raw["to_lifecycle_state"],
            name="to_lifecycle_state",
            allowed=LIFECYCLE_STATES,
        ),
        "expected_revision": expected_revision,
        "new_revision": new_revision,
        "patch": dict(raw["patch"]),
        "actor_kind": _code(
            raw["actor_kind"],
            name="actor_kind",
            allowed=(
                "solen_explicit",
                "astel_explicit",
                "joint_explicit",
                "structured_client_event",
                "structured_tool_event",
                "deterministic_lifecycle",
            ),
        ),
        "actor_ref": _string(raw["actor_ref"], name="actor_ref", maximum=180),
        "idempotency_key": _string(
            raw["idempotency_key"], name="idempotency_key", maximum=160
        ),
        "command_sha256": _hash(
            raw["command_sha256"], name="command_sha256"
        ),
        "source_turn_ids": _opaque_list(
            raw["source_turn_ids"], name="source_turn_ids", maximum=16
        ),
        "source_room_ids": _opaque_list(
            raw["source_room_ids"],
            name="source_room_ids",
            maximum=4,
            kind="room_id",
        ),
        "source_operation_ids": _opaque_list(
            raw["source_operation_ids"],
            name="source_operation_ids",
            maximum=8,
        ),
        "source_proposal_ids": _opaque_list(
            raw["source_proposal_ids"],
            name="source_proposal_ids",
            maximum=8,
        ),
        "created_at": _timestamp(raw["created_at"], name="created_at"),
    }
    if normalized["event_kind"] == "create":
        if (
            normalized["expected_revision"] != 0
            or normalized["from_lifecycle_state"] is not None
        ):
            _error("invalid_create_event", "Create event begins revision one.")
    elif normalized["from_lifecycle_state"] is None:
        _error(
            "missing_from_lifecycle_state",
            "Non-create event requires prior lifecycle.",
        )
    if _event_payload_hash(normalized) != normalized["event_payload_sha256"]:
        _error("event_payload_sha256_mismatch", "Event payload digest differs.")
    if _global_event_hash(normalized) != normalized["global_event_sha256"]:
        _error("global_event_sha256_mismatch", "Global event digest differs.")
    if _item_event_hash(normalized) != normalized["item_event_sha256"]:
        _error("item_event_sha256_mismatch", "Item event digest differs.")
    if len(
        {
            normalized["event_payload_sha256"],
            normalized["global_event_sha256"],
            normalized["item_event_sha256"],
        }
    ) != 3:
        _error(
            "collapsed_event_hash_identity",
            "Payload, global, and item hashes are distinct identities.",
        )
    return normalized

def validate_scope_binding_event(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "event_id",
            "creation_seed_sha256",
            "event_payload_sha256",
            "global_event_sequence",
            "prior_global_event_sha256",
            "global_event_sha256",
            "room_id",
            "binding_event_sequence",
            "prior_binding_event_sha256",
            "binding_event_sha256",
            "event_kind",
            "expected_binding_revision",
            "new_binding_revision",
            "from_binding",
            "to_binding",
            "actor_kind",
            "actor_ref",
            "idempotency_key",
            "command_sha256",
            "source_turn_ids",
            "source_room_ids",
            "source_operation_ids",
            "created_at",
        ),
        path="scope_binding_event",
    )
    if raw["schema_version"] != SCOPE_BINDING_EVENT_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported binding event.")
    global_sequence = _integer(
        raw["global_event_sequence"], name="global_event_sequence", minimum=1
    )
    binding_sequence = _integer(
        raw["binding_event_sequence"],
        name="binding_event_sequence",
        minimum=1,
    )
    prior_global = _nullable_hash(
        raw["prior_global_event_sha256"],
        name="prior_global_event_sha256",
    )
    prior_binding = _nullable_hash(
        raw["prior_binding_event_sha256"],
        name="prior_binding_event_sha256",
    )
    _validate_chain_link(global_sequence, prior_global, owner="global")
    _validate_chain_link(binding_sequence, prior_binding, owner="binding")
    expected_revision = _integer(
        raw["expected_binding_revision"],
        name="expected_binding_revision",
        minimum=0,
    )
    new_revision = _integer(
        raw["new_binding_revision"],
        name="new_binding_revision",
        minimum=1,
    )
    if new_revision != expected_revision + 1:
        _error(
            "invalid_binding_event_revision",
            "Binding revision must increment by one.",
        )
    from_binding = (
        None
        if raw["from_binding"] is None
        else validate_scope_binding(raw["from_binding"])
    )
    to_binding = validate_scope_binding(raw["to_binding"])
    room_id = _id(raw["room_id"], name="room_id", kind="room_id")
    if to_binding["room_id"] != room_id or (
        from_binding is not None and from_binding["room_id"] != room_id
    ):
        _error("binding_event_room_mismatch", "Binding event room differs.")
    if to_binding["binding_revision"] != new_revision or (
        from_binding is not None
        and from_binding["binding_revision"] != expected_revision
    ):
        _error("binding_event_revision_mismatch", "Binding projection differs.")
    normalized = {
        "schema_version": SCOPE_BINDING_EVENT_SCHEMA_VERSION,
        "event_id": _id(raw["event_id"], name="event_id", kind="event_id"),
        "creation_seed_sha256": _hash(
            raw["creation_seed_sha256"], name="creation_seed_sha256"
        ),
        "event_payload_sha256": _hash(
            raw["event_payload_sha256"], name="event_payload_sha256"
        ),
        "global_event_sequence": global_sequence,
        "prior_global_event_sha256": prior_global,
        "global_event_sha256": _hash(
            raw["global_event_sha256"], name="global_event_sha256"
        ),
        "room_id": room_id,
        "binding_event_sequence": binding_sequence,
        "prior_binding_event_sha256": prior_binding,
        "binding_event_sha256": _hash(
            raw["binding_event_sha256"], name="binding_event_sha256"
        ),
        "event_kind": _code(
            raw["event_kind"],
            name="event_kind",
            allowed=("bind", "rebind", "decline", "inherit"),
        ),
        "expected_binding_revision": expected_revision,
        "new_binding_revision": new_revision,
        "from_binding": from_binding,
        "to_binding": to_binding,
        "actor_kind": _code(
            raw["actor_kind"],
            name="actor_kind",
            allowed=(
                "solen_explicit",
                "astel_explicit",
                "structured_client_event",
                "deterministic_binding",
            ),
        ),
        "actor_ref": _string(raw["actor_ref"], name="actor_ref", maximum=180),
        "idempotency_key": _string(
            raw["idempotency_key"], name="idempotency_key", maximum=160
        ),
        "command_sha256": _hash(
            raw["command_sha256"], name="command_sha256"
        ),
        "source_turn_ids": _opaque_list(
            raw["source_turn_ids"], name="source_turn_ids", maximum=16
        ),
        "source_room_ids": _opaque_list(
            raw["source_room_ids"],
            name="source_room_ids",
            maximum=4,
            kind="room_id",
        ),
        "source_operation_ids": _opaque_list(
            raw["source_operation_ids"],
            name="source_operation_ids",
            maximum=8,
        ),
        "created_at": _timestamp(raw["created_at"], name="created_at"),
    }
    if _event_payload_hash(normalized) != normalized["event_payload_sha256"]:
        _error(
            "event_payload_sha256_mismatch",
            "Binding event payload digest differs.",
        )
    if _global_event_hash(normalized) != normalized["global_event_sha256"]:
        _error(
            "global_event_sha256_mismatch",
            "Binding global event digest differs.",
        )
    if _binding_event_hash(normalized) != normalized["binding_event_sha256"]:
        _error(
            "binding_event_sha256_mismatch",
            "Per-binding event digest differs.",
        )
    if len(
        {
            normalized["event_payload_sha256"],
            normalized["global_event_sha256"],
            normalized["binding_event_sha256"],
        }
    ) != 3:
        _error(
            "collapsed_event_hash_identity",
            "Payload, global, and binding hashes are distinct identities.",
        )
    return normalized

def _normalize_chain_checkpoint(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "global_event_sequence",
            "global_event_sha256",
            "item_heads",
            "binding_heads",
        ),
        path="event_chain_checkpoint",
    )
    for field in ("item_heads", "binding_heads"):
        if not isinstance(raw[field], Mapping):
            _error("invalid_chain_checkpoint", f"{field} must be an object.")
    item_heads = {}
    for item_id, head in raw["item_heads"].items():
        head = _exact(
            head, ("sequence", "sha256"), path=f"item_heads.{item_id}"
        )
        item_heads[_id(item_id, name="item_head_id", kind="item_id")] = {
            "sequence": _integer(
                head["sequence"], name="item_head_sequence", minimum=1
            ),
            "sha256": _hash(head["sha256"], name="item_head_sha256"),
        }
    binding_heads = {}
    for room_id, head in raw["binding_heads"].items():
        head = _exact(
            head, ("sequence", "sha256"), path=f"binding_heads.{room_id}"
        )
        binding_heads[_id(room_id, name="binding_head_id", kind="room_id")] = {
            "sequence": _integer(
                head["sequence"], name="binding_head_sequence", minimum=1
            ),
            "sha256": _hash(
                head["sha256"], name="binding_head_sha256"
            ),
        }
    return {
        "global_event_sequence": _integer(
            raw["global_event_sequence"],
            name="checkpoint_global_event_sequence",
            minimum=1,
        ),
        "global_event_sha256": _hash(
            raw["global_event_sha256"],
            name="checkpoint_global_event_sha256",
        ),
        "item_heads": item_heads,
        "binding_heads": binding_heads,
    }

def validate_event_chains(
    events: Any, *, checkpoint: Any | None = None
) -> dict[str, Any]:
    if not isinstance(events, list) or not events:
        _error("invalid_event_chain", "Event chain must be a nonempty list.")
    normalized = []
    for value in events:
        if not isinstance(value, Mapping):
            _error("invalid_event_chain", "Event chain entry must be an object.")
        if value.get("schema_version") == WORKING_SET_EVENT_SCHEMA_VERSION:
            normalized.append(("item", validate_working_set_event(value)))
        elif value.get("schema_version") == SCOPE_BINDING_EVENT_SCHEMA_VERSION:
            normalized.append(("binding", validate_scope_binding_event(value)))
        else:
            _error("invalid_event_chain_schema", "Unknown event schema.")
    head = None if checkpoint is None else _normalize_chain_checkpoint(checkpoint)
    first_event = normalized[0][1]
    if first_event["global_event_sequence"] == 1:
        if head is not None:
            _error("unexpected_chain_checkpoint", "Genesis chain has no checkpoint.")
        previous_sequence = 0
        previous_global = None
        item_heads: dict[str, dict[str, Any]] = {}
        binding_heads: dict[str, dict[str, Any]] = {}
    else:
        if head is None:
            _error(
                "partial_chain_checkpoint_required",
                "Non-genesis chain requires an explicit verified head.",
            )
        previous_sequence = head["global_event_sequence"]
        previous_global = head["global_event_sha256"]
        item_heads = dict(head["item_heads"])
        binding_heads = dict(head["binding_heads"])
    seen_event_ids = set()
    seen_global_hashes = set()
    for owner, event in normalized:
        if event["event_id"] in seen_event_ids:
            _error("duplicate_event_id", "Event IDs must be globally unique.")
        if event["global_event_sha256"] in seen_global_hashes:
            _error(
                "duplicate_global_event_hash",
                "Global event hashes must be unique.",
            )
        seen_event_ids.add(event["event_id"])
        seen_global_hashes.add(event["global_event_sha256"])
        sequence = event["global_event_sequence"]
        if sequence != previous_sequence + 1:
            _error("global_event_sequence_gap", "Global sequence is not contiguous.")
        if event["prior_global_event_sha256"] != previous_global:
            _error("global_event_chain_mismatch", "Global predecessor differs.")
        if owner == "item":
            expected = item_heads.get(event["item_id"])
            expected_sequence = 0 if expected is None else expected["sequence"]
            expected_sha = None if expected is None else expected["sha256"]
            if (
                event["item_event_sequence"] != expected_sequence + 1
                or event["prior_item_event_sha256"] != expected_sha
            ):
                _error("item_event_chain_mismatch", "Item predecessor differs.")
            item_heads[event["item_id"]] = {
                "sequence": event["item_event_sequence"],
                "sha256": event["item_event_sha256"],
            }
        else:
            expected = binding_heads.get(event["room_id"])
            expected_sequence = 0 if expected is None else expected["sequence"]
            expected_sha = None if expected is None else expected["sha256"]
            if (
                event["binding_event_sequence"] != expected_sequence + 1
                or event["prior_binding_event_sha256"] != expected_sha
            ):
                _error("binding_event_chain_mismatch", "Binding predecessor differs.")
            binding_heads[event["room_id"]] = {
                "sequence": event["binding_event_sequence"],
                "sha256": event["binding_event_sha256"],
            }
        previous_sequence = sequence
        previous_global = event["global_event_sha256"]
    return {
        "event_count": len(normalized),
        "first_global_event_sequence": normalized[0][1][
            "global_event_sequence"
        ],
        "last_global_event_sequence": previous_sequence,
        "last_global_event_sha256": previous_global,
        "item_heads": item_heads,
        "binding_heads": binding_heads,
    }

__all__ = [
    "CREATION_SEED_SCHEMA_VERSION",
    "SCOPE_BINDING_SCHEMA_VERSION",
    "WORKING_SET_ITEM_SCHEMA_VERSION",
    "WORKING_SET_EVENT_SCHEMA_VERSION",
    "SCOPE_BINDING_EVENT_SCHEMA_VERSION",
    "ITEM_KINDS",
    "SOLEN_CREATABLE_KINDS",
    "LIFECYCLE_STATES",
    "SEMANTIC_OPERATION_KINDS",
    "WORKING_SET_EVENT_KINDS",
    "SCOPE_KINDS",
    "RESOLUTION_REASONS",
    "SUMMARY_MAX_CHARS",
    "MAX_LINKED_ITEM_IDS",
    "_PAYLOAD_FIELDS",
    "_PAYLOAD_ENUMS",
    "_EVENT_CHAIN_FIELDS",
    "validate_item_kind_payload",
    "validate_creation_seed_registry",
    "validate_creation_seed_collision",
    "validate_scope_binding",
    "_nullable_timestamp",
    "_authorship_evidence_ref",
    "validate_working_set_item",
    "_event_payload_hash",
    "_global_event_hash",
    "_item_event_hash",
    "_binding_event_hash",
    "_nullable_hash",
    "_validate_chain_link",
    "validate_working_set_event",
    "validate_scope_binding_event",
    "_normalize_chain_checkpoint",
    "validate_event_chains",
]
