"""Stable provider law for Solen-authored transient continuity.

This local Gate-6 owner defines text and protocol identity only. It does not
issue capabilities, parse responses, prepare commands, call a provider, or
enter a standing-live route.
"""

from __future__ import annotations


SCHEMA_VERSION = "talk_continuity_authorship_intent_v1"
PROTOCOL_VERSION = "house_continuity_private_carrier_v1_2"
OPEN_TAG = "<house-continuity-intent>"
CLOSE_TAG = "</house-continuity-intent>"

PROVIDER_VISIBLE_INSTRUCTION = """Continuity authorship option:
When House's current dynamic context contains an offered continuity capability, first inspect that exact offer. If it contains coverage_decision_required=true, House is asking you to exercise your own continuity judgment on this turn: after your complete natural reply, append exactly one private terminal continuity carrier and choose semantic_operations when you judge that the offered context should carry a delta, or no_semantic_delta when you judge that it should not. Requiring the carrier records that a choice was made; it does not require a semantic delta, and the judgment and authorship remain yours alone. For an offer without coverage_decision_required=true, you may deliberately append one carrier, and include no carrier when you do not choose to make that judgment. Copy the offered capability exactly and use the offered command context only. Never claim Astel or joint authorship. Do not put Memory, self-state, exact evidence or wording, action authority, tool permission, secrets, or raw conversation text in the carrier. Use <house-continuity-intent> followed by the exact canonical JSON required by the offer and </house-continuity-intent>. If you also choose the separate optional Memory carrier, place the continuity carrier immediately before Memory, which remains final. House removes private carriers before visible delivery. Keep the ordinary visible response natural and complete without mentioning this protocol."""


__all__ = [
    "CLOSE_TAG",
    "OPEN_TAG",
    "PROTOCOL_VERSION",
    "PROVIDER_VISIBLE_INSTRUCTION",
    "SCHEMA_VERSION",
]
