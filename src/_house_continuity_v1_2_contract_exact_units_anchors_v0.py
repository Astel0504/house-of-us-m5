"""Exact-anchor and complete-continuity-unit contracts for Continuity V1.2."""

from __future__ import annotations

from _house_continuity_v1_2_contract_primitives_v0 import *

EXACT_ANCHOR_SCHEMA_VERSION = "house_continuity_exact_anchor_ref_v1"

COMPLETE_UNIT_SCHEMA_VERSION = "house_complete_continuity_unit_v1"

def validate_exact_anchor_ref(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "anchor_id",
            "source_class",
            "source_ref",
            "room_id",
            "turn_id",
            "operation_id",
            "message_order_start",
            "message_order_end",
            "content_sha256",
            "exact_body_stored",
        ),
        path="exact_anchor_ref",
    )
    if raw["schema_version"] != EXACT_ANCHOR_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported exact anchor.")
    if raw["exact_body_stored"] is not False:
        _error("raw_body_forbidden", "Anchor is reference-only.")
    start = _integer(
        raw["message_order_start"], name="message_order_start", minimum=0
    )
    end = _integer(
        raw["message_order_end"], name="message_order_end", minimum=0
    )
    if end < start:
        _error("invalid_source_boundary", "Anchor boundary regresses.")
    return {
        "schema_version": EXACT_ANCHOR_SCHEMA_VERSION,
        "anchor_id": _id(
            raw["anchor_id"], name="anchor_id", kind="anchor_id"
        ),
        "source_class": _code(
            raw["source_class"],
            name="source_class",
            allowed=(
                "complete_continuity_unit",
                "android_complete_unit",
                "room_turn",
                "provider_operation",
                "tool_receipt",
                "chat_history_ref",
                "source_attachment_ref",
                "vault_exact_ref",
            ),
        ),
        "source_ref": _id(raw["source_ref"], name="source_ref"),
        "room_id": _id(raw["room_id"], name="room_id", kind="room_id"),
        "turn_id": _id(raw["turn_id"], name="turn_id"),
        "operation_id": (
            None
            if raw["operation_id"] is None
            else _id(raw["operation_id"], name="operation_id")
        ),
        "message_order_start": start,
        "message_order_end": end,
        "content_sha256": _hash(
            raw["content_sha256"], name="content_sha256"
        ),
        "exact_body_stored": False,
    }

def _complete_unit_message(value: Any, *, index: int) -> dict[str, Any]:
    raw = _exact(
        value,
        (
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
        ),
        path=f"complete_continuity_unit.messages[{index}]",
    )
    segment_index = _integer(
        raw["segment_index"], name="segment_index", minimum=0
    )
    segment_count = _integer(
        raw["segment_count"], name="segment_count", minimum=1, maximum=32
    )
    if segment_index >= segment_count:
        _error("invalid_message_segment", "Segment index exceeds count.")
    if raw["complete"] is not True or raw["exact_or_derived"] != "exact":
        _error("incomplete_or_derived_message", "Messages must be complete exact units.")
    operation_state = (
        None
        if raw["operation_state"] is None
        else _code(
            raw["operation_state"],
            name="operation_state",
            allowed=(
                "acknowledged",
                "running",
                "completed",
                "failed",
                "cancelled",
            ),
        )
    )
    return {
        "message_id": _id(raw["message_id"], name="message_id"),
        "parent_turn_id": _id(
            raw["parent_turn_id"], name="parent_turn_id"
        ),
        "segment_index": segment_index,
        "segment_count": segment_count,
        "side": _code(
            raw["side"], name="side", allowed=("astel", "solen", "tool")
        ),
        "speaker": _string(raw["speaker"], name="speaker", maximum=80),
        "text": _normalize_unicode(raw["text"], name="text"),
        "route_label": _string(
            raw["route_label"], name="route_label", maximum=160
        ),
        "created_at_epoch_millis": _integer(
            raw["created_at_epoch_millis"],
            name="created_at_epoch_millis",
            minimum=0,
        ),
        "complete": True,
        "operation_id": (
            None
            if raw["operation_id"] is None
            else _id(raw["operation_id"], name="operation_id")
        ),
        "event_kind": (
            None
            if raw["event_kind"] is None
            else _code(
                raw["event_kind"],
                name="event_kind",
                allowed=(
                    "acknowledgement",
                    "agent_message",
                    "tool_result",
                    "terminal_result",
                ),
            )
        ),
        "operation_state": operation_state,
        "exact_or_derived": "exact",
    }

