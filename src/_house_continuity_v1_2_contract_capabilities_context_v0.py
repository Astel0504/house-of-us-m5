"""Capability, command-context, and Solen-intent contracts for Continuity V1.2."""

from __future__ import annotations

from copy import deepcopy
from _house_continuity_v1_2_contract_primitives_v0 import *
from _house_continuity_v1_2_contract_primitives_v0 import validate_authored_reason
from _house_continuity_v1_2_contract_items_events_v0 import (
    ITEM_KINDS,
    LIFECYCLE_STATES,
    SEMANTIC_OPERATION_KINDS,
    SOLEN_CREATABLE_KINDS,
    SUMMARY_MAX_CHARS,
    validate_item_kind_payload,
)

COMMAND_CONTEXT_SCHEMA_VERSION = "house_continuity_command_context_v1"

INTENT_SCHEMA_VERSION = "house_talk_continuity_authorship_intent_v1"

INTENT_PROTOCOL_VERSION = "house_continuity_private_carrier_v1_2"

CAPABILITY_OFFER_SCHEMA_VERSION = "house_continuity_authorship_offer_v1"

CAPABILITY_SCHEMA_VERSION = "house_continuity_intent_capability_v1"

COMMANDABLE_OPERATION_KINDS = (
    "confirm",
    "revise",
    "resolve",
    "supersede",
    "reopen",
)

PROVISIONAL_BINDING_CHOICES = (
    "inherit_predecessor_project_thread",
    "inherit_predecessor_project",
    "rebind_allowed_existing",
    "decline_predecessor",
)

COMMAND_CONTEXT_MAX_ITEMS = 8

COMMAND_CONTEXT_MAX_CREATE_OFFERS = 4

COMMAND_CONTEXT_MAX_BINDING_CHOICES = 4

COMMAND_CONTEXT_MAX_UTF8_BYTES = 12_000

MAX_TOTAL_OPERATIONS = 4

SEMANTIC_NOVELTY_COMPARISON_VERSION = "v1"
SEMANTIC_NOVELTY_EVIDENCE_SCHEMA_VERSION = (
    "house_continuity_semantic_novelty_evidence_v1"
)
SEMANTIC_NOVELTY_POLICY_FIELD = "semantic_novelty_policy"
SEMANTIC_NOVELTY_POLICY_VERSION = "house_continuity_semantic_novelty_policy_v1"
SEMANTIC_EVALUATION_FIELD = "semantic_evaluation"
SEMANTIC_EVALUATION_SCHEMA_VERSION = (
    "house_continuity_semantic_evaluation_v1"
)
SEMANTIC_EVALUATION_REQUEST_SCHEMA_VERSION = (
    "house_continuity_semantic_evaluation_request_v1"
)
SEMANTIC_EVALUATION_RELATIONS = (
    "unknown",
    "contextual_return",
    "explicit_lifecycle_request",
)
SEMANTIC_NOVELTY_MARKER_NAMESPACE = "house_continuity_no_delta"
SEMANTIC_NOVELTY_MARKER_VERSION = "v1"
LEGACY_FALSE_SCOPE_CANONICALIZATION_CODE = (
    "false_scope_conflict_to_no_semantic_delta"
)
FALSE_SCOPE_CONFLICT_CANONICALIZATION_CODE = (
    f"{SEMANTIC_NOVELTY_MARKER_NAMESPACE}:"
    f"{SEMANTIC_NOVELTY_MARKER_VERSION}:false_scope_conflict"
)
CONTEXTUAL_RESTATEMENT_CANONICALIZATION_CODE = (
    f"{SEMANTIC_NOVELTY_MARKER_NAMESPACE}:"
    f"{SEMANTIC_NOVELTY_MARKER_VERSION}:contextual_restatement"
)
AUTHORITATIVE_REAFFIRMATION_CANONICALIZATION_CODE = (
    f"{SEMANTIC_NOVELTY_MARKER_NAMESPACE}:"
    f"{SEMANTIC_NOVELTY_MARKER_VERSION}:authoritative_reaffirmation"
)
GENUINE_REVISION_EVIDENCE_RECOMPUTED_CODE = (
    "house_continuity_runtime_evaluation:v1:"
    "genuine_revision_evidence_recomputed"
)
NO_DELTA_CANONICALIZATION_CODES = frozenset(
    {
        LEGACY_FALSE_SCOPE_CANONICALIZATION_CODE,
        FALSE_SCOPE_CONFLICT_CANONICALIZATION_CODE,
        CONTEXTUAL_RESTATEMENT_CANONICALIZATION_CODE,
        AUTHORITATIVE_REAFFIRMATION_CANONICALIZATION_CODE,
    }
)

# The old marker is durable evidence from the first deployed provenance
# correction.  It remains readable but is never emitted by this version.
CANONICALIZATION_MARKER_COMPATIBILITY = {
    LEGACY_FALSE_SCOPE_CANONICALIZATION_CODE: {
        "status": "legacy_read_only",
        "namespace": "legacy",
        "version": None,
        "replacement": FALSE_SCOPE_CONFLICT_CANONICALIZATION_CODE,
    },
    FALSE_SCOPE_CONFLICT_CANONICALIZATION_CODE: {
        "status": "current",
        "namespace": SEMANTIC_NOVELTY_MARKER_NAMESPACE,
        "version": SEMANTIC_NOVELTY_MARKER_VERSION,
        "replacement": None,
    },
    CONTEXTUAL_RESTATEMENT_CANONICALIZATION_CODE: {
        "status": "current",
        "namespace": SEMANTIC_NOVELTY_MARKER_NAMESPACE,
        "version": SEMANTIC_NOVELTY_MARKER_VERSION,
        "replacement": None,
    },
    AUTHORITATIVE_REAFFIRMATION_CANONICALIZATION_CODE: {
        "status": "current",
        "namespace": SEMANTIC_NOVELTY_MARKER_NAMESPACE,
        "version": SEMANTIC_NOVELTY_MARKER_VERSION,
        "replacement": None,
    },
}

COMMAND_CONTEXT_AUTHORITY = {
    "descriptive_dynamic_data": True,
    "working_set_snapshot_projection": True,
    "memory_vault_truth": False,
    "exact_evidence": False,
    "self_state": False,
    "action_permission": False,
    "capability_authority": False,
    "raw_history_included": False,
}

_OPERATION_FIELDS = (
    "operation_key",
    "operation_kind",
    "item_id",
    "expected_revision",
    "item_kind",
    "scope",
    "summary",
    "kind_payload",
    "reason_code",
    "superseded_by_item_id",
    "source_proposal_ids",
)

