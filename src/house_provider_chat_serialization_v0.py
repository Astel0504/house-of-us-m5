"""Deterministic local/no-live Chat Completions endpoint serialization."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

import house_provider_chat_adapter_v0 as chat_adapter
import provider_visible_text_safety_v0 as provider_text_safety


CHAT_ENDPOINT_SERIALIZATION_VERSION = "house_chat_endpoint_serialization_v1"

_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,179}$")
_CHAT_ROLES = frozenset({"developer", "user", "assistant"})


class ChatEndpointSerializationError(ValueError):
    """Raised when a no-live Chat request cannot be represented canonically."""


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ChatEndpointSerializationError(
            "Chat wrapper cannot be encoded canonically"
        ) from exc


def _provider_visible_message_content(
    content: Any,
    *,
    message_index: int,
) -> str:
    if not isinstance(content, str) or not content:
        raise ChatEndpointSerializationError(
            f"Chat message {message_index} content must be nonempty text"
        )
    if "\x00" in content:
        raise ChatEndpointSerializationError(
            f"Chat message {message_index} content contains NUL"
        )
    try:
        content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ChatEndpointSerializationError(
            f"Chat message {message_index} content must contain Unicode scalar text"
        ) from exc
    if provider_text_safety.contains_forbidden_text(content):
        raise ChatEndpointSerializationError(
            f"Chat message {message_index} content violates provider-visible safety"
        )
    return content


def _exact_wrapper_payload(
    content: str,
    *,
    wrapper_version: str,
    fields: tuple[str, ...],
    message_index: int,
) -> dict[str, Any]:
    try:
        prefix, payload_text = content.split("\n", 1)
    except ValueError as exc:
        raise ChatEndpointSerializationError(
            f"Chat message {message_index} wrapper is malformed"
        ) from exc
    if prefix != wrapper_version:
        raise ChatEndpointSerializationError(
            f"Chat message {message_index} wrapper version is unsupported"
        )
    try:
        payload = json.loads(payload_text)
    except (TypeError, ValueError) as exc:
        raise ChatEndpointSerializationError(
            f"Chat message {message_index} wrapper JSON is invalid"
        ) from exc
    if not isinstance(payload, dict) or tuple(payload) != fields:
        raise ChatEndpointSerializationError(
            f"Chat message {message_index} wrapper fields are not exact"
        )
    if _canonical_json(payload) != payload_text:
        raise ChatEndpointSerializationError(
            f"Chat message {message_index} wrapper JSON is not canonical"
        )
    return payload


def _text_list(
    value: Any,
    *,
    field_name: str,
    allow_empty: bool,
) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ChatEndpointSerializationError(
            f"{field_name} must be an exact text array"
        )
    return list(value)


def validate_chat_projection(
    value: Any,
) -> chat_adapter.ChatProjection:
    """Validate the sealed adapter projection and exact House Chat contract."""

    try:
        projection = chat_adapter.attest_chat_projection(value)
    except chat_adapter.ChatAdapterError as exc:
        raise ChatEndpointSerializationError(str(exc)) from exc

    expected_versions = (
        (projection.projection_version, chat_adapter.CHAT_PROJECTION_VERSION),
        (projection.adapter_version, chat_adapter.CHAT_ADAPTER_VERSION),
        (
            projection.data_isolation_law_version,
            chat_adapter.DATA_ISOLATION_LAW_VERSION,
        ),
        (
            projection.developer_wrapper_version,
            chat_adapter.DEVELOPER_WRAPPER_VERSION,
        ),
        (
            projection.stable_context_wrapper_version,
            chat_adapter.STABLE_CONTEXT_WRAPPER_VERSION,
        ),
        (
            projection.current_turn_wrapper_version,
            chat_adapter.CURRENT_TURN_WRAPPER_VERSION,
        ),
        (
            projection.segment_framing_version,
            chat_adapter.SEGMENT_FRAMING_VERSION,
        ),
    )
    if any(actual != expected for actual, expected in expected_versions):
        raise ChatEndpointSerializationError(
            "Chat projection version attestation is inconsistent"
        )

    model = projection.model
    if not isinstance(model, str) or not _MODEL_RE.fullmatch(model):
        raise ChatEndpointSerializationError("Chat model must be a bounded ASCII identifier")
    if model not in set(chat_adapter.CHAT_MODEL_BY_ROUTE.values()):
        raise ChatEndpointSerializationError("Chat model is not in the reviewed local mapping")

    messages = projection.messages
    if not isinstance(messages, tuple) or len(messages) < 2:
        raise ChatEndpointSerializationError(
            "Chat projection requires developer and final current-turn messages"
        )
    for index, message in enumerate(messages):
        if type(message) is not chat_adapter.ChatMessage:
            raise ChatEndpointSerializationError(
                f"Chat message {index} must be typed adapter output"
            )
        role = message.role
        if role not in _CHAT_ROLES:
            raise ChatEndpointSerializationError(f"Chat message {index} role is unsupported")
        if message.message_kind not in chat_adapter.MESSAGE_KINDS:
            raise ChatEndpointSerializationError(
                f"Chat message {index} kind is unsupported"
            )
        _provider_visible_message_content(
            message.content,
            message_index=index,
        )

    first = messages[0]
    final = messages[-1]
    if first.role != "developer" or first.message_kind != "developer_wrapper":
        raise ChatEndpointSerializationError(
            "first Chat message must be the developer wrapper"
        )
    if first.segment_count != 0:
        raise ChatEndpointSerializationError(
            "developer wrapper cannot carry history segment metadata"
        )
    if final.role != "user" or final.message_kind != "current_turn_wrapper":
        raise ChatEndpointSerializationError(
            "final Chat message must be the current-turn user wrapper"
        )
    if final.segment_count != 0:
        raise ChatEndpointSerializationError(
            "current-turn wrapper cannot carry history segment metadata"
        )

    developer = _exact_wrapper_payload(
        first.content,
        wrapper_version=chat_adapter.DEVELOPER_WRAPPER_VERSION,
        fields=("instruction_law", "data_isolation_law", "output_policy"),
        message_index=0,
    )
    _text_list(
        developer["instruction_law"],
        field_name="developer instruction_law",
        allow_empty=False,
    )
    if developer["data_isolation_law"] != chat_adapter.DATA_ISOLATION_LAW:
        raise ChatEndpointSerializationError(
            "developer data-isolation law is not the reviewed exact value"
        )
    if not isinstance(developer["output_policy"], str) or not developer["output_policy"]:
        raise ChatEndpointSerializationError(
            "developer output_policy must be nonempty text"
        )

    history_start = 1
    stable_context_present = (
        len(messages) > 2
        and messages[1].message_kind == "stable_context_wrapper"
    )
    if stable_context_present:
        context_message = messages[1]
        if context_message.role != "user" or context_message.segment_count != 0:
            raise ChatEndpointSerializationError(
                "stable-context wrapper must be one non-history user message"
            )
        stable = _exact_wrapper_payload(
            context_message.content,
            wrapper_version=chat_adapter.STABLE_CONTEXT_WRAPPER_VERSION,
            fields=("context_data",),
            message_index=1,
        )
        _text_list(
            stable["context_data"],
            field_name="stable context_data",
            allow_empty=False,
        )
        history_start = 2

    history = messages[history_start:-1]
    if len(history) % 2:
        raise ChatEndpointSerializationError(
            "Chat history must contain complete user/assistant pairs"
        )
    for offset, message in enumerate(history):
        expected_role = "user" if offset % 2 == 0 else "assistant"
        expected_kind = f"history_{expected_role}"
        if (
            message.role != expected_role
            or message.message_kind != expected_kind
            or type(message.segment_count) is not int
            or message.segment_count < 1
        ):
            raise ChatEndpointSerializationError(
                "Chat history topology or segment metadata is invalid"
            )

    current = _exact_wrapper_payload(
        final.content,
        wrapper_version=chat_adapter.CURRENT_TURN_WRAPPER_VERSION,
        fields=("dynamic_context", "current_input"),
        message_index=len(messages) - 1,
    )
    _text_list(
        current["dynamic_context"],
        field_name="current dynamic_context",
        allow_empty=True,
    )
    if not isinstance(current["current_input"], str) or not current["current_input"]:
        raise ChatEndpointSerializationError(
            "current_input must be nonempty text"
        )

    if projection.stable_context_present is not stable_context_present:
        raise ChatEndpointSerializationError(
            "Chat projection stable-context attestation is inconsistent"
        )
    if projection.history_message_count != len(history):
        raise ChatEndpointSerializationError(
            "Chat projection history-count attestation is inconsistent"
        )
    return projection


def endpoint_request_from_chat_projection(
    projection: Any,
) -> dict[str, Any]:
    """Return the closed endpoint object from one attested adapter projection."""

    validated = validate_chat_projection(projection)
    return {
        "model": validated.model,
        "messages": [
            {"role": message.role, "content": message.content}
            for message in validated.messages
        ],
        "stream": False,
    }


def build_no_live_chat_projection(
    request: Mapping[str, Any],
) -> chat_adapter.ChatProjection:
    """Build the one typed projection accepted by activation-safe serialization."""

    try:
        return chat_adapter.build_chat_projection(request)
    except chat_adapter.ChatAdapterError as exc:
        raise ChatEndpointSerializationError(str(exc)) from exc


def build_no_live_chat_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build one activation-safe local endpoint object from a neutral request."""

    return endpoint_request_from_chat_projection(
        build_no_live_chat_projection(request)
    )


def canonical_chat_endpoint_body(projection: Any) -> bytes:
    """Serialize only an attested adapter projection to compact UTF-8 bytes."""

    endpoint_request = endpoint_request_from_chat_projection(projection)
    try:
        text = json.dumps(
            endpoint_request,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        return text.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ChatEndpointSerializationError(
            "Chat request cannot be encoded canonically"
        ) from exc


def serialize_neutral_request_to_chat_body(request: Mapping[str, Any]) -> bytes:
    """Use the one activation-safe neutral-to-projection-to-bytes path."""

    return canonical_chat_endpoint_body(
        build_no_live_chat_projection(request)
    )
