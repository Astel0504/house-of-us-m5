from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Mapping, Sequence


EVENT_SCHEMA_VERSION = "house_memory_durable_event_v0"
PROJECTION_SCHEMA_VERSION = "house_memory_durable_projection_v0"
EVENT_ID_PREFIX = "house_mem_evt_"
CURSOR_PREFIX = "house_mem_cursor_"

ALLOWED_ACTION_CODES = frozenset({"record_observed", "record_version_observed"})
ALLOWED_SCOPE_CODES = frozenset({"synthetic_test"})
ALLOWED_STATUS_CODES = frozenset({"approved"})
ALLOWED_REVIEW_STATE_CODES = frozenset({"reviewed"})
ALLOWED_ACTOR_TYPES = frozenset({"synthetic_test"})
ALLOWED_CAPABILITY_FLAGS = frozenset(
    {
        "standing_footing_eligible",
        "default_surfacing_eligible",
        "explicit_search_eligible",
        "manual_lookup_eligible",
        "exact_recall_eligible",
    }
)
ALLOWED_BLOCKER_FLAGS = frozenset(
    {
        "security_sensitive",
        "forbidden_or_secret_shaped_text",
        "missing_runtime_safe_summary",
        "missing_source_or_provenance_pointer",
        "missing_safe_for_context_packet",
        "missing_use_scope",
        "missing_injection_scope",
        "unclear_audience",
        "sensitive_without_audience_scope",
        "stale_or_superseded",
        "unresolved_contradiction",
        "raw_body_required",
        "overlong",
        "duplicate_cluster_unresolved",
        "authority_unclear",
    }
)

EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "event_sequence",
        "previous_event_id",
        "occurred_at",
        "action_code",
        "memory_ref_hash",
        "canonical_record_version_hash",
        "actor_type",
        "actor_ref_hash",
        "action_ref_hash",
        "participant_scope_code",
        "authority_scope_code",
        "audience_scope_code",
        "status_code",
        "review_state_code",
        "reason_code",
        "provenance_present",
        "blocker_flags",
        "safe_capability_flags",
    }
)

_HASH_RE = re.compile(r"[0-9a-f]{64}")
_EVENT_ID_RE = re.compile(r"house_mem_evt_[0-9a-f]{32}")
_UTC_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,79}")
_FORBIDDEN_CODE_MARKERS = (
    "api_key",
    "credential",
    "embedding",
    "env_value",
    "private_path",
    "prompt",
    "provider_body",
    "raw_chat",
    "raw_memory",
    "secret_key",
    "token_value",
    "vector",
)


class HouseMemoryDurableEventError(ValueError):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.message = message


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HouseMemoryDurableEventError(
            "noncanonical_event_value",
            "Durable memory data must contain only canonical JSON values.",
        ) from exc


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def synthetic_hash(label: str) -> str:
    """Build an opaque fixture hash without accepting the label into an event."""
    if not isinstance(label, str) or not label:
        raise HouseMemoryDurableEventError(
            "invalid_synthetic_label", "Synthetic fixture labels must be non-empty strings."
        )
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _require_hash(name: str, value: Any) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise HouseMemoryDurableEventError(
            f"invalid_{name}", f"{name} must be a lowercase SHA-256 hex value."
        )
    return value


def _require_code(name: str, value: Any, allowed: frozenset[str] | None = None) -> str:
    if not isinstance(value, str) or _CODE_RE.fullmatch(value) is None:
        raise HouseMemoryDurableEventError(
            f"invalid_{name}", f"{name} must be a bounded lowercase ASCII code."
        )
    if allowed is not None and value not in allowed:
        raise HouseMemoryDurableEventError(f"unsupported_{name}", f"{name} is not allowed in Gate 1.")
    if value not in ALLOWED_BLOCKER_FLAGS and any(marker in value for marker in _FORBIDDEN_CODE_MARKERS):
        raise HouseMemoryDurableEventError(
            "forbidden_raw_text_marker", "Durable memory codes cannot carry raw or secret-shaped text."
        )
    return value


def _require_flag_list(name: str, value: Any, allowed: frozenset[str]) -> list[str]:
    if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes)):
        raise HouseMemoryDurableEventError(f"invalid_{name}", f"{name} must be a list of codes.")
    normalized = [_require_code(name, item, allowed) for item in value]
    if len(normalized) > len(allowed) or len(normalized) != len(set(normalized)):
        raise HouseMemoryDurableEventError(f"invalid_{name}", f"{name} must be unique and bounded.")
    return sorted(normalized)


def _identity_basis(event: Mapping[str, Any]) -> dict[str, Any]:
    return {key: event[key] for key in sorted(EVENT_FIELDS - {"event_id"})}


def compute_event_id(event: Mapping[str, Any]) -> str:
    return EVENT_ID_PREFIX + canonical_sha256(_identity_basis(event))[:32]


