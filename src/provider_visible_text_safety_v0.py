"""Canonical provider-visible credential-shaped text safety policy."""

from __future__ import annotations

import re
from typing import Any, Match


REDACTION_MARKER = "[redacted-local-secret]"
_TOKEN_CHARS = r"A-Za-z0-9._~+/=\-"
_SAFE_LABELS = {
    "password_policy",
    "token_count",
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


def is_sensitive_label(value: Any) -> bool:
    """Classify an exact credential label without matching embedded prose words."""
    label = str(value or "").strip().strip("\"'").casefold()
    if not label or label in _SAFE_LABELS:
        return False
    if label in {"authorization", "cookie", "set-cookie"}:
        return True
    parts = [part for part in re.split(r"[_-]+", label) if part]
    if not parts:
        return False
    if label == "apikey" or parts[-2:] == ["api", "key"]:
        return True
    if label == "token" or (len(parts) > 1 and parts[-1] == "token"):
        return True
    if label == "password" or (len(parts) > 1 and parts[-1] == "password"):
        return True
    if label == "secret" or (len(parts) > 1 and parts[-1] == "secret"):
        return True
    return False


_SK_KEY = re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])")
_AUTHORIZATION = re.compile(
    rf"(?<![A-Za-z0-9_-])"
    rf"(?P<prefix>[\"']?Authorization[\"']?\s*[:=]\s*(?P<quote>[\"']?)(?:Bearer|Basic)\s+)"
    rf"(?P<value>[{_TOKEN_CHARS}]{{8,}})(?P=quote)",
    re.IGNORECASE,
)
_COOKIE = re.compile(
    r"(?<![A-Za-z0-9_-])(?P<prefix>(?:Cookie|Set-Cookie)\s*:\s*)(?P<value>[^\r\n]+)",
    re.IGNORECASE,
)
_BARE_BEARER = re.compile(
    rf"(?<![A-Za-z0-9_-])(?P<prefix>Bearer\s+)"
    rf"(?P<value>(?=[{_TOKEN_CHARS}]*[0-9])(?=[{_TOKEN_CHARS}]*[._+/=])[{_TOKEN_CHARS}]{{12,}})"
    rf"(?![{_TOKEN_CHARS}])",
    re.IGNORECASE,
)
_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9_-])"
    r"(?P<prefix>(?:(?:export)\s+|\$env:\s*)?"
    r"(?P<field_quote>[\"']?)(?P<label>(?:(?:[A-Za-z0-9]+[_-])*(?:api[_-]?key|apikey|token|password|secret)|authorization|cookie|set-cookie))"
    r"(?P=field_quote)\s*[:=]\s*)"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\r\n,;}]+)",
    re.IGNORECASE,
)

# Compatibility export for owners that inventory the canonical detector shapes.
FORBIDDEN_TEXT_PATTERNS = (_SK_KEY, _AUTHORIZATION, _COOKIE, _BARE_BEARER, _ASSIGNMENT)


def _prefixed_marker(match: Match[str]) -> str:
    quote = match.groupdict().get("quote") or ""
    return f"{match.group('prefix')}{REDACTION_MARKER}{quote}"


def _assignment_marker(match: Match[str]) -> str:
    label = match.group("label")
    if not is_sensitive_label(label):
        return match.group(0)
    value = match.group("value")
    stripped = value.strip()
    quote = stripped[0] if len(stripped) >= 2 and stripped[0] in "\"'" and stripped[-1] == stripped[0] else ""
    logical_value = stripped[1:-1] if quote else stripped
    if REDACTION_MARKER in logical_value:
        return match.group(0)
    trailing = value[len(value.rstrip()):]
    replacement = f"{quote}{REDACTION_MARKER}{quote}" if quote else REDACTION_MARKER
    return f"{match.group('prefix')}{replacement}{trailing}"


def sanitize_provider_visible_text(value: Any) -> str:
    """Remove NULs and redact complete credential values without clipping."""
    text = str(value or "").replace("\x00", "")
    text = _SK_KEY.sub(REDACTION_MARKER, text)
    text = _AUTHORIZATION.sub(_prefixed_marker, text)
    text = _COOKIE.sub(_prefixed_marker, text)
    text = _BARE_BEARER.sub(_prefixed_marker, text)
    text = _ASSIGNMENT.sub(_assignment_marker, text)
    return text


def contains_forbidden_text(value: Any) -> bool:
    text = str(value or "").replace("\x00", "")
    return sanitize_provider_visible_text(text) != text
