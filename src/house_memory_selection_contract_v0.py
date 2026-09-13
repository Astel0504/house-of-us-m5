from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

import house_memory_durable_event_contract_v0 as durable
import house_memory_curated_event_contract_v0 as curated_events
import house_memory_curated_projection_v0 as curated_projection


REQUEST_SCHEMA_VERSION = "house_memory_selection_request_v0"
RESULT_SCHEMA_VERSION = "house_memory_selection_result_v0"
TRACE_SCHEMA_VERSION = "house_memory_selection_trace_v0"

MODES = frozenset({"ordinary_talk", "standing_live"})
REQUESTED_CAPABILITIES = frozenset({"ambient_detail", "explicit_search", "manual_lookup", "exact_recall"})
SELECTION_SCOPES = frozenset({"ordinary_talk", "standing_live", "both"})
SOURCE_CHANNEL_CODES = frozenset(
    {
        "active_memory",
        "ordinary_memory",
        "reviewed_memory",
        "selected_memory_evidence",
        "standing_core",
        "synthetic_fixture",
        "api_talk_reviewed",
        "api_talk_active",
        "standing_live_lifecycle",
        "manual_lookup_adapter",
        "exact_recall_adapter",
    }
)
DIRECT_EVIDENCE_TIERS = (
    "none",
    "soft_lexical",
    "direct_current_turn_reference",
    "exact_source_identity",
    "exact_event_identity",
    "exact_record_identity",
)
DIRECT_EVIDENCE_RANK = {code: rank for rank, code in enumerate(DIRECT_EVIDENCE_TIERS)}
RELATION_EXPANSION_TYPES = frozenset({"same_event", "complements"})

REQUEST_FIELDS = frozenset(
    {
        "schema_version", "request_ref_hash", "mode", "requested_capability_code",
        "allowed_audience_scope_codes", "allowed_export_scope_codes", "max_selected",
        "max_relation_fanout", "nominations",
    }
)
NOMINATION_FIELDS = frozenset(
    {
        "memory_ref_hash",
        "canonical_record_version_hash",
        "selection_scope_code",
        "source_channel_code",
        "evidence_code",
        "evidence_strength_milli",
    }
)
PROJECTION_FIELDS = frozenset(
    {
        "schema_version", "replay_cursor", "event_count", "record_count", "relation_count",
        "proposal_count", "last_event_id", "event_chain_checksum", "record_refs", "relation_refs",
        "proposal_refs", "resolution_count", "resolution_refs", "records", "relations", "proposals",
        "resolutions",
    }
)
PROJECTION_RECORD_FIELDS = frozenset(
    {
        "memory_ref_hash", "canonical_record_version_hash", "participant_scope_code",
        "authority_scope_code", "authority_owner_code", "audience_scope_code", "status_code",
        "review_state_code", "provenance_present", "blocker_flags", "safe_capability_flags",
        "core_status", "core_resolution_required", "base_standing_footing_eligible",
        "standing_footing_eligible", "default_surfacing_eligible", "explicit_search_eligible",
        "manual_lookup_eligible", "exact_recall_eligible", "last_event_id", "last_reason_code",
        "event_count", "lifecycle_status",
    }
)
PROJECTION_RELATION_FIELDS = frozenset(
    {
        "payload_schema_version", "relation_ref_hash", "left_memory_ref_hash",
        "left_canonical_record_version_hash", "right_memory_ref_hash",
        "right_canonical_record_version_hash", "relation_type", "strength_milli",
        "evidence_ref_hash", "participant_scope_code", "authority_scope_code",
        "authority_owner_code", "audience_scope_code", "state", "eligible_for_expansion",
        "last_event_id",
    }
)
PROJECTION_RELATION_V2_FIELDS = PROJECTION_RELATION_FIELDS | frozenset({
    "left_authority_scope_code", "left_authority_owner_code", "right_authority_scope_code",
    "right_authority_owner_code", "participant_scope_code", "audience_scope_code", "evidence_class",
})
PROJECTION_PROPOSAL_FIELDS = frozenset(
    {
        "payload_schema_version", "proposal_ref_hash", "proposal_kind", "proposal_basis",
        "primary_memory_ref_hash", "primary_canonical_record_version_hash",
        "comparison_memory_ref_hash", "comparison_canonical_record_version_hash",
        "candidate_ref_hash", "proposal_origin_action_ref_hash", "participant_scope_code",
        "authority_scope_code", "authority_owner_code", "audience_scope_code", "state",
        "core_involved", "core_resolution_required", "proposal_blocker_flags",
        "canonical_record_changed", "automatic_supersession_made",
        "memory_vault_record_mutation_made", "writeback_candidate_mutation_made", "last_event_id",
    }
)
PROJECTION_RESOLUTION_FIELDS = frozenset({
    "payload_schema_version", "resolution_ref_hash", "candidate_id", "candidate_version_hash",
    "evolution_kind", "primary_memory_ref_hash", "primary_applied_version_hash",
    "comparison_memory_ref_hash", "comparison_applied_version_hash", "approved_by_actor_type",
    "approved_by_actor_ref_hash", "approval_authority_scope_code", "approval_authority_owner_code",
    "approval_evidence_ref_hash", "source_evidence_ref_hash", "provenance_evidence_ref_hash",
    "resolution_code", "disposition_code", "core_involved", "core_check_needed",
    "canonical_record_changed", "core_moved_or_removed", "participant_scope_code",
    "audience_scope_code", "resolution_blocker_flags", "state", "selection_expansion_authorized",
    "last_event_id",
})

