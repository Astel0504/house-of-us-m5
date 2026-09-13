"""Turn-atomic current-session continuity selection.

The Android payload supplies already-grouped source records. This owner validates
the grouping, chooses newest whole units under one measured render budget, and
returns a raw-free source manifest. It never clips an exact source message.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

import provider_visible_text_safety_v0 as provider_text_safety


SCHEMA_VERSION = "house_standing_live_continuity_units_v0"
SELECTION_MANIFEST_SCHEMA_VERSION = "house_standing_live_continuity_selection_manifest_v0"
MAX_CANDIDATE_UNITS = 16
MAX_MESSAGES_PER_UNIT = 20
MAX_SOURCE_TEXT_CHARS = 8000
RECENT_SECTION_HEADING = "Recent exact turns:"
SOFT_RECENT_SECTION_CHARS = 5500
HARD_NEWEST_EXACT_SECTION_CHARS = 18000
MAX_RECENT_RENDER_CHARS = SOFT_RECENT_SECTION_CHARS


class ContinuityUnitError(ValueError):
    pass


def _text(value: Any, *, max_chars: int) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if len(text) > max_chars:
        raise ContinuityUnitError("continuity source text exceeds the canonical Android persistence limit")
    return text


def _identifier(value: Any) -> str:
    text = _text(value, max_chars=180)
    if not text or not all(character.isascii() and (character.isalnum() or character in "_-") for character in text):
        raise ContinuityUnitError("continuity source identity is invalid")
    return text


def _render_unit(messages: list[dict[str, Any]]) -> tuple[list[str], int]:
    lines = [f"- {'Astel' if item['side'] == 'astel' else 'Solen'}: {item['text']}" for item in messages]
    return lines, sum(len(line) + 1 for line in lines)


def _strict_bool(value: Any, *, field: str) -> bool:
    if type(value) is not bool:
        raise ContinuityUnitError(f"continuity {field} must be a boolean")
    return value


def _strict_nonnegative_int(value: Any, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ContinuityUnitError(f"continuity {field} must be a nonnegative integer")
    return value


def _strict_positive_int(value: Any, *, field: str) -> int:
    if type(value) is not int or value < 1:
        raise ContinuityUnitError(f"continuity {field} must be a positive integer")
    return value


def render_recent_section(lines: list[str]) -> str:
    return RECENT_SECTION_HEADING if not lines else f"{RECENT_SECTION_HEADING}\n" + "\n".join(lines)


def _normalize_unit(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContinuityUnitError("continuity unit must be an object")
    unit_id = _identifier(value.get("unit_id"))
    grouping_id = _identifier(value.get("grouping_id"))
    unit_kind = _text(value.get("unit_kind"), max_chars=80)
    if unit_kind not in {"visible_exchange", "provider_agent_operation"}:
        raise ContinuityUnitError("continuity unit kind is unsupported")
    source_ids_value = value.get("source_ids")
    rendered_ids_value = value.get("rendered_source_ids")
    messages_value = value.get("messages")
    if not isinstance(source_ids_value, list) or not isinstance(rendered_ids_value, list) or not isinstance(messages_value, list):
        raise ContinuityUnitError("continuity unit source lists are invalid")
    source_ids = [_identifier(item) for item in source_ids_value]
    rendered_source_ids = [_identifier(item) for item in rendered_ids_value]
    if (
        not source_ids
        or len(source_ids) != len(set(source_ids))
        or not rendered_source_ids
        or len(rendered_source_ids) != len(set(rendered_source_ids))
        or not set(rendered_source_ids).issubset(source_ids)
    ):
        raise ContinuityUnitError("continuity unit source mapping is inconsistent")
    source_start_id = _identifier(value.get("source_start_id"))
    source_end_id = _identifier(value.get("source_end_id"))
    if source_start_id != source_ids[0] or source_end_id != source_ids[-1]:
        raise ContinuityUnitError("continuity source range does not match source ordering")
    if len(messages_value) > MAX_MESSAGES_PER_UNIT:
        raise ContinuityUnitError("continuity unit contains too many source messages")
    messages: list[dict[str, Any]] = []
    unit_exact_or_derived = _text(value.get("exact_or_derived"), max_chars=20) or "exact"
    if unit_exact_or_derived not in {"exact", "derived"}:
        raise ContinuityUnitError("continuity exact-or-derived state is invalid")
    for item in messages_value:
        if not isinstance(item, Mapping):
            raise ContinuityUnitError("continuity message must be an object")
        message_id = _identifier(item.get("message_id"))
        side = _text(item.get("side"), max_chars=20)
        canonical_text = _text(item.get("text"), max_chars=MAX_SOURCE_TEXT_CHARS)
        if message_id not in rendered_source_ids or side not in {"astel", "solen"} or not canonical_text:
            raise ContinuityUnitError("continuity rendered message is invalid")
        message_exact_or_derived = _text(item.get("exact_or_derived"), max_chars=20) or unit_exact_or_derived
        if message_exact_or_derived not in {"exact", "derived"}:
            raise ContinuityUnitError("continuity message exact-or-derived state is invalid")
        provider_text = provider_text_safety.sanitize_provider_visible_text(canonical_text)
        provider_redacted = provider_text != canonical_text
        provider_exact_or_derived = "derived" if provider_redacted else message_exact_or_derived
        messages.append({
            "side": side,
            "speaker": _text(item.get("speaker"), max_chars=96) or ("Astel" if side == "astel" else "Solen"),
            "text": provider_text,
            "partial": not _strict_bool(item.get("complete"), field="message complete"),
            "message_id": message_id,
            "parent_turn_id": _text(item.get("parent_turn_id"), max_chars=180),
            "segment_index": _strict_nonnegative_int(item.get("segment_index"), field="segment index"),
            "segment_count": _strict_positive_int(item.get("segment_count"), field="segment count"),
            "route_label": _text(item.get("route_label"), max_chars=96),
            "created_at_epoch_millis": _strict_nonnegative_int(
                item.get("created_at_epoch_millis"), field="message timestamp"
            ),
            "complete": _strict_bool(item.get("complete"), field="message complete"),
            "operation_id": _text(item.get("operation_id"), max_chars=180),
            "event_kind": _text(item.get("event_kind"), max_chars=80),
            "operation_state": _text(item.get("operation_state"), max_chars=80),
            "exact_or_derived": provider_exact_or_derived,
            "provider_representation_state": "provider_redacted" if provider_redacted else provider_exact_or_derived,
            "provider_redacted": provider_redacted,
        })
    if not messages:
        raise ContinuityUnitError("continuity unit has no rendered messages")
    if [item["message_id"] for item in messages] != rendered_source_ids:
        raise ContinuityUnitError("continuity rendered source order does not match messages")
    timestamps = [item["created_at_epoch_millis"] for item in messages]
    if timestamps != sorted(timestamps):
        raise ContinuityUnitError("continuity messages are not chronological")
    complete = _strict_bool(value.get("complete"), field="unit complete") and all(
        not item["partial"] for item in messages
    )
    assistant = [item for item in messages if item["side"] == "solen"]
    operation_id = _text(value.get("operation_id"), max_chars=180)
    continuity_status = _text(value.get("continuity_status"), max_chars=80) or ("complete" if complete else "partial")
    if unit_kind == "visible_exchange":
        split_assistant = [item for item in assistant if item["segment_count"] > 1]
        if split_assistant:
            expected_count = split_assistant[0]["segment_count"]
            if (
                any(item["segment_count"] != expected_count for item in split_assistant)
                or any(item["parent_turn_id"] != grouping_id for item in split_assistant)
                or len({item["segment_index"] for item in split_assistant}) != len(split_assistant)
                or any(item["segment_index"] >= expected_count for item in split_assistant)
            ):
                raise ContinuityUnitError("continuity split turn grouping is inconsistent")
            if complete and [item["segment_index"] for item in split_assistant] != list(range(expected_count)):
                raise ContinuityUnitError("complete continuity split turn is missing ordered segments")
    else:
        if not operation_id or operation_id != grouping_id:
            raise ContinuityUnitError("continuity provider operation identity is inconsistent")
        if any(item["parent_turn_id"] != grouping_id for item in assistant):
            raise ContinuityUnitError("continuity provider messages do not share the operation parent")
        if any(item["operation_id"] and item["operation_id"] != operation_id for item in assistant):
            raise ContinuityUnitError("continuity provider message operation identity is inconsistent")
        legacy_unknown = bool(assistant) and all(
            not item["event_kind"] and not item["operation_state"] and not item["operation_id"]
            for item in assistant
        )
        if legacy_unknown:
            if continuity_status != "legacy_unknown":
                raise ContinuityUnitError("legacy continuity operation must retain unknown lifecycle state")
        else:
            allowed_states = {"accepted", "running", "completed", "failed", "cancelled", "interrupted"}
            allowed_events = {
                "assistant_acknowledgement", "assistant_final", "operation_failed",
                "operation_cancelled", "operation_interrupted",
            }
            if any(
                not item["operation_id"] or not item["event_kind"] or not item["operation_state"]
                for item in assistant
            ):
                raise ContinuityUnitError("continuity provider lifecycle metadata is incomplete")
            if any(item["operation_state"] not in allowed_states for item in assistant):
                raise ContinuityUnitError("continuity provider operation state is unsupported")
            if any(item["event_kind"] not in allowed_events for item in assistant):
                raise ContinuityUnitError("continuity provider event kind is unsupported")
            valid_event_states = {
                "assistant_acknowledgement": {"accepted", "running"},
                "assistant_final": {"completed"},
                "operation_failed": {"failed"},
                "operation_cancelled": {"cancelled"},
                "operation_interrupted": {"interrupted"},
            }
            if any(item["operation_state"] not in valid_event_states[item["event_kind"]] for item in assistant):
                raise ContinuityUnitError("continuity provider event and operation state are inconsistent")
            terminal = [item for item in assistant if item["event_kind"] != "assistant_acknowledgement"]
            terminal_is_split_final = (
                len(terminal) > 1
                and all(item["event_kind"] == "assistant_final" for item in terminal)
            )
            if terminal_is_split_final:
                expected_count = terminal[0]["segment_count"]
                if (
                    any(item["segment_count"] != expected_count for item in terminal)
                    or len({item["segment_index"] for item in terminal}) != len(terminal)
                    or any(item["segment_index"] >= expected_count for item in terminal)
                    or (complete and [item["segment_index"] for item in terminal] != list(range(expected_count)))
                ):
                    raise ContinuityUnitError("continuity provider split final grouping is inconsistent")
            if (
                (len(terminal) > 1 and not terminal_is_split_final)
                or (terminal and assistant[-len(terminal):] != terminal)
            ):
                raise ContinuityUnitError("continuity provider terminal event ordering is inconsistent")
            expected_status = (
                terminal[-1]["operation_state"] if terminal else "running"
            )
            if continuity_status != expected_status:
                raise ContinuityUnitError("continuity provider unit state is inconsistent")
    lines, char_estimate = _render_unit(messages)
    provider_redaction_count = sum(1 for item in messages if item["provider_redacted"])
    normalized_exact_or_derived = "derived" if provider_redaction_count else unit_exact_or_derived
    return {
        "unit_id": unit_id,
        "unit_kind": unit_kind,
        "grouping_id": grouping_id,
        "source_ids": source_ids,
        "rendered_source_ids": rendered_source_ids,
        "source_start_id": source_start_id,
        "source_end_id": source_end_id,
        "exact_or_derived": normalized_exact_or_derived,
        "provider_representation_state": "provider_redacted" if provider_redaction_count else normalized_exact_or_derived,
        "provider_redaction_count": provider_redaction_count,
        "continuity_status": continuity_status,
        "complete": complete,
        "operation_id": operation_id,
        "created_at_epoch_millis": min((item["created_at_epoch_millis"] for item in messages), default=0),
        "messages": messages,
        "render_lines": lines,
        "char_estimate": char_estimate,
    }


def select_recent_continuity_units(values: Any, *, max_render_chars: int = MAX_RECENT_RENDER_CHARS) -> dict[str, Any]:
    if not isinstance(values, list):
        raise ContinuityUnitError("recent continuity units must be a list")
    if len(values) > MAX_CANDIDATE_UNITS:
        raise ContinuityUnitError("recent continuity unit candidate count exceeds the Android contract")
    if type(max_render_chars) is not int or max_render_chars < len(RECENT_SECTION_HEADING):
        raise ContinuityUnitError("recent continuity render budget is invalid")
    units = [_normalize_unit(value) for value in values]
    all_source_ids = [source_id for unit in units for source_id in unit["source_ids"]]
    if len(all_source_ids) != len(set(all_source_ids)):
        raise ContinuityUnitError("continuity source identity belongs to more than one candidate unit")
    unit_times = [unit["created_at_epoch_millis"] for unit in units]
    if unit_times != sorted(unit_times):
        raise ContinuityUnitError("continuity units are not chronological")
    effective_soft_budget = min(max_render_chars, SOFT_RECENT_SECTION_CHARS)
    selected: list[dict[str, Any]] = []
    manifest_by_id: dict[str, dict[str, Any]] = {}
    boundary_unit_id = ""
    boundary_seen = False
    for unit in reversed(units):
        selectable_running_operation = (
            unit["unit_kind"] == "provider_agent_operation"
            and unit["continuity_status"] in {"accepted", "running"}
        )
        if boundary_seen:
            reason = "older_than_exact_history_boundary"
            selected_state = False
        elif not unit["complete"] and not selectable_running_operation:
            reason = "incomplete_canonical_unit"
            selected_state = False
            boundary_seen = True
            boundary_unit_id = unit["unit_id"]
        else:
            candidate_units = [unit, *selected]
            candidate_lines = [line for candidate in candidate_units for line in candidate["render_lines"]]
            candidate_section_chars = len(render_recent_section(candidate_lines))
            if not selected and candidate_section_chars <= HARD_NEWEST_EXACT_SECTION_CHARS:
                selected.insert(0, unit)
                selected_state = True
                if candidate_section_chars <= effective_soft_budget:
                    reason = "selected_newest_whole_unit"
                else:
                    reason = "selected_newest_exact_over_soft_budget"
                    boundary_seen = True
                    boundary_unit_id = unit["unit_id"]
            elif selected and candidate_section_chars <= effective_soft_budget:
                selected.insert(0, unit)
                selected_state = True
                reason = "selected_whole_unit_within_soft_budget"
            elif not selected:
                selected_state = False
                reason = "newest_unit_exceeds_hard_exact_ceiling_no_semantic_representation"
                boundary_seen = True
                boundary_unit_id = unit["unit_id"]
            else:
                reason = "whole_unit_budget_eviction"
                selected_state = False
                boundary_seen = True
                boundary_unit_id = unit["unit_id"]
        manifest_by_id[unit["unit_id"]] = {
            "unit_id": unit["unit_id"],
            "unit_kind": unit["unit_kind"],
            "grouping_id": unit["grouping_id"],
            "source_ids": unit["source_ids"],
            "rendered_source_ids": unit["rendered_source_ids"],
            "source_start_id": unit["source_start_id"],
            "source_end_id": unit["source_end_id"],
            "exact_or_derived": unit["exact_or_derived"],
            "selected": selected_state,
            "exclusion_reason": "" if selected_state else reason,
            "selection_reason": reason if selected_state else "",
            "character_estimate": unit["char_estimate"],
            "token_estimate": (unit["char_estimate"] + 3) // 4,
            "continuity_status": unit["continuity_status"],
            "provider_representation_state": unit["provider_representation_state"],
            "provider_redaction_count": unit["provider_redaction_count"],
            "destination_section": "recent_exact_turns" if selected_state else "excluded",
            "whole_unit_budget_eviction": reason == "whole_unit_budget_eviction",
            "exact_history_boundary": reason in {
                "incomplete_canonical_unit",
                "whole_unit_budget_eviction",
                "newest_unit_exceeds_hard_exact_ceiling_no_semantic_representation",
                "selected_newest_exact_over_soft_budget",
            },
            "boundary_unit_id": boundary_unit_id if not selected_state else "",
            "coherent_fallback": False,
        }
    owned_source_ids = [source_id for unit in selected for source_id in unit["source_ids"]]
    rendered_source_ids = [source_id for unit in selected for source_id in unit["rendered_source_ids"]]
    render_lines = [line for unit in selected for line in unit["render_lines"]]
    rendered_section = render_recent_section(render_lines) if render_lines else ""
    derived_count = sum(1 for unit in selected if unit["exact_or_derived"] == "derived")
    provider_redaction_count = sum(unit["provider_redaction_count"] for unit in selected)
    provider_redacted_unit_count = sum(1 for unit in selected if unit["provider_redaction_count"])
    return {
        "schema_version": SCHEMA_VERSION,
        "selected_units": selected,
        "selected_messages": [message for unit in selected for message in unit["messages"]],
        "render_lines": render_lines,
        "rendered_section": rendered_section,
        "owned_source_ids": owned_source_ids,
        "rendered_source_ids": rendered_source_ids,
        "selected_source_ids": rendered_source_ids,
        "selected_source_ids_alias": "rendered_source_ids",
        "truncated": len(selected) != len(units),
        "selection_manifest": {
            "schema_version": SELECTION_MANIFEST_SCHEMA_VERSION,
            "raw_text_included": False,
            "budget_chars": effective_soft_budget,
            "hard_newest_exact_section_chars": HARD_NEWEST_EXACT_SECTION_CHARS,
            "heading_chars_included": True,
            "selected_render_chars": len(rendered_section),
            "owned_source_ids": owned_source_ids,
            "rendered_source_ids": rendered_source_ids,
            "derived_representation_count": derived_count,
            "provider_redaction_count": provider_redaction_count,
            "provider_redacted_unit_count": provider_redacted_unit_count,
            "provider_redaction_state": "applied" if provider_redaction_count else "not_needed",
            "fallback_representation_count": 0,
            "whole_unit_budget_eviction_count": sum(
                1 for item in manifest_by_id.values() if item["whole_unit_budget_eviction"]
            ),
            "hard_ceiling_exclusion_count": sum(
                1
                for item in manifest_by_id.values()
                if item["exclusion_reason"] == "newest_unit_exceeds_hard_exact_ceiling_no_semantic_representation"
            ),
            "candidates": [manifest_by_id[unit["unit_id"]] for unit in units],
        },
    }


def normalize_punctuation_for_forensic_match(value: str) -> str:
    translation = str.maketrans({
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "-", "\u2026": "...",
    })
    normalized = " ".join(str(value or "").translate(translation).split())
    return re.sub(r"\s*-\s*", "-", normalized)
