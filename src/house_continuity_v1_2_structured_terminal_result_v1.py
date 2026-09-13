"""Forced, locally consumed Generation-2 terminal result protocol.

The named function is a provider response envelope, not an executable House
tool.  This owner validates the Chat Completions response before the ordinary
provider-tool normalizer or broker can observe it.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import re
import secrets
from typing import Any, Mapping

import house_continuity_v1_2_contract_schema_v0 as contracts
from _house_continuity_v1_2_contract_primitives_v0 import (
    AUTHORED_REASON_MAX_CHARS,
)


SCHEMA_VERSION = "house_continuity_structured_terminal_result_v1"
PROTOCOL_VERSION = contracts.INTENT_PROTOCOL_VERSION
TOOL_NAME = "house_submit_turn_result_v1"
GENERATION_2 = "house_standing_root_v2_generation_2"
_CAPABILITY_RE = re.compile(r"^cwc_[A-Za-z0-9_-]{43}$")
_CAPABILITY_SEARCH_RE = re.compile(r"cwc_[A-Za-z0-9_-]{43}")
_OLD_CARRIER_MARKERS = (
    "<house-continuity-intent>",
    "</house-continuity-intent>",
)
_MAX_ARGUMENT_BYTES = 65_536
_MAX_VISIBLE_BYTES = 32_768

PROVIDER_VISIBLE_INSTRUCTION = """For this turn, return exactly one call to the required function house_submit_turn_result_v1. Your submitted continuity operation is a candidate semantic proposal; House evaluates it against the exact bound authoritative projection before granting any durable write authority. Its arguments are the complete terminal result: visible_response is your complete natural reply; capability is copied exactly from the current continuity offer; continuity_decision is apply_operation when you author exactly one reviewed continuity operation or no_semantic_delta when you explicitly author no continuity delta; semantic_operations contains exactly one operation for apply_operation and is empty for no_semantic_delta. Contextual return or navigation to a state whose accepted current projection is already authoritative is not a semantic operation: when the current request introduces no new semantic fact and does not explicitly ask to close or resolve an item, choose no_semantic_delta with an empty semantic_operations array. operation_kind determines the requested state transition. A resolve operation is lifecycle-only: target the exact offered item, emit an empty summary and empty kind_payload, and set semantic_evidence to null. Choose resolve only when the current request explicitly asks to close or resolve the exact offered item. Resolve must not rewrite the item's summary or semantic kind payload; use revise or create for a genuine semantic change. Historical or non-authoritative evidence may be preserved for audit, but it is not a current actionable target. For a revise operation, a changed summary without a semantic payload change must include semantic_evidence; never omit it. Bind it to the exact offered item ID and current content SHA-256, set comparison to contextual_restatement or genuine_revision, and provide the candidate summary SHA-256 for the exact summary string. House independently evaluates the candidate evidence and does not treat a provider-supplied digest as durable authority. Omit no-delta inference from wording alone. reason_code is optional Solen-authored meaning: preserve your wording, and do not limit it to a House taxonomy. Do not put authorship in the result. Do not emit ordinary assistant content, a prose continuity carrier, a Memory carrier, or any other function call. House consumes this result locally and shows only visible_response."""


class StructuredTerminalResultError(ValueError):
    def __init__(self, error_class: str) -> None:
        super().__init__(error_class)
        self.error_class = error_class


class StructuredTerminalSchemaCompatibilityError(ValueError):
    """Bounded local rejection for provider-incompatible strict schemas."""

    def __init__(self, error_class: str, path: str) -> None:
        super().__init__(error_class)
        self.error_class = error_class
        self.path = path


@dataclass(frozen=True)
class StructuredTerminalResult:
    visible_response: str | None
    capability: str | None
    continuity_decision: str | None
    semantic_operations: tuple[Mapping[str, Any], ...]
    private_state: str
    error_class: str | None
    raw_arguments: bytes = field(repr=False)

    @property
    def terminal_valid(self) -> bool:
        return self.private_state == "valid"


