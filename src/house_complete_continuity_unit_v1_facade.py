"""Gate-2 local adapter for exact current Android continuity-unit bytes.

This module is deliberately not imported by a runtime route.  It accepts one
exact current-producer JSON array containing one unit, verifies the caller's
byte digest, and projects the unit into the accepted backend-neutral Gate-0
contract.  The source bytes remain the evidence; the normalized facade is an
in-memory validation view and is not a persistence format.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from house_continuity_v1_2_executable_contracts_v0 import (
    HouseContinuityV12ContractError,
    validate_complete_continuity_unit,
)


CURRENT_PRODUCER_CLASS = "android_talk_continuity_units_v0"
CURRENT_PRODUCER_SCHEMA_VERSION = "current"
_ANDROID_UNIT_FIELDS = {
    "unit_id",
    "unit_kind",
    "grouping_id",
    "source_start_id",
    "source_end_id",
    "source_ids",
    "rendered_source_ids",
    "exact_or_derived",
    "continuity_status",
    "complete",
    "operation_id",
    "messages",
}
_ANDROID_MESSAGE_FIELDS = {
    "message_id",
    "parent_turn_id",
    "segment_index",
    "segment_count",
    "side",
    "speaker",
    "text",
    "route_label",
    "created_at_epoch_millis",
    "complete",
    "operation_id",
    "event_kind",
    "operation_state",
    "exact_or_derived",
}
_TERMINAL_ANDROID_STATES = {"completed", "failed", "cancelled"}
_SIDE_SPEAKER = {"astel": "Astel", "solen": "Solen"}
_ANDROID_EVENT_MAP = {
    "": None,
    "assistant_acknowledgement": "acknowledgement",
    "assistant_final": "terminal_result",
    "operation_failed": "terminal_result",
    "operation_cancelled": "terminal_result",
    "operation_interrupted": "terminal_result",
}


class CompleteUnitFacadeError(ValueError):
    """Fail-closed Gate-2 adapter error with a stable reason code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _facade_unit_id(native_unit_id: str, source_sha256: str) -> str:
    seed = json.dumps(
        {
            "native_unit_id": native_unit_id,
            "producer_class": CURRENT_PRODUCER_CLASS,
            "source_payload_sha256": source_sha256,
            "versioned_namespace": "house_complete_continuity_unit_v1",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "ccu_" + sha256_bytes(seed)[:32]


def _fail(code: str) -> None:
    raise CompleteUnitFacadeError(code)


def _exact_fields(value: Any, allowed: set[str], *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != allowed:
        _fail(code)
    return value


def _nullable_android(value: Any, *, code: str) -> str | None:
    if not isinstance(value, str):
        _fail(code)
    return value or None


def _parse_one_exact_unit(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, bytes) or not payload or payload.startswith(b"\xef\xbb\xbf"):
        _fail("invalid_android_source_bytes")
    try:
        text = payload.decode("utf-8", errors="strict")
        decoded = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail("invalid_android_source_bytes")
    if not isinstance(decoded, list) or len(decoded) != 1:
        _fail("exactly_one_android_unit_required")
    return _exact_fields(
        decoded[0], _ANDROID_UNIT_FIELDS, code="unexpected_android_unit_shape"
    )


def _validate_android_anatomy(unit: dict[str, Any]) -> list[dict[str, Any]]:
    if unit["unit_kind"] not in {"visible_exchange", "provider_agent_operation"}:
        _fail("unknown_android_unit_kind")
    if unit["exact_or_derived"] != "exact" or unit["complete"] is not True:
        _fail("incomplete_or_derived_android_unit")
    messages_raw = unit["messages"]
    if not isinstance(messages_raw, list) or not messages_raw:
        _fail("missing_android_messages")
    messages = [
        _exact_fields(
            message,
            _ANDROID_MESSAGE_FIELDS,
            code="unexpected_android_message_shape",
        )
        for message in messages_raw
    ]
    source_ids = unit["source_ids"]
    rendered_ids = unit["rendered_source_ids"]
    if (
        not isinstance(source_ids, list)
        or not source_ids
        or not isinstance(rendered_ids, list)
        or not rendered_ids
        or unit["source_start_id"] != source_ids[0]
        or unit["source_end_id"] != source_ids[-1]
        or [message["message_id"] for message in messages] != rendered_ids
        or not set(rendered_ids).issubset(set(source_ids))
    ):
        _fail("android_source_order_mismatch")
    if len(source_ids) != len(set(source_ids)) or len(rendered_ids) != len(
        set(rendered_ids)
    ):
        _fail("duplicate_android_source_id")
    for message in messages:
        if message["exact_or_derived"] != "exact" or message["complete"] is not True:
            _fail("incomplete_or_derived_android_message")
        if not isinstance(message["text"], str):
            _fail("invalid_android_message_text")
        if _SIDE_SPEAKER.get(message["side"]) != message["speaker"]:
            _fail("android_side_speaker_mismatch")
    return messages


def _validate_visible_exchange(
    unit: dict[str, Any], messages: list[dict[str, Any]]
) -> None:
    if (
        len(messages) < 2
        or messages[0]["side"] != "astel"
        or any(message["side"] != "solen" for message in messages[1:])
    ):
        _fail("invalid_android_visible_participant_order")
    if unit["source_ids"] != unit["rendered_source_ids"] or unit[
        "source_ids"
    ] != [message["message_id"] for message in messages]:
        _fail("android_visible_source_order_mismatch")
    request = messages[0]
    if request["segment_index"] != 0 or request["segment_count"] != 1:
        _fail("android_visible_request_segment_invalid")
    delivery = messages[1:]
    segment_count = delivery[0]["segment_count"]
    if (
        not isinstance(segment_count, int)
        or isinstance(segment_count, bool)
        or segment_count < 1
        or segment_count > 32
        or len(delivery) != segment_count
        or any(message["segment_count"] != segment_count for message in delivery)
        or [message["segment_index"] for message in delivery]
        != list(range(segment_count))
        or len({message["parent_turn_id"] for message in delivery}) != 1
    ):
        _fail("android_visible_delivery_segments_incomplete")
    for message in messages:
        if (
            message["operation_id"] != ""
            or message["event_kind"] != ""
            or message["operation_state"] != ""
        ):
            _fail("android_visible_hidden_operation_fields")


def _validate_provider_operation(
    unit: dict[str, Any],
    messages: list[dict[str, Any]],
    operation_id: str,
) -> int:
    if (
        len(messages) < 2
        or len(messages) > 33
        or messages[0]["side"] != "astel"
        or any(message["side"] != "solen" for message in messages[1:])
    ):
        _fail("invalid_android_operation_participant_order")
    request = messages[0]
    if (
        request["operation_id"] != ""
        or request["event_kind"] != ""
        or request["operation_state"] != ""
        or request["route_label"] != "android_standing_live_send"
    ):
        _fail("invalid_android_operation_request")
    terminal = messages[1:]
    first = terminal[0]
    terminal_ids = [message["message_id"] for message in terminal]
    if (
        unit["rendered_source_ids"]
        != [request["message_id"], *terminal_ids]
        or len(unit["source_ids"]) != len(unit["rendered_source_ids"]) + 1
        or unit["source_ids"][0] != request["message_id"]
        or unit["source_ids"][2:] != terminal_ids
        or unit["source_ids"][1] in unit["rendered_source_ids"]
    ):
        _fail("android_acknowledgement_source_order_mismatch")
    if (
        first["parent_turn_id"] != operation_id
        or first["operation_id"] != operation_id
        or first["route_label"] != "android_provider_agent_operation"
        or first["segment_count"] != len(terminal)
        or first["event_kind"] not in _ANDROID_EVENT_MAP
        or _ANDROID_EVENT_MAP[first["event_kind"]] != "terminal_result"
        or first["operation_state"] != unit["continuity_status"]
    ):
        _fail("android_terminal_group_mismatch")
    for index, message in enumerate(terminal):
        if (
            message["parent_turn_id"] != first["parent_turn_id"]
            or message["operation_id"] != first["operation_id"]
            or message["route_label"] != first["route_label"]
            or message["segment_count"] != first["segment_count"]
            or message["segment_index"] != index
            or message["event_kind"] != first["event_kind"]
            or message["operation_state"] != first["operation_state"]
            or message["created_at_epoch_millis"]
            != first["created_at_epoch_millis"]
        ):
            _fail("android_terminal_sibling_mismatch")
    return len(messages) - 1


def _operation_message_projection(
    message: dict[str, Any],
    *,
    operation_id: str,
    is_last_terminal_segment: bool,
) -> dict[str, Any]:
    raw_event = message["event_kind"]
    if raw_event not in _ANDROID_EVENT_MAP:
        _fail("unknown_android_operation_event")
    mapped_event = _ANDROID_EVENT_MAP[raw_event]
    if message["side"] == "astel":
        mapped_event = "agent_message"
    raw_state = _nullable_android(
        message["operation_state"], code="invalid_android_operation_state"
    )
    if raw_state in _TERMINAL_ANDROID_STATES and not is_last_terminal_segment:
        # Android repeats the logical terminal state on every split sibling.
        # The facade records terminal finality once, on the last complete
        # sibling, while source_payload_sha256 still binds the unchanged bytes.
        mapped_state = None
    else:
        mapped_state = raw_state
    return {
        **message,
        "parent_turn_id": message["parent_turn_id"] or message["message_id"],
        "operation_id": operation_id,
        "event_kind": mapped_event,
        "operation_state": mapped_state,
    }


def adapt_current_android_unit_bytes(
    payload: bytes,
    *,
    expected_source_payload_sha256: str,
    producer_class: str = CURRENT_PRODUCER_CLASS,
    producer_schema_version: str = CURRENT_PRODUCER_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Verify exact source bytes and return a validated backend-neutral facade."""

    actual_sha = sha256_bytes(payload)
    if actual_sha != expected_source_payload_sha256:
        _fail("android_source_payload_sha256_mismatch")
    if producer_class != CURRENT_PRODUCER_CLASS:
        _fail("future_producer_not_accepted")
    if producer_schema_version != CURRENT_PRODUCER_SCHEMA_VERSION:
        _fail("future_producer_schema_not_accepted")

    unit = _parse_one_exact_unit(payload)
    messages = _validate_android_anatomy(unit)
    operation_id = _nullable_android(
        unit["operation_id"], code="invalid_android_operation_id"
    )
    if unit["unit_kind"] == "visible_exchange":
        if operation_id is not None or unit["continuity_status"] != "complete":
            _fail("invalid_android_visible_exchange")
        _validate_visible_exchange(unit, messages)
        projected_messages = [
            {
                **message,
                "parent_turn_id": message["parent_turn_id"] or message["message_id"],
                "operation_id": None,
                "event_kind": None,
                "operation_state": None,
            }
            for message in messages
        ]
    else:
        if operation_id is None or unit["continuity_status"] not in {
            "completed",
            "failed",
            "cancelled",
        }:
            _fail("android_operation_not_terminal_complete")
        last_terminal_index = _validate_provider_operation(
            unit, messages, operation_id
        )
        terminal_indexes = [
            index
            for index, message in enumerate(messages)
            if message["operation_state"] in _TERMINAL_ANDROID_STATES
        ]
        if (
            not terminal_indexes
            or terminal_indexes[-1] != len(messages) - 1
            or terminal_indexes[-1] != last_terminal_index
        ):
            _fail("android_operation_finality_missing")
        projected_messages = [
            _operation_message_projection(
                message,
                operation_id=operation_id,
                is_last_terminal_segment=index == terminal_indexes[-1],
            )
            for index, message in enumerate(messages)
        ]

    candidate = {
        "schema_version": "house_complete_continuity_unit_v1",
        "producer_class": producer_class,
        "producer_schema_version": producer_schema_version,
        "unit_id": _facade_unit_id(unit["unit_id"], actual_sha),
        "unit_kind": unit["unit_kind"],
        "grouping_id": unit["grouping_id"],
        "source_start_id": unit["source_start_id"],
        "source_end_id": unit["source_end_id"],
        "source_ids": unit["source_ids"],
        "rendered_source_ids": unit["rendered_source_ids"],
        "exact_or_derived": "exact",
        "continuity_status": "complete",
        "complete": True,
        "operation_id": operation_id,
        "messages": projected_messages,
        "source_payload_sha256": actual_sha,
        "transport_bytes_unchanged": True,
        "persisted_by_working_set": False,
        "memory_vault_truth": False,
        "self_state": False,
        "action_permission": False,
    }
    try:
        return validate_complete_continuity_unit(candidate)
    except HouseContinuityV12ContractError as exc:
        raise CompleteUnitFacadeError(f"gate0_facade_rejected:{exc}") from exc


def build_visible_exchange_from_android_sync(
    payload: Mapping[str, Any], *, client_turn_id: str
) -> tuple[bytes, dict[str, Any]]:
    """Derive the one complete visible unit from the canonical Android sync payload."""
    if not isinstance(payload, Mapping) or not isinstance(client_turn_id, str):
        _fail("android_sync_unit_input_invalid")
    messages = payload.get("messages")
    if not isinstance(messages, list):
        _fail("android_sync_messages_missing")
    start = next(
        (
            index
            for index, value in enumerate(messages)
            if isinstance(value, Mapping)
            and value.get("message_id") == client_turn_id
            and value.get("from_astel") is True
        ),
        None,
    )
    if start is None:
        _fail("android_sync_client_turn_missing")
    selected = [messages[start]]
    for value in messages[start + 1 :]:
        if not isinstance(value, Mapping):
            _fail("android_sync_message_invalid")
        if value.get("from_astel") is True:
            break
        selected.append(value)
    if len(selected) < 2:
        _fail("android_sync_solen_delivery_missing")
    source_ids = [str(value.get("message_id") or "") for value in selected]
    if not all(source_ids):
        _fail("android_sync_source_id_missing")
    parent = str(selected[1].get("parent_turn_id") or source_ids[1])
    projected = []
    for index, value in enumerate(selected):
        astel = index == 0
        projected.append(
            {
                "message_id": source_ids[index],
                "parent_turn_id": str(value.get("parent_turn_id") or ""),
                "segment_index": int(value.get("segment_index") or 0),
                "segment_count": int(value.get("segment_count") or 1),
                "side": "astel" if astel else "solen",
                "speaker": str(
                    value.get("speaker") or ("Astel" if astel else "Solen")
                )[:96],
                "text": str(value.get("text") or ""),
                "route_label": str(value.get("route_label") or "")[:96],
                "created_at_epoch_millis": int(
                    value.get("created_at_epoch_millis") or 0
                ),
                "complete": value.get("complete", True) is True,
                "operation_id": "",
                "event_kind": "",
                "operation_state": "",
                "exact_or_derived": "exact",
            }
        )
    unit = {
        "unit_id": "continuity_unit_" + client_turn_id,
        "unit_kind": "visible_exchange",
        "grouping_id": parent,
        "source_start_id": source_ids[0],
        "source_end_id": source_ids[-1],
        "source_ids": source_ids,
        "rendered_source_ids": source_ids,
        "exact_or_derived": "exact",
        "continuity_status": "complete",
        "complete": True,
        "operation_id": "",
        "messages": projected,
    }
    payload_bytes = json.dumps(
        [unit],
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    facade = adapt_current_android_unit_bytes(
        payload_bytes,
        expected_source_payload_sha256=sha256_bytes(payload_bytes),
    )
    return payload_bytes, facade


def exact_unit_binding(facade: dict[str, Any]) -> dict[str, Any]:
    """Return the bounded raw-free identity used by later coverage/capability gates."""

    normalized = validate_complete_continuity_unit(facade)
    return {
        "schema_version": "house_complete_continuity_unit_binding_v1",
        "unit_id": normalized["unit_id"],
        "unit_kind": normalized["unit_kind"],
        "producer_class": normalized["producer_class"],
        "source_payload_sha256": normalized["source_payload_sha256"],
        "source_start_id": normalized["source_start_id"],
        "source_end_id": normalized["source_end_id"],
        "operation_id": normalized["operation_id"],
        "complete": True,
        "raw_body_included": False,
    }


__all__ = [
    "CURRENT_PRODUCER_CLASS",
    "CURRENT_PRODUCER_SCHEMA_VERSION",
    "CompleteUnitFacadeError",
    "adapt_current_android_unit_bytes",
    "build_visible_exchange_from_android_sync",
    "exact_unit_binding",
    "sha256_bytes",
]