_SEMANTIC_EVIDENCE_FIELDS = (
    "schema_version",
    "comparison",
    "authoritative_item_id",
    "authoritative_content_sha256",
    "candidate_summary_sha256",
)


def authoritative_projection_sha256(value: Mapping[str, Any]) -> str:
    """Hash the exact normalized projection used for semantic evaluation."""

    return canonical_sha256(
        {
            "room_id": value["room_id"],
            "scope_binding_revision": value["scope_binding_revision"],
            "snapshot_global_event_sequence": value[
                "snapshot_global_event_sequence"
            ],
            "snapshot_global_event_sha256": value[
                "snapshot_global_event_sha256"
            ],
            "items": value["items"],
            "create_offers": value["create_offers"],
        }
    )


def validate_semantic_evaluation_request(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        ("schema_version", "request_relation"),
        path="semantic_evaluation_request",
    )
    if raw["schema_version"] != SEMANTIC_EVALUATION_REQUEST_SCHEMA_VERSION:
        _error(
            "unknown_semantic_evaluation_request_version",
            "Unsupported semantic evaluation request.",
        )
    relation = _code(
        raw["request_relation"],
        name="semantic_evaluation_request_relation",
        allowed=SEMANTIC_EVALUATION_RELATIONS,
    )
    return {
        "schema_version": SEMANTIC_EVALUATION_REQUEST_SCHEMA_VERSION,
        "request_relation": relation,
    }


def _validate_semantic_evaluation(
    value: Any,
    *,
    projection_sha256: str,
) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "request_relation",
            "authoritative_projection_sha256",
        ),
        path=SEMANTIC_EVALUATION_FIELD,
    )
    if raw["schema_version"] != SEMANTIC_EVALUATION_SCHEMA_VERSION:
        _error(
            "unknown_semantic_evaluation_version",
            "Unsupported semantic evaluation evidence.",
        )
    relation = _code(
        raw["request_relation"],
        name="semantic_evaluation_request_relation",
        allowed=SEMANTIC_EVALUATION_RELATIONS,
    )
    projection = _hash(
        raw["authoritative_projection_sha256"],
        name="authoritative_projection_sha256",
    )
    if projection != projection_sha256:
        _error(
            "semantic_evaluation_projection_mismatch",
            "Semantic evaluation is not bound to the authoritative projection.",
        )
    return {
        "schema_version": SEMANTIC_EVALUATION_SCHEMA_VERSION,
        "request_relation": relation,
        "authoritative_projection_sha256": projection,
    }

def _context_item(value: Any, *, index: int) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "item_id",
            "revision",
            "item_kind",
            "lifecycle_state",
            "scope",
            "summary",
            "kind_payload",
            "content_sha256",
            "allowed_operations",
            "offered_successor_item_ids",
        ),
        path=f"command_context.items[{index}]",
    )
    kind = _code(raw["item_kind"], name="item_kind", allowed=ITEM_KINDS)
    lifecycle = _code(
        raw["lifecycle_state"],
        name="lifecycle_state",
        allowed=LIFECYCLE_STATES,
    )
    if not isinstance(raw["allowed_operations"], list):
        _error("invalid_allowed_operations", "allowed_operations must be a list.")
    operations = [
        _code(item, name="allowed_operation", allowed=COMMANDABLE_OPERATION_KINDS)
        for item in raw["allowed_operations"]
    ]
    if len(operations) != len(set(operations)):
        _error("invalid_allowed_operations", "Allowed operations must be unique.")
    allowed_by_state = {
        "active": {"confirm", "revise", "resolve", "supersede"},
        "resolved": {"reopen", "supersede"},
        "abandoned": {"reopen", "supersede"},
        "superseded": set(),
        "expired": set(),
    }[lifecycle]
    if not set(operations).issubset(allowed_by_state):
        _error("invalid_allowed_operations", "Operations conflict with lifecycle.")
    normalized_scope = normalize_scope(
        raw["scope"], path=f"command_context.items[{index}].scope"
    )
    summary = _string(
        raw["summary"], name="summary", maximum=SUMMARY_MAX_CHARS
    )
    payload = validate_item_kind_payload(kind, raw["kind_payload"])
    content_sha256 = _hash(raw["content_sha256"], name="content_sha256")
    semantic_content = {
        "item_kind": kind,
        "scope": normalized_scope,
        "summary": summary,
        "kind_payload": payload,
    }
    if canonical_sha256(semantic_content) != content_sha256:
        _error(
            "command_context_content_sha256_mismatch",
            "Offered item content digest differs from its exact semantic fields.",
        )
    return {
        "item_id": _id(raw["item_id"], name="item_id", kind="item_id"),
        "revision": _integer(raw["revision"], name="revision", minimum=1),
        "item_kind": kind,
        "lifecycle_state": lifecycle,
        "scope": normalized_scope,
        "summary": summary,
        "kind_payload": payload,
        "content_sha256": content_sha256,
        "allowed_operations": operations,
        "offered_successor_item_ids": _id_list(
            raw["offered_successor_item_ids"],
            name="offered_successor_item_ids",
            maximum=COMMAND_CONTEXT_MAX_ITEMS,
            kind="item_id",
        ),
    }