def normalize_event(value: Any, *, verify_identity: bool = True) -> dict[str, Any]:
    if isinstance(value, Mapping) and value.get("schema_version") != EVENT_SCHEMA_VERSION:
        from house_memory_curated_event_contract_v0 import (
            EVENT_SCHEMA_VERSION as CURATED_EVENT_SCHEMA_VERSION,
            normalize_event as normalize_curated_event,
        )

        if value.get("schema_version") == CURATED_EVENT_SCHEMA_VERSION:
            return normalize_curated_event(value, verify_identity=verify_identity)
    if not isinstance(value, Mapping):
        raise HouseMemoryDurableEventError("invalid_event", "Durable memory event must be an object.")
    extra = sorted(set(value) - EVENT_FIELDS)
    missing = sorted(EVENT_FIELDS - set(value))
    if extra or missing:
        raise HouseMemoryDurableEventError(
            "invalid_event_fields", "Durable memory event fields must exactly match the Gate 1 allowlist."
        )
    if value["schema_version"] != EVENT_SCHEMA_VERSION:
        raise HouseMemoryDurableEventError("invalid_schema_version", "Event schema version is unsupported.")
    sequence = value["event_sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise HouseMemoryDurableEventError("invalid_event_sequence", "Event sequence must be positive.")
    previous = value["previous_event_id"]
    if not isinstance(previous, str) or (previous and _EVENT_ID_RE.fullmatch(previous) is None):
        raise HouseMemoryDurableEventError("invalid_previous_event_id", "Previous event id is invalid.")
    if (sequence == 1) != (previous == ""):
        raise HouseMemoryDurableEventError(
            "invalid_previous_event_id", "Only the first event may have an empty previous event id."
        )
    occurred_at = value["occurred_at"]
    if not isinstance(occurred_at, str) or _UTC_RE.fullmatch(occurred_at) is None:
        raise HouseMemoryDurableEventError(
            "invalid_occurred_at", "occurred_at must be canonical microsecond UTC."
        )
    try:
        parsed_occurred_at = datetime.strptime(occurred_at, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise HouseMemoryDurableEventError(
            "invalid_occurred_at", "occurred_at must contain a real canonical UTC date and time."
        ) from exc
    if parsed_occurred_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ") != occurred_at:
        raise HouseMemoryDurableEventError(
            "invalid_occurred_at", "occurred_at must be canonical microsecond UTC."
        )
    if not isinstance(value["provenance_present"], bool):
        raise HouseMemoryDurableEventError(
            "invalid_provenance_present", "provenance_present must be a boolean."
        )

    event = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": str(value["event_id"]),
        "event_sequence": sequence,
        "previous_event_id": previous,
        "occurred_at": occurred_at,
        "action_code": _require_code("action_code", value["action_code"], ALLOWED_ACTION_CODES),
        "memory_ref_hash": _require_hash("memory_ref_hash", value["memory_ref_hash"]),
        "canonical_record_version_hash": _require_hash(
            "canonical_record_version_hash", value["canonical_record_version_hash"]
        ),
        "actor_type": _require_code("actor_type", value["actor_type"], ALLOWED_ACTOR_TYPES),
        "actor_ref_hash": _require_hash("actor_ref_hash", value["actor_ref_hash"]),
        "action_ref_hash": _require_hash("action_ref_hash", value["action_ref_hash"]),
        "participant_scope_code": _require_code(
            "participant_scope_code", value["participant_scope_code"], ALLOWED_SCOPE_CODES
        ),
        "authority_scope_code": _require_code(
            "authority_scope_code", value["authority_scope_code"], ALLOWED_SCOPE_CODES
        ),
        "audience_scope_code": _require_code(
            "audience_scope_code", value["audience_scope_code"], ALLOWED_SCOPE_CODES
        ),
        "status_code": _require_code("status_code", value["status_code"], ALLOWED_STATUS_CODES),
        "review_state_code": _require_code(
            "review_state_code", value["review_state_code"], ALLOWED_REVIEW_STATE_CODES
        ),
        "reason_code": _require_code("reason_code", value["reason_code"]),
        "provenance_present": value["provenance_present"],
        "blocker_flags": _require_flag_list("blocker_flags", value["blocker_flags"], ALLOWED_BLOCKER_FLAGS),
        "safe_capability_flags": _require_flag_list(
            "safe_capability_flags", value["safe_capability_flags"], ALLOWED_CAPABILITY_FLAGS
        ),
    }
    expected_id = compute_event_id(event)
    if verify_identity and event["event_id"] != expected_id:
        raise HouseMemoryDurableEventError("event_identity_mismatch", "Event identity does not match its fields.")
    if _EVENT_ID_RE.fullmatch(event["event_id"]) is None:
        raise HouseMemoryDurableEventError("invalid_event_id", "Event id is invalid.")
    return event


def build_event(
    *,
    event_sequence: int,
    previous_event_id: str,
    occurred_at: str,
    action_code: str,
    memory_ref_hash: str,
    canonical_record_version_hash: str,
    actor_type: str,
    actor_ref_hash: str,
    action_ref_hash: str,
    participant_scope_code: str = "synthetic_test",
    authority_scope_code: str = "synthetic_test",
    audience_scope_code: str = "synthetic_test",
    status_code: str = "approved",
    review_state_code: str = "reviewed",
    reason_code: str = "synthetic_observation",
    provenance_present: bool = True,
    blocker_flags: Sequence[str] = (),
    safe_capability_flags: Sequence[str] = (),
) -> dict[str, Any]:
    candidate = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": EVENT_ID_PREFIX + ("0" * 32),
        "event_sequence": event_sequence,
        "previous_event_id": previous_event_id,
        "occurred_at": occurred_at,
        "action_code": action_code,
        "memory_ref_hash": memory_ref_hash,
        "canonical_record_version_hash": canonical_record_version_hash,
        "actor_type": actor_type,
        "actor_ref_hash": actor_ref_hash,
        "action_ref_hash": action_ref_hash,
        "participant_scope_code": participant_scope_code,
        "authority_scope_code": authority_scope_code,
        "audience_scope_code": audience_scope_code,
        "status_code": status_code,
        "review_state_code": review_state_code,
        "reason_code": reason_code,
        "provenance_present": provenance_present,
        "blocker_flags": list(blocker_flags),
        "safe_capability_flags": list(safe_capability_flags),
    }
    normalized = normalize_event(candidate, verify_identity=False)
    normalized["event_id"] = compute_event_id(normalized)
    return normalize_event(normalized)


