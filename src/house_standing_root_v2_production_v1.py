"""Active production owner for the reviewed Standing Root V2 prompt surface.

This owner selects between the existing V1 prompt-cache assembly and the
reviewed Standing Root V2 production assembly.  It assembles and attests local
provider input only; provider transport, tool execution, response handling,
Memory writes, and route lifecycle remain with their existing owners.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import hashlib
import inspect
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import api_talk_card_envelope_v0 as api_talk_card_envelope
import house_prompt_cache_production_v1 as prompt_cache_production
import house_prompt_registry_budget_v0 as registry_budget
import house_prompt_registry_manifest_v0 as registry_manifest
import house_prompt_registry_state_v1 as registry_state
import house_provider_agent_live_runtime_v0 as provider_agent_runtime
import house_provider_chat_serialization_v0 as chat_serialization
import house_provider_tool_surface_v0 as provider_tool_surface
import living_footing_packet_v0 as living_footing
import provider_observability_v0 as provider_observability
import talk_memory_authorship_intent_v0 as memory_authorship


SCHEMA_VERSION = "house_standing_root_v2_production_v1"
FEATURE_SWITCH_NAME = "HOUSE_STANDING_ROOT_V2_PRODUCTION_ASSEMBLY"
V1_SELECTION_VALUE = "v1"
V2_SELECTION_VALUE = "v2"
# The logical route stays provider-neutral, while the selected provider may
# require its qualified model identifier.  Keep this allowlist narrow so a
# provider-qualified name cannot silently widen the approved V2 model.
APPROVED_V2_MODEL_IDENTIFIERS = frozenset({
    "gpt-5.5",
    "openai/gpt-5.5",
})
APPROVED_V2_ROUTE = "openai_compatible_chat_completions"

PRODUCTION_PREFIX_PROFILE = "house_prompt_cache_standing_root_v2_prefix_v1"
PRODUCTION_PREFIX_ASSEMBLY_VERSION = (
    "house_standing_root_v2_production_assembly_v1"
)
PRODUCTION_PREFIX_GENERATION = "house_standing_root_v2_generation_1"
PRODUCTION_PREFIX_SHA256 = (
    "bb81a210cbe8bff1d6477a83737cd2aa140c4a6afa627f4a26046b6254b2d680"
)
PRODUCTION_PREFIX_UTF8_BYTES = 43_114
PRODUCTION_PREFIX_VERSION = (
    "house_prompt_cache_standing_root_v2_prefix_v1.bb81a210cbe8bff1"
)
PRODUCTION_CACHE_KEY = (
    "house-pc-v1-bb81a210cbe8bff1d6477a83737cd2aa140c4a6a"
)
PRODUCTION_CACHE_RETENTION = "24h"
ROLLBACK_ASSEMBLY_VERSION = (
    prompt_cache_production.PRODUCTION_PREFIX_ASSEMBLY_VERSION
)

REPO_ROOT = Path(__file__).resolve().parent
REGISTRY_ROOT = REPO_ROOT / "house_standing_root_v2_registry_v0"
CONTEXT_CARD_ROOT = REGISTRY_ROOT / "context_cards"
INSTRUCTION_LAW_ATTESTATION_ROOT = (
    REPO_ROOT
    / "prompt_caching_gate4_synthetic_registry_v0"
    / "instruction_law"
)

STANDING_ROOT_SLOTS = (
    "house_solen_core",
    "house_solen_standing_profile",
    "house_astel_profile",
    "house_relationship_footing",
    "house_care_intervention_footing",
    "house_solen_voice",
    "house_runtime_orientation",
)
REVIEWED_BROWSER_TOOL_NAMES = (
    "browser_search",
    "browser_open",
    "browser_read",
    "browser_follow",
    "browser_screenshot",
    "browser_download",
)
REVIEWED_BROWSER_TOOL_IDENTITIES = frozenset(
    f"mcp/browser/{name}" for name in REVIEWED_BROWSER_TOOL_NAMES
)
V2_REVIEWED_READ_ONLY_CAPABILITIES: Mapping[
    str,
    Mapping[str, str],
] = {
    "browser": copy.deepcopy(
        provider_tool_surface.DEFAULT_REVIEWED_READ_ONLY_CAPABILITIES[
            "browser"
        ]
    )
}

_V1_VISIBLE_CARD_OWNERS = frozenset(
    {
        "soul_identity_card",
        "astel_profile_card",
        "style_profile_card",
        "adult_authentication_card",
    }
)
_V1_PROVIDER_SECTION_IDS = frozenset(
    {
        "solen_identity",
        "astel_profile",
        "style_profile",
        "relationship_adult_context",
    }
)
_LIVING_FOOTING_LIST_FIELDS = (
    "profile_footing_items",
    "core_memory_footing_items",
    "active_situation_memory_items",
    "current_room_footing",
    "recent_pattern_footing",
)
_LIVING_FOOTING_SINGLETON_FIELDS = (
    "active_task",
    "active_recall_target",
)
_V1_PROFILE_OWNER_SIGNATURES = frozenset(
    {
        ("profile_footing", "active_profile_configuration"),
        ("profile_preference", "active_profile_configuration"),
    }
)
_STANDING_ROOT_SOURCE_OWNERS = frozenset(
    {
        "house_standing_root_v2_registry_v0",
        "house_standing_root_v2_production_candidate_assembly_v1",
        PRODUCTION_PREFIX_ASSEMBLY_VERSION,
        PRODUCTION_PREFIX_PROFILE,
    }
)


class StandingRootV2ProductionError(ValueError):
    """Raised when the active V2 surface cannot be locally attested."""


@dataclass(frozen=True)
class ProductionPromptSelection:
    envelope: Mapping[str, Any] = field(repr=False)
    rendered_text: str = field(repr=False)
    section_metrics: tuple[Mapping[str, Any], ...] = field(repr=False)
    section_outputs: tuple[Mapping[str, Any], ...] = field(repr=False)
    prompt_cache_assembly: (
        prompt_cache_production.ProductionPromptCacheAssembly
    ) = field(repr=False)
    observability: Mapping[str, Any]
    reviewed_read_only_capabilities: (
        Mapping[str, Mapping[str, str]] | None
    ) = field(default=None, repr=False)

    @property
    def v2_active(self) -> bool:
        return self.observability.get("selected_assembly") == V2_SELECTION_VALUE


def configured_selection(
    env: Mapping[str, str] | None,
) -> tuple[str, str]:
    source = env if env is not None else {}
    raw = str(source.get(FEATURE_SWITCH_NAME) or "").strip().casefold()
    if not raw:
        return "default_v1", V1_SELECTION_VALUE
    if raw == V1_SELECTION_VALUE:
        return "explicit_v1", V1_SELECTION_VALUE
    if raw == V2_SELECTION_VALUE:
        return "explicit_v2", V2_SELECTION_VALUE
    return "invalid_v1", V1_SELECTION_VALUE


def v2_requested(env: Mapping[str, str] | None) -> bool:
    return configured_selection(env)[1] == V2_SELECTION_VALUE


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
        raise StandingRootV2ProductionError(
            "production stable surface is not canonically encodable"
        ) from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _standing_root_owner_slot(value: Mapping[str, Any]) -> str:
    for key in (
        "standing_root_slot",
        "stable_slot",
        "owner_slot",
        "provenance_slot",
    ):
        slot = value.get(key)
        if isinstance(slot, str) and slot:
            return slot
    return ""


def _standing_root_owned_living_item(value: Mapping[str, Any]) -> bool:
    if _standing_root_owner_slot(value) in STANDING_ROOT_SLOTS:
        return True
    source_owner = value.get("source_owner")
    if (
        isinstance(source_owner, str)
        and source_owner in _STANDING_ROOT_SOURCE_OWNERS
    ):
        return True
    signature = (
        str(value.get("source_class") or ""),
        str(value.get("authority") or ""),
    )
    return signature in _V1_PROFILE_OWNER_SIGNATURES


def prepare_production_envelope(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    """Remove V1 standing owners and root-owned dynamic footing by identity."""

    if not isinstance(envelope, Mapping):
        raise StandingRootV2ProductionError(
            "production envelope is malformed"
        )
    prepared = copy.deepcopy(dict(envelope))
    card_summary = (
        prepared.get("card_summary")
        if isinstance(prepared.get("card_summary"), Mapping)
        else {}
    )
    visible = card_summary.get("provider_visible_cards")
    if isinstance(visible, list):
        prepared["card_summary"] = {
            **dict(card_summary),
            "provider_visible_cards": [
                value
                for value in visible
                if value not in _V1_VISIBLE_CARD_OWNERS
            ],
        }

    living = (
        prepared.get("living_footing")
        if isinstance(prepared.get("living_footing"), Mapping)
        else None
    )
    if living is None:
        return prepared, 0
    packet = (
        living.get("packet")
        if isinstance(living.get("packet"), Mapping)
        else None
    )
    if packet is None:
        return prepared, 0

    filtered_packet = copy.deepcopy(dict(packet))
    excluded = 0
    for field_name in _LIVING_FOOTING_LIST_FIELDS:
        values = filtered_packet.get(field_name)
        if not isinstance(values, list):
            continue
        kept: list[Any] = []
        for value in values:
            if (
                isinstance(value, Mapping)
                and _standing_root_owned_living_item(value)
            ):
                excluded += 1
                continue
            kept.append(value)
        filtered_packet[field_name] = kept
    for field_name in _LIVING_FOOTING_SINGLETON_FIELDS:
        value = filtered_packet.get(field_name)
        if (
            isinstance(value, Mapping)
            and value
            and _standing_root_owned_living_item(value)
        ):
            filtered_packet[field_name] = {}
            excluded += 1

    rendered = living_footing.render_living_footing_provider_section(
        filtered_packet,
        max_chars=living_footing.PROVIDER_VISIBLE_HARD_MAX_CHARS,
    )
    prepared["living_footing"] = {
        **dict(living),
        "packet": filtered_packet,
        "rendered_preview": rendered,
        "provider_visible_render_attached": bool(rendered),
        "standing_root_v2_exclusion": {
            "schema_version": (
                "house_standing_root_v2_living_footing_exclusion_v0"
            ),
            "rule": "stable_slot_or_owner_provenance",
            "excluded_item_count": excluded,
            "provider_text_collision_used_as_owner_rule": False,
        },
    }
    return prepared, excluded


def _load_standing_roots() -> tuple[
    tuple[dict[str, Any], ...],
    tuple[str, ...],
]:
    try:
        state = registry_state.load_validated_registry_state(
            instruction_law_root=INSTRUCTION_LAW_ATTESTATION_ROOT.resolve(),
            context_card_root=CONTEXT_CARD_ROOT.resolve(),
            integrity_lock_path=REGISTRY_ROOT / "integrity_lock.json",
            epoch_manifest_path=REGISTRY_ROOT / "epoch_manifest.json",
            private_content_mode=(
                registry_manifest.PrivateContentMode.OWNER_AUTHORIZED_PRIVATE
            ),
        )
        selection = registry_budget.select_registry_entries(
            state.registries,
            policy=state.policy,
        )
    except Exception as exc:
        raise StandingRootV2ProductionError(
            "sealed Standing Root V2 registry did not re-attest"
        ) from exc
    slots = tuple(item.entry.slot_key for item in selection.context_cards)
    if slots != STANDING_ROOT_SLOTS or selection.omissions:
        raise StandingRootV2ProductionError(
            "Standing Root V2 selection is not exact"
        )
    sections = tuple(
        {
            "section_id": item.entry.slot_key,
            "section_class": "standing_root",
            "exactness": "exact",
            "update_frequency": "slowly_changing",
            "rendered_text": item.rendered_text,
        }
        for item in selection.context_cards
    )
    return sections, slots


def _root_paragraphs(rendered_text: str) -> tuple[str, ...]:
    _, separator, body = rendered_text.partition("\n")
    if not separator or not body:
        raise StandingRootV2ProductionError(
            "standing-root provider render is malformed"
        )
    return tuple(
        paragraph.strip()
        for paragraph in body.split("\n\n")
        if paragraph.strip()
    )


def _validate_dynamic_root_isolation(
    *,
    standing_roots: Sequence[Mapping[str, Any]],
    production_sections: Sequence[Mapping[str, Any]],
) -> None:
    dynamic_text = "\n\n".join(
        str(section.get("rendered_text") or "")
        for section in production_sections
        if section.get("section_id") != "current_input"
        and section.get("update_frequency") != "immutable_versioned"
    )
    for root in standing_roots:
        rendered = str(root.get("rendered_text") or "")
        label, _, _ = rendered.partition("\n")
        if label and label in dynamic_text:
            raise StandingRootV2ProductionError(
                "standing-root label was re-emitted in dynamic context"
            )
        if rendered and rendered in dynamic_text:
            raise StandingRootV2ProductionError(
                "standing-root body was re-emitted in dynamic context"
            )
        for paragraph in _root_paragraphs(rendered):
            if paragraph in dynamic_text:
                raise StandingRootV2ProductionError(
                    "standing-root paragraph was re-emitted in dynamic context"
                )


def _render_production_envelope(
    envelope: Mapping[str, Any],
    *,
    memory_authorship_enabled: bool,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    section_metrics: list[dict[str, Any]] = []
    section_outputs: list[dict[str, Any]] = []
    rendered_text = (
        api_talk_card_envelope.render_kouri_chat_completions_user_text(
            envelope,
            section_metrics=section_metrics,
            section_outputs=section_outputs,
        )
    )
    rendered_text = memory_authorship.append_provider_instruction(
        rendered_text,
        enabled=memory_authorship_enabled,
    )
    if memory_authorship_enabled:
        section_outputs.append(
            {
                "section_id": "memory_authorship_law",
                "section_class": "memory_authorship_law",
                "exactness": "exact",
                "update_frequency": "immutable_versioned",
                "rendered_text": (
                    memory_authorship.PROVIDER_VISIBLE_INSTRUCTION
                ),
            }
        )
        try:
            section_metrics.append(
                provider_observability.build_section_metric(
                    section_id="memory_authorship_law",
                    section_class="memory_authorship_law",
                    order=len(section_metrics),
                    rendered_text=(
                        memory_authorship.PROVIDER_VISIBLE_INSTRUCTION
                    ),
                    exactness="exact",
                    update_frequency="immutable_versioned",
                    selected_count=1,
                )
            )
        except Exception:
            pass
    return rendered_text, section_metrics, section_outputs


def _selection_observability(
    *,
    configured_mode: str,
    requested_assembly: str,
    selected_assembly: str,
    fallback_state: str,
    fallback_count: int,
    excluded_count: int = 0,
    tool_count: int = 0,
    validation_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    v2_active = selected_assembly == V2_SELECTION_VALUE
    activation_matches_request = requested_assembly == selected_assembly
    return {
        "schema_version": SCHEMA_VERSION,
        "feature_switch": FEATURE_SWITCH_NAME,
        "configured_mode": configured_mode,
        "requested_assembly": requested_assembly,
        "selected_assembly": selected_assembly,
        "activation_readiness": {
            "schema_version": (
                "house_standing_root_v2_production_activation_readiness_v1"
            ),
            "ok": activation_matches_request,
            "state": "ready" if activation_matches_request else "degraded",
            "requested_assembly": requested_assembly,
            "effective_assembly": selected_assembly,
            "invariant": "requested_assembly_equals_effective_assembly",
        },
        "active_prefix_assembly_version": (
            PRODUCTION_PREFIX_ASSEMBLY_VERSION
            if v2_active
            else ROLLBACK_ASSEMBLY_VERSION
        ),
        "active_prefix_profile": (
            PRODUCTION_PREFIX_PROFILE if v2_active else None
        ),
        "active_prefix_generation": (
            PRODUCTION_PREFIX_GENERATION if v2_active else None
        ),
        "active_prefix_version": (
            PRODUCTION_PREFIX_VERSION if v2_active else None
        ),
        "active_prefix_sha256": (
            PRODUCTION_PREFIX_SHA256 if v2_active else None
        ),
        "active_prefix_utf8_bytes": (
            PRODUCTION_PREFIX_UTF8_BYTES if v2_active else None
        ),
        "active_cache_key": PRODUCTION_CACHE_KEY if v2_active else None,
        "active_cache_retention": (
            PRODUCTION_CACHE_RETENTION if v2_active else None
        ),
        "rollback_assembly_version": ROLLBACK_ASSEMBLY_VERSION,
        "fallback_state": fallback_state,
        "fallback_count": fallback_count,
        "excluded_living_footing_item_count": excluded_count,
        "provider_tool_definition_count": tool_count,
        "v2_validation_receipt": (
            copy.deepcopy(dict(validation_receipt))
            if isinstance(validation_receipt, Mapping)
            else {
                "schema_version": (
                    "house_standing_root_v2_validation_receipt_v1"
                ),
                "stage": "not_requested",
                "error_code": "none",
                "raw_material_present": False,
            }
        ),
        "raw_provider_content_present": False,
    }


def _validation_receipt(
    exc: BaseException | None,
    *,
    stage: str = "complete",
    error_code: str = "none",
) -> dict[str, Any]:
    if exc is not None and error_code == "none":
        message = str(exc)
        mappings = {
            "V2 production model or route is not approved": (
                "route_selection",
                "model_or_route_mismatch",
            ),
            "V2 production requires the reviewed provider-agent tool route": (
                "tool_route",
                "tools_or_broker_unavailable",
            ),
            "V2 production requires the reviewed Memory-authorship route": (
                "memory_route",
                "memory_authorship_route_unavailable",
            ),
            "sealed Standing Root V2 registry did not re-attest": (
                "standing_roots",
                "root_registry_order_body_mismatch",
            ),
            "Standing Root V2 selection is not exact": (
                "standing_roots",
                "root_registry_order_body_mismatch",
            ),
            "Standing Root V2 order changed": (
                "standing_roots",
                "root_registry_order_body_mismatch",
            ),
            "standing-root label was re-emitted in dynamic context": (
                "dynamic_root_isolation",
                "dynamic_root_isolation_failure",
            ),
            "standing-root body was re-emitted in dynamic context": (
                "dynamic_root_isolation",
                "dynamic_root_isolation_failure",
            ),
            "standing-root paragraph was re-emitted in dynamic context": (
                "dynamic_root_isolation",
                "dynamic_root_isolation_failure",
            ),
            "V2 prompt assembly fell back before attestation": (
                "typed_assembly",
                "assembly_fallback",
            ),
            "production stable-message boundary is malformed": (
                "stable_message_boundary",
                "stable_message_boundary_mismatch",
            ),
            "reviewed production tool surface is not the six-tool set": (
                "tool_semantics",
                "tool_semantic_mismatch",
            ),
            "reviewed production tool surface could not be built": (
                "tool_semantics",
                "tool_semantic_mismatch",
            ),
            "production stable surface changed from the approved candidate": (
                "canonical_stable_surface",
                "canonical_stable_surface_mismatch",
            ),
            "exact serialized stable-message or tool identity changed": (
                "serialized_stable_identity",
                "exact_serialized_stable_message_tool_identity_mismatch",
            ),
            "provider-neutral continuity output-policy signature mismatch": (
                "typed_assembly_dependency",
                "assembly_dependency_signature_mismatch",
            ),
        }
        stage, error_code = mappings.get(
            message,
            ("unknown_internal", "unknown_internal_validation_failure"),
        )
    return {
        "schema_version": "house_standing_root_v2_validation_receipt_v1",
        "stage": stage,
        "error_code": error_code,
        "raw_material_present": False,
    }


def _v1_selection(
    *,
    envelope: Mapping[str, Any],
    env: Mapping[str, str] | None,
    model: str,
    route: str,
    tools_requested: bool,
    memory_authorship_enabled: bool,
    configured_mode: str,
    requested_assembly: str,
    fallback_state: str,
    fallback_count: int,
    validation_receipt: Mapping[str, Any] | None = None,
) -> ProductionPromptSelection:
    rendered, metrics, outputs = _render_production_envelope(
        envelope,
        memory_authorship_enabled=memory_authorship_enabled,
    )
    # Preserve the existing V1 assembly byte-for-byte.  In particular, do not
    # add V2 Memory-policy projection metadata to the rollback branch.
    assembly = prompt_cache_production.assemble_production_prompt(
        legacy_user_text=rendered,
        section_outputs=outputs,
        envelope=envelope,
        env=env,
        model=model,
        route=route,
        tools_requested=tools_requested,
    )
    if fallback_state != "none":
        assembly = (
            prompt_cache_production.ProductionPromptCacheAssembly(
                legacy_user_text=assembly.legacy_user_text,
                chat_projection=assembly.chat_projection,
                request_observability={
                    **dict(assembly.request_observability),
                    "local_assembly_fallback_state": fallback_state,
                    "local_assembly_fallback_count": fallback_count,
                },
            )
        )
    return ProductionPromptSelection(
        envelope=copy.deepcopy(dict(envelope)),
        rendered_text=rendered,
        section_metrics=tuple(copy.deepcopy(metrics)),
        section_outputs=tuple(copy.deepcopy(outputs)),
        prompt_cache_assembly=assembly,
        observability=_selection_observability(
            configured_mode=configured_mode,
            requested_assembly=requested_assembly,
            selected_assembly=V1_SELECTION_VALUE,
            fallback_state=fallback_state,
            fallback_count=fallback_count,
            validation_receipt=validation_receipt,
        ),
    )


def _projected_memory_authorship_available(
    projection_request: Mapping[str, Any],
) -> bool:
    messages = projection_request.get("messages")
    if not isinstance(messages, list):
        raise StandingRootV2ProductionError(
            "production messages are absent"
        )
    payloads: list[Mapping[str, Any]] = []
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content.startswith(
            "HOUSE_CHAT_DEVELOPER_V2\n"
        ):
            continue
        try:
            payload = json.loads(content.split("\n", 1)[1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise StandingRootV2ProductionError(
                "production developer message is malformed"
            ) from exc
        if isinstance(payload, Mapping):
            payloads.append(payload)
    if len(payloads) != 1:
        raise StandingRootV2ProductionError(
            "production developer policy owner is not singular"
        )
    output_policy_text = payloads[0].get("output_policy")
    if not isinstance(output_policy_text, str):
        raise StandingRootV2ProductionError(
            "production output policy projection is absent"
        )
    try:
        output_policy = json.loads(output_policy_text)
    except json.JSONDecodeError as exc:
        raise StandingRootV2ProductionError(
            "production output policy projection is malformed"
        ) from exc
    available = (
        output_policy.get("memory_authorship_available")
        if isinstance(output_policy, Mapping)
        else None
    )
    if type(available) is not bool:
        raise StandingRootV2ProductionError(
            "production Memory-authorship availability is malformed"
        )
    return available


def _reviewed_tool_definitions(broker: Any) -> list[dict[str, Any]]:
    try:
        surface = provider_tool_surface.build_provider_tool_surface(
            provider_family="openai",
            provider_endpoint="chat_completions",
            broker=broker,
            reviewed_read_only_capabilities=(
                V2_REVIEWED_READ_ONLY_CAPABILITIES
            ),
        )
    except Exception as exc:
        raise StandingRootV2ProductionError(
            "reviewed production tool surface could not be built"
        ) from exc
    tools = surface.get("tools")
    definitions = surface.get("provider_tool_definitions")
    identities = {
        str(item.get("tool_identity") or "")
        for item in tools
        if isinstance(item, Mapping)
    } if isinstance(tools, list) else set()
    if (
        identities != REVIEWED_BROWSER_TOOL_IDENTITIES
        or not isinstance(definitions, list)
        or len(definitions) != len(REVIEWED_BROWSER_TOOL_IDENTITIES)
    ):
        raise StandingRootV2ProductionError(
            "reviewed production tool surface is not the six-tool set"
        )
    return copy.deepcopy(definitions)


def _attest_full_stable_surface(
    assembly: prompt_cache_production.ProductionPromptCacheAssembly,
    *,
    model: str,
    tools: Sequence[Mapping[str, Any]],
) -> None:
    if assembly.chat_projection is None:
        raise StandingRootV2ProductionError(
            "V2 chat projection is absent"
        )
    projection_request = (
        chat_serialization.endpoint_request_from_chat_projection(
            assembly.chat_projection
        )
    )
    if not _projected_memory_authorship_available(projection_request):
        raise StandingRootV2ProductionError(
            "V2 Memory-authorship output policy is disabled"
        )
    messages = projection_request.get("messages")
    stable_count = assembly.request_observability.get(
        "stable_message_count"
    )
    if (
        not isinstance(messages, list)
        or type(stable_count) is not int
        or stable_count < 1
        or stable_count >= len(messages)
    ):
        raise StandingRootV2ProductionError(
            "production stable-message boundary is malformed"
        )
    provider_messages = [
        {
            "role": "system",
            "content": (
                provider_agent_runtime.TOOL_BRANCH_VISIBLE_ACK_INSTRUCTION
            ),
        },
        *copy.deepcopy(messages),
    ]
    provider_stable_count = stable_count + 1
    # OpenRouter's provider-qualified alias names the same reviewed GPT-5.5
    # model family.  Keep the already-approved stable prompt identity bound
    # to that canonical model family while the actual provider request retains
    # the qualified model name required by OpenRouter.
    stable_surface = {
        "model": (
            "gpt-5.5"
            if model == "openai/gpt-5.5"
            else model
        ),
        "messages": copy.deepcopy(
            provider_messages[:provider_stable_count]
        ),
        "tools": copy.deepcopy(list(tools)),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
    }
    stable_body = _canonical_sorted_bytes(stable_surface)
    if (
        len(stable_body) != PRODUCTION_PREFIX_UTF8_BYTES
        or _sha256(stable_body) != PRODUCTION_PREFIX_SHA256
    ):
        raise StandingRootV2ProductionError(
            "production stable surface changed from the approved candidate"
        )


def _v2_selection(
    *,
    envelope: Mapping[str, Any],
    env: Mapping[str, str] | None,
    model: str,
    route: str,
    tools_requested: bool,
    memory_authorship_enabled: bool,
    broker: Any,
    configured_mode: str,
) -> ProductionPromptSelection:
    if (
        model not in APPROVED_V2_MODEL_IDENTIFIERS
        or route != APPROVED_V2_ROUTE
    ):
        raise StandingRootV2ProductionError(
            "V2 production model or route is not approved"
        )
    if not tools_requested or broker is None:
        raise StandingRootV2ProductionError(
            "V2 production requires the reviewed provider-agent tool route"
        )
    if not memory_authorship_enabled:
        raise StandingRootV2ProductionError(
            "V2 production requires the reviewed Memory-authorship route"
        )
    output_policy_parameters = set(
        inspect.signature(
            prompt_cache_production.neutral.output_policy
        ).parameters
    )
    if not {
        "continuity_authorship_protocol_version",
        "continuity_authorship_available",
        "continuity_authorship_requires_turn_capability",
    }.issubset(output_policy_parameters):
        raise StandingRootV2ProductionError(
            "provider-neutral continuity output-policy signature mismatch"
        )

    prepared_envelope, excluded_count = prepare_production_envelope(
        envelope
    )
    rendered, metrics, production_sections = (
        _render_production_envelope(
            prepared_envelope,
            memory_authorship_enabled=True,
        )
    )
    section_ids = {
        str(value.get("section_id") or "")
        for value in production_sections
    }
    if section_ids & _V1_PROVIDER_SECTION_IDS:
        raise StandingRootV2ProductionError(
            "V1 card section survived Standing Root V2 replacement"
        )
    roots, slots = _load_standing_roots()
    if slots != STANDING_ROOT_SLOTS:
        raise StandingRootV2ProductionError(
            "Standing Root V2 order changed"
        )
    _validate_dynamic_root_isolation(
        standing_roots=roots,
        production_sections=production_sections,
    )
    combined_sections = [
        *[dict(value) for value in roots],
        *production_sections,
    ]
    assembly = prompt_cache_production.assemble_production_prompt(
        legacy_user_text=rendered,
        section_outputs=combined_sections,
        envelope=prepared_envelope,
        env=env,
        model=model,
        route=route,
        tools_requested=True,
        memory_authorship_protocol_version=memory_authorship.SCHEMA_VERSION,
    )
    if not assembly.stable_prefix_used:
        raise StandingRootV2ProductionError(
            "V2 prompt assembly fell back before attestation"
        )
    tools = _reviewed_tool_definitions(broker)
    _attest_full_stable_surface(
        assembly,
        model=model,
        tools=tools,
    )
    stable_count = assembly.request_observability.get(
        "stable_message_count"
    )
    request_observability = {
        **dict(assembly.request_observability),
        "prefix_profile": PRODUCTION_PREFIX_PROFILE,
        "prefix_version": PRODUCTION_PREFIX_VERSION,
        "prefix_sha256": PRODUCTION_PREFIX_SHA256,
        "stable_projection_utf8_bytes": PRODUCTION_PREFIX_UTF8_BYTES,
        "stable_message_count": stable_count,
    }
    attested_assembly = (
        prompt_cache_production.ProductionPromptCacheAssembly(
            legacy_user_text=assembly.legacy_user_text,
            chat_projection=assembly.chat_projection,
            request_observability=request_observability,
        )
    )
    return ProductionPromptSelection(
        envelope=prepared_envelope,
        rendered_text=rendered,
        section_metrics=tuple(copy.deepcopy(metrics)),
        section_outputs=tuple(copy.deepcopy(combined_sections)),
        prompt_cache_assembly=attested_assembly,
        observability=_selection_observability(
            configured_mode=configured_mode,
            requested_assembly=V2_SELECTION_VALUE,
            selected_assembly=V2_SELECTION_VALUE,
            fallback_state="none",
            fallback_count=0,
            excluded_count=excluded_count,
            tool_count=len(tools),
            validation_receipt=_validation_receipt(None),
        ),
        reviewed_read_only_capabilities=copy.deepcopy(
            V2_REVIEWED_READ_ONLY_CAPABILITIES
        ),
    )


def select_production_prompt(
    *,
    envelope: Mapping[str, Any],
    env: Mapping[str, str] | None,
    model: str,
    route: str,
    tools_requested: bool,
    memory_authorship_enabled: bool,
    broker: Any = None,
) -> ProductionPromptSelection:
    """Select and locally attest V2, or preserve immediate V1 rollback."""

    configured_mode, requested = configured_selection(env)
    if requested != V2_SELECTION_VALUE:
        fallback_state = (
            "invalid_switch"
            if configured_mode == "invalid_v1"
            else "none"
        )
        return _v1_selection(
            envelope=envelope,
            env=env,
            model=model,
            route=route,
            tools_requested=tools_requested,
            memory_authorship_enabled=memory_authorship_enabled,
            configured_mode=configured_mode,
            requested_assembly=requested,
            fallback_state=fallback_state,
            fallback_count=1 if fallback_state != "none" else 0,
        )
    try:
        return _v2_selection(
            envelope=envelope,
            env=env,
            model=model,
            route=route,
            tools_requested=tools_requested,
            memory_authorship_enabled=memory_authorship_enabled,
            broker=broker,
            configured_mode=configured_mode,
        )
    except Exception as exc:
        return _v1_selection(
            envelope=envelope,
            env=env,
            model=model,
            route=route,
            tools_requested=tools_requested,
            memory_authorship_enabled=memory_authorship_enabled,
            configured_mode=configured_mode,
            requested_assembly=V2_SELECTION_VALUE,
            fallback_state="v2_validation_failed",
            fallback_count=1,
            validation_receipt=_validation_receipt(exc),
        )


__all__ = [
    "FEATURE_SWITCH_NAME",
    "PRODUCTION_CACHE_KEY",
    "PRODUCTION_CACHE_RETENTION",
    "PRODUCTION_PREFIX_ASSEMBLY_VERSION",
    "PRODUCTION_PREFIX_GENERATION",
    "PRODUCTION_PREFIX_PROFILE",
    "PRODUCTION_PREFIX_SHA256",
    "PRODUCTION_PREFIX_UTF8_BYTES",
    "PRODUCTION_PREFIX_VERSION",
    "ProductionPromptSelection",
    "REVIEWED_BROWSER_TOOL_IDENTITIES",
    "REVIEWED_BROWSER_TOOL_NAMES",
    "ROLLBACK_ASSEMBLY_VERSION",
    "SCHEMA_VERSION",
    "STANDING_ROOT_SLOTS",
    "StandingRootV2ProductionError",
    "V1_SELECTION_VALUE",
    "V2_REVIEWED_READ_ONLY_CAPABILITIES",
    "V2_SELECTION_VALUE",
    "configured_selection",
    "prepare_production_envelope",
    "select_production_prompt",
    "v2_requested",
]
