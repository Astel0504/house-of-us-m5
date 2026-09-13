"""Provider-neutral, in-memory tool envelopes and raw-free receipt contracts.

This module owns shared shapes and deterministic bindings only.  It does not
call providers or tools, persist receipts, authorize capabilities, or own MCP
sessions.  Raw arguments and results exist only in the normalized in-memory
envelopes; ``build_tool_receipt`` deliberately omits them.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "house_provider_agent_tool_contract_v0"

SUPPORTED_PROVIDER_ENDPOINTS = {
    "openai": frozenset({"chat_completions", "responses"}),
    "anthropic": frozenset({"messages"}),
    "gemini": frozenset({"generate_content"}),
}

OPERATION_STATES = frozenset({
    "accepted", "running", "waiting_tool", "waiting_provider", "completed",
    "failed", "cancelled",
})
PROVIDER_LEG_STATES = frozenset({
    "planned", "in_flight", "completed", "failed", "cancelled", "timed_out", "ambiguous",
})
TOOL_CALL_STATES = frozenset({
    "proposed", "validated", "rejected", "queued", "leased", "running",
    "succeeded", "failed", "cancelled", "timed_out", "ambiguous",
})
TOOL_RESULT_STATES = frozenset({
    "succeeded", "failed", "cancelled", "timed_out", "ambiguous",
})
ARGUMENT_PARSE_STATES = frozenset({"complete", "partial", "malformed"})

_TRANSITIONS = {
    "operation": {
        "accepted": frozenset({"running", "cancelled"}),
        "running": frozenset({"waiting_tool", "waiting_provider", "completed", "failed", "cancelled"}),
        "waiting_tool": frozenset({"running", "waiting_provider", "failed", "cancelled"}),
        "waiting_provider": frozenset({"running", "waiting_tool", "completed", "failed", "cancelled"}),
    },
    "provider_leg": {
        "planned": frozenset({"in_flight", "cancelled", "timed_out"}),
        "in_flight": frozenset({"completed", "failed", "cancelled", "timed_out", "ambiguous"}),
        "ambiguous": frozenset({"completed", "failed"}),
    },
    "tool_call": {
        "proposed": frozenset({"validated", "rejected", "cancelled"}),
        "validated": frozenset({"queued", "rejected", "cancelled"}),
        "queued": frozenset({"leased", "cancelled", "timed_out"}),
        "leased": frozenset({"running", "cancelled", "timed_out"}),
        "running": frozenset({"succeeded", "failed", "cancelled", "timed_out", "ambiguous"}),
        "ambiguous": frozenset({"succeeded", "failed"}),
    },
}

_ID_RE = re.compile(r"[a-z][a-z0-9_]*_[0-9a-f]{64}")
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_ARTIFACT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class ProviderAgentToolContractError(ValueError):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class


def _canonical_json(value: Any, field: str) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProviderAgentToolContractError(
            "invalid_json_value", f"{field} must be canonical JSON data."
        ) from exc


def canonical_sha256(value: Any) -> str:
    """Return the SHA-256 of canonical JSON without retaining serialized text."""
    return hashlib.sha256(_canonical_json(value, "value").encode("utf-8")).hexdigest()


def _json_copy(value: Any, field: str) -> Any:
    encoded = _canonical_json(value, field)
    return json.loads(encoded)


def _hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ProviderAgentToolContractError(
            "invalid_binding_hash", f"{field} must be a lowercase SHA-256 hash."
        )
    return value


def _house_id(value: Any, field: str, prefix: str) -> str:
    if not isinstance(value, str) or not value.startswith(prefix) or _ID_RE.fullmatch(value) is None:
        raise ProviderAgentToolContractError("invalid_identity", f"{field} is malformed.")
    return value


def _identity(value: Any, field: str) -> str:
    if not isinstance(value, str) or _IDENTITY_RE.fullmatch(value) is None:
        raise ProviderAgentToolContractError("invalid_identity", f"{field} is malformed.")
    return value


def _optional_identity(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _identity(value, field)


def _ordinal(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1_000_000:
        raise ProviderAgentToolContractError("invalid_ordinal", f"{field} is outside its bound.")
    return value


def _provider(provider_family: Any, provider_endpoint: Any) -> tuple[str, str]:
    if not isinstance(provider_family, str) or not isinstance(provider_endpoint, str):
        raise ProviderAgentToolContractError("unsupported_provider_endpoint", "Provider endpoint is unsupported.")
    family = provider_family.strip().lower()
    endpoint = provider_endpoint.strip().lower()
    if endpoint not in SUPPORTED_PROVIDER_ENDPOINTS.get(family, frozenset()):
        raise ProviderAgentToolContractError("unsupported_provider_endpoint", "Provider endpoint is unsupported.")
    return family, endpoint


def _resolved_schema(
    tool_identity: str,
    tool_schema_identity: Any,
    known_tool_schemas: Mapping[str, str],
) -> str:
    if not isinstance(known_tool_schemas, Mapping):
        raise ProviderAgentToolContractError(
            "invalid_schema_catalog", "Known tool schemas must be a mapping."
        )
    supplied = _identity(tool_schema_identity, "tool_schema_identity")
    expected = known_tool_schemas.get(tool_identity)
    if expected is None:
        raise ProviderAgentToolContractError(
            "unknown_tool_schema", "Tool has no resolved schema identity."
        )
    expected_identity = _identity(expected, "known_tool_schemas entry")
    if supplied != expected_identity:
        raise ProviderAgentToolContractError(
            "tool_schema_identity_mismatch", "Tool schema identity differs from the resolved schema."
        )
    return supplied


def derive_parent_operation_id(operation_basis: Mapping[str, Any]) -> str:
    """Derive one stable parent identity from caller-selected durable basis fields."""
    if not isinstance(operation_basis, Mapping) or not operation_basis:
        raise ProviderAgentToolContractError("invalid_operation_basis", "Operation basis must be a non-empty mapping.")
    digest = canonical_sha256({
        "schema_version": SCHEMA_VERSION,
        "kind": "parent_operation",
        "basis": _json_copy(dict(operation_basis), "operation_basis"),
    })
    return f"hpaop_{digest}"


def derive_provider_leg_id(parent_operation_id: str, provider_leg_ordinal: int) -> str:
    parent = _house_id(parent_operation_id, "parent_operation_id", "hpaop_")
    ordinal = _ordinal(provider_leg_ordinal, "provider_leg_ordinal")
    digest = canonical_sha256({
        "schema_version": SCHEMA_VERSION,
        "kind": "provider_leg",
        "parent_operation_id": parent,
        "provider_leg_ordinal": ordinal,
    })
    return f"hpaleg_{digest}"


def _derive_tool_call_id(provider_leg_id: str, call_index: int) -> str:
    digest = canonical_sha256({
        "schema_version": SCHEMA_VERSION,
        "kind": "tool_call",
        "provider_leg_id": provider_leg_id,
        "call_index": call_index,
    })
    return f"hpatc_{digest}"


def normalize_tool_call(
    *,
    provider_family: str,
    provider_endpoint: str,
    parent_operation_id: str,
    provider_leg_ordinal: int,
    call_index: int,
    tool_identity: str,
    tool_schema_identity: str,
    known_tool_schemas: Mapping[str, str],
    capability_decision_binding_sha256: str,
    arguments: Any,
    argument_parse_state: str = "complete",
    original_provider_tool_call_id: str | None = None,
) -> dict[str, Any]:
    """Normalize one provider call while retaining its JSON arguments/fragment in memory."""
    family, endpoint = _provider(provider_family, provider_endpoint)
    parent = _house_id(parent_operation_id, "parent_operation_id", "hpaop_")
    leg_ordinal = _ordinal(provider_leg_ordinal, "provider_leg_ordinal")
    index = _ordinal(call_index, "call_index")
    leg_id = derive_provider_leg_id(parent, leg_ordinal)
    tool_call_id = _derive_tool_call_id(leg_id, index)
    tool = _identity(tool_identity, "tool_identity")
    schema = _resolved_schema(tool, tool_schema_identity, known_tool_schemas)
    capability_binding = _hash(
        capability_decision_binding_sha256, "capability_decision_binding_sha256"
    )
    if argument_parse_state not in ARGUMENT_PARSE_STATES:
        raise ProviderAgentToolContractError(
            "invalid_argument_parse_state", "Argument parse state is unsupported."
        )
    normalized_arguments = _json_copy(arguments, "arguments")
    arguments_sha256 = canonical_sha256(normalized_arguments)
    if original_provider_tool_call_id is None:
        original_id = None
        provider_call_id = f"house_tool_call_{tool_call_id[-32:]}"
        synthesized = True
    else:
        original_id = _identity(original_provider_tool_call_id, "original_provider_tool_call_id")
        provider_call_id = original_id
        synthesized = False
    binding_basis = {
        "schema_version": SCHEMA_VERSION,
        "tool_call_id": tool_call_id,
        "provider_family": family,
        "provider_endpoint": endpoint,
        "parent_operation_id": parent,
        "provider_leg_id": leg_id,
        "provider_leg_ordinal": leg_ordinal,
        "call_index": index,
        "provider_tool_call_id": provider_call_id,
        "original_provider_tool_call_id": original_id,
        "tool_identity": tool,
        "tool_schema_identity": schema,
        "capability_decision_binding_sha256": capability_binding,
        "argument_parse_state": argument_parse_state,
        "arguments_sha256": arguments_sha256,
    }
    return {
        **binding_basis,
        "provider_tool_call_id_synthesized": synthesized,
        "tool_call_binding_sha256": canonical_sha256(binding_basis),
        "state": "proposed",
        "arguments": normalized_arguments,
        "raw_content_present": True,
    }


def _artifact_refs(values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or len(values) > 256:
        raise ProviderAgentToolContractError("invalid_artifact_refs", "Artifact references are malformed.")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or _ARTIFACT_RE.fullmatch(value) is None:
            raise ProviderAgentToolContractError("invalid_artifact_refs", "Artifact references are malformed.")
        normalized.append(value)
    if normalized != sorted(set(normalized)):
        raise ProviderAgentToolContractError("invalid_artifact_refs", "Artifact references must be unique and sorted.")
    return normalized


def normalize_tool_result(
    tool_call: Mapping[str, Any],
    *,
    state: str,
    result: Any,
    artifact_refs: Sequence[str] = (),
    error_class: str | None = None,
) -> dict[str, Any]:
    """Normalize one result while retaining its JSON payload in memory."""
    if not isinstance(tool_call, Mapping):
        raise ProviderAgentToolContractError("invalid_tool_call", "Tool call envelope is malformed.")
    family, endpoint = _provider(tool_call.get("provider_family"), tool_call.get("provider_endpoint"))
    call_identity = {
        "schema_version": SCHEMA_VERSION,
        "provider_family": family,
        "provider_endpoint": endpoint,
        "parent_operation_id": _house_id(tool_call.get("parent_operation_id"), "parent_operation_id", "hpaop_"),
        "provider_leg_id": _house_id(tool_call.get("provider_leg_id"), "provider_leg_id", "hpaleg_"),
        "provider_leg_ordinal": _ordinal(tool_call.get("provider_leg_ordinal"), "provider_leg_ordinal"),
        "tool_call_id": _house_id(tool_call.get("tool_call_id"), "tool_call_id", "hpatc_"),
        "call_index": _ordinal(tool_call.get("call_index"), "call_index"),
        "original_provider_tool_call_id": _optional_identity(
            tool_call.get("original_provider_tool_call_id"), "original_provider_tool_call_id"
        ),
        "provider_tool_call_id": _identity(tool_call.get("provider_tool_call_id"), "provider_tool_call_id"),
        "tool_identity": _identity(tool_call.get("tool_identity"), "tool_identity"),
        "tool_schema_identity": _identity(tool_call.get("tool_schema_identity"), "tool_schema_identity"),
        "capability_decision_binding_sha256": _hash(
            tool_call.get("capability_decision_binding_sha256"), "capability_decision_binding_sha256"
        ),
        "argument_parse_state": tool_call.get("argument_parse_state"),
        "arguments_sha256": _hash(tool_call.get("arguments_sha256"), "arguments_sha256"),
        "tool_call_binding_sha256": _hash(
            tool_call.get("tool_call_binding_sha256"), "tool_call_binding_sha256"
        ),
    }
    if call_identity["argument_parse_state"] not in ARGUMENT_PARSE_STATES:
        raise ProviderAgentToolContractError("invalid_argument_parse_state", "Argument parse state is unsupported.")
    if state not in TOOL_RESULT_STATES:
        raise ProviderAgentToolContractError("invalid_tool_result_state", "Tool result state is unsupported.")
    normalized_result = _json_copy(result, "result")
    result_sha256 = canonical_sha256(normalized_result)
    artifacts = _artifact_refs(artifact_refs)
    if error_class is not None:
        error = _identity(error_class, "error_class")
    else:
        error = None
    binding_basis = {
        **call_identity,
        "state": state,
        "result_sha256": result_sha256,
        "artifact_refs": artifacts,
        "error_class": error,
    }
    return {
        **binding_basis,
        "tool_result_binding_sha256": canonical_sha256(binding_basis),
        "result": normalized_result,
        "raw_content_present": True,
    }


def build_tool_receipt(tool_result: Mapping[str, Any]) -> dict[str, Any]:
    """Build the exact durable, raw-free receipt projection for one tool result."""
    if not isinstance(tool_result, Mapping):
        raise ProviderAgentToolContractError("invalid_receipt_source", "Receipt source is malformed.")
    state = tool_result.get("state")
    if state not in TOOL_RESULT_STATES:
        raise ProviderAgentToolContractError("invalid_tool_result_state", "Tool result state is unsupported.")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "provider_family": _provider(
            tool_result.get("provider_family"), tool_result.get("provider_endpoint")
        )[0],
        "provider_endpoint": _provider(
            tool_result.get("provider_family"), tool_result.get("provider_endpoint")
        )[1],
        "parent_operation_id": _house_id(tool_result.get("parent_operation_id"), "parent_operation_id", "hpaop_"),
        "provider_leg_id": _house_id(tool_result.get("provider_leg_id"), "provider_leg_id", "hpaleg_"),
        "provider_leg_ordinal": _ordinal(tool_result.get("provider_leg_ordinal"), "provider_leg_ordinal"),
        "tool_call_id": _house_id(tool_result.get("tool_call_id"), "tool_call_id", "hpatc_"),
        "call_index": _ordinal(tool_result.get("call_index"), "call_index"),
        "original_provider_tool_call_id": _optional_identity(
            tool_result.get("original_provider_tool_call_id"), "original_provider_tool_call_id"
        ),
        "provider_tool_call_id": _identity(tool_result.get("provider_tool_call_id"), "provider_tool_call_id"),
        "tool_identity": _identity(tool_result.get("tool_identity"), "tool_identity"),
        "tool_schema_identity": _identity(tool_result.get("tool_schema_identity"), "tool_schema_identity"),
        "capability_decision_binding_sha256": _hash(tool_result.get("capability_decision_binding_sha256"), "capability_decision_binding_sha256"),
        "argument_parse_state": tool_result.get("argument_parse_state"),
        "arguments_sha256": _hash(tool_result.get("arguments_sha256"), "arguments_sha256"),
        "result_sha256": _hash(tool_result.get("result_sha256"), "result_sha256"),
        "state": state,
        "artifact_refs": _artifact_refs(tool_result.get("artifact_refs", ())),
        "error_class": _optional_identity(tool_result.get("error_class"), "error_class"),
        "tool_call_binding_sha256": _hash(tool_result.get("tool_call_binding_sha256"), "tool_call_binding_sha256"),
        "tool_result_binding_sha256": _hash(tool_result.get("tool_result_binding_sha256"), "tool_result_binding_sha256"),
        "raw_content_present": False,
    }
    binding_basis = {key: value for key, value in receipt.items() if key != "raw_content_present"}
    receipt["receipt_binding_sha256"] = canonical_sha256(binding_basis)
    return receipt


def validate_state_transition(scope: str, current_state: str, next_state: str) -> str:
    """Validate an exact state step; same-state calls are idempotent replay."""
    states = {
        "operation": OPERATION_STATES,
        "provider_leg": PROVIDER_LEG_STATES,
        "tool_call": TOOL_CALL_STATES,
    }.get(scope)
    if states is None or current_state not in states or next_state not in states:
        raise ProviderAgentToolContractError("invalid_state", "State scope or value is unsupported.")
    if current_state == next_state:
        return next_state
    if next_state not in _TRANSITIONS[scope].get(current_state, frozenset()):
        raise ProviderAgentToolContractError("invalid_state_transition", "State transition is unsupported.")
    return next_state


def compare_replay_binding(
    existing: Mapping[str, Any] | None,
    candidate: Mapping[str, Any],
    *,
    identity_field: str,
    binding_field: str,
) -> str:
    """Classify new/exact replay and reject same-identity binding collisions."""
    if not isinstance(candidate, Mapping):
        raise ProviderAgentToolContractError("invalid_binding_record", "Candidate binding record is malformed.")
    candidate_identity = candidate.get(identity_field)
    candidate_binding = _hash(candidate.get(binding_field), binding_field)
    if not isinstance(candidate_identity, str) or not candidate_identity:
        raise ProviderAgentToolContractError("invalid_binding_record", "Candidate identity is absent.")
    if existing is None:
        return "new"
    if not isinstance(existing, Mapping):
        raise ProviderAgentToolContractError("invalid_binding_record", "Existing binding record is malformed.")
    if existing.get(identity_field) != candidate_identity:
        return "different_identity"
    if _hash(existing.get(binding_field), binding_field) != candidate_binding:
        raise ProviderAgentToolContractError("identity_binding_collision", "Same identity has a different binding.")
    return "exact_replay"


__all__ = [
    "ARGUMENT_PARSE_STATES", "OPERATION_STATES", "PROVIDER_LEG_STATES",
    "ProviderAgentToolContractError",
    "SCHEMA_VERSION", "SUPPORTED_PROVIDER_ENDPOINTS", "TOOL_CALL_STATES",
    "TOOL_RESULT_STATES", "build_tool_receipt", "canonical_sha256",
    "compare_replay_binding", "derive_parent_operation_id", "derive_provider_leg_id",
    "normalize_tool_call", "normalize_tool_result", "validate_state_transition",
]
