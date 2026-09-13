"""Stable-generation identity contracts for Continuity V1.2."""

from __future__ import annotations

from _house_continuity_v1_2_contract_primitives_v0 import *

GENERATION_IDENTITY_SCHEMA_VERSION = (
    "house_continuity_generation_2_identity_evidence_v1"
)

def derived_house_cache_signature(
    *,
    generation: str,
    profile: str,
    semantic_sha256: str,
    stable_messages_sha256: str,
    tool_block_sha256: str,
    tool_count: int,
) -> str:
    return canonical_sha256(
        {
            "algorithm": "house_cache_signature_v1",
            "generation": _string(
                generation, name="generation", maximum=160
            ),
            "profile": _string(profile, name="profile", maximum=160),
            "semantic_sha256": _hash(
                semantic_sha256, name="semantic_sha256"
            ),
            "stable_messages_sha256": _hash(
                stable_messages_sha256, name="stable_messages_sha256"
            ),
            "tool_block_sha256": _hash(
                tool_block_sha256, name="tool_block_sha256"
            ),
            "tool_count": _integer(
                tool_count, name="tool_count", minimum=1
            ),
        }
    )

def _byte_identity(value: Any, *, path: str) -> dict[str, Any]:
    raw = _exact(value, ("utf8_bytes", "sha256"), path=path)
    return {
        "utf8_bytes": _integer(
            raw["utf8_bytes"], name=f"{path}_utf8_bytes", minimum=1
        ),
        "sha256": _hash(raw["sha256"], name=f"{path}_sha256"),
    }

def validate_generation_identity_evidence(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "evidence_scope",
            "generation",
            "profile",
            "canonical_semantic_stable_surface",
            "serialized_stable_messages",
            "serialized_tool_block",
            "house_cache_signature",
            "semantic_equality_proves_wire_byte_equality",
            "tool_order_preserved",
            "tool_order_normalized",
            "provider_call_made",
            "prefix_generation_2_generated",
        ),
        path="generation_identity_evidence",
    )
    if raw["schema_version"] != GENERATION_IDENTITY_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported identity evidence.")
    if raw["evidence_scope"] != "synthetic_gate0_contract":
        _error("invalid_evidence_scope", "Only synthetic evidence is allowed.")
    if raw["generation"] != "house_standing_root_v2_generation_2":
        _error("invalid_generation", "Generation identity differs.")
    if raw["profile"] != "house_prompt_cache_standing_root_v2_prefix_v1":
        _error("invalid_profile", "Cache profile differs.")
    semantic = _byte_identity(
        raw["canonical_semantic_stable_surface"],
        path="canonical_semantic_stable_surface",
    )
    messages = _byte_identity(
        raw["serialized_stable_messages"],
        path="serialized_stable_messages",
    )
    tools_raw = _exact(
        raw["serialized_tool_block"],
        ("utf8_bytes", "sha256", "tool_count"),
        path="serialized_tool_block",
    )
    tools = {
        "utf8_bytes": _integer(
            tools_raw["utf8_bytes"], name="tool_utf8_bytes", minimum=1
        ),
        "sha256": _hash(tools_raw["sha256"], name="tool_sha256"),
        "tool_count": _integer(
            tools_raw["tool_count"], name="tool_count", minimum=1
        ),
    }
    signature_raw = _exact(
        raw["house_cache_signature"],
        ("algorithm", "value"),
        path="house_cache_signature",
    )
    if signature_raw["algorithm"] != "house_cache_signature_v1":
        _error(
            "invalid_cache_signature_algorithm",
            "Cache signature algorithm differs.",
        )
    expected_signature = derived_house_cache_signature(
        generation=raw["generation"],
        profile=raw["profile"],
        semantic_sha256=semantic["sha256"],
        stable_messages_sha256=messages["sha256"],
        tool_block_sha256=tools["sha256"],
        tool_count=tools["tool_count"],
    )
    if signature_raw["value"] != expected_signature:
        _error("cache_signature_mismatch", "Cache signature differs.")
    for field in (
        "semantic_equality_proves_wire_byte_equality",
        "tool_order_normalized",
        "provider_call_made",
        "prefix_generation_2_generated",
    ):
        if raw[field] is not False:
            _error(f"invalid_{field}", f"{field} must remain false.")
    if raw["tool_order_preserved"] is not True:
        _error("tool_order_not_preserved", "Current tool order must remain.")
    return {
        "schema_version": GENERATION_IDENTITY_SCHEMA_VERSION,
        "evidence_scope": "synthetic_gate0_contract",
        "generation": raw["generation"],
        "profile": raw["profile"],
        "canonical_semantic_stable_surface": semantic,
        "serialized_stable_messages": messages,
        "serialized_tool_block": tools,
        "house_cache_signature": {
            "algorithm": "house_cache_signature_v1",
            "value": expected_signature,
        },
        "semantic_equality_proves_wire_byte_equality": False,
        "tool_order_preserved": True,
        "tool_order_normalized": False,
        "provider_call_made": False,
        "prefix_generation_2_generated": False,
    }

__all__ = [
    "GENERATION_IDENTITY_SCHEMA_VERSION",
    "derived_house_cache_signature",
    "_byte_identity",
    "validate_generation_identity_evidence",
]
