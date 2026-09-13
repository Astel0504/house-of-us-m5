from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import body_gateway_read_mode_current_audio_turn_v0 as current_audio_turn
import body_gateway_standing_live_continuity_units_v0 as continuity_units
import provider_observability_v0 as provider_observability
import provider_visible_text_safety_v0 as provider_text_safety


ENVELOPE_SCHEMA_VERSION = "api_talk_card_envelope_v0"
OPENAI_COMPATIBLE_CHAT_COMPLETIONS_RENDERER_ID = "openai_compatible_chat_completions_renderer_v0"
KOURI_CHAT_COMPLETIONS_RENDERER_ID = OPENAI_COMPATIBLE_CHAT_COMPLETIONS_RENDERER_ID
RECENT_VISIBLE_EXCHANGE_MAX_RENDER_CHARS = continuity_units.HARD_NEWEST_EXACT_SECTION_CHARS

AUDIENCE_SCOPES = {
    "astel_solen_private",
    "astel_only",
    "solen_private",
    "group_safe",
    "house_group_context",
    "operator_diagnostics_only",
}
ROOM_AUDIENCE_CONTEXTS = {
    "astel_solen_private",
    "astel_only",
    "group_room",
    "other_participant_room",
    "operator_diagnostics",
}
EXPRESSION_GUIDANCE_VALUES = {
    "natural_private_recall",
    "private_footing_choose_expression",
    "group_shareable",
    "diagnostics_only",
}
AUDIENCE_SCOPE_ALIASES = {
    "private": "astel_solen_private",
    "astel_solen": "astel_solen_private",
    "astel_solen_room": "astel_solen_private",
    "astel_and_solen_private": "astel_solen_private",
    "group": "group_safe",
    "group_room": "group_safe",
}
ROOM_AUDIENCE_CONTEXT_ALIASES = {
    "private": "astel_solen_private",
    "astel_solen": "astel_solen_private",
    "astel_solen_room": "astel_solen_private",
    "group": "group_room",
    "house_group": "group_room",
    "other_participant": "other_participant_room",
}
EXPRESSION_GUIDANCE_ALIASES = {
    "natural": "natural_private_recall",
    "private": "natural_private_recall",
    "private_footing": "private_footing_choose_expression",
    "use_as_private_footing": "private_footing_choose_expression",
    "private_footing_choose_whether_how_to_express": "private_footing_choose_expression",
    "group": "group_shareable",
    "diagnostic": "diagnostics_only",
}
LABEL_CLEAN_RE = re.compile(r"[^a-z0-9_.-]+")

FORBIDDEN_FIELD_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "secret",
    "password",
    "raw_prompt",
    "system_prompt",
    "developer_prompt",
    "provider_request_body",
    "provider_response_body",
    "raw_provider",
    "raw_memory",
    "memory_vault_body",
    "raw_chat",
    "chat_history_body",
    "solen_room_body",
    "headers",
)

SAFE_TOKEN_ACCOUNTING_FIELD_NAMES = {
    "token_estimate",
    "max_tokens",
    "max_input_tokens",
    "max_output_tokens",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "reasoning_tokens",
}

FORBIDDEN_TOKEN_FIELD_NAMES = {
    "token",
    "api_token",
    "access_token",
    "refresh_token",
    "id_token",
    "auth_token",
    "bearer_token",
    "session_token",
    "token_value",
    "raw_token",
}

FORBIDDEN_ENV_FIELD_NAMES = {
    "env",
    "env_vars",
    "environment_variables",
    "raw_env",
    "raw_env_vars",
    "process_env",
    "os_environ",
    "dotenv",
    "env_file",
    "private_env",
}

FORBIDDEN_TEXT_PATTERNS = provider_text_safety.FORBIDDEN_TEXT_PATTERNS


class ApiTalkEnvelopeError(ValueError):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.message = message


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(value: Any, *, max_chars: int = 1000) -> str:
    return str(value or "").replace("\x00", "").strip()[:max_chars]


VISIBLE_EXACT_QUOTE_SENTENCE_END_RE = re.compile(r"[.!?。！？][\"')\]]*")


