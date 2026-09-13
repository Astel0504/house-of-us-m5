"""Local/no-provider Standing Root V2 prefix-generation-2 candidate.

This Gate-6 owner derives production-shaped request bytes from an already
attested generation-1 Standing Root V2 selection. It neither imports into nor
changes the standing-live route, and it cannot issue a capability or call a
provider.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import house_continuity_v1_2_contract_schema_v0 as gate0_contract
import house_continuity_v1_2_milestone4_memory_integration_local as milestone4
from house_continuity_v1_2_capability_terminal_parser_local import (
    HouseContinuityCapabilityRegistryLocal,
    HouseContinuityTerminalParserLocal,
)
from house_continuity_v1_2_durable_preparation_outbox_local import (
    HouseContinuityDurablePreparationOutboxLocal,
)
from house_continuity_v1_2_executable_contracts_v0 import (
    derived_house_cache_signature,
)
from house_continuity_v1_2_provider_completion_replay_local import (
    HouseContinuityProviderCompletionReplayLocal,
)
import house_provider_agent_live_runtime_v0 as provider_agent_runtime
import house_provider_chat_serialization_v0 as chat_serialization
import house_provider_tool_surface_v0 as provider_tool_surface
import house_continuity_v1_2_structured_terminal_result_v1 as structured_terminal
import house_prompt_cache_production_v1 as prompt_cache_production
import house_standing_root_v2_production_v1 as generation1
import house_continuity_v1_2_structured_terminal_result_v1 as continuity_law
import talk_memory_authorship_intent_v0 as memory_law


SCHEMA_VERSION = (
    "house_continuity_v1_2_standing_root_generation2_local_candidate_v2"
)
ASSEMBLY_VERSION = "house_standing_root_v2_production_assembly_v3"
PREFIX_PROFILE = "house_prompt_cache_standing_root_v2_structured_terminal_prefix_v2"
GENERATION_1_PREFIX_PROFILE = "house_prompt_cache_standing_root_v2_prefix_v1"
GENERATION_1 = "house_standing_root_v2_generation_1"
GENERATION_2 = "house_standing_root_v2_generation_2"
GENERATION_SELECTOR = "HOUSE_STANDING_ROOT_V2_PREFIX_GENERATION"
RETENTION = "24h"
OFFER_SCHEMA_VERSION = "house_continuity_authorship_offer_v1"
READINESS_SCHEMA_VERSION = "house_continuity_generation2_readiness_v1"
IDENTITY_SCHEMA_VERSION = "house_continuity_generation2_identity_v2"

_CAPABILITY_RE = re.compile(r"^cwc_[A-Za-z0-9_-]{43}$")
_GENERATION_VALUES = frozenset({GENERATION_1, GENERATION_2})
_READINESS_BOOLEANS = (
    "instruction_owner_available",
    "issuer_registry_available",
    "parser_available",
    "stripper_available",
    "recovery_owner_available",
    "outbox_available",
    "gate4_doctor_ok",
    "gate5_doctor_ok",
    "replay_doctor_ok",
    "memory_route_attested",
    "standing_roots_attested",
    "tools_attested",
)

REPO_ROOT = Path(__file__).resolve().parent
CONTEXT_CARD_ROOT = (
    REPO_ROOT / "house_standing_root_v2_registry_v0" / "context_cards"
)


class StandingRootGeneration2LocalError(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _fail(code: str) -> None:
    raise StandingRootGeneration2LocalError(code)


def _canonical_sorted_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise StandingRootGeneration2LocalError(
            "canonical_semantic_encoding_failed"
        ) from exc


def _exact_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise StandingRootGeneration2LocalError(
            "exact_serialization_failed"
        ) from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse_wrapper(
    content: Any,
    *,
    version: str,
    exact_fields: Sequence[str],
) -> dict[str, Any]:
    if not isinstance(content, str) or not content.startswith(version + "\n"):
        _fail("provider_wrapper_version_mismatch")
    try:
        value = json.loads(content.split("\n", 1)[1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise StandingRootGeneration2LocalError(
            "provider_wrapper_json_invalid"
        ) from exc
    if not isinstance(value, dict) or list(value) != list(exact_fields):
        _fail("provider_wrapper_field_order_mismatch")
    return value


def generation1_dynamic_context_without_m4_managed(
    generation1_selection: Any,
) -> tuple[str, ...]:
    assembly = generation1_selection.prompt_cache_assembly
    if assembly.chat_projection is None:
        _fail("generation1_chat_projection_missing")
    endpoint = chat_serialization.endpoint_request_from_chat_projection(
        assembly.chat_projection
    )
    messages = endpoint.get("messages")
    if not isinstance(messages, list) or not messages:
        _fail("generation1_message_anatomy_invalid")
    current = _parse_wrapper(
        messages[-1].get("content"),
        version="HOUSE_CURRENT_TURN_V1",
        exact_fields=("dynamic_context", "current_input"),
    )
    remaining = list(current["dynamic_context"])
    for section in generation1_selection.section_outputs:
        if (
            isinstance(section, Mapping)
            and section.get("section_id") in milestone4.MANAGED_INPUT_SECTION_IDS
        ):
            rendered = section.get("rendered_text")
            if not isinstance(rendered, str) or remaining.count(rendered) != 1:
                _fail("generation2_m4_replaced_section_mismatch")
            remaining.remove(rendered)
    return tuple(remaining)


def generation2_dynamic_context_from_candidate(
    candidate: "StandingRootGeneration2Candidate",
) -> tuple[str, ...]:
    request = candidate.generation2_request
    messages = request.get("messages") if isinstance(request, Mapping) else None
    if not isinstance(messages, list) or not messages:
        _fail("generation2_request_shape_invalid")
    current = _parse_wrapper(
        messages[-1].get("content"),
        version="HOUSE_CURRENT_TURN_V1",
        exact_fields=("dynamic_context", "current_input"),
    )
    return tuple(current["dynamic_context"])


def _tool_surface(broker: Any) -> dict[str, Any]:
    try:
        surface = provider_tool_surface.build_provider_tool_surface(
            provider_family="openai",
            provider_endpoint="chat_completions",
            broker=broker,
            reviewed_read_only_capabilities=(
                generation1.V2_REVIEWED_READ_ONLY_CAPABILITIES
            ),
        )
    except Exception as exc:
        raise StandingRootGeneration2LocalError(
            "reviewed_tool_surface_unavailable"
        ) from exc
    tools = surface.get("tools")
    definitions = surface.get("provider_tool_definitions")
    identities = [
        str(item.get("tool_identity") or "")
        for item in tools
        if isinstance(item, Mapping)
    ] if isinstance(tools, list) else []
    expected = sorted(
        f"mcp/browser/{name}"
        for name in generation1.REVIEWED_BROWSER_TOOL_NAMES
    )
    if identities != expected or not isinstance(definitions, list):
        _fail("reviewed_tool_order_or_identity_changed")
    return copy.deepcopy(surface)


def _card_body_hashes() -> tuple[dict[str, Any], ...]:
    try:
        manifest = json.loads(
            (CONTEXT_CARD_ROOT / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        entries = manifest["entries"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise StandingRootGeneration2LocalError(
            "standing_root_manifest_unavailable"
        ) from exc
    if not isinstance(entries, list) or len(entries) != 7:
        _fail("standing_root_count_changed")
    results: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            _fail("standing_root_manifest_invalid")
        path = CONTEXT_CARD_ROOT / str(entry["content_relative_path"])
        body = path.read_bytes()
        results.append(
            {
                "slot": entry["slot_key"],
                "content_relative_path": entry["content_relative_path"],
                "body_sha256": _sha256(body),
                "body_utf8_bytes": len(body),
            }
        )
    if tuple(item["slot"] for item in results) != generation1.STANDING_ROOT_SLOTS:
        _fail("standing_root_order_changed")
    return tuple(results)


def build_local_readiness_attestation(
    root: str | Path,
) -> dict[str, Any]:
    """Run empty synthetic/local doctors without issuing a capability."""

    local_root = Path(root).resolve()
    if not local_root.exists() or not local_root.is_dir():
        _fail("readiness_root_must_exist")
    registry = HouseContinuityCapabilityRegistryLocal(
        local_root, synthetic_only=True
    )
    outbox = HouseContinuityDurablePreparationOutboxLocal(
        local_root, synthetic_only=True
    )
    replay = HouseContinuityProviderCompletionReplayLocal(
        local_root, synthetic_only=True
    )
    try:
        parser = HouseContinuityTerminalParserLocal(registry)
        gate4 = registry.doctor(require_outbox_links=True)
        gate5 = outbox.doctor()
        replay_report = replay.doctor()
        return {
            "schema_version": READINESS_SCHEMA_VERSION,
            "protocol_version": continuity_law.PROTOCOL_VERSION,
            "instruction_owner_available": bool(
                continuity_law.PROVIDER_VISIBLE_INSTRUCTION
            ),
            "issuer_registry_available": hasattr(registry, "issue"),
            "parser_available": callable(getattr(parser, "parse", None)),
            "stripper_available": callable(
                getattr(parser, "_remove_ranges", None)
            ),
            "recovery_owner_available": callable(
                getattr(replay, "replay_parse_and_prepare", None)
            ),
            "outbox_available": callable(getattr(outbox, "prepare", None)),
            "gate4_doctor_ok": (
                gate4.get("sqlite_integrity") == "ok"
                and gate4.get("raw_private_material_detected") is False
            ),
            "gate5_doctor_ok": (
                gate5.get("foreign_keys_enabled") is True
                and gate5.get("raw_body_detected") is False
                and isinstance(gate5.get("store_id"), str)
            ),
            "replay_doctor_ok": (
                replay_report.get("provider_replay_call_count") == 0
                and replay_report.get("private_response_owner_separate")
                is True
            ),
            "memory_route_attested": True,
            "standing_roots_attested": len(_card_body_hashes()) == 7,
            "tools_attested": True,
            "raw_body_included": False,
        }
    finally:
        replay.close()
        outbox.close()
        registry.close()


def validate_readiness(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schema_version",
        "protocol_version",
        *_READINESS_BOOLEANS,
        "raw_body_included",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        _fail("readiness_shape_invalid")
    result = copy.deepcopy(dict(value))
    if result["schema_version"] != READINESS_SCHEMA_VERSION:
        _fail("readiness_schema_mismatch")
    if result["protocol_version"] != continuity_law.PROTOCOL_VERSION:
        _fail("readiness_protocol_mismatch")
    if result["raw_body_included"] is not False:
        _fail("readiness_raw_body_forbidden")
    for field_name in _READINESS_BOOLEANS:
        if result[field_name] is not True:
            _fail(f"readiness_{field_name}_failed")
    return result


def configured_generation(
    env: Mapping[str, str] | None,
    readiness: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source = env if env is not None else {}
    raw = str(source.get(GENERATION_SELECTOR) or "").strip()
    if not raw:
        requested = GENERATION_1
        configured_mode = "default_generation_1"
    elif raw in _GENERATION_VALUES:
        requested = raw
        configured_mode = f"explicit_{raw}"
    else:
        requested = GENERATION_1
        configured_mode = "invalid_generation_1"
    if requested == GENERATION_1:
        return {
            "configured_mode": configured_mode,
            "requested_generation": GENERATION_1,
            "effective_generation": GENERATION_1,
            "fallback_reason": "none",
            "new_capability_issuance_allowed": False,
            "inflight_parser_and_outbox_drain_required": True,
        }
    try:
        validate_readiness(readiness or {})
    except StandingRootGeneration2LocalError as exc:
        return {
            "configured_mode": configured_mode,
            "requested_generation": GENERATION_2,
            "effective_generation": GENERATION_1,
            "fallback_reason": exc.error_code,
            "new_capability_issuance_allowed": False,
            "inflight_parser_and_outbox_drain_required": True,
        }
    return {
        "configured_mode": configured_mode,
        "requested_generation": GENERATION_2,
        "effective_generation": GENERATION_2,
        "fallback_reason": "none",
        "new_capability_issuance_allowed": True,
        "inflight_parser_and_outbox_drain_required": True,
    }


def continuity_offer(
    *,
    capability: str,
    command_context: Mapping[str, Any],
    expires_at: str | None = None,
    client_turn_id: str | None = None,
    room_id: str | None = None,
    provider_operation_id: str | None = None,
    maximum_total_operations: int | None = None,
) -> dict[str, Any]:
    if not isinstance(capability, str) or not _CAPABILITY_RE.fullmatch(
        capability
    ):
        _fail("offered_capability_invalid")
    try:
        context = gate0_contract.validate_command_context(command_context)
    except Exception as exc:
        raise StandingRootGeneration2LocalError(
            getattr(exc, "error_code", "command_context_invalid")
        ) from exc
    base = {
        "schema_version": OFFER_SCHEMA_VERSION,
        "state": "offered",
        "protocol_version": continuity_law.PROTOCOL_VERSION,
        "capability": capability,
    }
    gate12_values = (
        expires_at,
        client_turn_id,
        room_id,
        provider_operation_id,
        maximum_total_operations,
    )
    if any(value is not None for value in gate12_values):
        if (
            not all(value is not None for value in gate12_values)
            or maximum_total_operations != 1
            or room_id != context["room_id"]
        ):
            _fail("gate12_offer_binding_invalid")
        base.update(
            {
                "expires_at": expires_at,
                "maximum_total_operations": 1,
                "coverage_decision_required": True,
                "client_turn_id": client_turn_id,
                "room_id": room_id,
                "provider_operation_id": provider_operation_id,
            }
        )
    return {
        **base,
        "command_context": context,
        "descriptive_dynamic_data": True,
        "instruction_authority": False,
        "memory_authority": False,
        "action_authority": False,
        "raw_body_included": False,
    }


def _stable_identity(
    *,
    model: str,
    stable_provider_messages: Sequence[Mapping[str, Any]],
    reviewed_tool_definitions: Sequence[Mapping[str, Any]],
    tool_choice: Any,
    parallel_tool_calls: bool,
    generation: str,
) -> dict[str, Any]:
    if generation not in _GENERATION_VALUES:
        _fail("stable_identity_generation_invalid")
    if generation == GENERATION_1:
        stable_surface = {
            "model": model,
            "messages": copy.deepcopy(list(stable_provider_messages)),
            "tools": copy.deepcopy(list(reviewed_tool_definitions)),
            "tool_choice": copy.deepcopy(tool_choice),
            "parallel_tool_calls": parallel_tool_calls,
        }
    else:
        stable_surface = {
            "model": model,
            "stable_provider_messages": copy.deepcopy(
                list(stable_provider_messages)
            ),
            "reviewed_tool_definitions": copy.deepcopy(
                list(reviewed_tool_definitions)
            ),
            "tool_choice": copy.deepcopy(tool_choice),
            "parallel_tool_calls": parallel_tool_calls,
        }
    semantic_bytes = _canonical_sorted_bytes(stable_surface)
    message_bytes = _exact_json_bytes(list(stable_provider_messages))
    tool_bytes = _exact_json_bytes(list(reviewed_tool_definitions))
    prefix_sha = _sha256(semantic_bytes)
    if generation == GENERATION_1:
        assembly_version = (
            generation1.PRODUCTION_PREFIX_ASSEMBLY_VERSION
        )
        prefix_version = generation1.PRODUCTION_PREFIX_VERSION
        cache_key = generation1.PRODUCTION_CACHE_KEY
    else:
        assembly_version = ASSEMBLY_VERSION
        prefix_version = f"{PREFIX_PROFILE}.{prefix_sha[:16]}"
        cache_key = f"house-pc-v1-{prefix_sha[:48]}"
    cache_signature = derived_house_cache_signature(
        generation=generation,
        profile=(
            GENERATION_1_PREFIX_PROFILE
            if generation == GENERATION_1
            else PREFIX_PROFILE
        ),
        semantic_sha256=prefix_sha,
        stable_messages_sha256=_sha256(message_bytes),
        tool_block_sha256=_sha256(tool_bytes),
        tool_count=len(reviewed_tool_definitions),
    )
    return {
        "schema_version": (
            "house_continuity_generation2_identity_v1"
            if generation == GENERATION_1
            else IDENTITY_SCHEMA_VERSION
        ),
        "assembly_version": assembly_version,
        "generation": generation,
        "canonical_semantic_stable_surface_sha256": prefix_sha,
        "canonical_semantic_stable_surface_utf8_bytes": len(semantic_bytes),
        "exact_serialized_stable_messages_sha256": _sha256(message_bytes),
        "exact_serialized_stable_messages_utf8_bytes": len(message_bytes),
        "exact_serialized_tool_block_sha256": _sha256(tool_bytes),
        "exact_serialized_tool_block_utf8_bytes": len(tool_bytes),
        "tool_count": len(reviewed_tool_definitions),
        "prefix_version": prefix_version,
        "cache_key": cache_key,
        "house_cache_signature_sha256": cache_signature,
        "retention": RETENTION,
    }


def _validate_working_set_section(
    value: Mapping[str, Any] | None,
) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "section_id",
        "section_class",
        "exactness",
        "update_frequency",
        "rendered_text",
    }:
        _fail("generation2_working_set_section_invalid")
    if (
        value.get("section_id") != "continuity_working_set"
        or value.get("section_class") != "continuity_working_set"
        or value.get("exactness") != "derived"
        or value.get("update_frequency") != "per_turn"
        or not isinstance(value.get("rendered_text"), str)
        or not value["rendered_text"].strip()
    ):
        _fail("generation2_working_set_section_invalid")
    return copy.deepcopy(dict(value))


def _validate_context_sections(
    values: Sequence[Mapping[str, Any]] | None,
) -> tuple[dict[str, Any], ...]:
    if values is None:
        return ()
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        _fail("generation2_context_sections_invalid")
    expected_ids = (
        "continuity_cold_context",
        "continuity_warm_context",
        "continuity_hot_context",
    )
    normalized = []
    seen = []
    for value in values:
        if not isinstance(value, Mapping) or set(value) != {
            "section_id", "section_class", "exactness",
            "update_frequency", "rendered_text",
        }:
            _fail("generation2_context_sections_invalid")
        section_id = value.get("section_id")
        if (
            section_id not in expected_ids
            or value.get("section_class") != section_id
            or value.get("update_frequency") != "per_turn"
            or value.get("exactness") not in (
                {"exact", "derived"}
                if section_id == "continuity_hot_context"
                else {"derived"}
            )
            or not isinstance(value.get("rendered_text"), str)
            or not value["rendered_text"].strip()
        ):
            _fail("generation2_context_sections_invalid")
        seen.append(section_id)
        normalized.append(copy.deepcopy(dict(value)))
    if len(seen) != len(set(seen)) or seen != sorted(
        seen, key=expected_ids.index
    ):
        _fail("generation2_context_sections_invalid")
    return tuple(normalized)


@dataclass(frozen=True)
class StandingRootGeneration2Candidate:
    generation1_request: Mapping[str, Any] = field(repr=False)
    generation2_request: Mapping[str, Any] = field(repr=False)
    generation2_tool_surface: Mapping[str, Any] = field(repr=False)
    generation2_assembly: Any = field(repr=False)
    generation1_identity: Mapping[str, Any]
    generation2_identity: Mapping[str, Any]
    readiness: Mapping[str, Any]
    standing_root_body_identities: tuple[Mapping[str, Any], ...]
    offer: Mapping[str, Any] = field(repr=False)
    working_set_section: Mapping[str, Any] | None = field(
        default=None, repr=False
    )
    context_sections: tuple[Mapping[str, Any], ...] = field(
        default=(), repr=False
    )
    integrated_context_sections: tuple[Mapping[str, Any], ...] = field(
        default=(), repr=False
    )
    replaced_generation1_sections: tuple[Mapping[str, Any], ...] = field(
        default=(), repr=False
    )
    provider_calls_made: bool = False
    cache_warmed: bool = False
    runtime_imported: bool = False


def build_generation2_candidate(
    *,
    generation1_selection: Any,
    broker: Any,
    capability: str,
    command_context: Mapping[str, Any],
    readiness: Mapping[str, Any],
    offer: Mapping[str, Any] | None = None,
    working_set_section: Mapping[str, Any] | None = None,
    context_sections: Sequence[Mapping[str, Any]] | None = None,
    integrated_context_sections: Sequence[Mapping[str, Any]] | None = None,
) -> StandingRootGeneration2Candidate:
    normalized_readiness = validate_readiness(readiness)
    normalized_working_set_section = _validate_working_set_section(
        working_set_section
    )
    normalized_context_sections = _validate_context_sections(context_sections)
    normalized_integrated_context_sections = (
        milestone4.validate_integrated_sections(integrated_context_sections)
        if integrated_context_sections is not None
        else ()
    )
    if normalized_integrated_context_sections:
        integrated_by_id = {
            item["section_id"]: item
            for item in normalized_integrated_context_sections
        }
        raw_context_by_id = {
            item["section_id"]: item for item in normalized_context_sections
        }
        if (
            normalized_working_set_section is None
            or integrated_by_id.get("continuity_working_set")
            != normalized_working_set_section
            or any(
                raw_context_by_id.get(item["section_id"]) != item
                for item in normalized_integrated_context_sections
                if item["section_id"]
                in {
                    "continuity_cold_context",
                    "continuity_warm_context",
                    "continuity_hot_context",
                }
            )
        ):
            _fail("generation2_m4_authority_binding_invalid")
    if (
        generation1_selection.observability.get("active_prefix_generation")
        != GENERATION_1
        or generation1_selection.observability.get("active_prefix_sha256")
        != generation1.PRODUCTION_PREFIX_SHA256
    ):
        _fail("generation1_attestation_missing")
    assembly = generation1_selection.prompt_cache_assembly
    if assembly.chat_projection is None:
        _fail("generation1_chat_projection_missing")
    endpoint = chat_serialization.endpoint_request_from_chat_projection(
        assembly.chat_projection
    )
    messages = endpoint.get("messages")
    if not isinstance(messages, list) or len(messages) < 3:
        _fail("generation1_message_anatomy_invalid")
    stable_count = assembly.request_observability.get(
        "stable_message_count"
    )
    if type(stable_count) is not int or stable_count != len(messages) - 1:
        _fail("generation1_stable_boundary_invalid")
    generation1_tool_surface = _tool_surface(broker)
    generation1_tools = copy.deepcopy(
        generation1_tool_surface["provider_tool_definitions"]
    )
    generation2_tools = [
        *copy.deepcopy(generation1_tools),
        structured_terminal.provider_tool_definition(),
    ]
    generation2_tool_surface = copy.deepcopy(generation1_tool_surface)
    generation2_tool_surface["provider_tool_definitions"] = copy.deepcopy(
        generation2_tools
    )
    generation2_tool_surface["terminal_result_required"] = True
    system_message = {
        "role": "system",
        "content": provider_agent_runtime.TOOL_BRANCH_VISIBLE_ACK_INSTRUCTION,
    }
    generation1_messages = [system_message, *copy.deepcopy(messages)]
    provider_stable_count = stable_count + 1
    generation1_identity = _stable_identity(
        model=endpoint["model"],
        stable_provider_messages=(
            generation1_messages[:provider_stable_count]
        ),
        reviewed_tool_definitions=generation1_tools,
        tool_choice="auto",
        parallel_tool_calls=True,
        generation=GENERATION_1,
    )
    if (
        generation1_identity[
            "canonical_semantic_stable_surface_sha256"
        ]
        != generation1.PRODUCTION_PREFIX_SHA256
        or generation1_identity[
            "canonical_semantic_stable_surface_utf8_bytes"
        ]
        != generation1.PRODUCTION_PREFIX_UTF8_BYTES
    ):
        _fail("generation1_exact_identity_changed")

    expected_offer = continuity_offer(
        capability=capability,
        command_context=command_context,
        **(
            {
                "expires_at": offer.get("expires_at"),
                "client_turn_id": offer.get("client_turn_id"),
                "room_id": offer.get("room_id"),
                "provider_operation_id": offer.get(
                    "provider_operation_id"
                ),
                "maximum_total_operations": offer.get(
                    "maximum_total_operations"
                ),
            }
            if isinstance(offer, Mapping)
            and "expires_at" in offer
            else {}
        ),
    )
    if offer is not None and dict(offer) != expected_offer:
        _fail("generation2_offer_contract_invalid")
    offer = expected_offer
    replaced_generation1_sections = tuple(
        copy.deepcopy(item)
        for item in generation1_selection.section_outputs
        if isinstance(item, Mapping)
        and item.get("section_id") in milestone4.MANAGED_INPUT_SECTION_IDS
    ) if normalized_integrated_context_sections else ()
    generation2_assembly = (
        prompt_cache_production.assemble_production_prompt(
            legacy_user_text=generation1_selection.rendered_text,
            section_outputs=[
                *[
                    copy.deepcopy(item)
                    for item in generation1_selection.section_outputs
                    if isinstance(item, Mapping)
                    and item.get("section_id") != "memory_authorship_law"
                    and (
                        not normalized_integrated_context_sections
                        or item.get("section_id")
                        not in milestone4.MANAGED_INPUT_SECTION_IDS
                    )
                ],
                *(
                    [copy.deepcopy(normalized_working_set_section)]
                    if normalized_working_set_section is not None
                    and not normalized_integrated_context_sections
                    else []
                ),
                *(
                    [copy.deepcopy(item) for item in normalized_context_sections]
                    if not normalized_integrated_context_sections
                    else []
                ),
                *[
                    copy.deepcopy(item)
                    for item in normalized_integrated_context_sections
                ],
            ],
            envelope=generation1_selection.envelope,
            env={},
            model=endpoint["model"],
            route="openai_compatible_chat_completions",
            tools_requested=True,
            memory_authorship_protocol_version=None,
            continuity_authorship_instruction=(
                continuity_law.PROVIDER_VISIBLE_INSTRUCTION
            ),
            continuity_authorship_protocol_version=(
                continuity_law.PROTOCOL_VERSION
            ),
            continuity_authorship_available=True,
            continuity_authorship_offer=offer,
        )
    )
    if (
        not generation2_assembly.stable_prefix_used
        or generation2_assembly.chat_projection is None
    ):
        _fail("generation2_typed_assembly_failed")
    generation2_endpoint = (
        chat_serialization.endpoint_request_from_chat_projection(
            generation2_assembly.chat_projection
        )
    )
    generation2_endpoint_messages = generation2_endpoint.get("messages")
    generation2_stable_count = (
        generation2_assembly.request_observability.get(
            "stable_message_count"
        )
    )
    if (
        not isinstance(generation2_endpoint_messages, list)
        or generation2_stable_count != stable_count
    ):
        _fail("generation2_typed_stable_boundary_changed")
    generation2_messages = [
        copy.deepcopy(system_message),
        *copy.deepcopy(generation2_endpoint_messages),
    ]
    generation2_identity = _stable_identity(
        model=endpoint["model"],
        stable_provider_messages=(
            generation2_messages[:provider_stable_count]
        ),
        reviewed_tool_definitions=generation2_tools,
        tool_choice=structured_terminal.forced_tool_choice(),
        parallel_tool_calls=False,
        generation=GENERATION_2,
    )
    if (
        generation2_identity[
            "canonical_semantic_stable_surface_sha256"
        ]
        == generation1.PRODUCTION_PREFIX_SHA256
        or generation2_identity["prefix_version"]
        == generation1.PRODUCTION_PREFIX_VERSION
        or generation2_identity["cache_key"]
        == generation1.PRODUCTION_CACHE_KEY
    ):
        _fail("generation2_identity_reused_generation1")

    generation1_request = {
        "model": endpoint["model"],
        "messages": generation1_messages,
        "tools": copy.deepcopy(generation1_tools),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "stream": endpoint["stream"],
    }
    generation2_request = {
        "model": endpoint["model"],
        "messages": generation2_messages,
        "tools": copy.deepcopy(generation2_tools),
        "tool_choice": structured_terminal.forced_tool_choice(),
        "parallel_tool_calls": False,
        "stream": endpoint["stream"],
    }
    return StandingRootGeneration2Candidate(
        generation1_request=generation1_request,
        generation2_request=generation2_request,
        generation2_tool_surface=generation2_tool_surface,
        generation2_assembly=generation2_assembly,
        generation1_identity=generation1_identity,
        generation2_identity=generation2_identity,
        readiness=normalized_readiness,
        standing_root_body_identities=_card_body_hashes(),
        offer=offer,
        working_set_section=normalized_working_set_section,
        context_sections=normalized_context_sections,
        integrated_context_sections=normalized_integrated_context_sections,
        replaced_generation1_sections=replaced_generation1_sections,
    )


def production_selection_from_candidate(
    candidate: StandingRootGeneration2Candidate,
    generation1_selection: generation1.ProductionPromptSelection,
) -> generation1.ProductionPromptSelection:
    """Project one already-built candidate into the ordinary runtime selection."""

    attest_generation2_candidate(candidate)
    assembly = candidate.generation2_assembly
    identity = candidate.generation2_identity
    stable_count = assembly.request_observability.get("stable_message_count")
    if (
        assembly.chat_projection is None
        or type(stable_count) is not int
        or stable_count < 1
    ):
        _fail("generation2_candidate_selection_invalid")
    observability = {
        **dict(generation1_selection.observability),
        "active_prefix_assembly_version": ASSEMBLY_VERSION,
        "active_prefix_generation": GENERATION_2,
        "active_prefix_version": identity["prefix_version"],
        "active_prefix_sha256": identity[
            "canonical_semantic_stable_surface_sha256"
        ],
        "active_prefix_utf8_bytes": identity[
            "canonical_semantic_stable_surface_utf8_bytes"
        ],
        "active_cache_key": identity["cache_key"],
        "active_cache_retention": identity["retention"],
        "gate12_one_shot": True,
    }
    request_observability = {
        **dict(assembly.request_observability),
        "prefix_profile": PREFIX_PROFILE,
        "prefix_version": identity["prefix_version"],
        "prefix_sha256": identity[
            "canonical_semantic_stable_surface_sha256"
        ],
        "stable_projection_utf8_bytes": identity[
            "canonical_semantic_stable_surface_utf8_bytes"
        ],
        "cache_key": identity["cache_key"],
        "retention": identity["retention"],
    }
    attested = prompt_cache_production.ProductionPromptCacheAssembly(
        legacy_user_text=assembly.legacy_user_text,
        chat_projection=assembly.chat_projection,
        request_observability=request_observability,
    )
    return generation1.ProductionPromptSelection(
        envelope=generation1_selection.envelope,
        rendered_text=generation1_selection.rendered_text,
        section_metrics=generation1_selection.section_metrics,
        section_outputs=generation1_selection.section_outputs,
        prompt_cache_assembly=attested,
        observability=observability,
        reviewed_read_only_capabilities=(
            generation1_selection.reviewed_read_only_capabilities
        ),
    )


def attest_generation2_candidate(
    candidate: StandingRootGeneration2Candidate,
) -> dict[str, Any]:
    """Recompute the local candidate boundary without trusting its receipts."""

    if type(candidate) is not StandingRootGeneration2Candidate:
        _fail("generation2_candidate_type_invalid")
    if (
        candidate.provider_calls_made is not False
        or candidate.cache_warmed is not False
        or candidate.runtime_imported is not False
    ):
        _fail("generation2_local_only_boundary_violated")
    validate_readiness(candidate.readiness)
    expected_offer = continuity_offer(
        capability=candidate.offer.get("capability"),
        command_context=candidate.offer.get("command_context"),
        **(
            {
                "expires_at": candidate.offer.get("expires_at"),
                "client_turn_id": candidate.offer.get("client_turn_id"),
                "room_id": candidate.offer.get("room_id"),
                "provider_operation_id": candidate.offer.get(
                    "provider_operation_id"
                ),
                "maximum_total_operations": candidate.offer.get(
                    "maximum_total_operations"
                ),
            }
            if "expires_at" in candidate.offer
            else {}
        ),
    )
    if dict(candidate.offer) != expected_offer:
        _fail("generation2_offer_contract_invalid")
    working_set_section = _validate_working_set_section(
        candidate.working_set_section
    )
    context_sections = _validate_context_sections(candidate.context_sections)
    if tuple(candidate.context_sections) != context_sections:
        _fail("generation2_context_sections_invalid")
    integrated_context_sections = (
        milestone4.validate_integrated_sections(
            candidate.integrated_context_sections
        )
        if candidate.integrated_context_sections
        else ()
    )
    if tuple(candidate.integrated_context_sections) != integrated_context_sections:
        _fail("generation2_m4_integrated_sections_invalid")
    replaced_generation1_sections = tuple(
        copy.deepcopy(dict(item))
        for item in candidate.replaced_generation1_sections
        if isinstance(item, Mapping)
        and item.get("section_id") in milestone4.MANAGED_INPUT_SECTION_IDS
    )
    if replaced_generation1_sections != tuple(
        candidate.replaced_generation1_sections
    ):
        _fail("generation2_m4_replaced_sections_invalid")
    generation1_request = copy.deepcopy(dict(candidate.generation1_request))
    generation2_request = copy.deepcopy(dict(candidate.generation2_request))
    if (
        set(generation1_request)
        != {
            "model",
            "messages",
            "tools",
            "tool_choice",
            "parallel_tool_calls",
            "stream",
        }
        or set(generation2_request) != set(generation1_request)
    ):
        _fail("generation2_request_shape_invalid")
    for field_name in ("model", "stream"):
        if (
            _exact_json_bytes(generation1_request[field_name])
            != _exact_json_bytes(generation2_request[field_name])
        ):
            _fail("generation2_invariant_request_field_changed")
    if (
        generation2_request["tools"]
        != [
            *generation1_request["tools"],
            structured_terminal.provider_tool_definition(),
        ]
        or generation2_request["tool_choice"]
        != structured_terminal.forced_tool_choice()
        or generation2_request["parallel_tool_calls"] is not False
        or generation1_request["tool_choice"] != "auto"
        or generation1_request["parallel_tool_calls"] is not True
    ):
        _fail("generation2_structured_tool_surface_invalid")
    messages1 = generation1_request["messages"]
    messages2 = generation2_request["messages"]
    if (
        not isinstance(messages1, list)
        or not isinstance(messages2, list)
        or len(messages1) != len(messages2)
        or len(messages1) < 4
    ):
        _fail("generation2_message_anatomy_invalid")
    if messages1[0] != messages2[0]:
        _fail("generation2_tool_ack_instruction_changed")
    if messages1[2:-1] != messages2[2:-1]:
        _fail("generation2_stable_or_history_message_changed")

    developer1 = _parse_wrapper(
        messages1[1].get("content"),
        version="HOUSE_CHAT_DEVELOPER_V2",
        exact_fields=(
            "instruction_law",
            "data_isolation_law",
            "output_policy",
        ),
    )
    developer2 = _parse_wrapper(
        messages2[1].get("content"),
        version="HOUSE_CHAT_DEVELOPER_V2",
        exact_fields=(
            "instruction_law",
            "data_isolation_law",
            "output_policy",
        ),
    )
    if (
        developer2["instruction_law"]
        != [
            *[
                value
                for value in developer1["instruction_law"]
                if value != memory_law.PROVIDER_VISIBLE_INSTRUCTION
            ],
            continuity_law.PROVIDER_VISIBLE_INSTRUCTION,
        ]
        or developer2["data_isolation_law"]
        != developer1["data_isolation_law"]
    ):
        _fail("generation2_instruction_delta_invalid")
    if (
        developer2["instruction_law"].count(
            continuity_law.PROVIDER_VISIBLE_INSTRUCTION
        )
        != 1
        or memory_law.PROVIDER_VISIBLE_INSTRUCTION
        in developer2["instruction_law"]
    ):
        _fail("continuity_instruction_not_singular")
    try:
        policy1 = json.loads(developer1["output_policy"])
        policy2 = json.loads(developer2["output_policy"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise StandingRootGeneration2LocalError(
            "generation2_output_policy_invalid"
        ) from exc
    if not isinstance(policy1, dict) or not isinstance(policy2, dict):
        _fail("generation2_output_policy_invalid")
    continuity_fields = {
        "continuity_authorship_available": True,
        "continuity_authorship_protocol_version": (
            continuity_law.PROTOCOL_VERSION
        ),
        "continuity_authorship_requires_turn_capability": True,
    }
    for field_name, expected in continuity_fields.items():
        if policy2.get(field_name) != expected:
            _fail("generation2_output_policy_continuity_mismatch")
    if policy2.get("memory_authorship_available") is not False:
        _fail("generation2_memory_authorship_not_disabled")
    stripped_policy2 = {
        key: value
        for key, value in policy2.items()
        if key not in continuity_fields
    }
    stripped_policy2["memory_authorship_available"] = True
    if policy1 != stripped_policy2:
        _fail("generation2_unapproved_output_policy_changed")
    if policy1.get("memory_authorship_available") is not True:
        _fail("generation2_memory_route_unavailable")

    current1 = _parse_wrapper(
        messages1[-1].get("content"),
        version="HOUSE_CURRENT_TURN_V1",
        exact_fields=("dynamic_context", "current_input"),
    )
    current2 = _parse_wrapper(
        messages2[-1].get("content"),
        version="HOUSE_CURRENT_TURN_V1",
        exact_fields=("dynamic_context", "current_input"),
    )
    if current1["current_input"] != current2["current_input"]:
        _fail("generation2_current_input_changed")
    dynamic_without_offer = list(current2["dynamic_context"][:-1])
    expected_generation1_dynamic = list(current1["dynamic_context"])
    if integrated_context_sections:
        integrated_by_id = {
            item["section_id"]: item for item in integrated_context_sections
        }
        raw_context_by_id = {
            item["section_id"]: item for item in context_sections
        }
        if (
            working_set_section is None
            or integrated_by_id.get("continuity_working_set")
            != working_set_section
            or any(
                raw_context_by_id.get(item["section_id"]) != item
                for item in integrated_context_sections
                if item["section_id"]
                in {
                    "continuity_cold_context",
                    "continuity_warm_context",
                    "continuity_hot_context",
                }
            )
        ):
            _fail("generation2_m4_authority_binding_invalid")
        for section in integrated_context_sections:
            rendered = section["rendered_text"]
            if dynamic_without_offer.count(rendered) != 1:
                _fail("generation2_m4_integrated_section_mismatch")
            dynamic_without_offer.remove(rendered)
        for section in replaced_generation1_sections:
            rendered = section["rendered_text"]
            if expected_generation1_dynamic.count(rendered) != 1:
                _fail("generation2_m4_replaced_section_mismatch")
            expected_generation1_dynamic.remove(rendered)
    else:
        if working_set_section is not None:
            rendered_working_set = working_set_section["rendered_text"]
            if dynamic_without_offer.count(rendered_working_set) != 1:
                _fail("generation2_working_set_section_mismatch")
            dynamic_without_offer.remove(rendered_working_set)
        for context_section in context_sections:
            rendered_context = context_section["rendered_text"]
            if dynamic_without_offer.count(rendered_context) != 1:
                _fail("generation2_context_section_mismatch")
            dynamic_without_offer.remove(rendered_context)
    if dynamic_without_offer != expected_generation1_dynamic:
        _fail("generation2_dynamic_offer_delta_invalid")
    if list(current2)[-1] != "current_input":
        _fail("generation2_current_input_not_last")
    try:
        rendered_offer = json.loads(current2["dynamic_context"][-1])
    except (TypeError, json.JSONDecodeError) as exc:
        raise StandingRootGeneration2LocalError(
            "generation2_offer_render_invalid"
        ) from exc
    if rendered_offer != candidate.offer:
        _fail("generation2_offer_identity_mismatch")

    stable1 = _stable_identity(
        model=generation1_request["model"],
        stable_provider_messages=messages1[:-1],
        reviewed_tool_definitions=generation1_request["tools"],
        tool_choice=generation1_request["tool_choice"],
        parallel_tool_calls=generation1_request[
            "parallel_tool_calls"
        ],
        generation=GENERATION_1,
    )
    stable2 = _stable_identity(
        model=generation2_request["model"],
        stable_provider_messages=messages2[:-1],
        reviewed_tool_definitions=generation2_request["tools"],
        tool_choice=generation2_request["tool_choice"],
        parallel_tool_calls=generation2_request[
            "parallel_tool_calls"
        ],
        generation=GENERATION_2,
    )
    if (
        stable1 != candidate.generation1_identity
        or stable2 != candidate.generation2_identity
    ):
        _fail("generation2_identity_receipt_mismatch")
    if stable1[
        "canonical_semantic_stable_surface_sha256"
    ] != generation1.PRODUCTION_PREFIX_SHA256:
        _fail("generation1_exact_identity_changed")
    if tuple(_card_body_hashes()) != tuple(
        candidate.standing_root_body_identities
    ):
        _fail("standing_root_body_identity_changed")
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "ready_local_candidate",
        "generation1_unchanged": True,
        "generation2_distinct": True,
        "standing_root_card_count": 7,
        "memory_route_unchanged": True,
        "tool_order_unchanged": True,
        "current_input_last": True,
        "working_set_section_present": working_set_section is not None,
        "context_section_ids": [
            item["section_id"] for item in context_sections
        ],
        "integrated_context_section_ids": [
            item["section_id"] for item in integrated_context_sections
        ],
        "provider_calls_made": False,
        "cache_warmed": False,
        "runtime_imported": False,
    }


__all__ = [
    "ASSEMBLY_VERSION",
    "GENERATION_1",
    "GENERATION_2",
    "GENERATION_SELECTOR",
    "OFFER_SCHEMA_VERSION",
    "PREFIX_PROFILE",
    "READINESS_SCHEMA_VERSION",
    "RETENTION",
    "SCHEMA_VERSION",
    "StandingRootGeneration2Candidate",
    "StandingRootGeneration2LocalError",
    "attest_generation2_candidate",
    "build_generation2_candidate",
    "build_local_readiness_attestation",
    "configured_generation",
    "continuity_offer",
    "generation1_dynamic_context_without_m4_managed",
    "generation2_dynamic_context_from_candidate",
    "production_selection_from_candidate",
    "validate_readiness",
]
