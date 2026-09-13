from __future__ import annotations

from typing import Any


VISIBLE_REPLY_SEGMENTS_SCHEMA_VERSION = "api_talk_visible_reply_segments_v0"
FUTURE_STRUCTURED_REPLY_SCHEMA_VERSION = "api_talk_future_structured_reply_contract_v0"
SPLIT_MARKER = "<split>"
MAX_VISIBLE_REPLY_SEGMENTS = 4


def split_visible_reply_segments(value: Any, *, max_segments: int = MAX_VISIBLE_REPLY_SEGMENTS) -> dict[str, Any]:
    text = "" if value is None else str(value)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_segments: list[str] = []
    current_lines: list[str] = []
    marker_count = 0
    in_fenced_code = False

    for line in normalized.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            current_lines.append(line)
            in_fenced_code = not in_fenced_code
            continue
        if not in_fenced_code and stripped == SPLIT_MARKER:
            marker_count += 1
            segment = "\n".join(current_lines).strip()
            if segment:
                raw_segments.append(segment)
            current_lines = []
            continue
        current_lines.append(line)

    final_segment = "\n".join(current_lines).strip()
    if final_segment:
        raw_segments.append(final_segment)

    if marker_count <= 0:
        fallback = normalized.strip()
        raw_segments = [fallback] if fallback else []
        state = "single"
    elif raw_segments:
        state = "selected"
    else:
        state = "empty"

    safe_max = max(int(max_segments or MAX_VISIBLE_REPLY_SEGMENTS), 1)
    truncated = len(raw_segments) > safe_max
    if truncated:
        kept = raw_segments[: safe_max - 1]
        folded = "\n\n".join(raw_segments[safe_max - 1 :]).strip()
        raw_segments = kept + ([folded] if folded else [])

    return {
        "schema_version": VISIBLE_REPLY_SEGMENTS_SCHEMA_VERSION,
        "state": state,
        "split_marker": SPLIT_MARKER,
        "segment_count": len(raw_segments),
        "marker_count": marker_count,
        "max_segments": safe_max,
        "truncated": truncated,
        "split_on_sentences": False,
        "split_on_blank_lines": False,
        "ignore_markers_inside_fenced_code_blocks": True,
        "segments": raw_segments,
    }


def future_structured_reply_contract() -> dict[str, Any]:
    return {
        "schema_version": FUTURE_STRUCTURED_REPLY_SCHEMA_VERSION,
        "state": "fake_no_live_scaffold",
        "required_for_android_standing_live": False,
        "provider_json_required": False,
        "standing_live_provider_responses_may_remain_plain_text": True,
        "example_shape": {
            "memory_candidates": [],
            "check_needed": [],
        },
        "fields": {
            "memory_candidates": {
                "type": "array",
                "default": [],
                "state": "future_not_written_by_this_gate",
                "max_items": 0,
            },
            "check_needed": {
                "type": "array",
                "default": [],
                "state": "future_not_actioned_by_this_gate",
                "max_items": 0,
            },
        },
        "boundaries": {
            "memory_writes_enabled": False,
            "tool_actions_enabled": False,
            "provider_structured_output_calls_enabled": False,
            "raw_provider_body_logging_enabled": False,
        },
    }