def generation2_structured_mode(request: Mapping[str, Any]) -> bool:
    metadata = request.get("metadata")
    selection = (
        metadata.get("standing_root_v2_selection")
        if isinstance(metadata, Mapping)
        and isinstance(metadata.get("standing_root_v2_selection"), Mapping)
        else {}
    )
    return selection.get("active_prefix_generation") == GENERATION_2


def _strict_object(
    properties: Mapping[str, Any],
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": deepcopy(dict(properties)),
        "required": list(properties) if required is None else list(required),
        "additionalProperties": False,
    }


def _string_array(max_items: int = 12) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string"},
        "maxItems": max_items,
    }


def _payload_variants() -> list[dict[str, Any]]:
    return [
        _strict_object({
            "topic_state": {"type": "string", "enum": ["current", "paused"]},
            "linked_item_ids": _string_array(),
        }),
        _strict_object({
            "task_state": {"type": "string", "enum": ["not_started", "in_progress", "blocked", "waiting"]},
            "linked_item_ids": _string_array(),
            "completion_evidence_refs": _string_array(),
        }),
        _strict_object({
            "question_owner": {"type": "string", "enum": ["astel", "solen", "shared", "unknown"]},
            "answer_state": {"type": "string", "enum": ["unanswered", "partially_answered", "awaiting_confirmation"]},
            "linked_item_ids": _string_array(),
        }),
        _strict_object({
            "committed_by": {"type": "string", "enum": ["astel", "solen", "shared"]},
            "commitment_state": {"type": "string", "enum": ["pending", "in_progress", "blocked"]},
            "linked_item_ids": _string_array(),
        }),
        _strict_object({
            "decision_state": {"type": "string", "enum": ["provisional", "accepted", "contested"]},
            "decision_scope": {"type": "string"},
            "linked_item_ids": _string_array(),
        }),
        _strict_object({
            "fact_state": {"type": "string", "enum": ["observed", "reported", "uncertain"]},
            "source_class": {"type": "string"},
            "linked_item_ids": _string_array(),
        }),
        _strict_object({
            "thread_state": {"type": "string", "enum": ["open", "held", "needs_return"]},
            "expressed_by": {"type": "string", "enum": ["astel", "solen", "shared", "uncertain"]},
            "linked_item_ids": _string_array(),
        }),
        _strict_object({
            "review_kind": {"type": "string", "enum": ["parallel_conflict", "scope_conflict", "contradiction", "uncertain_resolution", "possible_duplicate"]},
            "conflicting_item_ids": _string_array(),
            "conflicting_event_ids": _string_array(),
            "linked_item_ids": _string_array(),
        }),
        _strict_object({
            "task_item_id": {"type": "string"},
            "operation_ref": {"type": "string"},
            "operation_state": {"type": "string", "enum": ["completed", "failed", "cancelled"]},
            "result_summary": {"type": "string"},
            "result_ref_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        }),
    ]


def _strict_schema_error(error_class: str, path: str) -> None:
    raise StructuredTerminalSchemaCompatibilityError(error_class, path)


def _validate_strict_schema_node(
    value: Any,
    *,
    path: str,
    depth: int = 0,
) -> None:
    """Check the small strict-schema subset required by the active provider.

    This is intentionally a compatibility guard, not a general JSON Schema
    implementation.  It catches the provider rejection class where a strict
    object declares a property without declaring it required, while also
    rejecting the structural escape hatches this terminal schema does not
    use.
    """

    if depth > 64:
        _strict_schema_error("strict_schema_depth_exceeded", path)
    if not isinstance(value, Mapping):
        _strict_schema_error("strict_schema_node_invalid", path)
    if "$ref" in value:
        _strict_schema_error("strict_schema_ref_unsupported", path)

    properties = value.get("properties")
    schema_type = value.get("type")
    if properties is not None or schema_type == "object":
        if not isinstance(properties, Mapping):
            _strict_schema_error("strict_schema_properties_invalid", path)
        required = value.get("required")
        if not isinstance(required, list) or any(
            not isinstance(item, str) for item in required
        ) or len(required) != len(set(required)):
            _strict_schema_error("strict_schema_required_invalid", path)
        property_names = set(properties)
        if set(required) != property_names:
            _strict_schema_error("strict_schema_required_mismatch", path)
        if value.get("additionalProperties") is not False:
            _strict_schema_error(
                "strict_schema_additional_properties_invalid", path
            )
        for name, nested in properties.items():
            _validate_strict_schema_node(
                nested,
                path=f"{path}.properties[{name!r}]",
                depth=depth + 1,
            )

    for keyword in ("anyOf", "oneOf", "allOf"):
        variants = value.get(keyword)
        if variants is None:
            continue
        if not isinstance(variants, list) or not variants:
            _strict_schema_error(
                f"strict_schema_{keyword}_invalid", path
            )
        for index, nested in enumerate(variants):
            _validate_strict_schema_node(
                nested,
                path=f"{path}.{keyword}[{index}]",
                depth=depth + 1,
            )

    items = value.get("items")
    if items is not None:
        _validate_strict_schema_node(
            items,
            path=f"{path}.items",
            depth=depth + 1,
        )


def validate_strict_tool_definitions(definitions: Any) -> None:
    """Validate active strict tool schemas before provider dispatch."""

    if not isinstance(definitions, list):
        _strict_schema_error("strict_schema_tool_definitions_invalid", "tools")
    for index, definition in enumerate(definitions):
        if not isinstance(definition, Mapping):
            _strict_schema_error(
                "strict_schema_tool_definition_invalid", f"tools[{index}]"
            )
        function = definition.get("function")
        if not isinstance(function, Mapping) or function.get("strict") is not True:
            continue
        parameters = function.get("parameters")
        _validate_strict_schema_node(
            parameters,
            path=f"tools[{index}].function.parameters",
        )


def _operation_properties() -> dict[str, Any]:
    scope = _strict_object({
        "scope_kind": {"type": "string", "enum": ["room", "project", "global"]},
        "room_id": {"type": ["string", "null"]},
        "project_id": {"type": ["string", "null"]},
        "thread_id": {"type": ["string", "null"]},
    })
    return {
        "operation_key": {"type": "string"},
        "operation_kind": {"type": "string", "enum": list(contracts.SEMANTIC_OPERATION_KINDS)},
        "item_id": {"type": ["string", "null"]},
        "expected_revision": {"type": "integer", "minimum": 0},
        "item_kind": {"type": "string", "enum": list(contracts.ITEM_KINDS)},
        "scope": scope,
        "summary": {"type": "string", "maxLength": contracts.SUMMARY_MAX_CHARS},
        "kind_payload": {"anyOf": _payload_variants()},
        "reason_code": {
            "type": ["string", "null"],
            "maxLength": AUTHORED_REASON_MAX_CHARS,
        },
        "superseded_by_item_id": {"type": ["string", "null"]},
        "source_proposal_ids": _string_array(contracts.MAX_SOURCE_PROPOSAL_IDS),
        "semantic_evidence": {
            "anyOf": [
                _strict_object({
                    "schema_version": {
                        "type": "string",
                        "const": contracts.SEMANTIC_NOVELTY_EVIDENCE_SCHEMA_VERSION,
                    },
                    "comparison": {
                        "type": "string",
                        "enum": ["contextual_restatement", "genuine_revision"],
                    },
                    "authoritative_item_id": {"type": "string"},
                    "authoritative_content_sha256": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                    "candidate_summary_sha256": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                }),
                {"type": "null"},
            ]
        },
    }


def _resolve_operation_schema() -> dict[str, Any]:
    properties = _operation_properties()
    properties.update(
        {
            "operation_kind": {"type": "string", "enum": ["resolve"]},
            "summary": {"type": "string", "enum": [""]},
            "kind_payload": _strict_object({}),
            "semantic_evidence": {"type": "null"},
        }
    )
    return _strict_object(properties)


def provider_operation_schema() -> dict[str, Any]:
    properties = _operation_properties()
    properties["operation_kind"] = {
        "type": "string",
        "enum": [
            kind
            for kind in contracts.SEMANTIC_OPERATION_KINDS
            if kind != "resolve"
        ],
    }
    return {
        "anyOf": [
            _resolve_operation_schema(),
            _strict_object(properties),
        ]
    }


def terminal_result_parameters() -> dict[str, Any]:
    return _strict_object({
        "visible_response": {"type": "string"},
        "capability": {"type": "string", "pattern": "^cwc_[A-Za-z0-9_-]{43}$"},
        "continuity_decision": {"type": "string", "enum": ["apply_operation", "no_semantic_delta"]},
        "semantic_operations": {
            "type": "array",
            "items": provider_operation_schema(),
            "maxItems": 1,
        },
    })


def provider_tool_definition() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Submit the single terminal House turn result. This response envelope is consumed locally and is never executed as a tool.",
            "strict": True,
            "parameters": terminal_result_parameters(),
        },
    }


