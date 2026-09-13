"""Provider-neutral House request schema and local validation.

This owner defines semantic units before any provider endpoint rendering. It
does not build Chat/Responses payloads, call a provider, or enter a live route.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, Iterator, Mapping, Sequence

import house_provider_neutral_contract_v1 as contract
import provider_visible_text_safety_v0 as provider_text_safety


REQUEST_SCHEMA_VERSION = "house_provider_neutral_request_v4"
REQUEST_MODEL_VERSION = "house_provider_request_model_v4"
SEMANTIC_UNIT_SCHEMA_VERSION = "house_provider_semantic_unit_v4"
SOURCE_REFERENCE_SCHEMA_VERSION = "house_provider_source_reference_v1"
UNIT_PROVENANCE_SCHEMA_VERSION = "house_provider_unit_provenance_v0"
REQUEST_PROVENANCE_SCHEMA_VERSION = "house_provider_request_provenance_v1"
STRUCTURED_DATUM_SCHEMA_VERSION = "house_provider_structured_datum_v1"
CONVERSATION_UNIT_SCHEMA_VERSION = "house_provider_conversation_unit_v3"
PROVIDER_OPERATION_SCHEMA_VERSION = "house_provider_operation_v1"
PROACTIVE_EVENT_SCHEMA_VERSION = "house_provider_proactive_event_v3"
MODEL_ROUTE_SCHEMA_VERSION = "house_provider_model_route_v0"
OUTPUT_POLICY_SCHEMA_VERSION = "house_provider_output_policy_v2"
OUTPUT_TOKEN_POLICY_SCHEMA_VERSION = "house_provider_output_token_policy_v1"
CAPABILITY_POLICY_SCHEMA_VERSION = "house_provider_capability_policy_v1"

AUTHORITY_CLASSES = (
    "instruction_law",
    "context_data",
    "conversation_user",
    "conversation_assistant",
    "conversation_tool_result",
    "dynamic_context",
    "current_input",
    "output_policy_data",
)
CONTENT_KINDS = (
    "exact_source_text",
    "house_derived_text",
    "structured_data",
    "code_source_quotation",
    "attachment_vision_description",
    "operation_tool_result",
    "future_card_checkpoint",
    "future_proactive_event",
)
TRANSFORMATION_FLAGS = (
    "provider_safety_redacted",
    "credential_redacted",
    "content_abridged",
    "unicode_normalized",
    "line_endings_normalized",
    "continuity_derived",
    "structured_rendered",
    "attachment_described",
)
EXACTNESS_VALUES = ("exact", "derived", "mixed")
SOURCE_CLASSES = contract.SOURCE_CLASS_ORDER
INITIATION_TYPES = ("user", "tool_follow_up", "proactive")
RESERVED_INITIATION_TYPES = ("tool_follow_up",)
CONVERSATION_ROLES = ("user", "assistant", "tool_result")
COMPLETION_STATES = (
    "open",
    "complete",
    "partial",
    "failed",
    "timed_out",
    "cancelled",
    "interrupted",
    "legacy_unknown",
)
OPERATION_STATES = tuple(contract.OPERATION_RESOLUTION_BY_STATE)
PROVIDER_VISIBLE_RESOLUTIONS = tuple(contract.OPERATION_VISIBLE_COLLECTION_BY_RESOLUTION)
ROUTE_CLASSES = ("main_talk", "provider_agent", "local_fixture")
MODEL_CLASSES = ("general_dialogue", "reasoning", "multimodal", "provider_neutral_fixture")
TOOL_MODES = ("none", "read_only", "bounded_effects")
CAPABILITIES = (
    "instruction_authority",
    "native_conversation_roles",
    "text_output",
    "structured_output",
    "split_segments",
    "tool_operations",
    "vision_input",
    "audio_input",
    "prompt_caching",
    "proactive_event",
)
RESPONSE_FORMS = ("natural_prose", "structured_data", "mixed")
VISIBLE_OUTPUT_MODES = ("prose", "structured", "prose_and_structured")
OUTPUT_TOKEN_MODES = ("unspecified", "advisory", "requested_limit")
REASONING_POLICY_STATES = ("unspecified", "minimal", "balanced", "deep")
VERBOSITY_POLICY_STATES = ("unspecified", "concise", "balanced", "detailed")
MODALITIES = ("text", "image", "audio")
CURRENT_MODALITIES = ("text",)
STRUCTURED_VALUE_TYPES = ("text", "integer", "boolean", "null")
BUILD_MODES = ("synthetic_fixture", "local_shadow")
EVENT_TYPES = ("state_change", "scheduled", "external_signal", "synthetic_fixture")
DETECTOR_CLASSES = ("state_observer", "schedule", "external_adapter", "synthetic_fixture")
MAX_REQUESTED_OUTPUT_TOKENS = (2**31) - 1

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,179}$")
_DATUM_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,95}$")


class NeutralRequestValidationError(ValueError):
    """Raised when a neutral request violates a closed local schema."""


def _validate_unicode_scalars(value: str, *, field: str) -> None:
    if any("\ud800" <= character <= "\udfff" for character in value):
        raise NeutralRequestValidationError(
            f"{field} must contain only Unicode scalar values"
        )


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NeutralRequestValidationError(f"{field} must be an object")
    return value


def _exact_fields(value: Mapping[str, Any], fields: Sequence[str], *, field: str) -> None:
    actual = set(value)
    expected = set(fields)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise NeutralRequestValidationError(
            f"{field} fields are closed; missing={missing or []}; unknown={unknown or []}"
        )


def _string(value: Any, *, field: str, allow_empty: bool = False, max_chars: int = 20000) -> str:
    if not isinstance(value, str):
        raise NeutralRequestValidationError(f"{field} must be a string")
    _validate_unicode_scalars(value, field=field)
    if not allow_empty and not value:
        raise NeutralRequestValidationError(f"{field} must not be empty")
    if len(value) > max_chars:
        raise NeutralRequestValidationError(f"{field} exceeds {max_chars} characters")
    return value


def _optional_string(value: Any, *, field: str, max_chars: int = 20000) -> str | None:
    if value is None:
        return None
    return _string(value, field=field, max_chars=max_chars)


def _identifier(value: Any, *, field: str) -> str:
    text = _string(value, field=field, max_chars=180)
    if not _IDENTIFIER_RE.fullmatch(text):
        raise NeutralRequestValidationError(f"{field} must be a bounded ASCII identifier")
    return text


def _optional_identifier(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field=field)


def _enum(value: Any, allowed: Sequence[str], *, field: str) -> str:
    text = _string(value, field=field, max_chars=96)
    if text not in allowed:
        raise NeutralRequestValidationError(f"{field} has unsupported value {text!r}")
    return text


def _integer(value: Any, *, field: str, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        range_text = f"{minimum}.." + (str(maximum) if maximum is not None else "unbounded")
        raise NeutralRequestValidationError(f"{field} must be an integer in {range_text}")
    return value


def _boolean(value: Any, *, field: str) -> bool:
    if type(value) is not bool:
        raise NeutralRequestValidationError(f"{field} must be a boolean")
    return value


def _list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise NeutralRequestValidationError(f"{field} must be a list")
    return value


def _stable_enum_list(value: Any, allowed: Sequence[str], *, field: str) -> list[str]:
    items = [_enum(item, allowed, field=f"{field}[]") for item in _list(value, field=field)]
    if len(items) != len(set(items)):
        raise NeutralRequestValidationError(f"{field} contains duplicate values")
    rank = {item: index for index, item in enumerate(allowed)}
    return sorted(items, key=rank.__getitem__)


def _nfc_lf_text(value: str, *, field: str) -> None:
    if unicodedata.normalize("NFC", value) != value:
        raise NeutralRequestValidationError(f"{field} must already use reviewed NFC text")
    if "\r" in value:
        raise NeutralRequestValidationError(f"{field} must already use LF line endings")


def source_reference(
    *,
    source_class: str,
    source_id: str,
    range_start: str | None = None,
    range_end: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SOURCE_REFERENCE_SCHEMA_VERSION,
        "source_class": source_class,
        "source_id": source_id,
        "range_start": range_start,
        "range_end": range_end,
    }


def unit_provenance(
    *,
    owner: str,
    source_snapshot_id: str,
    derivation_version: str | None = None,
    operation_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": UNIT_PROVENANCE_SCHEMA_VERSION,
        "owner": owner,
        "source_snapshot_id": source_snapshot_id,
        "derivation_version": derivation_version,
        "operation_id": operation_id,
    }


def structured_datum(
    *,
    key: str,
    value_type: str,
    text_value: str | None = None,
    integer_value: int | None = None,
    boolean_value: bool | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": STRUCTURED_DATUM_SCHEMA_VERSION,
        "key": key,
        "value_type": value_type,
        "text_value": text_value,
        "integer_value": integer_value,
        "boolean_value": boolean_value,
    }


def semantic_unit(
    *,
    unit_id: str,
    ordinal: int,
    authority_class: str,
    content_kind: str,
    source_text: str,
    provider_text: str,
    transformation_flags: Sequence[str],
    exactness: str,
    source_class: str,
    source_references: Sequence[Mapping[str, Any]],
    internal_provenance: Mapping[str, Any],
    structured_data: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "schema_version": SEMANTIC_UNIT_SCHEMA_VERSION,
        "unit_id": unit_id,
        "ordinal": ordinal,
        "authority_class": authority_class,
        "content_kind": content_kind,
        "source_text": source_text,
        "provider_text": provider_text,
        "transformation_flags": list(transformation_flags),
        "exactness": exactness,
        "source_class": source_class,
        "source_references": [dict(item) for item in source_references],
        "internal_provenance": dict(internal_provenance),
        "structured_data": [dict(item) for item in structured_data],
    }


def _constructor_enum_order(
    values: Sequence[str],
    allowed: Sequence[str],
) -> list[str]:
    rank = {item: index for index, item in enumerate(allowed)}
    return sorted(values, key=lambda item: (rank.get(item, len(rank)), item))


def provider_safe_semantic_unit(
    *,
    unit_id: str,
    ordinal: int,
    authority_class: str,
    content_kind: str,
    source_text: str,
    provider_text: str,
    transformation_flags: Sequence[str],
    exactness: str,
    source_class: str,
    source_references: Sequence[Mapping[str, Any]],
    internal_provenance: Mapping[str, Any],
    structured_data: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build a semantic unit after applying the canonical provider-text policy."""

    safe_provider_text = provider_text_safety.sanitize_provider_visible_text(
        provider_text
    )
    flags = list(transformation_flags)
    adjusted_exactness = exactness
    provenance = dict(internal_provenance)
    if safe_provider_text != provider_text:
        if "provider_safety_redacted" not in flags:
            flags.append("provider_safety_redacted")
        if adjusted_exactness in {"exact", "derived"}:
            adjusted_exactness = "mixed"
        if provenance.get("derivation_version") is None:
            provenance["derivation_version"] = "provider_safety_redaction_v0"
    return semantic_unit(
        unit_id=unit_id,
        ordinal=ordinal,
        authority_class=authority_class,
        content_kind=content_kind,
        source_text=source_text,
        provider_text=safe_provider_text,
        transformation_flags=_constructor_enum_order(
            flags,
            TRANSFORMATION_FLAGS,
        ),
        exactness=adjusted_exactness,
        source_class=source_class,
        source_references=source_references,
        internal_provenance=provenance,
        structured_data=structured_data,
    )