def validate_command_context(value: Any) -> dict[str, Any]:
    required_fields = (
            "schema_version",
            "context_id",
            "creation_seed_sha256",
            "snapshot_global_event_sequence",
            "snapshot_global_event_sha256",
            "room_id",
            "scope_binding_revision",
            "items",
            "create_offers",
            "provisional_scope_binding_choices",
            "authority",
    )
    optional_fields = []
    if isinstance(value, Mapping) and SEMANTIC_NOVELTY_POLICY_FIELD in value:
        optional_fields.append(SEMANTIC_NOVELTY_POLICY_FIELD)
    if isinstance(value, Mapping) and SEMANTIC_EVALUATION_FIELD in value:
        optional_fields.append(SEMANTIC_EVALUATION_FIELD)
    if optional_fields:
        raw = _exact(
            value,
            (*required_fields, *optional_fields),
            path="command_context",
        )
    else:
        raw = _exact(value, required_fields, path="command_context")
    if raw["schema_version"] != COMMAND_CONTEXT_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported command-context schema.")
    if not isinstance(raw["items"], list) or len(raw["items"]) > 8:
        _error("invalid_items", "Command context permits at most eight items.")
    items = [_context_item(item, index=index) for index, item in enumerate(raw["items"])]
    item_ids = [item["item_id"] for item in items]
    if len(item_ids) != len(set(item_ids)):
        _error("duplicate_item_id", "Item IDs must be unique.")
    item_map = {item["item_id"]: item for item in items}
    for item in items:
        for successor_id in item["offered_successor_item_ids"]:
            successor = item_map.get(successor_id)
            if successor is None:
                _error("unoffered_successor", "Successor must be in the context.")
            if (
                successor["item_kind"] != item["item_kind"]
                or successor["scope"] != item["scope"]
            ):
                _error(
                    "incompatible_successor",
                    "Offered successor must have exact kind and scope compatibility.",
                )
    if (
        not isinstance(raw["create_offers"], list)
        or len(raw["create_offers"]) > COMMAND_CONTEXT_MAX_CREATE_OFFERS
    ):
        _error("invalid_create_offers", "Create offers exceed their cap.")
    offers = []
    scope_hashes = set()
    offer_ids = set()
    for index, offer_value in enumerate(raw["create_offers"]):
        offer = _exact(
            offer_value,
            ("offer_id", "scope", "allowed_item_kinds"),
            path=f"command_context.create_offers[{index}]",
        )
        scope = normalize_scope(
            offer["scope"], path=f"command_context.create_offers[{index}].scope"
        )
        scope_hash = canonical_sha256(scope)
        if scope_hash in scope_hashes:
            _error(
                "duplicate_create_scope",
                "Duplicate canonical create scopes are forbidden.",
            )
        scope_hashes.add(scope_hash)
        if not isinstance(offer["allowed_item_kinds"], list):
            _error("invalid_allowed_item_kinds", "Allowed kinds must be a list.")
        kinds = [
            _code(kind, name="allowed_item_kind", allowed=SOLEN_CREATABLE_KINDS)
            for kind in offer["allowed_item_kinds"]
        ]
        if len(kinds) != len(set(kinds)) or not kinds:
            _error("invalid_allowed_item_kinds", "Allowed kinds must be unique.")
        offer_id = _id(
            offer["offer_id"], name="offer_id", kind="offer_id"
        )
        if offer_id in offer_ids:
            _error("duplicate_offer_id", "Create offer IDs must be unique.")
        offer_ids.add(offer_id)
        offers.append(
            {
                "offer_id": offer_id,
                "scope": scope,
                "allowed_item_kinds": kinds,
            }
        )
    if (
        not isinstance(raw["provisional_scope_binding_choices"], list)
        or len(raw["provisional_scope_binding_choices"])
        > COMMAND_CONTEXT_MAX_BINDING_CHOICES
    ):
        _error("invalid_binding_choices", "Binding choices exceed their cap.")
    choices = []
    seen_choices = set()
    for index, choice_value in enumerate(
        raw["provisional_scope_binding_choices"]
    ):
        choice = _exact(
            choice_value,
            (
                "choice_code",
                "predecessor_room_id",
                "target_scope",
                "expected_binding_revision",
            ),
            path=f"command_context.provisional_scope_binding_choices[{index}]",
        )
        code = _code(
            choice["choice_code"],
            name="choice_code",
            allowed=PROVISIONAL_BINDING_CHOICES,
        )
        choice_identity = canonical_sha256(
            {
                "choice_code": code,
                "predecessor_room_id": choice["predecessor_room_id"],
                "target_scope": choice["target_scope"],
                "expected_binding_revision": choice[
                    "expected_binding_revision"
                ],
            }
        )
        if choice_identity in seen_choices:
            _error("duplicate_binding_choice", "Binding choices must be unique.")
        seen_choices.add(choice_identity)
        target = (
            None
            if code == "decline_predecessor"
            else normalize_scope(
                choice["target_scope"],
                path=f"command_context.provisional_scope_binding_choices[{index}].target_scope",
            )
        )
        if code == "decline_predecessor" and choice["target_scope"] is not None:
            _error("invalid_binding_choice", "Decline has no target scope.")
        choices.append(
            {
                "choice_code": code,
                "predecessor_room_id": _id(
                    choice["predecessor_room_id"],
                    name="predecessor_room_id",
                    kind="room_id",
                ),
                "target_scope": target,
                "expected_binding_revision": _integer(
                    choice["expected_binding_revision"],
                    name="expected_binding_revision",
                    minimum=1,
                ),
            }
        )
    if raw["authority"] != COMMAND_CONTEXT_AUTHORITY:
        _error("invalid_command_context_authority", "Authority boundary differs.")
    semantic_novelty_policy = None
    if SEMANTIC_NOVELTY_POLICY_FIELD in raw:
        semantic_novelty_policy = _string(
            raw[SEMANTIC_NOVELTY_POLICY_FIELD],
            name=SEMANTIC_NOVELTY_POLICY_FIELD,
            maximum=96,
        )
        if semantic_novelty_policy != SEMANTIC_NOVELTY_POLICY_VERSION:
            _error(
                "unknown_semantic_novelty_policy",
                "Unsupported semantic novelty policy.",
            )
    normalized = {
        "schema_version": COMMAND_CONTEXT_SCHEMA_VERSION,
        "context_id": _id(
            raw["context_id"], name="context_id", kind="context_id"
        ),
        "creation_seed_sha256": _hash(
            raw["creation_seed_sha256"], name="creation_seed_sha256"
        ),
        "snapshot_global_event_sequence": _integer(
            raw["snapshot_global_event_sequence"],
            name="snapshot_global_event_sequence",
        ),
        "snapshot_global_event_sha256": _hash(
            raw["snapshot_global_event_sha256"],
            name="snapshot_global_event_sha256",
        ),
        "room_id": _id(raw["room_id"], name="room_id", kind="room_id"),
        "scope_binding_revision": _integer(
            raw["scope_binding_revision"],
            name="scope_binding_revision",
            minimum=1,
        ),
        "items": items,
        "create_offers": offers,
        "provisional_scope_binding_choices": choices,
        "authority": dict(COMMAND_CONTEXT_AUTHORITY),
    }
    if semantic_novelty_policy is not None:
        normalized[SEMANTIC_NOVELTY_POLICY_FIELD] = semantic_novelty_policy
    if SEMANTIC_EVALUATION_FIELD in raw:
        normalized[SEMANTIC_EVALUATION_FIELD] = _validate_semantic_evaluation(
            raw[SEMANTIC_EVALUATION_FIELD],
            projection_sha256=authoritative_projection_sha256(normalized),
        )
    if len(canonical_json_bytes(normalized)) > COMMAND_CONTEXT_MAX_UTF8_BYTES:
        _error("command_context_too_large", "Command context exceeds its cap.")
    return normalized

