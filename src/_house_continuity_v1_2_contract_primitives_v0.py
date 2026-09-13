"""Shared canonicalization and validation primitives for Continuity V1.2 contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any
import unicodedata

MAX_COMPLETE_UNIT_IDS = 4

MAX_RECEIPT_IDS = 8

AUTHORED_REASON_MAX_CHARS = 2048

SCOPE_KINDS = ("room", "project", "global")

_HASH_RE = re.compile(r"[0-9a-f]{64}")

_OPAQUE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,179}")

_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,79}")

_CAPABILITY_RE = re.compile(r"cwc_[A-Za-z0-9_-]{43}")

_PRIVATE_CAPABILITY_SEARCH_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:cwc|cac)_[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])"
)

_PRIVATE_CARRIER_MARKERS = (
    "<house-continuity-intent>",
    "</house-continuity-intent>",
    "<house-memory-authorship-intent>",
    "</house-memory-authorship-intent>",
)

_ASTEL_CONFIRMATION_RE = re.compile(r"cac_[A-Za-z0-9_-]{43}")

_ID_PATTERNS = {
    "room_id": re.compile(r"cws_room_[0-9a-f]{32}"),
    "project_id": re.compile(r"cws_prj_[0-9a-f]{32}"),
    "thread_id": re.compile(r"cws_thr_[0-9a-f]{32}"),
    "item_id": re.compile(r"cws_item_[0-9a-f]{32}"),
    "event_id": re.compile(r"cws_evt_[0-9a-f]{32}"),
    "context_id": re.compile(r"cws_ctx_[0-9a-f]{32}"),
    "offer_id": re.compile(r"cws_offer_[0-9a-f]{32}"),
    "bundle_id": re.compile(r"cws_out_[0-9a-f]{32}"),
    "capability_id": re.compile(r"cwcap_[0-9a-f]{32}"),
    "fence_id": re.compile(r"cws_fence_[0-9a-f]{32}"),
    "seed_id": re.compile(r"cws_seed_[0-9a-f]{32}"),
    "binding_id": re.compile(r"cws_bind_[0-9a-f]{32}"),
    "anchor_id": re.compile(r"cws_anchor_[0-9a-f]{32}"),
    "unit_id": re.compile(r"ccu_[0-9a-f]{32}"),
    "confirmation_capability_id": re.compile(r"cwaconf_[0-9a-f]{32}"),
}

_FORBIDDEN_NAMES = frozenset(
    {
        "api_key",
        "authorization",
        "body",
        "credential",
        "exact_quote",
        "exact_text",
        "headers",
        "memory_body",
        "password",
        "prompt",
        "provider_body",
        "raw_body",
        "raw_history",
        "raw_text",
        "secret",
        "self_state_body",
        "token",
        "tool_body",
        "tool_permission",
        "transcript",
        "vault_body",
    }
)

_FORBIDDEN_FRAGMENTS = (
    "api_key",
    "auth_header",
    "exact_quote",
    "full_transcript",
    "memory_body",
    "private_path",
    "provider_body",
    "raw_chat",
    "raw_history",
    "secret_value",
    "self_state_body",
    "tool_permission",
    "transcript_dump",
)

class HouseContinuityV12ContractError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message

def _error(code: str, message: str) -> None:
    raise HouseContinuityV12ContractError(code, message)

def _normalize_unicode(value: Any, *, name: str) -> str:
    if not isinstance(value, str):
        _error(f"invalid_{name}", f"{name} must be a string.")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        _error("unpaired_surrogate", f"{name} contains a surrogate code point.")
    normalized = unicodedata.normalize("NFC", value)
    if value != normalized:
        _error(
            "noncanonical_unicode",
            f"{name} must already be Unicode NFC.",
        )
    return value

def canonical_json_bytes(value: Any) -> bytes:
    def normalize(node: Any, path: str) -> Any:
        if isinstance(node, str):
            return _normalize_unicode(node, name=path)
        if isinstance(node, Mapping):
            return {
                _normalize_unicode(key, name=f"{path}.key"): normalize(
                    nested, f"{path}.{key}"
                )
                for key, nested in node.items()
            }
        if isinstance(node, (list, tuple)):
            return [
                normalize(nested, f"{path}[{index}]")
                for index, nested in enumerate(node)
            ]
        return node

    try:
        return json.dumps(
            normalize(value, "value"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except HouseContinuityV12ContractError:
        raise
    except (TypeError, ValueError) as exc:
        raise HouseContinuityV12ContractError(
            "noncanonical_value", "Value is not canonical JSON."
        ) from exc

def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()

def _reject_private(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = _normalize_unicode(key, name=f"{path}.key").casefold()
            if key_text in {
                "memory_vault_truth",
                "exact_evidence",
                "self_state",
                "action_permission",
                "capability_authority",
                "raw_history_included",
                "raw_body_included",
                "exact_body_included",
                "raw_bytes_migrated",
            }:
                if nested is not False:
                    _error(
                        "forbidden_authority_true",
                        f"{path}.{key} must be exactly false.",
                    )
                continue
            if key_text in _FORBIDDEN_NAMES or any(
                marker in key_text for marker in _FORBIDDEN_FRAGMENTS
            ):
                _error("forbidden_field", f"Forbidden field at {path}.{key}.")
            _reject_private(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_private(nested, path=f"{path}[{index}]")
    elif isinstance(value, str):
        _normalize_unicode(value, name=path)

def _exact(value: Any, fields: Sequence[str], *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _error(f"invalid_{path}_type", f"{path} must be an object.")
    _reject_private(value, path=path)
    expected = set(fields)
    if set(value) != expected:
        _error(
            f"invalid_{path}_fields",
            f"{path} fields must exactly match the allowlist.",
        )
    return value

def _string(
    value: Any,
    *,
    name: str,
    maximum: int,
    empty: bool = False,
) -> str:
    text = _normalize_unicode(value, name=name)
    if text != text.strip() or any(ord(char) < 32 for char in text):
        _error(f"invalid_{name}", f"{name} must be canonical single-line text.")
    if (not text and not empty) or len(text) > maximum:
        _error(f"invalid_{name}", f"{name} violates its size contract.")
    return text

def validate_authored_reason(
    value: Any,
    *,
    name: str = "reason_code",
) -> str | None:
    """Preserve participant-authored meaning without treating it as a code.

    This validator enforces only representation integrity and a generous
    storage bound. It deliberately does not trim, normalize, classify, or
    whitelist the participant's wording.
    """

    if value is None:
        return None
    text = _normalize_unicode(value, name=name)
    if len(text) > AUTHORED_REASON_MAX_CHARS:
        _error(f"invalid_{name}", f"{name} exceeds its storage cap.")
    if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
        _error(f"invalid_{name}", f"{name} contains an invalid control character.")
    if (
        _PRIVATE_CAPABILITY_SEARCH_RE.search(text) is not None
        or any(marker in text for marker in _PRIVATE_CARRIER_MARKERS)
    ):
        _error(
            f"{name}_private_material_rejected",
            f"{name} cannot contain a private capability or carrier.",
        )
    return text

def _code(value: Any, *, name: str, allowed: Sequence[str]) -> str:
    if (
        not isinstance(value, str)
        or _CODE_RE.fullmatch(value) is None
        or value not in allowed
    ):
        _error(f"invalid_{name}", f"{name} is not an allowed code.")
    return value

def _integer(
    value: Any,
    *,
    name: str,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _error(f"invalid_{name}", f"{name} must be a bounded integer.")
    if maximum is not None and value > maximum:
        _error(f"invalid_{name}", f"{name} exceeds its cap.")
    return value

def _hash(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        _error(f"invalid_{name}", f"{name} must be lowercase SHA-256.")
    return value

def _id(value: Any, *, name: str, kind: str | None = None) -> str:
    pattern = _ID_PATTERNS.get(kind or name, _OPAQUE_ID_RE)
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _error(f"invalid_{name}", f"{name} is not a valid identifier.")
    return value

def _nullable_id(value: Any, *, name: str, kind: str | None = None) -> str | None:
    return None if value is None else _id(value, name=name, kind=kind)

def _id_list(
    value: Any,
    *,
    name: str,
    maximum: int,
    kind: str | None = None,
) -> list[str]:
    if not isinstance(value, list):
        _error(f"invalid_{name}", f"{name} must be a list.")
    result = [_id(item, name=name, kind=kind) for item in value]
    if len(result) > maximum or len(result) != len(set(result)):
        _error(f"invalid_{name}", f"{name} must be unique and bounded.")
    return result

def _timestamp(value: Any, *, name: str) -> str:
    text = _string(value, name=name, maximum=24)
    if not text.endswith("Z") or len(text) != 24 or text[19] != ".":
        _error(f"invalid_{name}", f"{name} must be millisecond UTC.")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise HouseContinuityV12ContractError(
            f"invalid_{name}", f"{name} is not a real UTC datetime."
        ) from exc
    if parsed.tzinfo != timezone.utc or parsed.microsecond % 1000:
        _error(f"invalid_{name}", f"{name} must be millisecond UTC.")
    return text

def _timestamp_value(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")

def normalize_scope(value: Any, *, path: str = "scope") -> dict[str, Any]:
    raw = _exact(
        value,
        ("scope_kind", "room_id", "project_id", "thread_id"),
        path=path,
    )
    kind = _code(raw["scope_kind"], name="scope_kind", allowed=SCOPE_KINDS)
    room = _nullable_id(raw["room_id"], name="room_id", kind="room_id")
    project = _nullable_id(
        raw["project_id"], name="project_id", kind="project_id"
    )
    thread = _nullable_id(
        raw["thread_id"], name="thread_id", kind="thread_id"
    )
    if thread is not None and project is None:
        _error("invalid_scope", "Thread scope requires a project.")
    if kind == "room" and room is None:
        _error("invalid_scope", "Room scope requires room_id.")
    if kind == "project" and (room is not None or project is None):
        _error("invalid_scope", "Project scope requires project/thread IDs.")
    if kind == "global" and any(item is not None for item in (room, project, thread)):
        _error("invalid_scope", "Global scope contains no IDs.")
    return {
        "scope_kind": kind,
        "room_id": room,
        "project_id": project,
        "thread_id": thread,
    }

def _opaque_list(
    value: Any,
    *,
    name: str,
    maximum: int,
    kind: str | None = None,
) -> list[str]:
    return _id_list(value, name=name, maximum=maximum, kind=kind)

__all__ = [
    "Any",
    "Mapping",
    "Sequence",
    "datetime",
    "timezone",
    "hashlib",
    "json",
    "re",
    "unicodedata",
    "MAX_COMPLETE_UNIT_IDS",
    "MAX_RECEIPT_IDS",
    "SCOPE_KINDS",
    "_HASH_RE",
    "_OPAQUE_ID_RE",
    "_CODE_RE",
    "_CAPABILITY_RE",
    "_ASTEL_CONFIRMATION_RE",
    "_ID_PATTERNS",
    "_FORBIDDEN_NAMES",
    "_FORBIDDEN_FRAGMENTS",
    "HouseContinuityV12ContractError",
    "_error",
    "_normalize_unicode",
    "canonical_json_bytes",
    "canonical_sha256",
    "_reject_private",
    "_exact",
    "_string",
    "_code",
    "_integer",
    "_hash",
    "_id",
    "_nullable_id",
    "_id_list",
    "_timestamp",
    "_timestamp_value",
    "normalize_scope",
    "_opaque_list",
]
