"""Cross-field authority, lifecycle, capability, and provenance contracts.

This focused owner keeps compatibility matrices out of the neutral schema
parser. It is provider-neutral and has no endpoint, runtime, or live behavior.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Mapping, Sequence

import provider_visible_text_safety_v0 as provider_text_safety


CONTRACT_SCHEMA_VERSION = "house_provider_neutral_contract_v5"
OUTPUT_POLICY_PROJECTION_VERSION = "house_output_policy_projection_v3"
PROACTIVE_EVENT_PROJECTION_VERSION = "house_proactive_event_projection_v4"

SOURCE_CLASS_ORDER = (
    "house_behavior_law",
    "astel_profile",
    "solen_profile",
    "relationship_footing",
    "memory",
    "capability_description",
    "room_checkpoint",
    "retrieved_memory",
    "standing_live_state",
    "conversation",
    "provider_agent_operation",
    "tool_result",
    "attachment",
    "current_input",
    "output_policy",
    "proactive_event",
)

AUTHORITY_SOURCE_CONTENT_MATRIX = {
    "instruction_law_units": {
        "authority_class": "instruction_law",
        "source_classes": ("house_behavior_law",),
        "content_kinds": ("exact_source_text", "house_derived_text", "structured_data"),
    },
    "context_data_units": {
        "authority_class": "context_data",
        "source_classes": (
            "astel_profile",
            "solen_profile",
            "relationship_footing",
            "memory",
            "capability_description",
            "room_checkpoint",
            "attachment",
        ),
        "content_kinds": (
            "exact_source_text",
            "house_derived_text",
            "structured_data",
            "code_source_quotation",
            "attachment_vision_description",
            "future_card_checkpoint",
        ),
    },
    "dynamic_context_units": {
        "authority_class": "dynamic_context",
        "source_classes": (
            "retrieved_memory",
            "standing_live_state",
            "tool_result",
            "attachment",
        ),
        "content_kinds": (
            "exact_source_text",
            "house_derived_text",
            "structured_data",
            "code_source_quotation",
            "attachment_vision_description",
            "operation_tool_result",
        ),
    },
    "current_input_unit": {
        "authority_class": "current_input",
        "source_classes": ("current_input",),
        "content_kinds": ("exact_source_text", "code_source_quotation"),
    },
    "output_policy.policy_unit": {
        "authority_class": "output_policy_data",
        "source_classes": ("output_policy",),
        "content_kinds": ("house_derived_text", "structured_data"),
    },
    "proactive_event.semantic_unit": {
        "authority_class": "dynamic_context",
        "source_classes": ("proactive_event",),
        "content_kinds": ("future_proactive_event",),
    },
    "conversation.user": {
        "authority_class": "conversation_user",
        "source_classes": ("conversation", "provider_agent_operation"),
        "content_kinds": ("exact_source_text", "code_source_quotation"),
    },
    "conversation.assistant": {
        "authority_class": "conversation_assistant",
        "source_classes": ("conversation", "provider_agent_operation"),
        "content_kinds": (
            "exact_source_text",
            "house_derived_text",
            "code_source_quotation",
            "attachment_vision_description",
        ),
    },
    "conversation.tool_result": {
        "authority_class": "conversation_tool_result",
        "source_classes": ("tool_result", "provider_agent_operation"),
        "content_kinds": (
            "exact_source_text",
            "structured_data",
            "code_source_quotation",
            "operation_tool_result",
        ),
    },
}

OPERATION_RESOLUTION_BY_STATE = {
    "accepted": "acknowledgement_only",
    "running": "acknowledgement_only",
    "completed": "final_only",
    "failed": "status_only",
    "timed_out": "status_only",
    "cancelled": "status_only",
    "interrupted": "status_only",
    "legacy_unknown": "legacy_all",
}

OPERATION_VISIBLE_COLLECTION_BY_RESOLUTION = {
    "acknowledgement_only": "acknowledgement_segments",
    "final_only": "final_segments",
    "status_only": "status_segments",
    "legacy_all": "legacy_segments",
}

ORDINARY_CONVERSATION_COMPLETION_BY_ROLE = {
    "user": ("complete",),
    "assistant": ("complete",),
    "tool_result": ("complete",),
}

DERIVED_CONTENT_KINDS = {
    "house_derived_text",
    "structured_data",
    "attachment_vision_description",
    "future_card_checkpoint",
    "future_proactive_event",
}
EXACT_SOURCE_CONTENT_KINDS = {
    "exact_source_text",
    "code_source_quotation",
    "operation_tool_result",
}
CONTENT_KIND_EXACTNESS_MATRIX = {
    "exact_source_text": ("exact", "mixed"),
    "code_source_quotation": ("exact", "mixed"),
    "operation_tool_result": ("exact", "mixed"),
    "house_derived_text": ("derived", "mixed"),
    "structured_data": ("derived", "mixed"),
    "attachment_vision_description": ("derived", "mixed"),
    "future_card_checkpoint": ("derived", "mixed"),
    "future_proactive_event": ("derived", "mixed"),
}
REPRESENTATION_CHANGE_FLAGS = {
    "provider_safety_redacted",
    "credential_redacted",
    "content_abridged",
    "unicode_normalized",
    "line_endings_normalized",
    "structured_rendered",
}
DERIVATION_CONDITION_FLAGS = {
    "continuity_derived",
    "structured_rendered",
    "attachment_described",
}
RESPONSE_VISIBLE_OUTPUT_MATRIX = {
    "natural_prose": "prose",
    "structured_data": "structured",
    "mixed": "prose_and_structured",
}
PROACTIVE_ALLOWED_CAPABILITIES = (
    "text_output",
    "structured_output",
    "tool_operations",
)

_RAW_FREE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")


class NeutralContractError(ValueError):
    """Raised when individually valid fields form an invalid semantic contract."""


def source_reference_identity(reference: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return the exact identity tuple for one source reference."""

    return (
        reference["source_class"],
        reference["source_id"],
        reference["range_start"],
        reference["range_end"],
    )