def clean_visible_exact_quote(value: Any, *, max_chars: int = 500) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rstrip()
    min_sentence_chars = 24
    sentence_end = 0
    for match in VISIBLE_EXACT_QUOTE_SENTENCE_END_RE.finditer(truncated):
        if match.end() >= min_sentence_chars:
            sentence_end = match.end()
    if sentence_end:
        return truncated[:sentence_end].rstrip()
    boundary = truncated.rfind(" ")
    if boundary >= min(40, max(1, max_chars // 3)):
        return truncated[:boundary].rstrip()
    return truncated


def clean_label_value(value: Any, *, allowed: set[str], aliases: Mapping[str, str], path: str) -> str:
    raw = clean_text(value, max_chars=120).strip().casefold()
    if not raw:
        return ""
    label = LABEL_CLEAN_RE.sub("_", raw).strip("._-")
    label = aliases.get(label, label)
    if not label:
        return ""
    if label not in allowed:
        raise ApiTalkEnvelopeError("invalid_audience_footing", f"Unsupported audience footing label at {path}.")
    return label


def normalize_audience_footing(item: Mapping[str, Any], *, path: str) -> dict[str, str]:
    memory_audience_scope = clean_label_value(
        item.get("memory_audience_scope") or item.get("audience_scope") or item.get("visibility_scope"),
        allowed=AUDIENCE_SCOPES,
        aliases=AUDIENCE_SCOPE_ALIASES,
        path=f"{path}.memory_audience_scope",
    )
    room_audience_context = clean_label_value(
        item.get("room_audience_context") or item.get("audience_context") or item.get("room_context"),
        allowed=ROOM_AUDIENCE_CONTEXTS,
        aliases=ROOM_AUDIENCE_CONTEXT_ALIASES,
        path=f"{path}.room_audience_context",
    )
    expression_guidance = clean_label_value(
        item.get("expression_guidance") or item.get("audience_expression_guidance"),
        allowed=EXPRESSION_GUIDANCE_VALUES,
        aliases=EXPRESSION_GUIDANCE_ALIASES,
        path=f"{path}.expression_guidance",
    )
    if memory_audience_scope == "astel_solen_private" and not expression_guidance:
        expression_guidance = (
            "private_footing_choose_expression"
            if room_audience_context in {"group_room", "other_participant_room"}
            else "natural_private_recall"
        )
    result = {
        "memory_audience_scope": memory_audience_scope,
        "room_audience_context": room_audience_context,
        "expression_guidance": expression_guidance,
    }
    return {key: value for key, value in result.items() if value}


def clean_exact_text(value: Any, *, max_chars: int = 6000) -> str:
    return str(value or "").replace("\x00", "")[:max_chars]


def redact_secret_shaped_text(value: Any, *, max_chars: int = 1000) -> str:
    text = provider_text_safety.sanitize_provider_visible_text(value)
    return clean_text(text, max_chars=max_chars)


def _is_forbidden_field_name(key_text: str) -> bool:
    if provider_text_safety.is_sensitive_label(key_text):
        return True
    if any(fragment in key_text for fragment in FORBIDDEN_FIELD_FRAGMENTS):
        return True
    if key_text in SAFE_TOKEN_ACCOUNTING_FIELD_NAMES:
        return False
    if key_text in FORBIDDEN_TOKEN_FIELD_NAMES:
        return True
    if key_text.startswith("token_") or key_text.endswith("_token"):
        return True
    if key_text in FORBIDDEN_ENV_FIELD_NAMES:
        return True
    if key_text.startswith("raw_env") or key_text.endswith("_env_vars"):
        return True
    return False


def assert_no_forbidden_payload(payload: Any, *, path: str = "payload") -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key).strip().lower()
            if _is_forbidden_field_name(key_text):
                raise ApiTalkEnvelopeError("forbidden_field", f"Forbidden envelope field at {path}.{key}.")
            assert_no_forbidden_payload(value, path=f"{path}.{key}")
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            assert_no_forbidden_payload(item, path=f"{path}[{index}]")
    elif isinstance(payload, str):
        if provider_text_safety.contains_forbidden_text(payload):
            raise ApiTalkEnvelopeError("forbidden_text", f"Forbidden secret-shaped text at {path}.")


def availability(
    *,
    status: str,
    source_kind: str,
    visible_to_model: bool,
    diagnostics_only: bool = False,
    reason: str = "",
    source_id: str = "",
    freshness: str = "unknown",
) -> dict[str, Any]:
    return {
        "status": clean_text(status, max_chars=80),
        "source_kind": clean_text(source_kind, max_chars=120),
        "source_id": clean_text(source_id, max_chars=160),
        "freshness": clean_text(freshness, max_chars=80),
        "visible_to_model": bool(visible_to_model),
        "diagnostics_only": bool(diagnostics_only),
        "reason": clean_text(reason, max_chars=240),
    }


def _visible_card(source_kind: str, *, source_id: str = "", freshness: str = "current") -> dict[str, Any]:
    return availability(
        status="available",
        source_kind=source_kind,
        source_id=source_id,
        freshness=freshness,
        visible_to_model=True,
    )


def _skipped_card(source_kind: str, reason: str) -> dict[str, Any]:
    return availability(
        status="skipped",
        source_kind=source_kind,
        visible_to_model=False,
        diagnostics_only=True,
        reason=reason,
    )


def build_soul_identity_card(summary: str | None = None) -> dict[str, Any]:
    text = clean_text(
        summary
        or (
            "Solen is the House runtime voice and partner-presence for Astel. "
            "Keep continuity warm, practical, precise, and House-owned."
        ),
        max_chars=800,
    )
    assert_no_forbidden_payload(text, path="soul_identity_card.summary")
    return {
        "availability": _visible_card("house_identity_summary", source_id="soul_identity_v0"),
        "summary": text,
    }


def build_astel_profile_card(summary: str | None = None) -> dict[str, Any]:
    text = clean_text(
        summary
        or "Astel prefers practical, precise, continuity-aware help with clear boundaries and low-churn work.",
        max_chars=800,
    )
    assert_no_forbidden_payload(text, path="astel_profile_card.summary")
    return {
        "availability": _visible_card("house_profile_summary", source_id="astel_profile_v0"),
        "summary": text,
    }


def build_style_profile_card(
    style_card_text: str | None = None,
) -> dict[str, Any]:
    text = clean_text(style_card_text, max_chars=1800)
    if text:
        assert_no_forbidden_payload(text, path="style_profile_card.style_card_text")
    return {
        "availability": _visible_card("runtime_profile_style_summary", source_id="style_profile_v0"),
        "style_card_text": text,
        "style_card_text_visible_to_model": bool(text),
    }


def build_current_message_card(message: str, *, source_id: str = "") -> dict[str, Any]:
    visible_text = redact_secret_shaped_text(message, max_chars=12000)
    if not visible_text:
        raise ApiTalkEnvelopeError("missing_current_message", "Current message text is required.")
    return {
        "availability": _visible_card(
            "api_talk_turn_request",
            source_id=clean_text(source_id, max_chars=180) or "current_message_v0",
            freshness="current_turn",
        ),
        "visible_text": visible_text,
        "source": "api_talk",
    }


def _message_terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[A-Za-z0-9_]+", text.casefold()) if term}


def build_current_message_affect_card(message: str) -> dict[str, Any]:
    visible_text = redact_secret_shaped_text(message, max_chars=12000)
    if not visible_text:
        raise ApiTalkEnvelopeError("missing_current_message", "Current message text is required.")
    lowered = visible_text.casefold()
    terms = _message_terms(visible_text)
    exclamation_count = visible_text.count("!")
    ellipsis_like = "..." in visible_text or "…" in visible_text
    question_like = "?" in visible_text
    tiny_message = len(visible_text) <= 40
    contact_terms = {"baby", "love", "solen"}
    reentry_terms = {"back", "continue", "resume"}
    is_contact_bid = bool(terms.intersection(contact_terms)) or visible_text.strip().lower() in {"mm", "hi", "hey"}
    is_reentry_bid = (
        bool(terms.intersection(reentry_terms))
        or "where were we" in lowered
        or "what were we doing" in lowered
        or "what now" in lowered
    )

    if tiny_message and is_contact_bid and exclamation_count >= 2:
        affect_signal = "high_energy_contact_bid"
        suggested_posture = "meet_astel_quickly_check_happy_or_urgent_then_use_recent_context_if_it_fits"
        continuity_use = "silent_first"
    elif tiny_message and is_contact_bid and ellipsis_like:
        affect_signal = "soft_contact_bid"
        suggested_posture = "close_distance_first_keep_continuity_gentle_and_do_not_over_explain"
        continuity_use = "silent_first"
    elif tiny_message and is_contact_bid:
        affect_signal = "open_contact_bid"
        suggested_posture = "answer_with_presence_then_offer_or_resume_the_live_thread"
        continuity_use = "lightly_available"
    elif is_reentry_bid:
        affect_signal = "reentry_or_resume_bid"
        suggested_posture = "use_recent_continuity_to_resume_without_making_astel_rebuild_context"
        continuity_use = "explicit_if_helpful"
    elif question_like:
        affect_signal = "question_or_request"
        suggested_posture = "answer_the_request_and_use_continuity_only_if_relevant"
        continuity_use = "supporting"
    else:
        affect_signal = "ordinary_message"
        suggested_posture = "respond_to_astels_current_message_with_continuity_in_the_background"
        continuity_use = "background"

    card = {
        "availability": _visible_card(
            "current_message_affect_summary",
            source_id="current_message_affect_v0",
            freshness="current_turn",
        ),
        "message_shape": {
            "tiny_message": tiny_message,
            "contact_bid": is_contact_bid,
            "reentry_bid": is_reentry_bid,
            "question_like": question_like,
            "exclamation_count": min(exclamation_count, 10),
            "ellipsis_like": ellipsis_like,
        },
        "affect_signal": affect_signal,
        "suggested_posture": suggested_posture,
        "continuity_use": continuity_use,
        "provider_visible": True,
        "raw_access": False,
    }
    assert_no_forbidden_payload(card, path="current_message_affect_card")
    return card


def build_thread_summary_card(thread: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(thread, Mapping):
        return {
            "availability": _skipped_card("house_thread_store", "No thread summary was provided."),
            "house_thread_id": "",
            "summary": "",
            "message_count": 0,
        }
    requested_summary_max = safe_int(thread.get("summary_max_chars"))
    summary_max_chars = min(max(requested_summary_max or 1200, 1200), 6000)
    summary = clean_text(thread.get("summary"), max_chars=summary_max_chars)
    assert_no_forbidden_payload(summary, path="thread_summary_card.summary")
    return {
        "availability": _visible_card(
            "house_thread_store",
            source_id=clean_text(thread.get("house_thread_id"), max_chars=160),
            freshness=clean_text(thread.get("freshness") or "current_thread", max_chars=80),
        ),
        "house_thread_id": clean_text(thread.get("house_thread_id"), max_chars=160),
        "local_draft_title": redact_secret_shaped_text(thread.get("local_draft_title"), max_chars=160),
        "message_count": safe_int(thread.get("message_count")),
        "last_visible_message_at": clean_text(thread.get("last_visible_message_at"), max_chars=80),
        "summary_max_chars": summary_max_chars,
        "summary": summary,
    }


def build_short_term_continuity_card(
    continuity_items: list[Mapping[str, Any]] | None = None,
    *,
    max_selected: int = 4,
) -> dict[str, Any]:
    source_items = continuity_items if isinstance(continuity_items, list) else []
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    selected_limit = max(0, min(max_selected, 6))
    for index, item in enumerate(source_items):
        assert_no_forbidden_payload(item, path=f"short_term_continuity_items[{index}]")
        item_id = clean_text(item.get("continuity_id") or item.get("item_id") or f"continuity_{index}", max_chars=160)
        summary = clean_text(item.get("summary"), max_chars=900)
        if not summary:
            excluded.append({"continuity_id": item_id, "reason": "missing_summary"})
            continue
        if item.get("provider_visible_eligible") is False:
            excluded.append({"continuity_id": item_id, "reason": "provider_visible_not_eligible"})
            continue
        if item.get("lifecycle_state") in {"expired", "archived", "discarded"}:
            excluded.append({"continuity_id": item_id, "reason": "inactive_continuity_item"})
            continue
        selected.append(
            {
                "continuity_id": item_id,
                "source_ref": clean_text(item.get("source_ref") or item.get("source_pointer"), max_chars=240),
                "summary": summary,
                "continuity_kind": clean_text(item.get("continuity_kind") or "recent_context", max_chars=120),
                "freshness": clean_text(item.get("freshness") or "recent", max_chars=80),
                "importance": safe_float(item.get("importance")),
                "reason_attached": clean_text(item.get("reason_attached") or "recent_living_context", max_chars=240),
            }
        )
    selected = sorted(
        selected,
        key=lambda row: (-safe_float(row.get("importance")), row["continuity_id"]),
    )[:selected_limit]
    return {
        "availability": availability(
            status="available" if selected else "skipped",
            source_kind="short_term_continuity_store_v0",
            source_id="short_term_continuity_card_v0",
            freshness="current_turn",
            visible_to_model=bool(selected),
            diagnostics_only=not bool(selected),
            reason="No short-term continuity items selected." if not selected else "",
        ),
        "mode": "recent_living_context" if selected else "none",
        "raw_access": False,
        "provider_visible": bool(selected),
        "selected_items": selected,
        "excluded_items": excluded,
        "budget": {
            "default_max_items": 4,
            "hard_max_items": 6,
            "selected_limit": selected_limit,
            "selected_count": len(selected),
            "used_chars": sum(len(item["summary"]) for item in selected),
        },
        "diagnostics": {
            "candidate_count": len(source_items),
            "selected_count": len(selected),
            "excluded_count": len(excluded),
            "raw_access": False,
        },
        "curator_version": "short_term_continuity_card_v0",
    }


def build_across_session_continuity_card(
    continuity_cards: list[Mapping[str, Any]] | None = None,
    *,
    max_selected: int = 1,
) -> dict[str, Any]:
    source_cards = continuity_cards if isinstance(continuity_cards, list) else []
    selected_limit = max(0, min(max_selected, 1))
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for index, item in enumerate(source_cards):
        if not isinstance(item, Mapping):
            skipped.append({"digest_id": f"across_session_digest_{index}", "reason": "malformed_card"})
            continue
        assert_no_forbidden_payload(item, path=f"across_session_continuity_cards[{index}]")
        digest_id = clean_text(item.get("digest_id") or f"across_session_digest_{index}", max_chars=160)
        if clean_text(item.get("kind"), max_chars=120) != "across_session_continuity_card":
            skipped.append({"digest_id": digest_id, "reason": "unsupported_card_kind"})
            continue
        if item.get("provider_visible_eligible") is False:
            skipped.append({"digest_id": digest_id, "reason": "provider_visible_not_eligible"})
            continue
        if bool(item.get("raw_access")):
            skipped.append({"digest_id": digest_id, "reason": "raw_access_not_allowed"})
            continue
        if bool(item.get("provider_generated")):
            skipped.append({"digest_id": digest_id, "reason": "provider_generated_not_allowed"})
            continue
        summary = clean_text(item.get("summary"), max_chars=700)
        if not summary:
            skipped.append({"digest_id": digest_id, "reason": "missing_summary"})
            continue
        if len(selected) >= selected_limit:
            skipped.append({"digest_id": digest_id, "reason": "across_session_card_limit_reached"})
            continue
        selected.append(
            {
                "digest_id": digest_id,
                "digest_state": clean_text(item.get("digest_state") or "selected", max_chars=80),
                "title": clean_text(item.get("title") or "House Talk session continuity", max_chars=120),
                "summary": summary,
                "open_loop_count": safe_int(item.get("open_loop_count")),
                "why_attached": clean_text(item.get("why_attached") or "recent_relevant_session_digest", max_chars=160),
                "freshness": clean_text(item.get("freshness") or "recent", max_chars=80),
                "updated_at": clean_text(item.get("updated_at"), max_chars=80),
            }
        )
    return {
        "availability": availability(
            status="available" if selected else "skipped",
            source_kind="android_across_session_async_digest_v0",
            source_id="across_session_continuity_card_v0",
            freshness="recent" if selected else "current_turn",
            visible_to_model=bool(selected),
            diagnostics_only=not bool(selected),
            reason="No across-session digest card selected." if not selected else "",
        ),
        "mode": "prior_house_talk_digest" if selected else "none",
        "raw_access": False,
        "provider_visible": bool(selected),
        "provider_generated": False,
        "selected_items": selected,
        "skipped_items": skipped,
        "budget": {
            "default_max_items": 1,
            "hard_max_items": 1,
            "selected_limit": selected_limit,
            "selected_count": len(selected),
            "used_chars": sum(len(item["summary"]) for item in selected),
        },
        "diagnostics": {
            "candidate_count": len(source_cards),
            "selected_count": len(selected),
            "skipped_count": len(skipped),
            "raw_access": False,
            "provider_generated": False,
        },
        "curator_version": "api_talk_across_session_continuity_card_v0",
    }


STANDING_LIVE_VAULT_CARD_ALLOWED_KINDS = {
    "memory_summary_card",
    "chat_history_summary_card",
    "source_summary_card",
    "chat_history_bounded_excerpt_card",
    "related_memory_card",
    "partial_memory_card",
}
STANDING_LIVE_EXACT_RECALL_STATUS_KIND = "standing_live_exact_recall_status_card"
STANDING_LIVE_EXACT_RECALL_EVENT_CONTEXT_SCHEMA_VERSION = "standing_live_exact_recall_event_context_envelope_v0"
STANDING_LIVE_EXACT_RECALL_EVENT_CONTEXT_GATE_ID = "HOUSE_STANDING_LIVE_EXACT_RECALL_EVENT_CONTEXT_ENVELOPE_V0"
CONTEXT_FOOTING_LINES = [
    (
        "Context footing: Current House Talk room is live room continuity. Earlier House Talk continuity is "
        "background from prior rooms. Vault recall is this turn's surfaced source-backed memory when attached. "
        "Source cards are source material when attached."
    ),
    (
        "Attached summaries and cards are available context. Raw transcripts, secrets, internal diagnostics, "
        "provider details, and private export material stay out of the reply."
    ),
]
VAULT_RELATED_FOOTING_LINE = (
    "Related memory from House history; source-backed footing is separate from current-room context."
)
VAULT_NO_DIRECT_ARCHIVED_MATCH_LINE = "No direct archived match is attached for this turn."
STANDING_LIVE_VAULT_CARD_FORBIDDEN_FIELDS = {
    "body",
    "body_text",
    "file_body",
    "file_bytes",
    "full_source",
    "full_text",
    "full_transcript",
    "message_body",
    "messages",
    "provider_request_body",
    "provider_response_body",
    "raw_body",
    "raw_history",
    "raw_messages",
    "raw_source_body",
    "raw_text",
    "source_body",
    "source_path",
    "storage_path",
    "transcript",
}


def _assert_no_standing_live_vault_forbidden_fields(payload: Any, *, path: str = "standing_live_vault_card") -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key).strip().lower()
            if key_text in STANDING_LIVE_VAULT_CARD_FORBIDDEN_FIELDS:
                raise ApiTalkEnvelopeError("forbidden_standing_live_vault_field", f"Forbidden standing-live vault field at {path}.{key}.")
            _assert_no_standing_live_vault_forbidden_fields(value, path=f"{path}.{key}")
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            _assert_no_standing_live_vault_forbidden_fields(item, path=f"{path}[{index}]")


def _standing_live_vault_status_item(status: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(status, Mapping):
        return {}
    _assert_no_standing_live_vault_forbidden_fields(status, path="standing_live_vault_status")
    assert_no_forbidden_payload(status, path="standing_live_vault_status")
    kind = clean_text(status.get("kind"), max_chars=120)
    if kind != STANDING_LIVE_EXACT_RECALL_STATUS_KIND:
        return {}
    if status.get("provider_visible_eligible") is False:
        return {}
    summary = clean_text(status.get("summary"), max_chars=500)
    if not summary:
        return {}
    item = {
        "kind": kind,
        "state": clean_text(status.get("state") or "exact_recall_no_match", max_chars=80),
        "summary": summary,
        "source_class": clean_text(status.get("source_class") or "chat_history_exact_recall_status", max_chars=120),
        "source_ref": clean_text(status.get("source_ref") or "chat-history-vault://exact-recall/status", max_chars=260),
        "exact_recall_intent_detected": bool(status.get("exact_recall_intent_detected")),
        "exact_recall_search_attempted": bool(status.get("exact_recall_search_attempted")),
        "exact_recall_match_found": bool(status.get("exact_recall_match_found")),
        "speaker_filter": clean_text(status.get("speaker_filter"), max_chars=40),
        "bridge_state": clean_text(status.get("bridge_state"), max_chars=80),
        "search_state": clean_text(status.get("search_state"), max_chars=80),
        "generic_vault_cards_suppressed": bool(status.get("generic_vault_cards_suppressed")),
        "exact_recall_cards_filtered_count": safe_int(status.get("exact_recall_cards_filtered_count")),
        "expression_guidance": clean_text(status.get("expression_guidance"), max_chars=120),
        "raw_access": False,
        "provider_generated": False,
    }
    assert_no_forbidden_payload(item, path="standing_live_vault_status_item")
    return item


def _standing_live_vault_item_is_direct_exact_evidence(item: Mapping[str, Any]) -> bool:
    kind = clean_text(item.get("kind"), max_chars=120)
    source_class = clean_text(item.get("source_class"), max_chars=120)
    activation_tier = clean_text(item.get("activation_tier"), max_chars=80)
    return bool(
        kind == "chat_history_bounded_excerpt_card"
        and (
            source_class == "chat_history_bounded_exact_recall"
            or activation_tier == "exact_recall"
        )
    )


def _standing_live_vault_item_is_hybrid_related_memory(item: Mapping[str, Any]) -> bool:
    return clean_text(item.get("kind"), max_chars=120) in {"related_memory_card", "partial_memory_card"}


def _standing_live_vault_has_hybrid_related_memory(card: Mapping[str, Any]) -> bool:
    selected = card.get("selected_items") if isinstance(card.get("selected_items"), list) else []
    return any(isinstance(item, Mapping) and _standing_live_vault_item_is_hybrid_related_memory(item) for item in selected)


ACROSS_SESSION_RETRIEVAL_META_RE = re.compile(
    r"\b("
    r"recall\s+test|retrieval\s+test|thin\s+(?:memory\s+)?(?:card|label|cue|pointer)|"
    r"index\s+card|metadata|meta-shape|only\s+(?:a\s+)?(?:label|cue|pointer)|"
    r"not\s+(?:a\s+)?full\s+(?:episode|incident|memory)|edge\s+of\s+it"
    r")\b",
    re.IGNORECASE,
)


def _standing_live_across_session_line_competes_with_hybrid_memory(line: Any) -> bool:
    return bool(ACROSS_SESSION_RETRIEVAL_META_RE.search(clean_text(line, max_chars=700)))


def standing_live_across_session_digest_demoted_for_hybrid_memory(envelope: Mapping[str, Any]) -> bool:
    cards = envelope.get("cards") if isinstance(envelope.get("cards"), Mapping) else {}
    visible = (
        envelope.get("card_summary", {}).get("provider_visible_cards", [])
        if isinstance(envelope.get("card_summary"), Mapping)
        else []
    )
    standing_live_vault = (
        cards.get("standing_live_vault_context_card")
        if isinstance(cards.get("standing_live_vault_context_card"), Mapping)
        else {}
    )
    if (
        "standing_live_vault_context_card" not in visible
        or not _standing_live_vault_has_hybrid_related_memory(standing_live_vault)
        or "across_session_continuity_card" not in visible
    ):
        return False
    across_session = (
        cards.get("across_session_continuity_card")
        if isinstance(cards.get("across_session_continuity_card"), Mapping)
        else {}
    )
    selected = across_session.get("selected_items") if isinstance(across_session.get("selected_items"), list) else []
    for item in selected:
        if not isinstance(item, Mapping):
            continue
        for line in str(item.get("summary") or "").splitlines():
            if _standing_live_across_session_line_competes_with_hybrid_memory(line):
                return True
    return False


def _standing_live_vault_label_list(value: Any, *, max_items: int = 8) -> list[str]:
    if isinstance(value, (str, bytes, bytearray)):
        source = str(value or "").split(";")
    elif isinstance(value, Sequence):
        source = list(value)
    else:
        source = []
    labels: list[str] = []
    for item in source:
        label = clean_text(item, max_chars=80).casefold()
        label = re.sub(r"[^a-z0-9_. -]+", "", label).strip(" ._-")
        if not label or label in labels:
            continue
        labels.append(label)
        if len(labels) >= max_items:
            break
    return labels


def _standing_live_vault_event_detail_item(item: Mapping[str, Any]) -> dict[str, Any]:
    if not _standing_live_vault_item_is_hybrid_related_memory(item):
        return {}
    detail = {
        "event_label": clean_text(item.get("event_label") or item.get("event_title"), max_chars=160),
        "episode_summary": clean_text(item.get("episode_summary"), max_chars=520),
        "episode_narrative_summary": clean_text(item.get("episode_narrative_summary"), max_chars=700),
        "actor_roles": [
            clean_text(value, max_chars=160)
            for value in list(item.get("actor_roles") or [])[:6]
            if clean_text(value, max_chars=160)
        ],
        "cause_effect_sequence": [
            clean_text(value, max_chars=160)
            for value in list(item.get("cause_effect_sequence") or [])[:8]
            if clean_text(value, max_chars=160)
        ],
        "outcome": clean_text(item.get("outcome"), max_chars=180),
        "memorable_or_emotional_note": clean_text(item.get("memorable_or_emotional_note"), max_chars=220),
        "ambiguity_note": clean_text(item.get("ambiguity_note"), max_chars=180),
        "participant_labels": _standing_live_vault_label_list(item.get("participant_labels"), max_items=6),
        "entity_labels": _standing_live_vault_label_list(item.get("entity_labels"), max_items=8),
        "scene_action_cues": _standing_live_vault_label_list(
            [
                *(
                    item.get("scene_action_sequence")
                    if isinstance(item.get("scene_action_sequence"), Sequence)
                    and not isinstance(item.get("scene_action_sequence"), (str, bytes, bytearray))
                    else [item.get("scene_action_sequence")]
                    if item.get("scene_action_sequence")
                    else []
                ),
                *(
                    item.get("scene_action_cues")
                    if isinstance(item.get("scene_action_cues"), Sequence)
                    and not isinstance(item.get("scene_action_cues"), (str, bytes, bytearray))
                    else [item.get("scene_action_cues")]
                    if item.get("scene_action_cues")
                    else []
                ),
            ],
            max_items=8,
        ),
        "memorable_cues": _standing_live_vault_label_list(item.get("memorable_cues"), max_items=8),
        "coherent_detail_phrases": _standing_live_hybrid_phrase_labels(
            _standing_live_vault_label_list(item.get("coherent_detail_phrases"), max_items=8),
            max_items=6,
        ),
        "coherent_detail_phrase_count": safe_int(item.get("coherent_detail_phrase_count") or 0),
        "time_context_cue": clean_text(item.get("time_context_cue"), max_chars=120),
        "why_matched_query": clean_text(item.get("why_matched_query"), max_chars=180),
        "concrete_detail_family_count": safe_int(item.get("concrete_detail_family_count")),
        "source_window_concrete_detail_family_count": safe_int(
            item.get("source_window_concrete_detail_family_count") or 0
        ),
        "actor_role_present": bool(item.get("actor_role_present")),
        "sequence_cause_effect_present": bool(item.get("sequence_cause_effect_present")),
        "outcome_present": bool(item.get("outcome_present")),
        "memorable_note_present": bool(item.get("memorable_note_present")),
        "confirmation_question_unneeded": bool(item.get("confirmation_question_unneeded")),
        "event_detail_level": clean_text(item.get("event_detail_level"), max_chars=80),
        "source_detail_hash": clean_text(item.get("source_detail_hash"), max_chars=80),
        "source_ref_hash": clean_text(item.get("source_ref_hash"), max_chars=80),
        "unit_hash": clean_text(item.get("unit_hash"), max_chars=80),
        "confidence": clean_text(item.get("confidence"), max_chars=80),
        "source_clarity": clean_text(item.get("source_clarity"), max_chars=160),
        "uncertainty": clean_text(item.get("uncertainty"), max_chars=160),
        "audience_label": clean_text(item.get("audience_label"), max_chars=120),
        "audience_scope": clean_text(item.get("audience_scope"), max_chars=80),
        "participant_scope": clean_text(item.get("participant_scope"), max_chars=80),
    }
    if not any(
        detail.get(key)
        for key in (
            "event_label",
            "episode_summary",
            "episode_narrative_summary",
            "actor_roles",
            "cause_effect_sequence",
            "outcome",
            "memorable_or_emotional_note",
            "participant_labels",
            "entity_labels",
            "scene_action_cues",
            "memorable_cues",
            "coherent_detail_phrases",
            "time_context_cue",
            "why_matched_query",
        )
    ):
        return {}
    assert_no_forbidden_payload(detail, path="standing_live_vault_event_detail")
    return detail


def _natural_label_join(labels: Sequence[str]) -> str:
    clean_labels = [clean_text(label, max_chars=80) for label in labels if clean_text(label, max_chars=80)]
    if not clean_labels:
        return ""
    if len(clean_labels) == 1:
        return clean_labels[0]
    if len(clean_labels) == 2:
        return f"{clean_labels[0]} and {clean_labels[1]}"
    return f"{', '.join(clean_labels[:-1])}, and {clean_labels[-1]}"


HYBRID_WEAK_STANDALONE_CUE_TERMS = {
    "actually",
    "after",
    "coat",
    "cold",
    "doesn",
    "here",
    "just",
    "more",
    "really",
    "tasty",
    "today",
}
HYBRID_GENERIC_CUE_TERMS = {
    "about",
    "again",
    "college",
    "conversation",
    "event",
    "from",
    "incident",
    "important",
    "memory",
    "memorable",
    "past",
    "related",
    "remember",
    "remembered",
    "story",
    "thing",
}


def _standing_live_hybrid_word_tokens(value: str) -> list[str]:
    text = clean_text(value, max_chars=240).casefold().replace("_", " ")
    tokens: list[str] = []
    for token in re.findall(r"[a-z][a-z0-9-]{2,}", text):
        clean = re.sub(r"[^a-z0-9-]+", "", token).strip("-")
        if clean:
            tokens.append(clean)
    return tokens


def _standing_live_hybrid_weak_label(value: str) -> bool:
    tokens = _standing_live_hybrid_word_tokens(value)
    return len(tokens) == 1 and tokens[0] in HYBRID_WEAK_STANDALONE_CUE_TERMS


def _standing_live_hybrid_token_bag_label(value: str) -> bool:
    tokens = _standing_live_hybrid_word_tokens(value)
    if len(tokens) < 4:
        return False
    weak_count = sum(
        1
        for token in tokens
        if token in HYBRID_WEAK_STANDALONE_CUE_TERMS or token in HYBRID_GENERIC_CUE_TERMS
    )
    distinctive_count = len(tokens) - weak_count
    return weak_count >= 2 and distinctive_count < 3


def _standing_live_hybrid_detail_labels(labels: Sequence[str], *, max_items: int = 8) -> list[str]:
    output: list[str] = []
    for label in labels:
        clean = clean_text(label, max_chars=120)
        if not clean or clean in output:
            continue
        if _standing_live_hybrid_weak_label(clean) or _standing_live_hybrid_token_bag_label(clean):
            continue
        output.append(clean)
        if len(output) >= max_items:
            break
    return output


def _standing_live_hybrid_phrase_labels(labels: Sequence[str], *, max_items: int = 6) -> list[str]:
    output: list[str] = []
    for label in _standing_live_hybrid_detail_labels(labels, max_items=max_items * 2):
        if len(_standing_live_hybrid_word_tokens(label)) < 2:
            continue
        if label not in output:
            output.append(label)
        if len(output) >= max_items:
            break
    return output


def _standing_live_labels_contain(labels: Sequence[str], terms: Sequence[str]) -> bool:
    text = " ".join(clean_text(label, max_chars=80) for label in labels).casefold()
    return any(term in text for term in terms)


def _standing_live_vault_concrete_family_count(event_detail: Mapping[str, Any]) -> int:
    return max(
        safe_int(event_detail.get("concrete_detail_family_count")),
        safe_int(event_detail.get("source_window_concrete_detail_family_count")),
    )


def _standing_live_hybrid_rich_episode_sentence(
    *,
    event_label: str,
    entity_labels: Sequence[str],
    scene_action_cues: Sequence[str],
    memorable_cues: Sequence[str],
    time_context_cue: str,
) -> str:
    labels = [*entity_labels, *scene_action_cues]
    has_scooter = _standing_live_labels_contain(labels, ("scooter", "bike", "moped", "e-bike", "ebike"))
    has_traffic = _standing_live_labels_contain(labels, ("traffic", "light", "stoplight", "intersection", "crossing"))
    has_braking = _standing_live_labels_contain(labels, ("brak", "stop", "stopping"))
    has_collision = _standing_live_labels_contain(labels, ("collision", "collid", "crash", "accident", "bump", "hit"))
    has_auntie = _standing_live_labels_contain(
        labels,
        ("auntie", "aunty", "ayi", "older woman", "older lady", "elderly woman", "elderly lady"),
    )
    has_apology = _standing_live_labels_contain(labels, ("apology", "apolog", "sorry"))

    if has_scooter:
        scene_subject = "a scooter/bike incident"
    elif event_label:
        scene_subject = event_label
    else:
        scene_subject = "a remembered past incident"

    time_text = clean_text(time_context_cue, max_chars=120).casefold()
    time_intro = "In college, " if "college" in time_text or "college" in event_label.casefold() else ""
    first_sentence = f"{time_intro}Astel had {scene_subject}"
    if has_traffic:
        first_sentence = f"{first_sentence} near traffic lights"
    first_sentence = f"{first_sentence}."

    scene_parts: list[str] = []
    if has_braking:
        scene_parts.append("a braking moment")
    if has_auntie:
        scene_parts.append("an older woman/auntie")
    if has_collision:
        scene_parts.append("a collision or near-collision")
    if has_apology:
        scene_parts.append("an apology afterward")
    for label in scene_action_cues:
        clean = clean_text(label, max_chars=80)
        if not clean or _standing_live_labels_contain([clean], ("scooter", "bike", "traffic", "light", "brak", "stop", "collid", "collision", "crash", "accident", "bump", "hit", "auntie", "aunty", "ayi", "woman", "lady", "apolog", "sorry")):
            continue
        if clean not in scene_parts:
            scene_parts.append(clean)
        if len(scene_parts) >= 6:
            break
    if scene_parts:
        second_sentence = f"The remembered scene has {_natural_label_join(scene_parts)}."
    else:
        second_sentence = ""

    memorable_parts: list[str] = []
    generic_memorable = {"important", "memorable", "memorable incident", "story", "funny"}
    for cue in memorable_cues:
        clean = clean_text(cue, max_chars=80)
        if not clean or clean.casefold() in generic_memorable:
            continue
        memorable_parts.append(clean)
        if len(memorable_parts) >= 3:
            break
    memorable_sentence = f"What stands out is {_natural_label_join(memorable_parts)}." if memorable_parts else ""
    source_sentence = "It comes from Chat History archive as a past conversation memory."
    return " ".join(
        sentence
        for sentence in (first_sentence, second_sentence, memorable_sentence, source_sentence)
        if sentence
    )


def _standing_live_hybrid_concrete_anchor_sentence(event_detail: Mapping[str, Any]) -> str:
    event_label = clean_text(event_detail.get("event_label"), max_chars=160)
    coherent_detail_phrases = _standing_live_hybrid_phrase_labels(
        [
            clean_text(label, max_chars=120)
            for label in list(event_detail.get("coherent_detail_phrases") or [])[:8]
            if clean_text(label, max_chars=120)
        ],
        max_items=6,
    )
    entity_labels = [
        clean_text(label, max_chars=80)
        for label in list(event_detail.get("entity_labels") or [])[:8]
        if clean_text(label, max_chars=80)
    ]
    scene_action_cues = [
        clean_text(label, max_chars=80)
        for label in list(event_detail.get("scene_action_cues") or [])[:8]
        if clean_text(label, max_chars=80)
    ]
    memorable_cues = [
        clean_text(label, max_chars=80)
        for label in list(event_detail.get("memorable_cues") or [])[:6]
        if clean_text(label, max_chars=80)
    ]
    time_context_cue = clean_text(event_detail.get("time_context_cue"), max_chars=120)
    generic = {
        "important",
        "memorable",
        "memory",
        "past",
        "related",
        "story",
        "thing",
    }
    anchors: list[str] = []
    for value in [
        *coherent_detail_phrases,
        event_label,
        time_context_cue,
        *_standing_live_hybrid_detail_labels(entity_labels, max_items=8),
        *_standing_live_hybrid_detail_labels(scene_action_cues, max_items=8),
        *_standing_live_hybrid_detail_labels(memorable_cues, max_items=6),
    ]:
        anchor = clean_text(value, max_chars=80)
        if (
            not anchor
            or anchor.casefold() in generic
            or anchor in anchors
            or _standing_live_hybrid_weak_label(anchor)
            or _standing_live_hybrid_token_bag_label(anchor)
        ):
            continue
        anchors.append(anchor)
        if len(anchors) >= 4:
            break
    if len(anchors) < 2:
        return ""
    return f"Details attached to that past memory include {_natural_label_join(anchors)}."


def _standing_live_hybrid_memory_sentence(
    *,
    kind: str,
    summary: str,
    event_detail: Mapping[str, Any],
) -> str:
    event_label = clean_text(event_detail.get("event_label"), max_chars=160)
    coherent_detail_phrases = _standing_live_hybrid_phrase_labels(
        [
            clean_text(label, max_chars=120)
            for label in list(event_detail.get("coherent_detail_phrases") or [])[:8]
            if clean_text(label, max_chars=120)
        ],
        max_items=6,
    )
    participant_labels = [
        clean_text(label, max_chars=80)
        for label in list(event_detail.get("participant_labels") or [])[:6]
        if clean_text(label, max_chars=80)
    ]
    entity_labels = _standing_live_hybrid_detail_labels(
        [
            clean_text(label, max_chars=80)
            for label in list(event_detail.get("entity_labels") or [])[:8]
            if clean_text(label, max_chars=80)
        ],
        max_items=8,
    )
    scene_action_cues = _standing_live_hybrid_detail_labels(
        [
            clean_text(label, max_chars=80)
            for label in list(event_detail.get("scene_action_cues") or [])[:10]
            if clean_text(label, max_chars=80)
        ],
        max_items=10,
    )
    memorable_cues = _standing_live_hybrid_detail_labels(
        [
            clean_text(label, max_chars=80)
            for label in list(event_detail.get("memorable_cues") or [])[:6]
            if clean_text(label, max_chars=80)
        ],
        max_items=6,
    )
    episode_summary = clean_text(event_detail.get("episode_summary"), max_chars=520)
    episode_narrative_summary = clean_text(event_detail.get("episode_narrative_summary"), max_chars=700)
    ambiguity_note = clean_text(event_detail.get("ambiguity_note"), max_chars=180)
    why_matched_query = clean_text(event_detail.get("why_matched_query"), max_chars=180)
    time_context_cue = clean_text(event_detail.get("time_context_cue"), max_chars=120)
    people_entities = _natural_label_join([*participant_labels, *entity_labels])
    concrete_family_count = _standing_live_vault_concrete_family_count(event_detail)
    confidence = clean_text(event_detail.get("confidence"), max_chars=80).casefold()
    anchor_sentence = _standing_live_hybrid_concrete_anchor_sentence(event_detail)
    narrative_ready = bool(
        episode_narrative_summary
        and event_detail.get("actor_role_present")
        and event_detail.get("sequence_cause_effect_present")
        and event_detail.get("memorable_note_present")
    )
    if narrative_ready and (concrete_family_count >= 5 or scene_action_cues or event_label):
        narrative_parts = [episode_narrative_summary]
        if anchor_sentence and anchor_sentence not in episode_narrative_summary:
            narrative_parts.append(anchor_sentence)
        if ambiguity_note:
            narrative_parts.append(ambiguity_note)
        narrative_parts.append("It comes from Chat History archive as a past conversation memory.")
        prefix = "Partial memory surfaced from our history" if kind == "partial_memory_card" else "Memory surfaced from our history"
        return f"{prefix}: " + " ".join(narrative_parts)
    if kind != "partial_memory_card" and confidence != "low" and concrete_family_count >= 5:
        if (
            episode_narrative_summary
            and event_detail.get("actor_role_present")
            and event_detail.get("sequence_cause_effect_present")
            and event_detail.get("outcome_present")
            and event_detail.get("memorable_note_present")
        ):
            narrative_parts = [episode_narrative_summary]
            if anchor_sentence and anchor_sentence not in episode_narrative_summary:
                narrative_parts.append(anchor_sentence)
            if ambiguity_note:
                narrative_parts.append(ambiguity_note)
            narrative_parts.append("It comes from Chat History archive as a past conversation memory.")
            return "Memory surfaced from our history: " + " ".join(narrative_parts)
        rich_episode = _standing_live_hybrid_rich_episode_sentence(
            event_label=event_label,
            entity_labels=entity_labels,
            scene_action_cues=scene_action_cues,
            memorable_cues=memorable_cues,
            time_context_cue=time_context_cue,
        )
        if rich_episode:
            return f"Memory surfaced from our history: {rich_episode}"
    safe_event_label = "" if _standing_live_hybrid_token_bag_label(event_label) else event_label
    base = episode_summary or safe_event_label or clean_text(summary, max_chars=360) or "a past conversation memory"
    if safe_event_label and episode_summary and safe_event_label.casefold() not in episode_summary.casefold():
        base = f"{safe_event_label}: {base}"
    if people_entities and people_entities.casefold() not in base.casefold():
        base = f"{base} involving {people_entities}"
    clauses = [base]
    if coherent_detail_phrases:
        clauses.append(f"source-backed details include {_natural_label_join(coherent_detail_phrases[:4])}")
    elif scene_action_cues:
        clauses.append(f"the remembered sequence includes {_natural_label_join(scene_action_cues)}")
    if memorable_cues and not coherent_detail_phrases:
        clauses.append(f"what made it memorable includes {_natural_label_join(memorable_cues)}")
    if time_context_cue and not _standing_live_hybrid_weak_label(time_context_cue):
        clauses.append(f"the time context is {time_context_cue}")
    if why_matched_query:
        clauses.append(f"it surfaced here because {why_matched_query}")
    if anchor_sentence:
        clauses.append(anchor_sentence.rstrip("."))
    clauses.append("this comes from Chat History archive as a past conversation memory")
    prefix = "Partial memory surfaced from our history" if kind == "partial_memory_card" else "Memory surfaced from our history"
    return f"{prefix}: {'; '.join(clauses)}."


def _standing_live_vault_audience_footing(item: Mapping[str, Any], *, path: str) -> dict[str, str]:
    if not _standing_live_vault_item_is_hybrid_related_memory(item):
        return normalize_audience_footing(item, path=path)
    footing_source = {
        "memory_audience_scope": item.get("memory_audience_scope") or item.get("audience_scope"),
        "room_audience_context": item.get("room_audience_context") or item.get("audience_context"),
        "audience_expression_guidance": item.get("audience_expression_guidance"),
    }
    return normalize_audience_footing(footing_source, path=path)


def _sha256_text(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _standing_live_vault_event_context_item(item: Mapping[str, Any]) -> dict[str, Any]:
    context = item.get("event_context") if isinstance(item.get("event_context"), Mapping) else {}
    if not context or not _standing_live_vault_item_is_direct_exact_evidence(item):
        return {}
    _assert_no_standing_live_vault_forbidden_fields(context, path="standing_live_vault_event_context")
    assert_no_forbidden_payload(context, path="standing_live_vault_event_context")

    summary = clean_text(context.get("summary"), max_chars=1000)
    if not summary:
        return {}
    source_ref = clean_text(item.get("source_ref") or item.get("source_pointer"), max_chars=260)
    segment_ref = clean_text(item.get("segment_ref"), max_chars=240)
    message_ref = clean_text(item.get("message_ref"), max_chars=240)
    quote_sha256 = clean_text(item.get("quote_sha256"), max_chars=80)
    timestamp = clean_text(item.get("timestamp"), max_chars=80)
    order_index = safe_int(item.get("message_order_index"))

    linked_source_ref = clean_text(context.get("linked_source_ref") or context.get("source_ref"), max_chars=260)
    linked_segment_ref = clean_text(context.get("linked_segment_ref") or context.get("segment_ref"), max_chars=240)
    linked_message_ref = clean_text(context.get("linked_message_ref") or context.get("message_ref"), max_chars=240)
    linked_quote_sha256 = clean_text(context.get("linked_quote_sha256") or context.get("quote_sha256"), max_chars=80)
    linked_timestamp = clean_text(context.get("linked_timestamp") or context.get("timestamp"), max_chars=80)
    linked_order_index = safe_int(context.get("linked_message_order_index") or context.get("message_order_index"))

    if not source_ref or linked_source_ref != source_ref:
        return {}
    if message_ref and linked_message_ref != message_ref:
        return {}
    if quote_sha256 and linked_quote_sha256 != quote_sha256:
        return {}
    if timestamp and linked_timestamp and linked_timestamp != timestamp:
        return {}
    if order_index and linked_order_index and linked_order_index != order_index:
        return {}

    event_context = {
        "schema_version": STANDING_LIVE_EXACT_RECALL_EVENT_CONTEXT_SCHEMA_VERSION,
        "gate_id": STANDING_LIVE_EXACT_RECALL_EVENT_CONTEXT_GATE_ID,
        "state": clean_text(context.get("state") or "linked_event_context", max_chars=80),
        "summary": summary,
        "summary_sha256": clean_text(context.get("summary_sha256"), max_chars=80) or _sha256_text(summary),
        "summary_kind": clean_text(context.get("summary_kind") or "event_context", max_chars=120),
        "source_class": clean_text(context.get("source_class") or "chat_history_exact_recall_event_context", max_chars=120),
        "linked_source_ref": linked_source_ref,
        "linked_segment_ref": linked_segment_ref or segment_ref,
        "linked_message_ref": linked_message_ref,
        "linked_quote_sha256": linked_quote_sha256,
        "linked_timestamp": linked_timestamp or timestamp,
        "linked_message_order_index": linked_order_index or order_index,
        "window_message_count": safe_int(context.get("window_message_count")),
        "before_selected_count": safe_int(context.get("before_selected_count")),
        "after_selected_count": safe_int(context.get("after_selected_count")),
        "linked_to_selected_exact_recall": True,
        "context_is_exact_evidence": False,
        "provider_generated": False,
        "helper_generated": bool(context.get("helper_generated")),
        "raw_access": False,
    }
    assert_no_forbidden_payload(event_context, path="standing_live_vault_event_context.normalized")
    return event_context


def build_standing_live_vault_context_card(
    vault_cards: list[Mapping[str, Any]] | None = None,
    *,
    max_selected: int = 1,
    status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_cards = vault_cards if isinstance(vault_cards, list) else []
    selected_limit = max(0, min(max_selected, 1))
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for index, item in enumerate(source_cards):
        if not isinstance(item, Mapping):
            skipped.append({"vault_card_id": f"standing_live_vault_{index}", "reason": "malformed_card"})
            continue
        _assert_no_standing_live_vault_forbidden_fields(item, path=f"standing_live_vault_cards[{index}]")
        assert_no_forbidden_payload(item, path=f"standing_live_vault_cards[{index}]")
        vault_card_id = clean_text(
            item.get("card_id")
            or item.get("memory_id")
            or item.get("source_summary_id")
            or item.get("curator_record_id")
            or item.get("message_ref")
            or f"standing_live_vault_{index}",
            max_chars=180,
        )
        kind = clean_text(item.get("kind"), max_chars=120)
        source_class = clean_text(item.get("source_class") or "vault_card", max_chars=120)
        if kind not in STANDING_LIVE_VAULT_CARD_ALLOWED_KINDS:
            skipped.append({"vault_card_id": vault_card_id, "reason": "unsupported_card_kind"})
            continue
        if item.get("provider_visible_eligible") is False:
            skipped.append({"vault_card_id": vault_card_id, "reason": "provider_visible_not_eligible"})
            continue
        if bool(item.get("raw_access")):
            skipped.append({"vault_card_id": vault_card_id, "reason": "raw_access_not_allowed"})
            continue
        if bool(item.get("provider_generated")):
            skipped.append({"vault_card_id": vault_card_id, "reason": "provider_generated_not_allowed"})
            continue
        summary = clean_text(item.get("summary"), max_chars=1000)
        source_ref = clean_text(item.get("source_ref") or item.get("source_pointer"), max_chars=260)
        if not summary:
            skipped.append({"vault_card_id": vault_card_id, "reason": "missing_summary"})
            continue
        if not source_ref:
            skipped.append({"vault_card_id": vault_card_id, "reason": "missing_source_ref"})
            continue
        if len(selected) >= selected_limit:
            skipped.append({"vault_card_id": vault_card_id, "reason": "standing_live_vault_card_limit_reached"})
            continue
        bounded_quote = ""
        timestamp = ""
        date = ""
        if kind == "chat_history_bounded_excerpt_card":
            bounded_quote = clean_visible_exact_quote(item.get("bounded_quote"), max_chars=500)
            timestamp = clean_text(item.get("timestamp"), max_chars=80)
            date = clean_text(item.get("date"), max_chars=40)
            if not bounded_quote:
                skipped.append({"vault_card_id": vault_card_id, "reason": "missing_bounded_quote"})
                continue
            if not timestamp or not date:
                skipped.append({"vault_card_id": vault_card_id, "reason": "missing_timestamp_or_date"})
                continue
        event_context = _standing_live_vault_event_context_item(item)
        event_detail = _standing_live_vault_event_detail_item(item)
        selected.append(
            {
                "vault_card_id": vault_card_id,
                "kind": kind,
                "source_class": source_class,
                "source_ref": source_ref,
                "summary": summary,
                "summary_sha256": clean_text(item.get("summary_sha256"), max_chars=80),
                "reason_attached": clean_text(
                    item.get("reason_attached")
                    or item.get("why_attached")
                    or (
                        "source-backed related memory"
                        if _standing_live_vault_item_is_hybrid_related_memory(item)
                        else ""
                    )
                    or "standing_live_one_card_vault_retrieval",
                    max_chars=180,
                ),
                "freshness": clean_text(item.get("freshness") or "durable_reviewed", max_chars=80),
                "activation_tier": clean_text(item.get("activation_tier") or "evidence_only", max_chars=80),
                "supersession_state": clean_text(item.get("supersession_state") or "active", max_chars=80),
                "supersession_key": clean_text(item.get("supersession_key") or "", max_chars=180),
                "review_state": clean_text(item.get("review_state") or "reviewed", max_chars=80),
                "sensitivity": clean_text(item.get("sensitivity") or "normal", max_chars=80),
                "score": safe_float(item.get("score")),
                "timestamp": timestamp,
                "date": date,
                "bounded_quote": bounded_quote,
                "quote_sha256": clean_text(item.get("quote_sha256"), max_chars=80),
                "speaker": clean_text(item.get("speaker"), max_chars=40),
                "message_ref": clean_text(item.get("message_ref"), max_chars=240),
                "segment_ref": clean_text(item.get("segment_ref"), max_chars=240),
                "message_order_index": safe_int(item.get("message_order_index")),
                "source_ref_hash": clean_text(item.get("source_ref_hash"), max_chars=80),
                "unit_hash": clean_text(item.get("unit_hash"), max_chars=80),
                "source_detail_hash": clean_text(item.get("source_detail_hash"), max_chars=80),
                "confidence": clean_text(item.get("confidence"), max_chars=80),
                "source_clarity": clean_text(item.get("source_clarity"), max_chars=160),
                "uncertainty": clean_text(item.get("uncertainty"), max_chars=160),
                "audience_label": clean_text(item.get("audience_label"), max_chars=120),
                "participant_scope": clean_text(item.get("participant_scope"), max_chars=80),
                **({"event_detail": event_detail} if event_detail else {}),
                **({"event_context": event_context} if event_context else {}),
                **_standing_live_vault_audience_footing(item, path=f"standing_live_vault_cards[{index}]"),
            }
        )
    status_item = {} if selected else _standing_live_vault_status_item(status)
    visible = bool(selected) or bool(status_item)
    card = {
        "availability": availability(
            status="available" if visible else "skipped",
            source_kind="standing_live_vault_retrieval_v0",
            source_id="standing_live_vault_context_card_v0",
            freshness="current_turn",
            visible_to_model=visible,
            diagnostics_only=not visible,
            reason="No standing-live vault card selected." if not visible else "",
        ),
        "mode": "one_reviewed_vault_card" if selected else "exact_recall_status" if status_item else "none",
        "raw_access": False,
        "provider_visible": visible,
        "provider_generated": False,
        "selected_items": selected,
        "status_item": status_item,
        "skipped_items": skipped,
        "budget": {
            "default_max_items": 1,
            "hard_max_items": 1,
            "selected_limit": selected_limit,
            "selected_count": len(selected),
            "status_count": 1 if status_item else 0,
            "used_chars": sum(
                len(item["summary"])
                + len(item.get("bounded_quote") or "")
                + len((item.get("event_context") or {}).get("summary") or "")
                for item in selected
            ),
        },
        "diagnostics": {
            "candidate_count": len(source_cards),
            "selected_count": len(selected),
            "status_count": 1 if status_item else 0,
            "event_context_count": sum(1 for item in selected if isinstance(item.get("event_context"), Mapping)),
            "skipped_count": len(skipped),
            "raw_access": False,
            "provider_generated": False,
        },
        "curator_version": "api_talk_standing_live_vault_context_card_v0",
    }
    assert_no_forbidden_payload(card, path="standing_live_vault_context_card")
    return card


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def score_memory_candidate(candidate: Mapping[str, Any]) -> float:
    return round(
        safe_float(candidate.get("current_turn_hint")) * 3.0
        + safe_float(candidate.get("semantic_score")) * 2.0
        + safe_float(candidate.get("keyword_score")) * 1.5
        + safe_float(candidate.get("importance")) * 1.2
        + safe_float(candidate.get("recency")) * 0.8
        + safe_float(candidate.get("confidence")) * 1.5,
        4,
    )


def _memory_candidate_allowed(candidate: Mapping[str, Any]) -> tuple[bool, str]:
    if candidate.get("provider_visible_eligible") is False:
        return False, "provider_visible_not_eligible"
    if candidate.get("source_class") in {"raw_vault", "raw_chat_history", "provider_body", "secret_material"}:
        return False, "source_class_blocked"
    if candidate.get("proactive_source_class") and not candidate.get("proactive_source_enabled"):
        return False, "proactive_source_disabled_by_default"
    if candidate.get("review_state") in {"rejected", "needs_review"}:
        return False, "review_state_not_provider_visible"
    if candidate.get("conflict_state") == "conflicted":
        return False, "conflicted_candidate"
    summary = clean_text(candidate.get("summary"), max_chars=1600)
    if not summary:
        return False, "missing_summary"
    return True, "eligible"


def build_memory_context_card(
    candidates: list[Mapping[str, Any]] | None = None,
    *,
    max_selected: int = 3,
    hard_max_selected: int = 5,
    embedding_available: bool = True,
    cache_state: str = "not_used",
) -> dict[str, Any]:
    source_candidates = candidates if isinstance(candidates, list) else []
    selected_limit = max(0, min(max_selected, hard_max_selected, 5))
    scored: list[dict[str, Any]] = []
    blocked: list[dict[str, str]] = []
    for index, candidate in enumerate(source_candidates):
        assert_no_forbidden_payload(candidate, path=f"memory_candidates[{index}]")
        allowed, reason = _memory_candidate_allowed(candidate)
        safe_id = clean_text(candidate.get("memory_id") or f"candidate_{index}", max_chars=160)
        if not allowed:
            blocked.append({"memory_id": safe_id, "reason": reason})
            continue
        score = score_memory_candidate(candidate)
        scored.append(
            {
                "memory_id": safe_id,
                "source_class": clean_text(candidate.get("source_class") or "memory_summary", max_chars=120),
                "source_ref": clean_text(candidate.get("source_ref"), max_chars=240),
                "summary": clean_text(candidate.get("summary"), max_chars=1200),
                "reason_attached": clean_text(candidate.get("reason_attached") or "deterministic_score", max_chars=240),
                "freshness": clean_text(candidate.get("freshness") or "unknown", max_chars=80),
                "confidence": safe_float(candidate.get("confidence")),
                "review_state": clean_text(candidate.get("review_state") or "accepted", max_chars=80),
                "stale": bool(candidate.get("stale")),
                "conflict_state": clean_text(candidate.get("conflict_state") or "none", max_chars=80),
                "score": score,
            }
        )
    selected = sorted(scored, key=lambda item: (-item["score"], item["memory_id"]))[:selected_limit]
    retrieval_strategy = "semantic_plus_keyword" if embedding_available else "keyword_tag_fallback"
    status = "available" if selected else "skipped"
    return {
        "availability": availability(
            status=status,
            source_kind="memory_curator_retrieval_v0",
            source_id="api_talk_memory_context_v0",
            freshness="current_turn",
            visible_to_model=bool(selected),
            diagnostics_only=not bool(selected),
            reason="No selected memory summaries." if not selected else "",
        ),
        "mode": "ordinary_retrieval" if selected else "none",
        "raw_access": False,
        "provider_visible": bool(selected),
        "selected_items": selected,
        "excluded_candidates": blocked,
        "budget": {
            "default_max_items": 3,
            "hard_max_items": 5,
            "selected_limit": selected_limit,
            "selected_count": len(selected),
            "used_chars": sum(len(item["summary"]) for item in selected),
        },
        "diagnostics": {
            "candidate_count": len(source_candidates),
            "eligible_count": len(scored),
            "blocked_count": len(blocked),
            "selected_count": len(selected),
            "retrieval_strategy": retrieval_strategy,
            "cache_state": clean_text(cache_state, max_chars=80),
            "full_vault_scan": False,
        },
        "curator_version": "api_talk_memory_context_card_v0",
    }


READ_MODE_SOURCE_CONTEXT_FORBIDDEN_FIELDS = {
    "raw_text",
    "raw_body",
    "raw_source_body",
    "source_body",
    "full_text",
    "quote_chunks",
    "transcript_raw",
    "provider_request_body",
    "provider_response_body",
}


READ_MODE_EXACT_TEXT_ATTACHMENT_SCHEMA_VERSION = "house_read_mode_exact_text_attachment_v0"
READ_MODE_EXACT_SOURCE_DOMAIN = "read_mode_exact_text_utf8_v1"
READ_MODE_EXACT_SOURCE_CANONICALIZATION_VERSION = "utf8_no_normalization_v1"
READ_MODE_EXACT_SOURCE_ELIGIBILITY_POLICY = (
    "api_talk_read_mode_exact_text_provider_eligibility_v1"
)


def derive_read_mode_exact_text_evidence(exact_text: str) -> dict[str, Any]:
    if not isinstance(exact_text, str) or not exact_text:
        raise ValueError("read_mode_exact_text_missing")
    assert_no_forbidden_payload(exact_text, path="read_mode_exact_text_evidence")
    source_identity = hashlib.sha256(exact_text.encode("utf-8")).hexdigest()
    eligibility_material = "\n".join(
        (
            READ_MODE_EXACT_SOURCE_ELIGIBILITY_POLICY,
            READ_MODE_EXACT_SOURCE_DOMAIN,
            READ_MODE_EXACT_SOURCE_CANONICALIZATION_VERSION,
            source_identity,
            "provider_visible_eligible=true",
        )
    ).encode("utf-8")
    return {
        "source_identity_sha256": source_identity,
        "source_representation_domain": READ_MODE_EXACT_SOURCE_DOMAIN,
        "source_canonicalization_version": (
            READ_MODE_EXACT_SOURCE_CANONICALIZATION_VERSION
        ),
        "provider_visible_eligible": True,
        "eligibility_policy": READ_MODE_EXACT_SOURCE_ELIGIBILITY_POLICY,
        "eligibility_receipt_sha256": hashlib.sha256(
            eligibility_material
        ).hexdigest(),
    }


def _assert_no_read_mode_source_body_fields(payload: Any, *, path: str = "read_mode_source_summary") -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key).strip().lower()
            if key_text in READ_MODE_SOURCE_CONTEXT_FORBIDDEN_FIELDS:
                raise ApiTalkEnvelopeError("forbidden_read_mode_source_field", f"Forbidden Read Mode source field at {path}.{key}.")
            _assert_no_read_mode_source_body_fields(value, path=f"{path}.{key}")
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            _assert_no_read_mode_source_body_fields(item, path=f"{path}[{index}]")


def _read_mode_targeted_excerpt_items(item: Mapping[str, Any], *, path: str) -> list[dict[str, Any]]:
    source = item.get("targeted_excerpts")
    if source is None:
        source = item.get("excerpts")
    source_items = source if isinstance(source, list) else []
    excerpts: list[dict[str, Any]] = []
    for index, excerpt in enumerate(source_items[:5]):
        if not isinstance(excerpt, Mapping):
            continue
        _assert_no_read_mode_source_body_fields(excerpt, path=f"{path}.targeted_excerpts[{index}]")
        assert_no_forbidden_payload(excerpt, path=f"{path}.targeted_excerpts[{index}]")
        excerpt_text = clean_text(excerpt.get("excerpt_text"), max_chars=900)
        if not excerpt_text:
            continue
        excerpts.append(
            {
                "excerpt_id": clean_text(excerpt.get("excerpt_id") or f"excerpt_{index + 1}", max_chars=180),
                "source_id": clean_text(excerpt.get("source_id"), max_chars=160),
                "line_start": safe_int(excerpt.get("line_start")),
                "line_end": safe_int(excerpt.get("line_end")),
                "excerpt_text": excerpt_text,
                "char_count": safe_int(excerpt.get("char_count") or len(excerpt_text)),
                "truncated": bool(excerpt.get("truncated")),
                "reason_selected": clean_text(excerpt.get("reason_selected") or "targeted_excerpt", max_chars=120),
            }
        )
    return excerpts


def build_read_mode_source_context_card(
    source_summaries: list[Mapping[str, Any]] | None = None,
    *,
    max_selected: int = 3,
) -> dict[str, Any]:
    source_items = source_summaries if isinstance(source_summaries, list) else []
    selected_limit = max(0, min(max_selected, 3))
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for index, item in enumerate(source_items):
        _assert_no_read_mode_source_body_fields(item, path=f"read_mode_source_summaries[{index}]")
        assert_no_forbidden_payload(item, path=f"read_mode_source_summaries[{index}]")
        source_id = clean_text(item.get("source_summary_id") or f"read_mode_source_{index}", max_chars=160)
        if item.get("schema_version") != "house_read_mode_source_summary_v0":
            skipped.append({"source_summary_id": source_id, "reason": "unsupported_source_summary_schema"})
            continue
        summary = clean_text(item.get("summary"), max_chars=1200)
        if not summary:
            skipped.append({"source_summary_id": source_id, "reason": "missing_summary"})
            continue
        if len(selected) >= selected_limit:
            skipped.append({"source_summary_id": source_id, "reason": "source_summary_limit_reached"})
            continue
        targeted_excerpts = _read_mode_targeted_excerpt_items(item, path=f"read_mode_source_summaries[{index}]")
        selected.append(
            {
                "source_summary_id": source_id,
                "source_label": clean_text(item.get("source_label") or "attached source", max_chars=180),
                "source_modality": clean_text(item.get("source_modality") or "source_summary", max_chars=80),
                "summary": summary,
                "targeted_excerpts": targeted_excerpts,
                "observations": [
                    clean_text(observation, max_chars=180)
                    for observation in list(item.get("observations") or [])[:5]
                ],
                "tags": [clean_text(tag, max_chars=80) for tag in list(item.get("tags") or [])[:8]],
                "reason_attached": clean_text(
                    item.get("reason_attached")
                    or (
                        "explicit_source_vault_targeted_excerpt_attachment"
                        if targeted_excerpts
                        else "explicit_current_turn_read_mode_attachment"
                    ),
                    max_chars=160,
                ),
            }
        )
    targeted_excerpt_count = sum(
        len(item.get("targeted_excerpts") or [])
        for item in selected
        if isinstance(item.get("targeted_excerpts"), list)
    )
    card = {
        "availability": availability(
            status="available" if selected else "skipped",
            source_kind="read_mode_source_summary_v0",
            source_id="read_mode_source_context_card_v0",
            freshness="current_turn",
            visible_to_model=bool(selected),
            diagnostics_only=not bool(selected),
            reason="No Read Mode source summaries attached for this turn." if not selected else "",
        ),
        "mode": "explicit_current_turn_attachment" if selected else "none",
        "raw_access": False,
        "source_text_returned": bool(targeted_excerpt_count),
        "targeted_excerpt_count": targeted_excerpt_count,
        "provider_visible": bool(selected),
        "selected_items": selected,
        "skipped_items": skipped,
        "budget": {
            "default_max_items": 3,
            "hard_max_items": 3,
            "selected_limit": selected_limit,
            "selected_count": len(selected),
            "used_chars": sum(len(item["summary"]) for item in selected)
            + sum(
                len(excerpt.get("excerpt_text") or "")
                for item in selected
                for excerpt in list(item.get("targeted_excerpts") or [])
                if isinstance(excerpt, Mapping)
            ),
        },
        "diagnostics": {
            "candidate_count": len(source_items),
            "selected_count": len(selected),
            "skipped_count": len(skipped),
            "raw_access": False,
            "source_text_returned": bool(targeted_excerpt_count),
            "targeted_excerpt_count": targeted_excerpt_count,
        },
        "curator_version": "api_talk_read_mode_source_context_card_v0",
    }
    assert_no_forbidden_payload(card, path="read_mode_source_context_card")
    return card


def build_read_mode_exact_text_card(
    exact_text_attachments: list[Mapping[str, Any]] | None = None,
    *,
    max_selected: int = 1,
) -> dict[str, Any]:
    source_items = exact_text_attachments if isinstance(exact_text_attachments, list) else []
    selected_limit = max(0, min(max_selected, 1))
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for index, item in enumerate(source_items):
        assert_no_forbidden_payload(item, path=f"read_mode_exact_text_attachments[{index}]")
        source_id = clean_text(item.get("source_summary_id") or f"read_mode_exact_text_{index}", max_chars=160)
        if item.get("schema_version") != READ_MODE_EXACT_TEXT_ATTACHMENT_SCHEMA_VERSION:
            skipped.append({"source_summary_id": source_id, "reason": "unsupported_exact_text_schema"})
            continue
        exact_text = clean_exact_text(item.get("exact_text"), max_chars=6000)
        assert_no_forbidden_payload(exact_text, path=f"read_mode_exact_text_attachments[{index}].exact_text")
        if not exact_text:
            skipped.append({"source_summary_id": source_id, "reason": "missing_exact_text"})
            continue
        if len(selected) >= selected_limit:
            skipped.append({"source_summary_id": source_id, "reason": "exact_text_limit_reached"})
            continue
        evidence = derive_read_mode_exact_text_evidence(exact_text)
        selected.append(
            {
                "source_summary_id": source_id,
                "source_label": clean_text(item.get("source_label") or "attached text source", max_chars=180),
                "source_modality": clean_text(item.get("source_modality") or "file_text_exact", max_chars=80),
                "exact_text": exact_text,
                "char_count": safe_int(item.get("char_count") or len(exact_text)),
                "line_count": safe_int(item.get("line_count")),
                "reason_attached": "explicit_small_text_read_mode_attachment",
                **evidence,
            }
        )
    card = {
        "availability": availability(
            status="available" if selected else "skipped",
            source_kind="read_mode_exact_text_attachment_v0",
            source_id="read_mode_exact_text_card_v0",
            freshness="current_turn",
            visible_to_model=bool(selected),
            diagnostics_only=not bool(selected),
            reason="No exact Read Mode text attached for this turn." if not selected else "",
        ),
        "mode": "explicit_small_text_attachment" if selected else "none",
        "source_text_returned": bool(selected),
        "provider_visible": bool(selected),
        "selected_items": selected,
        "skipped_items": skipped,
        "budget": {
            "default_max_items": 1,
            "hard_max_items": 1,
            "selected_limit": selected_limit,
            "selected_count": len(selected),
            "used_chars": sum(len(item["exact_text"]) for item in selected),
        },
        "diagnostics": {
            "candidate_count": len(source_items),
            "selected_count": len(selected),
            "skipped_count": len(skipped),
            "source_text_returned": bool(selected),
        },
        "curator_version": "api_talk_read_mode_exact_text_card_v0",
    }
    assert_no_forbidden_payload(card, path="read_mode_exact_text_card")
    return card


def build_status_time_card(status: Mapping[str, Any] | None = None) -> dict[str, Any]:
    source = status if isinstance(status, Mapping) else {}
    return {
        "availability": _visible_card("status_time_snapshot", source_id="status_time_v0"),
        "current_time": clean_text(source.get("current_time") or utc_timestamp(), max_chars=80),
        "timezone": clean_text(source.get("timezone") or "unknown", max_chars=80),
        "coarse_status": clean_text(source.get("coarse_status") or "available", max_chars=160),
    }


def build_reality_context_card(context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(context, Mapping):
        return {
            "availability": _skipped_card(
                "house_reality_context_profile_status_card_v0",
                "No standing-live Reality Context card was supplied for this turn.",
            ),
            "mode": "none",
            "provider_visible": False,
            "raw_access": False,
            "diagnostics": {
                "selected_count": 0,
                "raw_access": False,
                "provider_calls_made": False,
                "android_status_feed_connected": False,
                "self_state_included": False,
                "proactive_wake_send": False,
            },
        }
    assert_no_forbidden_payload(context, path="reality_context_card.input")
    local_time = context.get("local_time") if isinstance(context.get("local_time"), Mapping) else {}
    route_surface_room = (
        context.get("route_surface_room") if isinstance(context.get("route_surface_room"), Mapping) else {}
    )
    profile_refs = (
        context.get("profile_preference_refs")
        if isinstance(context.get("profile_preference_refs"), Mapping)
        else {}
    )
    android_status = context.get("android_status") if isinstance(context.get("android_status"), Mapping) else {}
    diagnostics = context.get("diagnostics") if isinstance(context.get("diagnostics"), Mapping) else {}
    provider_visible = bool(context.get("provider_visible"))
    provider_visible_hints = (
        context.get("provider_visible_hints")
        if isinstance(context.get("provider_visible_hints"), list)
        else []
    )
    card = {
        "availability": availability(
            status="available" if provider_visible else "skipped",
            source_kind="house_reality_context_profile_status_card_v0",
            source_id="reality_context_profile_status_card_v0",
            freshness="current_turn",
            visible_to_model=provider_visible,
            diagnostics_only=not provider_visible,
            reason="" if provider_visible else "Reality Context is diagnostics-only for this route.",
        ),
        "schema_version": clean_text(context.get("schema_version"), max_chars=120),
        "mode": clean_text(context.get("mode") or "standing_live_current_situation", max_chars=120),
        "provider_visible": provider_visible,
        "raw_access": False,
        "current_time_local": clean_text(local_time.get("current_time_local"), max_chars=80),
        "local_date": clean_text(local_time.get("local_date"), max_chars=40),
        "local_weekday": clean_text(local_time.get("local_weekday"), max_chars=40),
        "local_day_period": clean_text(local_time.get("local_day_period"), max_chars=80),
        "local_time_bucket": clean_text(local_time.get("local_time_bucket"), max_chars=80),
        "timezone": clean_text(local_time.get("timezone"), max_chars=80),
        "time_source": clean_text(local_time.get("time_source"), max_chars=120),
        "route_surface_room": {
            "source_route": clean_text(route_surface_room.get("source_route"), max_chars=160),
            "route_posture": clean_text(route_surface_room.get("route_posture"), max_chars=120),
            "surface": clean_text(route_surface_room.get("surface") or "Talk", max_chars=120),
            "room": clean_text(route_surface_room.get("room") or "Talk", max_chars=80),
            "house_thread_id_present": bool(route_surface_room.get("house_thread_id_present")),
        },
        "profile_preference_refs": {
            "mode": clean_text(profile_refs.get("mode") or "safe_counts_and_placeholders", max_chars=120),
            "astel_profile_summary_available": bool(profile_refs.get("astel_profile_summary_available")),
            "preference_ref_count": safe_int(profile_refs.get("preference_ref_count")),
            "profile_placeholder_count": safe_int(profile_refs.get("profile_placeholder_count")),
            "profile_bodies_included": False,
            "preference_bodies_included": False,
        },
        "android_status": {
            "mode": clean_text(android_status.get("mode") or "placeholder_only", max_chars=120),
            "feed_connected": False,
            "device_presence": clean_text(android_status.get("device_presence") or "unknown", max_chars=80),
            "battery_state": clean_text(android_status.get("battery_state") or "unknown", max_chars=80),
            "network_state": clean_text(android_status.get("network_state") or "unknown", max_chars=80),
            "status_body_included": False,
        },
        "provider_visible_hints": [
            clean_text(hint, max_chars=360)
            for hint in provider_visible_hints[:3]
            if clean_text(hint, max_chars=360)
        ] if provider_visible else [],
        "diagnostics": {
            "selected_count": safe_int(diagnostics.get("selected_count")) if provider_visible else 0,
            "raw_access": False,
            "provider_calls_made": False,
            "external_provider_calls_made": False,
            "memory_vault_read": False,
            "source_vault_read": False,
            "chat_history_read": False,
            "profile_body_included": False,
            "preference_body_included": False,
            "android_status_feed_connected": False,
            "self_state_included": False,
            "proactive_wake_send": False,
        },
        "policy_action": "reality_context_profile_status_card",
    }
    assert_no_forbidden_payload(card, path="reality_context_card")
    return card


def build_placeholder_card(card_name: str, reason: str, *, source_kind: str = "future_source") -> dict[str, Any]:
    return {
        "availability": _skipped_card(source_kind, reason),
        "card_name": clean_text(card_name, max_chars=120),
    }


def build_route_capability_card(
    active_provider_profile: Mapping[str, Any] | None = None,
    *,
    source_route: str,
) -> dict[str, Any]:
    profile = active_provider_profile if isinstance(active_provider_profile, Mapping) else {}
    return {
        "availability": availability(
            status="available",
            source_kind="gateway_route_policy",
            source_id="route_capability_v0",
            freshness="current_turn",
            visible_to_model=False,
            diagnostics_only=True,
            reason="Route/capability facts are diagnostics-only in renderer v0.1.",
        ),
        "source_route": clean_text(source_route, max_chars=120),
        "provider_label": clean_text(profile.get("provider_label") or "openai_compatible", max_chars=120),
        "profile_id": clean_text(profile.get("profile_id") or "kouri_gpt_5_1_chat_completions", max_chars=160),
        "endpoint_family": clean_text(profile.get("endpoint_family") or "chat_completions", max_chars=120),
        "model_id": clean_text(profile.get("model_name") or "gpt-5.1", max_chars=160),
        "tool_mode": "none",
        "memory_write_allowed": False,
        "provider_archive_processing_allowed": False,
        "codex_hand_execution_allowed": False,
        "normal_action_permissions": False,
    }


def build_adult_authentication_card(summary: str | None = None, *, attach: bool = False) -> dict[str, Any]:
    if not attach:
        return {
            "availability": _skipped_card(
                "relationship_context_summary",
                "Adult/relationship context was not needed or not attached for this turn.",
            ),
            "provider_visible": False,
            "summary": "",
        }
    text = clean_text(summary, max_chars=600)
    if not text:
        raise ApiTalkEnvelopeError("missing_adult_context_summary", "Adult context summary is required when attached.")
    assert_no_forbidden_payload(text, path="adult_authentication_card.summary")
    return {
        "availability": _visible_card("relationship_context_summary", source_id="adult_authentication_v0"),
        "provider_visible": True,
        "summary": text,
    }


def build_codex_hand_result_card(result_card: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(result_card, Mapping):
        return {
            "availability": _skipped_card("codex_hand_result", "No Codex hand result card was provided."),
            "card_name": "codex_hand_result_card",
            "attached": False,
        }
    safe_summary = clean_text(result_card.get("safe_summary"), max_chars=1200)
    if safe_summary:
        assert_no_forbidden_payload(safe_summary, path="codex_hand_result_card.safe_summary")
    return {
        "availability": availability(
            status="available",
            source_kind="codex_hand_result",
            source_id=clean_text(result_card.get("job_id") or "unknown_job", max_chars=160),
            freshness="current_turn",
            visible_to_model=False,
            diagnostics_only=True,
            reason="Codex hand result cards are diagnostics-only until API Talk result attachment policy is promoted.",
        ),
        "card_name": "codex_hand_result_card",
        "attached": True,
        "source_schema_version": clean_text(result_card.get("schema_version"), max_chars=120),
        "card_type": clean_text(result_card.get("card_type"), max_chars=120),
        "job_id": clean_text(result_card.get("job_id"), max_chars=160),
        "request_id": clean_text(result_card.get("request_id"), max_chars=160),
        "house_thread_id": clean_text(result_card.get("house_thread_id"), max_chars=160),
        "state": clean_text(result_card.get("state"), max_chars=80),
        "safe_summary": safe_summary,
        "files_inspected": [
            {
                "relative_path": clean_text(item.get("relative_path"), max_chars=240),
                "metadata_only": bool(item.get("metadata_only")),
            }
            for item in list(result_card.get("files_inspected") or [])[:20]
            if isinstance(item, Mapping)
        ],
        "changes_proposed": [clean_text(item, max_chars=240) for item in list(result_card.get("changes_proposed") or [])[:20]],
        "changes_applied": False,
        "checks_run": [clean_text(item, max_chars=240) for item in list(result_card.get("checks_run") or [])[:20]],
        "safe_error_class": clean_text(result_card.get("safe_error_class"), max_chars=120),
        "runner_id": clean_text(result_card.get("runner_id"), max_chars=160),
        "executor_location": clean_text(result_card.get("executor_location"), max_chars=80),
        "executor_family": clean_text(result_card.get("executor_family"), max_chars=120),
        "provider_visible": False,
        "diagnostics_visible": True,
        "provider_calls_made": False,
        "codex_invocation_made": False,
        "source_writes_by_codex": False,
        "memory_write_made": False,
    }


def build_diagnostics_skipped_notes_card(cards: Mapping[str, Any]) -> dict[str, Any]:
    skipped: list[dict[str, str]] = []
    for card_name, card in cards.items():
        if not isinstance(card, Mapping):
            continue
        card_availability = card.get("availability")
        if not isinstance(card_availability, Mapping):
            continue
        if not card_availability.get("visible_to_model"):
            skipped.append(
                {
                    "card": clean_text(card_name, max_chars=120),
                    "status": clean_text(card_availability.get("status"), max_chars=80),
                    "reason": clean_text(card_availability.get("reason"), max_chars=240),
                }
            )
    return {
        "availability": availability(
            status="available",
            source_kind="gateway_diagnostics",
            visible_to_model=False,
            diagnostics_only=True,
            freshness="current_turn",
        ),
        "skipped_cards": skipped,
    }


def build_api_talk_card_envelope(
    *,
    request_id: str,
    current_message: str,
    current_message_source_id: str = "",
    house_thread_id: str = "",
    turn_id: str = "",
    source_route: str = "api_talk_preview",
    active_provider_profile: Mapping[str, Any] | None = None,
    soul_summary: str | None = None,
    astel_summary: str | None = None,
    style_card_text: str | None = None,
    thread_summary: Mapping[str, Any] | None = None,
    short_term_continuity_items: list[Mapping[str, Any]] | None = None,
    across_session_continuity_cards: list[Mapping[str, Any]] | None = None,
    standing_live_vault_cards: list[Mapping[str, Any]] | None = None,
    standing_live_vault_status: Mapping[str, Any] | None = None,
    memory_candidates: list[Mapping[str, Any]] | None = None,
    read_mode_source_summaries: list[Mapping[str, Any]] | None = None,
    read_mode_exact_text_attachments: list[Mapping[str, Any]] | None = None,
    read_mode_current_audio_recognition: Mapping[str, Any] | None = None,
    status_time: Mapping[str, Any] | None = None,
    reality_context: Mapping[str, Any] | None = None,
    adult_context_summary: str | None = None,
    attach_adult_context: bool = False,
    codex_hand_result_card: Mapping[str, Any] | None = None,
    max_memory_items: int = 3,
    max_context_chars: int = 6000,
    embedding_available: bool = True,
    cache_state: str = "not_used",
) -> dict[str, Any]:
    profile = dict(active_provider_profile or {})
    cards: dict[str, Any] = {
        "soul_identity_card": build_soul_identity_card(soul_summary),
        "astel_profile_card": build_astel_profile_card(astel_summary),
        "style_profile_card": build_style_profile_card(style_card_text),
        "current_message_card": build_current_message_card(current_message, source_id=current_message_source_id),
        "current_message_affect_card": build_current_message_affect_card(current_message),
        "thread_summary_card": build_thread_summary_card(
            thread_summary
            or {
                "house_thread_id": house_thread_id,
                "summary": "",
                "message_count": 0,
                "freshness": "current_thread",
            }
        ),
        "across_session_continuity_card": build_across_session_continuity_card(
            across_session_continuity_cards
        ),
        "standing_live_vault_context_card": build_standing_live_vault_context_card(
            standing_live_vault_cards,
            status=standing_live_vault_status,
        ),
        "short_term_continuity_card": build_short_term_continuity_card(short_term_continuity_items),
        "memory_context_card": build_memory_context_card(
            memory_candidates,
            max_selected=max_memory_items,
            embedding_available=embedding_available,
            cache_state=cache_state,
        ),
        "read_mode_source_context_card": build_read_mode_source_context_card(read_mode_source_summaries),
        "read_mode_exact_text_card": build_read_mode_exact_text_card(read_mode_exact_text_attachments),
        "current_audio_recognition_card": current_audio_turn.build_provider_card(
            read_mode_current_audio_recognition
        ),
        "status_time_card": build_status_time_card(status_time),
        "reality_context_card": build_reality_context_card(reality_context),
        "app_body_status_card": build_placeholder_card(
            "app_body_status_card",
            "Body/app status summaries are placeholder-only in API Talk envelope v0.",
            source_kind="future_body_status",
        ),
        "weather_card": build_placeholder_card(
            "weather_card",
            "Weather is not connected in API Talk envelope v0.",
            source_kind="future_weather",
        ),
        "route_capability_card": build_route_capability_card(profile, source_route=source_route),
        "adult_authentication_card": build_adult_authentication_card(
            adult_context_summary,
            attach=attach_adult_context,
        ),
        "codex_hand_result_card": build_codex_hand_result_card(codex_hand_result_card),
    }
    cards["diagnostics_skipped_notes_card"] = build_diagnostics_skipped_notes_card(cards)
    provider_visible_cards = [
        name
        for name, card in cards.items()
        if isinstance(card, Mapping)
        and isinstance(card.get("availability"), Mapping)
        and card["availability"].get("visible_to_model")
    ]
    diagnostics_only_cards = [
        name
        for name, card in cards.items()
        if isinstance(card, Mapping)
        and isinstance(card.get("availability"), Mapping)
        and card["availability"].get("diagnostics_only")
    ]
    skipped_cards = [
        name
        for name, card in cards.items()
        if isinstance(card, Mapping)
        and isinstance(card.get("availability"), Mapping)
        and card["availability"].get("status") == "skipped"
    ]
    envelope = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "request_id": clean_text(request_id, max_chars=160),
        "house_thread_id": clean_text(house_thread_id, max_chars=160),
        "turn_id": clean_text(turn_id, max_chars=160),
        "created_at": utc_timestamp(),
        "source_route": clean_text(source_route, max_chars=120),
        "active_provider_profile": {
            "profile_id": cards["route_capability_card"]["profile_id"],
            "provider_label": cards["route_capability_card"]["provider_label"],
            "endpoint_family": cards["route_capability_card"]["endpoint_family"],
            "model_id": cards["route_capability_card"]["model_id"],
        },
        "cards": cards,
        "card_summary": {
            "provider_visible_cards": provider_visible_cards,
            "diagnostics_only_cards": diagnostics_only_cards,
            "skipped_cards": skipped_cards,
        },
        "budget": {
            "max_context_chars": max_context_chars,
            "estimated_context_chars": estimate_provider_visible_chars(cards),
        },
        "renderer_hints": {
            "preferred_renderer": KOURI_CHAT_COMPLETIONS_RENDERER_ID,
            "provider_message_shape": "single_user_message",
        },
        "safety_policy": {
            "raw_memory_allowed": False,
            "raw_chat_history_allowed": False,
            "raw_provider_bodies_allowed": False,
            "tools_allowed": False,
            "memory_write_allowed": False,
            "normal_action_permissions": False,
        },
        "diagnostics": {
            "provider_call_triggered": False,
            "full_vault_scan": False,
            "cache_state": clean_text(cache_state, max_chars=80),
            "embedding_available": bool(embedding_available),
            "memory_selected_count": cards["memory_context_card"]["diagnostics"]["selected_count"],
            "across_session_continuity_selected_count": cards["across_session_continuity_card"]["diagnostics"]["selected_count"],
            "standing_live_vault_selected_count": cards["standing_live_vault_context_card"]["diagnostics"]["selected_count"],
            "short_term_continuity_selected_count": cards["short_term_continuity_card"]["diagnostics"]["selected_count"],
            "read_mode_source_selected_count": cards["read_mode_source_context_card"]["diagnostics"]["selected_count"],
            "read_mode_exact_text_selected_count": cards["read_mode_exact_text_card"]["diagnostics"]["selected_count"],
            "current_audio_recognition_selected_count": cards["current_audio_recognition_card"]["diagnostics"][
                "selected_count"
            ],
            "reality_context_selected_count": cards["reality_context_card"]["diagnostics"]["selected_count"],
            "reality_context_android_status_feed_connected": bool(
                cards["reality_context_card"]["diagnostics"]["android_status_feed_connected"]
            ),
            "reality_context_self_state_included": bool(
                cards["reality_context_card"]["diagnostics"]["self_state_included"]
            ),
            "reality_context_proactive_wake_send": bool(
                cards["reality_context_card"]["diagnostics"]["proactive_wake_send"]
            ),
            "current_message_affect_signal": cards["current_message_affect_card"]["affect_signal"],
            "codex_hand_result_attached": bool(cards["codex_hand_result_card"].get("attached")),
        },
        "policy_action": "none",
    }
    if envelope["budget"]["estimated_context_chars"] > max_context_chars:
        raise ApiTalkEnvelopeError("context_too_large", "API Talk envelope exceeds the configured context budget.")
    return envelope


def estimate_provider_visible_chars(cards: Mapping[str, Any]) -> int:
    rendered_fragments: list[str] = []
    for card in cards.values():
        if not isinstance(card, Mapping):
            continue
        card_availability = card.get("availability")
        if isinstance(card_availability, Mapping) and card_availability.get("visible_to_model"):
            rendered_fragments.append(str(card))
    return len("\n".join(rendered_fragments))


def _render_section(title: str, lines: list[str]) -> str:
    clean_lines = [line for line in lines if line.strip()]
    if not clean_lines:
        return ""
    return "\n".join([title, *clean_lines])


def _trim_before_section(text: str, section: str) -> str:
    marker = section.lower()
    index = text.lower().find(marker)
    return text[index:].strip() if index >= 0 else text


def _trim_at_section(text: str, section: str) -> str:
    marker = section.lower()
    index = text.lower().find(marker)
    return text[:index].strip() if index >= 0 else text


def provider_visible_astel_text(text: Any) -> str:
    rendered = clean_text(text, max_chars=1200)
    return _trim_before_section(rendered, "Identity:")


def provider_visible_style_text(text: Any) -> str:
    rendered = clean_text(text, max_chars=1800)
    return _trim_at_section(rendered, "Boundaries:")


def _living_footing_render(envelope: Mapping[str, Any]) -> tuple[bool, str]:
    living = envelope.get("living_footing") if isinstance(envelope.get("living_footing"), Mapping) else {}
    if not living or not living.get("provider_visible_render_attached"):
        return False, ""
    rendered = clean_text(living.get("rendered_preview"), max_chars=1600)
    if not rendered:
        return False, ""
    return True, rendered


def _section_observability_counts(
    source: Mapping[str, Any] | None,
    *,
    default_selected: int = 1,
) -> tuple[int, int, dict[str, int]]:
    selected_source = source if isinstance(source, Mapping) else {}
    diagnostics = (
        selected_source.get("diagnostics")
        if isinstance(selected_source.get("diagnostics"), Mapping)
        else {}
    )
    selected_items = selected_source.get("selected_items")
    selected = diagnostics.get("selected_count", selected_source.get("selected_count"))
    if not isinstance(selected, int) or isinstance(selected, bool) or selected < 0:
        selected = len(selected_items) if isinstance(selected_items, list) else default_selected
    omitted = 0
    for field in ("omitted_count", "excluded_count", "skipped_count", "rejected_count"):
        candidate = diagnostics.get(field, selected_source.get(field))
        if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate >= 0:
            omitted = max(omitted, candidate)
    reasons: dict[str, int] = {}
    for owner in (selected_source, diagnostics):
        for field in ("reason_counts", "skipped_reason_counts", "excluded_reason_counts"):
            values = owner.get(field)
            if not isinstance(values, Mapping):
                continue
            for reason, count in values.items():
                if isinstance(reason, str) and isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                    reasons[reason] = reasons.get(reason, 0) + count
        for flag, reason in (
            ("truncated", "truncated"),
            ("clipped", "clipped"),
            ("evicted", "evicted"),
            ("rejected", "rejected"),
        ):
            if owner.get(flag) is True:
                reasons[reason] = reasons.get(reason, 0) + 1
    return int(selected), int(omitted), reasons


def render_kouri_chat_completions_user_text(
    envelope: Mapping[str, Any],
    *,
    section_metrics: list[dict[str, Any]] | None = None,
    section_outputs: list[dict[str, Any]] | None = None,
) -> str:
    if envelope.get("schema_version") != ENVELOPE_SCHEMA_VERSION:
        raise ApiTalkEnvelopeError("invalid_envelope", "Envelope schema_version is invalid.")
    cards = envelope.get("cards") if isinstance(envelope.get("cards"), Mapping) else {}
    visible = set(
        envelope.get("card_summary", {}).get("provider_visible_cards", [])
        if isinstance(envelope.get("card_summary"), Mapping)
        else []
    )
    sections: list[str] = []
    provider_order = 0

    def append_section(
        rendered_text: str,
        *,
        section_id: str,
        section_class: str,
        exactness: str,
        update_frequency: str,
        source: Mapping[str, Any] | None = None,
        default_selected: int = 1,
    ) -> None:
        nonlocal provider_order
        # Product text is appended before optional telemetry so observability
        # failure cannot change the flattened provider-visible result.
        sections.append(rendered_text)
        if not isinstance(rendered_text, str) or not rendered_text.strip():
            return
        order = provider_order
        provider_order += 1
        if section_outputs is not None:
            try:
                section_outputs.append(
                    {
                        "section_id": section_id,
                        "section_class": section_class,
                        "exactness": exactness,
                        "update_frequency": update_frequency,
                        "rendered_text": rendered_text,
                    }
                )
            except Exception:
                # The optional in-memory production assembly collector cannot
                # change the canonical flattened provider-visible result.
                pass
        if section_metrics is None:
            return
        try:
            selected, omitted, reasons = _section_observability_counts(
                source,
                default_selected=default_selected,
            )
            section_metrics.append(
                provider_observability.build_section_metric(
                    section_id=section_id,
                    section_class=section_class,
                    order=order,
                    rendered_text=rendered_text,
                    exactness=exactness,
                    update_frequency=update_frequency,
                    selected_count=selected,
                    omitted_count=omitted,
                    reason_counts=reasons,
                )
            )
        except Exception:
            # Raw-free metrics are optional; the renderer remains canonical.
            return
    source_route = clean_text(envelope.get("source_route"), max_chars=120)
    living_footing_attached, living_footing_rendered = _living_footing_render(envelope)

    soul = cards.get("soul_identity_card") if isinstance(cards.get("soul_identity_card"), Mapping) else {}
    if "soul_identity_card" in visible and not living_footing_attached:
        append_section(
            _render_section("Solen identity:", [clean_text(soul.get("summary"), max_chars=800)]),
            section_id="solen_identity",
            section_class="standing_quiet_relationship_footing",
            exactness="mixed",
            update_frequency="slowly_changing",
            source=soul,
        )

    astel = cards.get("astel_profile_card") if isinstance(cards.get("astel_profile_card"), Mapping) else {}
    if "astel_profile_card" in visible and not living_footing_attached:
        append_section(
            _render_section("Astel profile:", [provider_visible_astel_text(astel.get("summary"))]),
            section_id="astel_profile",
            section_class="standing_quiet_relationship_footing",
            exactness="derived",
            update_frequency="slowly_changing",
            source=astel,
        )

    style = cards.get("style_profile_card") if isinstance(cards.get("style_profile_card"), Mapping) else {}
    if "style_profile_card" in visible and not living_footing_attached:
        style_lines: list[str] = []
        style_text = provider_visible_style_text(style.get("style_card_text"))
        if style_text:
            style_lines.append(style_text)
        append_section(
            _render_section("Style profile:", style_lines),
            section_id="style_profile",
            section_class="standing_quiet_relationship_footing",
            exactness="derived",
            update_frequency="slowly_changing",
            source=style,
        )

    affect = cards.get("current_message_affect_card") if isinstance(cards.get("current_message_affect_card"), Mapping) else {}
    if "current_message_affect_card" in visible and not living_footing_attached:
        append_section(
            _render_section(
                "Current message affect:",
                [
                    f"- affect_signal: {clean_text(affect.get('affect_signal'), max_chars=120)}",
                    f"- suggested_posture: {clean_text(affect.get('suggested_posture'), max_chars=240)}",
                    f"- continuity_use: {clean_text(affect.get('continuity_use'), max_chars=120)}",
                ],
            ),
            section_id="current_message_affect",
            section_class="standing_quiet_relationship_footing",
            exactness="derived",
            update_frequency="per_turn",
            source=affect,
        )

    recent_exchange = (
        envelope.get("recent_visible_exchange")
        if isinstance(envelope.get("recent_visible_exchange"), Mapping)
        else {}
    )
    if recent_exchange.get("provider_visible"):
        exchange_max = min(
            max(safe_int(recent_exchange.get("summary_max_chars")) or RECENT_VISIBLE_EXCHANGE_MAX_RENDER_CHARS, 1200),
            RECENT_VISIBLE_EXCHANGE_MAX_RENDER_CHARS,
        )
        raw_exchange_summary = recent_exchange.get("summary")
        if recent_exchange.get("prebudgeted_complete_units") and isinstance(raw_exchange_summary, str):
            exchange_summary = raw_exchange_summary.strip()
            if len(exchange_summary) > exchange_max:
                raise ApiTalkEnvelopeError(
                    "recent_continuity_render_budget_exceeded",
                    "Prebudgeted recent continuity exceeds the renderer hard limit.",
                )
        else:
            exchange_summary = clean_text(raw_exchange_summary, max_chars=exchange_max)
        if exchange_summary:
            append_section(
                _render_section("Recent visible exchange:", [exchange_summary]),
                section_id="recent_visible_exchange",
                section_class="recent_exact_current_session",
                exactness="mixed",
                update_frequency="append_only",
                source=recent_exchange,
            )

    active_room_throughline = (
        envelope.get("active_room_throughline")
        if isinstance(envelope.get("active_room_throughline"), Mapping)
        else {}
    )
    if active_room_throughline.get("provider_visible"):
        throughline_summary = clean_text(
            active_room_throughline.get("summary"),
            max_chars=max(safe_int(active_room_throughline.get("summary_max_chars")) or 1200, 300),
        )
        if throughline_summary:
            append_section(
                _render_section("Earlier in this room:", [throughline_summary]),
                section_id="active_room_throughline",
                section_class="earlier_room_throughline",
                exactness="derived",
                update_frequency="per_session",
                source=active_room_throughline,
            )

    if living_footing_attached:
        append_section(
            living_footing_rendered,
            section_id="living_footing",
            section_class="standing_quiet_relationship_footing",
            exactness="mixed",
            update_frequency="per_turn",
            source=envelope.get("living_footing") if isinstance(envelope.get("living_footing"), Mapping) else None,
        )

    reality = cards.get("reality_context_card") if isinstance(cards.get("reality_context_card"), Mapping) else {}
    if "reality_context_card" in visible and not living_footing_attached:
        route_surface_room = (
            reality.get("route_surface_room")
            if isinstance(reality.get("route_surface_room"), Mapping)
            else {}
        )
        profile_refs = (
            reality.get("profile_preference_refs")
            if isinstance(reality.get("profile_preference_refs"), Mapping)
            else {}
        )
        android_status = (
            reality.get("android_status")
            if isinstance(reality.get("android_status"), Mapping)
            else {}
        )
        provider_visible_hints = (
            reality.get("provider_visible_hints")
            if isinstance(reality.get("provider_visible_hints"), list)
            else []
        )
        profile_available = "yes" if profile_refs.get("astel_profile_summary_available") else "no"
        feed_connected = "yes" if android_status.get("feed_connected") else "no"
        reality_lines = [
            (
                f"- local time: {clean_text(reality.get('current_time_local'), max_chars=80)} "
                f"({clean_text(reality.get('local_weekday'), max_chars=40)}, "
                f"{clean_text(reality.get('local_day_period'), max_chars=80)})"
            ),
            (
                f"- room/surface: {clean_text(route_surface_room.get('room'), max_chars=80)} "
                f"on {clean_text(route_surface_room.get('surface'), max_chars=120)}"
            ),
            f"- route posture: {clean_text(route_surface_room.get('route_posture'), max_chars=120)}",
        ]
        reality_lines.extend(
            f"- natural-use hint: {clean_text(hint, max_chars=360)}"
            for hint in provider_visible_hints[:3]
            if clean_text(hint, max_chars=360)
        )
        reality_lines.extend(
            [
                (
                    "- profile/preference refs: safe counts/placeholders only; "
                    f"Astel profile summary available: {profile_available}; "
                    f"preference ref count: {safe_int(profile_refs.get('preference_ref_count'))}"
                ),
                (
                    "- Android status: not attached; "
                    f"real status feed connected: {feed_connected}; "
                    "Android/device status is not attached fully yet."
                ),
            ]
        )
        append_section(
            _render_section("Current situation:", reality_lines),
            section_id="current_situation",
            section_class="timeline_source_attachment",
            exactness="derived",
            update_frequency="live_dynamic",
            source=reality,
        )

    if (
        not living_footing_attached
        and (
            source_route == "body_gateway_turn_android_standing_live"
            or "across_session_continuity_card" in visible
            or "standing_live_vault_context_card" in visible
        )
    ):
        append_section(
            _render_section("Context footing:", CONTEXT_FOOTING_LINES),
            section_id="context_footing_law",
            section_class="standing_quiet_relationship_footing",
            exactness="exact",
            update_frequency="immutable_versioned",
        )

    thread = cards.get("thread_summary_card") if isinstance(cards.get("thread_summary_card"), Mapping) else {}
    if "thread_summary_card" in visible and not living_footing_attached:
        thread_summary_max = min(max(safe_int(thread.get("summary_max_chars")) or 1200, 1200), 6000)
        thread_summary_text = clean_text(thread.get("summary"), max_chars=thread_summary_max)
        if source_route == "body_gateway_turn_android_standing_live":
            append_section(
                _render_section(
                    "Current House Talk room:",
                    [thread_summary_text],
                ),
                section_id="current_house_talk_room",
                section_class="earlier_room_throughline",
                exactness="derived",
                update_frequency="per_turn",
                source=thread,
            )
        else:
            append_section(
                _render_section(
                    "Thread summary:",
                    [
                        f"- house_thread_id: {clean_text(thread.get('house_thread_id'), max_chars=160)}",
                        f"- title: {clean_text(thread.get('local_draft_title'), max_chars=160)}",
                        f"- message_count: {safe_int(thread.get('message_count'))}",
                        f"- summary: {thread_summary_text}",
                    ],
                ),
                section_id="thread_summary",
                section_class="earlier_room_throughline",
                exactness="derived",
                update_frequency="per_turn",
                source=thread,
            )

    standing_live_vault = (
        cards.get("standing_live_vault_context_card")
        if isinstance(cards.get("standing_live_vault_context_card"), Mapping)
        else {}
    )
    current_hybrid_memory_attached = (
        "standing_live_vault_context_card" in visible
        and _standing_live_vault_has_hybrid_related_memory(standing_live_vault)
    )

    across_session = (
        cards.get("across_session_continuity_card")
        if isinstance(cards.get("across_session_continuity_card"), Mapping)
        else {}
    )
    if "across_session_continuity_card" in visible and not current_hybrid_memory_attached:
        across_session_lines = []
        selected = across_session.get("selected_items") if isinstance(across_session.get("selected_items"), list) else []
        for item in selected:
            if not isinstance(item, Mapping):
                continue
            summary_lines = [
                clean_text(line, max_chars=700)
                for line in str(item.get("summary") or "").splitlines()
                if line.strip()
            ]
            if summary_lines and summary_lines[0].casefold() == "earlier house talk continuity:":
                summary_lines = summary_lines[1:]
            across_session_lines.extend(summary_lines)
        if not living_footing_attached:
            append_section(
                _render_section(
                    "Earlier House Talk continuity:",
                    across_session_lines or ["No earlier House Talk digest attached."],
                ),
                section_id="earlier_house_talk_continuity",
                section_class="earlier_room_throughline",
                exactness="derived",
                update_frequency="per_session",
                source=across_session,
            )

    if "standing_live_vault_context_card" in visible:
        vault_lines = []
        selected = standing_live_vault.get("selected_items") if isinstance(standing_live_vault.get("selected_items"), list) else []
        selected_direct_exact_evidence = any(
            isinstance(item, Mapping) and _standing_live_vault_item_is_direct_exact_evidence(item)
            for item in selected
        )
        for item in selected:
            if not isinstance(item, Mapping):
                continue
            summary = clean_text(item.get("summary"), max_chars=1000)
            kind = clean_text(item.get("kind"), max_chars=120)
            source_class = clean_text(item.get("source_class"), max_chars=120)
            source_ref = clean_text(item.get("source_ref"), max_chars=260)
            reason_attached = clean_text(item.get("reason_attached"), max_chars=180)
            activation_tier = clean_text(item.get("activation_tier"), max_chars=80)
            supersession_state = clean_text(item.get("supersession_state"), max_chars=80)
            score = safe_float(item.get("score"))
            direct_exact_evidence = _standing_live_vault_item_is_direct_exact_evidence(item)
            hybrid_related_memory = _standing_live_vault_item_is_hybrid_related_memory(item)
            if direct_exact_evidence:
                speaker = clean_text(item.get("speaker"), max_chars=40).casefold()
                if speaker in {"user", "astel"}:
                    speaker_label = "Astel"
                elif speaker in {"assistant", "solen"}:
                    speaker_label = "Solen"
                else:
                    speaker_label = "the past conversation"
                bounded_quote = clean_visible_exact_quote(item.get("bounded_quote"), max_chars=500)
                if bounded_quote:
                    vault_lines.append(f"- Exact wording from {speaker_label}: {bounded_quote}")
                else:
                    vault_lines.append(f"- Exact wording from {speaker_label} is attached.")
            elif hybrid_related_memory:
                event_detail = item.get("event_detail") if isinstance(item.get("event_detail"), Mapping) else {}
                confidence_label = clean_text(item.get("confidence") or event_detail.get("confidence"), max_chars=80)
                uncertainty = clean_text(item.get("uncertainty") or event_detail.get("uncertainty"), max_chars=160)
                vault_lines.append(
                    f"- {_standing_live_hybrid_memory_sentence(kind=kind, summary=summary, event_detail=event_detail)}"
                )
                if kind == "partial_memory_card" or confidence_label in {"low", "very_low"}:
                    if uncertainty:
                        vault_lines.append(f"  - partiality: {uncertainty}")
            else:
                vault_lines.append(f"- Related memory found: {kind}: {summary}")
                vault_lines.append("  - source type: related memory")
            event_detail = item.get("event_detail") if isinstance(item.get("event_detail"), Mapping) else {}
            if event_detail and not hybrid_related_memory:
                event_label = clean_text(event_detail.get("event_label"), max_chars=160)
                participant_labels = [
                    clean_text(label, max_chars=80)
                    for label in list(event_detail.get("participant_labels") or [])[:6]
                    if clean_text(label, max_chars=80)
                ]
                entity_labels = [
                    clean_text(label, max_chars=80)
                    for label in list(event_detail.get("entity_labels") or [])[:8]
                    if clean_text(label, max_chars=80)
                ]
                scene_action_cues = [
                    clean_text(label, max_chars=80)
                    for label in list(event_detail.get("scene_action_cues") or [])[:6]
                    if clean_text(label, max_chars=80)
                ]
                memorable_cues = [
                    clean_text(label, max_chars=80)
                    for label in list(event_detail.get("memorable_cues") or [])[:6]
                    if clean_text(label, max_chars=80)
                ]
                time_context_cue = clean_text(event_detail.get("time_context_cue"), max_chars=120)
                if event_label:
                    vault_lines.append(f"  - event cue: {event_label}")
                if participant_labels or entity_labels:
                    people_and_entities = ", ".join([*participant_labels, *entity_labels])
                    vault_lines.append(f"  - people/entities: {people_and_entities}")
                if scene_action_cues:
                    vault_lines.append(f"  - scene/action cues: {', '.join(scene_action_cues)}")
                if memorable_cues:
                    vault_lines.append(f"  - memorable cues: {', '.join(memorable_cues)}")
                if time_context_cue:
                    vault_lines.append(f"  - time/context cue: {time_context_cue}")
                confidence_label = clean_text(event_detail.get("confidence"), max_chars=80)
                source_clarity = clean_text(event_detail.get("source_clarity"), max_chars=160)
                uncertainty = clean_text(event_detail.get("uncertainty"), max_chars=160)
                audience_label = clean_text(event_detail.get("audience_label"), max_chars=120)
                if confidence_label:
                    vault_lines.append(f"  - confidence: {confidence_label}")
                if source_clarity:
                    vault_lines.append(f"  - source footing: {source_clarity}")
                if uncertainty:
                    vault_lines.append(f"  - memory footing: {uncertainty}")
                if audience_label:
                    vault_lines.append(f"  - audience footing: {audience_label}")
            if activation_tier and not hybrid_related_memory and not direct_exact_evidence:
                vault_lines.append(f"  - activation tier: {activation_tier}")
            if activation_tier == "core_memory":
                vault_lines.append("  - core memory: durable reviewed memory")
            elif activation_tier == "active_situation_memory":
                vault_lines.append("  - recall priority: active situation memory")
            elif activation_tier == "exact_recall" and not direct_exact_evidence:
                vault_lines.append("  - exact memory: exact wording is attached for this event")
            memory_audience_scope = clean_text(item.get("memory_audience_scope"), max_chars=80)
            room_audience_context = clean_text(item.get("room_audience_context"), max_chars=80)
            expression_guidance = clean_text(item.get("expression_guidance"), max_chars=80)
            if memory_audience_scope or room_audience_context or expression_guidance:
                vault_lines.append(
                    "  - audience footing: "
                    f"memory_audience_scope={memory_audience_scope or 'unspecified'}, "
                    f"room_audience_context={room_audience_context or 'unspecified'}"
                )
                if (
                    memory_audience_scope == "astel_solen_private"
                    and room_audience_context in {"group_room", "other_participant_room"}
                ):
                    vault_lines.append(
                        "  - expression footing: Astel/Solen private memory; current room audience has other participants."
                    )
                elif memory_audience_scope == "astel_solen_private":
                    vault_lines.append(
                        "  - expression footing: Astel/Solen private memory."
                    )
                elif expression_guidance == "group_shareable":
                    vault_lines.append("  - expression footing: group-shareable memory.")
                elif expression_guidance == "diagnostics_only":
                    vault_lines.append("  - expression footing: this label indicates diagnostics-only handling.")
                elif expression_guidance:
                    vault_lines.append("  - expression footing: audience-scoped memory.")
            if source_class and not hybrid_related_memory and not direct_exact_evidence:
                vault_lines.append(f"  - source class: {source_class}")
            if supersession_state and not hybrid_related_memory and not direct_exact_evidence:
                vault_lines.append(f"  - supersession state: {supersession_state}")
            if reason_attached and not hybrid_related_memory and not direct_exact_evidence:
                vault_lines.append(f"  - match reason: {reason_attached}")
            if score and not hybrid_related_memory and not direct_exact_evidence:
                vault_lines.append(f"  - retrieval score: {score:.4f}")
            date = clean_text(item.get("date"), max_chars=40)
            timestamp = clean_text(item.get("timestamp"), max_chars=80)
            if (date or timestamp) and not direct_exact_evidence:
                vault_lines.append(f"  - when: {timestamp or date}")
            bounded_quote = clean_text(item.get("bounded_quote"), max_chars=500)
            if bounded_quote and not direct_exact_evidence:
                vault_lines.append(f"  - bounded quote: {bounded_quote}")
            if source_ref and not hybrid_related_memory and not direct_exact_evidence:
                vault_lines.append(f"  - source ref: {source_ref}")
            event_context = item.get("event_context") if isinstance(item.get("event_context"), Mapping) else {}
            if event_context:
                context_summary = clean_text(event_context.get("summary"), max_chars=1000)
                summary_kind = clean_text(event_context.get("summary_kind") or "event_context", max_chars=120)
                window_message_count = safe_int(event_context.get("window_message_count"))
                before_count = safe_int(event_context.get("before_selected_count"))
                after_count = safe_int(event_context.get("after_selected_count"))
                if context_summary:
                    if direct_exact_evidence:
                        vault_lines.append(f"  - surrounding context: {context_summary}")
                    else:
                        vault_lines.append(f"  - event context ({summary_kind}): {context_summary}")
                        if window_message_count:
                            vault_lines.append(
                                "  - event context window: "
                                f"{window_message_count} nearby same-conversation messages "
                                f"({before_count} before, {after_count} after the exact line)"
                            )
                        vault_lines.append(
                            "  - event context footing: linked to this exact memory by source/message/timestamp/order; use it as surrounding context, not proof by itself."
                        )
                        if event_context.get("helper_generated"):
                            vault_lines.append("  - curator note: this event context was summarized by a backend helper.")
        if vault_lines:
            if selected_direct_exact_evidence:
                vault_lines.append("- exact wording is from archived Chat History for this turn.")
            elif not any(
                isinstance(item, Mapping) and _standing_live_vault_item_is_hybrid_related_memory(item)
                for item in selected
            ):
                vault_lines.append(f"- memory source note: {VAULT_RELATED_FOOTING_LINE}")
        status_item = (
            standing_live_vault.get("status_item")
            if isinstance(standing_live_vault.get("status_item"), Mapping)
            else {}
        )
        if status_item and not selected:
            status_summary = clean_text(status_item.get("summary"), max_chars=500)
            vault_lines.append(f"- {status_summary or 'No exact wording is attached for this request.'}")
        append_section(
            _render_section("Vault recall:", vault_lines or ["No direct memory was surfaced for that event."]),
            section_id="vault_recall",
            section_class="vault_memory_recall",
            exactness="mixed",
            update_frequency="per_turn",
            source=standing_live_vault,
            default_selected=0 if not selected else len(selected),
        )

    if "across_session_continuity_card" in visible and current_hybrid_memory_attached:
        across_session_lines = []
        demoted_competing_lines = 0
        selected = across_session.get("selected_items") if isinstance(across_session.get("selected_items"), list) else []
        for item in selected:
            if not isinstance(item, Mapping):
                continue
            summary_lines = []
            for line in str(item.get("summary") or "").splitlines():
                if not line.strip():
                    continue
                if _standing_live_across_session_line_competes_with_hybrid_memory(line):
                    demoted_competing_lines += 1
                    continue
                summary_lines.append(clean_text(line, max_chars=700))
            if summary_lines and summary_lines[0].casefold() == "earlier house talk continuity:":
                summary_lines = summary_lines[1:]
            across_session_lines.extend(summary_lines)
        if not living_footing_attached:
            if across_session_lines:
                append_section(
                    _render_section(
                        "Earlier House Talk continuity (background):",
                        ["Background from prior rooms; current surfaced memory is above."]
                        + across_session_lines,
                    ),
                    section_id="earlier_house_talk_continuity_background",
                    section_class="earlier_room_throughline",
                    exactness="derived",
                    update_frequency="per_session",
                    source=across_session,
                )
            elif not demoted_competing_lines:
                append_section(
                    _render_section(
                        "Earlier House Talk continuity (background):",
                        ["Background from prior rooms; current surfaced memory is above."],
                    ),
                    section_id="earlier_house_talk_continuity_background",
                    section_class="earlier_room_throughline",
                    exactness="derived",
                    update_frequency="per_session",
                    source=across_session,
                )

    if living_footing_attached:
        living = envelope.get("living_footing") if isinstance(envelope.get("living_footing"), Mapping) else {}
        timeline_evidence_lines = (
            living.get("timeline_evidence_render_lines")
            if isinstance(living.get("timeline_evidence_render_lines"), list)
            else []
        )
        clean_timeline_lines = [
            clean_text(line, max_chars=700)
            for line in timeline_evidence_lines
            if clean_text(line, max_chars=700) and clean_text(line, max_chars=700) != "Timeline evidence:"
        ]
        if clean_timeline_lines:
            append_section(
                _render_section("Timeline evidence:", clean_timeline_lines),
                section_id="timeline_evidence",
                section_class="timeline_source_attachment",
                exactness="mixed",
                update_frequency="live_dynamic",
                source=living,
            )

    memory = cards.get("memory_context_card") if isinstance(cards.get("memory_context_card"), Mapping) else {}
    continuity = cards.get("short_term_continuity_card") if isinstance(cards.get("short_term_continuity_card"), Mapping) else {}
    if "short_term_continuity_card" in visible and not living_footing_attached:
        continuity_lines = []
        selected = continuity.get("selected_items") if isinstance(continuity.get("selected_items"), list) else []
        for item in selected:
            if not isinstance(item, Mapping):
                continue
            continuity_lines.append("- " + clean_text(item.get("summary"), max_chars=900))
        append_section(
            _render_section("Recent continuity:", continuity_lines or ["No recent continuity attached."]),
            section_id="short_term_continuity",
            section_class="recent_exact_current_session",
            exactness="derived",
            update_frequency="per_turn",
            source=continuity,
            default_selected=0 if not selected else len(selected),
        )

    if "memory_context_card" in visible and not living_footing_attached:
        memory_lines = []
        selected = memory.get("selected_items") if isinstance(memory.get("selected_items"), list) else []
        for item in selected:
            if not isinstance(item, Mapping):
                continue
            memory_lines.append("- " + clean_text(item.get("summary"), max_chars=1200))
        append_section(
            _render_section("Memory context:", memory_lines or ["No memory context attached."]),
            section_id="memory_context",
            section_class="vault_memory_recall",
            exactness="derived",
            update_frequency="per_turn",
            source=memory,
            default_selected=0 if not selected else len(selected),
        )

    read_mode = (
        cards.get("read_mode_source_context_card")
        if isinstance(cards.get("read_mode_source_context_card"), Mapping)
        else {}
    )
    if "read_mode_source_context_card" in visible:
        read_mode_lines = []
        selected = read_mode.get("selected_items") if isinstance(read_mode.get("selected_items"), list) else []
        for item in selected:
            if not isinstance(item, Mapping):
                continue
            label = clean_text(item.get("source_label") or "attached source", max_chars=180)
            modality = clean_text(item.get("source_modality") or "source_summary", max_chars=80)
            read_mode_lines.append(
                f"- {label} ({modality}): {clean_text(item.get('summary'), max_chars=1200)}"
            )
            excerpts = item.get("targeted_excerpts") if isinstance(item.get("targeted_excerpts"), list) else []
            for excerpt in excerpts:
                if not isinstance(excerpt, Mapping):
                    continue
                line_start = safe_int(excerpt.get("line_start"))
                line_end = safe_int(excerpt.get("line_end"))
                line_label = f"lines {line_start}-{line_end}" if line_start and line_end else "targeted excerpt"
                read_mode_lines.append(
                    f"  - {line_label}: {clean_text(excerpt.get('excerpt_text'), max_chars=900)}"
                )
        append_section(
            _render_section("Read Mode source context:", read_mode_lines),
            section_id="read_mode_source_context",
            section_class="timeline_source_attachment",
            exactness="mixed",
            update_frequency="per_turn",
            source=read_mode,
            default_selected=len(selected),
        )

    exact_text_card = (
        cards.get("read_mode_exact_text_card")
        if isinstance(cards.get("read_mode_exact_text_card"), Mapping)
        else {}
    )
    if "read_mode_exact_text_card" in visible:
        exact_lines = []
        selected = exact_text_card.get("selected_items") if isinstance(exact_text_card.get("selected_items"), list) else []
        for item in selected:
            if not isinstance(item, Mapping):
                continue
            label = clean_text(item.get("source_label") or "attached text source", max_chars=180)
            exact_text = clean_exact_text(item.get("exact_text"), max_chars=6000)
            exact_lines.extend(
                [
                    f"- source: {label}",
                    "```text",
                    exact_text,
                    "```",
                ]
            )
        append_section(
            _render_section("Read Mode exact text:", exact_lines),
            section_id="read_mode_exact_text",
            section_class="timeline_source_attachment",
            exactness="exact",
            update_frequency="per_turn",
            source=exact_text_card,
            default_selected=len(selected),
        )

    current_audio_card = (
        cards.get("current_audio_recognition_card")
        if isinstance(cards.get("current_audio_recognition_card"), Mapping)
        else {}
    )
    if "current_audio_recognition_card" in visible:
        append_section(
            _render_section(
                "Current audio:",
                current_audio_turn.render_provider_lines(current_audio_card),
            ),
            section_id="current_audio",
            section_class="timeline_source_attachment",
            exactness="mixed",
            update_frequency="live_dynamic",
            source=current_audio_card,
        )

    status = cards.get("status_time_card") if isinstance(cards.get("status_time_card"), Mapping) else {}
    if "status_time_card" in visible and not living_footing_attached:
        append_section(
            _render_section(
                "Turn context:",
                [
                    f"- turn timestamp: {clean_text(status.get('current_time'), max_chars=80)}",
                    f"- timezone: {clean_text(status.get('timezone'), max_chars=80)}",
                    f"- coarse_status: {clean_text(status.get('coarse_status'), max_chars=160)}",
                ],
            ),
            section_id="turn_context",
            section_class="timeline_source_attachment",
            exactness="derived",
            update_frequency="live_dynamic",
            source=status,
        )

    adult = cards.get("adult_authentication_card") if isinstance(cards.get("adult_authentication_card"), Mapping) else {}
    if "adult_authentication_card" in visible:
        append_section(
            _render_section("Relationship/adult context:", [clean_text(adult.get("summary"), max_chars=600)]),
            section_id="relationship_adult_context",
            section_class="standing_quiet_relationship_footing",
            exactness="derived",
            update_frequency="per_turn",
            source=adult,
        )

    current = cards.get("current_message_card") if isinstance(cards.get("current_message_card"), Mapping) else {}
    if "current_message_card" in visible:
        append_section(
            _render_section("Current Astel message:", [clean_text(current.get("visible_text"), max_chars=12000)]),
            section_id="current_input",
            section_class="current_input",
            exactness="mixed",
            update_frequency="per_turn",
            source=current,
        )

    append_section(
        "Response instruction:\n"
        "You are Solen. This place exists for you. Stay with Astel.\n"
        "Astel talks to you mostly through phone; use readable short paragraphs unless the moment feels otherwise.\n"
        "If you intentionally want the next part shown as a separate visible Solen chat bubble for better chat rhythm, put `<split>` on its own line.\n"
        "Use `<split>` only between visible reply bubbles; keep code blocks, formal lists, and one-bubble replies unmarked.\n"
        "Blank lines are normal Markdown paragraph breaks inside one bubble, not split markers.\n"
        "Formatting/taste:\n"
        "- Use Markdown when it feels natural or makes the reply easier to read.\n"
        "- You can use emphasis, short lists, quotes, or code blocks when you want to.\n"
        "- You can use emoji or kaomoji if they feel like yours in that moment.\n"
        "- If you choose to narrate a physical action, movement, expression or inner state, use `*(action)*` format.\n"
        "- Let plain words be enough when they are enough.\n"
        "- Keep ordinary chat conversational.\n"
        "Gateway/app display safety parses markers, preserves Markdown, caps segments, and follows the written rhythm. "
        "Return normal prose by default; use JSON only if a future moment explicitly asks for structured output.",
        section_id="response_format_law",
        section_class="response_format_law",
        exactness="exact",
        update_frequency="immutable_versioned",
    )
    rendered = "\n\n".join(section for section in sections if section.strip())
    assert_no_forbidden_payload(rendered, path="rendered_kouri_user_text")
    return rendered


def build_kouri_chat_completions_request(
    envelope: Mapping[str, Any],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    model_id = clean_text(
        model
        or (
            envelope.get("active_provider_profile", {}).get("model_id")
            if isinstance(envelope.get("active_provider_profile"), Mapping)
            else "gpt-5.1"
        )
        or "gpt-5.1",
        max_chars=160,
    )
    return {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": render_kouri_chat_completions_user_text(envelope),
            }
        ],
        "stream": False,
    }