def forced_tool_choice() -> dict[str, Any]:
    return {"type": "function", "function": {"name": TOOL_NAME}}


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StructuredTerminalResultError("terminal_arguments_duplicate_key")
        result[key] = value
    return result


def _valid_visible(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return len(encoded) <= _MAX_VISIBLE_BYTES


def _private_invalid(
    raw: bytes,
    value: Mapping[str, Any],
    *,
    error_class: str,
) -> StructuredTerminalResult:
    visible = value.get("visible_response")
    if not _valid_visible(visible):
        raise StructuredTerminalResultError("terminal_visible_response_invalid")
    capability = value.get("capability")
    decision = value.get("continuity_decision")
    operations = value.get("semantic_operations")
    return StructuredTerminalResult(
        visible_response=visible,
        capability=capability if isinstance(capability, str) else None,
        continuity_decision=decision if isinstance(decision, str) else None,
        semantic_operations=tuple(
            deepcopy(item) for item in operations if isinstance(item, Mapping)
        ) if isinstance(operations, list) else (),
        private_state="invalid",
        error_class=error_class,
        raw_arguments=raw,
    )


def parse_chat_completions_terminal_result(
    response: Mapping[str, Any],
) -> StructuredTerminalResult:
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
        raise StructuredTerminalResultError("terminal_result_choice_cardinality_invalid")
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise StructuredTerminalResultError("terminal_result_message_missing")
    content = message.get("content")
    if content not in (None, ""):
        raise StructuredTerminalResultError("terminal_result_parallel_content_rejected")
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], Mapping):
        raise StructuredTerminalResultError("terminal_result_call_cardinality_invalid")
    call = calls[0]
    function = call.get("function")
    if call.get("type") != "function" or not isinstance(function, Mapping):
        raise StructuredTerminalResultError("terminal_result_function_shape_invalid")
    if function.get("name") != TOOL_NAME:
        raise StructuredTerminalResultError("terminal_result_wrong_function")
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        raise StructuredTerminalResultError("terminal_arguments_not_string")
    try:
        raw = arguments.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise StructuredTerminalResultError("terminal_arguments_utf8_invalid") from exc
    if not raw or len(raw) > _MAX_ARGUMENT_BYTES:
        raise StructuredTerminalResultError("terminal_arguments_size_invalid")
    try:
        value = json.loads(arguments, object_pairs_hook=_pairs_no_duplicates)
    except StructuredTerminalResultError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise StructuredTerminalResultError("terminal_arguments_malformed_json") from exc
    if not isinstance(value, dict):
        raise StructuredTerminalResultError("terminal_arguments_not_object")
    if not _valid_visible(value.get("visible_response")):
        raise StructuredTerminalResultError("terminal_visible_response_invalid")
    visible = value["visible_response"]
    if _CAPABILITY_SEARCH_RE.search(visible) is not None:
        raise StructuredTerminalResultError(
            "terminal_visible_response_private_capability_rejected"
        )
    if any(marker in visible or marker in arguments for marker in _OLD_CARRIER_MARKERS):
        raise StructuredTerminalResultError("terminal_result_old_carrier_rejected")
    required = {
        "visible_response",
        "capability",
        "continuity_decision",
        "semantic_operations",
    }
    if set(value) != required:
        return _private_invalid(raw, value, error_class="terminal_result_fields_invalid")
    capability = value["capability"]
    decision = value["continuity_decision"]
    operations = value["semantic_operations"]
    if not isinstance(capability, str) or _CAPABILITY_RE.fullmatch(capability) is None:
        return _private_invalid(raw, value, error_class="terminal_capability_shape_invalid")
    if decision not in {"apply_operation", "no_semantic_delta"}:
        return _private_invalid(raw, value, error_class="terminal_decision_invalid")
    if not isinstance(operations, list) or len(operations) > 1:
        return _private_invalid(raw, value, error_class="terminal_operation_cardinality_invalid")
    if (decision == "apply_operation" and len(operations) != 1) or (
        decision == "no_semantic_delta" and operations
    ):
        return _private_invalid(raw, value, error_class="terminal_decision_operation_mismatch")
    coverage = "semantic_operations" if decision == "apply_operation" else "no_semantic_delta"
    try:
        intent = contracts.validate_continuity_intent({
            "capability": capability,
            "schema_version": contracts.INTENT_SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "coverage_decision": coverage,
            "semantic_operations": operations,
            "scope_binding_operation": None,
        })
    except Exception as exc:
        return _private_invalid(
            raw,
            value,
            error_class=str(getattr(exc, "error_code", "terminal_operation_invalid")),
        )
    return StructuredTerminalResult(
        visible_response=visible,
        capability=capability,
        continuity_decision=decision,
        semantic_operations=tuple(deepcopy(intent["semantic_operations"])),
        private_state="valid",
        error_class=None,
        raw_arguments=raw,
    )


