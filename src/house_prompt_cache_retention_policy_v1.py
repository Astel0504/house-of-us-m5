"""Model-aware provider prompt-cache retention for stable House requests.

This owner selects only reviewed request fields. It does not assemble prompts,
select models, call providers, or retain prompt content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping


POLICY_SCHEMA_VERSION = "house_prompt_cache_retention_policy_v1"
FEATURE_SWITCH_NAME = "HOUSE_PROMPT_CACHE_RETENTION_POLICY"
DEFAULT_ENABLED = True

_ON_VALUES = frozenset({"1", "true", "yes", "on", "enabled"})
_OFF_VALUES = frozenset({"0", "false", "no", "off", "disabled"})
_SUPPORTED_ENDPOINTS = frozenset({"chat_completions", "responses"})
_GPT_56_FAMILY_RE = re.compile(r"^gpt-5\.6(?:$|[-.])")
_EXTENDED_24H_FAMILY_RES = (
    re.compile(r"^gpt-5\.5(?:$|[-.])"),
    re.compile(r"^gpt-5\.4(?:$|[-.])"),
    re.compile(r"^gpt-5\.2(?:$|[-.])"),
    re.compile(r"^gpt-5\.1(?:$|[-.])"),
    re.compile(r"^gpt-5(?:$|-)"),
    re.compile(r"^gpt-4\.1(?:$|[-.])"),
)


def _canonical_model_family(model: str) -> str:
    if model == "openai/gpt-5.5":
        return "gpt-5.5"
    return model


@dataclass(frozen=True)
class PromptCacheRetentionDecision:
    configured_mode: str
    policy_state: str
    request_field: str = ""
    requested_value: str = ""
    request_fields: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def requested(self) -> bool:
        return bool(self.request_fields)

    def safe_observability(self) -> dict[str, Any]:
        return {
            "retention_feature_switch": FEATURE_SWITCH_NAME,
            "retention_configured_mode": self.configured_mode,
            "retention_policy_state": self.policy_state,
            "retention_request_field": self.request_field,
            "retention_requested_value": self.requested_value,
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


def _supports_extended_24h(model: str) -> bool:
    if _GPT_56_FAMILY_RE.match(model):
        return False
    return any(pattern.match(model) for pattern in _EXTENDED_24H_FAMILY_RES)


def decide_retention(
    *,
    provider: str,
    endpoint_family: str,
    model: str,
    stable_prefix_effective: bool,
    configured_mode: str,
    enabled: bool,
) -> PromptCacheRetentionDecision:
    clean_provider = str(provider or "").strip()
    clean_endpoint = str(endpoint_family or "").strip()
    clean_model = _canonical_model_family(str(model or "").strip())
    if not enabled:
        return PromptCacheRetentionDecision(configured_mode, "switch_off")
    if not stable_prefix_effective:
        return PromptCacheRetentionDecision(
            configured_mode,
            "stable_prefix_inactive",
        )
    if clean_provider != "openai_compatible":
        return PromptCacheRetentionDecision(
            configured_mode,
            "unsupported_provider",
        )
    if clean_endpoint not in _SUPPORTED_ENDPOINTS:
        return PromptCacheRetentionDecision(
            configured_mode,
            "unsupported_endpoint",
        )
    if _GPT_56_FAMILY_RE.match(clean_model):
        return PromptCacheRetentionDecision(
            configured_mode,
            "requested_model_supported_ttl",
            request_field="prompt_cache_options.ttl",
            requested_value="30m",
            request_fields={"prompt_cache_options": {"ttl": "30m"}},
        )
    if _supports_extended_24h(clean_model):
        return PromptCacheRetentionDecision(
            configured_mode,
            "requested_extended_24h",
            request_field="prompt_cache_retention",
            requested_value="24h",
            request_fields={"prompt_cache_retention": "24h"},
        )
    return PromptCacheRetentionDecision(
        configured_mode,
        "unsupported_model",
    )


def decision_from_env(
    *,
    env: Mapping[str, str] | None,
    provider: str,
    endpoint_family: str,
    model: str,
    stable_prefix_effective: bool,
) -> PromptCacheRetentionDecision:
    configured_mode, enabled = configured_feature_mode(env)
    return decide_retention(
        provider=provider,
        endpoint_family=endpoint_family,
        model=model,
        stable_prefix_effective=stable_prefix_effective,
        configured_mode=configured_mode,
        enabled=enabled,
    )


__all__ = [
    "DEFAULT_ENABLED",
    "FEATURE_SWITCH_NAME",
    "POLICY_SCHEMA_VERSION",
    "PromptCacheRetentionDecision",
    "configured_feature_mode",
    "decide_retention",
    "decision_from_env",
]
