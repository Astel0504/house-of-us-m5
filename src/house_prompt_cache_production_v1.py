"""Ordinary House prompt-cache assembly and raw-free observability.

This owner reorganizes already-selected provider-visible sections.  It does
not select context, retrieve memory, call a provider, persist prompt content,
or log raw text.  Assembly failure returns the previous flattened user text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

import house_provider_chat_adapter_v0 as chat_adapter
import house_provider_chat_serialization_v0 as chat_serialization
import house_provider_neutral_request_v0 as neutral
import house_prompt_cache_retention_policy_v1 as retention_policy
import living_footing_packet_v0 as living_footing
import provider_observability_v0 as provider_observability


PRODUCTION_CACHE_SCHEMA_VERSION = "house_prompt_cache_production_v1"
PRODUCTION_PREFIX_PROFILE = "house_prompt_cache_stable_prefix_v1"
PRODUCTION_PREFIX_ASSEMBLY_VERSION = "house_prompt_cache_production_assembly_v1"
PRODUCTION_CACHE_OBSERVABILITY_VERSION = "house_prompt_cache_production_observability_v1"
FEATURE_SWITCH_NAME = "HOUSE_PROMPT_CACHE_PRODUCTION_ASSEMBLY"
PRODUCTION_CACHE_DEFAULT_ENABLED = True

_ON_VALUES = frozenset({"1", "true", "yes", "on", "enabled"})
_OFF_VALUES = frozenset({"0", "false", "no", "off", "disabled"})
_SUPPORTED_ROUTE = "openai_compatible_chat_completions"
_SUPPORTED_MODEL_IDENTIFIERS = frozenset({
    "gpt-5.5",
    "openai/gpt-5.5",
})
_CONTINUITY_OFFER_SCHEMA_VERSION = "house_continuity_authorship_offer_v1"
_CONTINUITY_CAPABILITY_RE = re.compile(r"^cwc_[A-Za-z0-9_-]{43}$")
_CONTINUITY_OFFER_FIELDS = (
    "schema_version",
    "state",
    "protocol_version",
    "capability",
    "command_context",
    "descriptive_dynamic_data",
    "instruction_authority",
    "memory_authority",
    "action_authority",
    "raw_body_included",
)
_CONTINUITY_GATE12_OFFER_FIELDS = (
    "schema_version",
    "state",
    "protocol_version",
    "capability",
    "expires_at",
    "maximum_total_operations",
    "coverage_decision_required",
    "client_turn_id",
    "room_id",
    "provider_operation_id",
    "command_context",
    "descriptive_dynamic_data",
    "instruction_authority",
    "memory_authority",
    "action_authority",
    "raw_body_included",
)
_INSTRUCTION_SECTION_IDS = frozenset(
    {
        "context_footing_law",
        "memory_authorship_law",
        "response_format_law",
    }
)
_OLDER_CONTEXT_SECTION_IDS = frozenset(
    {
        "active_room_throughline",
        "current_house_talk_room",
        "earlier_house_talk_continuity",
        "earlier_house_talk_continuity_background",
        "continuity_cold_context",
        "continuity_warm_context",
        "thread_summary",
    }
)
_RECENT_CONTEXT_SECTION_IDS = frozenset(
    {
        "recent_visible_exchange",
        "continuity_hot_context",
        "m4_recent_turns",
        "short_term_continuity",
    }
)
_ATTACHMENT_HELPER_SECTION_IDS = frozenset(
    {
        "current_audio",
        "read_mode_source_context",
        "read_mode_exact_text",
        "turn_context",
        "m4_source_context",
    }
)
_OBSERVABILITY_FIELDS = frozenset(
    {
        "schema_version",
        "feature_switch",
        "configured_mode",
        "effective_mode",
        "prefix_profile",
        "prefix_version",
        "prefix_sha256",
        "stable_projection_utf8_bytes",
        "stable_message_count",
        "semantic_equivalence",
        "semantic_section_count",
        "semantic_section_sha256",
        "model",
        "route",
        "provider_input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "cache_state",
        "cached_input_ratio",
        "local_assembly_fallback_state",
        "local_assembly_fallback_count",
        "provider_fallback",
        "request_outcome",
        "retention_feature_switch",
        "retention_configured_mode",
        "retention_policy_state",
        "retention_request_field",
        "retention_requested_value",
        "provider_prefix_identity_state",
        "provider_prefix_sha256",
        "provider_prefix_utf8_bytes",
        "provider_stable_message_count",
        "provider_tool_definition_count",
        "provider_retention_field",
        "provider_retention_value",
        "provider_prompt_cache_key_present",
    }
)


class ProductionPromptCacheError(ValueError):
    """Raised for a local production-cache assembly contract failure."""


@dataclass(frozen=True)
class ProductionPromptCacheAssembly:
    legacy_user_text: str = field(repr=False)
    chat_projection: chat_adapter.ChatProjection | None = field(
        default=None,
        repr=False,
    )
    request_observability: Mapping[str, Any] = field(default_factory=dict)

    @property
    def stable_prefix_used(self) -> bool:
        return self.chat_projection is not None


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ProductionPromptCacheError("canonical encoding failed") from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_label(value: Any, *, fallback: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    safe = "".join(
        character
        for character in text
        if character.isascii() and (character.isalnum() or character in "._:-")
    )
    return safe[:180] or fallback


def configured_feature_mode(
    env: Mapping[str, str] | None,
) -> tuple[str, bool]:
    source = env if env is not None else {}
    raw = str(source.get(FEATURE_SWITCH_NAME) or "").strip().casefold()
    if not raw:
        return (
            "default_on" if PRODUCTION_CACHE_DEFAULT_ENABLED else "default_off",
            PRODUCTION_CACHE_DEFAULT_ENABLED,
        )
    if raw in _ON_VALUES:
        return "explicit_on", True
    if raw in _OFF_VALUES:
        return "explicit_off", False
    return "invalid_off", False


def _base_observability(
    *,
    configured_mode: str,
    effective_mode: str,
    fallback_state: str,
    fallback_count: int,
    model: str,
    retention_observability: Mapping[str, Any],
) -> dict[str, Any]:
    result = {
        "schema_version": PRODUCTION_CACHE_OBSERVABILITY_VERSION,
        "feature_switch": FEATURE_SWITCH_NAME,
        "configured_mode": configured_mode,
        "effective_mode": effective_mode,
        "prefix_profile": PRODUCTION_PREFIX_PROFILE,
        "prefix_version": "",
        "prefix_sha256": "",
        "stable_projection_utf8_bytes": 0,
        "stable_message_count": 0,
        "semantic_equivalence": "legacy_exact"
        if effective_mode == "legacy"
        else "pending",
        "semantic_section_count": 0,
        "semantic_section_sha256": "",
        "model": _safe_label(model, fallback="unknown"),
        "route": _SUPPORTED_ROUTE,
        "provider_input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "cache_state": "unavailable",
        "cached_input_ratio": None,
        "local_assembly_fallback_state": fallback_state,
        "local_assembly_fallback_count": fallback_count,
        "provider_fallback": False,
        "request_outcome": "not_called",
        "provider_prefix_identity_state": "pre_wrapper_only",
        "provider_prefix_sha256": "",
        "provider_prefix_utf8_bytes": 0,
        "provider_stable_message_count": 0,
        "provider_tool_definition_count": 0,
        "provider_retention_field": "",
        "provider_retention_value": "",
        "provider_prompt_cache_key_present": False,
    }
    result.update(dict(retention_observability))
    return result


def _validated_sections(
    section_outputs: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, value in enumerate(section_outputs):
        if not isinstance(value, Mapping):
            raise ProductionPromptCacheError("provider section output is invalid")
        section_id = _safe_label(value.get("section_id"))
        rendered_text = value.get("rendered_text")
        if (
            not section_id
            or section_id in seen_ids
            or not isinstance(rendered_text, str)
            or not rendered_text.strip()
        ):
            raise ProductionPromptCacheError("provider section identity is invalid")
        seen_ids.add(section_id)
        sections.append(
            {
                "section_id": section_id,
                "section_class": _safe_label(
                    value.get("section_class"),
                    fallback="standing_live_state",
                ),
                "exactness": _safe_label(value.get("exactness"), fallback="derived"),
                "update_frequency": _safe_label(
                    value.get("update_frequency"),
                    fallback="per_turn",
                ),
                "rendered_text": rendered_text,
                "source_order": str(index),
            }
        )
    if not sections:
        raise ProductionPromptCacheError("provider sections are empty")
    return sections


def _parse_living_render(value: str) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for section in value.split("\n\n"):
        heading, separator, body = section.partition("\n")
        if not separator or not heading.endswith(":") or not body:
            raise ProductionPromptCacheError("living-footing render is not splittable")
        parsed.append((heading, body))
    return parsed


def _merge_living_renders(*values: str) -> str:
    order: list[str] = []
    bodies: dict[str, list[str]] = {}
    for value in values:
        if not value:
            continue
        for heading, body in _parse_living_render(value):
            if heading not in bodies:
                order.append(heading)
                bodies[heading] = []
            bodies[heading].append(body)
    return "\n\n".join(
        f"{heading}\n{' '.join(bodies[heading])}"
        for heading in order
    )


def _living_dynamic_remainder(
    selected_text: str,
    stable_text: str,
) -> str:
    selected_sections = _parse_living_render(selected_text)
    stable_sections = dict(_parse_living_render(stable_text))
    remainder: list[tuple[str, str]] = []
    seen_stable: set[str] = set()
    for heading, selected_body in selected_sections:
        stable_body = stable_sections.get(heading)
        if stable_body is None:
            remainder.append((heading, selected_body))
            continue
        seen_stable.add(heading)
        if selected_body == stable_body:
            continue
        prefix = f"{stable_body} "
        if not selected_body.startswith(prefix):
            raise ProductionPromptCacheError(
                "stable living footing is not an exact selected prefix"
            )
        dynamic_body = selected_body[len(prefix) :]
        if dynamic_body:
            remainder.append((heading, dynamic_body))
    if seen_stable != set(stable_sections):
        raise ProductionPromptCacheError(
            "stable living footing heading is absent from selected content"
        )
    return "\n\n".join(
        f"{heading}\n{body}" for heading, body in remainder
    )


def _living_packet_projection(
    packet: Mapping[str, Any],
    *,
    stable: bool,
) -> dict[str, Any]:
    projected = dict(packet)
    profile_items = [
        dict(item)
        for item in packet.get("profile_footing_items", [])
        if isinstance(item, Mapping)
    ]
    stable_profile_items = [
        item
        for item in profile_items
        if item.get("source_class") in {"profile_footing", "profile_preference"}
    ]
    dynamic_profile_items = [
        item
        for item in profile_items
        if item.get("source_class") not in {"profile_footing", "profile_preference"}
    ]
    projected["profile_footing_items"] = (
        stable_profile_items if stable else dynamic_profile_items
    )
    projected["room_surface"] = packet.get("room_surface") if stable else ""
    for field_name in (
        "core_memory_footing_items",
        "active_situation_memory_items",
        "current_room_footing",
        "recent_pattern_footing",
    ):
        projected[field_name] = [] if stable else list(packet.get(field_name) or [])
    for field_name in ("active_task", "active_recall_target"):
        projected[field_name] = {} if stable else dict(
            packet.get(field_name)
            if isinstance(packet.get(field_name), Mapping)
            else {}
        )
    return projected


def _split_living_footing(
    section: Mapping[str, str],
    envelope: Mapping[str, Any],
) -> tuple[dict[str, str] | None, dict[str, str]]:
    living = (
        envelope.get("living_footing")
        if isinstance(envelope.get("living_footing"), Mapping)
        else {}
    )
    packet = living.get("packet") if isinstance(living.get("packet"), Mapping) else {}
    if not packet:
        return None, dict(section)
    stable_text = living_footing.render_living_footing_provider_section(
        _living_packet_projection(packet, stable=True),
        max_chars=len(section["rendered_text"]),
    )
    if not stable_text:
        return None, dict(section)
    try:
        dynamic_text = _living_dynamic_remainder(
            section["rendered_text"],
            stable_text,
        )
    except ProductionPromptCacheError:
        # Some ordinary packets place a dynamic reality item before profile
        # footing inside the same rendered heading.  Keep that exact selected
        # section dynamic instead of reordering it or failing the whole turn.
        return None, dict(section)
    if _merge_living_renders(stable_text, dynamic_text) != section["rendered_text"]:
        raise ProductionPromptCacheError(
            "living-footing partition would change selected content"
        )
    stable_section = {
        **dict(section),
        "section_id": "living_footing_stable",
        "section_class": "standing_quiet_relationship_footing",
        "update_frequency": "slowly_changing",
        "rendered_text": stable_text,
    }
    dynamic_section = {
        **dict(section),
        "rendered_text": dynamic_text,
    }
    return stable_section, dynamic_section


def _dynamic_rank(section_id: str) -> tuple[int, str]:
    if section_id in _OLDER_CONTEXT_SECTION_IDS:
        return 1, section_id
    if section_id in _RECENT_CONTEXT_SECTION_IDS:
        return 2, section_id
    if section_id in _ATTACHMENT_HELPER_SECTION_IDS:
        return 3, section_id
    return 0, section_id


def _partition_sections(
    section_outputs: Sequence[Mapping[str, Any]],
    *,
    envelope: Mapping[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
    instructions: list[dict[str, str]] = []
    stable: list[dict[str, str]] = []
    dynamic: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for section in _validated_sections(section_outputs):
        section_id = section["section_id"]
        if section_id == "current_input":
            if current is not None:
                raise ProductionPromptCacheError("current input is duplicated")
            current = section
            continue
        if section_id == "living_footing":
            stable_living, dynamic_living = _split_living_footing(
                section,
                envelope,
            )
            if stable_living is not None:
                stable.append(stable_living)
            if dynamic_living["rendered_text"]:
                dynamic.append(dynamic_living)
            continue
        if (
            section_id in _INSTRUCTION_SECTION_IDS
            or section["update_frequency"] == "immutable_versioned"
        ):
            instructions.append(section)
            continue
        if section["update_frequency"] == "slowly_changing":
            stable.append(section)
            continue
        dynamic.append(section)
    if current is None:
        raise ProductionPromptCacheError("current input section is missing")
    instructions.sort(key=lambda item: int(item["source_order"]))
    stable.sort(key=lambda item: int(item["source_order"]))
    dynamic.sort(
        key=lambda item: (
            _dynamic_rank(item["section_id"])[0],
            int(item["source_order"]),
        )
    )
    return instructions, stable, dynamic, current


def _semantic_unit(
    section: Mapping[str, str],
    *,
    ordinal: int,
    authority_class: str,
    source_class: str,
    exact: bool = False,
) -> dict[str, Any]:
    section_id = section["section_id"]
    text = section["rendered_text"]
    return neutral.semantic_unit(
        unit_id=f"production:{authority_class}:{section_id}",
        ordinal=ordinal,
        authority_class=authority_class,
        content_kind="exact_source_text" if exact else "house_derived_text",
        source_text=text,
        provider_text=text,
        transformation_flags=() if exact else ("continuity_derived",),
        exactness="exact" if exact else "derived",
        source_class=source_class,
        source_references=(
            neutral.source_reference(
                source_class=source_class,
                source_id=f"production:{section_id}",
            ),
        ),
        internal_provenance=neutral.unit_provenance(
            owner="house_prompt_cache_production_v1",
            source_snapshot_id=f"production:{section_id}",
            derivation_version=None
            if exact
            else PRODUCTION_PREFIX_ASSEMBLY_VERSION,
        ),
    )


def _validated_continuity_offer(
    value: Mapping[str, Any],
    *,
    protocol_version: str,
) -> dict[str, Any]:
    """Validate the exact optional Gate-6 offer before provider rendering.

    The Gate-0 contract import is deliberately lazy: generation-1/default
    assembly neither imports nor executes continuity schema code.
    """

    if not isinstance(value, Mapping):
        raise ProductionPromptCacheError(
            "continuity offer must be an exact mapping"
        )
    raw = dict(value)
    field_order = tuple(raw)
    if field_order not in {
        _CONTINUITY_OFFER_FIELDS,
        _CONTINUITY_GATE12_OFFER_FIELDS,
    }:
        raise ProductionPromptCacheError(
            "continuity offer fields are not exact or ordered"
        )
    if (
        raw["schema_version"] != _CONTINUITY_OFFER_SCHEMA_VERSION
        or raw["state"] != "offered"
        or raw["protocol_version"] != protocol_version
        or not isinstance(raw["capability"], str)
        or _CONTINUITY_CAPABILITY_RE.fullmatch(raw["capability"]) is None
        or raw["descriptive_dynamic_data"] is not True
        or raw["instruction_authority"] is not False
        or raw["memory_authority"] is not False
        or raw["action_authority"] is not False
        or raw["raw_body_included"] is not False
    ):
        raise ProductionPromptCacheError(
            "continuity offer authority or identity is invalid"
        )
    if field_order == _CONTINUITY_GATE12_OFFER_FIELDS:
        if (
            not isinstance(raw["expires_at"], str)
            or not raw["expires_at"]
            or raw["maximum_total_operations"] != 1
            or raw["coverage_decision_required"] is not True
            or not all(
                isinstance(raw[name], str) and bool(raw[name])
                for name in (
                    "client_turn_id",
                    "room_id",
                    "provider_operation_id",
                )
            )
            or not isinstance(raw["command_context"], Mapping)
            or raw["room_id"] != raw["command_context"].get("room_id")
        ):
            raise ProductionPromptCacheError(
                "Gate-12 continuity offer binding is invalid"
            )
    try:
        from house_continuity_v1_2_contract_schema_v0 import (
            validate_command_context,
        )

        command_context = validate_command_context(raw["command_context"])
    except Exception as exc:
        raise ProductionPromptCacheError(
            "continuity offer command context is invalid"
        ) from exc
    normalized = dict(raw)
    normalized["command_context"] = command_context
    if normalized != raw:
        raise ProductionPromptCacheError(
            "continuity offer command context is not canonical"
        )
    return normalized


def _build_neutral_request(
    *,
    instructions: Sequence[Mapping[str, str]],
    stable: Sequence[Mapping[str, str]],
    dynamic: Sequence[Mapping[str, str]],
    current: Mapping[str, str],
    memory_authorship_protocol_version: str | None,
    continuity_authorship_instruction: str | None,
    continuity_authorship_protocol_version: str | None,
    continuity_authorship_available: bool | None,
    continuity_authorship_offer: Mapping[str, Any] | None,
) -> dict[str, Any]:
    continuity_values = (
        continuity_authorship_instruction,
        continuity_authorship_protocol_version,
        continuity_authorship_available,
    )
    if any(value is not None for value in continuity_values):
        if (
            not isinstance(continuity_authorship_instruction, str)
            or not continuity_authorship_instruction
            or not isinstance(
                continuity_authorship_protocol_version, str
            )
            or not continuity_authorship_protocol_version
            or continuity_authorship_available is not True
        ):
            raise ProductionPromptCacheError(
                "continuity authorship typed inputs are inconsistent"
            )
        continuity_section = {
            "section_id": "continuity_authorship_law",
            "section_class": "continuity_authorship_law",
            "exactness": "exact",
            "update_frequency": "immutable_versioned",
            "rendered_text": continuity_authorship_instruction,
        }
        instruction_values = [*instructions, continuity_section]
    else:
        instruction_values = list(instructions)
    if continuity_authorship_offer is not None:
        if continuity_authorship_available is not True:
            raise ProductionPromptCacheError(
                "continuity offer requires typed authorship availability"
            )
        if continuity_authorship_protocol_version is None:
            raise ProductionPromptCacheError(
                "continuity offer requires typed protocol identity"
            )
        validated_offer = _validated_continuity_offer(
            continuity_authorship_offer,
            protocol_version=continuity_authorship_protocol_version,
        )
        offer_section = {
            "section_id": "continuity_authorship_offer",
            "section_class": "continuity_authorship_offer",
            "exactness": "derived",
            "update_frequency": "per_turn",
            "rendered_text": _canonical_json_bytes(
                validated_offer
            ).decode("utf-8"),
        }
        dynamic_values = [*dynamic, offer_section]
    else:
        dynamic_values = list(dynamic)
    section_ids = [
        item["section_id"]
        for item in (*instruction_values, *stable, *dynamic_values, current)
    ]
    snapshot_id = f"production:{_sha256(_canonical_json_bytes(section_ids))[:24]}"
    return neutral.neutral_request(
        initiation_type="user",
        model_route_value=neutral.model_route(
            route_class="main_talk",
            model_class="general_dialogue",
            tool_mode="none",
        ),
        instruction_law_units=[
            _semantic_unit(
                item,
                ordinal=index,
                authority_class="instruction_law",
                source_class="house_behavior_law",
            )
            for index, item in enumerate(instruction_values)
        ],
        context_data_units=[
            _semantic_unit(
                item,
                ordinal=index,
                authority_class="context_data",
                source_class="relationship_footing",
            )
            for index, item in enumerate(stable)
        ],
        conversation_units=[],
        dynamic_context_units=[
            _semantic_unit(
                item,
                ordinal=index,
                authority_class="dynamic_context",
                source_class=(
                    "attachment"
                    if item["section_id"] in _ATTACHMENT_HELPER_SECTION_IDS
                    else "standing_live_state"
                ),
                exact=(
                    item["section_id"] == "m4_exact_recall"
                    and item["exactness"] == "exact"
                ),
            )
            for index, item in enumerate(dynamic_values)
        ],
        current_input_unit=_semantic_unit(
            current,
            ordinal=0,
            authority_class="current_input",
            source_class="current_input",
            exact=True,
        ),
        proactive_event_unit_value=None,
        output_policy_value=neutral.output_policy(
            split_marker_protocol_version="house_visible_split_marker_v0",
            memory_authorship_protocol_version=(
                memory_authorship_protocol_version
            ),
            continuity_authorship_protocol_version=(
                continuity_authorship_protocol_version
            ),
            continuity_authorship_available=(
                continuity_authorship_available
            ),
            continuity_authorship_requires_turn_capability=(
                True
                if continuity_authorship_available is True
                else None
            ),
            generation_policy_epoch=PRODUCTION_PREFIX_PROFILE,
        ),
        provider_capability_policy_value=neutral.provider_capability_policy(
            required_capabilities=(
                "instruction_authority",
                "text_output",
                "split_segments",
            ),
            optional_capabilities=("prompt_caching",),
            forbidden_capabilities=(
                "structured_output",
                "tool_operations",
                "vision_input",
                "audio_input",
                "proactive_event",
            ),
        ),
        internal_provenance=neutral.request_provenance(
            build_mode="local_shadow",
            owner="house_prompt_cache_production_v1",
            source_snapshot_id=snapshot_id,
            builder_version=PRODUCTION_PREFIX_ASSEMBLY_VERSION,
            builder_input_ids=section_ids,
        ),
    )


def _stable_projection_identity(
    projection: chat_adapter.ChatProjection,
) -> tuple[str, int, int]:
    stable_messages = [
        {"role": message.role, "content": message.content}
        for message in projection.messages[:-1]
    ]
    payload = {
        "model": projection.model,
        "messages": stable_messages,
    }
    encoded = _canonical_json_bytes(payload)
    return _sha256(encoded), len(encoded), len(stable_messages)


def _semantic_section_identity(
    sections: Sequence[Mapping[str, Any]],
) -> tuple[str, int]:
    values = [
        {
            "section_id": section["section_id"],
            "rendered_text_sha256": _sha256(
                str(section["rendered_text"]).encode("utf-8")
            ),
        }
        for section in sections
    ]
    return _sha256(_canonical_json_bytes(values)), len(values)


def assemble_production_prompt(
    *,
    legacy_user_text: str,
    section_outputs: Sequence[Mapping[str, Any]],
    envelope: Mapping[str, Any],
    env: Mapping[str, str] | None,
    model: str,
    route: str,
    tools_requested: bool,
    memory_authorship_protocol_version: str | None = None,
    continuity_authorship_instruction: str | None = None,
    continuity_authorship_protocol_version: str | None = None,
    continuity_authorship_available: bool | None = None,
    continuity_authorship_offer: Mapping[str, Any] | None = None,
) -> ProductionPromptCacheAssembly:
    """Build the stable-prefix projection or preserve the legacy user text."""

    configured_mode, enabled = configured_feature_mode(env)
    inactive_retention = retention_policy.decision_from_env(
        env=env,
        provider="openai_compatible",
        endpoint_family="chat_completions",
        model=model,
        stable_prefix_effective=False,
    )
    if not enabled:
        return ProductionPromptCacheAssembly(
            legacy_user_text=legacy_user_text,
            request_observability=_base_observability(
                configured_mode=configured_mode,
                effective_mode="legacy",
                fallback_state="switch_off",
                fallback_count=0,
                model=model,
                retention_observability=inactive_retention.safe_observability(),
            ),
        )
    if route != _SUPPORTED_ROUTE or model not in _SUPPORTED_MODEL_IDENTIFIERS:
        reason = (
            "unsupported_route"
            if route != _SUPPORTED_ROUTE
            else "unsupported_model"
        )
        return ProductionPromptCacheAssembly(
            legacy_user_text=legacy_user_text,
            request_observability=_base_observability(
                configured_mode=configured_mode,
                effective_mode="legacy",
                fallback_state=reason,
                fallback_count=1,
                model=model,
                retention_observability=inactive_retention.safe_observability(),
            ),
        )

    # Tool definitions and tool-loop history are owned by the provider-agent
    # runtime. The initial House chat projection remains the same lossless
    # stable-prefix assembly and can be handed to that runtime unchanged.
    try:
        sections = _validated_sections(section_outputs)
        instructions, stable, dynamic, current = _partition_sections(
            sections,
            envelope=envelope,
        )
        if not instructions:
            raise ProductionPromptCacheError("instruction law is missing")
        neutral_request = _build_neutral_request(
            instructions=instructions,
            stable=stable,
            dynamic=dynamic,
            current=current,
            memory_authorship_protocol_version=(
                memory_authorship_protocol_version
            ),
            continuity_authorship_instruction=(
                continuity_authorship_instruction
            ),
            continuity_authorship_protocol_version=(
                continuity_authorship_protocol_version
            ),
            continuity_authorship_available=(
                continuity_authorship_available
            ),
            continuity_authorship_offer=continuity_authorship_offer,
        )
        projection = chat_serialization.build_no_live_chat_projection(
            neutral_request
        )
        chat_serialization.canonical_chat_endpoint_body(projection)
        prefix_sha256, prefix_bytes, stable_message_count = (
            _stable_projection_identity(projection)
        )
        semantic_sha256, semantic_count = _semantic_section_identity(sections)
    except Exception:
        return ProductionPromptCacheAssembly(
            legacy_user_text=legacy_user_text,
            request_observability=_base_observability(
                configured_mode=configured_mode,
                effective_mode="legacy",
                fallback_state="local_assembly_failed",
                fallback_count=1,
                model=model,
                retention_observability=inactive_retention.safe_observability(),
            ),
        )

    active_retention = retention_policy.decision_from_env(
        env=env,
        provider="openai_compatible",
        endpoint_family="chat_completions",
        model=model,
        stable_prefix_effective=True,
    )
    observability = _base_observability(
        configured_mode=configured_mode,
        effective_mode="stable_prefix",
        fallback_state="none",
        fallback_count=0,
        model=model,
        retention_observability=active_retention.safe_observability(),
    )
    observability.update(
        {
            "prefix_version": (
                f"{PRODUCTION_PREFIX_PROFILE}.{prefix_sha256[:16]}"
            ),
            "prefix_sha256": prefix_sha256,
            "stable_projection_utf8_bytes": prefix_bytes,
            "stable_message_count": stable_message_count,
            "semantic_equivalence": "lossless_selected_section_partition",
            "semantic_section_count": semantic_count,
            "semantic_section_sha256": semantic_sha256,
        }
    )
    return ProductionPromptCacheAssembly(
        legacy_user_text=legacy_user_text,
        chat_projection=projection,
        request_observability=observability,
    )


def _cached_field_reported(usage: Mapping[str, Any]) -> bool:
    presence = (
        usage.get("source_field_presence")
        if isinstance(usage.get("source_field_presence"), Mapping)
        else {}
    )
    return any(
        presence.get(key) is True
        for key in (
            "usage.prompt_tokens_details.cached_tokens",
            "usage.input_tokens_details.cached_tokens",
            "usage.cached_input_tokens",
        )
    )


def _provider_agent_cache_request_observability(
    adapter_response: Mapping[str, Any],
) -> dict[str, Any]:
    provider_agent = (
        adapter_response.get("provider_agent")
        if isinstance(adapter_response.get("provider_agent"), Mapping)
        else {}
    )
    value = (
        provider_agent.get("prompt_cache_request_observability")
        if isinstance(
            provider_agent.get("prompt_cache_request_observability"),
            Mapping,
        )
        else {}
    )
    if (
        value.get("schema_version")
        != "house_provider_agent_prompt_cache_request_observability_v1"
        or value.get("raw_provider_content_present") is not False
    ):
        return {}
    state = value.get("provider_prefix_identity_state")
    digest = value.get("provider_prefix_sha256")
    retention_field = value.get("provider_retention_field")
    retention_value = value.get("provider_retention_value")
    counts = (
        value.get("provider_prefix_utf8_bytes"),
        value.get("provider_stable_message_count"),
        value.get("provider_tool_definition_count"),
    )
    if (
        not isinstance(state, str)
        or _safe_label(state) != state
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or not isinstance(retention_field, str)
        or _safe_label(retention_field) != retention_field
        or not isinstance(retention_value, str)
        or _safe_label(retention_value) != retention_value
        or any(type(count) is not int or count < 0 for count in counts)
        or type(value.get("provider_prompt_cache_key_present")) is not bool
    ):
        return {}
    return {
        "provider_prefix_identity_state": state,
        "provider_prefix_sha256": digest,
        "provider_prefix_utf8_bytes": counts[0],
        "provider_stable_message_count": counts[1],
        "provider_tool_definition_count": counts[2],
        "provider_retention_field": retention_field,
        "provider_retention_value": retention_value,
        "provider_prompt_cache_key_present": value[
            "provider_prompt_cache_key_present"
        ],
    }


def finalize_adapter_observability(
    assembly: ProductionPromptCacheAssembly,
    adapter_response: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one field-closed raw-free production cache observation."""

    observation = dict(assembly.request_observability)
    raw_usage = (
        adapter_response.get("usage")
        if isinstance(adapter_response.get("usage"), Mapping)
        else None
    )
    try:
        usage = provider_observability.normalize_usage(
            raw_usage,
            endpoint_family="chat_completions",
            retain_details=True,
            source_usage_present=raw_usage is not None,
        )
    except (TypeError, ValueError):
        usage = provider_observability.normalize_usage(
            None,
            endpoint_family="chat_completions",
            retain_details=True,
            source_usage_present=False,
        )
    input_tokens = usage.get("input_tokens")
    cached_tokens = usage.get("cached_input_tokens")
    output_tokens = usage.get("output_tokens")
    if type(cached_tokens) is int and _cached_field_reported(usage):
        cache_state = (
            "reported_positive" if cached_tokens > 0 else "reported_zero"
        )
    else:
        cache_state = "unavailable"
        cached_tokens = None
    ratio = (
        round(cached_tokens / input_tokens, 6)
        if type(cached_tokens) is int
        and type(input_tokens) is int
        and input_tokens > 0
        and cached_tokens <= input_tokens
        else None
    )
    provider = (
        adapter_response.get("provider")
        if isinstance(adapter_response.get("provider"), Mapping)
        else {}
    )
    observation.update(
        {
            "model": _safe_label(
                provider.get("model"),
                fallback=observation.get("model") or "unknown",
            ),
            "provider_input_tokens": (
                input_tokens if type(input_tokens) is int else None
            ),
            "cached_input_tokens": cached_tokens,
            "output_tokens": (
                output_tokens if type(output_tokens) is int else None
            ),
            "cache_state": cache_state,
            "cached_input_ratio": ratio,
            "request_outcome": (
                "success" if adapter_response.get("ok") is True else "failed"
            ),
        }
    )
    observation.update(
        _provider_agent_cache_request_observability(adapter_response)
    )
    return safe_cache_observability(observation)