_HASH_RE = re.compile(r"[0-9a-f]{64}")
_CURSOR_RE = re.compile(r"house_mem_cursor_[0-9a-f]{32}")
ALLOWED_AUDIENCE_SCOPES = frozenset({"astel_solen_private", "astel_only", "group_safe", "house_group_context"})
ALLOWED_EXPORT_SCOPES = frozenset({"private_house", "group_safe"})
MAX_INPUT_NOMINATIONS = 256
MAX_UNIQUE_REFS = 128
MAX_DIRECT_SEEDS = 32
MAX_RELATION_FANOUT_PER_NODE = 8
MAX_SELECTED = 5
MAX_MERGED_SOURCE_CODES = 8
MAX_MERGED_EVIDENCE_CODES = 8
SOURCE_CHANNEL_EVIDENCE_CODES = {
    "standing_core": frozenset({"none"}),
    "ordinary_memory": frozenset({"none"}),
    "reviewed_memory": frozenset({"none"}),
    "active_memory": frozenset({"none"}),
    "standing_live_lifecycle": frozenset({"none"}),
    "api_talk_reviewed": frozenset({"none", "soft_lexical", "direct_current_turn_reference"}),
    "api_talk_active": frozenset({"none", "soft_lexical", "direct_current_turn_reference"}),
    "selected_memory_evidence": frozenset({"none", "direct_current_turn_reference", "exact_record_identity"}),
    "manual_lookup_adapter": frozenset({"none", "direct_current_turn_reference", "exact_source_identity", "exact_record_identity"}),
    "exact_recall_adapter": frozenset(DIRECT_EVIDENCE_TIERS),
    "synthetic_fixture": frozenset(DIRECT_EVIDENCE_TIERS),
}
_FORBIDDEN_KEY_FRAGMENTS = (
    "body", "embedding", "env", "filesystem_path", "header", "private_path", "prompt", "query_text",
    "raw", "secret", "source_path", "storage_path",
    "summary", "tag", "title", "token", "transcript", "vector",
)


class HouseMemorySelectionContractError(ValueError):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.message = message