def intent_from_result(result: StructuredTerminalResult) -> dict[str, Any]:
    if not result.terminal_valid or result.capability is None:
        raise StructuredTerminalResultError("terminal_private_result_invalid")
    return {
        "capability": result.capability,
        "schema_version": contracts.INTENT_SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "coverage_decision": (
            "semantic_operations"
            if result.continuity_decision == "apply_operation"
            else "no_semantic_delta"
        ),
        "semantic_operations": [deepcopy(dict(item)) for item in result.semantic_operations],
        "scope_binding_operation": None,
    }


def authority_parse_result(
    result: StructuredTerminalResult,
    *,
    registry: Any,
    capability_id: str,
    expected_clear_capability: str,
    client_turn_id: str,
    room_id: str,
    provider_operation_id: str,
    protocol_version: str,
    command_context: Mapping[str, Any],
    current_snapshot_sequence: int,
    current_snapshot_sha256: str,
    current_binding_revision: int,
    provider_request_bytes_invariant: bool,
    now: str,
) -> dict[str, Any]:
    """Bind one parsed provider result to the existing private authority."""

    from house_continuity_v1_2_capability_terminal_parser_local import (
        HouseContinuityTerminalParserLocal,
        PARSE_RESULT_SCHEMA_VERSION,
    )

    response_hash = hashlib.sha256(result.raw_arguments).hexdigest()
    visible = (
        result.visible_response.encode("utf-8")
        if isinstance(result.visible_response, str)
        else b""
    )
    record = registry.read(capability_id)
    if record is None:
        raise StructuredTerminalResultError("terminal_capability_record_missing")

    def rejected(code: str, effect: str = "rejected_consumed") -> dict[str, Any]:
        current = registry.read(capability_id)
        if current is None:
            raise StructuredTerminalResultError("terminal_capability_record_missing")
        if current["state"] == "issued":
            registry.reject_consumed(
                current,
                response_sha256=response_hash,
                result_code=code,
                at=now,
            )
        else:
            registry.record_binding_or_replay_failure(
                current,
                response_sha256=response_hash,
                result_code=code,
                at=now,
            )
            effect = "replay_recorded"
        return {
            "schema_version": PARSE_RESULT_SCHEMA_VERSION,
            "response_sha256": response_hash,
            "visible_bytes": visible,
            "visible_sha256": hashlib.sha256(visible).hexdigest(),
            "stripped_private_ranges": [],
            "continuity_state": code,
            "memory_disposition": "not_supplied",
            "continuity_write_permitted": False,
            "memory_write_permitted": False,
            "any_write_permitted": False,
            "normalized_intent": None,
            "validated_command_bundle": None,
            "capability_id": capability_id,
            "capability_effect": effect,
            "memory_candidate_bytes": None,
            "second_provider_call_count": 0,
            "raw_body_persisted": False,
        }

    if result.private_state != "valid":
        return rejected(result.error_class or "terminal_private_result_invalid")
    if (
        result.capability is None
        or not secrets.compare_digest(
            result.capability, expected_clear_capability
        )
    ):
        return rejected("terminal_wrong_capability")
    record = registry.expire_if_due(record, now=now)
    binding = (
        record.get("client_turn_id") == client_turn_id
        and record.get("room_id") == room_id
        and record.get("provider_operation_id") == provider_operation_id
        and protocol_version == PROTOCOL_VERSION
        and record.get("protocol_version") == protocol_version
    )
    if not binding:
        registry.record_binding_or_replay_failure(
            record,
            response_sha256=response_hash,
            result_code="terminal_authority_binding_mismatch",
            at=now,
        )
        return rejected(
            "terminal_authority_binding_mismatch",
            effect="binding_failure_recorded",
        )
    if record["state"] != "issued":
        return rejected("terminal_capability_replayed", effect="replay_recorded")
    intent = intent_from_result(result)
    try:
        bundle = contracts.validate_intent_against_capability(
            intent,
            contracts.validate_command_context(command_context),
            record,
            current_snapshot_sequence=current_snapshot_sequence,
            current_snapshot_sha256=current_snapshot_sha256,
            current_binding_revision=current_binding_revision,
        )
        bundle["gate5_durable_operation_context"] = (
            HouseContinuityTerminalParserLocal._gate5_durable_operation_context(
                command_context,
                bundle["intent"],
            )
        )
    except Exception as exc:
        return rejected(
            str(getattr(exc, "error_code", "terminal_operation_invalid"))
        )
    if provider_request_bytes_invariant is not True:
        return rejected("provider_request_byte_mismatch")
    if (
        result.continuity_decision == "no_semantic_delta"
        or contracts.is_no_delta_canonicalization(bundle)
    ):
        registry.reject_consumed(
            record,
            response_sha256=response_hash,
            result_code="explicit_solen_no_semantic_delta",
            at=now,
        )
        continuity_write = False
        state = "explicit_solen_no_semantic_delta"
        effect = "explicit_no_delta_consumed"
    else:
        continuity_write = True
        state = "accepted_known_capability"
        effect = "pending_gate5_durable_preparation"
    return {
        "schema_version": PARSE_RESULT_SCHEMA_VERSION,
        "response_sha256": response_hash,
        "visible_bytes": visible,
        "visible_sha256": hashlib.sha256(visible).hexdigest(),
        "stripped_private_ranges": [],
        "continuity_state": state,
        "memory_disposition": "not_supplied",
        "continuity_write_permitted": continuity_write,
        "memory_write_permitted": False,
        "any_write_permitted": continuity_write,
        "normalized_intent": deepcopy(bundle["intent"]),
        "validated_command_bundle": deepcopy(bundle),
        "capability_id": capability_id,
        "capability_effect": effect,
        "memory_candidate_bytes": None,
        "second_provider_call_count": 0,
        "raw_body_persisted": False,
    }


def visible_response_from_replay_arguments(arguments: bytes) -> bytes:
    try:
        value = json.loads(arguments.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
    except Exception as exc:
        raise StructuredTerminalResultError("replay_terminal_arguments_invalid") from exc
    if not isinstance(value, dict) or not _valid_visible(value.get("visible_response")):
        raise StructuredTerminalResultError("replay_visible_response_invalid")
    return value["visible_response"].encode("utf-8")


__all__ = [
    "GENERATION_2",
    "PROTOCOL_VERSION",
    "PROVIDER_VISIBLE_INSTRUCTION",
    "SCHEMA_VERSION",
    "TOOL_NAME",
    "StructuredTerminalResult",
    "StructuredTerminalResultError",
    "forced_tool_choice",
    "authority_parse_result",
    "generation2_structured_mode",
    "intent_from_result",
    "parse_chat_completions_terminal_result",
    "provider_tool_definition",
    "terminal_result_parameters",
    "visible_response_from_replay_arguments",
]
