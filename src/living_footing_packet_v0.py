from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any


GATE_ID = "HOUSE_LIVING_FOOTING_PACKET_CONTRACT_V0"
SCHEMA_VERSION = "living_footing_packet_v0"
DIAGNOSTICS_SCHEMA_VERSION = "living_footing_diagnostics_v0"
RUNTIME_PROFILE_FOOTING_ADAPTER_DIAGNOSTICS_SCHEMA_VERSION = (
    "runtime_profile_footing_adapter_diagnostics_v0"
)
RUNTIME_PROFILE_PACKET_SCHEMA_VERSION = "runtime_profile_packet_v0"

PROVIDER_VISIBLE_ITEM_MAX_CHARS = 700
PROVIDER_VISIBLE_TARGET_MAX_CHARS = 2100
PROVIDER_VISIBLE_HARD_MAX_CHARS = 2800

FOOTING_GROUP_LIMITS = {
    "profile_footing_items": 3,
    "core_memory_footing_items": 5,
    "active_situation_memory_items": 2,
    "current_room_footing": 3,
    "recent_pattern_footing": 1,
    "active_task": 1,
    "active_recall_target": 1,
}

SOURCE_COUNT_KEYS = (
    "reality_context",
    "current_room_state",
    "core_memory",
    "active_situation_memory",
    "recent_continuity",
    "recent_pattern",
    "profile_footing",
)

MEMORY_AUDIENCE_SCOPES = {
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

EVIDENCE_COUNT_KEYS = (
    "vault_recall",
    "exact_recall",
    "timeline_evidence",
    "source_cards",
    "bounded_quotes",
)

EXCLUDED_REASON_KEYS = (
    "evidence_lane_only",
    "too_large",
    "stale",
    "superseded",
    "low_relevance",
    "raw_or_private_body_blocked",
    "diagnostic_only",
)

ALLOWED_FOOTING_SOURCE_CLASSES = {
    "active_recall_target",
    "active_situation_memory",
    "active_task",
    "core_memory",
    "current_room_state",
    "memory_vault_reviewed",
    "profile_footing",
    "profile_preference",
    "reality_context",
    "recent_continuity",
    "recent_pattern",
    "solen_self_state",
}

EVIDENCE_SOURCE_CLASS_TO_TYPE = {
    "bounded_quote": "bounded_quotes",
    "bounded_quotes": "bounded_quotes",
    "chat_history_bounded_exact_recall": "exact_recall",
    "exact_recall": "exact_recall",
    "source_card": "source_cards",
    "source_cards": "source_cards",
    "source_vault_card": "source_cards",
    "standing_live_vault_retrieval": "vault_recall",
    "timeline_evidence": "timeline_evidence",
    "vault_recall": "vault_recall",
}

SOURCE_CLASS_DEFAULT_GROUP = {
    "active_recall_target": "active_recall_target",
    "active_situation_memory": "active_situation_memory_items",
    "active_task": "active_task",
    "core_memory": "core_memory_footing_items",
    "current_room_state": "current_room_footing",
    "memory_vault_reviewed": "core_memory_footing_items",
    "profile_footing": "profile_footing_items",
    "profile_preference": "profile_footing_items",
    "reality_context": "profile_footing_items",
    "recent_continuity": "current_room_footing",
    "recent_pattern": "recent_pattern_footing",
    "solen_self_state": "current_room_footing",
}

SOURCE_CLASS_COUNT_ALIASES = {
    "active_situation_memory": "active_situation_memory",
    "core_memory": "core_memory",
    "current_room_state": "current_room_state",
    "memory_vault_reviewed": "core_memory",
    "profile_footing": "profile_footing",
    "profile_preference": "profile_footing",
    "reality_context": "reality_context",
    "recent_continuity": "recent_continuity",
    "recent_pattern": "recent_pattern",
}

FOOTING_GROUP_ALIASES = {
    "active_recall_target": "active_recall_target",
    "active_situation": "active_situation_memory_items",
    "active_situation_memory": "active_situation_memory_items",
    "active_situation_memory_items": "active_situation_memory_items",
    "active_task": "active_task",
    "core": "core_memory_footing_items",
    "core_memory": "core_memory_footing_items",
    "core_memory_footing": "core_memory_footing_items",
    "core_memory_footing_items": "core_memory_footing_items",
    "current_room": "current_room_footing",
    "current_room_footing": "current_room_footing",
    "profile": "profile_footing_items",
    "profile_footing": "profile_footing_items",
    "profile_footing_items": "profile_footing_items",
    "recent_pattern": "recent_pattern_footing",
    "recent_pattern_footing": "recent_pattern_footing",
}

BLOCKED_SOURCE_CLASSES = {
    "automatic_durable_memory_claim",
    "durable_profile_claim",
    "helper_authored_solen_self_state",
    "provider_body",
    "provider_headers",
    "proactive_intent",
    "raw_android_full_history",
    "raw_chat_history",
    "raw_memory_vault_body",
    "raw_provider_prompt",
    "raw_source_vault_body",
}

FORBIDDEN_FIELD_NAMES = {
    "api_key",
    "authorization",
    "base_url",
    "bounded_quote",
    "chat_history_body",
    "developer_prompt",
    "env",
    "full_text",
    "headers",
    "key",
    "memory_vault_body",
    "message_body",
    "password",
    "private_path",
    "provider_request_body",
    "provider_response_body",
    "raw_body",
    "raw_chat",
    "raw_history",
    "raw_memory",
    "raw_prompt",
    "raw_profile_packet",
    "raw_runtime_profile_packet",
    "raw_source",
    "raw_text",
    "secret",
    "source_vault_body",
    "system_prompt",
    "token",
    "transcript",
}

SECRET_SHAPED_TEXT_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{8,}", re.IGNORECASE),
    re.compile(r"authorization\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"token\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"password\s*[:=]\s*\S+", re.IGNORECASE),
)