def _require_exact_fields(value: Any, fields: frozenset[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise HouseMemorySelectionContractError(
            f"invalid_{name}_fields", f"{name} fields must exactly match the raw-free allowlist."
        )
    return value


def require_hash(name: str, value: Any) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise HouseMemorySelectionContractError(f"invalid_{name}", f"{name} must be opaque SHA-256 hex.")
    return value


def require_code(name: str, value: Any, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise HouseMemorySelectionContractError(f"unsupported_{name}", f"{name} is not allowed.")
    return value


def require_bounded_int(name: str, value: Any, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise HouseMemorySelectionContractError(
            f"invalid_{name}", f"{name} must be an integer from {minimum} through {maximum}."
        )
    return value


def _require_safe_code(name: str, value: Any) -> str:
    try:
        return durable._require_code(name, value)
    except durable.HouseMemoryDurableEventError as exc:
        raise HouseMemorySelectionContractError(
            f"invalid_{name}", f"{name} is not a safe bounded code."
        ) from exc


def _require_canonical_code_list(name: str, value: Any, allowed: frozenset[str]) -> list[str]:
    if not isinstance(value, list) or value != sorted(set(value)) or len(value) > len(allowed):
        raise HouseMemorySelectionContractError(
            f"invalid_{name}", f"{name} must be a canonical sorted unique list."
        )
    if any(item not in allowed for item in value):
        raise HouseMemorySelectionContractError(f"invalid_{name}", f"{name} contains an unsupported code.")
    return value


def reject_forbidden_shape(value: Any, *, path: str = "selection") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).casefold()
            if any(fragment in key_text for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise HouseMemorySelectionContractError(
                    "forbidden_selection_field", f"Forbidden raw-capable field at {path}.{key}."
                )
            reject_forbidden_shape(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            reject_forbidden_shape(item, path=f"{path}[{index}]")


def normalize_nomination(value: Any) -> dict[str, Any]:
    source = _require_exact_fields(value, NOMINATION_FIELDS, "nomination")
    evidence_code = require_code("evidence_code", source["evidence_code"], frozenset(DIRECT_EVIDENCE_TIERS))
    evidence_strength = require_bounded_int(
        "evidence_strength_milli", source["evidence_strength_milli"], minimum=0, maximum=1000
    )
    if evidence_strength == 0 or (evidence_code == "soft_lexical" and evidence_strength < 700):
        evidence_code = "none"
        evidence_strength = 0
    source_channel = require_code(
        "source_channel_code", source["source_channel_code"], SOURCE_CHANNEL_CODES
    )
    if evidence_code not in SOURCE_CHANNEL_EVIDENCE_CODES[source_channel]:
        raise HouseMemorySelectionContractError(
            "channel_evidence_mismatch", "Source channel cannot originate this evidence tier."
        )
    return {
        "canonical_record_version_hash": require_hash(
            "canonical_record_version_hash", source["canonical_record_version_hash"]
        ),
        "evidence_code": evidence_code,
        "evidence_strength_milli": evidence_strength,
        "memory_ref_hash": require_hash("memory_ref_hash", source["memory_ref_hash"]),
        "selection_scope_code": require_code(
            "selection_scope_code", source["selection_scope_code"], SELECTION_SCOPES
        ),
        "source_channel_code": source_channel,
    }


def normalize_request(value: Any) -> dict[str, Any]:
    reject_forbidden_shape(value, path="selection_request")
    source = _require_exact_fields(value, REQUEST_FIELDS, "request")
    nominations = source["nominations"]
    if isinstance(nominations, (str, bytes, bytearray)) or not isinstance(nominations, Sequence):
        raise HouseMemorySelectionContractError("invalid_nominations", "nominations must be a bounded list.")
    if len(nominations) > MAX_INPUT_NOMINATIONS:
        raise HouseMemorySelectionContractError("too_many_nominations", "Selection nominations exceed the cap.")
    if source["schema_version"] != REQUEST_SCHEMA_VERSION:
        raise HouseMemorySelectionContractError("request_schema_mismatch", "Selection request schema is unsupported.")
    normalized_nominations = sorted(
        (normalize_nomination(item) for item in nominations),
        key=lambda item: (
            item["memory_ref_hash"], item["canonical_record_version_hash"],
            item["selection_scope_code"], item["source_channel_code"],
            item["evidence_code"], item["evidence_strength_milli"],
        ),
    )
    if len({item["memory_ref_hash"] for item in normalized_nominations}) > MAX_UNIQUE_REFS:
        raise HouseMemorySelectionContractError("too_many_unique_refs", "Selection unique refs exceed the cap.")
    audience_scopes = _normalize_code_list(
        "allowed_audience_scope_codes", source["allowed_audience_scope_codes"], ALLOWED_AUDIENCE_SCOPES
    )
    export_scopes = _normalize_code_list(
        "allowed_export_scope_codes", source["allowed_export_scope_codes"], ALLOWED_EXPORT_SCOPES
    )
    if len(export_scopes) != 1:
        raise HouseMemorySelectionContractError(
            "ambiguous_export_destination", "Selection requires exactly one export destination."
        )
    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "request_ref_hash": require_hash("request_ref_hash", source["request_ref_hash"]),
        "mode": require_code("mode", source["mode"], MODES),
        "requested_capability_code": require_code(
            "requested_capability_code", source["requested_capability_code"], REQUESTED_CAPABILITIES
        ),
        "allowed_audience_scope_codes": audience_scopes,
        "allowed_export_scope_codes": export_scopes,
        "max_selected": require_bounded_int("max_selected", source["max_selected"], minimum=0, maximum=MAX_SELECTED),
        "max_relation_fanout": require_bounded_int(
            "max_relation_fanout", source["max_relation_fanout"], minimum=0, maximum=MAX_RELATION_FANOUT_PER_NODE
        ),
        "nominations": normalized_nominations,
    }


def _normalize_code_list(name: str, value: Any, allowed: frozenset[str]) -> list[str]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise HouseMemorySelectionContractError(f"invalid_{name}", f"{name} must be a list.")
    normalized = [require_code(name, item, allowed) for item in value]
    if not normalized or len(normalized) != len(set(normalized)) or len(normalized) > 8:
        raise HouseMemorySelectionContractError(f"invalid_{name}", f"{name} must be unique and bounded.")
    return sorted(normalized)


def validate_projection(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema_version") != curated_projection.PROJECTION_SCHEMA_VERSION:
        raise HouseMemorySelectionContractError(
            "invalid_curated_projection", "Selection requires the Gate 2 curated projection."
        )
    reject_forbidden_shape(value, path="curated_projection")
    if set(value) != PROJECTION_FIELDS:
        raise HouseMemorySelectionContractError("invalid_curated_projection", "Projection fields are not exact.")
    if not isinstance(value.get("records"), Mapping) or not isinstance(value.get("relations"), Mapping):
        raise HouseMemorySelectionContractError("invalid_curated_projection", "Projection records and relations are required.")
    if not isinstance(value.get("proposals"), Mapping):
        raise HouseMemorySelectionContractError("invalid_curated_projection", "Projection proposals are required.")
    if not isinstance(value.get("resolutions"), Mapping):
        raise HouseMemorySelectionContractError("invalid_curated_projection", "Projection resolutions are required.")
    for count_field in ("event_count", "record_count", "relation_count", "proposal_count"):
        require_bounded_int(count_field, value[count_field], minimum=0, maximum=1_000_000)
    require_hash("event_chain_checksum", value["event_chain_checksum"])
    if not isinstance(value["replay_cursor"], str) or _CURSOR_RE.fullmatch(value["replay_cursor"]) is None:
        raise HouseMemorySelectionContractError("invalid_projection_cursor", "Projection cursor is invalid.")
    if value["event_count"] and durable._EVENT_ID_RE.fullmatch(str(value["last_event_id"])) is None:
        raise HouseMemorySelectionContractError("invalid_projection_event_ref", "Projection tail event ref is invalid.")
    collection_contracts = (
        ("records", "record_refs", "record_count"),
        ("relations", "relation_refs", "relation_count"),
        ("proposals", "proposal_refs", "proposal_count"),
        ("resolutions", "resolution_refs", "resolution_count"),
    )
    for collection_field, refs_field, count_field in collection_contracts:
        refs = value[refs_field]
        if not isinstance(refs, list) or refs != sorted(set(refs)):
            raise HouseMemorySelectionContractError("projection_ref_list_mismatch", "Projection refs are not canonical.")
        if refs != sorted(value[collection_field]) or value[count_field] != len(refs):
            raise HouseMemorySelectionContractError("projection_count_or_ref_mismatch", "Projection counts or refs differ.")
        for ref in refs:
            require_hash(refs_field, ref)
    for memory_ref, raw_record in value["records"].items():
        record = _require_exact_fields(raw_record, PROJECTION_RECORD_FIELDS, "projection_record")
        if memory_ref != record["memory_ref_hash"]:
            raise HouseMemorySelectionContractError("projection_record_ref_mismatch", "Projection record key differs.")
        require_hash("memory_ref_hash", memory_ref)
        require_hash("canonical_record_version_hash", record["canonical_record_version_hash"])
        _require_canonical_code_list("projection_blocker_flags", record["blocker_flags"], durable.ALLOWED_BLOCKER_FLAGS)
        _require_canonical_code_list(
            "projection_safe_capability_flags", record["safe_capability_flags"], durable.ALLOWED_CAPABILITY_FLAGS
        )
        bool_fields = (
            "provenance_present", "core_resolution_required", "base_standing_footing_eligible",
            "standing_footing_eligible", "default_surfacing_eligible", "explicit_search_eligible",
            "manual_lookup_eligible", "exact_recall_eligible",
        )
        if any(not isinstance(record[field], bool) for field in bool_fields):
            raise HouseMemorySelectionContractError("invalid_projection_record_type", "Projection record booleans are invalid.")
        require_bounded_int("record_event_count", record["event_count"], minimum=1, maximum=1_000_000)
        if record["participant_scope_code"] not in curated_events.PARTICIPANT_SCOPES:
            raise HouseMemorySelectionContractError("invalid_projection_scope", "Projection participant scope is invalid.")
        if record["authority_scope_code"] not in curated_events.AUTHORITY_SCOPES:
            raise HouseMemorySelectionContractError("invalid_projection_scope", "Projection authority scope is invalid.")
        if record["authority_owner_code"] not in curated_events.AUTHORITY_OWNERS:
            raise HouseMemorySelectionContractError("invalid_projection_scope", "Projection authority owner is invalid.")
        if record["audience_scope_code"] not in curated_events.AUDIENCE_SCOPES:
            raise HouseMemorySelectionContractError("invalid_projection_scope", "Projection audience scope is invalid.")
        if record["status_code"] != "approved" or record["review_state_code"] not in curated_events.REVIEW_STATES:
            raise HouseMemorySelectionContractError("invalid_projection_record_state", "Projection record state is invalid.")
        if record["core_status"] not in {"core", "normal_reviewed"}:
            raise HouseMemorySelectionContractError("invalid_projection_core_state", "Projection Core state is invalid.")
        if record["core_status"] == "normal_reviewed" and record["core_resolution_required"]:
            raise HouseMemorySelectionContractError(
                "invalid_projection_core_resolution", "Normal reviewed memory cannot require Core resolution."
            )
        accepted_authority = (
            record["authority_scope_code"] == "reviewed_memory"
            and record["review_state_code"] == "reviewed"
            and record["authority_owner_code"] in {"astel", "solen", "astel_solen"}
        ) or (
            record["authority_scope_code"] == "solen_active_memory"
            and record["review_state_code"] == "standing_consent_active"
            and record["authority_owner_code"] in {"solen", "house_standing_consent"}
        ) or (
            record["authority_scope_code"] == "candidate_only"
            and record["review_state_code"] == "reviewed"
            and record["authority_owner_code"] in {"astel", "solen", "astel_solen"}
        )
        if not accepted_authority:
            raise HouseMemorySelectionContractError(
                "invalid_projection_authority_combination", "Projection authority combination is invalid."
            )
        blockers = set(record["blocker_flags"])
        blocked = bool(blockers) or not record["provenance_present"]
        capabilities = set(record["safe_capability_flags"])
        if record["lifecycle_status"] not in {"active", "cooling", "quiet"}:
            raise HouseMemorySelectionContractError("invalid_projection_lifecycle_state", "Projection lifecycle state is invalid.")
        default_active = record["lifecycle_status"] == "active"
        base_standing = not blocked and default_active and "standing_footing_eligible" in capabilities
        expected_capabilities = {
            "base_standing_footing_eligible": base_standing,
            "default_surfacing_eligible": not blocked and default_active and "default_surfacing_eligible" in capabilities,
            "explicit_search_eligible": not blocked and "explicit_search_eligible" in capabilities,
            "manual_lookup_eligible": not blocked and "manual_lookup_eligible" in capabilities,
            "exact_recall_eligible": not blocked and "exact_recall_eligible" in capabilities,
            "standing_footing_eligible": base_standing or (
                not blocked
                and record["core_status"] == "core"
                and not record["core_resolution_required"]
            ),
        }
        if any(record[field] != expected for field, expected in expected_capabilities.items()):
            raise HouseMemorySelectionContractError(
                "projection_capability_derivation_mismatch",
                "Projection eligibility booleans do not match capabilities and blocker state.",
            )
        if durable._EVENT_ID_RE.fullmatch(str(record["last_event_id"])) is None:
            raise HouseMemorySelectionContractError("invalid_projection_event_ref", "Projection record event ref is invalid.")
        _require_safe_code("projection_last_reason_code", record["last_reason_code"])
    for relation_ref, raw_relation in value["relations"].items():
        relation_schema = raw_relation.get("payload_schema_version") if isinstance(raw_relation, Mapping) else None
        relation_fields = (PROJECTION_RELATION_V2_FIELDS if relation_schema == curated_events.RELATION_PAYLOAD_V2_SCHEMA_VERSION
                           else PROJECTION_RELATION_FIELDS)
        relation = _require_exact_fields(raw_relation, relation_fields, "projection_relation")
        if relation_ref != relation["relation_ref_hash"]:
            raise HouseMemorySelectionContractError("projection_relation_ref_mismatch", "Projection relation key differs.")
        for field in (
            "relation_ref_hash", "left_memory_ref_hash", "left_canonical_record_version_hash",
            "right_memory_ref_hash", "right_canonical_record_version_hash", "evidence_ref_hash",
        ):
            require_hash(field, relation[field])
        if relation["relation_type"] not in curated_events.RELATION_TYPES:
            raise HouseMemorySelectionContractError("invalid_projection_relation_type", "Relation type is unsupported.")
        require_bounded_int("relation_strength_milli", relation["strength_milli"], minimum=0, maximum=1000)
        if not isinstance(relation["eligible_for_expansion"], bool):
            raise HouseMemorySelectionContractError("invalid_projection_relation_type", "Relation eligibility is invalid.")
        if relation["state"] not in {"active", "retracted", "stale_endpoint_version"}:
            raise HouseMemorySelectionContractError("invalid_projection_relation_state", "Relation state is invalid.")
        if relation["payload_schema_version"] not in {curated_events.RELATION_PAYLOAD_SCHEMA_VERSION,
                                                       curated_events.RELATION_PAYLOAD_V2_SCHEMA_VERSION}:
            raise HouseMemorySelectionContractError("invalid_projection_relation_schema", "Relation schema is invalid.")
        if relation["participant_scope_code"] not in curated_events.PARTICIPANT_SCOPES or relation["authority_scope_code"] not in curated_events.AUTHORITY_SCOPES or relation["authority_owner_code"] not in curated_events.AUTHORITY_OWNERS or relation["audience_scope_code"] not in curated_events.AUDIENCE_SCOPES:
            raise HouseMemorySelectionContractError("invalid_projection_relation_scope", "Relation scope is invalid.")
        if durable._EVENT_ID_RE.fullmatch(str(relation["last_event_id"])) is None:
            raise HouseMemorySelectionContractError("invalid_projection_event_ref", "Relation event ref is invalid.")
        try:
            canonical_left, canonical_right = curated_events.canonical_relation_endpoints(
                relation["left_memory_ref_hash"], relation["right_memory_ref_hash"], relation["relation_type"]
            )
            if relation_schema == curated_events.RELATION_PAYLOAD_V2_SCHEMA_VERSION:
                expected_relation_ref = curated_events.compute_relation_ref_v2(
                    left_memory_ref_hash=relation["left_memory_ref_hash"], right_memory_ref_hash=relation["right_memory_ref_hash"],
                    relation_type=relation["relation_type"], participant_scope_code=relation["participant_scope_code"],
                    audience_scope_code=relation["audience_scope_code"],
                    left_authority_scope_code=relation["left_authority_scope_code"],
                    left_authority_owner_code=relation["left_authority_owner_code"],
                    right_authority_scope_code=relation["right_authority_scope_code"],
                    right_authority_owner_code=relation["right_authority_owner_code"])
            else:
                expected_relation_ref = curated_events.compute_relation_ref(
                    left_memory_ref_hash=relation["left_memory_ref_hash"],
                    right_memory_ref_hash=relation["right_memory_ref_hash"], relation_type=relation["relation_type"],
                    participant_scope_code=relation["participant_scope_code"], authority_scope_code=relation["authority_scope_code"],
                    authority_owner_code=relation["authority_owner_code"], audience_scope_code=relation["audience_scope_code"])
        except durable.HouseMemoryDurableEventError as exc:
            raise HouseMemorySelectionContractError(
                "invalid_projection_relation_identity", "Projection relation identity is invalid."
            ) from exc
        if (
            relation["left_memory_ref_hash"] != canonical_left
            or relation["right_memory_ref_hash"] != canonical_right
            or relation["relation_ref_hash"] != expected_relation_ref
        ):
            raise HouseMemorySelectionContractError(
                "projection_relation_identity_mismatch", "Projection relation identity is noncanonical."
            )
        left_record = value["records"].get(canonical_left)
        right_record = value["records"].get(canonical_right)
        if not isinstance(left_record, Mapping) or not isinstance(right_record, Mapping):
            raise HouseMemorySelectionContractError(
                "projection_relation_endpoint_missing", "Projection relation endpoint is missing."
            )
        left_current = relation["left_canonical_record_version_hash"] == left_record["canonical_record_version_hash"]
        right_current = relation["right_canonical_record_version_hash"] == right_record["canonical_record_version_hash"]
        relation_scope = (relation["participant_scope_code"], relation["authority_scope_code"],
                          relation["authority_owner_code"], relation["audience_scope_code"])
        left_scope = (
            left_record["participant_scope_code"], left_record["authority_scope_code"],
            left_record["authority_owner_code"], left_record["audience_scope_code"],
        )
        right_scope = (
            right_record["participant_scope_code"], right_record["authority_scope_code"],
            right_record["authority_owner_code"], right_record["audience_scope_code"],
        )
        if relation_schema == curated_events.RELATION_PAYLOAD_V2_SCHEMA_VERSION:
            left_expected = (relation["participant_scope_code"], relation["left_authority_scope_code"],
                             relation["left_authority_owner_code"], relation["audience_scope_code"])
            right_expected = (relation["participant_scope_code"], relation["right_authority_scope_code"],
                              relation["right_authority_owner_code"], relation["audience_scope_code"])
            left_scope_current = not left_current or left_expected == left_scope
            right_scope_current = not right_current or right_expected == right_scope
            current_and_scoped = left_current and right_current and left_expected == left_scope and right_expected == right_scope
        else:
            left_scope_current = not left_current or relation_scope == left_scope
            right_scope_current = not right_current or relation_scope == right_scope
            current_and_scoped = left_current and right_current and relation_scope == left_scope == right_scope
        if not left_scope_current or not right_scope_current:
            raise HouseMemorySelectionContractError(
                "projection_relation_scope_mismatch", "Current relation endpoint scope differs."
            )
        expected_expansion = bool(
            relation["state"] == "active"
            and current_and_scoped
            and not left_record["blocker_flags"]
            and not right_record["blocker_flags"]
        )
        if relation["state"] == "active" and not current_and_scoped:
            raise HouseMemorySelectionContractError(
                "projection_active_relation_stale", "Active relation endpoints must be current and scoped."
            )
        if relation["eligible_for_expansion"] != expected_expansion:
            raise HouseMemorySelectionContractError(
                "projection_relation_eligibility_mismatch", "Relation expansion eligibility is inconsistent."
            )
    for proposal_ref, raw_proposal in value["proposals"].items():
        proposal = _require_exact_fields(raw_proposal, PROJECTION_PROPOSAL_FIELDS, "projection_proposal")
        if proposal_ref != proposal["proposal_ref_hash"]:
            raise HouseMemorySelectionContractError("projection_proposal_ref_mismatch", "Projection proposal key differs.")
        for field in (
            "proposal_ref_hash", "primary_memory_ref_hash", "primary_canonical_record_version_hash",
            "comparison_memory_ref_hash", "comparison_canonical_record_version_hash", "candidate_ref_hash",
            "proposal_origin_action_ref_hash",
        ):
            require_hash(field, proposal[field])
        if proposal["proposal_kind"] not in curated_events.PROPOSAL_KINDS:
            raise HouseMemorySelectionContractError("invalid_projection_proposal_kind", "Proposal kind is invalid.")
        if proposal["proposal_basis"] not in curated_events.PROPOSAL_BASES:
            raise HouseMemorySelectionContractError("invalid_projection_proposal_basis", "Proposal basis is invalid.")
        if proposal["state"] not in {"proposed", "check_needed", "withdrawn", "stale"}:
            raise HouseMemorySelectionContractError("invalid_projection_proposal_state", "Proposal state is invalid.")
        proposal_bool_fields = (
            "core_involved", "core_resolution_required", "canonical_record_changed",
            "automatic_supersession_made", "memory_vault_record_mutation_made",
            "writeback_candidate_mutation_made",
        )
        if any(not isinstance(proposal[field], bool) for field in proposal_bool_fields):
            raise HouseMemorySelectionContractError("invalid_projection_proposal_type", "Proposal booleans are invalid.")
        _require_canonical_code_list(
            "projection_proposal_blocker_flags", proposal["proposal_blocker_flags"], durable.ALLOWED_BLOCKER_FLAGS
        )
        if proposal["payload_schema_version"] != curated_events.PROPOSAL_PAYLOAD_SCHEMA_VERSION:
            raise HouseMemorySelectionContractError("invalid_projection_proposal_schema", "Proposal schema is invalid.")
        if proposal["participant_scope_code"] not in curated_events.PARTICIPANT_SCOPES or proposal["authority_scope_code"] not in curated_events.AUTHORITY_SCOPES or proposal["authority_owner_code"] not in curated_events.AUTHORITY_OWNERS or proposal["audience_scope_code"] not in curated_events.AUDIENCE_SCOPES:
            raise HouseMemorySelectionContractError("invalid_projection_proposal_scope", "Proposal scope is invalid.")
        if durable._EVENT_ID_RE.fullmatch(str(proposal["last_event_id"])) is None:
            raise HouseMemorySelectionContractError("invalid_projection_event_ref", "Proposal event ref is invalid.")
        if proposal["primary_memory_ref_hash"] == proposal["comparison_memory_ref_hash"] or proposal["candidate_ref_hash"] in {
            proposal["primary_memory_ref_hash"], proposal["comparison_memory_ref_hash"]
        }:
            raise HouseMemorySelectionContractError(
                "projection_proposal_endpoint_collision", "Proposal endpoints and candidate must differ."
            )
        expected_proposal_ref = curated_events.compute_proposal_ref(
            action_ref_hash=proposal["proposal_origin_action_ref_hash"],
            proposal_kind=proposal["proposal_kind"],
            primary_memory_ref_hash=proposal["primary_memory_ref_hash"],
            primary_canonical_record_version_hash=proposal["primary_canonical_record_version_hash"],
            comparison_memory_ref_hash=proposal["comparison_memory_ref_hash"],
            comparison_canonical_record_version_hash=proposal["comparison_canonical_record_version_hash"],
            candidate_ref_hash=proposal["candidate_ref_hash"],
        )
        if proposal["proposal_ref_hash"] != expected_proposal_ref:
            raise HouseMemorySelectionContractError(
                "projection_proposal_identity_mismatch", "Projection proposal ref is inconsistent."
            )
        if any(proposal[field] for field in (
            "canonical_record_changed", "automatic_supersession_made",
            "memory_vault_record_mutation_made", "writeback_candidate_mutation_made",
        )):
            raise HouseMemorySelectionContractError(
                "projection_proposal_mutation_forbidden", "Projection proposal mutation flags must remain false."
            )
        primary_record = value["records"].get(proposal["primary_memory_ref_hash"])
        comparison_record = value["records"].get(proposal["comparison_memory_ref_hash"])
        if not isinstance(primary_record, Mapping) or not isinstance(comparison_record, Mapping):
            raise HouseMemorySelectionContractError(
                "projection_proposal_endpoint_missing", "Projection proposal endpoint is missing."
            )
        proposal_scope = (
            proposal["participant_scope_code"], proposal["authority_scope_code"],
            proposal["authority_owner_code"], proposal["audience_scope_code"],
        )
        primary_current = proposal["primary_canonical_record_version_hash"] == primary_record["canonical_record_version_hash"]
        comparison_current = proposal["comparison_canonical_record_version_hash"] == comparison_record["canonical_record_version_hash"]
        primary_scope = (
            primary_record["participant_scope_code"], primary_record["authority_scope_code"],
            primary_record["authority_owner_code"], primary_record["audience_scope_code"],
        )
        comparison_scope = (
            comparison_record["participant_scope_code"], comparison_record["authority_scope_code"],
            comparison_record["authority_owner_code"], comparison_record["audience_scope_code"],
        )
        if (primary_current and proposal_scope != primary_scope) or (comparison_current and proposal_scope != comparison_scope):
            raise HouseMemorySelectionContractError(
                "projection_proposal_scope_mismatch", "Current proposal endpoint scope differs."
            )
        if proposal["state"] in {"proposed", "check_needed"} and not (
            primary_current and comparison_current and proposal_scope == primary_scope == comparison_scope
        ):
            raise HouseMemorySelectionContractError(
                "projection_active_proposal_stale", "Active proposal endpoints must be current and scoped."
            )
    for resolution_ref, raw_resolution in value["resolutions"].items():
        resolution = _require_exact_fields(raw_resolution, PROJECTION_RESOLUTION_FIELDS, "projection_resolution")
        if resolution_ref != resolution["resolution_ref_hash"]:
            raise HouseMemorySelectionContractError("projection_resolution_ref_mismatch", "Projection resolution key differs.")
        for field in (
            "resolution_ref_hash", "candidate_id", "candidate_version_hash", "primary_memory_ref_hash",
            "primary_applied_version_hash", "comparison_memory_ref_hash", "comparison_applied_version_hash",
            "approved_by_actor_ref_hash", "approval_evidence_ref_hash", "source_evidence_ref_hash",
            "provenance_evidence_ref_hash",
        ):
            require_hash(field, resolution[field])
        if resolution["payload_schema_version"] != curated_events.EVOLUTION_APPLIED_PAYLOAD_SCHEMA_VERSION:
            raise HouseMemorySelectionContractError("invalid_projection_resolution_schema", "Resolution schema is invalid.")
        if resolution["evolution_kind"] not in curated_events.EVOLUTION_KINDS or resolution["resolution_code"] not in curated_events.EVOLUTION_RESOLUTION_CODES or resolution["disposition_code"] not in curated_events.EVOLUTION_DISPOSITION_CODES:
            raise HouseMemorySelectionContractError("invalid_projection_resolution_code", "Resolution code is invalid.")
        if resolution["resolution_code"] != curated_events.EVOLUTION_KIND_RESOLUTION_CODES[resolution["evolution_kind"]]:
            raise HouseMemorySelectionContractError(
                "projection_resolution_kind_mismatch", "Resolution kind and accepted action differ."
            )
        if resolution["approved_by_actor_type"] not in {"astel", "solen"}:
            raise HouseMemorySelectionContractError("invalid_projection_resolution_actor", "Resolution actor is invalid.")
        expected_authority = (("reviewed_memory", "astel") if resolution["approved_by_actor_type"] == "astel"
                              else ("solen_active_memory", resolution["approval_authority_owner_code"]))
        if ((resolution["approval_authority_scope_code"], resolution["approval_authority_owner_code"]) != expected_authority
                or (resolution["approved_by_actor_type"] == "solen"
                    and resolution["approval_authority_owner_code"] not in {"solen", "house_standing_consent"})):
            raise HouseMemorySelectionContractError("invalid_projection_resolution_authority", "Resolution authority is invalid.")
        if resolution["participant_scope_code"] not in curated_events.PARTICIPANT_SCOPES or resolution["audience_scope_code"] not in curated_events.AUDIENCE_SCOPES:
            raise HouseMemorySelectionContractError("invalid_projection_resolution_scope", "Resolution scope is invalid.")
        _require_canonical_code_list("projection_resolution_blocker_flags", resolution["resolution_blocker_flags"], durable.ALLOWED_BLOCKER_FLAGS)
        for field in ("core_involved", "core_check_needed", "canonical_record_changed", "core_moved_or_removed", "selection_expansion_authorized"):
            if not isinstance(resolution[field], bool):
                raise HouseMemorySelectionContractError("invalid_projection_resolution_boolean", "Resolution flags must be boolean.")
        if resolution["canonical_record_changed"] or resolution["core_moved_or_removed"] or resolution["selection_expansion_authorized"]:
            raise HouseMemorySelectionContractError("projection_resolution_authority_widening", "Resolution projection cannot claim mutation or selection authority.")
        expected_ref = curated_events.compute_evolution_resolution_ref(**{key: resolution[key] for key in (
            "candidate_id", "candidate_version_hash", "evolution_kind", "primary_memory_ref_hash",
            "primary_applied_version_hash", "comparison_memory_ref_hash", "comparison_applied_version_hash",
            "resolution_code", "disposition_code")})
        if expected_ref != resolution_ref:
            raise HouseMemorySelectionContractError("projection_resolution_identity_mismatch", "Resolution identity is inconsistent.")
        primary = value["records"].get(resolution["primary_memory_ref_hash"])
        comparison = value["records"].get(resolution["comparison_memory_ref_hash"])
        if not isinstance(primary, Mapping) or not isinstance(comparison, Mapping):
            raise HouseMemorySelectionContractError("projection_resolution_endpoint_missing", "Resolution endpoint is missing.")
        for endpoint in (primary, comparison):
            if (endpoint["participant_scope_code"] != resolution["participant_scope_code"]
                    or endpoint["audience_scope_code"] != resolution["audience_scope_code"]):
                raise HouseMemorySelectionContractError(
                    "projection_resolution_endpoint_scope_mismatch", "Resolution scope differs from an endpoint."
                )
        endpoint_core_involved = primary["core_status"] == "core" or comparison["core_status"] == "core"
        endpoint_core_check_needed = bool(
            endpoint_core_involved or primary["core_resolution_required"] or comparison["core_resolution_required"]
        )
        if (resolution["core_involved"] != endpoint_core_involved
                or resolution["core_check_needed"] != endpoint_core_check_needed):
            raise HouseMemorySelectionContractError(
                "projection_resolution_core_mismatch", "Resolution Core flags differ from its endpoints."
            )
        endpoint_blockers = set(primary["blocker_flags"]) | set(comparison["blocker_flags"])
        if not endpoint_blockers.issubset(resolution["resolution_blocker_flags"]):
            raise HouseMemorySelectionContractError(
                "projection_resolution_blockers_missing", "Resolution omits an endpoint blocker."
            )
        current = (primary["canonical_record_version_hash"] == resolution["primary_applied_version_hash"]
                   and comparison["canonical_record_version_hash"] == resolution["comparison_applied_version_hash"])
        expected_state = "stale_endpoint_version" if not current else (
            "check_needed" if (resolution["core_check_needed"] or resolution["resolution_blocker_flags"]
                               or resolution["disposition_code"] == "check_needed") else "active")
        if resolution["state"] != expected_state:
            raise HouseMemorySelectionContractError("projection_resolution_state_mismatch", "Resolution state is inconsistent.")
    return value


def canonical_checksum(value: Any) -> str:
    return durable.canonical_sha256(value)


__all__ = [
    "DIRECT_EVIDENCE_RANK",
    "DIRECT_EVIDENCE_TIERS",
    "HouseMemorySelectionContractError",
    "MODES",
    "REQUESTED_CAPABILITIES",
    "NOMINATION_FIELDS",
    "PROJECTION_FIELDS",
    "PROJECTION_RECORD_FIELDS",
    "PROJECTION_RELATION_FIELDS",
    "PROJECTION_PROPOSAL_FIELDS",
    "PROJECTION_RESOLUTION_FIELDS",
    "RELATION_EXPANSION_TYPES",
    "REQUEST_FIELDS",
    "REQUEST_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
    "SELECTION_SCOPES",
    "SOURCE_CHANNEL_CODES",
    "SOURCE_CHANNEL_EVIDENCE_CODES",
    "TRACE_SCHEMA_VERSION",
    "ALLOWED_AUDIENCE_SCOPES",
    "ALLOWED_EXPORT_SCOPES",
    "MAX_DIRECT_SEEDS",
    "MAX_INPUT_NOMINATIONS",
    "MAX_MERGED_EVIDENCE_CODES",
    "MAX_MERGED_SOURCE_CODES",
    "MAX_RELATION_FANOUT_PER_NODE",
    "MAX_SELECTED",
    "MAX_UNIQUE_REFS",
    "canonical_checksum",
    "normalize_nomination",
    "normalize_request",
    "reject_forbidden_shape",
    "validate_projection",
]