def _projection_structured_data(
    projection: Mapping[str, Any],
) -> list[dict[str, Any]]:
    datums: list[dict[str, Any]] = []
    for key in sorted(projection):
        value = projection[key]
        if value is None:
            datum = structured_datum(key=key, value_type="null")
        elif type(value) is bool:
            datum = structured_datum(
                key=key,
                value_type="boolean",
                boolean_value=value,
            )
        elif type(value) is int:
            datum = structured_datum(
                key=key,
                value_type="integer",
                integer_value=value,
            )
        elif isinstance(value, str):
            datum = structured_datum(
                key=key,
                value_type="text",
                text_value=value,
            )
        else:
            datum = structured_datum(
                key=key,
                value_type="text",
                text_value=contract.canonical_projection_text(value),
            )
        datums.append(datum)
    return datums


def canonical_output_policy_unit(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the only accepted policy semantic unit from the outer policy."""

    projection = contract.output_policy_projection(policy)
    projection_text = contract.canonical_projection_text(projection)
    return semantic_unit(
        unit_id="output_policy_projection_v3",
        ordinal=0,
        authority_class="output_policy_data",
        content_kind="structured_data",
        source_text=projection_text,
        provider_text=projection_text,
        transformation_flags=("structured_rendered",),
        exactness="derived",
        source_class="output_policy",
        source_references=(
            source_reference(
                source_class="output_policy",
                source_id=contract.OUTPUT_POLICY_PROJECTION_VERSION,
            ),
        ),
        internal_provenance=unit_provenance(
            owner="house_provider_neutral_request_v0",
            source_snapshot_id=contract.OUTPUT_POLICY_PROJECTION_VERSION,
            derivation_version=contract.OUTPUT_POLICY_PROJECTION_VERSION,
        ),
        structured_data=_projection_structured_data(projection),
    )


def canonical_proactive_semantic_unit(event: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the only accepted proactive semantic unit from the outer packet."""

    source_projection = contract.proactive_event_projection(event)
    provider_projection = contract.proactive_event_projection(
        event,
        provider_safe=True,
    )
    source_projection_text = contract.canonical_projection_text(
        source_projection
    )
    provider_projection_text = contract.canonical_projection_text(
        provider_projection
    )
    provider_redacted = source_projection_text != provider_projection_text
    references = [
        source_reference(
            source_class="proactive_event",
            source_id=event["event_id"],
            range_start="event_id",
            range_end="event_id",
        ),
        source_reference(
            source_class="proactive_event",
            source_id=event["dedup_key"],
            range_start="dedup_key",
            range_end="dedup_key",
        ),
    ]
    references.sort(key=contract.source_reference_sort_key)
    return semantic_unit(
        unit_id="proactive_event_projection_v4",
        ordinal=0,
        authority_class="dynamic_context",
        content_kind="future_proactive_event",
        source_text=source_projection_text,
        provider_text=provider_projection_text,
        transformation_flags=(
            ("provider_safety_redacted", "structured_rendered")
            if provider_redacted
            else ("structured_rendered",)
        ),
        exactness="mixed" if provider_redacted else "derived",
        source_class="proactive_event",
        source_references=references,
        internal_provenance=unit_provenance(
            owner="house_provider_neutral_request_v0",
            source_snapshot_id=contract.PROACTIVE_EVENT_PROJECTION_VERSION,
            derivation_version=contract.PROACTIVE_EVENT_PROJECTION_VERSION,
        ),
        structured_data=_projection_structured_data(provider_projection),
    )


def request_provenance(
    *,
    build_mode: str,
    owner: str,
    source_snapshot_id: str,
    builder_version: str,
    builder_input_ids: Sequence[str],
) -> dict[str, Any]:
    return {
        "schema_version": REQUEST_PROVENANCE_SCHEMA_VERSION,
        "build_mode": build_mode,
        "owner": owner,
        "source_snapshot_id": source_snapshot_id,
        "builder_version": builder_version,
        "builder_input_ids": list(builder_input_ids),
    }


def model_route(
    *,
    route_class: str = "local_fixture",
    model_class: str = "provider_neutral_fixture",
    tool_mode: str = "none",
) -> dict[str, Any]:
    return {
        "schema_version": MODEL_ROUTE_SCHEMA_VERSION,
        "route_class": route_class,
        "model_class": model_class,
        "tool_mode": tool_mode,
    }


def provider_capability_policy(
    *,
    required_capabilities: Sequence[str],
    optional_capabilities: Sequence[str] = (),
    forbidden_capabilities: Sequence[str] = (),
    unsupported_policy: str = "adapter_must_report",
) -> dict[str, Any]:
    return {
        "schema_version": CAPABILITY_POLICY_SCHEMA_VERSION,
        "required_capabilities": list(required_capabilities),
        "optional_capabilities": list(optional_capabilities),
        "forbidden_capabilities": list(forbidden_capabilities),
        "unsupported_policy": unsupported_policy,
    }


def output_token_policy(*, mode: str = "unspecified", requested_max_tokens: int | None = None) -> dict[str, Any]:
    return {
        "schema_version": OUTPUT_TOKEN_POLICY_SCHEMA_VERSION,
        "mode": mode,
        "requested_max_tokens": requested_max_tokens,
    }


def output_policy(
    *,
    requested_response_form: str = "natural_prose",
    visible_output: str = "prose",
    split_marker_protocol_version: str | None = None,
    memory_authorship_protocol_version: str | None = None,
    continuity_authorship_protocol_version: str | None = None,
    continuity_authorship_available: bool | None = None,
    continuity_authorship_requires_turn_capability: bool | None = None,
    requested_output_token_policy: Mapping[str, Any] | None = None,
    reasoning_policy_state: str = "unspecified",
    verbosity_policy_state: str = "unspecified",
    modalities: Sequence[str] = ("text",),
    structured_output_schema_ref: str | None = None,
    generation_policy_epoch: str = "generation_policy_0001",
    structured_output_epoch: str = "structured_output_none_0001",
) -> dict[str, Any]:
    policy = {
        "schema_version": OUTPUT_POLICY_SCHEMA_VERSION,
        "requested_response_form": requested_response_form,
        "visible_output": visible_output,
        "split_marker_protocol_version": split_marker_protocol_version,
        "memory_authorship_protocol_version": memory_authorship_protocol_version,
        "requested_output_token_policy": dict(
            requested_output_token_policy or output_token_policy()
        ),
        "reasoning_policy_state": reasoning_policy_state,
        "verbosity_policy_state": verbosity_policy_state,
        "modalities": _constructor_enum_order(modalities, MODALITIES),
        "structured_output_schema_ref": structured_output_schema_ref,
        "generation_policy_epoch": generation_policy_epoch,
        "structured_output_epoch": structured_output_epoch,
    }
    continuity_values = (
        continuity_authorship_protocol_version,
        continuity_authorship_available,
        continuity_authorship_requires_turn_capability,
    )
    if any(value is not None for value in continuity_values):
        policy.update(
            {
                "continuity_authorship_protocol_version": (
                    continuity_authorship_protocol_version
                ),
                "continuity_authorship_available": (
                    continuity_authorship_available
                ),
                "continuity_authorship_requires_turn_capability": (
                    continuity_authorship_requires_turn_capability
                ),
            }
        )
    return {
        "schema_version": policy["schema_version"],
        "policy_unit": canonical_output_policy_unit(policy),
        **{key: value for key, value in policy.items() if key != "schema_version"},
    }


def provider_operation(
    *,
    operation_id: str,
    operation_state: str,
    request_unit_id: str,
    provider_visible_resolution: str,
    acknowledgement_segments: Sequence[Mapping[str, Any]] = (),
    final_segments: Sequence[Mapping[str, Any]] = (),
    status_segments: Sequence[Mapping[str, Any]] = (),
    legacy_segments: Sequence[Mapping[str, Any]] = (),
    tool_result_references: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "schema_version": PROVIDER_OPERATION_SCHEMA_VERSION,
        "operation_id": operation_id,
        "operation_state": operation_state,
        "request_unit_id": request_unit_id,
        "acknowledgement_segments": [dict(item) for item in acknowledgement_segments],
        "final_segments": [dict(item) for item in final_segments],
        "status_segments": [dict(item) for item in status_segments],
        "legacy_segments": [dict(item) for item in legacy_segments],
        "tool_result_references": list(tool_result_references),
        "provider_visible_resolution": provider_visible_resolution,
    }


def conversation_unit(
    *,
    conversation_unit_id: str,
    sequence_index: int,
    role: str,
    completion_state: str,
    parent_turn_id: str,
    operation_id: str | None,
    segments: Sequence[Mapping[str, Any]],
    provider_operation_value: Mapping[str, Any] | None,
    source_references: Sequence[Mapping[str, Any]],
    internal_provenance: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": CONVERSATION_UNIT_SCHEMA_VERSION,
        "conversation_unit_id": conversation_unit_id,
        "sequence_index": sequence_index,
        "role": role,
        "completion_state": completion_state,
        "parent_turn_id": parent_turn_id,
        "operation_id": operation_id,
        "segments": [dict(item) for item in segments],
        "provider_operation": dict(provider_operation_value) if provider_operation_value is not None else None,
        "source_references": [dict(item) for item in source_references],
        "internal_provenance": dict(internal_provenance),
    }


def proactive_event_unit(
    *,
    event_id: str,
    event_type: str,
    detector_class: str,
    observed_at: str,
    reason_for_wake: str,
    state_snapshot: Sequence[Mapping[str, Any]],
    confidence_micros: int,
    allowed_capabilities: Sequence[str],
    quiet_constraints: Sequence[Mapping[str, Any]],
    cost_constraints: Sequence[Mapping[str, Any]],
    related_operation_ids: Sequence[str],
    dedup_key: str,
) -> dict[str, Any]:
    event = {
        "schema_version": PROACTIVE_EVENT_SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": event_type,
        "detector_class": detector_class,
        "observed_at": observed_at,
        "reason_for_wake": reason_for_wake,
        "state_snapshot": sorted(
            (dict(item) for item in state_snapshot),
            key=lambda item: str(item.get("key", "")),
        ),
        "confidence_micros": confidence_micros,
        "allowed_capabilities": _constructor_enum_order(
            allowed_capabilities,
            CAPABILITIES,
        ),
        "quiet_constraints": sorted(
            (dict(item) for item in quiet_constraints),
            key=lambda item: str(item.get("key", "")),
        ),
        "cost_constraints": sorted(
            (dict(item) for item in cost_constraints),
            key=lambda item: str(item.get("key", "")),
        ),
        "related_operation_ids": sorted(related_operation_ids),
        "dedup_key": dedup_key,
    }
    return {
        "schema_version": event["schema_version"],
        "semantic_unit": canonical_proactive_semantic_unit(event),
        **{key: value for key, value in event.items() if key != "schema_version"},
    }


def neutral_request(
    *,
    initiation_type: str,
    model_route_value: Mapping[str, Any],
    instruction_law_units: Sequence[Mapping[str, Any]],
    context_data_units: Sequence[Mapping[str, Any]],
    conversation_units: Sequence[Mapping[str, Any]],
    dynamic_context_units: Sequence[Mapping[str, Any]],
    current_input_unit: Mapping[str, Any],
    proactive_event_unit_value: Mapping[str, Any] | None,
    output_policy_value: Mapping[str, Any],
    provider_capability_policy_value: Mapping[str, Any],
    internal_provenance: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "request_model_version": REQUEST_MODEL_VERSION,
        "initiation_type": initiation_type,
        "model_route": dict(model_route_value),
        "instruction_law_units": [dict(item) for item in instruction_law_units],
        "context_data_units": [dict(item) for item in context_data_units],
        "conversation_units": [dict(item) for item in conversation_units],
        "dynamic_context_units": [dict(item) for item in dynamic_context_units],
        "current_input_unit": dict(current_input_unit),
        "proactive_event_unit": (
            dict(proactive_event_unit_value) if proactive_event_unit_value is not None else None
        ),
        "output_policy": dict(output_policy_value),
        "provider_capability_policy": dict(provider_capability_policy_value),
        "internal_provenance": dict(internal_provenance),
    }


def _validate_source_reference(value: Any, *, field: str) -> dict[str, Any]:
    item = _mapping(value, field=field)
    fields = ("schema_version", "source_class", "source_id", "range_start", "range_end")
    _exact_fields(item, fields, field=field)
    schema_version = _enum(
        item["schema_version"], (SOURCE_REFERENCE_SCHEMA_VERSION,), field=f"{field}.schema_version"
    )
    source_class = _enum(item["source_class"], SOURCE_CLASSES, field=f"{field}.source_class")
    source_id = _identifier(item["source_id"], field=f"{field}.source_id")
    range_start = _optional_identifier(item["range_start"], field=f"{field}.range_start")
    range_end = _optional_identifier(item["range_end"], field=f"{field}.range_end")
    if (range_start is None) != (range_end is None):
        raise NeutralRequestValidationError(f"{field} source range must be wholly present or null")
    return {
        "schema_version": schema_version,
        "source_class": source_class,
        "source_id": source_id,
        "range_start": range_start,
        "range_end": range_end,
    }


def _validate_unit_provenance(value: Any, *, field: str) -> dict[str, Any]:
    item = _mapping(value, field=field)
    fields = ("schema_version", "owner", "source_snapshot_id", "derivation_version", "operation_id")
    _exact_fields(item, fields, field=field)
    return {
        "schema_version": _enum(
            item["schema_version"], (UNIT_PROVENANCE_SCHEMA_VERSION,), field=f"{field}.schema_version"
        ),
        "owner": _identifier(item["owner"], field=f"{field}.owner"),
        "source_snapshot_id": _identifier(
            item["source_snapshot_id"], field=f"{field}.source_snapshot_id"
        ),
        "derivation_version": _optional_identifier(
            item["derivation_version"], field=f"{field}.derivation_version"
        ),
        "operation_id": _optional_identifier(item["operation_id"], field=f"{field}.operation_id"),
    }


def _validate_structured_datum(value: Any, *, field: str) -> dict[str, Any]:
    item = _mapping(value, field=field)
    fields = (
        "schema_version",
        "key",
        "value_type",
        "text_value",
        "integer_value",
        "boolean_value",
    )
    _exact_fields(item, fields, field=field)
    schema_version = _enum(
        item["schema_version"], (STRUCTURED_DATUM_SCHEMA_VERSION,), field=f"{field}.schema_version"
    )
    key = _string(item["key"], field=f"{field}.key", max_chars=96)
    if not _DATUM_KEY_RE.fullmatch(key):
        raise NeutralRequestValidationError(f"{field}.key must be a bounded ASCII data key")
    value_type = _enum(item["value_type"], STRUCTURED_VALUE_TYPES, field=f"{field}.value_type")
    text_value = _optional_string(item["text_value"], field=f"{field}.text_value")
    integer_value = item["integer_value"]
    boolean_value = item["boolean_value"]
    if integer_value is not None:
        integer_value = _integer(
            integer_value,
            field=f"{field}.integer_value",
            minimum=-(2**63),
            maximum=(2**63) - 1,
        )
    if boolean_value is not None:
        boolean_value = _boolean(boolean_value, field=f"{field}.boolean_value")
    active = {
        "text": text_value is not None and integer_value is None and boolean_value is None,
        "integer": text_value is None and integer_value is not None and boolean_value is None,
        "boolean": text_value is None and integer_value is None and boolean_value is not None,
        "null": text_value is None and integer_value is None and boolean_value is None,
    }
    if not active[value_type]:
        raise NeutralRequestValidationError(f"{field} typed value fields are inconsistent")
    return {
        "schema_version": schema_version,
        "key": key,
        "value_type": value_type,
        "text_value": text_value,
        "integer_value": integer_value,
        "boolean_value": boolean_value,
    }


def _validate_semantic_unit(value: Any, *, field: str) -> dict[str, Any]:
    item = _mapping(value, field=field)
    fields = (
        "schema_version",
        "unit_id",
        "ordinal",
        "authority_class",
        "content_kind",
        "source_text",
        "provider_text",
        "transformation_flags",
        "exactness",
        "source_class",
        "source_references",
        "internal_provenance",
        "structured_data",
    )
    _exact_fields(item, fields, field=field)
    schema_version = _enum(
        item["schema_version"], (SEMANTIC_UNIT_SCHEMA_VERSION,), field=f"{field}.schema_version"
    )
    unit_id = _identifier(item["unit_id"], field=f"{field}.unit_id")
    ordinal = _integer(item["ordinal"], field=f"{field}.ordinal")
    authority_class = _enum(item["authority_class"], AUTHORITY_CLASSES, field=f"{field}.authority_class")
    content_kind = _enum(item["content_kind"], CONTENT_KINDS, field=f"{field}.content_kind")
    source_text = _string(item["source_text"], field=f"{field}.source_text")
    provider_text = _string(item["provider_text"], field=f"{field}.provider_text")
    if (
        "\x00" in provider_text
        or provider_text_safety.contains_forbidden_text(provider_text)
    ):
        raise NeutralRequestValidationError(
            f"{field}.provider_text violates canonical provider-visible safety"
        )
    transformation_flags = _stable_enum_list(
        item["transformation_flags"], TRANSFORMATION_FLAGS, field=f"{field}.transformation_flags"
    )
    exactness = _enum(item["exactness"], EXACTNESS_VALUES, field=f"{field}.exactness")
    source_class = _enum(item["source_class"], SOURCE_CLASSES, field=f"{field}.source_class")
    source_references = [
        _validate_source_reference(ref, field=f"{field}.source_references[{index}]")
        for index, ref in enumerate(_list(item["source_references"], field=f"{field}.source_references"))
    ]
    if not source_references:
        raise NeutralRequestValidationError(f"{field}.source_references must not be empty")
    source_references = sorted(
        source_references,
        key=contract.source_reference_sort_key,
    )
    if len(
        {contract.source_reference_identity(ref) for ref in source_references}
    ) != len(source_references):
        raise NeutralRequestValidationError(f"{field}.source_references contains duplicates")
    if source_class not in {ref["source_class"] for ref in source_references}:
        raise NeutralRequestValidationError(
            f"{field}.source_references must include the unit source class"
        )
    internal_provenance = _validate_unit_provenance(
        item["internal_provenance"], field=f"{field}.internal_provenance"
    )
    structured_data = [
        _validate_structured_datum(datum, field=f"{field}.structured_data[{index}]")
        for index, datum in enumerate(_list(item["structured_data"], field=f"{field}.structured_data"))
    ]
    structured_data = sorted(structured_data, key=lambda datum: datum["key"])
    if len({datum["key"] for datum in structured_data}) != len(structured_data):
        raise NeutralRequestValidationError(f"{field}.structured_data contains duplicate keys")
    if content_kind in {"structured_data", "future_proactive_event"} and not structured_data:
        raise NeutralRequestValidationError(f"{field} structured content must carry structured_data")
    if content_kind not in {"structured_data", "future_proactive_event"} and structured_data:
        raise NeutralRequestValidationError(f"{field} non-structured content cannot carry structured_data")
    if authority_class == "instruction_law" or content_kind in {
        "house_derived_text",
        "structured_data",
        "future_card_checkpoint",
        "future_proactive_event",
    }:
        _nfc_lf_text(source_text, field=f"{field}.source_text")
        _nfc_lf_text(provider_text, field=f"{field}.provider_text")
    validated = {
        "schema_version": schema_version,
        "unit_id": unit_id,
        "ordinal": ordinal,
        "authority_class": authority_class,
        "content_kind": content_kind,
        "source_text": source_text,
        "provider_text": provider_text,
        "transformation_flags": transformation_flags,
        "exactness": exactness,
        "source_class": source_class,
        "source_references": source_references,
        "internal_provenance": internal_provenance,
        "structured_data": structured_data,
    }
    try:
        contract.validate_exactness_and_transformation(validated)
    except contract.NeutralContractError as exc:
        raise NeutralRequestValidationError(f"{field} {exc}") from exc
    return validated


def _ordered_units(
    value: Any,
    *,
    field: str,
    expected_authority: str | None = None,
    allow_empty: bool = True,
) -> list[dict[str, Any]]:
    units = [
        _validate_semantic_unit(item, field=f"{field}[{index}]")
        for index, item in enumerate(_list(value, field=field))
    ]
    units = sorted(units, key=lambda unit: (unit["ordinal"], unit["unit_id"]))
    if not allow_empty and not units:
        raise NeutralRequestValidationError(f"{field} must not be empty")
    if [unit["ordinal"] for unit in units] != list(range(len(units))):
        raise NeutralRequestValidationError(f"{field} ordinals must be contiguous from zero")
    if len({unit["unit_id"] for unit in units}) != len(units):
        raise NeutralRequestValidationError(f"{field} contains duplicate unit IDs")
    if expected_authority is not None and any(
        unit["authority_class"] != expected_authority for unit in units
    ):
        raise NeutralRequestValidationError(f"{field} contains the wrong authority class")
    return units


def _validate_provider_operation(value: Any, *, field: str) -> dict[str, Any]:
    item = _mapping(value, field=field)
    fields = (
        "schema_version",
        "operation_id",
        "operation_state",
        "request_unit_id",
        "acknowledgement_segments",
        "final_segments",
        "status_segments",
        "legacy_segments",
        "tool_result_references",
        "provider_visible_resolution",
    )
    _exact_fields(item, fields, field=field)
    schema_version = _enum(
        item["schema_version"], (PROVIDER_OPERATION_SCHEMA_VERSION,), field=f"{field}.schema_version"
    )
    operation_id = _identifier(item["operation_id"], field=f"{field}.operation_id")
    operation_state = _enum(item["operation_state"], OPERATION_STATES, field=f"{field}.operation_state")
    request_unit_id = _identifier(item["request_unit_id"], field=f"{field}.request_unit_id")
    acknowledgements = _ordered_units(
        item["acknowledgement_segments"],
        field=f"{field}.acknowledgement_segments",
        expected_authority="conversation_assistant",
    )
    finals = _ordered_units(
        item["final_segments"],
        field=f"{field}.final_segments",
        expected_authority="conversation_assistant",
    )
    statuses = _ordered_units(
        item["status_segments"],
        field=f"{field}.status_segments",
        expected_authority="conversation_assistant",
    )
    legacy = _ordered_units(
        item["legacy_segments"],
        field=f"{field}.legacy_segments",
        expected_authority="conversation_assistant",
    )
    for segment in [*acknowledgements, *finals, *statuses, *legacy]:
        try:
            contract.validate_unit_compatibility(
                segment,
                owner="conversation.assistant",
            )
        except contract.NeutralContractError as exc:
            raise NeutralRequestValidationError(f"{field} {exc}") from exc
    tool_result_references = sorted(
        _identifier(ref, field=f"{field}.tool_result_references[]")
        for ref in _list(item["tool_result_references"], field=f"{field}.tool_result_references")
    )
    if len(tool_result_references) != len(set(tool_result_references)):
        raise NeutralRequestValidationError(f"{field}.tool_result_references contains duplicates")
    resolution = _enum(
        item["provider_visible_resolution"],
        PROVIDER_VISIBLE_RESOLUTIONS,
        field=f"{field}.provider_visible_resolution",
    )
    validated = {
        "schema_version": schema_version,
        "operation_id": operation_id,
        "operation_state": operation_state,
        "request_unit_id": request_unit_id,
        "acknowledgement_segments": acknowledgements,
        "final_segments": finals,
        "status_segments": statuses,
        "legacy_segments": legacy,
        "tool_result_references": tool_result_references,
        "provider_visible_resolution": resolution,
    }
    try:
        contract.validate_operation_lifecycle(validated)
    except contract.NeutralContractError as exc:
        raise NeutralRequestValidationError(f"{field} {exc}") from exc
    return validated


def _validate_conversation_unit(value: Any, *, field: str) -> dict[str, Any]:
    item = _mapping(value, field=field)
    fields = (
        "schema_version",
        "conversation_unit_id",
        "sequence_index",
        "role",
        "completion_state",
        "parent_turn_id",
        "operation_id",
        "segments",
        "provider_operation",
        "source_references",
        "internal_provenance",
    )
    _exact_fields(item, fields, field=field)
    schema_version = _enum(
        item["schema_version"], (CONVERSATION_UNIT_SCHEMA_VERSION,), field=f"{field}.schema_version"
    )
    conversation_unit_id = _identifier(
        item["conversation_unit_id"], field=f"{field}.conversation_unit_id"
    )
    sequence_index = _integer(item["sequence_index"], field=f"{field}.sequence_index")
    role = _enum(item["role"], CONVERSATION_ROLES, field=f"{field}.role")
    if role == "tool_result":
        raise NeutralRequestValidationError(
            f"{field} native tool-result history is reserved for a later tool-continuity version"
        )
    completion_state = _enum(
        item["completion_state"], COMPLETION_STATES, field=f"{field}.completion_state"
    )
    parent_turn_id = _identifier(item["parent_turn_id"], field=f"{field}.parent_turn_id")
    operation_id = _optional_identifier(item["operation_id"], field=f"{field}.operation_id")
    authority_by_role = {
        "user": "conversation_user",
        "assistant": "conversation_assistant",
        "tool_result": "conversation_tool_result",
    }
    segments = _ordered_units(
        item["segments"],
        field=f"{field}.segments",
        expected_authority=authority_by_role[role],
    )
    for segment in segments:
        try:
            contract.validate_unit_compatibility(
                segment,
                owner=f"conversation.{role}",
            )
        except contract.NeutralContractError as exc:
            raise NeutralRequestValidationError(f"{field} {exc}") from exc
    operation_value = item["provider_operation"]
    operation = (
        _validate_provider_operation(operation_value, field=f"{field}.provider_operation")
        if operation_value is not None
        else None
    )
    source_references = [
        _validate_source_reference(ref, field=f"{field}.source_references[{index}]")
        for index, ref in enumerate(_list(item["source_references"], field=f"{field}.source_references"))
    ]
    if not source_references:
        raise NeutralRequestValidationError(f"{field}.source_references must not be empty")
    source_references = sorted(
        source_references,
        key=contract.source_reference_sort_key,
    )
    internal_provenance = _validate_unit_provenance(
        item["internal_provenance"], field=f"{field}.internal_provenance"
    )
    if operation is None:
        if not segments:
            raise NeutralRequestValidationError(
                f"{field} ordinary conversation requires segments"
            )
        if completion_state not in contract.ORDINARY_CONVERSATION_COMPLETION_BY_ROLE[role]:
            raise NeutralRequestValidationError(
                f"{field} ordinary {role} history must be complete"
            )
        if role == "assistant" and operation_id is not None:
            raise NeutralRequestValidationError(
                f"{field} ordinary assistant cannot carry an operation ID"
            )
        provenance_operation_id = internal_provenance["operation_id"]
        if operation_id is None and provenance_operation_id is not None:
            raise NeutralRequestValidationError(
                f"{field} ordinary conversation cannot hide operation provenance"
            )
        if operation_id is not None and (
            role != "user"
            or parent_turn_id != operation_id
            or provenance_operation_id != operation_id
        ):
            raise NeutralRequestValidationError(
                f"{field} provider-operation request identity is inconsistent"
            )
    else:
        if role != "assistant" or segments:
            raise NeutralRequestValidationError(
                f"{field} provider operation must be one assistant logical unit with resolved segments in its operation"
            )
        if operation_id != operation["operation_id"]:
            raise NeutralRequestValidationError(f"{field} operation identity is inconsistent")
        if parent_turn_id != operation_id:
            raise NeutralRequestValidationError(
                f"{field} operation parent identity is inconsistent"
            )
        if internal_provenance["operation_id"] != operation_id:
            raise NeutralRequestValidationError(
                f"{field} operation provenance identity is inconsistent"
            )
        expected_completion = {
            "accepted": "open",
            "running": "open",
            "completed": "complete",
            "failed": "failed",
            "timed_out": "timed_out",
            "cancelled": "cancelled",
            "interrupted": "interrupted",
            "legacy_unknown": "legacy_unknown",
        }[operation["operation_state"]]
        if completion_state != expected_completion:
            raise NeutralRequestValidationError(f"{field} operation completion state is inconsistent")
    validated = {
        "schema_version": schema_version,
        "conversation_unit_id": conversation_unit_id,
        "sequence_index": sequence_index,
        "role": role,
        "completion_state": completion_state,
        "parent_turn_id": parent_turn_id,
        "operation_id": operation_id,
        "segments": segments,
        "provider_operation": operation,
        "source_references": source_references,
        "internal_provenance": internal_provenance,
    }
    try:
        contract.validate_conversation_provenance(validated)
    except contract.NeutralContractError as exc:
        raise NeutralRequestValidationError(f"{field} {exc}") from exc
    return validated


def _validate_model_route(value: Any, *, field: str) -> dict[str, Any]:
    item = _mapping(value, field=field)
    fields = ("schema_version", "route_class", "model_class", "tool_mode")
    _exact_fields(item, fields, field=field)
    return {
        "schema_version": _enum(
            item["schema_version"], (MODEL_ROUTE_SCHEMA_VERSION,), field=f"{field}.schema_version"
        ),
        "route_class": _enum(item["route_class"], ROUTE_CLASSES, field=f"{field}.route_class"),
        "model_class": _enum(item["model_class"], MODEL_CLASSES, field=f"{field}.model_class"),
        "tool_mode": _enum(item["tool_mode"], TOOL_MODES, field=f"{field}.tool_mode"),
    }


def _validate_output_token_policy(value: Any, *, field: str) -> dict[str, Any]:
    item = _mapping(value, field=field)
    fields = ("schema_version", "mode", "requested_max_tokens")
    _exact_fields(item, fields, field=field)
    mode = _enum(item["mode"], OUTPUT_TOKEN_MODES, field=f"{field}.mode")
    requested_max_tokens = item["requested_max_tokens"]
    if requested_max_tokens is not None:
        requested_max_tokens = _integer(
            requested_max_tokens,
            field=f"{field}.requested_max_tokens",
            minimum=1,
            maximum=MAX_REQUESTED_OUTPUT_TOKENS,
        )
    if (mode == "unspecified") != (requested_max_tokens is None):
        raise NeutralRequestValidationError(
            f"{field} unspecified mode requires null tokens; requested modes require a positive value"
        )
    return {
        "schema_version": _enum(
            item["schema_version"], (OUTPUT_TOKEN_POLICY_SCHEMA_VERSION,), field=f"{field}.schema_version"
        ),
        "mode": mode,
        "requested_max_tokens": requested_max_tokens,
    }


def _validate_output_policy(value: Any, *, field: str) -> dict[str, Any]:
    item = _mapping(value, field=field)
    base_fields = (
        "schema_version",
        "policy_unit",
        "requested_response_form",
        "visible_output",
        "split_marker_protocol_version",
        "memory_authorship_protocol_version",
        "requested_output_token_policy",
        "reasoning_policy_state",
        "verbosity_policy_state",
        "modalities",
        "structured_output_schema_ref",
        "generation_policy_epoch",
        "structured_output_epoch",
    )
    continuity_fields = (
        "continuity_authorship_protocol_version",
        "continuity_authorship_available",
        "continuity_authorship_requires_turn_capability",
    )
    actual_fields = set(item)
    if actual_fields == set(base_fields):
        continuity_enabled = False
    elif actual_fields == set((*base_fields, *continuity_fields)):
        continuity_enabled = True
    else:
        _exact_fields(item, base_fields, field=field)
        continuity_enabled = False
    policy_unit = _validate_semantic_unit(item["policy_unit"], field=f"{field}.policy_unit")
    if policy_unit["authority_class"] != "output_policy_data":
        raise NeutralRequestValidationError(f"{field}.policy_unit has the wrong authority class")
    requested_response_form = _enum(
        item["requested_response_form"], RESPONSE_FORMS, field=f"{field}.requested_response_form"
    )
    visible_output = _enum(
        item["visible_output"], VISIBLE_OUTPUT_MODES, field=f"{field}.visible_output"
    )
    split_marker_protocol_version = _optional_identifier(
        item["split_marker_protocol_version"], field=f"{field}.split_marker_protocol_version"
    )
    memory_authorship_protocol_version = _optional_identifier(
        item["memory_authorship_protocol_version"],
        field=f"{field}.memory_authorship_protocol_version",
    )
    continuity_authorship_protocol_version = None
    continuity_authorship_available = None
    continuity_authorship_requires_turn_capability = None
    if continuity_enabled:
        continuity_authorship_protocol_version = _identifier(
            item["continuity_authorship_protocol_version"],
            field=f"{field}.continuity_authorship_protocol_version",
        )
        continuity_authorship_available = _boolean(
            item["continuity_authorship_available"],
            field=f"{field}.continuity_authorship_available",
        )
        continuity_authorship_requires_turn_capability = _boolean(
            item["continuity_authorship_requires_turn_capability"],
            field=(
                f"{field}.continuity_authorship_requires_turn_capability"
            ),
        )
        if (
            continuity_authorship_available is not True
            or continuity_authorship_requires_turn_capability is not True
        ):
            raise NeutralRequestValidationError(
                f"{field} continuity authorship requires available=true"
                " and requires_turn_capability=true"
            )
    token_policy = _validate_output_token_policy(
        item["requested_output_token_policy"], field=f"{field}.requested_output_token_policy"
    )
    reasoning_policy_state = _enum(
        item["reasoning_policy_state"], REASONING_POLICY_STATES, field=f"{field}.reasoning_policy_state"
    )
    verbosity_policy_state = _enum(
        item["verbosity_policy_state"], VERBOSITY_POLICY_STATES, field=f"{field}.verbosity_policy_state"
    )
    modalities = _stable_enum_list(item["modalities"], MODALITIES, field=f"{field}.modalities")
    if modalities != list(CURRENT_MODALITIES):
        raise NeutralRequestValidationError(
            f"{field}.modalities must be text-only in the current contract"
        )
    structured_output_schema_ref = _optional_identifier(
        item["structured_output_schema_ref"], field=f"{field}.structured_output_schema_ref"
    )
    generation_policy_epoch = _identifier(
        item["generation_policy_epoch"], field=f"{field}.generation_policy_epoch"
    )
    structured_output_epoch = _identifier(
        item["structured_output_epoch"], field=f"{field}.structured_output_epoch"
    )
    expected_visible_output = contract.RESPONSE_VISIBLE_OUTPUT_MATRIX[
        requested_response_form
    ]
    if visible_output != expected_visible_output:
        raise NeutralRequestValidationError(
            f"{field} response form and visible output are inconsistent"
        )
    wants_structured = requested_response_form in {"structured_data", "mixed"}
    if wants_structured != (structured_output_schema_ref is not None):
        raise NeutralRequestValidationError(
            f"{field} structured response form and schema reference must be present together"
        )
    if requested_response_form == "structured_data" and (
        split_marker_protocol_version is not None
        or memory_authorship_protocol_version is not None
        or continuity_authorship_protocol_version is not None
    ):
        raise NeutralRequestValidationError(
            f"{field} structured-only output reserves split and Memory-authorship protocols as null"
        )
    validated = {
        "schema_version": _enum(
            item["schema_version"], (OUTPUT_POLICY_SCHEMA_VERSION,), field=f"{field}.schema_version"
        ),
        "policy_unit": policy_unit,
        "requested_response_form": requested_response_form,
        "visible_output": visible_output,
        "split_marker_protocol_version": split_marker_protocol_version,
        "memory_authorship_protocol_version": memory_authorship_protocol_version,
        "requested_output_token_policy": token_policy,
        "reasoning_policy_state": reasoning_policy_state,
        "verbosity_policy_state": verbosity_policy_state,
        "modalities": modalities,
        "structured_output_schema_ref": structured_output_schema_ref,
        "generation_policy_epoch": generation_policy_epoch,
        "structured_output_epoch": structured_output_epoch,
    }
    if continuity_enabled:
        validated.update(
            {
                "continuity_authorship_protocol_version": (
                    continuity_authorship_protocol_version
                ),
                "continuity_authorship_available": (
                    continuity_authorship_available
                ),
                "continuity_authorship_requires_turn_capability": (
                    continuity_authorship_requires_turn_capability
                ),
            }
        )
    if policy_unit["ordinal"] != 0:
        raise NeutralRequestValidationError(
            f"{field}.policy_unit singleton ordinal must be zero"
        )
    if policy_unit != canonical_output_policy_unit(validated):
        raise NeutralRequestValidationError(
            f"{field}.policy_unit must equal the canonical outer-policy projection"
        )
    return validated


def _validate_capability_policy(value: Any, *, field: str) -> dict[str, Any]:
    item = _mapping(value, field=field)
    fields = (
        "schema_version",
        "required_capabilities",
        "optional_capabilities",
        "forbidden_capabilities",
        "unsupported_policy",
    )
    _exact_fields(item, fields, field=field)
    required = _stable_enum_list(
        item["required_capabilities"], CAPABILITIES, field=f"{field}.required_capabilities"
    )
    optional = _stable_enum_list(
        item["optional_capabilities"], CAPABILITIES, field=f"{field}.optional_capabilities"
    )
    forbidden = _stable_enum_list(
        item["forbidden_capabilities"], CAPABILITIES, field=f"{field}.forbidden_capabilities"
    )
    if (set(required) & set(optional)) or (set(required) & set(forbidden)) or (set(optional) & set(forbidden)):
        raise NeutralRequestValidationError(f"{field} capability classes must not overlap")
    return {
        "schema_version": _enum(
            item["schema_version"], (CAPABILITY_POLICY_SCHEMA_VERSION,), field=f"{field}.schema_version"
        ),
        "required_capabilities": required,
        "optional_capabilities": optional,
        "forbidden_capabilities": forbidden,
        "unsupported_policy": _enum(
            item["unsupported_policy"],
            ("adapter_must_report", "reject_request"),
            field=f"{field}.unsupported_policy",
        ),
    }


def _rfc3339_utc(value: Any, *, field: str) -> str:
    text = _string(value, field=field, max_chars=40)
    if not text.endswith("Z"):
        raise NeutralRequestValidationError(f"{field} must be UTC RFC 3339 ending in Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise NeutralRequestValidationError(f"{field} must be valid RFC 3339") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise NeutralRequestValidationError(f"{field} must be UTC")
    return text


def _validate_proactive_event(value: Any, *, field: str) -> dict[str, Any]:
    item = _mapping(value, field=field)
    fields = (
        "schema_version",
        "semantic_unit",
        "event_id",
        "event_type",
        "detector_class",
        "observed_at",
        "reason_for_wake",
        "state_snapshot",
        "confidence_micros",
        "allowed_capabilities",
        "quiet_constraints",
        "cost_constraints",
        "related_operation_ids",
        "dedup_key",
    )
    _exact_fields(item, fields, field=field)
    schema_version = _enum(
        item["schema_version"],
        (PROACTIVE_EVENT_SCHEMA_VERSION,),
        field=f"{field}.schema_version",
    )
    event_id = _identifier(item["event_id"], field=f"{field}.event_id")
    event_type = _enum(item["event_type"], EVENT_TYPES, field=f"{field}.event_type")
    detector_class = _enum(
        item["detector_class"],
        DETECTOR_CLASSES,
        field=f"{field}.detector_class",
    )
    observed_at = _rfc3339_utc(item["observed_at"], field=f"{field}.observed_at")
    reason_for_wake = _string(
        item["reason_for_wake"],
        field=f"{field}.reason_for_wake",
    )
    state_snapshot = [
        _validate_structured_datum(datum, field=f"{field}.state_snapshot[{index}]")
        for index, datum in enumerate(_list(item["state_snapshot"], field=f"{field}.state_snapshot"))
    ]
    quiet_constraints = [
        _validate_structured_datum(datum, field=f"{field}.quiet_constraints[{index}]")
        for index, datum in enumerate(_list(item["quiet_constraints"], field=f"{field}.quiet_constraints"))
    ]
    cost_constraints = [
        _validate_structured_datum(datum, field=f"{field}.cost_constraints[{index}]")
        for index, datum in enumerate(_list(item["cost_constraints"], field=f"{field}.cost_constraints"))
    ]
    for label, data in (
        ("state_snapshot", state_snapshot),
        ("quiet_constraints", quiet_constraints),
        ("cost_constraints", cost_constraints),
    ):
        data.sort(key=lambda datum: datum["key"])
        if len({datum["key"] for datum in data}) != len(data):
            raise NeutralRequestValidationError(f"{field}.{label} contains duplicate keys")
    related_operation_ids = sorted(
        _identifier(operation_id, field=f"{field}.related_operation_ids[]")
        for operation_id in _list(item["related_operation_ids"], field=f"{field}.related_operation_ids")
    )
    if len(related_operation_ids) != len(set(related_operation_ids)):
        raise NeutralRequestValidationError(f"{field}.related_operation_ids contains duplicates")
    confidence_micros = _integer(
        item["confidence_micros"],
        field=f"{field}.confidence_micros",
        maximum=1_000_000,
    )
    allowed_capabilities = _stable_enum_list(
        item["allowed_capabilities"],
        CAPABILITIES,
        field=f"{field}.allowed_capabilities",
    )
    if not set(allowed_capabilities) <= set(
        contract.PROACTIVE_ALLOWED_CAPABILITIES
    ):
        raise NeutralRequestValidationError(
            f"{field}.allowed_capabilities contains non-action capability semantics"
        )
    dedup_key = _identifier(item["dedup_key"], field=f"{field}.dedup_key")
    event_unit = _validate_semantic_unit(
        item["semantic_unit"],
        field=f"{field}.semantic_unit",
    )
    if (
        event_unit["authority_class"] != "dynamic_context"
        or event_unit["content_kind"] != "future_proactive_event"
        or event_unit["source_class"] != "proactive_event"
    ):
        raise NeutralRequestValidationError(
            f"{field}.semantic_unit has inconsistent proactive semantics"
        )
    validated = {
        "schema_version": schema_version,
        "semantic_unit": event_unit,
        "event_id": event_id,
        "event_type": event_type,
        "detector_class": detector_class,
        "observed_at": observed_at,
        "reason_for_wake": reason_for_wake,
        "state_snapshot": state_snapshot,
        "confidence_micros": confidence_micros,
        "allowed_capabilities": allowed_capabilities,
        "quiet_constraints": quiet_constraints,
        "cost_constraints": cost_constraints,
        "related_operation_ids": related_operation_ids,
        "dedup_key": dedup_key,
    }
    if event_unit["ordinal"] != 0:
        raise NeutralRequestValidationError(
            f"{field}.semantic_unit singleton ordinal must be zero"
        )
    if event_unit != canonical_proactive_semantic_unit(validated):
        raise NeutralRequestValidationError(
            f"{field}.semantic_unit must equal the canonical proactive-packet projection"
        )
    return validated


def _validate_request_provenance(value: Any, *, field: str) -> dict[str, Any]:
    item = _mapping(value, field=field)
    fields = (
        "schema_version",
        "build_mode",
        "owner",
        "source_snapshot_id",
        "builder_version",
        "builder_input_ids",
    )
    _exact_fields(item, fields, field=field)
    builder_input_ids = sorted(
        _identifier(unit_id, field=f"{field}.builder_input_ids[]")
        for unit_id in _list(item["builder_input_ids"], field=f"{field}.builder_input_ids")
    )
    if len(builder_input_ids) != len(set(builder_input_ids)):
        raise NeutralRequestValidationError(f"{field}.builder_input_ids contains duplicates")
    return {
        "schema_version": _enum(
            item["schema_version"], (REQUEST_PROVENANCE_SCHEMA_VERSION,), field=f"{field}.schema_version"
        ),
        "build_mode": _enum(item["build_mode"], BUILD_MODES, field=f"{field}.build_mode"),
        "owner": _identifier(item["owner"], field=f"{field}.owner"),
        "source_snapshot_id": _identifier(
            item["source_snapshot_id"], field=f"{field}.source_snapshot_id"
        ),
        "builder_version": _identifier(item["builder_version"], field=f"{field}.builder_version"),
        "builder_input_ids": builder_input_ids,
    }


def _all_semantic_units(request: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    yield from request["instruction_law_units"]
    yield from request["context_data_units"]
    for conversation in request["conversation_units"]:
        yield from conversation["segments"]
        operation = conversation["provider_operation"]
        if operation is not None:
            yield from operation["acknowledgement_segments"]
            yield from operation["final_segments"]
            yield from operation["status_segments"]
            yield from operation["legacy_segments"]
    yield from request["dynamic_context_units"]
    yield request["current_input_unit"]
    proactive = request["proactive_event_unit"]
    if proactive is not None:
        yield proactive["semantic_unit"]
    yield request["output_policy"]["policy_unit"]


def iter_provider_visible_units(request: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    """Yield semantic units later adapters must account for, without choosing roles."""

    validated = validate_neutral_request(request)
    yield from validated["instruction_law_units"]
    yield from validated["context_data_units"]
    for conversation in validated["conversation_units"]:
        if conversation["provider_operation"] is None:
            yield from conversation["segments"]
        else:
            yield from contract.resolved_operation_segments(
                conversation["provider_operation"]
            )
    yield from validated["dynamic_context_units"]
    proactive = validated["proactive_event_unit"]
    if proactive is not None:
        yield proactive["semantic_unit"]
    yield validated["current_input_unit"]
    yield validated["output_policy"]["policy_unit"]


def validate_neutral_request(value: Any) -> dict[str, Any]:
    """Validate and return the canonical field/list ordering for one request."""

    item = _mapping(value, field="request")
    fields = (
        "schema_version",
        "request_model_version",
        "initiation_type",
        "model_route",
        "instruction_law_units",
        "context_data_units",
        "conversation_units",
        "dynamic_context_units",
        "current_input_unit",
        "proactive_event_unit",
        "output_policy",
        "provider_capability_policy",
        "internal_provenance",
    )
    _exact_fields(item, fields, field="request")
    schema_version = _enum(
        item["schema_version"], (REQUEST_SCHEMA_VERSION,), field="request.schema_version"
    )
    request_model_version = _enum(
        item["request_model_version"], (REQUEST_MODEL_VERSION,), field="request.request_model_version"
    )
    initiation_type = _enum(
        item["initiation_type"], INITIATION_TYPES, field="request.initiation_type"
    )
    if initiation_type in RESERVED_INITIATION_TYPES:
        raise NeutralRequestValidationError(
            "request tool_follow_up initiation is reserved until a lineage packet exists"
        )
    route = _validate_model_route(item["model_route"], field="request.model_route")
    instruction_units = _ordered_units(
        item["instruction_law_units"],
        field="request.instruction_law_units",
        expected_authority="instruction_law",
        allow_empty=False,
    )
    for unit in instruction_units:
        try:
            contract.validate_unit_compatibility(unit, owner="instruction_law_units")
        except contract.NeutralContractError as exc:
            raise NeutralRequestValidationError(f"request.instruction_law_units {exc}") from exc
    context_units = _ordered_units(
        item["context_data_units"],
        field="request.context_data_units",
        expected_authority="context_data",
    )
    for unit in context_units:
        try:
            contract.validate_unit_compatibility(unit, owner="context_data_units")
        except contract.NeutralContractError as exc:
            raise NeutralRequestValidationError(f"request.context_data_units {exc}") from exc
    conversation_units = [
        _validate_conversation_unit(unit, field=f"request.conversation_units[{index}]")
        for index, unit in enumerate(_list(item["conversation_units"], field="request.conversation_units"))
    ]
    conversation_units = sorted(
        conversation_units,
        key=lambda unit: (unit["sequence_index"], unit["conversation_unit_id"]),
    )
    if [unit["sequence_index"] for unit in conversation_units] != list(range(len(conversation_units))):
        raise NeutralRequestValidationError(
            "request.conversation_units sequence indexes must be contiguous from zero"
        )
    if len({unit["conversation_unit_id"] for unit in conversation_units}) != len(conversation_units):
        raise NeutralRequestValidationError("request.conversation_units contains duplicate IDs")
    try:
        contract.validate_conversation_topology(conversation_units)
    except contract.NeutralContractError as exc:
        raise NeutralRequestValidationError(
            f"request conversation topology {exc}"
        ) from exc
    dynamic_units = _ordered_units(
        item["dynamic_context_units"],
        field="request.dynamic_context_units",
        expected_authority="dynamic_context",
    )
    for unit in dynamic_units:
        try:
            contract.validate_unit_compatibility(unit, owner="dynamic_context_units")
        except contract.NeutralContractError as exc:
            raise NeutralRequestValidationError(f"request.dynamic_context_units {exc}") from exc
    current_input = _validate_semantic_unit(
        item["current_input_unit"], field="request.current_input_unit"
    )
    if current_input["ordinal"] != 0:
        raise NeutralRequestValidationError(
            "request.current_input_unit singleton ordinal must be zero"
        )
    try:
        contract.validate_unit_compatibility(current_input, owner="current_input_unit")
    except contract.NeutralContractError as exc:
        raise NeutralRequestValidationError(f"request.current_input_unit {exc}") from exc
    proactive = (
        _validate_proactive_event(item["proactive_event_unit"], field="request.proactive_event_unit")
        if item["proactive_event_unit"] is not None
        else None
    )
    if (initiation_type == "proactive") != (proactive is not None):
        raise NeutralRequestValidationError(
            "request proactive initiation requires one packet; ordinary initiation requires null"
        )
    if proactive is not None:
        try:
            contract.validate_unit_compatibility(
                proactive["semantic_unit"],
                owner="proactive_event.semantic_unit",
            )
        except contract.NeutralContractError as exc:
            raise NeutralRequestValidationError(f"request.proactive_event_unit {exc}") from exc
    policy = _validate_output_policy(item["output_policy"], field="request.output_policy")
    try:
        contract.validate_unit_compatibility(
            policy["policy_unit"],
            owner="output_policy.policy_unit",
        )
    except contract.NeutralContractError as exc:
        raise NeutralRequestValidationError(f"request.output_policy {exc}") from exc
    capabilities = _validate_capability_policy(
        item["provider_capability_policy"], field="request.provider_capability_policy"
    )
    provenance = _validate_request_provenance(
        item["internal_provenance"], field="request.internal_provenance"
    )
    validated = {
        "schema_version": schema_version,
        "request_model_version": request_model_version,
        "initiation_type": initiation_type,
        "model_route": route,
        "instruction_law_units": instruction_units,
        "context_data_units": context_units,
        "conversation_units": conversation_units,
        "dynamic_context_units": dynamic_units,
        "current_input_unit": current_input,
        "proactive_event_unit": proactive,
        "output_policy": policy,
        "provider_capability_policy": capabilities,
        "internal_provenance": provenance,
    }
    all_units = list(_all_semantic_units(validated))
    unit_ids = [unit["unit_id"] for unit in all_units]
    if len(unit_ids) != len(set(unit_ids)):
        raise NeutralRequestValidationError("request semantic unit IDs must be globally unique")
    try:
        contract.validate_capability_consistency(validated)
    except contract.NeutralContractError as exc:
        raise NeutralRequestValidationError(f"request capability policy {exc}") from exc
    return validated


def provider_visible_texts(request: Mapping[str, Any]) -> tuple[str, ...]:
    """Return provider-visible texts in canonical semantic order."""

    return tuple(unit["provider_text"] for unit in iter_provider_visible_units(request))


def semantic_unit_ids(request: Mapping[str, Any]) -> tuple[str, ...]:
    """Return internal semantic IDs for local validation/testing only."""

    validated = validate_neutral_request(request)
    return tuple(unit["unit_id"] for unit in _all_semantic_units(validated))