def _semantic_operation(value: Any, *, index: int) -> dict[str, Any]:
    path = f"continuity_intent.semantic_operations[{index}]"
    if isinstance(value, Mapping) and "semantic_evidence" in value:
        raw = _exact(value, (*_OPERATION_FIELDS, "semantic_evidence"), path=path)
    else:
        raw = _exact(value, _OPERATION_FIELDS, path=path)
    operation = _code(
        raw["operation_kind"],
        name="operation_kind",
        allowed=SEMANTIC_OPERATION_KINDS,
    )
    kind = _code(raw["item_kind"], name="item_kind", allowed=ITEM_KINDS)
    item_id = _nullable_id(raw["item_id"], name="item_id", kind="item_id")
    revision = _integer(
        raw["expected_revision"], name="expected_revision", minimum=0
    )
    scope = normalize_scope(
        raw["scope"], path=f"continuity_intent.semantic_operations[{index}].scope"
    )
    summary = _string(
        raw["summary"],
        name="summary",
        maximum=SUMMARY_MAX_CHARS,
        empty=operation != "create",
    )
    # This is Solen-authored meaning, not a machine transition code.  Keep it
    # exact and bounded, while operation_kind and bindings remain authoritative
    # for the legal state transition.
    reason = validate_authored_reason(raw["reason_code"])
    successor = _nullable_id(
        raw["superseded_by_item_id"],
        name="superseded_by_item_id",
        kind="item_id",
    )
    proposals = _id_list(
        raw["source_proposal_ids"],
        name="source_proposal_ids",
        maximum=8,
    )
    evidence = None
    if "semantic_evidence" in raw and raw["semantic_evidence"] is not None:
        evidence_raw = _exact(
            raw["semantic_evidence"],
            _SEMANTIC_EVIDENCE_FIELDS,
            path=f"{path}.semantic_evidence",
        )
        comparison = _code(
            evidence_raw["comparison"],
            name="semantic_evidence_comparison",
            allowed=("contextual_restatement", "genuine_revision"),
        )
        evidence = {
            "schema_version": _string(
                evidence_raw["schema_version"],
                name="semantic_evidence_schema_version",
                maximum=96,
            ),
            "comparison": comparison,
            "authoritative_item_id": _id(
                evidence_raw["authoritative_item_id"],
                name="authoritative_item_id",
                kind="item_id",
            ),
            "authoritative_content_sha256": _hash(
                evidence_raw["authoritative_content_sha256"],
                name="authoritative_content_sha256",
            ),
            "candidate_summary_sha256": _hash(
                evidence_raw["candidate_summary_sha256"],
                name="candidate_summary_sha256",
            ),
        }
        if evidence["schema_version"] != SEMANTIC_NOVELTY_EVIDENCE_SCHEMA_VERSION:
            _error(
                "unknown_semantic_evidence_version",
                "Unsupported semantic novelty evidence.",
            )
    if evidence is not None and operation != "revise":
        _error(
            "semantic_evidence_operation_invalid",
            "Semantic novelty evidence applies only to revise.",
        )
    if operation == "create":
        if item_id is not None or revision != 0:
            _error("invalid_create_target", "Create requires null ID/revision zero.")
        if kind not in SOLEN_CREATABLE_KINDS:
            _error(
                "solen_completed_tool_result_create_forbidden",
                "Solen cannot create a completed operation fact.",
            )
        payload = validate_item_kind_payload(kind, raw["kind_payload"])
        if successor is not None:
            _error("invalid_create_semantics", "Create has no successor.")
    elif operation == "revise":
        if item_id is None or revision < 1:
            _error("invalid_operation_target", "Revise requires an exact target.")
        payload = validate_item_kind_payload(
            kind, raw["kind_payload"], partial=True
        )
        if not summary and not payload:
            _error("empty_revision_patch", "Revise requires a bounded patch.")
        if successor is not None:
            _error("invalid_revise_semantics", "Revise has no successor.")
    else:
        if item_id is None or revision < 1:
            _error("invalid_operation_target", "Operation requires an exact target.")
        if summary or raw["kind_payload"] != {}:
            _error(
                f"{operation}_semantic_rewrite_forbidden",
                f"{operation} cannot rewrite semantic fields.",
            )
        payload = {}
        if operation in {"confirm", "resolve", "reopen"} and successor is not None:
            _error(
                f"invalid_{operation}_semantics",
                f"{operation.capitalize()} has no successor.",
            )
        if operation == "supersede" and successor is None:
            _error(
                "invalid_supersede_semantics",
                "Supersede needs an exact successor.",
            )
    normalized = {
        "operation_key": _string(
            raw["operation_key"], name="operation_key", maximum=80
        ),
        "operation_kind": operation,
        "item_id": item_id,
        "expected_revision": revision,
        "item_kind": kind,
        "scope": scope,
        "summary": summary,
        "kind_payload": payload,
        "reason_code": reason,
        "superseded_by_item_id": successor,
        "source_proposal_ids": proposals,
    }
    if evidence is not None:
        normalized["semantic_evidence"] = evidence
    return normalized

def validate_continuity_intent(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "capability",
            "schema_version",
            "protocol_version",
            "coverage_decision",
            "semantic_operations",
            "scope_binding_operation",
        ),
        path="continuity_intent",
    )
    if raw["schema_version"] != INTENT_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported continuity intent.")
    if raw["protocol_version"] != INTENT_PROTOCOL_VERSION:
        _error("invalid_protocol_version", "Unsupported continuity protocol.")
    if (
        not isinstance(raw["capability"], str)
        or _CAPABILITY_RE.fullmatch(raw["capability"]) is None
    ):
        _error("invalid_capability", "Capability format is invalid.")
    decision = _code(
        raw["coverage_decision"],
        name="coverage_decision",
        allowed=("semantic_operations", "no_semantic_delta"),
    )
    if not isinstance(raw["semantic_operations"], list):
        _error("invalid_semantic_operations", "Operations must be a list.")
    operations = [
        _semantic_operation(item, index=index)
        for index, item in enumerate(raw["semantic_operations"])
    ]
    if decision == "semantic_operations" and not operations:
        _error("missing_semantic_operations", "Semantic decision needs operations.")
    if decision == "no_semantic_delta" and operations:
        _error("no_delta_with_operations", "No-delta must be empty.")
    keys = [item["operation_key"] for item in operations]
    if len(keys) != len(set(keys)):
        _error("duplicate_operation_key", "Operation keys must be unique.")
    targets = [
        item["item_id"] for item in operations if item["item_id"] is not None
    ]
    if len(targets) != len(set(targets)):
        _error(
            "duplicate_operation_target",
            "One bundle cannot ambiguously target an item twice.",
        )
    binding = raw["scope_binding_operation"]
    normalized_binding = None
    if binding is not None:
        binding_raw = _exact(
            binding,
            ("choice_code", "expected_binding_revision"),
            path="continuity_intent.scope_binding_operation",
        )
        normalized_binding = {
            "choice_code": _code(
                binding_raw["choice_code"],
                name="choice_code",
                allowed=PROVISIONAL_BINDING_CHOICES,
            ),
            "expected_binding_revision": _integer(
                binding_raw["expected_binding_revision"],
                name="expected_binding_revision",
                minimum=1,
            ),
        }
    if len(operations) + (1 if normalized_binding else 0) > MAX_TOTAL_OPERATIONS:
        _error("too_many_operations", "Intent exceeds operation cap.")
    return {
        "capability": raw["capability"],
        "schema_version": INTENT_SCHEMA_VERSION,
        "protocol_version": INTENT_PROTOCOL_VERSION,
        "coverage_decision": decision,
        "semantic_operations": operations,
        "scope_binding_operation": normalized_binding,
    }


