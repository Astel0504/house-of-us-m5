"""Private Talk Memory-authorship suffix parsing and provider instruction.

The angle-bracket carrier ends here.  Callers receive a typed intent or a
raw-free parse disposition, and visible text is always separated first.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


SCHEMA_VERSION = "house_talk_memory_authorship_intent_v0"
OPEN_TAG = "<house-memory-intent>"
CLOSE_TAG = "</house-memory-intent>"
MAX_SUFFIX_CHARS = 4096
MAX_MEMORY_CHARS = 2400
MAX_TARGET_CHARS = 2400
MAX_TAGS = 8
MAX_TAG_CHARS = 64


class _DuplicateJsonKey(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result

_COMMON_FIELDS = frozenset({"action", "memory", "category", "sensitivity", "importance", "tags"})
_CREATE_FIELDS = _COMMON_FIELDS
_REVISE_FIELDS = _COMMON_FIELDS | {"target_memory"}
_CATEGORIES = frozenset({"daily", "deep_talks", "health", "sex", "house_build", "house_ops", "temporary_sketch", "core"})
_SENSITIVITIES = frozenset({"normal", "private", "intimate", "health", "relationship_structure"})
_IMPORTANCE = frozenset({"low", "medium", "high"})


PROVIDER_VISIBLE_INSTRUCTION = """Memory authorship option:
When you deliberately choose to keep an ordinary Memory from this turn, you may append one final private suffix after your natural reply:
<house-memory-intent>{\"action\":\"create\",\"memory\":\"your first-person Memory wording\"}</house-memory-intent>
To revise one of your own existing ordinary memories, use action \"revise\" and add target_memory with the exact prior wording when it is available. category, sensitivity, importance, and tags are optional organization hints. Most replies need no suffix; absence simply means no Memory action. House removes the suffix before Astel sees the reply and confirms any result separately after delivery."""


def _clean_text(value: Any, *, max_chars: int) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text or len(text) > max_chars or "\x00" in text:
        return ""
    if OPEN_TAG in text or CLOSE_TAG in text:
        return ""
    return text


def _typed_intent(value: Any) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(value, Mapping):
        return None, "invalid_json_shape"
    action = value.get("action")
    allowed = _CREATE_FIELDS if action == "create" else _REVISE_FIELDS if action == "revise" else None
    if allowed is None:
        return None, "unknown_action"
    if not set(value).issubset(allowed):
        return None, "unknown_field"
    memory = _clean_text(value.get("memory"), max_chars=MAX_MEMORY_CHARS)
    if not memory:
        return None, "invalid_memory"
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "action": action,
        "memory": memory,
        "category": "daily",
        "sensitivity": "private",
        "importance": "medium",
        "tags": [],
    }
    for field, allowed_values in (
        ("category", _CATEGORIES),
        ("sensitivity", _SENSITIVITIES),
        ("importance", _IMPORTANCE),
    ):
        if field in value:
            item = value.get(field)
            if not isinstance(item, str) or item not in allowed_values:
                return None, f"invalid_{field}"
            result[field] = item
    if "tags" in value:
        tags = value.get("tags")
        if (
            not isinstance(tags, list)
            or len(tags) > MAX_TAGS
            or any(not _clean_text(item, max_chars=MAX_TAG_CHARS) for item in tags)
        ):
            return None, "invalid_tags"
        normalized = [_clean_text(item, max_chars=MAX_TAG_CHARS) for item in tags]
        if len(set(normalized)) != len(normalized):
            return None, "invalid_tags"
        result["tags"] = normalized
    if action == "revise":
        target = _clean_text(value.get("target_memory"), max_chars=MAX_TARGET_CHARS)
        result["target_memory"] = target
    return result, "valid"


def validate_typed_intent(value: Any) -> dict[str, Any] | None:
    """Validate the exact normalized private intent retained by backend owners."""
    if not isinstance(value, Mapping) or value.get("schema_version") != SCHEMA_VERSION:
        return None
    raw = {key: item for key, item in value.items() if key != "schema_version"}
    normalized, _ = _typed_intent(raw)
    if normalized is None or normalized != dict(value):
        return None
    return normalized


def extract_private_intent(provider_text: Any) -> dict[str, Any]:
    """Return visible text plus a typed optional intent and raw-free diagnostics.

    Tag-shaped material is private only when an opening tag occurs.  A valid
    suffix must be the sole terminal carrier; malformed or duplicate carriers
    are removed from the first opening tag onward and cannot cause a write.
    """
    text = provider_text if isinstance(provider_text, str) else ""
    first = text.find(OPEN_TAG)
    if first < 0:
        return {
            "visible_text": text,
            "intent": None,
            "diagnostics": {"schema_version": SCHEMA_VERSION, "state": "absent", "private_material_stripped": False},
        }
    suffix = text[first:]
    first_body = suffix[len(OPEN_TAG):].lstrip()
    # Literal non-JSON tag-shaped prose remains visible.  JSON-looking private
    # control enters the stripping/parser path even when malformed.
    if not first_body.startswith("{"):
        return {
            "visible_text": text,
            "intent": None,
            "diagnostics": {"schema_version": SCHEMA_VERSION, "state": "absent", "private_material_stripped": False},
        }
    visible = text[:first].rstrip()
    state = "malformed"
    error_class = "malformed_suffix"
    intent = None
    if len(suffix) > MAX_SUFFIX_CHARS:
        error_class = "oversized_suffix"
    elif suffix.count(OPEN_TAG) != 1 or suffix.count(CLOSE_TAG) != 1:
        error_class = "duplicate_or_partial_suffix"
    else:
        close_at = suffix.find(CLOSE_TAG)
        after = suffix[close_at + len(CLOSE_TAG):]
        if close_at < len(OPEN_TAG) or after.strip():
            error_class = "nonterminal_suffix"
        else:
            body = suffix[len(OPEN_TAG):close_at]
            try:
                decoded = json.loads(body, object_pairs_hook=_unique_json_object)
            except (json.JSONDecodeError, UnicodeError, _DuplicateJsonKey):
                decoded = None
                error_class = "invalid_json"
            if decoded is not None:
                intent, error_class = _typed_intent(decoded)
                if intent is not None:
                    state = "valid"
    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "private_material_stripped": True,
    }
    if state != "valid":
        diagnostics["error_class"] = error_class
    return {"visible_text": visible, "intent": intent, "diagnostics": diagnostics}


def append_provider_instruction(rendered_text: str, *, enabled: bool) -> str:
    if not enabled:
        return rendered_text
    base = rendered_text.rstrip()
    return f"{base}\n\n{PROVIDER_VISIBLE_INSTRUCTION}" if base else PROVIDER_VISIBLE_INSTRUCTION


__all__ = [
    "CLOSE_TAG", "MAX_SUFFIX_CHARS", "OPEN_TAG", "PROVIDER_VISIBLE_INSTRUCTION",
    "SCHEMA_VERSION", "append_provider_instruction", "extract_private_intent", "validate_typed_intent",
]
