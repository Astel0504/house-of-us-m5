"""Reversible provider prompt-cache routing keys for stable House requests.

The key is derived only from House's existing stable-prefix SHA-256 identity.
This owner does not inspect or retain prompt content, assemble requests, select
models, call providers, or change cache-retention policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


POLICY_SCHEMA_VERSION = "house_prompt_cache_key_policy_v1"
FEATURE_SWITCH_NAME = "HOUSE_PROMPT_CACHE_KEY_POLICY"
DEFAULT_ENABLED = True
KEY_NAMESPACE = "house-pc-v1"
KEY_DIGEST_CHARS = 40

_ON_VALUES = frozenset({"1", "true", "yes", "on", "enabled"})
_OFF_VALUES = frozenset({"0", "false", "no", "off", "disabled"})
_SUPPORTED_ENDPOINTS = frozenset({"chat_completions"})
_LOWER_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class PromptCacheKeyDecision:
    configured_mode: str
    policy_state: str
    request_fields: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def requested(self) -> bool:
        return bool(self.request_fields)

    def safe_observability(self) -> dict[str, Any]:
        return {
            "cache_key_feature_switch": FEATURE_SWITCH_NAME,
            "cache_key_configured_mode": self.configured_mode,
            "cache_key_policy_state": self.policy_state,
            "cache_key_requested": self.requested,
        }


def configured_feature_mode(
    env: Mapping[str, str] | None,
) -> tuple[str, bool]:
    source = env if env is not None else {}
    raw = str(source.get(FEATURE_SWITCH_NAME) or "").strip().casefold()
    if not raw:
        return (
            "default_on" if DEFAULT_ENABLED else "default_off",
            DEFAULT_ENABLED,
        )
    if raw in _ON_VALUES:
        return "explicit_on", True
    if raw in _OFF_VALUES:
        return "explicit_off", False
    return "invalid_off", False


def _valid_prefix_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _LOWER_HEX for character in value)
    )


def decide_cache_key(
    *,
    provider: str,
    endpoint_family: str,
    stable_prefix_effective: bool,
    prefix_sha256: Any,
    configured_mode: str,
    enabled: bool,
) -> PromptCacheKeyDecision:
    if not enabled:
        return PromptCacheKeyDecision(configured_mode, "switch_off")
    if not stable_prefix_effective:
        return PromptCacheKeyDecision(
            configured_mode,
            "stable_prefix_inactive",
        )
    if str(provider or "").strip() != "openai_compatible":
        return PromptCacheKeyDecision(
            configured_mode,
            "unsupported_provider",
        )
    if str(endpoint_family or "").strip() not in _SUPPORTED_ENDPOINTS:
        return PromptCacheKeyDecision(
            configured_mode,
            "unsupported_endpoint",
        )
    if not _valid_prefix_sha256(prefix_sha256):
        return PromptCacheKeyDecision(
            configured_mode,
            "prefix_identity_unavailable",
        )
    return PromptCacheKeyDecision(
        configured_mode,
        "requested_stable_prefix_key",
        request_fields={
            "prompt_cache_key": (
                f"{KEY_NAMESPACE}-{prefix_sha256[:KEY_DIGEST_CHARS]}"
            )
        },
    )


def decision_from_env(
    *,
    env: Mapping[str, str] | None,
    provider: str,
    endpoint_family: str,
    stable_prefix_effective: bool,
    prefix_sha256: Any,
) -> PromptCacheKeyDecision:
    configured_mode, enabled = configured_feature_mode(env)
    return decide_cache_key(
        provider=provider,
        endpoint_family=endpoint_family,
        stable_prefix_effective=stable_prefix_effective,
        prefix_sha256=prefix_sha256,
        configured_mode=configured_mode,
        enabled=enabled,
    )


__all__ = [
    "DEFAULT_ENABLED",
    "FEATURE_SWITCH_NAME",
    "KEY_DIGEST_CHARS",
    "KEY_NAMESPACE",
    "POLICY_SCHEMA_VERSION",
    "PromptCacheKeyDecision",
    "configured_feature_mode",
    "decide_cache_key",
    "decision_from_env",
]