def _canonicalize_false_scope_conflict(
    intent: dict[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Turn a provider-only false scope conflict into canonical no-delta.

    The working-set projection has already selected the current room's
    eligible items.  A provider-created ``pending_review/scope_conflict`` is
    therefore not a semantic delta when every cited item is present in that
    projection and every room-scoped citation belongs to the current room.
    Unknown or foreign-room citations remain review candidates and are never
    silently discarded.
    """

    if (
        intent["coverage_decision"] != "semantic_operations"
        or len(intent["semantic_operations"]) != 1
        or intent["scope_binding_operation"] is not None
    ):
        return intent
    operation = intent["semantic_operations"][0]
    if (
        operation["operation_kind"] != "create"
        or operation["item_kind"] != "pending_review"
    ):
        return intent
    payload = operation["kind_payload"]
    if payload["review_kind"] != "scope_conflict":
        return intent
    conflicting_ids = payload["conflicting_item_ids"]
    if not conflicting_ids or payload["conflicting_event_ids"]:
        return intent
    reference_ids = list(
        dict.fromkeys(
            [*conflicting_ids, *payload["linked_item_ids"]]
        )
    )
    item_map = {item["item_id"]: item for item in context["items"]}
    references = [item_map.get(item_id) for item_id in reference_ids]
    if any(item is None for item in references):
        return intent
    target_scope = operation["scope"]
    if any(
        item["scope"]["scope_kind"] == "room"
        and (
            item["scope"]["room_id"] != context["room_id"]
            or (
                target_scope["scope_kind"] == "room"
                and (
                    item["scope"]["project_id"]
                    != target_scope["project_id"]
                    or item["scope"]["thread_id"]
                    != target_scope["thread_id"]
                )
            )
        )
        for item in references
    ):
        return intent
    return {
        **intent,
        "coverage_decision": "no_semantic_delta",
        "semantic_operations": [],
    }


def _canonicalize_contextual_restatement(
    intent: dict[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Canonicalize only an explicitly bound contextual reassertion.

    Natural-language overlap is deliberately not evidence.  A changed
    summary can remove write authority only when the producer supplies the
    versioned structured evidence object, bound to the exact offered item and
    its durable content digest.  A missing, mismatched, or unknown evidence
    value leaves the revision writable or fails closed; it never infers
    equivalence from words, operation keys, or scenario labels.
    """

    if (
        intent["coverage_decision"] != "semantic_operations"
        or len(intent["semantic_operations"]) != 1
        or intent["scope_binding_operation"] is not None
    ):
        return intent
    operation = intent["semantic_operations"][0]
    if operation["operation_kind"] != "revise":
        return intent
    offered = next(
        (
            item
            for item in context["items"]
            if item["item_id"] == operation["item_id"]
        ),
        None,
    )
    if offered is None:
        return intent
    evidence = operation.get("semantic_evidence")
    if evidence is not None and (
        evidence["authoritative_item_id"] != offered["item_id"]
        or evidence["authoritative_content_sha256"]
        != offered["content_sha256"]
    ):
        _error(
            "semantic_evidence_authority_mismatch",
            "Semantic evidence is not bound to the offered item.",
        )
    candidate_summary = operation["summary"] or offered["summary"]
    if evidence is not None and evidence["candidate_summary_sha256"] != canonical_sha256(candidate_summary):
        if evidence["comparison"] == "contextual_restatement":
            _error(
                "semantic_evidence_candidate_mismatch",
                "Semantic evidence does not bind the proposed summary.",
            )
        # A genuine revision is a provider candidate, not a provider-granted
        # authority decision.  The digest is explanatory evidence only for
        # that branch; recompute it locally so a model's hash arithmetic cannot
        # turn a real semantic revision into a false fail-closed rejection.
        if (
            context.get(SEMANTIC_EVALUATION_FIELD, {}).get("request_relation")
            == "contextual_return"
        ):
            _error(
                "semantic_evidence_candidate_mismatch",
                "Contextual-return evidence does not bind the proposed summary.",
            )
        corrected_evidence = {
            **evidence,
            "candidate_summary_sha256": canonical_sha256(candidate_summary),
        }
        corrected_operation = {
            **operation,
            "semantic_evidence": corrected_evidence,
        }
        intent = {
            **intent,
            "semantic_operations": [corrected_operation],
        }
        operation = corrected_operation
    candidate_payload = dict(offered["kind_payload"])
    candidate_payload.update(operation["kind_payload"])
    if evidence is None:
        if (
            context.get(SEMANTIC_NOVELTY_POLICY_FIELD)
            == SEMANTIC_NOVELTY_POLICY_VERSION
            and candidate_summary != offered["summary"]
            and candidate_payload == offered["kind_payload"]
        ):
            _error(
                "semantic_evidence_required",
                "Changed summary-only revisions require structured semantic evidence.",
            )
        return intent
    if candidate_payload != offered["kind_payload"]:
        if (
            evidence is not None
            and evidence["comparison"] == "contextual_restatement"
        ):
            _error(
                "semantic_evidence_semantic_fields_mismatch",
                "A contextual reassertion cannot change semantic payload fields.",
            )
        return intent
    if (
        evidence["comparison"] == "contextual_restatement"
        and operation["reason_code"] is not None
    ):
        _error(
            "semantic_evidence_semantic_fields_mismatch",
            "A contextual reassertion cannot carry new authored meaning.",
        )
    current_summary = offered["summary"]
    if candidate_summary == current_summary:
        return {
            **intent,
            "coverage_decision": "no_semantic_delta",
            "semantic_operations": [],
        }
    if evidence["comparison"] == "genuine_revision":
        return intent
    return {
        **intent,
        "coverage_decision": "no_semantic_delta",
        "semantic_operations": [],
    }


def _active_review_or_conflict_exists(context: Mapping[str, Any]) -> bool:
    return any(
        item["lifecycle_state"] == "active"
        and item["item_kind"] == "pending_review"
        for item in context["items"]
    )


def _canonicalize_authoritative_reaffirmation(
    intent: dict[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate exact provider proposals against accepted semantic state.

    This is deliberately structural.  It ignores item provenance and IDs when
    comparing a proposed create, but never infers semantic equivalence from
    wording.  Resolve is evaluated as a no-op only for an explicit,
    projection-bound contextual-return request; unknown request intent stays
    writable so a genuine lifecycle action cannot be hidden by a default.
    """

    evaluation = context.get(SEMANTIC_EVALUATION_FIELD)
    if not isinstance(evaluation, Mapping) or (
        evaluation.get("request_relation") != "contextual_return"
    ):
        return intent
    if (
        intent["coverage_decision"] != "semantic_operations"
        or len(intent["semantic_operations"]) != 1
        or intent["scope_binding_operation"] is not None
        or context["provisional_scope_binding_choices"]
        or _active_review_or_conflict_exists(context)
    ):
        return intent

    operation = intent["semantic_operations"][0]
    offered_items = [
        item
        for item in context["items"]
        if item["lifecycle_state"] == "active"
    ]

    if operation["operation_kind"] == "create":
        candidate = {
            "item_kind": operation["item_kind"],
            "scope": operation["scope"],
            "summary": operation["summary"],
            "kind_payload": operation["kind_payload"],
        }
        if any(
            candidate
            == {
                "item_kind": item["item_kind"],
                "scope": item["scope"],
                "summary": item["summary"],
                "kind_payload": item["kind_payload"],
            }
            for item in offered_items
        ):
            return {
                **intent,
                "coverage_decision": "no_semantic_delta",
                "semantic_operations": [],
            }
        return intent

    offered = next(
        (
            item
            for item in offered_items
            if item["item_id"] == operation["item_id"]
        ),
        None,
    )
    if offered is None or operation["reason_code"] is not None:
        return intent

    if operation["operation_kind"] == "revise":
        candidate_summary = operation["summary"] or offered["summary"]
        candidate_payload = dict(offered["kind_payload"])
        candidate_payload.update(operation["kind_payload"])
        if (
            candidate_summary == offered["summary"]
            and candidate_payload == offered["kind_payload"]
        ):
            return {
                **intent,
                "coverage_decision": "no_semantic_delta",
                "semantic_operations": [],
            }
        return intent

    if (
        operation["operation_kind"] == "resolve"
        and operation["item_kind"] != "pending_review"
    ):
        return {
            **intent,
            "coverage_decision": "no_semantic_delta",
            "semantic_operations": [],
        }
    return intent


def is_no_delta_canonicalization(bundle: Mapping[str, Any]) -> bool:
    """Return whether shared validation removed semantic write authority."""

    return bundle.get("canonicalization_code") in NO_DELTA_CANONICALIZATION_CODES

def validate_intent_against_context(
    intent: Any,
    command_context: Any,
    *,
    current_snapshot_sequence: int,
    current_snapshot_sha256: str,
    current_binding_revision: int,
    expected_command_context_id: str | None = None,
    expected_command_context_sha256: str | None = None,
) -> dict[str, Any]:
    context = validate_command_context(command_context)
    normalized = validate_continuity_intent(intent)
    context_hash = canonical_sha256(context)
    if (
        context["snapshot_global_event_sequence"] != current_snapshot_sequence
        or context["snapshot_global_event_sha256"] != current_snapshot_sha256
    ):
        _error("stale_command_context_snapshot", "Snapshot binding is stale.")
    if context["scope_binding_revision"] != current_binding_revision:
        _error("stale_scope_binding_revision", "Scope binding is stale.")
    if (
        expected_command_context_id is not None
        and context["context_id"] != expected_command_context_id
    ):
        _error("wrong_command_context_id", "Capability context ID differs.")
    if (
        expected_command_context_sha256 is not None
        and context_hash != expected_command_context_sha256
    ):
        _error("wrong_command_context_sha256", "Capability context hash differs.")
    item_map = {item["item_id"]: item for item in context["items"]}
    offer_map = {
        canonical_sha256(offer["scope"]): offer for offer in context["create_offers"]
    }
    operation_bindings = []
    for operation in normalized["semantic_operations"]:
        if operation["operation_kind"] == "create":
            offer = offer_map.get(canonical_sha256(operation["scope"]))
            if offer is None:
                _error("unoffered_create_scope", "Create scope was not offered.")
            if operation["item_kind"] not in offer["allowed_item_kinds"]:
                _error("unoffered_create_kind", "Create kind was not offered.")
            operation_bindings.append(
                {
                    "operation_key": operation["operation_key"],
                    "offer_id": offer["offer_id"],
                    "scope_sha256": canonical_sha256(offer["scope"]),
                    "preserved_content_sha256": None,
                    "successor_relationship_sha256": None,
                }
            )
            continue
        offered = item_map.get(operation["item_id"])
        if offered is None:
            _error("unoffered_item", "Target item was not offered.")
        if operation["expected_revision"] != offered["revision"]:
            _error("wrong_item_revision", "Target revision differs.")
        if operation["operation_kind"] not in offered["allowed_operations"]:
            _error("unoffered_operation", "Operation was not offered.")
        if (
            operation["item_kind"] != offered["item_kind"]
            or operation["scope"] != offered["scope"]
        ):
            _error("target_projection_mismatch", "Kind/scope binding differs.")
        if operation["operation_kind"] == "supersede":
            successor_id = operation["superseded_by_item_id"]
            if successor_id not in offered["offered_successor_item_ids"]:
                _error(
                    "unoffered_supersession_target",
                    "Successor relationship was not offered.",
                )
            successor = item_map[successor_id]
            if (
                successor["item_kind"] != offered["item_kind"]
                or successor["scope"] != offered["scope"]
            ):
                _error(
                    "incompatible_supersession_target",
                    "Successor kind/scope is incompatible.",
                )
        if operation["operation_kind"] == "reopen" and offered[
            "lifecycle_state"
        ] not in {"resolved", "abandoned"}:
            _error("invalid_reopen_target", "Reopen requires resolved/abandoned.")
        operation_bindings.append(
            {
                "operation_key": operation["operation_key"],
                "offer_id": None,
                "scope_sha256": canonical_sha256(offered["scope"]),
                "preserved_content_sha256": (
                    offered["content_sha256"]
                    if operation["operation_kind"]
                    in {"confirm", "resolve", "supersede", "reopen"}
                    else None
                ),
                "successor_relationship_sha256": (
                    canonical_sha256(
                        {
                            "item_id": offered["item_id"],
                            "successor_item_id": operation[
                                "superseded_by_item_id"
                            ],
                            "item_kind": offered["item_kind"],
                            "scope": offered["scope"],
                        }
                    )
                    if operation["operation_kind"] == "supersede"
                    else None
                ),
            }
        )
    if normalized["scope_binding_operation"] is not None:
        offered_choices = {
            item["choice_code"]: item
            for item in context["provisional_scope_binding_choices"]
        }
        binding = normalized["scope_binding_operation"]
        offered = offered_choices.get(binding["choice_code"])
        if offered is None:
            _error("unoffered_binding_choice", "Binding choice was not offered.")
        if (
            binding["expected_binding_revision"]
            != offered["expected_binding_revision"]
        ):
            _error("wrong_binding_revision", "Binding revision differs.")
    original_normalized = normalized
    normalized = _canonicalize_false_scope_conflict(normalized, context)
    canonicalization_code = None
    evaluation_code = None
    if normalized is not original_normalized:
        canonicalization_code = FALSE_SCOPE_CONFLICT_CANONICALIZATION_CODE
    else:
        normalized = _canonicalize_contextual_restatement(normalized, context)
        if normalized is not original_normalized:
            if normalized["coverage_decision"] == "no_semantic_delta":
                canonicalization_code = (
                    CONTEXTUAL_RESTATEMENT_CANONICALIZATION_CODE
                )
            else:
                evaluation_code = GENUINE_REVISION_EVIDENCE_RECOMPUTED_CODE
    if (
        normalized["coverage_decision"] != "no_semantic_delta"
        and (
            normalized is original_normalized
            or evaluation_code == GENUINE_REVISION_EVIDENCE_RECOMPUTED_CODE
        )
    ):
        normalized = _canonicalize_authoritative_reaffirmation(
            normalized, context
        )
        if normalized is not original_normalized:
            if normalized["coverage_decision"] == "no_semantic_delta":
                canonicalization_code = (
                    AUTHORITATIVE_REAFFIRMATION_CANONICALIZATION_CODE
                )
    result = {
        "schema_version": "house_continuity_validated_command_bundle_v1",
        "command_context_id": context["context_id"],
        "command_context_sha256": context_hash,
        "snapshot_global_event_sequence": context[
            "snapshot_global_event_sequence"
        ],
        "snapshot_global_event_sha256": context[
            "snapshot_global_event_sha256"
        ],
        "scope_binding_revision": context["scope_binding_revision"],
        "intent": normalized,
        "candidate_intent": deepcopy(original_normalized),
        "evaluated_intent": deepcopy(normalized),
        "operation_context_bindings": (
            []
            if normalized["coverage_decision"] == "no_semantic_delta"
            else operation_bindings
        ),
        "authorship_kind": "solen_explicit",
        "author_participants": ["solen"],
        "astel_or_joint_authorship_minted": False,
    }
    if canonicalization_code is not None:
        result["canonicalization_code"] = canonicalization_code
    if evaluation_code is not None:
        result["evaluation_code"] = evaluation_code
    return result

def _context_binding_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "command_context_id": _id(
            raw["command_context_id"], name="command_context_id", kind="context_id"
        ),
        "command_context_sha256": _hash(
            raw["command_context_sha256"], name="command_context_sha256"
        ),
        "snapshot_global_event_sequence": _integer(
            raw["snapshot_global_event_sequence"],
            name="snapshot_global_event_sequence",
        ),
        "snapshot_global_event_sha256": _hash(
            raw["snapshot_global_event_sha256"],
            name="snapshot_global_event_sha256",
        ),
        "scope_binding_revision": _integer(
            raw["scope_binding_revision"],
            name="scope_binding_revision",
            minimum=1,
        ),
    }

def validate_intent_capability(value: Any) -> dict[str, Any]:
    fields = (
        "schema_version",
        "capability_id",
        "creation_seed_sha256",
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
        "coverage_binding_state",
        "covered_complete_unit_ids",
        "covered_complete_unit_sha256s",
        "state",
        "issued_at",
        "expires_at",
        "consumed_at",
        "outbox_bundle_id",
        "terminal_response_sha256",
        "replay_attempt_count",
    )
    raw = _exact(value, fields, path="intent_capability")
    if raw["schema_version"] != CAPABILITY_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported capability schema.")
    if raw["protocol_version"] != INTENT_PROTOCOL_VERSION:
        _error("invalid_protocol_version", "Capability protocol differs.")
    binding = _code(
        raw["coverage_binding_state"],
        name="coverage_binding_state",
        allowed=("pending_complete_unit", "bound", "binding_failed"),
    )
    units = _id_list(
        raw["covered_complete_unit_ids"],
        name="covered_complete_unit_ids",
        maximum=MAX_COMPLETE_UNIT_IDS,
    )
    hashes = [
        _hash(item, name="covered_complete_unit_sha256")
        for item in raw["covered_complete_unit_sha256s"]
    ] if isinstance(raw["covered_complete_unit_sha256s"], list) else []
    if (
        len(hashes) > MAX_COMPLETE_UNIT_IDS
        or len(hashes) != len(set(hashes))
        or len(units) != len(hashes)
        or (binding == "bound") != bool(units)
    ):
        _error("invalid_complete_unit_binding", "Unit binding is inconsistent.")
    state = _code(
        raw["state"],
        name="state",
        allowed=(
            "issued",
            "prepared_consumed",
            "rejected_consumed",
            "closed_unused",
            "expired",
            "invalidated",
        ),
    )
    consumed = raw["consumed_at"]
    bundle = raw["outbox_bundle_id"]
    response_hash = raw["terminal_response_sha256"]
    if state in {"issued", "closed_unused", "expired", "invalidated"}:
        if any(item is not None for item in (consumed, bundle, response_hash)):
            _error(
                "invalid_unconsumed_capability",
                f"{state} cannot contain consumption evidence.",
            )
    elif state in {"prepared_consumed", "rejected_consumed"}:
        consumed = _timestamp(consumed, name="consumed_at")
        if state == "prepared_consumed":
            bundle = _id(bundle, name="outbox_bundle_id", kind="bundle_id")
            response_hash = _hash(
                response_hash, name="terminal_response_sha256"
            )
        else:
            if bundle is not None:
                _error(
                    "unexpected_outbox_bundle",
                    "Rejected capability has no outbox bundle.",
                )
            response_hash = _hash(
                response_hash, name="terminal_response_sha256"
            )
    issued = _timestamp(raw["issued_at"], name="issued_at")
    expires = _timestamp(raw["expires_at"], name="expires_at")
    if _timestamp_value(expires) <= _timestamp_value(issued):
        _error("invalid_capability_expiry", "Expiry must follow issue.")
    if consumed is not None and _timestamp_value(consumed) < _timestamp_value(issued):
        _error("invalid_capability_consumption_time", "Consumption precedes issue.")
    return {
        **raw,
        "capability_id": _id(
            raw["capability_id"], name="capability_id", kind="capability_id"
        ),
        "creation_seed_sha256": _hash(
            raw["creation_seed_sha256"], name="creation_seed_sha256"
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
        **_context_binding_fields(raw),
        "coverage_binding_state": binding,
        "covered_complete_unit_ids": units,
        "covered_complete_unit_sha256s": hashes,
        "state": state,
        "consumed_at": consumed,
        "outbox_bundle_id": bundle,
        "terminal_response_sha256": response_hash,
        "issued_at": issued,
        "expires_at": expires,
        "replay_attempt_count": _integer(
            raw["replay_attempt_count"], name="replay_attempt_count"
        ),
    }

def validate_intent_against_capability(
    intent: Any,
    command_context: Any,
    capability: Any,
    *,
    current_snapshot_sequence: int,
    current_snapshot_sha256: str,
    current_binding_revision: int,
) -> dict[str, Any]:
    normalized_capability = validate_intent_capability(capability)
    normalized_intent = validate_continuity_intent(intent)
    if normalized_capability["state"] != "issued":
        _error("capability_not_issued", "Capability is not available for authorship.")
    clear_digest = hashlib.sha256(
        normalized_intent["capability"].encode("ascii")
    ).hexdigest()
    if clear_digest != normalized_capability["capability_sha256"]:
        _error("capability_digest_mismatch", "Offered capability differs.")
    result = validate_intent_against_context(
        normalized_intent,
        command_context,
        current_snapshot_sequence=current_snapshot_sequence,
        current_snapshot_sha256=current_snapshot_sha256,
        current_binding_revision=current_binding_revision,
        expected_command_context_id=normalized_capability[
            "command_context_id"
        ],
        expected_command_context_sha256=normalized_capability[
            "command_context_sha256"
        ],
    )
    if (
        result["snapshot_global_event_sequence"]
        != normalized_capability["snapshot_global_event_sequence"]
        or result["snapshot_global_event_sha256"]
        != normalized_capability["snapshot_global_event_sha256"]
        or result["scope_binding_revision"]
        != normalized_capability["scope_binding_revision"]
    ):
        _error(
            "capability_context_binding_mismatch",
            "Capability snapshot/binding evidence differs.",
        )
    return result

def validate_capability_offer(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "state",
            "protocol_version",
            "capability",
            "coverage_decision_required",
            "maximum_total_operations",
            "expires_at",
        ),
        path="capability_offer",
    )
    if raw["schema_version"] != CAPABILITY_OFFER_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported capability offer.")
    state = _code(
        raw["state"], name="state", allowed=("offered", "unavailable")
    )
    if raw["protocol_version"] != INTENT_PROTOCOL_VERSION:
        _error("invalid_protocol_version", "Capability protocol differs.")
    if state == "offered":
        if (
            not isinstance(raw["capability"], str)
            or _CAPABILITY_RE.fullmatch(raw["capability"]) is None
            or raw["coverage_decision_required"] is not True
            or raw["maximum_total_operations"] != MAX_TOTAL_OPERATIONS
            or raw["expires_at"] is None
        ):
            _error("invalid_offered_capability", "Offered fields differ.")
        capability = raw["capability"]
        expires_at = _timestamp(raw["expires_at"], name="expires_at")
    else:
        if (
            raw["capability"] is not None
            or raw["coverage_decision_required"] is not False
            or raw["maximum_total_operations"] != 0
            or raw["expires_at"] is not None
        ):
            _error(
                "invalid_unavailable_capability",
                "Unavailable offer carries no capability authority.",
            )
        capability = None
        expires_at = None
    return {
        "schema_version": CAPABILITY_OFFER_SCHEMA_VERSION,
        "state": state,
        "protocol_version": INTENT_PROTOCOL_VERSION,
        "capability": capability,
        "coverage_decision_required": state == "offered",
        "maximum_total_operations": (
            MAX_TOTAL_OPERATIONS if state == "offered" else 0
        ),
        "expires_at": expires_at,
    }

__all__ = [
    "COMMAND_CONTEXT_SCHEMA_VERSION",
    "INTENT_SCHEMA_VERSION",
    "INTENT_PROTOCOL_VERSION",
    "CAPABILITY_OFFER_SCHEMA_VERSION",
    "CAPABILITY_SCHEMA_VERSION",
    "SEMANTIC_OPERATION_KINDS",
    "COMMANDABLE_OPERATION_KINDS",
    "PROVISIONAL_BINDING_CHOICES",
    "COMMAND_CONTEXT_MAX_ITEMS",
    "COMMAND_CONTEXT_MAX_CREATE_OFFERS",
    "COMMAND_CONTEXT_MAX_BINDING_CHOICES",
    "COMMAND_CONTEXT_MAX_UTF8_BYTES",
    "MAX_TOTAL_OPERATIONS",
    "COMMAND_CONTEXT_AUTHORITY",
    "SEMANTIC_NOVELTY_COMPARISON_VERSION",
    "SEMANTIC_NOVELTY_EVIDENCE_SCHEMA_VERSION",
    "SEMANTIC_NOVELTY_MARKER_NAMESPACE",
    "SEMANTIC_NOVELTY_MARKER_VERSION",
    "LEGACY_FALSE_SCOPE_CANONICALIZATION_CODE",
    "FALSE_SCOPE_CONFLICT_CANONICALIZATION_CODE",
    "CONTEXTUAL_RESTATEMENT_CANONICALIZATION_CODE",
    "AUTHORITATIVE_REAFFIRMATION_CANONICALIZATION_CODE",
    "GENUINE_REVISION_EVIDENCE_RECOMPUTED_CODE",
    "NO_DELTA_CANONICALIZATION_CODES",
    "CANONICALIZATION_MARKER_COMPATIBILITY",
    "SEMANTIC_EVALUATION_FIELD",
    "SEMANTIC_EVALUATION_SCHEMA_VERSION",
    "SEMANTIC_EVALUATION_REQUEST_SCHEMA_VERSION",
    "SEMANTIC_EVALUATION_RELATIONS",
    "authoritative_projection_sha256",
    "validate_semantic_evaluation_request",
    "_OPERATION_FIELDS",
    "_context_item",
    "validate_command_context",
    "_semantic_operation",
    "validate_continuity_intent",
    "validate_intent_against_context",
    "is_no_delta_canonicalization",
    "_context_binding_fields",
    "validate_intent_capability",
    "validate_intent_against_capability",
    "validate_capability_offer",
]