def validate_complete_continuity_unit(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "producer_class",
            "producer_schema_version",
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
            "source_payload_sha256",
            "transport_bytes_unchanged",
            "persisted_by_working_set",
            "memory_vault_truth",
            "self_state",
            "action_permission",
        ),
        path="complete_continuity_unit",
    )
    if raw["schema_version"] != COMPLETE_UNIT_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported complete-unit facade.")
    if raw["producer_class"] != "android_talk_continuity_units_v0":
        _error("invalid_complete_unit_producer", "Android is current producer.")
    if raw["producer_schema_version"] != "current":
        _error("invalid_complete_unit_producer", "Future producer needs a gate.")
    unit_kind = _code(
        raw["unit_kind"],
        name="unit_kind",
        allowed=("visible_exchange", "provider_agent_operation"),
    )
    if (
        raw["exact_or_derived"] != "exact"
        or raw["continuity_status"] != "complete"
        or raw["complete"] is not True
        or raw["transport_bytes_unchanged"] is not True
    ):
        _error(
            "invalid_complete_unit_authority",
            "Facade requires complete exact byte-preserved units.",
        )
    if not isinstance(raw["messages"], list) or not raw["messages"]:
        _error("complete_unit_messages_required", "Complete unit requires messages.")
    if len(raw["messages"]) > 64:
        _error("complete_unit_messages_too_many", "Message cap exceeded.")
    messages = [
        _complete_unit_message(message, index=index)
        for index, message in enumerate(raw["messages"])
    ]
    message_ids = [message["message_id"] for message in messages]
    if len(message_ids) != len(set(message_ids)):
        _error("duplicate_complete_unit_message", "Message IDs must be unique.")
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for message in messages:
        segment_group = (
            message["parent_turn_id"],
            message["side"],
            message["speaker"],
            message["route_label"],
            message["created_at_epoch_millis"],
            message["operation_id"],
            message["event_kind"],
        )
        groups.setdefault(segment_group, []).append(message)
    for siblings in groups.values():
        declared = {message["segment_count"] for message in siblings}
        indexes = [message["segment_index"] for message in siblings]
        if (
            len(declared) != 1
            or indexes != list(range(next(iter(declared))))
        ):
            _error(
                "missing_split_sibling",
                "Split messages require exact contiguous sibling order.",
            )
    operation_id = (
        None
        if raw["operation_id"] is None
        else _id(raw["operation_id"], name="operation_id")
    )
    if unit_kind == "visible_exchange":
        if operation_id is not None or any(
            message["operation_id"] is not None for message in messages
        ):
            _error("visible_exchange_operation_forbidden", "Visible exchange has no operation.")
        if len(messages) < 2 or messages[0]["side"] != "astel":
            _error("invalid_visible_exchange", "Visible exchange begins with Astel.")
    else:
        if operation_id is None or any(
            message["operation_id"] != operation_id for message in messages
        ):
            _error(
                "operation_identity_mismatch",
                "Operation unit messages share the exact operation identity.",
            )
        terminal_indexes = [
            index
            for index, message in enumerate(messages)
            if message["operation_state"] in ("completed", "failed", "cancelled")
        ]
        if terminal_indexes != [len(messages) - 1]:
            _error(
                "operation_finality_missing",
                "Operation unit ends in one terminal result.",
            )
        for index, message in enumerate(messages):
            if (
                message["event_kind"] == "acknowledgement"
                and index >= terminal_indexes[0]
            ):
                _error(
                    "acknowledgement_not_superseded",
                    "Acknowledgement must precede terminal result.",
                )
    for field, expected in (
        ("persisted_by_working_set", False),
        ("memory_vault_truth", False),
        ("self_state", False),
        ("action_permission", False),
    ):
        if raw[field] is not expected:
            _error("forbidden_authority_true", f"{field} differs.")
    source_ids = _opaque_list(
        raw["source_ids"], name="source_ids", maximum=64
    )
    rendered_ids = _opaque_list(
        raw["rendered_source_ids"], name="rendered_source_ids", maximum=64
    )
    if not source_ids or not rendered_ids:
        _error("missing_complete_unit_sources", "Source lists must be nonempty.")
    if not set(rendered_ids).issubset(set(source_ids)):
        _error(
            "rendered_source_not_in_source",
            "Rendered source IDs must come from the exact source set.",
        )
    if raw["source_start_id"] != source_ids[0] or raw["source_end_id"] != source_ids[-1]:
        _error("invalid_source_boundary", "Source boundaries must match order.")
    return {
        "schema_version": COMPLETE_UNIT_SCHEMA_VERSION,
        "producer_class": "android_talk_continuity_units_v0",
        "producer_schema_version": "current",
        "unit_id": _id(raw["unit_id"], name="unit_id", kind="unit_id"),
        "unit_kind": unit_kind,
        "grouping_id": _id(raw["grouping_id"], name="grouping_id"),
        "source_start_id": _id(
            raw["source_start_id"], name="source_start_id"
        ),
        "source_end_id": _id(raw["source_end_id"], name="source_end_id"),
        "source_ids": source_ids,
        "rendered_source_ids": rendered_ids,
        "exact_or_derived": "exact",
        "continuity_status": "complete",
        "complete": True,
        "operation_id": operation_id,
        "messages": messages,
        "source_payload_sha256": _hash(
            raw["source_payload_sha256"], name="source_payload_sha256"
        ),
        "transport_bytes_unchanged": True,
        "persisted_by_working_set": False,
        "memory_vault_truth": False,
        "self_state": False,
        "action_permission": False,
    }

__all__ = [
    "EXACT_ANCHOR_SCHEMA_VERSION",
    "COMPLETE_UNIT_SCHEMA_VERSION",
    "validate_exact_anchor_ref",
    "_complete_unit_message",
    "validate_complete_continuity_unit",
]
