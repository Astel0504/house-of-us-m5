"""Provider response normalization for the House provider-agent loop.

The loop shape follows the model -> tools -> model lifecycle demonstrated by
AionsHome (MIT, commit 6cf08792c5c8858f740a81f5cd097e9cbcfa6532), while the
provider formats and validation here are House-original.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from house_provider_agent_tool_contract_v0 import (
    ProviderAgentToolContractError,
    derive_provider_leg_id,
    normalize_tool_call,
)


class ProviderToolNormalizationError(ValueError):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProviderToolNormalizationError("malformed_provider_response", f"{field} is malformed.")
    return value


def _sequence(value: Any, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ProviderToolNormalizationError("malformed_provider_response", f"{field} is malformed.")
    return value


def _arguments(value: Any) -> tuple[Any, str]:
    if not isinstance(value, str):
        return value, "complete"
    try:
        return json.loads(value), "complete"
    except json.JSONDecodeError as exc:
        stripped = value.strip()
        partial = bool(stripped) and stripped[:1] in "[{" and (
            exc.pos >= max(0, len(value) - 1)
            or stripped.count("{") > stripped.count("}")
            or stripped.count("[") > stripped.count("]")
        )
        return value, "partial" if partial else "malformed"


def _call(
    *,
    provider_family: str,
    provider_endpoint: str,
    parent_operation_id: str,
    provider_leg_ordinal: int,
    call_index: int,
    name: Any,
    arguments: Any,
    original_id: Any,
    known_tool_schemas: Mapping[str, str],
    capability_decision_bindings: Mapping[str, str],
    tool_identity_by_provider_name: Mapping[str, str] | None,
) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        raise ProviderToolNormalizationError("dangling_tool_call", "Provider tool call has no tool name.")
    provider_tool_name = name.strip()
    if tool_identity_by_provider_name is None:
        tool_identity = provider_tool_name
    else:
        tool_identity = tool_identity_by_provider_name.get(provider_tool_name, "")
    if not tool_identity or tool_identity not in capability_decision_bindings:
        raise ProviderToolNormalizationError(
            "unknown_tool_or_capability", "Provider requested a tool without a capability decision."
        )
    parsed, parse_state = _arguments(arguments)
    provider_id = original_id if isinstance(original_id, str) and original_id.strip() else None
    try:
        return normalize_tool_call(
            provider_family=provider_family,
            provider_endpoint=provider_endpoint,
            parent_operation_id=parent_operation_id,
            provider_leg_ordinal=provider_leg_ordinal,
            call_index=call_index,
            tool_identity=tool_identity,
            tool_schema_identity=known_tool_schemas.get(tool_identity, "unknown"),
            known_tool_schemas=known_tool_schemas,
            capability_decision_binding_sha256=capability_decision_bindings[tool_identity],
            arguments=parsed,
            argument_parse_state=parse_state,
            original_provider_tool_call_id=provider_id,
        )
    except ProviderAgentToolContractError as exc:
        raise ProviderToolNormalizationError(exc.error_class, str(exc)) from exc


def _openai_chat(response: Mapping[str, Any]) -> tuple[str, list[tuple[Any, Any, Any]]]:
    choices = _sequence(response.get("choices"), "choices")
    if not choices:
        raise ProviderToolNormalizationError("malformed_provider_response", "Provider response has no choice.")
    message = _mapping(_mapping(choices[0], "choice").get("message"), "message")
    text = message.get("content") or ""
    calls: list[tuple[Any, Any, Any]] = []
    for item in _sequence(message.get("tool_calls", ()), "tool_calls"):
        call = _mapping(item, "tool_call")
        function = _mapping(call.get("function"), "function")
        calls.append((function.get("name"), function.get("arguments", {}), call.get("id")))
    return str(text), calls


def _openai_responses(response: Mapping[str, Any]) -> tuple[str, list[tuple[Any, Any, Any]]]:
    texts: list[str] = []
    calls: list[tuple[Any, Any, Any]] = []
    for item_value in _sequence(response.get("output", ()), "output"):
        item = _mapping(item_value, "output item")
        if item.get("type") == "function_call":
            calls.append((item.get("name"), item.get("arguments", {}), item.get("call_id") or item.get("id")))
        elif item.get("type") == "message":
            for part_value in _sequence(item.get("content", ()), "message content"):
                part = _mapping(part_value, "message content item")
                if part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                    texts.append(part["text"])
    if not texts and isinstance(response.get("output_text"), str):
        texts.append(response["output_text"])
    return "".join(texts), calls


def _anthropic(response: Mapping[str, Any]) -> tuple[str, list[tuple[Any, Any, Any]]]:
    texts: list[str] = []
    calls: list[tuple[Any, Any, Any]] = []
    for block_value in _sequence(response.get("content", ()), "content"):
        block = _mapping(block_value, "content block")
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            texts.append(block["text"])
        elif block.get("type") == "tool_use":
            calls.append((block.get("name"), block.get("input", {}), block.get("id")))
    return "".join(texts), calls


def _gemini(response: Mapping[str, Any]) -> tuple[str, list[tuple[Any, Any, Any]]]:
    candidates = _sequence(response.get("candidates"), "candidates")
    if not candidates:
        raise ProviderToolNormalizationError("malformed_provider_response", "Provider response has no candidate.")
    content = _mapping(_mapping(candidates[0], "candidate").get("content"), "content")
    texts: list[str] = []
    calls: list[tuple[Any, Any, Any]] = []
    for part_value in _sequence(content.get("parts", ()), "parts"):
        part = _mapping(part_value, "part")
        if isinstance(part.get("text"), str):
            texts.append(part["text"])
        if "functionCall" in part:
            function = _mapping(part["functionCall"], "functionCall")
            calls.append((function.get("name"), function.get("args", {}), function.get("id")))
    return "".join(texts), calls


def normalize_provider_response(
    *,
    provider_family: str,
    provider_endpoint: str,
    response: Mapping[str, Any],
    parent_operation_id: str,
    provider_leg_ordinal: int,
    known_tool_schemas: Mapping[str, str],
    capability_decision_bindings: Mapping[str, str],
    tool_identity_by_provider_name: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    body = _mapping(response, "response")
    key = (provider_family.strip().lower(), provider_endpoint.strip().lower())
    parser = {
        ("openai", "chat_completions"): _openai_chat,
        ("openai", "responses"): _openai_responses,
        ("anthropic", "messages"): _anthropic,
        ("gemini", "generate_content"): _gemini,
    }.get(key)
    if parser is None:
        raise ProviderToolNormalizationError("unsupported_provider_endpoint", "Provider endpoint is unsupported.")
    text, raw_calls = parser(body)
    calls = [
        _call(
            provider_family=key[0], provider_endpoint=key[1],
            parent_operation_id=parent_operation_id, provider_leg_ordinal=provider_leg_ordinal,
            call_index=index, name=name, arguments=arguments, original_id=original_id,
            known_tool_schemas=known_tool_schemas,
            capability_decision_bindings=capability_decision_bindings,
            tool_identity_by_provider_name=tool_identity_by_provider_name,
        )
        for index, (name, arguments, original_id) in enumerate(raw_calls)
    ]
    return {
        "provider_family": key[0],
        "provider_endpoint": key[1],
        "parent_operation_id": parent_operation_id,
        "provider_leg_id": derive_provider_leg_id(parent_operation_id, provider_leg_ordinal),
        "provider_leg_ordinal": provider_leg_ordinal,
        "text": text,
        "tool_calls": calls,
    }


def serialize_tool_results(
    provider_family: str,
    provider_endpoint: str,
    tool_results: Sequence[Mapping[str, Any]],
    provider_name_by_tool_identity: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    key = (provider_family.strip().lower(), provider_endpoint.strip().lower())
    if key not in {
        ("openai", "chat_completions"), ("openai", "responses"),
        ("anthropic", "messages"), ("gemini", "generate_content"),
    }:
        raise ProviderToolNormalizationError("unsupported_provider_endpoint", "Provider endpoint is unsupported.")
    seen: set[str] = set()
    ordered = list(tool_results)
    for result in ordered:
        if not isinstance(result, Mapping) or not isinstance(result.get("provider_tool_call_id"), str):
            raise ProviderToolNormalizationError("dangling_tool_result", "Tool result is not bound to a provider call.")
        call_id = result["provider_tool_call_id"]
        if call_id in seen:
            raise ProviderToolNormalizationError("duplicate_tool_result", "Tool call has more than one result.")
        seen.add(call_id)

    def payload(result: Mapping[str, Any]) -> str:
        return json.dumps(result.get("result"), ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    if key == ("openai", "chat_completions"):
        return [{"role": "tool", "tool_call_id": r["provider_tool_call_id"], "content": payload(r)} for r in ordered]
    if key == ("openai", "responses"):
        return [{"type": "function_call_output", "call_id": r["provider_tool_call_id"], "output": payload(r)} for r in ordered]
    if key == ("anthropic", "messages"):
        return [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": r["provider_tool_call_id"],
             "content": payload(r), "is_error": r.get("state") != "succeeded"}
            for r in ordered
        ]}]
    def provider_name(result: Mapping[str, Any]) -> Any:
        identity = result.get("tool_identity")
        if provider_name_by_tool_identity is None:
            return identity
        return provider_name_by_tool_identity.get(str(identity), identity)

    return [{"role": "user", "parts": [
        {"functionResponse": {"name": provider_name(r), "response": {"result": r.get("result")}}}
        for r in ordered
    ]}]


__all__ = [
    "ProviderToolNormalizationError", "normalize_provider_response", "serialize_tool_results",
]
