"""Local/default-off Milestone-3 hot, warm, and cold context authority.

This owner stores immutable canonical source units separately from mutable zone
membership.  Warm and cold episode records are derived context evidence only;
they never write to, replace, or override the Milestone-2 Working Set or any
Memory/Vault/self-state authority.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

import provider_visible_text_safety_v0 as provider_text_safety


SCHEMA_VERSION = "house_continuity_milestone3_context_local_v1"
STORE_SCHEMA_VERSION = "house_continuity_milestone3_context_store_v1"
SOURCE_UNIT_SCHEMA_VERSION = "house_continuity_milestone3_source_unit_v1"
EPISODE_SCHEMA_VERSION = "house_continuity_milestone3_episode_v1"
ZONE_PROJECTION_SCHEMA_VERSION = "house_continuity_milestone3_zone_projection_v1"
TRANSITION_RECEIPT_SCHEMA_VERSION = "house_continuity_milestone3_transition_receipt_v1"
SELECTION_RECEIPT_SCHEMA_VERSION = "house_continuity_milestone3_selection_receipt_v1"
COLD_RECEIPT_SCHEMA_VERSION = "house_continuity_milestone3_cold_selection_receipt_v1"
EQUALITY_RECEIPT_SCHEMA_VERSION = "house_evidence_domain_comparison_receipt_v1"

CANONICAL_JSON_VERSION = "sorted_json_utf8_v1"
SOURCE_TEXT_DOMAIN = "canonical_source_message_utf8_v1"
SOURCE_UNIT_DOMAIN = "m3_canonical_source_unit_sorted_json_utf8_v1"
EPISODE_DOMAIN = "m3_canonical_episode_sorted_json_utf8_v1"
ZONE_PROJECTION_DOMAIN = "m3_zone_projection_sorted_json_utf8_v1"
PROVIDER_MESSAGE_TEXT_DOMAIN = "m3_provider_visible_message_text_utf8_v1"
PROVIDER_SECTION_DOMAIN = "m3_provider_visible_section_utf8_v1"
DYNAMIC_LIST_DOMAIN = "generation2_dynamic_context_list_sorted_json_utf8_v1"
UNICODE_QUERY_DOMAIN = "m3_unicode_query_nfkc_casefold_utf8_v1"
UNICODE_NORMALIZATION_VERSION = "unicode_nfkc_casefold_v1"
UNICODE_TOKENIZER_VERSION = "house_m3_unicode_cjk_word_tokenizer_v1"
UNICODE_INDEX_DOMAIN = "m3_unicode_episode_index_sorted_json_utf8_v1"

SWITCH_ENV = "HOUSE_CONTINUITY_M3_CONTEXT_MODE"
SELECTOR_ENV = "HOUSE_CONTINUITY_M3_CONTEXT_SELECTOR"
BUDGET_ENV = "HOUSE_CONTINUITY_M3_DYNAMIC_BUDGET_CHARS"
ROOT_ENV = "HOUSE_CONTINUITY_V1_2_MILESTONE2_ROOT"
OFF = "off"
COPY_REHEARSAL = "copy_rehearsal"
ON = "on"
DEFAULT_DYNAMIC_BUDGET_CHARS = 12_000
MAX_DYNAMIC_BUDGET_CHARS = 64_000

STRUCTURED_FIELDS = (
    "open_loops",
    "decisions",
    "emotional_relational_threads",
    "task_phase",
    "intended_next_action",
    "temporary_facts",
    "solen_intentions",
)
AVAILABILITY = {"known", "unknown", "unavailable"}
EXACTNESS = {"exact", "derived", "unavailable"}
AUTHORSHIP = {"astel", "solen", "joint", "house_derived", "source_unknown"}
SCOPE_KINDS = {"global", "project", "room"}
ZONE_KINDS = {"hot", "warm", "cold"}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,180}$")
_LATIN_WORD_RE = re.compile(r"[A-Za-z0-9_]{2,80}")
_PRIVATE_CAPABILITY_RE = re.compile(r"\bcwc_[A-Za-z0-9_-]{40,60}\b")
_PRIVATE_CAPABILITY_ID_RE = re.compile(r"\bcwcap_[0-9a-f]{32}\b")
_PROTECTED_RAW_ROOT_RE = re.compile(
    r"(?:[A-Za-z]:\\Users\\[^\\\s]+\\\.codex\\|/root/body_prototype_staging/)"
)


def provider_boundary_denial_reason(value: str) -> str | None:
    if not isinstance(value, str):
        _fail("m3_provider_boundary_text_invalid")
    lowered = value.casefold()
    if provider_text_safety.contains_forbidden_text(value):
        return "credential_or_header_shaped_material"
    if _PRIVATE_CAPABILITY_RE.search(value) or _PRIVATE_CAPABILITY_ID_RE.search(value):
        return "capability_shaped_material"
    if "<house-continuity" in lowered or "<house-memory-intent" in lowered:
        return "private_terminal_carrier_material"
    if _PROTECTED_RAW_ROOT_RE.search(value):
        return "protected_raw_root_material"
    if (
        '"choices"' in value
        and '"usage"' in value
        and ('"tool_calls"' in value or '"finish_reason"' in value)
    ):
        return "provider_response_shaped_material"
    return None


def _cjk_character(value: str) -> bool:
    code = ord(value)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x3040 <= code <= 0x309F
        or 0x30A0 <= code <= 0x30FF
        or 0x31F0 <= code <= 0x31FF
    )


def unicode_search_tokens(value: str) -> tuple[str, ...]:
    """Return deterministic Latin/number words plus CJK characters and bigrams."""
    if not isinstance(value, str):
        _fail("m3_unicode_text_invalid")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens = set(_LATIN_WORD_RE.findall(normalized))
    run: list[str] = []

    def flush() -> None:
        if not run:
            return
        tokens.update(run)
        tokens.update("".join(run[index : index + 2]) for index in range(len(run) - 1))
        run.clear()

    for character in normalized:
        if _cjk_character(character):
            run.append(character)
        else:
            flush()
    flush()
    return tuple(sorted(tokens))


def _normalize_scope(value: Any, *, room_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "scope_kind", "room_id", "project_id"
    }:
        _fail("m3_scope_invalid")
    kind = value["scope_kind"]
    project_id = value["project_id"]
    if value["room_id"] != room_id or kind not in SCOPE_KINDS:
        _fail("m3_scope_invalid")
    if kind == "project":
        if not isinstance(project_id, str) or not project_id.startswith("cws_prj_"):
            _fail("m3_scope_invalid")
    elif project_id is not None:
        _fail("m3_scope_invalid")
    return {
        "scope_kind": kind,
        "room_id": room_id,
        "project_id": project_id,
    }


class Milestone3ContextError(ValueError):
    pass


def _fail(code: str) -> None:
    raise Milestone3ContextError(code)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _identifier(value: Any, *, prefix: str | None = None) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        _fail("m3_identifier_invalid")
    if prefix is not None and not value.startswith(prefix):
        _fail("m3_identifier_invalid")
    return value


def _strict_int(value: Any, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail("m3_integer_invalid")
    return value


def evidence_equality_receipt(
    *,
    left_bytes: bytes,
    left_domain: str,
    left_canonicalization_version: str,
    right_bytes: bytes,
    right_domain: str,
    right_canonicalization_version: str,
) -> dict[str, Any]:
    """Compare only like representations; mismatches are not booleans."""
    comparable = (
        left_domain == right_domain
        and left_canonicalization_version == right_canonicalization_version
    )
    body = {
        "schema_version": EQUALITY_RECEIPT_SCHEMA_VERSION,
        "left_domain": left_domain,
        "left_canonicalization_version": left_canonicalization_version,
        "left_sha256": _bytes_sha256(left_bytes),
        "right_domain": right_domain,
        "right_canonicalization_version": right_canonicalization_version,
        "right_sha256": _bytes_sha256(right_bytes),
        "comparison_state": "comparable" if comparable else "domain_mismatch",
        "equal": left_bytes == right_bytes if comparable else None,
        "canonical_conversion": None,
        "raw_material_present": False,
    }
    return {**body, "receipt_sha256": canonical_sha256(body)}


def provider_visible_conversion_receipt(source_text: str) -> dict[str, Any]:
    """Name and replay-test the source-to-provider canonical conversion."""
    source_bytes = source_text.encode("utf-8")
    denial_reason = provider_boundary_denial_reason(source_text)
    provider_text = (
        "[Exact source material unavailable for provider-visible use.]"
        if denial_reason is not None
        else provider_text_safety.sanitize_provider_visible_text(source_text)
    )
    provider_bytes = provider_text.encode("utf-8")
    replay_bytes = provider_text_safety.sanitize_provider_visible_text(source_text).encode("utf-8")
    replay_comparison = evidence_equality_receipt(
        left_bytes=provider_bytes,
        left_domain=PROVIDER_MESSAGE_TEXT_DOMAIN,
        left_canonicalization_version="utf8_no_normalization_v1",
        right_bytes=replay_bytes,
        right_domain=PROVIDER_MESSAGE_TEXT_DOMAIN,
        right_canonicalization_version="utf8_no_normalization_v1",
    )
    body = {
        "schema_version": EQUALITY_RECEIPT_SCHEMA_VERSION,
        "conversion_name": "provider_visible_text_safety_v0",
        "conversion_version": "provider_visible_text_safety_v0",
        "source_domain": SOURCE_TEXT_DOMAIN,
        "source_canonicalization_version": "utf8_no_normalization_v1",
        "source_sha256": _bytes_sha256(source_bytes),
        "output_domain": PROVIDER_MESSAGE_TEXT_DOMAIN,
        "output_canonicalization_version": "utf8_no_normalization_v1",
        "output_sha256": _bytes_sha256(provider_bytes),
        "conversion_state": (
            "denied_unavailable"
            if denial_reason is not None
            else "identity_byte_preserving"
            if source_bytes == provider_bytes
            else "derived_sanitized"
        ),
        "denial_reason": denial_reason,
        "cross_domain_equal": None,
        "replay_output_comparison": replay_comparison,
        "raw_material_present": False,
    }
    return {
        "provider_text": provider_text,
        "receipt": {**body, "receipt_sha256": canonical_sha256(body)},
    }


def _normalize_message(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("m3_source_message_invalid")
    expected = {
        "message_id", "side", "text", "complete", "segment_index",
        "segment_count", "parent_turn_id", "created_at_epoch_millis",
    }
    if set(value) != expected:
        _fail("m3_source_message_invalid")
    message_id = _identifier(value["message_id"], prefix="m3_msg_")
    side = value["side"]
    text = value["text"]
    if side not in {"astel", "solen"} or not isinstance(text, str) or not text:
        _fail("m3_source_message_invalid")
    if type(value["complete"]) is not bool:
        _fail("m3_source_message_invalid")
    segment_index = _strict_int(value["segment_index"])
    segment_count = _strict_int(value["segment_count"], minimum=1)
    if segment_index >= segment_count:
        _fail("m3_source_message_invalid")
    parent_turn_id = _identifier(value["parent_turn_id"], prefix="m3_turn_")
    return {
        "message_id": message_id,
        "side": side,
        "text": text,
        "complete": value["complete"],
        "segment_index": segment_index,
        "segment_count": segment_count,
        "parent_turn_id": parent_turn_id,
        "created_at_epoch_millis": _strict_int(value["created_at_epoch_millis"]),
    }


def normalize_source_unit(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("m3_source_unit_invalid")
    expected = {
        "schema_version", "unit_id", "room_id", "sequence", "messages",
        "source_ids", "source_start_id", "source_end_id", "authorship",
        "provenance", "scope",
    }
    if set(value) != expected or value.get("schema_version") != SOURCE_UNIT_SCHEMA_VERSION:
        _fail("m3_source_unit_invalid")
    unit_id = _identifier(value["unit_id"], prefix="m3_unit_")
    room_id = _identifier(value["room_id"], prefix="cws_room_")
    messages_value = value["messages"]
    if not isinstance(messages_value, list) or not messages_value:
        _fail("m3_source_unit_invalid")
    messages = [_normalize_message(item) for item in messages_value]
    message_ids = [item["message_id"] for item in messages]
    if len(message_ids) != len(set(message_ids)) or not all(item["complete"] for item in messages):
        _fail("m3_source_unit_incomplete")
    if [item["created_at_epoch_millis"] for item in messages] != sorted(
        item["created_at_epoch_millis"] for item in messages
    ):
        _fail("m3_source_unit_order_invalid")
    for parent in {item["parent_turn_id"] for item in messages if item["side"] == "solen"}:
        segments = [item for item in messages if item["side"] == "solen" and item["parent_turn_id"] == parent]
        if any(item["segment_count"] > 1 for item in segments):
            count = segments[0]["segment_count"]
            if (
                any(item["segment_count"] != count for item in segments)
                or [item["segment_index"] for item in segments] != list(range(count))
            ):
                _fail("m3_source_unit_split_incomplete")
    source_ids = value["source_ids"]
    if not isinstance(source_ids, list) or source_ids != message_ids:
        _fail("m3_source_unit_source_mapping_invalid")
    if value["source_start_id"] != source_ids[0] or value["source_end_id"] != source_ids[-1]:
        _fail("m3_source_unit_source_mapping_invalid")
    authorship = value["authorship"]
    if authorship not in AUTHORSHIP:
        _fail("m3_source_unit_authorship_invalid")
    provenance = value["provenance"]
    if not isinstance(provenance, Mapping) or set(provenance) != {"source_owner", "snapshot_id"}:
        _fail("m3_source_unit_provenance_invalid")
    if not all(isinstance(provenance[key], str) and provenance[key] for key in provenance):
        _fail("m3_source_unit_provenance_invalid")
    try:
        scope = _normalize_scope(value["scope"], room_id=room_id)
    except Milestone3ContextError as exc:
        raise Milestone3ContextError("m3_source_unit_scope_invalid") from exc
    normalized = {
        "schema_version": SOURCE_UNIT_SCHEMA_VERSION,
        "unit_id": unit_id,
        "room_id": room_id,
        "sequence": _strict_int(value["sequence"]),
        "messages": messages,
        "source_ids": list(source_ids),
        "source_start_id": source_ids[0],
        "source_end_id": source_ids[-1],
        "authorship": authorship,
        "provenance": dict(provenance),
        "scope": scope,
    }
    return normalized


def _normalize_structured_entry(value: Any, *, allowed_unit_ids: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("m3_structured_field_invalid")
    expected = {"availability", "value", "source_unit_ids", "authorship", "exactness", "uncertainty"}
    if set(value) != expected:
        _fail("m3_structured_field_invalid")
    availability = value["availability"]
    exactness = value["exactness"]
    authorship = value["authorship"]
    uncertainty = value["uncertainty"]
    source_unit_ids = value["source_unit_ids"]
    if (
        availability not in AVAILABILITY
        or exactness not in EXACTNESS
        or authorship not in AUTHORSHIP
        or not isinstance(uncertainty, str)
        or not isinstance(source_unit_ids, list)
        or len(source_unit_ids) != len(set(source_unit_ids))
        or not set(source_unit_ids).issubset(allowed_unit_ids)
    ):
        _fail("m3_structured_field_invalid")
    text = value["value"]
    if availability == "known":
        if not isinstance(text, str) or not text or not source_unit_ids or exactness == "unavailable":
            _fail("m3_structured_field_invalid")
    elif text is not None or exactness != "unavailable":
        _fail("m3_structured_field_invalid")
    return {
        "availability": availability,
        "value": text,
        "source_unit_ids": list(source_unit_ids),
        "authorship": authorship,
        "exactness": exactness,
        "uncertainty": uncertainty,
    }


def _message_lookup(units: Sequence[Mapping[str, Any]]) -> dict[str, tuple[str, str]]:
    return {
        message["message_id"]: (unit["unit_id"], message["text"])
        for unit in units
        for message in unit["messages"]
    }


def normalize_episode(value: Any, *, source_units: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("m3_episode_invalid")
    expected = {
        "schema_version", "episode_id", "room_id", "source_unit_ids",
        "source_start_id", "source_end_id", "authorship", "provenance",
        "scope", "uncertainty", "exactness", "derived_summary",
        "structured_fields", "exact_anchors", "m2_snapshot",
    }
    if set(value) != expected or value.get("schema_version") != EPISODE_SCHEMA_VERSION:
        _fail("m3_episode_invalid")
    unit_ids = [unit["unit_id"] for unit in source_units]
    if value["source_unit_ids"] != unit_ids or not unit_ids:
        _fail("m3_episode_source_range_invalid")
    source_ids = [source_id for unit in source_units for source_id in unit["source_ids"]]
    if value["source_start_id"] != source_ids[0] or value["source_end_id"] != source_ids[-1]:
        _fail("m3_episode_source_range_invalid")
    room_id = source_units[0]["room_id"]
    if value["room_id"] != room_id or any(unit["room_id"] != room_id for unit in source_units):
        _fail("m3_episode_cross_room")
    fields = value["structured_fields"]
    if not isinstance(fields, Mapping) or set(fields) != set(STRUCTURED_FIELDS):
        _fail("m3_structured_fields_incomplete")
    normalized_fields: dict[str, list[dict[str, Any]]] = {}
    for field in STRUCTURED_FIELDS:
        entries = fields[field]
        if not isinstance(entries, list) or not entries:
            _fail("m3_structured_fields_incomplete")
        normalized_fields[field] = [
            _normalize_structured_entry(item, allowed_unit_ids=set(unit_ids)) for item in entries
        ]
    message_lookup = _message_lookup(source_units)
    anchors = value["exact_anchors"]
    if not isinstance(anchors, list):
        _fail("m3_exact_anchor_invalid")
    normalized_anchors = []
    for anchor in anchors:
        expected_anchor = {
            "anchor_id", "source_unit_id", "source_message_id", "utf8_start",
            "utf8_end", "exact_quote", "source_representation_domain",
            "canonicalization_version", "source_message_utf8_sha256",
            "exact_quote_utf8_sha256",
        }
        if not isinstance(anchor, Mapping) or set(anchor) != expected_anchor:
            _fail("m3_exact_anchor_invalid")
        anchor_id = _identifier(anchor["anchor_id"], prefix="m3_anchor_")
        message_id = _identifier(anchor["source_message_id"], prefix="m3_msg_")
        source_unit_id = _identifier(anchor["source_unit_id"], prefix="m3_unit_")
        if message_id not in message_lookup or message_lookup[message_id][0] != source_unit_id:
            _fail("m3_exact_anchor_invalid")
        start = _strict_int(anchor["utf8_start"])
        end = _strict_int(anchor["utf8_end"])
        source_bytes = message_lookup[message_id][1].encode("utf-8")
        quote = anchor["exact_quote"]
        quote_bytes = quote.encode("utf-8") if isinstance(quote, str) else b""
        if (
            end <= start
            or end > len(source_bytes)
            or not isinstance(quote, str)
            or source_bytes[start:end] != quote_bytes
            or anchor["source_representation_domain"] != SOURCE_TEXT_DOMAIN
            or anchor["canonicalization_version"] != "utf8_no_normalization_v1"
            or anchor["source_message_utf8_sha256"] != _bytes_sha256(source_bytes)
            or anchor["exact_quote_utf8_sha256"] != _bytes_sha256(quote_bytes)
        ):
            _fail("m3_exact_anchor_invalid")
        normalized_anchors.append(dict(anchor))
    m2 = value["m2_snapshot"]
    expected_m2 = {
        "projection_sha256", "projection_domain", "canonicalization_version",
        "authoritative_empty", "authorship_result_state", "selected_item_ids",
    }
    if (
        not isinstance(m2, Mapping)
        or set(m2) != expected_m2
        or not isinstance(m2["projection_sha256"], str)
        or len(m2["projection_sha256"]) != 64
        or m2["projection_domain"] != "m2_authoritative_projection_sorted_json_utf8_v1"
        or m2["canonicalization_version"] != CANONICAL_JSON_VERSION
        or type(m2["authoritative_empty"]) is not bool
        or m2["authorship_result_state"] not in {"explicit_no_delta", "no_authored_result", "authored_operations"}
        or not isinstance(m2["selected_item_ids"], list)
    ):
        _fail("m3_m2_snapshot_invalid")
    if m2["authoritative_empty"] != (not m2["selected_item_ids"]):
        _fail("m3_m2_snapshot_invalid")
    if value["authorship"] not in AUTHORSHIP or value["exactness"] != "derived":
        _fail("m3_episode_authority_invalid")
    if not isinstance(value["derived_summary"], str) or not value["derived_summary"]:
        _fail("m3_episode_summary_invalid")
    if not isinstance(value["uncertainty"], str):
        _fail("m3_episode_uncertainty_invalid")
    provenance = value["provenance"]
    if not isinstance(provenance, Mapping) or set(provenance) != {"derivation_owner", "derivation_version", "source_snapshot_sha256"}:
        _fail("m3_episode_provenance_invalid")
    try:
        scope = _normalize_scope(value["scope"], room_id=room_id)
    except Milestone3ContextError as exc:
        raise Milestone3ContextError("m3_episode_scope_invalid") from exc
    if any(unit["scope"] != scope for unit in source_units):
        _fail("m3_episode_scope_invalid")
    normalized = {
        "schema_version": EPISODE_SCHEMA_VERSION,
        "episode_id": _identifier(value["episode_id"], prefix="m3_episode_"),
        "room_id": room_id,
        "source_unit_ids": unit_ids,
        "source_start_id": source_ids[0],
        "source_end_id": source_ids[-1],
        "authorship": value["authorship"],
        "provenance": dict(provenance),
        "scope": scope,
        "uncertainty": value["uncertainty"],
        "exactness": "derived",
        "derived_summary": value["derived_summary"],
        "structured_fields": normalized_fields,
        "exact_anchors": normalized_anchors,
        "m2_snapshot": dict(m2),
    }
    return normalized


def episode_unicode_index(episode: Mapping[str, Any]) -> dict[str, Any]:
    searchable_values = [str(episode["derived_summary"])]
    searchable_values.extend(
        str(entry["value"])
        for field in STRUCTURED_FIELDS
        for entry in episode["structured_fields"][field]
        if entry["availability"] == "known"
    )
    searchable_values.extend(
        str(anchor["exact_quote"])
        for anchor in episode["exact_anchors"]
    )
    tokens = unicode_search_tokens("\n".join(searchable_values))
    body = {
        "normalization_version": UNICODE_NORMALIZATION_VERSION,
        "tokenizer_version": UNICODE_TOKENIZER_VERSION,
        "tokens": list(tokens),
        "structured_fields_indexed": list(STRUCTURED_FIELDS),
        "exact_anchor_quotation_indexed": True,
    }
    return {
        **body,
        "index_domain": UNICODE_INDEX_DOMAIN,
        "index_canonicalization_version": CANONICAL_JSON_VERSION,
        "index_sha256": canonical_sha256(body),
    }


class Milestone3ContextStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "milestone3_context.sqlite3"
        self.connection = sqlite3.connect(self.path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS rooms(
              room_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
              snapshot_sha256 TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_units(
              unit_id TEXT PRIMARY KEY, room_id TEXT NOT NULL, sequence INTEGER NOT NULL,
              canonical_json TEXT NOT NULL, canonical_sha256 TEXT NOT NULL,
              UNIQUE(room_id,sequence)
            );
            CREATE TABLE IF NOT EXISTS zone_memberships(
              unit_id TEXT PRIMARY KEY, room_id TEXT NOT NULL, zone TEXT NOT NULL,
              episode_id TEXT, transition_revision INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS episodes(
              episode_id TEXT PRIMARY KEY, room_id TEXT NOT NULL, zone TEXT NOT NULL,
              canonical_json TEXT NOT NULL, canonical_sha256 TEXT NOT NULL,
              created_revision INTEGER NOT NULL, zone_revision INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS receipts(
              attempt_id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL,
              receipt_kind TEXT NOT NULL, receipt_json TEXT NOT NULL,
              receipt_sha256 TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshots(
              room_id TEXT NOT NULL, revision INTEGER NOT NULL,
              projection_json TEXT NOT NULL, projection_sha256 TEXT NOT NULL,
              PRIMARY KEY(room_id,revision)
            );
            """
        )
        row = self.connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is None:
            self.connection.execute("INSERT INTO meta(key,value) VALUES('schema_version',?)", (STORE_SCHEMA_VERSION,))
        elif row["value"] != STORE_SCHEMA_VERSION:
            _fail("m3_store_schema_mismatch")

    def _unit_rows(self, room_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT s.*,z.zone,z.episode_id,z.transition_revision "
            "FROM source_units s JOIN zone_memberships z ON z.unit_id=s.unit_id "
            "WHERE s.room_id=? ORDER BY s.sequence,s.unit_id", (room_id,)
        ).fetchall()

    def _episode_rows(self, room_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM episodes WHERE room_id=? ORDER BY created_revision,episode_id", (room_id,)
        ).fetchall()

    def _projection_body(self, room_id: str, revision: int) -> dict[str, Any]:
        units = self._unit_rows(room_id)
        episodes = self._episode_rows(room_id)
        zones = {zone: [] for zone in ("hot", "warm", "cold")}
        for row in units:
            if row["zone"] not in ZONE_KINDS:
                _fail("m3_zone_invalid")
            zones[row["zone"]].append({
                "unit_id": row["unit_id"],
                "sequence": row["sequence"],
                "source_unit_sha256": row["canonical_sha256"],
                "episode_id": row["episode_id"],
                "transition_revision": row["transition_revision"],
            })
        episode_manifests = [
            {
                "episode_id": row["episode_id"], "zone": row["zone"],
                "episode_sha256": row["canonical_sha256"],
                "created_revision": row["created_revision"], "zone_revision": row["zone_revision"],
            }
            for row in episodes
        ]
        all_ids = [entry["unit_id"] for zone in zones.values() for entry in zone]
        if len(all_ids) != len(set(all_ids)):
            _fail("m3_zone_overlap")
        return {
            "schema_version": ZONE_PROJECTION_SCHEMA_VERSION,
            "canonicalization_version": CANONICAL_JSON_VERSION,
            "evidence_domain": ZONE_PROJECTION_DOMAIN,
            "room_id": room_id,
            "revision": revision,
            "zones": zones,
            "episode_manifests": episode_manifests,
            "source_eviction_enabled": False,
            "memory_g_activated": False,
            "memory_authority_write": False,
            "m2_authority_write": False,
        }

    def projection(self, room_id: str) -> dict[str, Any]:
        room_id = _identifier(room_id, prefix="cws_room_")
        row = self.connection.execute("SELECT * FROM rooms WHERE room_id=?", (room_id,)).fetchone()
        revision = int(row["revision"]) if row is not None else 0
        body = self._projection_body(room_id, revision)
        projection_sha256 = canonical_sha256(body)
        if row is not None and row["snapshot_sha256"] != projection_sha256:
            _fail("m3_snapshot_integrity_invalid")
        return {**body, "projection_sha256": projection_sha256}

    def _persist_snapshot(self, room_id: str, revision: int) -> dict[str, Any]:
        body = self._projection_body(room_id, revision)
        sha = canonical_sha256(body)
        encoded = canonical_json_bytes(body).decode("utf-8")
        self.connection.execute(
            "INSERT INTO rooms(room_id,revision,snapshot_sha256) VALUES(?,?,?) "
            "ON CONFLICT(room_id) DO UPDATE SET revision=excluded.revision,snapshot_sha256=excluded.snapshot_sha256",
            (room_id, revision, sha),
        )
        self.connection.execute(
            "INSERT INTO snapshots(room_id,revision,projection_json,projection_sha256) VALUES(?,?,?,?)",
            (room_id, revision, encoded, sha),
        )
        return {**body, "projection_sha256": sha}

    def receipt(self, attempt_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT receipt_json FROM receipts WHERE attempt_id=?", (attempt_id,)).fetchone()
        return json.loads(row["receipt_json"]) if row is not None else None

    def _existing_receipt(self, attempt_id: str, request_sha256: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT request_sha256,receipt_json FROM receipts WHERE attempt_id=?", (attempt_id,)
        ).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != request_sha256:
            _fail("m3_attempt_identity_conflict")
        return json.loads(row["receipt_json"])

    def _write_receipt(self, attempt_id: str, request_sha256: str, kind: str, body: Mapping[str, Any]) -> dict[str, Any]:
        receipt = {**dict(body), "receipt_sha256": canonical_sha256(body)}
        self.connection.execute(
            "INSERT INTO receipts(attempt_id,request_sha256,receipt_kind,receipt_json,receipt_sha256) VALUES(?,?,?,?,?)",
            (attempt_id, request_sha256, kind, canonical_json_bytes(receipt).decode("utf-8"), receipt["receipt_sha256"]),
        )
        return receipt

    def _conflict_receipt(
        self, *, attempt_id: str, request_sha256: str, room_id: str,
        expected_revision: int, expected_snapshot_sha256: str,
        observed: Mapping[str, Any], operation: str,
    ) -> dict[str, Any]:
        body = {
            "schema_version": TRANSITION_RECEIPT_SCHEMA_VERSION,
            "attempt_id": attempt_id, "operation": operation,
            "state": "conflict_failed_closed", "room_id": room_id,
            "predecessor_revision_expected": expected_revision,
            "predecessor_snapshot_sha256_expected": expected_snapshot_sha256,
            "predecessor_snapshot_domain": ZONE_PROJECTION_DOMAIN,
            "predecessor_canonicalization_version": CANONICAL_JSON_VERSION,
            "observed_revision": observed["revision"],
            "observed_snapshot_sha256": observed["projection_sha256"],
            "semantic_writes": 0, "partial_writes": 0,
            "source_eviction_enabled": False, "raw_material_present": False,
        }
        return self._write_receipt(attempt_id, request_sha256, "transition_conflict", body)

    def append_hot_units(
        self, *, room_id: str, expected_revision: int,
        expected_snapshot_sha256: str, attempt_id: str,
        units: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        room_id = _identifier(room_id, prefix="cws_room_")
        attempt_id = _identifier(attempt_id, prefix="m3_attempt_")
        normalized = [normalize_source_unit(unit) for unit in units]
        if not normalized or any(unit["room_id"] != room_id for unit in normalized):
            _fail("m3_hot_append_invalid")
        request = {"operation": "append_hot", "room_id": room_id, "expected_revision": expected_revision,
                   "expected_snapshot_sha256": expected_snapshot_sha256,
                   "unit_sha256s": [canonical_sha256(unit) for unit in normalized]}
        request_sha = canonical_sha256(request)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._existing_receipt(attempt_id, request_sha)
            if existing is not None:
                self.connection.commit()
                return existing
            before = self.projection(room_id)
            if before["revision"] != expected_revision or before["projection_sha256"] != expected_snapshot_sha256:
                receipt = self._conflict_receipt(
                    attempt_id=attempt_id, request_sha256=request_sha, room_id=room_id,
                    expected_revision=expected_revision, expected_snapshot_sha256=expected_snapshot_sha256,
                    observed=before, operation="append_hot",
                )
                self.connection.commit()
                return receipt
            existing_sequences = [row["sequence"] for row in self._unit_rows(room_id)]
            expected_first = (max(existing_sequences) + 1) if existing_sequences else 0
            if [unit["sequence"] for unit in normalized] != list(range(expected_first, expected_first + len(normalized))):
                _fail("m3_hot_sequence_invalid")
            new_revision = expected_revision + 1
            for unit in normalized:
                unit_json = canonical_json_bytes(unit).decode("utf-8")
                unit_sha = canonical_sha256(unit)
                self.connection.execute(
                    "INSERT INTO source_units(unit_id,room_id,sequence,canonical_json,canonical_sha256) VALUES(?,?,?,?,?)",
                    (unit["unit_id"], room_id, unit["sequence"], unit_json, unit_sha),
                )
                self.connection.execute(
                    "INSERT INTO zone_memberships(unit_id,room_id,zone,episode_id,transition_revision) VALUES(?,?, 'hot',NULL,?)",
                    (unit["unit_id"], room_id, new_revision),
                )
            after = self._persist_snapshot(room_id, new_revision)
            body = {
                "schema_version": TRANSITION_RECEIPT_SCHEMA_VERSION,
                "attempt_id": attempt_id, "operation": "append_hot", "state": "committed",
                "room_id": room_id, "predecessor_revision": expected_revision,
                "predecessor_snapshot_sha256": expected_snapshot_sha256,
                "predecessor_snapshot_domain": ZONE_PROJECTION_DOMAIN,
                "predecessor_canonicalization_version": CANONICAL_JSON_VERSION,
                "successor_revision": new_revision,
                "successor_snapshot_sha256": after["projection_sha256"],
                "successor_snapshot_domain": ZONE_PROJECTION_DOMAIN,
                "successor_canonicalization_version": CANONICAL_JSON_VERSION,
                "moved_unit_ids": [unit["unit_id"] for unit in normalized],
                "transition": "unclassified_to_hot", "omitted_unit_ids": [],
                "duplicate_unit_ids": [], "semantic_writes": 0, "partial_writes": 0,
                "source_eviction_enabled": False, "raw_material_present": False,
            }
            receipt = self._write_receipt(attempt_id, request_sha, "transition", body)
            self.connection.commit()
            return receipt
        except Exception:
            self.connection.rollback()
            raise

    def compact(
        self, *, room_id: str, expected_revision: int,
        expected_snapshot_sha256: str, attempt_id: str,
        episode: Mapping[str, Any], warm_to_cold_episode_ids: Sequence[str] = (),
    ) -> dict[str, Any]:
        room_id = _identifier(room_id, prefix="cws_room_")
        attempt_id = _identifier(attempt_id, prefix="m3_attempt_")
        cold_ids = [_identifier(item, prefix="m3_episode_") for item in warm_to_cold_episode_ids]
        if len(cold_ids) != len(set(cold_ids)):
            _fail("m3_warm_to_cold_duplicate_episode")
        raw_request = {
            "operation": "compact", "room_id": room_id, "expected_revision": expected_revision,
            "expected_snapshot_sha256": expected_snapshot_sha256, "episode": episode,
            "warm_to_cold_episode_ids": cold_ids,
        }
        request_sha = canonical_sha256(raw_request)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._existing_receipt(attempt_id, request_sha)
            if existing is not None:
                self.connection.commit()
                return existing
            before = self.projection(room_id)
            if before["revision"] != expected_revision or before["projection_sha256"] != expected_snapshot_sha256:
                receipt = self._conflict_receipt(
                    attempt_id=attempt_id, request_sha256=request_sha, room_id=room_id,
                    expected_revision=expected_revision, expected_snapshot_sha256=expected_snapshot_sha256,
                    observed=before, operation="compact",
                )
                self.connection.commit()
                return receipt
            rows_by_id = {row["unit_id"]: row for row in self._unit_rows(room_id)}
            requested_ids = list(episode.get("source_unit_ids") or []) if isinstance(episode, Mapping) else []
            hot_ids = [row["unit_id"] for row in self._unit_rows(room_id) if row["zone"] == "hot"]
            if not requested_ids or requested_ids != hot_ids[:len(requested_ids)]:
                _fail("m3_compaction_range_not_oldest_contiguous_hot")
            source_units = []
            for unit_id in requested_ids:
                row = rows_by_id.get(unit_id)
                if row is None or row["zone"] != "hot":
                    _fail("m3_compaction_source_not_hot")
                unit = json.loads(row["canonical_json"])
                if canonical_sha256(unit) != row["canonical_sha256"]:
                    _fail("m3_source_unit_integrity_invalid")
                source_units.append(unit)
            normalized_episode = normalize_episode(episode, source_units=source_units)
            cold_episode_rows = []
            for episode_id in cold_ids:
                row = self.connection.execute("SELECT * FROM episodes WHERE episode_id=?", (episode_id,)).fetchone()
                if row is None or row["room_id"] != room_id or row["zone"] != "warm":
                    _fail("m3_warm_to_cold_invalid")
                cold_episode_rows.append(row)
            new_revision = expected_revision + 1
            episode_sha = canonical_sha256(normalized_episode)
            self.connection.execute(
                "INSERT INTO episodes(episode_id,room_id,zone,canonical_json,canonical_sha256,created_revision,zone_revision) VALUES(?,?, 'warm',?,?,?,?)",
                (normalized_episode["episode_id"], room_id, canonical_json_bytes(normalized_episode).decode("utf-8"), episode_sha, new_revision, new_revision),
            )
            for unit_id in requested_ids:
                self.connection.execute(
                    "UPDATE zone_memberships SET zone='warm',episode_id=?,transition_revision=? WHERE unit_id=?",
                    (normalized_episode["episode_id"], new_revision, unit_id),
                )
            cold_unit_ids: list[str] = []
            for row in cold_episode_rows:
                self.connection.execute(
                    "UPDATE episodes SET zone='cold',zone_revision=? WHERE episode_id=?", (new_revision, row["episode_id"])
                )
                member_rows = self.connection.execute(
                    "SELECT unit_id FROM zone_memberships WHERE episode_id=? ORDER BY unit_id", (row["episode_id"],)
                ).fetchall()
                for member in member_rows:
                    cold_unit_ids.append(member["unit_id"])
                    self.connection.execute(
                        "UPDATE zone_memberships SET zone='cold',transition_revision=? WHERE unit_id=?",
                        (new_revision, member["unit_id"]),
                    )
            after = self._persist_snapshot(room_id, new_revision)
            after_ids = [entry["unit_id"] for zone in after["zones"].values() for entry in zone]
            before_ids = [entry["unit_id"] for zone in before["zones"].values() for entry in zone]
            if sorted(after_ids) != sorted(before_ids) or len(after_ids) != len(set(after_ids)):
                _fail("m3_transition_identity_loss_or_duplicate")
            body = {
                "schema_version": TRANSITION_RECEIPT_SCHEMA_VERSION,
                "attempt_id": attempt_id, "operation": "compact", "state": "committed",
                "room_id": room_id, "predecessor_revision": expected_revision,
                "predecessor_snapshot_sha256": expected_snapshot_sha256,
                "predecessor_snapshot_domain": ZONE_PROJECTION_DOMAIN,
                "predecessor_canonicalization_version": CANONICAL_JSON_VERSION,
                "successor_revision": new_revision,
                "successor_snapshot_sha256": after["projection_sha256"],
                "successor_snapshot_domain": ZONE_PROJECTION_DOMAIN,
                "successor_canonicalization_version": CANONICAL_JSON_VERSION,
                "episode_id": normalized_episode["episode_id"],
                "episode_sha256": episode_sha, "episode_domain": EPISODE_DOMAIN,
                "episode_canonicalization_version": CANONICAL_JSON_VERSION,
                "exact_anchor_evidence": [
                    {
                        "anchor_id": anchor["anchor_id"],
                        "before_source_slice_sha256": anchor["exact_quote_utf8_sha256"],
                        "after_episode_quote_sha256": _bytes_sha256(anchor["exact_quote"].encode("utf-8")),
                        "comparison_domain": "exact_anchor_quote_utf8_v1",
                        "canonicalization_version": "utf8_no_normalization_v1",
                        "equal": anchor["exact_quote_utf8_sha256"]
                        == _bytes_sha256(anchor["exact_quote"].encode("utf-8")),
                    }
                    for anchor in normalized_episode["exact_anchors"]
                ],
                "hot_to_warm_unit_ids": requested_ids,
                "warm_to_cold_episode_ids": cold_ids,
                "warm_to_cold_unit_ids": cold_unit_ids,
                "omitted_unit_ids": [], "duplicate_unit_ids": [],
                "semantic_writes": 0, "memory_authority_writes": 0,
                "m2_authority_writes": 0, "partial_writes": 0,
                "source_eviction_enabled": False, "raw_material_present": False,
            }
            receipt = self._write_receipt(attempt_id, request_sha, "transition", body)
            self.connection.commit()
            return receipt
        except Exception:
            self.connection.rollback()
            raise

    def _episode(self, episode_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT canonical_json,canonical_sha256 FROM episodes WHERE episode_id=?", (episode_id,)).fetchone()
        if row is None:
            _fail("m3_episode_missing")
        episode = json.loads(row["canonical_json"])
        if canonical_sha256(episode) != row["canonical_sha256"]:
            _fail("m3_episode_integrity_invalid")
        return episode

    def _source_unit(self, unit_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT canonical_json,canonical_sha256 FROM source_units WHERE unit_id=?", (unit_id,)).fetchone()
        if row is None:
            _fail("m3_source_unit_missing")
        unit = json.loads(row["canonical_json"])
        if canonical_sha256(unit) != row["canonical_sha256"]:
            _fail("m3_source_unit_integrity_invalid")
        return unit

    def source_unit(self, *, room_id: str, unit_id: str) -> dict[str, Any]:
        room_id = _identifier(room_id, prefix="cws_room_")
        unit_id = _identifier(unit_id, prefix="m3_unit_")
        row = self.connection.execute(
            "SELECT canonical_json,canonical_sha256 FROM source_units WHERE unit_id=? AND room_id=?",
            (unit_id, room_id),
        ).fetchone()
        if row is None:
            _fail("m3_source_unit_missing")
        unit = json.loads(row["canonical_json"])
        if canonical_sha256(unit) != row["canonical_sha256"]:
            _fail("m3_source_unit_integrity_invalid")
        return unit

    def episode(self, *, room_id: str, episode_id: str) -> dict[str, Any]:
        room_id = _identifier(room_id, prefix="cws_room_")
        episode_id = _identifier(episode_id, prefix="m3_episode_")
        row = self.connection.execute(
            "SELECT canonical_json,canonical_sha256 FROM episodes WHERE episode_id=? AND room_id=?",
            (episode_id, room_id),
        ).fetchone()
        if row is None:
            _fail("m3_episode_missing")
        episode = json.loads(row["canonical_json"])
        if canonical_sha256(episode) != row["canonical_sha256"]:
            _fail("m3_episode_integrity_invalid")
        return episode

    def _persist_auxiliary_receipt(self, attempt_id: str, request: Mapping[str, Any], kind: str, body: Mapping[str, Any]) -> dict[str, Any]:
        attempt_id = _identifier(attempt_id, prefix="m3_attempt_")
        request_sha = canonical_sha256(request)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._existing_receipt(attempt_id, request_sha)
            if existing is not None:
                self.connection.commit()
                return existing
            receipt = self._write_receipt(attempt_id, request_sha, kind, body)
            self.connection.commit()
            return receipt
        except Exception:
            self.connection.rollback()
            raise

    def retrieve_cold(
        self, *, room_id: str, query: str, budget_chars: int, attempt_id: str,
    ) -> dict[str, Any]:
        room_id = _identifier(room_id, prefix="cws_room_")
        if not isinstance(query, str) or not query.strip():
            _fail("m3_cold_query_invalid")
        budget_chars = _strict_int(budget_chars, minimum=1)
        normalized_query = unicodedata.normalize("NFKC", query).casefold()
        query_terms = unicode_search_tokens(query)
        candidates = []
        indexed_episodes = []
        for row in self._episode_rows(room_id):
            if row["zone"] != "cold":
                continue
            episode = self._episode(row["episode_id"])
            index = episode_unicode_index(episode)
            indexed_episodes.append(
                {
                    "episode_id": episode["episode_id"],
                    "episode_sha256": canonical_sha256(episode),
                    "index_sha256": index["index_sha256"],
                }
            )
            indexed_tokens = set(index["tokens"])
            score = sum(1 for term in query_terms if term in indexed_tokens)
            if score:
                candidates.append((score, row["created_revision"], episode))
        candidates.sort(key=lambda item: (-item[0], -item[1], item[2]["episode_id"]))
        selected = []
        used = 0
        for score, _, episode in candidates:
            rendered = _render_episode(episode, heading="Retrieved archived context:")
            candidate_selected = [*selected, (score, episode, rendered)]
            candidate_text = "\n".join(item[2] for item in candidate_selected)
            if len(candidate_text) <= budget_chars:
                selected = candidate_selected
                used = len(candidate_text)
        section = None
        if selected:
            section = {
                "section_id": "continuity_cold_context",
                "section_class": "continuity_cold_context",
                "exactness": "derived",
                "update_frequency": "per_turn",
                "rendered_text": "\n".join(item[2] for item in selected),
            }
            if len(section["rendered_text"]) != used or used > budget_chars:
                _fail("m3_cold_budget_accounting_invalid")
        index_identity = canonical_sha256(indexed_episodes)
        request = {"operation": "cold_retrieval", "room_id": room_id,
                   "query_sha256": _bytes_sha256(normalized_query.encode("utf-8")), "budget_chars": budget_chars,
                   "query_tokens_sha256": canonical_sha256(list(query_terms)),
                   "index_identity": index_identity,
                   "snapshot_sha256": self.projection(room_id)["projection_sha256"]}
        body = {
            "schema_version": COLD_RECEIPT_SCHEMA_VERSION,
            "attempt_id": attempt_id, "state": "selected" if selected else "no_match",
            "room_id": room_id, "query_domain": UNICODE_QUERY_DOMAIN,
            "query_canonicalization_version": UNICODE_NORMALIZATION_VERSION,
            "query_tokenizer_version": UNICODE_TOKENIZER_VERSION,
            "query_sha256": request["query_sha256"],
            "query_tokens_sha256": request["query_tokens_sha256"],
            "selected_episode_ids": [item[1]["episode_id"] for item in selected],
            "selected_episode_sha256s": [canonical_sha256(item[1]) for item in selected],
            "selected_section_sha256": canonical_sha256(section) if section is not None else None,
            "selected_section_domain": "m3_cold_provider_section_sorted_json_utf8_v1",
            "selected_section_canonicalization_version": CANONICAL_JSON_VERSION,
            "episode_domain": EPISODE_DOMAIN,
            "episode_canonicalization_version": CANONICAL_JSON_VERSION,
            "budget_chars": budget_chars, "used_chars": used,
            "cold_attached_by_default": False, "explicit_retrieval": True,
            "cold_index_state": "deterministic_unicode_episode_field_and_anchor_index",
            "cold_index_domain": UNICODE_INDEX_DOMAIN,
            "cold_index_canonicalization_version": CANONICAL_JSON_VERSION,
            "cold_index_normalization_version": UNICODE_NORMALIZATION_VERSION,
            "cold_index_tokenizer_version": UNICODE_TOKENIZER_VERSION,
            "cold_index_identity": index_identity,
            "indexed_exact_anchor_quotation": True,
            "indexed_cold_episode_ids": [
                row["episode_id"] for row in self._episode_rows(room_id)
                if row["zone"] == "cold"
            ],
            "memory_g_activated": False, "durable_memory_promoted": False,
            "memory_authority_write": False, "m2_authority_write": False,
            "active_state_fabricated": False, "raw_material_present": False,
        }
        receipt = self._persist_auxiliary_receipt(attempt_id, request, "cold_selection", body)
        return {"section": section, "receipt": receipt}

    def assemble_provider_sections(
        self, *, room_id: str, required_m2_section: Mapping[str, Any] | None,
        budget_chars: int, attempt_id: str,
        explicit_cold_selection: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        room_id = _identifier(room_id, prefix="cws_room_")
        budget_chars = _strict_int(budget_chars, minimum=1)
        if budget_chars > MAX_DYNAMIC_BUDGET_CHARS:
            _fail("m3_dynamic_budget_invalid")
        m2_chars = len(str(required_m2_section.get("rendered_text") or "")) if isinstance(required_m2_section, Mapping) else 0
        projection = self.projection(room_id)
        cold_section = None
        selected_cold_ids: list[str] = []
        if explicit_cold_selection is not None:
            if not isinstance(explicit_cold_selection, Mapping) or set(explicit_cold_selection) != {"section", "receipt"}:
                _fail("m3_cold_selection_binding_invalid")
            cold_section = explicit_cold_selection["section"]
            cold_receipt = explicit_cold_selection["receipt"]
            if not isinstance(cold_section, Mapping) or not isinstance(cold_receipt, Mapping):
                _fail("m3_cold_selection_binding_invalid")
            attempt = cold_receipt.get("attempt_id")
            stored_receipt = self.receipt(attempt) if isinstance(attempt, str) else None
            selected_cold_ids = list(cold_receipt.get("selected_episode_ids") or [])
            cold_manifest_ids = {
                entry["episode_id"] for entry in projection["episode_manifests"]
                if entry["zone"] == "cold"
            }
            if (
                stored_receipt != dict(cold_receipt)
                or cold_receipt.get("state") != "selected"
                or cold_section.get("section_id") != "continuity_cold_context"
                or cold_receipt.get("selected_section_sha256") != canonical_sha256(cold_section)
                or not selected_cold_ids
                or len(selected_cold_ids) != len(set(selected_cold_ids))
                or not set(selected_cold_ids).issubset(cold_manifest_ids)
            ):
                _fail("m3_cold_selection_binding_invalid")
        request = {"operation": "provider_selection", "room_id": room_id,
                   "snapshot_sha256": projection["projection_sha256"], "budget_chars": budget_chars,
                   "m2_section_sha256": canonical_sha256(required_m2_section) if required_m2_section is not None else None,
                   "cold_section_sha256": canonical_sha256(cold_section) if cold_section is not None else None,
                   "cold_episode_ids": selected_cold_ids}
        if m2_chars > budget_chars:
            body = {
                "schema_version": SELECTION_RECEIPT_SCHEMA_VERSION,
                "attempt_id": attempt_id, "state": "required_m2_budget_failed_closed",
                "room_id": room_id, "budget_chars": budget_chars, "required_m2_chars": m2_chars,
                "required_m2_section_sha256": canonical_sha256(required_m2_section)
                if required_m2_section is not None else None,
                "required_m2_section_domain": "m2_provider_section_sorted_json_utf8_v1",
                "required_m2_section_canonicalization_version": CANONICAL_JSON_VERSION,
                "selected_hot_unit_ids": [], "selected_warm_episode_ids": [],
                "selected_cold_episode_ids": [], "hot_warm_overlap_unit_ids": [],
                "cold_attached_by_default": False, "m2_suppressed": False,
                "source_eviction_enabled": False, "raw_material_present": False,
            }
            receipt = self._persist_auxiliary_receipt(attempt_id, request, "provider_selection", body)
            return {"state": "failed_closed", "sections": [], "receipt": receipt}
        remaining = budget_chars - m2_chars
        hot_units = [self._source_unit(entry["unit_id"]) for entry in projection["zones"]["hot"]]
        selected_hot: list[tuple[dict[str, Any], str, list[dict[str, Any]]]] = []
        for unit in reversed(hot_units):
            rendered, conversions = _render_hot_unit(unit)
            candidate_hot = [(unit, rendered, conversions), *selected_hot]
            candidate_text = "Recent complete source turns:\n" + "\n".join(
                item[1] for item in candidate_hot
            )
            current_text = (
                "Recent complete source turns:\n" + "\n".join(item[1] for item in selected_hot)
                if selected_hot else ""
            )
            incremental_chars = len(candidate_text) - len(current_text)
            if incremental_chars <= remaining:
                selected_hot = candidate_hot
                remaining -= incremental_chars
            else:
                break
        warm_ids = [entry["episode_id"] for entry in projection["episode_manifests"] if entry["zone"] == "warm"]
        selected_warm: list[tuple[dict[str, Any], str]] = []
        for episode_id in reversed(warm_ids):
            episode = self._episode(episode_id)
            rendered = _render_episode(episode, heading="Earlier compacted context (derived background, not active truth):")
            candidate_warm = [(episode, rendered), *selected_warm]
            candidate_text = "\n".join(item[1] for item in candidate_warm)
            current_text = "\n".join(item[1] for item in selected_warm)
            incremental_chars = len(candidate_text) - len(current_text)
            if incremental_chars <= remaining:
                selected_warm = candidate_warm
                remaining -= incremental_chars
        sections = []
        if cold_section is not None:
            cold_text = str(cold_section.get("rendered_text") or "")
            if cold_text and len(cold_text) <= remaining:
                sections.append(deepcopy(dict(cold_section)))
                remaining -= len(cold_text)
            else:
                selected_cold_ids = []
        if selected_warm:
            sections.append({
                "section_id": "continuity_warm_context", "section_class": "continuity_warm_context",
                "exactness": "derived", "update_frequency": "per_turn",
                "rendered_text": "\n".join(item[1] for item in selected_warm),
            })
        if selected_hot:
            sections.append({
                "section_id": "continuity_hot_context", "section_class": "continuity_hot_context",
                "exactness": "exact"
                if all(
                    conversion["conversion_state"] == "identity_byte_preserving"
                    for item in selected_hot for conversion in item[2]
                )
                else "derived",
                "update_frequency": "per_turn",
                "rendered_text": "Recent complete source turns:\n" + "\n".join(item[1] for item in selected_hot),
            })
        hot_source_ids = {item[0]["unit_id"] for item in selected_hot}
        warm_source_ids = {unit_id for item in selected_warm for unit_id in item[0]["source_unit_ids"]}
        overlap = sorted(hot_source_ids & warm_source_ids)
        if overlap:
            _fail("m3_provider_hot_warm_overlap")
        body = {
            "schema_version": SELECTION_RECEIPT_SCHEMA_VERSION,
            "attempt_id": attempt_id, "state": "selected", "room_id": room_id,
            "snapshot_sha256": projection["projection_sha256"],
            "snapshot_domain": ZONE_PROJECTION_DOMAIN,
            "snapshot_canonicalization_version": CANONICAL_JSON_VERSION,
            "budget_chars": budget_chars, "required_m2_chars": m2_chars,
            "budget_domain": "provider_section_rendered_text_character_sum_v1",
            "budget_canonicalization_version": "unicode_codepoint_count_v1",
            "required_m2_section_sha256": canonical_sha256(required_m2_section)
            if required_m2_section is not None else None,
            "required_m2_section_domain": "m2_provider_section_sorted_json_utf8_v1",
            "required_m2_section_canonicalization_version": CANONICAL_JSON_VERSION,
            "remaining_chars": remaining,
            "emitted_context_chars": sum(len(section["rendered_text"]) for section in sections),
            "selected_section_identities": [
                {
                    "section_id": section["section_id"],
                    "section_sha256": canonical_sha256(section),
                    "section_domain": "m3_typed_provider_section_sorted_json_utf8_v1",
                    "canonicalization_version": CANONICAL_JSON_VERSION,
                }
                for section in sections
            ],
            "selected_hot_unit_ids": [item[0]["unit_id"] for item in selected_hot],
            "selected_warm_episode_ids": [item[0]["episode_id"] for item in selected_warm],
            "selected_cold_episode_ids": selected_cold_ids,
            "hot_warm_overlap_unit_ids": overlap,
            "cold_attached_by_default": False,
            "m2_suppressed": False, "m2_overridden": False,
            "complete_units_only": True, "solen_sentence_clipped": False,
            "provider_redacted_hot_unit_ids": [
                item[0]["unit_id"] for item in selected_hot
                if any(conversion["conversion_state"] != "identity_byte_preserving" for conversion in item[2])
            ],
            "provider_conversion_receipts": [
                conversion for item in selected_hot for conversion in item[2]
            ],
            "provider_section_composition_receipts": [
                _provider_section_composition_receipt(
                    section,
                    [conversion for item in selected_hot for conversion in item[2]],
                )
                for section in sections
                if section["section_id"] == "continuity_hot_context"
            ],
            "provider_section_domain": PROVIDER_SECTION_DOMAIN,
            "provider_section_canonicalization_version": "utf8_no_normalization_v1",
            "source_eviction_enabled": False, "memory_g_activated": False,
            "memory_authority_write": False, "m2_authority_write": False,
            "raw_material_present": False,
        }
        if body["emitted_context_chars"] + m2_chars > budget_chars:
            _fail("m3_emitted_budget_exceeded")
        receipt = self._persist_auxiliary_receipt(attempt_id, request, "provider_selection", body)
        return {"state": "selected", "sections": sections, "receipt": receipt}

    def persist_selector_rollback(
        self, *, room_id: str, attempt_id: str,
        selected_dynamic_context: Sequence[str],
        prior_dynamic_context: Sequence[str],
        m3_sections: Sequence[Mapping[str, Any]],
        selection_attempt_id: str,
    ) -> dict[str, Any]:
        projection = self.projection(room_id)
        selection_receipt = self.receipt(selection_attempt_id)
        supplied_identities = [
            {
                "section_id": section.get("section_id"),
                "section_sha256": canonical_sha256(section),
                "section_domain": "m3_typed_provider_section_sorted_json_utf8_v1",
                "canonicalization_version": CANONICAL_JSON_VERSION,
            }
            for section in m3_sections
            if isinstance(section, Mapping)
        ]
        if (
            selection_receipt is None
            or selection_receipt.get("state") != "selected"
            or selection_receipt.get("room_id") != room_id
            or selection_receipt.get("snapshot_sha256") != projection["projection_sha256"]
            or supplied_identities != selection_receipt.get("selected_section_identities")
        ):
            _fail("m3_selector_selection_binding_invalid")
        receipt = selector_rollback_receipt(
            predecessor_revision=projection["revision"],
            predecessor_snapshot_sha256=projection["projection_sha256"],
            selected_dynamic_context=selected_dynamic_context,
            prior_dynamic_context=prior_dynamic_context,
            m3_sections=m3_sections,
            selection_attempt_id=selection_attempt_id,
            selection_receipt_sha256=selection_receipt["receipt_sha256"],
        )
        request = {
            "operation": "selector_rollback", "room_id": room_id,
            "predecessor_revision": projection["revision"],
            "predecessor_snapshot_sha256": projection["projection_sha256"],
            "selected_dynamic_context_sha256": canonical_sha256(list(selected_dynamic_context)),
            "prior_dynamic_context_sha256": canonical_sha256(list(prior_dynamic_context)),
            "m3_sections_sha256": canonical_sha256(list(m3_sections)),
            "selection_attempt_id": selection_attempt_id,
            "selection_receipt_sha256": selection_receipt["receipt_sha256"],
        }
        body = dict(receipt)
        body.pop("receipt_sha256")
        return self._persist_auxiliary_receipt(
            attempt_id, request, "selector_rollback", body
        )

    def doctor(self) -> dict[str, Any]:
        integrity = self.connection.execute("PRAGMA integrity_check").fetchone()[0]
        rooms = self.connection.execute("SELECT room_id FROM rooms ORDER BY room_id").fetchall()
        replay_exact = True
        for row in rooms:
            projection = self.projection(row["room_id"])
            stored = self.connection.execute(
                "SELECT projection_sha256 FROM snapshots WHERE room_id=? AND revision=?",
                (row["room_id"], projection["revision"]),
            ).fetchone()
            replay_exact = replay_exact and stored is not None and stored["projection_sha256"] == projection["projection_sha256"]
        return {
            "schema_version": SCHEMA_VERSION,
            "state": "healthy" if integrity == "ok" and replay_exact else "unhealthy",
            "store_schema_version": STORE_SCHEMA_VERSION,
            "sqlite_integrity": integrity, "replay_exact": replay_exact,
            "source_eviction_enabled": False, "memory_g_activated": False,
            "memory_authority_write": False, "m2_authority_write": False,
        }


def _provider_section_composition_receipt(
    section: Mapping[str, Any], conversions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rendered_bytes = str(section["rendered_text"]).encode("utf-8")
    body = {
        "schema_version": EQUALITY_RECEIPT_SCHEMA_VERSION,
        "conversion_name": "m3_hot_provider_section_renderer_v1",
        "conversion_version": "m3_hot_provider_section_renderer_v1",
        "input_domain": PROVIDER_MESSAGE_TEXT_DOMAIN,
        "input_canonicalization_version": "utf8_no_normalization_v1",
        "input_conversion_receipt_sha256s": [
            conversion["receipt_sha256"] for conversion in conversions
        ],
        "input_binding_sha256": canonical_sha256(
            [
                {
                    "unit_id": conversion["unit_id"],
                    "message_id": conversion["message_id"],
                    "output_sha256": conversion["output_sha256"],
                }
                for conversion in conversions
            ]
        ),
        "output_domain": PROVIDER_SECTION_DOMAIN,
        "output_canonicalization_version": "utf8_no_normalization_v1",
        "output_sha256": _bytes_sha256(rendered_bytes),
        "cross_domain_equal": None,
        "composition_state": "bound",
        "raw_material_present": False,
    }
    return {**body, "receipt_sha256": canonical_sha256(body)}


def _render_hot_unit(unit: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    lines = []
    conversions = []
    for message in unit["messages"]:
        source = message["text"]
        conversion = provider_visible_conversion_receipt(source)
        visible = conversion["provider_text"]
        conversion_receipt = {
            "unit_id": unit["unit_id"],
            "message_id": message["message_id"],
            **conversion["receipt"],
        }
        conversions.append(conversion_receipt)
        label = "Astel" if message["side"] == "astel" else "Solen"
        suffix = (
            ""
            if conversion_receipt["conversion_state"] == "identity_byte_preserving"
            else " [provider-visible exact material denied]"
            if conversion_receipt["conversion_state"] == "denied_unavailable"
            else " [provider-visible derived representation]"
        )
        lines.append(f"- {label}: {visible}{suffix}")
    return "\n".join(lines), conversions


def _render_episode(episode: Mapping[str, Any], *, heading: str) -> str:
    safe_summary = provider_text_safety.sanitize_provider_visible_text(
        episode["derived_summary"]
    )
    summary_suffix = (
        ""
        if safe_summary == episode["derived_summary"]
        else " [provider-visible derived representation]"
    )
    lines = [heading, f"- Episode {episode['episode_id']}: {safe_summary}{summary_suffix}"]
    labels = {
        "open_loops": "Open loop", "decisions": "Historical decision evidence",
        "emotional_relational_threads": "Unresolved relational thread",
        "task_phase": "Task phase", "intended_next_action": "Intended next action",
        "temporary_facts": "Temporary fact", "solen_intentions": "Solen intention",
    }
    for field in STRUCTURED_FIELDS:
        for entry in episode["structured_fields"][field]:
            if entry["availability"] == "known":
                safe_value = provider_text_safety.sanitize_provider_visible_text(
                    entry["value"]
                )
                value_suffix = (
                    ""
                    if safe_value == entry["value"]
                    else " [provider-visible derived representation]"
                )
                lines.append(
                    f"- {labels[field]} ({entry['exactness']}, {entry['authorship']}): "
                    f"{safe_value}{value_suffix}"
                )
            else:
                lines.append(f"- {labels[field]}: {entry['availability']}")
    for anchor in episode["exact_anchors"]:
        conversion = provider_visible_conversion_receipt(anchor["exact_quote"])
        if conversion["receipt"]["conversion_state"] == "identity_byte_preserving":
            lines.append(
                f"- Exact anchor [{anchor['anchor_id']}]: {anchor['exact_quote']}"
            )
        else:
            lines.append(
                f"- Exact anchor [{anchor['anchor_id']}]: unavailable for provider-visible exact use."
            )
    m2 = episode["m2_snapshot"]
    if m2["authoritative_empty"]:
        lines.append("- M2 compaction-boundary state: authoritative_empty.")
    lines.append(
        "- M2 authorship-result state at compaction: "
        f"{m2['authorship_result_state']}."
    )
    lines.append("- Authority: derived context evidence only; Milestone-2 structured continuity remains active truth.")
    return "\n".join(lines)


def control_state(env: Mapping[str, str]) -> dict[str, Any]:
    mode = str(env.get(SWITCH_ENV, OFF) or OFF).strip().lower()
    selector = str(env.get(SELECTOR_ENV, OFF) or OFF).strip().lower()
    if mode not in {OFF, COPY_REHEARSAL} or selector not in {OFF, ON}:
        _fail("m3_control_invalid")
    if mode == OFF and selector != OFF:
        _fail("m3_control_invalid")
    budget_text = str(env.get(BUDGET_ENV, DEFAULT_DYNAMIC_BUDGET_CHARS))
    try:
        budget = int(budget_text)
    except ValueError as exc:
        raise Milestone3ContextError("m3_dynamic_budget_invalid") from exc
    if budget < 1 or budget > MAX_DYNAMIC_BUDGET_CHARS:
        _fail("m3_dynamic_budget_invalid")
    return {"mode": mode, "selector": selector, "budget_chars": budget}


def generation2_sections_from_env(
    env: Mapping[str, str], *, room_id: str,
    required_m2_section: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    state = control_state(env)
    if state["mode"] == OFF or state["selector"] == OFF:
        return []
    if required_m2_section is None:
        _fail("m3_m2_section_required")
    root_value = env.get(ROOT_ENV)
    if not isinstance(root_value, str) or not root_value.strip():
        _fail("m3_context_root_unavailable")
    context_root = Path(root_value).resolve() / "context"
    if not context_root.exists() or not context_root.is_dir():
        _fail("m3_context_root_unavailable")
    store = Milestone3ContextStore(context_root)
    try:
        projection = store.projection(room_id)
        attempt_id = "m3_attempt_" + canonical_sha256({
            "kind": "generation2_selection", "room_id": room_id,
            "snapshot": projection["projection_sha256"], "budget": state["budget_chars"],
            "m2": canonical_sha256(required_m2_section) if required_m2_section is not None else None,
        })[:32]
        result = store.assemble_provider_sections(
            room_id=room_id, required_m2_section=required_m2_section,
            budget_chars=state["budget_chars"], attempt_id=attempt_id,
        )
        if result["state"] != "selected":
            _fail("m3_required_m2_budget_failed_closed")
        return result["sections"]
    finally:
        store.close()


def selector_rollback_receipt(
    *, predecessor_revision: int, predecessor_snapshot_sha256: str,
    selected_dynamic_context: Sequence[str], prior_dynamic_context: Sequence[str],
    m3_sections: Sequence[Mapping[str, Any]], selection_attempt_id: str,
    selection_receipt_sha256: str,
) -> dict[str, Any]:
    _strict_int(predecessor_revision)
    if not isinstance(predecessor_snapshot_sha256, str) or len(predecessor_snapshot_sha256) != 64:
        _fail("m3_selector_predecessor_invalid")
    _identifier(selection_attempt_id, prefix="m3_attempt_")
    if not isinstance(selection_receipt_sha256, str) or len(selection_receipt_sha256) != 64:
        _fail("m3_selector_selection_binding_invalid")
    derived_prior = list(selected_dynamic_context)
    removed_section_ids = []
    for section in m3_sections:
        if not isinstance(section, Mapping):
            _fail("m3_selector_projection_invalid")
        section_id = section.get("section_id")
        rendered_text = section.get("rendered_text")
        if (
            section_id not in {
                "continuity_cold_context", "continuity_warm_context",
                "continuity_hot_context",
            }
            or not isinstance(rendered_text, str)
            or derived_prior.count(rendered_text) != 1
        ):
            _fail("m3_selector_projection_invalid")
        removed_section_ids.append(section_id)
        derived_prior.remove(rendered_text)
    if len(removed_section_ids) != len(set(removed_section_ids)):
        _fail("m3_selector_projection_invalid")
    selected_prior_bytes = canonical_json_bytes(derived_prior)
    prior_bytes = canonical_json_bytes(list(prior_dynamic_context))
    comparison = evidence_equality_receipt(
        left_bytes=selected_prior_bytes, left_domain=DYNAMIC_LIST_DOMAIN,
        left_canonicalization_version=CANONICAL_JSON_VERSION,
        right_bytes=prior_bytes, right_domain=DYNAMIC_LIST_DOMAIN,
        right_canonicalization_version=CANONICAL_JSON_VERSION,
    )
    body = {
        "schema_version": TRANSITION_RECEIPT_SCHEMA_VERSION,
        "operation": "selector_rollback", "state": "restored" if comparison["equal"] else "mismatch",
        "predecessor_revision": predecessor_revision,
        "predecessor_snapshot_sha256": predecessor_snapshot_sha256,
        "predecessor_snapshot_domain": ZONE_PROJECTION_DOMAIN,
        "predecessor_canonicalization_version": CANONICAL_JSON_VERSION,
        "selected_dynamic_context_sha256": canonical_sha256(list(selected_dynamic_context)),
        "removed_m3_section_ids": removed_section_ids,
        "derived_prior_dynamic_context_sha256": canonical_sha256(derived_prior),
        "selection_attempt_id": selection_attempt_id,
        "selection_receipt_sha256": selection_receipt_sha256,
        "selection_receipt_domain": "m3_provider_selection_receipt_sorted_json_utf8_v1",
        "selection_receipt_canonicalization_version": CANONICAL_JSON_VERSION,
        "restored_projection_comparison": comparison,
        "canonical_records_rewritten": False, "zone_records_rewritten": False,
        "source_eviction_enabled": False, "raw_material_present": False,
    }
    return {**body, "receipt_sha256": canonical_sha256(body)}


__all__ = [
    "BUDGET_ENV", "CANONICAL_JSON_VERSION", "COPY_REHEARSAL", "DYNAMIC_LIST_DOMAIN",
    "EPISODE_DOMAIN", "EPISODE_SCHEMA_VERSION", "Milestone3ContextError",
    "Milestone3ContextStore", "OFF", "ON", "ROOT_ENV", "SELECTOR_ENV", "SOURCE_TEXT_DOMAIN",
    "SOURCE_UNIT_SCHEMA_VERSION", "STRUCTURED_FIELDS", "SWITCH_ENV", "ZONE_PROJECTION_DOMAIN",
    "UNICODE_INDEX_DOMAIN", "UNICODE_NORMALIZATION_VERSION", "UNICODE_QUERY_DOMAIN",
    "UNICODE_TOKENIZER_VERSION",
    "canonical_json_bytes", "canonical_sha256", "control_state", "evidence_equality_receipt",
    "episode_unicode_index", "generation2_sections_from_env", "normalize_episode", "normalize_source_unit",
    "provider_boundary_denial_reason",
    "selector_rollback_receipt",
    "unicode_search_tokens",
]