def source_reference_sort_key(reference: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return the canonical ordering key without changing reference identity."""

    return (
        SOURCE_CLASS_ORDER.index(reference["source_class"]),
        reference["source_id"],
        reference["range_start"] or "",
        reference["range_end"] or "",
    )


def deterministic_source_reference_union(
    units: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return the unique deterministic union of semantic-unit source refs."""

    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for unit in units:
        for reference in unit["source_references"]:
            key = source_reference_identity(reference)
            by_key[key] = dict(reference)
    return sorted(by_key.values(), key=source_reference_sort_key)


def canonical_projection_text(projection: Mapping[str, Any]) -> str:
    """Render one closed projection as deterministic compact JSON."""

    return json.dumps(
        projection,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def output_policy_projection(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Return only model-meaningful behavior from the outer machine policy."""

    projection = {
        "response_mode": policy["requested_response_form"],
        "split_behavior_available": (
            policy["split_marker_protocol_version"] is not None
        ),
    }
    if "continuity_authorship_available" in policy:
        projection.update(
            {
                "continuity_authorship_available": policy[
                    "continuity_authorship_available"
                ],
                "continuity_authorship_protocol_version": policy[
                    "continuity_authorship_protocol_version"
                ],
                "continuity_authorship_requires_turn_capability": policy[
                    "continuity_authorship_requires_turn_capability"
                ],
            }
        )
    projection.update(
        {
            "memory_authorship_available": (
                policy["memory_authorship_protocol_version"] is not None
            ),
            "reasoning_policy_state": policy["reasoning_policy_state"],
            "verbosity_policy_state": policy["verbosity_policy_state"],
            "modality": "text",
        }
    )
    return projection


def _provider_safe_projection_text(value: Any) -> str:
    """Return safe structured text without retaining a sensitive label."""

    text = str(value)
    sanitized = provider_text_safety.sanitize_provider_visible_text(text)
    if sanitized != text:
        return provider_text_safety.REDACTION_MARKER
    return sanitized


def _structured_datum_projection(
    datum: Mapping[str, Any],
    *,
    provider_safe: bool,
) -> dict[str, Any]:
    value_type = datum["value_type"]
    value = {
        "text": datum["text_value"],
        "integer": datum["integer_value"],
        "boolean": datum["boolean_value"],
        "null": None,
    }[value_type]
    if provider_safe and value_type == "text":
        value = _provider_safe_projection_text(value)
    return {
        "key": datum["key"],
        "value_type": value_type,
        "value": value,
    }


def proactive_event_projection(
    event: Mapping[str, Any],
    *,
    provider_safe: bool = False,
) -> dict[str, Any]:
    """Return the reviewed provider-visible projection of the event packet.

    Detector/lineage metadata and event/dedup identities remain internal.
    Event/dedup equality is closed by semantic source-reference identities.
    """

    reason_for_wake = event["reason_for_wake"]
    if provider_safe:
        reason_for_wake = _provider_safe_projection_text(
            reason_for_wake
        )
    return {
        "event_type": event["event_type"],
        "observed_at": event["observed_at"],
        "reason_for_wake": reason_for_wake,
        "state_snapshot": [
            _structured_datum_projection(
                datum,
                provider_safe=provider_safe,
            )
            for datum in event["state_snapshot"]
        ],
        "confidence_micros": event["confidence_micros"],
        "allowed_capabilities": list(event["allowed_capabilities"]),
        "quiet_constraints": [
            _structured_datum_projection(
                datum,
                provider_safe=provider_safe,
            )
            for datum in event["quiet_constraints"]
        ],
        "cost_constraints": [
            _structured_datum_projection(
                datum,
                provider_safe=provider_safe,
            )
            for datum in event["cost_constraints"]
        ],
    }


def validate_unit_compatibility(
    unit: Mapping[str, Any],
    *,
    owner: str,
) -> None:
    rule = AUTHORITY_SOURCE_CONTENT_MATRIX.get(owner)
    if rule is None:
        raise NeutralContractError(f"unknown semantic owner {owner!r}")
    if unit["authority_class"] != rule["authority_class"]:
        raise NeutralContractError(f"{owner} authority class is incompatible")
    if unit["source_class"] not in rule["source_classes"]:
        raise NeutralContractError(f"{owner} source class is incompatible")
    if any(
        reference["source_class"] not in rule["source_classes"]
        for reference in unit.get("source_references", ())
    ):
        raise NeutralContractError(f"{owner} source reference class is incompatible")
    if unit["content_kind"] not in rule["content_kinds"]:
        raise NeutralContractError(f"{owner} content kind is incompatible")
    if unit["content_kind"] == "future_card_checkpoint" and owner != "context_data_units":
        raise NeutralContractError("future card/checkpoint content is descriptive context only")
    if (
        unit["content_kind"] == "future_proactive_event"
        and owner != "proactive_event.semantic_unit"
    ):
        raise NeutralContractError(
            "future proactive content requires the explicit proactive packet"
        )
    if unit["content_kind"] == "operation_tool_result" and owner not in {
        "dynamic_context_units",
        "conversation.tool_result",
    }:
        raise NeutralContractError("operation/tool result content cannot gain instruction authority")


def validate_exactness_and_transformation(unit: Mapping[str, Any]) -> None:
    source_text = unit["source_text"]
    provider_text = unit["provider_text"]
    flags = set(unit["transformation_flags"])
    exactness = unit["exactness"]
    provenance = unit["internal_provenance"]
    derivation_version = provenance["derivation_version"]
    changed = source_text != provider_text
    content_kind = unit["content_kind"]
    allowed_exactness = CONTENT_KIND_EXACTNESS_MATRIX[content_kind]

    if exactness not in allowed_exactness:
        raise NeutralContractError(
            f"{content_kind} cannot use {exactness} exactness"
        )

    if exactness == "exact" and (changed or flags):
        raise NeutralContractError(
            "exact text requires identical source/provider text and no transformations"
        )
    if changed and not flags:
        raise NeutralContractError(
            "changed provider text requires a reviewed transformation flag"
        )
    if (
        flags & (REPRESENTATION_CHANGE_FLAGS - {"structured_rendered"})
        and not changed
    ):
        raise NeutralContractError(
            "representation-change flags require changed provider text"
        )
    if flags and not changed and not (
        flags <= DERIVATION_CONDITION_FLAGS
        and exactness in {"derived", "mixed"}
        and derivation_version is not None
    ):
        raise NeutralContractError(
            "unchanged text may carry only an explicit derived-condition flag"
        )
    if flags & DERIVATION_CONDITION_FLAGS and derivation_version is None:
        raise NeutralContractError(
            "derived-condition transformations require derivation provenance"
        )
    if content_kind in DERIVED_CONTENT_KINDS and derivation_version is None:
        raise NeutralContractError(
            "House-derived/structured/card/proactive/attachment content requires derivation provenance"
        )
    if exactness == "derived" and derivation_version is None:
        raise NeutralContractError("derived exactness requires derivation provenance")
    if content_kind in EXACT_SOURCE_CONTENT_KINDS and exactness == "mixed":
        if (
            not changed
            or not flags
            or not flags <= REPRESENTATION_CHANGE_FLAGS
        ):
            raise NeutralContractError(
                "mixed exact-source content requires a changed representation and only representation-change flags"
            )
    if exactness == "mixed":
        documented_multi_source = (
            len(deterministic_source_reference_union((unit,))) >= 2
            and derivation_version is not None
        )
        if (
            content_kind not in EXACT_SOURCE_CONTENT_KINDS
            and not flags
            and not documented_multi_source
        ):
            raise NeutralContractError(
                "mixed exactness requires a transformation or documented multi-source derivation"
            )


def validate_operation_lifecycle(operation: Mapping[str, Any]) -> None:
    state = operation["operation_state"]
    expected_resolution = OPERATION_RESOLUTION_BY_STATE.get(state)
    if expected_resolution is None:
        raise NeutralContractError(f"unsupported provider operation state {state!r}")
    if operation["provider_visible_resolution"] != expected_resolution:
        raise NeutralContractError("provider operation visibility resolution contradicts state")

    acknowledgements = operation["acknowledgement_segments"]
    finals = operation["final_segments"]
    statuses = operation["status_segments"]
    legacy = operation["legacy_segments"]

    if state in {"accepted", "running"}:
        if not acknowledgements or finals or statuses or legacy:
            raise NeutralContractError(
                "accepted/running operation requires acknowledgement-only segments"
            )
    elif state == "completed":
        if not finals or statuses or legacy:
            raise NeutralContractError(
                "completed operation requires a final and no terminal/legacy segments"
            )
    elif state in {"failed", "timed_out", "cancelled", "interrupted"}:
        if not statuses or finals or legacy:
            raise NeutralContractError(
                "terminal operation requires status and no final/legacy segments"
            )
    elif state == "legacy_unknown":
        if not legacy or acknowledgements or finals or statuses:
            raise NeutralContractError(
                "legacy operation requires untyped legacy segments only"
            )

    all_segments = [*acknowledgements, *finals, *statuses, *legacy]
    unit_ids = [unit["unit_id"] for unit in all_segments]
    if len(unit_ids) != len(set(unit_ids)):
        raise NeutralContractError("provider operation segment IDs must be unique")
    if any(
        unit["internal_provenance"]["operation_id"] != operation["operation_id"]
        for unit in all_segments
    ):
        raise NeutralContractError("provider operation segment identity is inconsistent")
    if any(unit["source_class"] != "provider_agent_operation" for unit in all_segments):
        raise NeutralContractError(
            "provider operation segments require provider-operation source ownership"
        )
    if any(
        reference["source_class"] != "provider_agent_operation"
        for unit in all_segments
        for reference in unit["source_references"]
    ):
        raise NeutralContractError(
            "provider operation segment references require provider-operation sources"
        )


def resolved_operation_segments(operation: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    validate_operation_lifecycle(operation)
    collection = OPERATION_VISIBLE_COLLECTION_BY_RESOLUTION[
        operation["provider_visible_resolution"]
    ]
    return tuple(operation[collection])


def validate_conversation_provenance(conversation: Mapping[str, Any]) -> None:
    operation = conversation["provider_operation"]
    if operation is None:
        owned_units = list(conversation["segments"])
    else:
        owned_units = [
            *operation["acknowledgement_segments"],
            *operation["final_segments"],
            *operation["status_segments"],
            *operation["legacy_segments"],
        ]
    expected_references = deterministic_source_reference_union(owned_units)
    actual_references = conversation["source_references"]
    actual_keys = [
        source_reference_identity(reference) for reference in actual_references
    ]
    if len(actual_keys) != len(set(actual_keys)):
        raise NeutralContractError("conversation source references contain duplicates")
    if actual_references != expected_references:
        raise NeutralContractError(
            "conversation source references must equal the deterministic segment-reference union"
        )

    conversation_provenance = conversation["internal_provenance"]
    for unit in owned_units:
        unit_provenance = unit["internal_provenance"]
        if (
            unit_provenance["owner"] != conversation_provenance["owner"]
            or unit_provenance["source_snapshot_id"]
            != conversation_provenance["source_snapshot_id"]
            or unit_provenance["operation_id"]
            != conversation_provenance["operation_id"]
        ):
            raise NeutralContractError(
                "conversation segment owner/snapshot/operation provenance is inconsistent"
            )
        if (
            unit["source_class"] == "provider_agent_operation"
            and unit_provenance["operation_id"] is None
        ):
            raise NeutralContractError(
                "provider-operation conversation sources require operation provenance"
            )


def validate_conversation_topology(
    conversations: Sequence[Mapping[str, Any]],
) -> None:
    """Close current history to complete user/assistant logical pairs."""

    if len(conversations) % 2:
        raise NeutralContractError(
            "conversation history must contain only complete user/assistant pairs"
        )

    parent_turn_ids: set[str] = set()
    operation_ids: set[str] = set()
    for pair_index in range(0, len(conversations), 2):
        user = conversations[pair_index]
        assistant = conversations[pair_index + 1]
        if user["role"] != "user" or assistant["role"] != "assistant":
            raise NeutralContractError(
                "conversation history must alternate one user then one assistant"
            )
        parent_turn_id = user["parent_turn_id"]
        if assistant["parent_turn_id"] != parent_turn_id:
            raise NeutralContractError(
                "conversation pair parent-turn identities must match"
            )
        operation = assistant["provider_operation"]
        if (
            operation is not None
            and operation["operation_id"] in operation_ids
        ):
            raise NeutralContractError(
                "provider operation identity must be globally unique"
            )
        if parent_turn_id in parent_turn_ids:
            raise NeutralContractError(
                "one parent-turn identity may own only one user/assistant pair"
            )
        parent_turn_ids.add(parent_turn_id)

        if operation is None:
            for conversation in (user, assistant):
                if (
                    conversation["operation_id"] is not None
                    or conversation["internal_provenance"]["operation_id"]
                    is not None
                ):
                    raise NeutralContractError(
                        "ordinary dialogue cannot carry public or internal operation identity"
                    )
                owned_units = conversation["segments"]
                if any(
                    unit["source_class"] == "provider_agent_operation"
                    or any(
                        reference["source_class"]
                        == "provider_agent_operation"
                        for reference in unit["source_references"]
                    )
                    for unit in owned_units
                ):
                    raise NeutralContractError(
                        "ordinary dialogue cannot use provider-operation source ownership"
                    )
            continue

        operation_id = operation["operation_id"]
        operation_ids.add(operation_id)
        if (
            parent_turn_id != operation_id
            or user["operation_id"] != operation_id
            or assistant["operation_id"] != operation_id
            or user["internal_provenance"]["operation_id"] != operation_id
            or assistant["internal_provenance"]["operation_id"] != operation_id
            or operation["request_unit_id"] != user["conversation_unit_id"]
        ):
            raise NeutralContractError(
                "provider operation must have one canonical request/assistant identity pair"
            )
        if (
            user["internal_provenance"]["owner"]
            != assistant["internal_provenance"]["owner"]
            or user["internal_provenance"]["source_snapshot_id"]
            != assistant["internal_provenance"]["source_snapshot_id"]
        ):
            raise NeutralContractError(
                "provider operation request and assistant provenance must match"
            )
        if any(
            unit["source_class"] != "provider_agent_operation"
            or unit["internal_provenance"]["operation_id"] != operation_id
            or any(
                reference["source_class"] != "provider_agent_operation"
                for reference in unit["source_references"]
            )
            for unit in user["segments"]
        ):
            raise NeutralContractError(
                "provider operation request requires operation-owned source provenance"
            )


def derive_required_capabilities(request: Mapping[str, Any]) -> frozenset[str]:
    required = {"instruction_authority", "text_output"}
    conversations = request["conversation_units"]
    if conversations:
        required.add("native_conversation_roles")
    split_present = request["output_policy"]["split_marker_protocol_version"] is not None
    for conversation in conversations:
        if conversation["provider_operation"] is None:
            visible_segments = conversation["segments"]
        else:
            visible_segments = resolved_operation_segments(conversation["provider_operation"])
        if len(visible_segments) > 1:
            split_present = True
    if split_present:
        required.add("split_segments")

    output_policy = request["output_policy"]
    if (
        output_policy["structured_output_schema_ref"] is not None
        or output_policy["requested_response_form"] in {"structured_data", "mixed"}
        or output_policy["visible_output"] in {"structured", "prose_and_structured"}
    ):
        required.add("structured_output")
    if request["proactive_event_unit"] is not None:
        required.add("proactive_event")
    if request["model_route"]["tool_mode"] != "none":
        required.add("tool_operations")
    return frozenset(required)


def validate_capability_consistency(request: Mapping[str, Any]) -> None:
    policy = request["provider_capability_policy"]
    required = set(policy["required_capabilities"])
    optional = set(policy["optional_capabilities"])
    forbidden = set(policy["forbidden_capabilities"])
    semantic_requirements = set(derive_required_capabilities(request))
    missing = semantic_requirements - required
    if missing:
        raise NeutralContractError(
            f"request semantic capabilities must be required: {sorted(missing)}"
        )
    if semantic_requirements & optional:
        raise NeutralContractError(
            "present request semantics cannot be optional-only capabilities"
        )
    if semantic_requirements & forbidden:
        raise NeutralContractError(
            "present request semantics cannot be forbidden capabilities"
        )
    proactive = request["proactive_event_unit"]
    if proactive is not None:
        allowed = set(proactive["allowed_capabilities"])
        if allowed & forbidden:
            raise NeutralContractError(
                "proactive allowed capabilities cannot be forbidden by the request"
            )
        if not allowed <= semantic_requirements:
            raise NeutralContractError(
                "proactive allowed capabilities must be active required request semantics"
            )
    tool_mode = request["model_route"]["tool_mode"]
    if tool_mode == "none":
        if (
            "tool_operations" in required
            or "tool_operations" in optional
            or "tool_operations" not in forbidden
        ):
            raise NeutralContractError(
                "tool mode none requires tool_operations to be forbidden"
            )
    elif "tool_operations" not in required:
        raise NeutralContractError(
            "enabled tool mode requires tool_operations capability"
        )


def validate_raw_free_identifier(
    value: Any,
    *,
    field: str,
) -> str:
    if not isinstance(value, str) or not _RAW_FREE_IDENTIFIER_RE.fullmatch(value):
        raise NeutralContractError(
            f"{field} must be a bounded ASCII identifier"
        )
    return value