def replay_cursor(event_count: int, last_event_id: str) -> str:
    return CURSOR_PREFIX + canonical_sha256(
        {"event_count": event_count, "last_event_id": last_event_id}
    )[:32]


def replay_events(
    events: Sequence[Mapping[str, Any]], *, expected_cursor: str | None = None
) -> dict[str, Any]:
    if any(
        isinstance(event, Mapping) and event.get("schema_version") != EVENT_SCHEMA_VERSION
        for event in events
    ):
        from house_memory_curated_projection_v0 import replay_mixed_events

        return replay_mixed_events(events, expected_cursor=expected_cursor)
    records: dict[str, dict[str, Any]] = {}
    previous_id = ""
    chain_hashes: list[str] = []
    for expected_sequence, raw_event in enumerate(events, start=1):
        event = normalize_event(raw_event)
        if event["event_sequence"] != expected_sequence or event["previous_event_id"] != previous_id:
            raise HouseMemoryDurableEventError(
                "invalid_replay_order", "Replay events must form one contiguous canonical chain."
            )
        previous_id = event["event_id"]
        chain_hashes.append(event["event_id"])
        memory_ref_hash = event["memory_ref_hash"]
        prior_count = int(records.get(memory_ref_hash, {}).get("event_count", 0))
        capabilities = set(event["safe_capability_flags"])
        projected_blockers = set(event["blocker_flags"])
        if not event["provenance_present"]:
            projected_blockers.add("missing_source_or_provenance_pointer")
        blocked = bool(projected_blockers)
        records[memory_ref_hash] = {
            "memory_ref_hash": memory_ref_hash,
            "canonical_record_version_hash": event["canonical_record_version_hash"],
            "participant_scope_code": event["participant_scope_code"],
            "authority_scope_code": event["authority_scope_code"],
            "audience_scope_code": event["audience_scope_code"],
            "status_code": event["status_code"],
            "review_state_code": event["review_state_code"],
            "provenance_present": event["provenance_present"],
            "blocker_flags": sorted(projected_blockers),
            "safe_capability_flags": list(event["safe_capability_flags"]),
            "core_status": "normal_reviewed",
            "standing_footing_eligible": not blocked and "standing_footing_eligible" in capabilities,
            "default_surfacing_eligible": not blocked and "default_surfacing_eligible" in capabilities,
            "explicit_search_eligible": not blocked and "explicit_search_eligible" in capabilities,
            "manual_lookup_eligible": not blocked and "manual_lookup_eligible" in capabilities,
            "exact_recall_eligible": not blocked and "exact_recall_eligible" in capabilities,
            "last_event_id": event["event_id"],
            "last_reason_code": event["reason_code"],
            "event_count": prior_count + 1,
        }
    cursor = replay_cursor(len(events), previous_id)
    if expected_cursor is not None and expected_cursor != cursor:
        raise HouseMemoryDurableEventError("replay_cursor_mismatch", "Replay cursor does not match state.")
    return {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "replay_cursor": cursor,
        "event_count": len(events),
        "record_count": len(records),
        "last_event_id": previous_id,
        "event_chain_checksum": canonical_sha256(chain_hashes),
        "record_refs": sorted(records),
        "records": {key: records[key] for key in sorted(records)},
    }