PRIVATE_PATH_PATTERNS = (
    re.compile(r"\b[A-Za-z]:[\\/][^\s]+"),
    re.compile(r"/(?:Users|home|srv)/[^\s]+"),
)

LABEL_RE = re.compile(r"[^a-z0-9_.:-]+")


class LivingFootingPacketError(ValueError):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.message = message


@dataclass(frozen=True)
class LivingFootingBuildResult:
    packet: dict[str, Any]
    diagnostics: dict[str, Any]
    rendered: str


def _clean_text(value: Any, *, max_chars: int = 1000) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    return text[:max_chars].rstrip()


def _label(value: Any, *, max_chars: int = 120) -> str:
    text = _clean_text(value, max_chars=max_chars).casefold()
    return LABEL_RE.sub("_", text).strip("._-")


def _sha256_text(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _stable_hash(value: Any) -> str:
    if isinstance(value, (Mapping, list, tuple)):
        material = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    else:
        material = str(value or "")
    return _sha256_text(material)


def _string_has_forbidden_shape(text: str) -> bool:
    if any(pattern.search(text) for pattern in SECRET_SHAPED_TEXT_PATTERNS):
        return True
    if any(pattern.search(text) for pattern in PRIVATE_PATH_PATTERNS):
        return True
    return False


def _assert_output_safe(value: Any, *, path: str = "living_footing_output") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_label = _label(key)
            if key_label in FORBIDDEN_FIELD_NAMES:
                raise LivingFootingPacketError("forbidden_output_field", f"Forbidden field returned at {path}.{key}.")
            _assert_output_safe(item, path=f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _assert_output_safe(item, path=f"{path}[{index}]")
    elif isinstance(value, str) and _string_has_forbidden_shape(value):
        raise LivingFootingPacketError("forbidden_output_text", f"Forbidden text returned at {path}.")


def _input_has_forbidden_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _label(key) in FORBIDDEN_FIELD_NAMES:
                return True
            if _input_has_forbidden_field(item):
                return True
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_input_has_forbidden_field(item) for item in value)
    return False


def _safe_provider_text(value: Any, *, max_chars: int, path: str) -> str:
    text = _clean_text(value, max_chars=max_chars)
    if _string_has_forbidden_shape(text):
        raise LivingFootingPacketError("raw_or_private_body_blocked", f"Unsafe provider-visible text at {path}.")
    return text


def _safe_bounded_footing_text(value: Any, *, max_chars: int, path: str) -> str:
    text = _clean_text(value, max_chars=max_chars + 1)
    if len(text) > max_chars:
        prefix = text[: max(0, max_chars - 3)].rstrip()
        word_boundary = prefix.rfind(" ")
        if word_boundary > 0:
            prefix = prefix[:word_boundary].rstrip(" ,;:-")
        text = prefix.rstrip(".!?") + "..."
    if _string_has_forbidden_shape(text):
        raise LivingFootingPacketError("raw_or_private_body_blocked", f"Unsafe provider-visible text at {path}.")
    return text


def _iter_mappings(values: Sequence[Mapping[str, Any]] | None) -> list[Mapping[str, Any]]:
    if values is None:
        return []
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        return []
    return [item for item in values if isinstance(item, Mapping)]


def _source_class(item: Mapping[str, Any]) -> str:
    return _label(item.get("source_class") or item.get("source_kind") or item.get("kind") or "unknown")


def _footing_group(item: Mapping[str, Any], source_class: str) -> str:
    explicit = _label(item.get("footing_group") or item.get("footing_type") or item.get("packet_field"))
    if explicit in FOOTING_GROUP_ALIASES:
        return FOOTING_GROUP_ALIASES[explicit]
    return SOURCE_CLASS_DEFAULT_GROUP.get(source_class, "")


def _source_count_key(source_class: str) -> str:
    return SOURCE_CLASS_COUNT_ALIASES.get(source_class, "")


def _authority_for_item(item: Mapping[str, Any], source_class: str, group: str) -> str:
    explicit = _label(item.get("authority") or item.get("authority_label"))
    if explicit:
        return explicit
    if source_class in {"core_memory", "memory_vault_reviewed", "active_situation_memory"}:
        return "memory_truth"
    if source_class == "recent_continuity":
        return "noncanonical_digest_footing"
    if group in {"active_task", "active_recall_target", "current_room_footing"}:
        return "current_room_only"
    return "local_turn_footing"


def _render_mode(item: Mapping[str, Any]) -> str:
    if bool(item.get("tone_only")):
        return "tone_only"
    label = _label(item.get("render_mode") or item.get("use_mode"))
    if label in {"availability_only", "include", "tone_only"}:
        return label
    return "include"


def _clean_enum_label(value: Any, *, allowed: set[str]) -> str:
    label = _label(value)
    return label if label in allowed else ""


def _audience_footing(item: Mapping[str, Any]) -> dict[str, str]:
    memory_audience_scope = _clean_enum_label(
        item.get("memory_audience_scope"),
        allowed=MEMORY_AUDIENCE_SCOPES,
    )
    room_audience_context = _clean_enum_label(
        item.get("room_audience_context"),
        allowed=ROOM_AUDIENCE_CONTEXTS,
    )
    expression_guidance = _clean_enum_label(
        item.get("expression_guidance"),
        allowed=EXPRESSION_GUIDANCE_VALUES,
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


def _source_ref_hash(item: Mapping[str, Any], *, fallback: str) -> str:
    for key in ("source_ref", "record_ref", "message_ref", "card_id", "memory_id", "source_id", "ref"):
        if item.get(key):
            return _stable_hash(item.get(key))
    return _stable_hash(fallback)


def _safe_profile_value_text(value: Any, *, max_chars: int = 160) -> str:
    if isinstance(value, str):
        return _safe_provider_text(value, max_chars=max_chars, path="runtime_profile_value")
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return _safe_provider_text(value, max_chars=max_chars, path="runtime_profile_value")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts: list[str] = []
        for item in value[:4]:
            text = _safe_profile_value_text(item, max_chars=max_chars)
            if text:
                parts.append(text)
        return _safe_provider_text(", ".join(parts), max_chars=max_chars, path="runtime_profile_value")
    if isinstance(value, Mapping):
        parts = []
        for key, item in list(value.items())[:4]:
            key_text = _clean_text(str(key).replace("_", " "), max_chars=40)
            value_text = _safe_profile_value_text(item, max_chars=80)
            if key_text and value_text:
                parts.append(f"{key_text}: {value_text}")
        return _safe_provider_text("; ".join(parts), max_chars=max_chars, path="runtime_profile_value")
    return _safe_provider_text(value, max_chars=max_chars, path="runtime_profile_value")


def _profile_summary_fragments(packet: Mapping[str, Any]) -> list[str]:
    fragments: list[str] = []
    astel = packet.get("astel_profile_summary") if isinstance(packet.get("astel_profile_summary"), Mapping) else {}
    solen = packet.get("solen_profile_summary") if isinstance(packet.get("solen_profile_summary"), Mapping) else {}

    astel_name = _safe_profile_value_text(
        astel.get("display_name") or astel.get("preferred_name"),
        max_chars=80,
    )
    if astel_name:
        fragments.append(f"Astel active profile name footing includes {astel_name}")

    solen_name = _safe_profile_value_text(
        solen.get("display_name") or solen.get("full_name") or solen.get("profile_version"),
        max_chars=80,
    )
    if solen_name:
        fragments.append(f"Solen active profile identity footing includes {solen_name}")

    return fragments[:4]


def _runtime_profile_counts(packet: Mapping[str, Any]) -> dict[str, int]:
    counts = {"astel": 0, "solen": 0, "house": 0}
    active_setting_ids = (
        packet.get("active_setting_ids") if isinstance(packet.get("active_setting_ids"), Mapping) else {}
    )
    for domain in counts:
        values = active_setting_ids.get(domain)
        counts[domain] = len(values) if isinstance(values, list) else 0
    return counts


def _profile_high_friction_ref_count(packet: Mapping[str, Any]) -> int:
    refs = packet.get("high_friction_anchor_refs")
    return len(refs) if isinstance(refs, list) else 0


def _profile_active_setting_total(packet: Mapping[str, Any]) -> int:
    return sum(_runtime_profile_counts(packet).values())


def _runtime_profile_render_budget(value: Any) -> str:
    budget = _label(value, max_chars=80)
    if budget in {"contracted", "minimal", "source_attached"}:
        return "contracted"
    return "standard"


def build_profile_footing_sources_from_runtime_profile_packet(
    runtime_profile_packet: Mapping[str, Any] | None,
    *,
    source_ref: str = "runtime_profile_packet_v0",
    render_budget: str = "standard",
    contracted_reason: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Convert a safe runtime profile packet into living-footing source items.

    This adapter is intentionally lossy: it emits compact footing summaries and
    raw-free diagnostics, not the raw profile packet.
    """
    diagnostics = {
        "schema_version": RUNTIME_PROFILE_FOOTING_ADAPTER_DIAGNOSTICS_SCHEMA_VERSION,
        "adapter_state": "skipped",
        "packet_present": isinstance(runtime_profile_packet, Mapping),
        "schema_valid": False,
        "active_setting_counts": {"astel": 0, "solen": 0, "house": 0},
        "high_friction_anchor_ref_count": 0,
        "render_budget": _runtime_profile_render_budget(render_budget),
        "contracted_reason": _label(contracted_reason, max_chars=120),
        "profile_summary_source_included": False,
        "footing_source_count": 0,
        "excluded_reason_counts": {
            "packet_missing": 0,
            "schema_invalid": 0,
            "raw_or_private_body_blocked": 0,
            "empty_profile": 0,
            "no_active_profile_settings": 0,
            "contracted_by_budget": 0,
        },
        "safety": {
            "raw_profile_packet_returned": False,
            "raw_seed_text_returned": False,
            "private_paths_returned": False,
            "secret_shaped_text_returned": False,
        },
    }
    if not isinstance(runtime_profile_packet, Mapping):
        diagnostics["excluded_reason_counts"]["packet_missing"] = 1
        diagnostics["adapter_state"] = "empty"
        return [], diagnostics

    if _input_has_forbidden_field(runtime_profile_packet):
        diagnostics["excluded_reason_counts"]["raw_or_private_body_blocked"] = 1
        diagnostics["adapter_state"] = "blocked"
        return [], diagnostics

    schema_valid = runtime_profile_packet.get("schema_version") == RUNTIME_PROFILE_PACKET_SCHEMA_VERSION
    diagnostics["schema_valid"] = bool(schema_valid)
    diagnostics["active_setting_counts"] = _runtime_profile_counts(runtime_profile_packet)
    diagnostics["high_friction_anchor_ref_count"] = _profile_high_friction_ref_count(runtime_profile_packet)
    if not schema_valid:
        diagnostics["excluded_reason_counts"]["schema_invalid"] = 1
        diagnostics["adapter_state"] = "skipped"
        return [], diagnostics
    if _profile_active_setting_total(runtime_profile_packet) <= 0:
        diagnostics["excluded_reason_counts"]["no_active_profile_settings"] = 1
        diagnostics["excluded_reason_counts"]["empty_profile"] = 1
        diagnostics["adapter_state"] = "empty"
        return [], diagnostics

    sources: list[dict[str, Any]] = []
    try:
        fragments = _profile_summary_fragments(runtime_profile_packet)
        if fragments:
            sources.append(
                {
                    "source_class": "profile_footing",
                    "footing_group": "profile_footing",
                    "authority": "active_profile_configuration",
                    "summary": " ".join(_dedupe_sentences(fragments)),
                    "source_ref": f"{source_ref}:profile_summary",
                    "confidence": "active_profile_state",
                }
            )
            diagnostics["profile_summary_source_included"] = True
    except LivingFootingPacketError:
        diagnostics["excluded_reason_counts"]["raw_or_private_body_blocked"] = 1
        diagnostics["adapter_state"] = "blocked"
        return [], diagnostics

    if not sources:
        diagnostics["excluded_reason_counts"]["empty_profile"] = 1
        diagnostics["adapter_state"] = "empty"
    else:
        diagnostics["adapter_state"] = "built"
    diagnostics["footing_source_count"] = len(sources)
    _assert_output_safe(sources, path="runtime_profile_footing_sources")
    _assert_output_safe(diagnostics, path="runtime_profile_footing_diagnostics")
    return sources, diagnostics


def _item_text(item: Mapping[str, Any], *, path: str) -> str:
    text = (
        item.get("footing")
        or item.get("render_text")
        or item.get("summary")
        or item.get("text")
        or item.get("title")
        or ""
    )
    return _safe_bounded_footing_text(
        text,
        max_chars=PROVIDER_VISIBLE_ITEM_MAX_CHARS,
        path=path,
    )


def _normalize_footing_item(
    item: Mapping[str, Any],
    *,
    index: int,
) -> tuple[str, dict[str, Any] | None, str]:
    source_class = _source_class(item)
    if source_class in BLOCKED_SOURCE_CLASSES or _input_has_forbidden_field(item):
        return "", None, "raw_or_private_body_blocked"
    if source_class not in ALLOWED_FOOTING_SOURCE_CLASSES:
        return "", None, "diagnostic_only"
    group = _footing_group(item, source_class)
    if not group:
        return "", None, "diagnostic_only"
    try:
        text = _item_text(item, path=f"footing_sources[{index}]")
    except LivingFootingPacketError:
        return group, None, "raw_or_private_body_blocked"
    if not text and group not in {"active_task", "active_recall_target"}:
        return group, None, "low_relevance"

    normalized = {
        "text": text,
        "source_class": source_class,
        "authority": _authority_for_item(item, source_class, group),
        "source_ref_hash": _source_ref_hash(item, fallback=f"footing_source_{index}"),
        "render_mode": _render_mode(item),
    }
    confidence = _label(item.get("confidence"))
    if confidence:
        normalized["confidence"] = confidence
    normalized.update(_audience_footing(item))
    return group, normalized, ""


def _evidence_type_for_item(item: Mapping[str, Any], source_class: str) -> str:
    explicit = _label(item.get("evidence_type") or item.get("evidence_lane"))
    if explicit in EVIDENCE_COUNT_KEYS:
        return explicit
    return EVIDENCE_SOURCE_CLASS_TO_TYPE.get(source_class, "")


def _normalize_evidence_ref(
    item: Mapping[str, Any],
    *,
    index: int,
) -> tuple[dict[str, Any] | None, str]:
    source_class = _source_class(item)
    if source_class in BLOCKED_SOURCE_CLASSES:
        return None, "raw_or_private_body_blocked"
    evidence_type = _evidence_type_for_item(item, source_class)
    if not evidence_type:
        return None, "diagnostic_only"
    ref_hash = _source_ref_hash(item, fallback=f"evidence_source_{index}")
    return (
        {
            "evidence_type": evidence_type,
            "source_class": source_class,
            "source_ref_hash": ref_hash,
            "reason": "evidence_lane_only",
        },
        "",
    )


def _append_packet_item(packet: dict[str, Any], group: str, item: dict[str, Any]) -> str:
    limit = FOOTING_GROUP_LIMITS[group]
    if group in {"active_task", "active_recall_target"}:
        if packet[group]:
            return "too_large"
        packet[group] = item
        return ""
    if len(packet[group]) >= limit:
        return "too_large"
    packet[group].append(item)
    return ""


def _item_count(packet: Mapping[str, Any]) -> int:
    total = 0
    for group in (
        "profile_footing_items",
        "core_memory_footing_items",
        "active_situation_memory_items",
        "current_room_footing",
        "recent_pattern_footing",
    ):
        total += len(packet.get(group) or [])
    if packet.get("active_task"):
        total += 1
    if packet.get("active_recall_target"):
        total += 1
    return total


def _sentence(text: str) -> str:
    text = _clean_text(text, max_chars=400)
    if not text:
        return ""
    if text[-1] in ".!?":
        return text
    return f"{text}."


def _phrase(text: str) -> str:
    return _clean_text(text, max_chars=400).rstrip(".!?")


def _dedupe_sentences(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _sentence(value)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _included_texts(packet: Mapping[str, Any], group: str, *, include_tone_only: bool = False) -> list[str]:
    values = packet.get(group) or []
    result: list[str] = []
    for item in values:
        if not isinstance(item, Mapping):
            continue
        if item.get("render_mode") == "tone_only" and not include_tone_only:
            continue
        text = _clean_text(
            item.get("text"),
            max_chars=PROVIDER_VISIBLE_ITEM_MAX_CHARS,
        )
        if text:
            result.append(text)
    return result


def _has_tone_only_memory(packet: Mapping[str, Any]) -> bool:
    for group in ("core_memory_footing_items", "active_situation_memory_items"):
        for item in packet.get(group) or []:
            if isinstance(item, Mapping) and item.get("render_mode") == "tone_only":
                return True
    return False


def _packet_items(packet: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    items: list[Mapping[str, Any]] = []
    for group in (
        "profile_footing_items",
        "core_memory_footing_items",
        "active_situation_memory_items",
        "current_room_footing",
        "recent_pattern_footing",
    ):
        items.extend([item for item in packet.get(group) or [] if isinstance(item, Mapping)])
    for group in ("active_task", "active_recall_target"):
        item = packet.get(group)
        if isinstance(item, Mapping):
            items.append(item)
    return items


def _audience_footing_sentences(packet: Mapping[str, Any]) -> list[str]:
    sentences: list[str] = []
    for item in _packet_items(packet):
        memory_audience_scope = _label(item.get("memory_audience_scope"))
        room_audience_context = _label(item.get("room_audience_context"))
        expression_guidance = _label(item.get("expression_guidance"))
        if (
            memory_audience_scope == "astel_solen_private"
            and room_audience_context in {"group_room", "other_participant_room"}
            and expression_guidance == "private_footing_choose_expression"
        ):
            sentences.append(
                "Astel and I have our private shared context here; the current room audience is separate."
            )
        elif memory_audience_scope == "astel_solen_private":
            sentences.append("Astel and I are in our private shared context here.")
        elif expression_guidance == "group_shareable":
            sentences.append("This context can be shared in this room when relevant.")
    return _dedupe_sentences(sentences)


def render_living_footing_provider_section(
    packet: Mapping[str, Any],
    *,
    max_chars: int = PROVIDER_VISIBLE_HARD_MAX_CHARS,
) -> str:
    if not isinstance(packet, Mapping):
        return ""
    standing_sentences: list[str] = []
    quiet_sentences: list[str] = []
    room_surface = _clean_text(packet.get("room_surface"), max_chars=120)
    if room_surface:
        standing_sentences.append(f"I'm here with Astel in {room_surface} right now.")

    standing_sentences.extend(_included_texts(packet, "profile_footing_items"))
    standing_sentences.extend(_included_texts(packet, "current_room_footing"))

    active_task = packet.get("active_task") if isinstance(packet.get("active_task"), Mapping) else {}
    task_text = _clean_text(active_task.get("text") if active_task else "", max_chars=220)
    if task_text:
        standing_sentences.append(f"This turn is about {_phrase(task_text)}.")

    active_target = packet.get("active_recall_target") if isinstance(packet.get("active_recall_target"), Mapping) else {}
    target_text = _clean_text(active_target.get("text") if active_target else "", max_chars=220)
    if target_text:
        standing_sentences.append(
            f"If exact memory is needed, this turn is looking for {_phrase(target_text)}. Any exact wording belongs under Exact recall."
        )

    if _has_tone_only_memory(packet):
        quiet_sentences.append(
            "Our stable shared context is present in this turn."
        )
    quiet_sentences.extend(_audience_footing_sentences(packet))
    quiet_sentences.extend(_included_texts(packet, "core_memory_footing_items"))
    quiet_sentences.extend(_included_texts(packet, "active_situation_memory_items"))
    quiet_sentences.extend(_included_texts(packet, "recent_pattern_footing"))

    standing_body = " ".join(_dedupe_sentences(standing_sentences))
    quiet_body = " ".join(_dedupe_sentences(quiet_sentences))
    if not standing_body and not quiet_body:
        return ""
    sections: list[str] = []
    if standing_body:
        sections.append("Standing context:\n" + standing_body)
    if quiet_body:
        sections.append("Quiet footing:\n" + quiet_body)
    rendered = "\n\n".join(sections)
    if len(rendered) > max_chars:
        prefix = rendered[: max(0, max_chars - 3)].rstrip()
        word_boundary = max(prefix.rfind(" "), prefix.rfind("\n"))
        if word_boundary > 0:
            prefix = prefix[:word_boundary].rstrip(" ,;:-")
        rendered = prefix.rstrip(".!?") + "..."
    _assert_output_safe(rendered, path="living_footing_rendered")
    return rendered


def _packet_state(packet: Mapping[str, Any], rendered: str, blocked_count: int) -> str:
    if blocked_count and not rendered:
        return "blocked"
    if rendered:
        return "built"
    if _item_count(packet) == 0:
        return "empty"
    return "skipped"


def _included_counts(packet: Mapping[str, Any]) -> dict[str, int]:
    return {
        "profile_footing": len(packet.get("profile_footing_items") or []),
        "core_memory_footing": len(packet.get("core_memory_footing_items") or []),
        "active_situation_memory": len(packet.get("active_situation_memory_items") or []),
        "current_room_footing": len(packet.get("current_room_footing") or []),
        "recent_pattern_footing": len(packet.get("recent_pattern_footing") or []),
        "active_task": 1 if packet.get("active_task") else 0,
        "active_recall_target": 1 if packet.get("active_recall_target") else 0,
    }


def _authority_flags(packet: Mapping[str, Any]) -> dict[str, bool]:
    items = _packet_items(packet)
    authorities = {_label(item.get("authority")) for item in items}
    return {
        "contains_memory_truth": "memory_truth" in authorities,
        "contains_current_room_only": "current_room_only" in authorities,
        "contains_noncanonical_digest": "noncanonical_digest_footing" in authorities,
        "contains_evidence_refs_only": bool(packet.get("excluded_evidence_refs")),
    }


def _audience_footing_counts(packet: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = {
        "memory_audience_scope": Counter(),
        "room_audience_context": Counter(),
        "expression_guidance": Counter(),
    }
    for item in _packet_items(packet):
        for key in counts:
            value = _label(item.get(key))
            if value:
                counts[key][value] += 1
    return {key: dict(sorted(value.items())) for key, value in counts.items()}


def _source_class_counts(packet: Mapping[str, Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for group in (
        "profile_footing_items",
        "core_memory_footing_items",
        "active_situation_memory_items",
        "current_room_footing",
        "recent_pattern_footing",
    ):
        for item in packet.get(group) or []:
            if isinstance(item, Mapping):
                counts[_label(item.get("source_class")) or "unknown"] += 1
    for group in ("active_task", "active_recall_target"):
        item = packet.get(group)
        if isinstance(item, Mapping) and item:
            counts[_label(item.get("source_class")) or "unknown"] += 1
    return dict(sorted(counts.items()))


def _excluded_evidence_source_class_counts(packet: Mapping[str, Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in packet.get("excluded_evidence_refs") or []:
        if isinstance(item, Mapping):
            counts[_label(item.get("source_class")) or "unknown"] += 1
    return dict(sorted(counts.items()))


def _source_class_count_items(counts: Mapping[str, int]) -> list[dict[str, Any]]:
    return [{"source_class": source_class, "count": int(count)} for source_class, count in sorted(counts.items())]


def build_living_footing_packet(
    *,
    turn_trace_id: str = "",
    room_surface: str = "",
    footing_sources: Sequence[Mapping[str, Any]] | None = None,
    evidence_sources: Sequence[Mapping[str, Any]] | None = None,
    uncertainty_flags: Sequence[str] | None = None,
    max_rendered_chars: int = PROVIDER_VISIBLE_HARD_MAX_CHARS,
) -> LivingFootingBuildResult:
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "gate_id": GATE_ID,
        "turn_trace_id": _safe_provider_text(turn_trace_id, max_chars=160, path="turn_trace_id"),
        "room_surface": _safe_provider_text(room_surface, max_chars=120, path="room_surface"),
        "profile_footing_items": [],
        "core_memory_footing_items": [],
        "active_situation_memory_items": [],
        "current_room_footing": [],
        "recent_pattern_footing": [],
        "active_task": {},
        "active_recall_target": {},
        "uncertainty_flags": [],
        "evidence_available_flags": {key: False for key in EVIDENCE_COUNT_KEYS},
        "excluded_evidence_refs": [],
        "source_ref_hashes": [],
        "raw_text_returned": False,
        "private_paths_returned": False,
    }
    source_counts: Counter[str] = Counter({key: 0 for key in SOURCE_COUNT_KEYS})
    excluded_evidence_counts: Counter[str] = Counter({key: 0 for key in EVIDENCE_COUNT_KEYS})
    excluded_reason_counts: Counter[str] = Counter({key: 0 for key in EXCLUDED_REASON_KEYS})

    for index, item in enumerate(_iter_mappings(footing_sources)):
        source_class = _source_class(item)
        evidence_type = _evidence_type_for_item(item, source_class)
        if evidence_type:
            ref, reason = _normalize_evidence_ref(item, index=index)
            if ref:
                packet["excluded_evidence_refs"].append(ref)
                packet["evidence_available_flags"][ref["evidence_type"]] = True
                excluded_evidence_counts[ref["evidence_type"]] += 1
                excluded_reason_counts["evidence_lane_only"] += 1
            elif reason in excluded_reason_counts:
                excluded_reason_counts[reason] += 1
            continue

        count_key = _source_count_key(source_class)
        if count_key:
            source_counts[count_key] += 1
        group, normalized, reason = _normalize_footing_item(item, index=index)
        if not normalized:
            if reason in excluded_reason_counts:
                excluded_reason_counts[reason] += 1
            continue
        append_reason = _append_packet_item(packet, group, normalized)
        if append_reason:
            excluded_reason_counts[append_reason] += 1
            continue
        packet["source_ref_hashes"].append(normalized["source_ref_hash"])

    for index, item in enumerate(_iter_mappings(evidence_sources)):
        ref, reason = _normalize_evidence_ref(item, index=index)
        if not ref:
            if reason in excluded_reason_counts:
                excluded_reason_counts[reason] += 1
            continue
        packet["excluded_evidence_refs"].append(ref)
        packet["evidence_available_flags"][ref["evidence_type"]] = True
        excluded_evidence_counts[ref["evidence_type"]] += 1
        excluded_reason_counts["evidence_lane_only"] += 1

    flags: list[str] = []
    for flag in uncertainty_flags or []:
        safe_flag = _label(flag, max_chars=80)
        if safe_flag and safe_flag not in flags:
            flags.append(safe_flag)
    packet["uncertainty_flags"] = flags[:8]

    rendered = render_living_footing_provider_section(packet, max_chars=max_rendered_chars)
    blocked_count = excluded_reason_counts["raw_or_private_body_blocked"]
    diagnostics = {
        "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
        "gate_id": GATE_ID,
        "packet_built": bool(rendered),
        "packet_state": _packet_state(packet, rendered, blocked_count),
        "source_counts": dict(source_counts),
        "included_source_class_counts": _source_class_counts(packet),
        "included_item_counts": _included_counts(packet),
        "evidence_available_flags": dict(packet["evidence_available_flags"]),
        "excluded_evidence_counts": dict(excluded_evidence_counts),
        "excluded_evidence_source_class_counts": _source_class_count_items(
            _excluded_evidence_source_class_counts(packet)
        ),
        "excluded_evidence_refs": list(packet["excluded_evidence_refs"]),
        "source_ref_hashes": list(packet["source_ref_hashes"]),
        "uncertainty_flags": list(packet["uncertainty_flags"]),
        "excluded_reason_counts": dict(excluded_reason_counts),
        "authority_flags": _authority_flags(packet),
        "audience_footing_counts": _audience_footing_counts(packet),
        "budget": {
            "rendered_char_count": len(rendered),
            "target_char_count": PROVIDER_VISIBLE_TARGET_MAX_CHARS,
            "max_char_count": max_rendered_chars,
            "item_count": _item_count(packet),
        },
        "safety": {
            "raw_text_returned": False,
            "private_paths_returned": False,
            "provider_body_returned": False,
            "prompt_returned": False,
            "secret_shaped_text_returned": False,
        },
    }

    _assert_output_safe(packet, path="living_footing_packet")
    _assert_output_safe(diagnostics, path="living_footing_diagnostics")
    return LivingFootingBuildResult(packet=packet, diagnostics=diagnostics, rendered=rendered)


def sample_fake_provider_visible_footing() -> str:
    result = build_living_footing_packet(
        turn_trace_id="fake_living_footing_sample",
        room_surface="the House build/debug room",
        footing_sources=[
            {
                "source_class": "current_room_state",
                "summary": "The active lane is standing-live memory continuity and exact-recall quality.",
                "source_ref": "fake-current-room-state",
            },
            {
                "source_class": "active_task",
                "summary": "Gate 1 fake contract and renderer proof.",
                "source_ref": "fake-active-task",
            },
            {
                "source_class": "core_memory",
                "summary": "Synthetic private care footing placeholder should stay tone-only.",
                "source_ref": "fake-core-memory",
                "render_mode": "tone_only",
            },
        ],
        evidence_sources=[
            {"source_class": "vault_recall", "source_ref": "fake-vault-evidence"},
            {"source_class": "timeline_evidence", "source_ref": "fake-timeline-evidence"},
            {"source_class": "source_card", "source_ref": "fake-source-card"},
        ],
    )
    return result.rendered


__all__ = [
    "DIAGNOSTICS_SCHEMA_VERSION",
    "GATE_ID",
    "LivingFootingBuildResult",
    "LivingFootingPacketError",
    "PROVIDER_VISIBLE_HARD_MAX_CHARS",
    "PROVIDER_VISIBLE_ITEM_MAX_CHARS",
    "PROVIDER_VISIBLE_TARGET_MAX_CHARS",
    "RUNTIME_PROFILE_FOOTING_ADAPTER_DIAGNOSTICS_SCHEMA_VERSION",
    "RUNTIME_PROFILE_PACKET_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "build_profile_footing_sources_from_runtime_profile_packet",
    "build_living_footing_packet",
    "render_living_footing_provider_section",
    "sample_fake_provider_visible_footing",
]