def attach_adapter_observability(
    assembly: ProductionPromptCacheAssembly,
    adapter_response: Mapping[str, Any],
) -> dict[str, Any]:
    result = dict(adapter_response)
    result["prompt_cache_observability"] = finalize_adapter_observability(
        assembly,
        adapter_response,
    )
    return result


def safe_cache_observability(value: Any) -> dict[str, Any]:
    """Validate and return the exact raw-free cache telemetry projection."""

    if not isinstance(value, Mapping) or set(value) != _OBSERVABILITY_FIELDS:
        raise ProductionPromptCacheError("cache observability fields are invalid")
    result = dict(value)
    if result.get("schema_version") != PRODUCTION_CACHE_OBSERVABILITY_VERSION:
        raise ProductionPromptCacheError("cache observability version is invalid")
    if result.get("feature_switch") != FEATURE_SWITCH_NAME:
        raise ProductionPromptCacheError("cache feature switch identity is invalid")
    for field_name in (
        "configured_mode",
        "effective_mode",
        "prefix_profile",
        "prefix_version",
        "prefix_sha256",
        "semantic_equivalence",
        "semantic_section_sha256",
        "model",
        "route",
        "cache_state",
        "local_assembly_fallback_state",
        "request_outcome",
        "retention_feature_switch",
        "retention_configured_mode",
        "retention_policy_state",
        "retention_request_field",
        "retention_requested_value",
        "provider_prefix_identity_state",
        "provider_prefix_sha256",
        "provider_retention_field",
        "provider_retention_value",
    ):
        value_text = result.get(field_name)
        if (
            not isinstance(value_text, str)
            or _safe_label(value_text) != value_text
        ):
            raise ProductionPromptCacheError(
                "cache observability label is invalid"
            )
    for field_name in (
        "prefix_sha256",
        "semantic_section_sha256",
        "provider_prefix_sha256",
    ):
        value_text = result[field_name]
        if value_text and (
            len(value_text) != 64
            or any(character not in "0123456789abcdef" for character in value_text)
        ):
            raise ProductionPromptCacheError(
                "cache observability digest is invalid"
            )
    if result["cache_state"] not in {
        "reported_positive",
        "reported_zero",
        "unavailable",
    }:
        raise ProductionPromptCacheError("cache state is invalid")
    if (
        result["retention_feature_switch"]
        != retention_policy.FEATURE_SWITCH_NAME
    ):
        raise ProductionPromptCacheError(
            "cache retention feature switch identity is invalid"
        )
    for field_name in (
        "stable_projection_utf8_bytes",
        "stable_message_count",
        "semantic_section_count",
        "local_assembly_fallback_count",
        "provider_prefix_utf8_bytes",
        "provider_stable_message_count",
        "provider_tool_definition_count",
    ):
        if type(result.get(field_name)) is not int or result[field_name] < 0:
            raise ProductionPromptCacheError(
                "cache observability count is invalid"
            )
    for field_name in (
        "provider_input_tokens",
        "cached_input_tokens",
        "output_tokens",
    ):
        if result.get(field_name) is not None and (
            type(result[field_name]) is not int or result[field_name] < 0
        ):
            raise ProductionPromptCacheError(
                "cache observability token count is invalid"
            )
    ratio = result.get("cached_input_ratio")
    if ratio is not None and (
        type(ratio) not in {int, float}
        or isinstance(ratio, bool)
        or ratio < 0
        or ratio > 1
    ):
        raise ProductionPromptCacheError("cached-input ratio is invalid")
    if type(result.get("provider_fallback")) is not bool:
        raise ProductionPromptCacheError("provider fallback flag is invalid")
    if type(result.get("provider_prompt_cache_key_present")) is not bool:
        raise ProductionPromptCacheError(
            "provider prompt-cache key flag is invalid"
        )
    return result


__all__ = [
    "FEATURE_SWITCH_NAME",
    "PRODUCTION_CACHE_DEFAULT_ENABLED",
    "PRODUCTION_CACHE_OBSERVABILITY_VERSION",
    "PRODUCTION_CACHE_SCHEMA_VERSION",
    "PRODUCTION_PREFIX_ASSEMBLY_VERSION",
    "PRODUCTION_PREFIX_PROFILE",
    "ProductionPromptCacheAssembly",
    "ProductionPromptCacheError",
    "assemble_production_prompt",
    "attach_adapter_observability",
    "configured_feature_mode",
    "finalize_adapter_observability",
    "safe_cache_observability",
]
