"""Raw-free provider usage, header, causal, and section observability helpers.

This module never owns provider bodies. Exact request and response bytes remain
in Provider Trace Vault; the helpers here retain only reviewed numeric facts,
safe labels, and field-presence evidence.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence


LEGACY_USAGE_SCHEMA_VERSION = "house_provider_usage_observability_v0"
USAGE_SCHEMA_VERSION = "house_provider_usage_observability_v1"
HEADER_SCHEMA_VERSION = "house_provider_safe_response_headers_v0"
CAUSAL_SCHEMA_VERSION = "house_provider_causal_linkage_v0"
SECTION_METRICS_SCHEMA_VERSION = "house_flattened_provider_section_metrics_v0"
TRACE_OBSERVABILITY_SCHEMA_VERSION = "house_provider_trace_observability_v0"
LEGACY_ADAPTER_OBSERVABILITY_SCHEMA_VERSION = "house_provider_adapter_observability_v0"
ADAPTER_OBSERVABILITY_SCHEMA_VERSION = "house_provider_adapter_observability_v1"
LEGACY_SAFE_LOG_OBSERVABILITY_SCHEMA_VERSION = "house_provider_safe_log_observability_v0"
SAFE_LOG_OBSERVABILITY_SCHEMA_VERSION = "house_provider_safe_log_observability_v1"

TOKEN_ESTIMATOR_VERSION = "utf8_byte_upper_bound_v0"
CURRENT_REQUEST_MODEL_VERSION = "flattened_chat_single_user_v0"
FLATTENED_SECTION_JOINER = "\n\n"

_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,179}")
_SAFE_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+/-]{0,179}")
_SAFE_REASON_RE = re.compile(r"[a-z][a-z0-9_]{0,79}")
_GATEWAY_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_FINAL_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+/-]{0,127}")
_ATTEMPT_REASONS = frozenset({"initial", "tool_followup"})
_REQUEST_OBSERVABILITY_STATES = frozenset(
    {"trace_request_owned", "compact_runtime_only", "unavailable"}
)
_RESPONSE_OBSERVABILITY_STATES = frozenset(
    {"trace_response_owned", "compact_runtime_only", "unavailable"}
)
_HELPER_TOTAL_STATES = frozenset({"causal_linkage_available_not_aggregated"})
# Gate 1.1 retains complete per-attempt causal linkage only. Helper-inclusive
# read-time aggregation is deferred, and must exist before the bounded live
# cache/cost experiment; this module deliberately creates no aggregate store.
_OUTPUT_LIMIT_STATES = frozenset({"advisory_not_sent", "endpoint_dependent"})
_CAUSAL_LINKAGE_STATES = frozenset(
    {"trace_causal_linkage_owned", "compact_runtime_only", "unavailable"}
)
_USAGE_DIAGNOSTICS = frozenset(
    {
        "invalid_normalized_usage",
        "invalid_usage_field_values",
        "conflicting_usage_aliases",
        "unknown_usage_fields_present",
        "unknown_usage_shape",
        "usage_present_empty",
    }
)
_HEADER_DIAGNOSTICS = frozenset(
    {
        "allowed_header_value_rejected",
        "header_iteration_failed",
        "header_parsing_failed",
        "malformed_response_headers",
    }
)
_RESPONSE_DIAGNOSTICS = frozenset(
    {"non_object_response_envelope", "response_usage_unavailable"}
)

_PURPOSES = frozenset(
    {
        "main_talk",
        "provider_agent_leg",
        "activity_intent",
        "self_state_emotional_evidence",
        "provider_helper",
        "legacy_unspecified",
    }
)
_PROVENANCE_CLASSES = frozenset(
    {
        "flattened_house_context",
        "current_talk_turn",
        "provider_agent_history",
        "activity_intent_input",
        "completed_turn_evidence",
        "legacy_unspecified",
    }
)
_OUTPUT_DESTINATIONS = frozenset(
    {
        "talk_response",
        "provider_agent_loop",
        "activity_intent_event",
        "self_state_evidence",
        "legacy_unspecified",
    }
)

_SECTION_EXACTNESS = frozenset({"exact", "derived", "mixed"})
_UPDATE_FREQUENCIES = frozenset(
    {
        "immutable_versioned",
        "slowly_changing",
        "append_only",
        "per_session",
        "per_turn",
        "live_dynamic",
    }
)
_MINIMUM_SECTION_CLASSES = (
    "recent_exact_current_session",
    "earlier_room_throughline",
    "standing_quiet_relationship_footing",
    "vault_memory_recall",
    "timeline_source_attachment",
    "current_input",
    "response_format_law",
    "memory_authorship_law",
)
_LEADING_PREFIX_FREQUENCIES = frozenset({"immutable_versioned", "slowly_changing"})
_SECTION_IDS = frozenset(
    {
        "active_room_throughline",
        "astel_profile",
        "context_footing_law",
        "current_audio",
        "current_house_talk_room",
        "current_input",
        "current_message_affect",
        "current_situation",
        "earlier_house_talk_continuity",
        "earlier_house_talk_continuity_background",
        "living_footing",
        "memory_authorship_law",
        "memory_context",
        "read_mode_exact_text",
        "read_mode_source_context",
        "recent_visible_exchange",
        "relationship_adult_context",
        "response_format_law",
        "short_term_continuity",
        "solen_identity",
        "style_profile",
        "thread_summary",
        "timeline_evidence",
        "turn_context",
        "vault_recall",
    }
)

_KNOWN_USAGE_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "source_endpoint_family",
        "source_usage_present",
        "source_field_presence",
        "input_tokens",
        "prompt_tokens",
        "output_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_tokens_details",
        "input_tokens_details",
        "completion_tokens_details",
        "output_tokens_details",
        "cached_input_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "cache_hit",
        "estimated_cost",
        "provider_reported_cost",
        "currency",
        "house_computed_cost",
        "tariff_id",
        "tariff_effective_date",
        "unpriced_token_classes",
        "diagnostic_codes",
        "unknown_field_count",
    }
)
_LEGACY_USAGE_PRESENCE_FIELDS = frozenset(
    {
        "usage.prompt_tokens",
        "usage.prompt_tokens_details.cached_tokens",
        "usage.prompt_tokens_details.cache_write_tokens",
        "usage.completion_tokens",
        "usage.completion_tokens_details.reasoning_tokens",
        "usage.input_tokens",
        "usage.input_tokens_details.cached_tokens",
        "usage.input_tokens_details.cache_write_tokens",
        "usage.output_tokens",
        "usage.output_tokens_details.reasoning_tokens",
        "usage.total_tokens",
        "usage.estimated_cost",
        "usage.currency",
    }
)
_KNOWN_USAGE_PRESENCE_FIELDS = frozenset(
    set(_LEGACY_USAGE_PRESENCE_FIELDS)
    | {
        "usage.cached_input_tokens",
        "usage.cache_write_tokens",
        "usage.reasoning_tokens",
    }
)

_USAGE_SCHEMA_FIELDS = frozenset(
    {
        "schema_version",
        "source_endpoint_family",
        "source_usage_present",
        "source_field_presence",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "estimated_cost",
        "currency",
        "cached_input_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "cache_hit",
        "provider_reported_cost",
        "house_computed_cost",
        "tariff_id",
        "tariff_effective_date",
        "unpriced_token_classes",
        "diagnostic_codes",
        "unknown_field_count",
    }
)
_LEGACY_USAGE_SCHEMA_FIELDS = _USAGE_SCHEMA_FIELDS - {"source_usage_present"}
_HEADER_SCHEMA_FIELDS = frozenset(
    {
        "schema_version",
        "fields_present",
        "gateway_request_id",
        "final_model",
        "fallback",
        "diagnostic_codes",
    }
)
_CAUSAL_SCHEMA_FIELDS = frozenset(
    {
        "schema_version",
        "house_turn_id",
        "parent_trace_id",
        "operation_id",
        "purpose",
        "input_provenance_classes",
        "output_destination_class",
        "attempt_number",
        "attempt_reason",
        "provider_profile",
        "client_model_label",
        "endpoint_family",
    }
)
_SECTION_METRIC_FIELDS = frozenset(
    {
        "section_id",
        "section_class",
        "order",
        "characters_after_provider_safety",
        "utf8_bytes",
        "token_estimate",
        "token_estimator_version",
        "exactness",
        "update_frequency",
        "selected_item_count",
        "omitted_item_count",
        "reason_counts",
        "provider_visible_role_destination",
    }
)
_CLASS_SUMMARY_FIELDS = frozenset(
    {
        "present_section_count",
        "selected_item_count",
        "omitted_item_count",
        "characters_after_provider_safety",
        "utf8_bytes",
        "token_estimate",
    }
)
_LEGACY_REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "request_model_version",
        "raw_free",
        "provider_visible_role_destination",
        "section_count",
        "sections",
        "section_class_summary",
        "prompt_characters_after_provider_safety",
        "prompt_utf8_bytes",
        "total_input_token_estimate",
        "token_estimator_version",
        "estimated_reusable_leading_prefix_characters",
        "estimated_reusable_leading_prefix_utf8_bytes",
        "estimated_reusable_leading_prefix_tokens",
        "dynamic_before_stable",
        "late_stable_law_excluded_from_leading_prefix",
        "body_text_returned",
        "message_ids_returned",
        "body_hashes_returned",
        "private_paths_returned",
        "request_body_utf8_bytes",
    }
)
_REQUEST_FIELDS = frozenset(
    (_LEGACY_REQUEST_FIELDS - {
        "estimated_reusable_leading_prefix_characters",
        "estimated_reusable_leading_prefix_utf8_bytes",
    })
    | {
        "known_inter_section_framing_characters",
        "known_inter_section_framing_utf8_bytes",
        "unattributed_residual_characters",
        "unattributed_residual_utf8_bytes",
        "reusable_leading_prefix_characters",
        "reusable_leading_prefix_utf8_bytes",
    }
)
_RESPONSE_FIELDS = frozenset(
    {
        "http_status",
        "response_bytes",
        "transport_latency_ms",
        "finish_reason",
        "safe_response_headers",
        "usage",
        "diagnostic_codes",
    }
)
_ADAPTER_COMPACT_FIELDS = frozenset(
    {
        "schema_version",
        "raw_free",
        "request_model_version",
        "endpoint_family",
        "provider_profile",
        "client_model_label",
        "final_model_header",
        "fallback_observation",
        "gateway_request_id",
        "source_usage_present",
        "cache_read_field_present",
        "cache_write_field_present",
        "cache_fields_present",
        "cached_input_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "returned_cache_hit",
        "request_body_utf8_bytes",
        "response_bytes",
        "http_status",
        "adapter_latency_ms",
        "finish_reason",
        "ok",
        "provider_call_made",
        "house_retry_count",
        "house_retry_reasons",
        "helper_inclusive_totals_state",
        "output_token_limit_state",
        "request_observability_state",
        "response_observability_state",
        "causal_linkage_state",
    }
)
_LEGACY_ADAPTER_COMPACT_FIELDS = _ADAPTER_COMPACT_FIELDS - {
    "cache_read_field_present",
    "cache_write_field_present",
}
_LEGACY_ADAPTER_FIELDS = frozenset(
    {
        "schema_version",
        "raw_free",
        "request_model_version",
        "endpoint_family",
        "provider_profile",
        "client_model_label",
        "final_model_header",
        "fallback_observation",
        "gateway_request_id",
        "safe_response_headers",
        "usage",
        "cache_fields_present",
        "cached_input_tokens",
        "cache_write_tokens",
        "returned_cache_hit",
        "request_body_utf8_bytes",
        "response_bytes",
        "http_status",
        "adapter_latency_ms",
        "finish_reason",
        "ok",
        "provider_call_made",
        "house_retry_count",
        "house_retry_reasons",
        "helper_inclusive_totals_state",
        "output_token_limit_state",
        "request_observability",
    }
)
_TRACE_FIELDS = frozenset({"schema_version", "request", "response", "adapter"})


def _nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _nonnegative_number(value: Any) -> int | float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        return None
    return value


def _safe_id(value: Any, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ValueError("unsafe observability identifier")
    return value


def _safe_label(value: Any, *, fallback: str = "legacy_unspecified") -> str:
    if isinstance(value, str) and _SAFE_LABEL_RE.fullmatch(value) and "://" not in value:
        return value
    return fallback


def _require_exact_fields(
    value: Mapping[str, Any],
    *,
    required: frozenset[str] | set[str],
    optional: frozenset[str] | set[str] = frozenset(),
    schema_name: str,
) -> None:
    keys = set(value)
    missing = set(required) - keys
    unknown = keys - set(required) - set(optional)
    if missing or unknown:
        raise ValueError(f"{schema_name} fields are not closed")


def _require_bool(value: Any, *, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} must be a boolean")
    return value


def _require_optional_bool(value: Any, *, field: str) -> bool | None:
    if value is None:
        return None
    return _require_bool(value, field=field)


def _require_nonnegative_int(value: Any, *, field: str, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    selected = _nonnegative_int(value)
    if selected is None:
        raise ValueError(f"{field} must be a nonnegative integer")
    return selected


def _require_optional_number(value: Any, *, field: str) -> int | float | None:
    if value is None:
        return None
    selected = _nonnegative_number(value)
    if selected is None:
        raise ValueError(f"{field} must be a nonnegative finite number")
    return selected


def _require_label(value: Any, *, field: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or _safe_label(value, fallback="") != value:
        raise ValueError(f"{field} must be a reviewed safe label")
    return value


def _require_reason_list(
    value: Any,
    *,
    field: str,
    limit: int,
    allowed: frozenset[str] | None = None,
) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{field} must be a bounded reason list")
    if any(not isinstance(item, str) or not _SAFE_REASON_RE.fullmatch(item) for item in value):
        raise ValueError(f"{field} contains an invalid reason")
    if allowed is not None and any(item not in allowed for item in value):
        raise ValueError(f"{field} contains an unreviewed reason")
    return list(value)


def _require_http_status(value: Any, *, optional: bool = True) -> int | None:
    if value is None and optional:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 100 <= value <= 599:
        raise ValueError("http_status must be null or between 100 and 599")
    return value


def usage_empty() -> dict[str, Any]:
    """Return the legacy-compatible empty usage projection."""
    return {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "estimated_cost": None,
        "currency": None,
    }


def _nested_int(value: Mapping[str, Any], parent: str, child: str) -> tuple[int | None, bool]:
    nested = value.get(parent)
    if not isinstance(nested, Mapping) or child not in nested:
        return None, False
    return _nonnegative_int(nested.get(child)), True


def _source_endpoint(value: Mapping[str, Any], endpoint_family: str | None) -> str:
    if isinstance(endpoint_family, str) and endpoint_family:
        return _safe_label(endpoint_family, fallback="unknown")
    existing = value.get("source_endpoint_family")
    if isinstance(existing, str) and existing:
        return _safe_label(existing, fallback="unknown")
    if "prompt_tokens" in value or "completion_tokens" in value or "prompt_tokens_details" in value:
        return "chat_completions"
    if "input_tokens" in value or "output_tokens" in value or "input_tokens_details" in value:
        return "responses_or_input_output"
    return "unknown"


def _select_endpoint_alias(
    chat_value: int | None,
    chat_present: bool,
    responses_value: int | None,
    responses_present: bool,
    *,
    endpoint_family: str,
) -> tuple[int | None, bool]:
    conflict = (
        chat_present
        and responses_present
        and chat_value is not None
        and responses_value is not None
        and chat_value != responses_value
    )
    if endpoint_family == "chat_completions":
        return (chat_value if chat_value is not None else responses_value), conflict
    if endpoint_family in {"responses", "responses_or_input_output"}:
        return (responses_value if responses_value is not None else chat_value), conflict
    if conflict:
        return None, True
    return (chat_value if chat_value is not None else responses_value), False


def normalize_usage(
    value: Any = None,
    *,
    endpoint_family: str | None = None,
    retain_details: bool = False,
    source_usage_present: bool | None = None,
) -> dict[str, Any]:
    """Normalize usage while keeping zero distinct from missing.

    Extended field-presence data is added for endpoint-aware/provider usage.
    Legacy callers with only the old neutral fields retain the old five-key
    shape unless they explicitly request details.
    """

    usage = usage_empty()
    if source_usage_present is not None and type(source_usage_present) is not bool:
        raise ValueError("source_usage_present must be a boolean when supplied")
    parent_present = value is not None if source_usage_present is None else source_usage_present
    source_was_mapping = isinstance(value, Mapping)
    source_was_empty_mapping = source_was_mapping and not value
    if not isinstance(value, Mapping):
        if not retain_details and endpoint_family is None:
            return usage
        source: Mapping[str, Any] = {}
    else:
        source = value

    already_normalized = source.get("schema_version") in {
        USAGE_SCHEMA_VERSION,
        LEGACY_USAGE_SCHEMA_VERSION,
    }
    if already_normalized:
        try:
            normalized = validate_usage_observability(source)
            if source_usage_present is not None and normalized["source_usage_present"] != source_usage_present:
                raise ValueError("explicit usage presence disagrees with normalized usage")
            return normalized
        except ValueError:
            source = {}
            parent_present = True
            inherited_diagnostics = ["invalid_normalized_usage"]
    else:
        inherited_diagnostics = []
    extended = bool(
        retain_details
        or endpoint_family is not None
        or already_normalized
        or any(
            key in source
            for key in (
                "prompt_tokens_details",
                "input_tokens_details",
                "completion_tokens_details",
                "output_tokens_details",
                "cached_input_tokens",
                "cache_write_tokens",
                "reasoning_tokens",
            )
        )
    )

    endpoint = _source_endpoint(source, endpoint_family)
    input_tokens = _nonnegative_int(source.get("input_tokens"))
    prompt_tokens = _nonnegative_int(source.get("prompt_tokens"))
    output_tokens = _nonnegative_int(source.get("output_tokens"))
    completion_tokens = _nonnegative_int(source.get("completion_tokens"))
    total_tokens = _nonnegative_int(source.get("total_tokens"))
    selected_input, input_conflict = _select_endpoint_alias(
        prompt_tokens,
        "prompt_tokens" in source,
        input_tokens,
        "input_tokens" in source,
        endpoint_family=endpoint,
    )
    selected_output, output_conflict = _select_endpoint_alias(
        completion_tokens,
        "completion_tokens" in source,
        output_tokens,
        "output_tokens" in source,
        endpoint_family=endpoint,
    )
    usage["input_tokens"] = selected_input
    usage["output_tokens"] = selected_output
    usage["total_tokens"] = total_tokens

    reported_cost = _nonnegative_number(source.get("provider_reported_cost"))
    if reported_cost is None:
        reported_cost = _nonnegative_number(source.get("estimated_cost"))
    usage["estimated_cost"] = reported_cost
    currency = source.get("currency")
    if isinstance(currency, str) and currency.strip() and len(currency.strip()) <= 12:
        usage["currency"] = currency.strip()

    if not extended:
        return usage

    prompt_cached, prompt_cached_present = _nested_int(source, "prompt_tokens_details", "cached_tokens")
    input_cached, input_cached_present = _nested_int(source, "input_tokens_details", "cached_tokens")
    prompt_write, prompt_write_present = _nested_int(source, "prompt_tokens_details", "cache_write_tokens")
    input_write, input_write_present = _nested_int(source, "input_tokens_details", "cache_write_tokens")
    completion_reasoning, completion_reasoning_present = _nested_int(
        source, "completion_tokens_details", "reasoning_tokens"
    )
    output_reasoning, output_reasoning_present = _nested_int(source, "output_tokens_details", "reasoning_tokens")

    selected_cached, cached_conflict = _select_endpoint_alias(
        prompt_cached,
        prompt_cached_present,
        input_cached,
        input_cached_present,
        endpoint_family=endpoint,
    )
    selected_write, write_conflict = _select_endpoint_alias(
        prompt_write,
        prompt_write_present,
        input_write,
        input_write_present,
        endpoint_family=endpoint,
    )
    selected_reasoning, reasoning_conflict = _select_endpoint_alias(
        completion_reasoning,
        completion_reasoning_present,
        output_reasoning,
        output_reasoning_present,
        endpoint_family=endpoint,
    )
    direct_cached_present = "cached_input_tokens" in source
    direct_write_present = "cache_write_tokens" in source
    direct_reasoning_present = "reasoning_tokens" in source
    direct_cached = _nonnegative_int(source.get("cached_input_tokens"))
    direct_write = _nonnegative_int(source.get("cache_write_tokens"))
    direct_reasoning = _nonnegative_int(source.get("reasoning_tokens"))
    cached_input_tokens = direct_cached if direct_cached is not None else selected_cached
    cache_write_tokens = direct_write if direct_write is not None else selected_write
    reasoning_tokens = direct_reasoning if direct_reasoning is not None else selected_reasoning

    field_presence = {
        "usage.prompt_tokens": "prompt_tokens" in source,
        "usage.prompt_tokens_details.cached_tokens": prompt_cached_present,
        "usage.prompt_tokens_details.cache_write_tokens": prompt_write_present,
        "usage.completion_tokens": "completion_tokens" in source,
        "usage.completion_tokens_details.reasoning_tokens": completion_reasoning_present,
        "usage.input_tokens": "input_tokens" in source,
        "usage.input_tokens_details.cached_tokens": input_cached_present,
        "usage.input_tokens_details.cache_write_tokens": input_write_present,
        "usage.output_tokens": "output_tokens" in source,
        "usage.output_tokens_details.reasoning_tokens": output_reasoning_present,
        "usage.cached_input_tokens": direct_cached_present,
        "usage.cache_write_tokens": direct_write_present,
        "usage.reasoning_tokens": direct_reasoning_present,
        "usage.total_tokens": "total_tokens" in source,
        "usage.estimated_cost": "estimated_cost" in source or "provider_reported_cost" in source,
        "usage.currency": "currency" in source,
    }

    known_token_shape = any(
        field_presence.get(key)
        for key in (
            "usage.prompt_tokens",
            "usage.completion_tokens",
            "usage.input_tokens",
            "usage.output_tokens",
            "usage.total_tokens",
            "usage.prompt_tokens_details.cached_tokens",
            "usage.prompt_tokens_details.cache_write_tokens",
            "usage.input_tokens_details.cached_tokens",
            "usage.input_tokens_details.cache_write_tokens",
            "usage.cached_input_tokens",
            "usage.cache_write_tokens",
            "usage.reasoning_tokens",
        )
    )
    unknown_count = sum(1 for key in source if key not in _KNOWN_USAGE_TOP_LEVEL)
    diagnostics: list[str] = list(inherited_diagnostics)
    invalid_present_values = any(
        (
            field_presence["usage.prompt_tokens"] and prompt_tokens is None,
            field_presence["usage.completion_tokens"] and completion_tokens is None,
            field_presence["usage.input_tokens"] and input_tokens is None,
            field_presence["usage.output_tokens"] and output_tokens is None,
            field_presence["usage.total_tokens"] and total_tokens is None,
            prompt_cached_present and prompt_cached is None,
            input_cached_present and input_cached is None,
            prompt_write_present and prompt_write is None,
            input_write_present and input_write is None,
            completion_reasoning_present and completion_reasoning is None,
            output_reasoning_present and output_reasoning is None,
            direct_cached_present and direct_cached is None,
            direct_write_present and direct_write is None,
            direct_reasoning_present and direct_reasoning is None,
            field_presence["usage.estimated_cost"] and reported_cost is None,
            field_presence["usage.currency"] and usage["currency"] is None,
        )
    )
    if parent_present and source_was_empty_mapping:
        diagnostics.append("usage_present_empty")
    elif parent_present and not source_was_mapping:
        diagnostics.append("unknown_usage_shape")
    elif invalid_present_values:
        diagnostics.append("invalid_usage_field_values")
    if source and not known_token_shape and not already_normalized:
        diagnostics.append("unknown_usage_shape")
    elif unknown_count:
        diagnostics.append("unknown_usage_fields_present")
    if any((input_conflict, output_conflict, cached_conflict, write_conflict, reasoning_conflict)):
        diagnostics.append("conflicting_usage_aliases")
    diagnostics = list(dict.fromkeys(diagnostics))[:4]

    usage.update(
        {
            "schema_version": USAGE_SCHEMA_VERSION,
            "source_endpoint_family": endpoint,
            "source_usage_present": parent_present,
            "source_field_presence": field_presence,
            "cached_input_tokens": cached_input_tokens,
            "cache_write_tokens": cache_write_tokens,
            "reasoning_tokens": reasoning_tokens,
            "cache_hit": (cached_input_tokens > 0) if cached_input_tokens is not None else None,
            "provider_reported_cost": reported_cost,
            "house_computed_cost": _nonnegative_number(source.get("house_computed_cost")),
            "tariff_id": _safe_label(source.get("tariff_id"), fallback="") or None,
            "tariff_effective_date": _safe_label(source.get("tariff_effective_date"), fallback="") or None,
            "unpriced_token_classes": (
                [
                    item
                    for item in source.get("unpriced_token_classes", [])
                    if isinstance(item, str) and _SAFE_REASON_RE.fullmatch(item)
                ][:8]
                if isinstance(source.get("unpriced_token_classes"), list)
                else None
            ),
            "diagnostic_codes": diagnostics,
            "unknown_field_count": unknown_count,
        }
    )
    return validate_usage_observability(usage)


def validate_usage_observability(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("usage observability schema is invalid")
    if value.get("schema_version") == LEGACY_USAGE_SCHEMA_VERSION:
        return _validate_gate11_usage_observability(value)
    if value.get("schema_version") != USAGE_SCHEMA_VERSION:
        raise ValueError("usage observability schema is invalid")
    _require_exact_fields(
        value,
        required=_USAGE_SCHEMA_FIELDS,
        schema_name="usage observability",
    )
    endpoint = _require_label(value.get("source_endpoint_family"), field="source_endpoint_family")
    parent_present = _require_bool(value.get("source_usage_present"), field="source_usage_present")
    presence = value.get("source_field_presence")
    if not isinstance(presence, Mapping) or set(presence) != _KNOWN_USAGE_PRESENCE_FIELDS:
        raise ValueError("source_field_presence is not closed")
    validated_presence = {
        field: _require_bool(presence.get(field), field=field)
        for field in sorted(_KNOWN_USAGE_PRESENCE_FIELDS)
    }
    input_tokens = _require_nonnegative_int(value.get("input_tokens"), field="input_tokens", optional=True)
    output_tokens = _require_nonnegative_int(value.get("output_tokens"), field="output_tokens", optional=True)
    total_tokens = _require_nonnegative_int(value.get("total_tokens"), field="total_tokens", optional=True)
    cached = _require_nonnegative_int(value.get("cached_input_tokens"), field="cached_input_tokens", optional=True)
    cache_write = _require_nonnegative_int(value.get("cache_write_tokens"), field="cache_write_tokens", optional=True)
    reasoning = _require_nonnegative_int(value.get("reasoning_tokens"), field="reasoning_tokens", optional=True)
    cache_hit = _require_optional_bool(value.get("cache_hit"), field="cache_hit")
    expected_hit = cached > 0 if cached is not None else None
    if cache_hit != expected_hit:
        raise ValueError("cache_hit does not match cached_input_tokens")
    provider_cost = _require_optional_number(value.get("provider_reported_cost"), field="provider_reported_cost")
    estimated_cost = _require_optional_number(value.get("estimated_cost"), field="estimated_cost")
    if estimated_cost != provider_cost:
        raise ValueError("estimated_cost must remain the provider-reported compatibility alias")
    house_cost = _require_optional_number(value.get("house_computed_cost"), field="house_computed_cost")
    currency = value.get("currency")
    if currency is not None and (
        not isinstance(currency, str)
        or not currency.strip()
        or currency != currency.strip()
        or len(currency) > 12
        or any(ord(character) < 33 or ord(character) > 126 for character in currency)
    ):
        raise ValueError("currency is invalid")
    tariff_id = _require_label(value.get("tariff_id"), field="tariff_id", optional=True)
    tariff_date = _require_label(
        value.get("tariff_effective_date"),
        field="tariff_effective_date",
        optional=True,
    )
    unpriced = value.get("unpriced_token_classes")
    if unpriced is not None:
        unpriced = _require_reason_list(unpriced, field="unpriced_token_classes", limit=8)
    diagnostics = _require_reason_list(
        value.get("diagnostic_codes"),
        field="diagnostic_codes",
        limit=4,
        allowed=_USAGE_DIAGNOSTICS,
    )
    unknown_count = _require_nonnegative_int(value.get("unknown_field_count"), field="unknown_field_count")
    if not parent_present and (
        any(validated_presence.values())
        or any(
            item is not None
            for item in (
                input_tokens,
                output_tokens,
                total_tokens,
                cached,
                cache_write,
                reasoning,
                provider_cost,
                house_cost,
                currency,
                tariff_id,
                tariff_date,
                unpriced,
            )
        )
        or diagnostics
        or unknown_count
    ):
        raise ValueError("absent usage cannot contain provider usage facts")
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_cost": estimated_cost,
        "currency": currency,
        "schema_version": USAGE_SCHEMA_VERSION,
        "source_endpoint_family": endpoint,
        "source_usage_present": parent_present,
        "source_field_presence": validated_presence,
        "cached_input_tokens": cached,
        "cache_write_tokens": cache_write,
        "reasoning_tokens": reasoning,
        "cache_hit": cache_hit,
        "provider_reported_cost": provider_cost,
        "house_computed_cost": house_cost,
        "tariff_id": tariff_id,
        "tariff_effective_date": tariff_date,
        "unpriced_token_classes": unpriced,
        "diagnostic_codes": diagnostics,
        "unknown_field_count": unknown_count,
    }


def _validate_gate11_usage_observability(value: Mapping[str, Any]) -> dict[str, Any]:
    _require_exact_fields(
        value,
        required=_USAGE_SCHEMA_FIELDS,
        schema_name="Gate 1.1 usage observability",
    )
    current = dict(value)
    current["schema_version"] = USAGE_SCHEMA_VERSION
    presence = value.get("source_field_presence")
    if not isinstance(presence, Mapping) or set(presence) != _LEGACY_USAGE_PRESENCE_FIELDS:
        raise ValueError("legacy source_field_presence is not closed")
    current["source_field_presence"] = {
        **presence,
        "usage.cached_input_tokens": False,
        "usage.cache_write_tokens": False,
        "usage.reasoning_tokens": False,
    }
    validated = validate_usage_observability(current)
    validated["schema_version"] = LEGACY_USAGE_SCHEMA_VERSION
    validated["source_field_presence"] = {
        field: validated["source_field_presence"][field]
        for field in sorted(_LEGACY_USAGE_PRESENCE_FIELDS)
    }
    return validated


def _single_header_text(value: Any) -> str | None:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if not isinstance(value, str):
        return None
    if not value or value != value.strip():
        return None
    if any(ord(character) < 33 or ord(character) > 126 for character in value):
        return None
    return value


def _credential_shaped_header_value(value: str) -> bool:
    lowered = value.casefold()
    return bool(
        any(fragment in lowered for fragment in ("authorization", "cookie", "api_key", "apikey", "password"))
        or lowered.startswith(("bearer-", "bearer_", "bearer:"))
        or re.fullmatch(r"(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}", value)
    )


def _gateway_request_id_header(value: Any) -> str | None:
    selected = _single_header_text(value)
    if (
        selected is None
        or not _GATEWAY_REQUEST_ID_RE.fullmatch(selected)
        or "://" in selected
        or _credential_shaped_header_value(selected)
    ):
        return None
    return selected


def _final_model_header(value: Any) -> str | None:
    selected = _single_header_text(value)
    if (
        selected is None
        or not _FINAL_MODEL_RE.fullmatch(selected)
        or "://" in selected
        or _credential_shaped_header_value(selected)
    ):
        return None
    return selected


def _fallback_header(value: Any) -> str | None:
    selected = _single_header_text(value)
    if selected is None:
        return None
    normalized = selected.casefold()
    return normalized if normalized in {"true", "false"} else None


def empty_safe_response_headers() -> dict[str, Any]:
    return {
        "schema_version": HEADER_SCHEMA_VERSION,
        "fields_present": {
            "gateway_request_id": False,
            "final_model": False,
            "fallback": False,
        },
        "gateway_request_id": None,
        "final_model": None,
        "fallback": None,
        "diagnostic_codes": [],
    }


def safe_response_headers(headers: Any) -> dict[str, Any]:
    """Copy only the reviewed AIHubMix response-header allowlist."""

    try:
        already_normalized = (
            isinstance(headers, Mapping)
            and headers.get("schema_version") == HEADER_SCHEMA_VERSION
        )
    except Exception:
        result = empty_safe_response_headers()
        result["diagnostic_codes"] = ["header_parsing_failed"]
        return result

    if already_normalized:
        try:
            return validate_safe_response_headers(headers)
        except Exception:
            result = empty_safe_response_headers()
            result["diagnostic_codes"] = ["header_parsing_failed"]
        return result

    result = empty_safe_response_headers()
    if headers is None:
        return result
    try:
        items = getattr(headers, "items", None)
    except Exception:
        result["diagnostic_codes"] = ["header_parsing_failed"]
        return result
    if not callable(items):
        if headers is not None:
            result["diagnostic_codes"] = ["malformed_response_headers"]
        return result
    folded: dict[str, Any] = {}
    try:
        for key, value in items():
            if isinstance(key, str):
                folded[key.casefold()] = value
    except Exception:
        result["diagnostic_codes"] = ["header_iteration_failed"]
        return result
    mapping = {
        "gateway_request_id": ("x-request-id", _gateway_request_id_header),
        "final_model": ("x-aihubmix-model", _final_model_header),
        "fallback": ("x-aihubmix-fallback", _fallback_header),
    }
    invalid = False
    for field, (header_name, validator) in mapping.items():
        if header_name not in folded:
            continue
        try:
            value = validator(folded.get(header_name))
        except Exception:
            value = None
        if value is None:
            invalid = True
            continue
        result[field] = value
        result["fields_present"][field] = True
    if invalid:
        result["diagnostic_codes"] = ["allowed_header_value_rejected"]
    return validate_safe_response_headers(result)


def validate_safe_response_headers(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema_version") != HEADER_SCHEMA_VERSION:
        raise ValueError("safe response header schema is invalid")
    _require_exact_fields(
        value,
        required=_HEADER_SCHEMA_FIELDS,
        schema_name="safe response headers",
    )
    fields_present = value.get("fields_present")
    expected_fields = {"gateway_request_id", "final_model", "fallback"}
    if not isinstance(fields_present, Mapping) or set(fields_present) != expected_fields:
        raise ValueError("safe response header presence is not closed")
    validated_presence = {
        field: _require_bool(fields_present.get(field), field=f"fields_present.{field}")
        for field in sorted(expected_fields)
    }
    result = {
        "schema_version": HEADER_SCHEMA_VERSION,
        "fields_present": validated_presence,
        "gateway_request_id": None,
        "final_model": None,
        "fallback": None,
        "diagnostic_codes": _require_reason_list(
            value.get("diagnostic_codes"),
            field="diagnostic_codes",
            limit=4,
            allowed=_HEADER_DIAGNOSTICS,
        ),
    }
    validators = {
        "gateway_request_id": _gateway_request_id_header,
        "final_model": _final_model_header,
        "fallback": _fallback_header,
    }
    for field in sorted(expected_fields):
        candidate = value.get(field)
        if candidate is not None:
            selected = validators[field](candidate)
            if selected is None or selected != candidate:
                raise ValueError("safe response header value is invalid")
            result[field] = selected
        if validated_presence[field] != (result[field] is not None):
            raise ValueError("safe response header presence does not match value")
    return result


def unpack_http_transport_result(value: Any) -> tuple[int, bytes, dict[str, Any]]:
    if not isinstance(value, tuple) or len(value) not in {2, 3}:
        raise ValueError("malformed HTTP transport result")
    status, body = value[0], value[1]
    if not isinstance(status, int) or isinstance(status, bool) or not isinstance(body, (bytes, bytearray)):
        raise ValueError("malformed HTTP transport result")
    headers = value[2] if len(value) == 3 else None
    return status, bytes(body), safe_response_headers(headers)


def build_causal_linkage(
    *,
    house_turn_id: str,
    parent_trace_id: str | None,
    operation_id: str | None,
    purpose: str,
    input_provenance_classes: Sequence[str],
    output_destination_class: str,
    attempt_number: int,
    attempt_reason: str,
    provider_profile: str,
    client_model_label: str,
    endpoint_family: str,
) -> dict[str, Any]:
    if purpose not in _PURPOSES:
        raise ValueError("unsupported provider attempt purpose")
    provenance = list(dict.fromkeys(input_provenance_classes))
    if not provenance or any(item not in _PROVENANCE_CLASSES for item in provenance):
        raise ValueError("unsupported provider input provenance class")
    if output_destination_class not in _OUTPUT_DESTINATIONS:
        raise ValueError("unsupported provider output destination class")
    if not isinstance(attempt_number, int) or isinstance(attempt_number, bool) or attempt_number < 1:
        raise ValueError("attempt_number must be positive")
    if attempt_reason not in _ATTEMPT_REASONS:
        raise ValueError("unsupported provider attempt reason")
    result = {
        "schema_version": CAUSAL_SCHEMA_VERSION,
        "house_turn_id": _safe_id(house_turn_id),
        "parent_trace_id": _safe_id(parent_trace_id, optional=True),
        "operation_id": _safe_id(operation_id, optional=True),
        "purpose": purpose,
        "input_provenance_classes": provenance,
        "output_destination_class": output_destination_class,
        "attempt_number": attempt_number,
        "attempt_reason": attempt_reason,
        "provider_profile": _require_label(provider_profile, field="provider_profile"),
        "client_model_label": _require_label(client_model_label, field="client_model_label"),
        "endpoint_family": _require_label(endpoint_family, field="endpoint_family"),
    }
    return validate_causal_linkage(result)


def validate_causal_linkage(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or value.get("schema_version") != CAUSAL_SCHEMA_VERSION:
        raise ValueError("invalid causal linkage schema")
    _require_exact_fields(value, required=_CAUSAL_SCHEMA_FIELDS, schema_name="causal linkage")
    house_turn_id = _safe_id(value.get("house_turn_id"))
    parent_trace_id = _safe_id(value.get("parent_trace_id"), optional=True)
    operation_id = _safe_id(value.get("operation_id"), optional=True)
    purpose = value.get("purpose")
    if purpose not in _PURPOSES:
        raise ValueError("unsupported provider attempt purpose")
    provenance = value.get("input_provenance_classes")
    if (
        not isinstance(provenance, list)
        or not provenance
        or len(provenance) > len(_PROVENANCE_CLASSES)
        or any(not isinstance(item, str) or item not in _PROVENANCE_CLASSES for item in provenance)
        or len(set(provenance)) != len(provenance)
    ):
        raise ValueError("invalid provider input provenance classes")
    destination = value.get("output_destination_class")
    if destination not in _OUTPUT_DESTINATIONS:
        raise ValueError("unsupported provider output destination")
    attempt_number = _require_nonnegative_int(value.get("attempt_number"), field="attempt_number")
    if attempt_number < 1:
        raise ValueError("attempt_number must be positive")
    attempt_reason = value.get("attempt_reason")
    if attempt_reason not in _ATTEMPT_REASONS:
        raise ValueError("unsupported provider attempt reason")
    return {
        "schema_version": CAUSAL_SCHEMA_VERSION,
        "house_turn_id": house_turn_id,
        "parent_trace_id": parent_trace_id,
        "operation_id": operation_id,
        "purpose": purpose,
        "input_provenance_classes": list(provenance),
        "output_destination_class": destination,
        "attempt_number": attempt_number,
        "attempt_reason": attempt_reason,
        "provider_profile": _require_label(value.get("provider_profile"), field="provider_profile"),
        "client_model_label": _require_label(value.get("client_model_label"), field="client_model_label"),
        "endpoint_family": _require_label(value.get("endpoint_family"), field="endpoint_family"),
    }


def _safe_reason_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        count = _nonnegative_int(item)
        if isinstance(key, str) and _SAFE_REASON_RE.fullmatch(key) and count is not None:
            result[key] = count
    return dict(sorted(result.items()))


def _validate_reason_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping) or len(value) > 32:
        raise ValueError("reason_counts must be a bounded object")
    result: dict[str, int] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not _SAFE_REASON_RE.fullmatch(key):
            raise ValueError("reason_counts contains an invalid reason")
        result[key] = int(_require_nonnegative_int(item, field=f"reason_counts.{key}"))
    return dict(sorted(result.items()))


def build_section_metric(
    *,
    section_id: str,
    section_class: str,
    order: int,
    rendered_text: str,
    exactness: str,
    update_frequency: str,
    selected_count: int = 1,
    omitted_count: int = 0,
    reason_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    if not isinstance(rendered_text, str) or not rendered_text.strip():
        raise ValueError("section text must be present")
    if exactness not in _SECTION_EXACTNESS or update_frequency not in _UPDATE_FREQUENCIES:
        raise ValueError("invalid section classification")
    selected = _nonnegative_int(selected_count)
    omitted = _nonnegative_int(omitted_count)
    if selected is None or omitted is None or _nonnegative_int(order) is None:
        raise ValueError("invalid section counts")
    utf8_bytes = len(rendered_text.encode("utf-8"))
    if section_id not in _SECTION_IDS or section_class not in _MINIMUM_SECTION_CLASSES:
        raise ValueError("unreviewed section identity")
    return _validate_section_metric({
        "section_id": section_id,
        "section_class": section_class,
        "order": order,
        "characters_after_provider_safety": len(rendered_text),
        "utf8_bytes": utf8_bytes,
        "token_estimate": utf8_bytes,
        "token_estimator_version": TOKEN_ESTIMATOR_VERSION,
        "exactness": exactness,
        "update_frequency": update_frequency,
        "selected_item_count": selected,
        "omitted_item_count": omitted,
        "reason_counts": _safe_reason_counts(reason_counts),
        "provider_visible_role_destination": "user.content",
    })


def _validate_section_metric(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("section metric must be an object")
    _require_exact_fields(value, required=_SECTION_METRIC_FIELDS, schema_name="section metric")
    section_id = value.get("section_id")
    section_class = value.get("section_class")
    if section_id not in _SECTION_IDS or section_class not in _MINIMUM_SECTION_CLASSES:
        raise ValueError("unreviewed section identity")
    order = _require_nonnegative_int(value.get("order"), field="order")
    characters = _require_nonnegative_int(
        value.get("characters_after_provider_safety"), field="characters_after_provider_safety"
    )
    utf8_bytes = _require_nonnegative_int(value.get("utf8_bytes"), field="utf8_bytes")
    token_estimate = _require_nonnegative_int(value.get("token_estimate"), field="token_estimate")
    selected = _require_nonnegative_int(value.get("selected_item_count"), field="selected_item_count")
    omitted = _require_nonnegative_int(value.get("omitted_item_count"), field="omitted_item_count")
    if characters > utf8_bytes or token_estimate != utf8_bytes:
        raise ValueError("section byte/token accounting is invalid")
    if value.get("exactness") not in _SECTION_EXACTNESS:
        raise ValueError("invalid section exactness")
    if value.get("update_frequency") not in _UPDATE_FREQUENCIES:
        raise ValueError("invalid section update frequency")
    if value.get("token_estimator_version") != TOKEN_ESTIMATOR_VERSION:
        raise ValueError("invalid section token estimator")
    if value.get("provider_visible_role_destination") != "user.content":
        raise ValueError("invalid section destination")
    return {
        "section_id": section_id,
        "section_class": section_class,
        "order": order,
        "characters_after_provider_safety": characters,
        "utf8_bytes": utf8_bytes,
        "token_estimate": token_estimate,
        "token_estimator_version": TOKEN_ESTIMATOR_VERSION,
        "exactness": value.get("exactness"),
        "update_frequency": value.get("update_frequency"),
        "selected_item_count": selected,
        "omitted_item_count": omitted,
        "reason_counts": _validate_reason_counts(value.get("reason_counts")),
        "provider_visible_role_destination": "user.content",
    }


def build_flattened_request_observability(
    section_metrics: Sequence[Mapping[str, Any]],
    *,
    final_prompt_text: str,
    request_model_version: str = CURRENT_REQUEST_MODEL_VERSION,
) -> dict[str, Any]:
    validated = sorted((_validate_section_metric(item) for item in section_metrics), key=lambda item: item["order"])
    if [item["order"] for item in validated] != list(range(len(validated))):
        raise ValueError("section metric order must be contiguous")

    class_summary: dict[str, dict[str, int]] = {
        section_class: {
            "present_section_count": 0,
            "selected_item_count": 0,
            "omitted_item_count": 0,
            "characters_after_provider_safety": 0,
            "utf8_bytes": 0,
            "token_estimate": 0,
        }
        for section_class in _MINIMUM_SECTION_CLASSES
    }
    for metric in validated:
        selected = class_summary.setdefault(
            metric["section_class"],
            {
                "present_section_count": 0,
                "selected_item_count": 0,
                "omitted_item_count": 0,
                "characters_after_provider_safety": 0,
                "utf8_bytes": 0,
                "token_estimate": 0,
            },
        )
        selected["present_section_count"] += 1
        for field in (
            "selected_item_count",
            "omitted_item_count",
            "characters_after_provider_safety",
            "utf8_bytes",
            "token_estimate",
        ):
            selected[field] += int(metric[field])

    leading_chars = 0
    leading_bytes = 0
    leading_tokens = 0
    dynamic_seen = False
    dynamic_before_stable = False
    joiner_chars = len(FLATTENED_SECTION_JOINER)
    joiner_bytes = len(FLATTENED_SECTION_JOINER.encode("utf-8"))
    for index, metric in enumerate(validated):
        stable = metric["update_frequency"] in _LEADING_PREFIX_FREQUENCIES
        if not dynamic_seen and stable:
            leading_chars += metric["characters_after_provider_safety"]
            leading_bytes += metric["utf8_bytes"]
            leading_tokens += metric["token_estimate"]
            if index + 1 < len(validated):
                leading_chars += joiner_chars
                leading_bytes += joiner_bytes
                leading_tokens += joiner_bytes
        elif not stable:
            dynamic_seen = True
        elif dynamic_seen:
            dynamic_before_stable = True

    prompt_characters = len(final_prompt_text)
    prompt_bytes = len(final_prompt_text.encode("utf-8"))
    section_characters = sum(item["characters_after_provider_safety"] for item in validated)
    section_bytes = sum(item["utf8_bytes"] for item in validated)
    framing_characters = max(0, len(validated) - 1) * joiner_chars
    framing_bytes = max(0, len(validated) - 1) * joiner_bytes
    residual_characters = prompt_characters - section_characters - framing_characters
    residual_bytes = prompt_bytes - section_bytes - framing_bytes
    if residual_characters < 0 or residual_bytes < 0:
        raise ValueError("section metrics exceed the final prompt")
    return validate_request_observability({
        "schema_version": SECTION_METRICS_SCHEMA_VERSION,
        "request_model_version": _safe_label(request_model_version),
        "raw_free": True,
        "provider_visible_role_destination": "user.content",
        "section_count": len(validated),
        "sections": validated,
        "section_class_summary": class_summary,
        "prompt_characters_after_provider_safety": prompt_characters,
        "prompt_utf8_bytes": prompt_bytes,
        "known_inter_section_framing_characters": framing_characters,
        "known_inter_section_framing_utf8_bytes": framing_bytes,
        "unattributed_residual_characters": residual_characters,
        "unattributed_residual_utf8_bytes": residual_bytes,
        "total_input_token_estimate": prompt_bytes,
        "token_estimator_version": TOKEN_ESTIMATOR_VERSION,
        "reusable_leading_prefix_characters": leading_chars,
        "reusable_leading_prefix_utf8_bytes": leading_bytes,
        "estimated_reusable_leading_prefix_tokens": leading_tokens,
        "dynamic_before_stable": dynamic_before_stable,
        "late_stable_law_excluded_from_leading_prefix": dynamic_before_stable,
        "body_text_returned": False,
        "message_ids_returned": False,
        "body_hashes_returned": False,
        "private_paths_returned": False,
    })


def validate_request_observability(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or value.get("schema_version") != SECTION_METRICS_SCHEMA_VERSION:
        raise ValueError("invalid request observability schema")
    legacy = "known_inter_section_framing_utf8_bytes" not in value
    field_set = _LEGACY_REQUEST_FIELDS if legacy else _REQUEST_FIELDS
    _require_exact_fields(
        value,
        required=field_set - {"request_body_utf8_bytes"},
        optional={"request_body_utf8_bytes"},
        schema_name="request observability",
    )
    sections_value = value.get("sections")
    if not isinstance(sections_value, list):
        raise ValueError("sections must be a list")
    sections = sections_value
    validated_sections = [_validate_section_metric(item) for item in sections]
    if [item["order"] for item in validated_sections] != list(range(len(validated_sections))):
        raise ValueError("section metric order must be contiguous")
    section_count = _require_nonnegative_int(value.get("section_count"), field="section_count")
    if section_count != len(validated_sections):
        raise ValueError("section metric count does not match")
    if (
        _require_bool(value.get("raw_free"), field="raw_free") is not True
        or _require_bool(value.get("body_text_returned"), field="body_text_returned") is not False
        or _require_bool(value.get("message_ids_returned"), field="message_ids_returned") is not False
        or _require_bool(value.get("body_hashes_returned"), field="body_hashes_returned") is not False
        or _require_bool(value.get("private_paths_returned"), field="private_paths_returned") is not False
        or value.get("provider_visible_role_destination") != "user.content"
        or value.get("token_estimator_version") != TOKEN_ESTIMATOR_VERSION
    ):
        raise ValueError("request observability must remain raw-free")
    request_model_version = _require_label(value.get("request_model_version"), field="request_model_version")
    dynamic_before_stable = _require_bool(value.get("dynamic_before_stable"), field="dynamic_before_stable")
    late_law = _require_bool(
        value.get("late_stable_law_excluded_from_leading_prefix"),
        field="late_stable_law_excluded_from_leading_prefix",
    )
    if dynamic_before_stable != late_law:
        raise ValueError("late stable-law state must match dynamic-before-stable state")
    counts: dict[str, int] = {}
    for field in (
        "prompt_characters_after_provider_safety",
        "prompt_utf8_bytes",
        "total_input_token_estimate",
        "estimated_reusable_leading_prefix_tokens",
    ):
        counts[field] = int(_require_nonnegative_int(value.get(field), field=field))
    leading_char_field = (
        "estimated_reusable_leading_prefix_characters"
        if legacy
        else "reusable_leading_prefix_characters"
    )
    leading_byte_field = (
        "estimated_reusable_leading_prefix_utf8_bytes"
        if legacy
        else "reusable_leading_prefix_utf8_bytes"
    )
    counts[leading_char_field] = int(_require_nonnegative_int(value.get(leading_char_field), field=leading_char_field))
    counts[leading_byte_field] = int(_require_nonnegative_int(value.get(leading_byte_field), field=leading_byte_field))
    if counts["total_input_token_estimate"] != counts["prompt_utf8_bytes"]:
        raise ValueError("request token estimate must match the UTF-8 upper-bound estimator")
    request_bytes = None
    if "request_body_utf8_bytes" in value:
        request_bytes = _require_nonnegative_int(value.get("request_body_utf8_bytes"), field="request_body_utf8_bytes")
    class_summary = value.get("section_class_summary")
    if not isinstance(class_summary, Mapping) or set(class_summary) != set(_MINIMUM_SECTION_CLASSES):
        raise ValueError("section class summary must be an object")
    safe_summary: dict[str, dict[str, int]] = {}
    for section_class, summary in class_summary.items():
        if section_class not in _MINIMUM_SECTION_CLASSES:
            raise ValueError("invalid section class summary key")
        if not isinstance(summary, Mapping) or set(summary) != _CLASS_SUMMARY_FIELDS:
            raise ValueError("invalid section class summary")
        safe_summary[section_class] = {
            field: int(_require_nonnegative_int(summary.get(field), field=f"{section_class}.{field}"))
            for field in _CLASS_SUMMARY_FIELDS
        }
    expected_summary = {
        section_class: {field: 0 for field in _CLASS_SUMMARY_FIELDS}
        for section_class in _MINIMUM_SECTION_CLASSES
    }
    for metric in validated_sections:
        summary = expected_summary[metric["section_class"]]
        summary["present_section_count"] += 1
        for field in _CLASS_SUMMARY_FIELDS - {"present_section_count"}:
            summary[field] += int(metric[field])
    if safe_summary != expected_summary:
        raise ValueError("section class summary does not match section metrics")
    expected_leading_characters = 0
    expected_leading_bytes = 0
    expected_leading_tokens = 0
    dynamic_seen = False
    stable_after_dynamic = False
    for index, metric in enumerate(validated_sections):
        stable = metric["update_frequency"] in _LEADING_PREFIX_FREQUENCIES
        if not dynamic_seen and stable:
            expected_leading_characters += metric["characters_after_provider_safety"]
            expected_leading_bytes += metric["utf8_bytes"]
            expected_leading_tokens += metric["token_estimate"]
            if not legacy and index + 1 < len(validated_sections):
                expected_leading_characters += len(FLATTENED_SECTION_JOINER)
                expected_leading_bytes += len(FLATTENED_SECTION_JOINER.encode("utf-8"))
                expected_leading_tokens += len(FLATTENED_SECTION_JOINER.encode("utf-8"))
        elif not stable:
            dynamic_seen = True
        elif dynamic_seen:
            stable_after_dynamic = True
    if (
        counts[leading_char_field] != expected_leading_characters
        or counts[leading_byte_field] != expected_leading_bytes
        or counts["estimated_reusable_leading_prefix_tokens"] != expected_leading_tokens
        or dynamic_before_stable != stable_after_dynamic
    ):
        raise ValueError("reusable leading-prefix accounting does not match sections")
    result = {
        "schema_version": SECTION_METRICS_SCHEMA_VERSION,
        "request_model_version": request_model_version,
        "raw_free": True,
        "provider_visible_role_destination": "user.content",
        "section_count": section_count,
        "sections": validated_sections,
        "section_class_summary": safe_summary,
        "prompt_characters_after_provider_safety": counts["prompt_characters_after_provider_safety"],
        "prompt_utf8_bytes": counts["prompt_utf8_bytes"],
        "total_input_token_estimate": counts["total_input_token_estimate"],
        "token_estimator_version": TOKEN_ESTIMATOR_VERSION,
        leading_char_field: counts[leading_char_field],
        leading_byte_field: counts[leading_byte_field],
        "estimated_reusable_leading_prefix_tokens": counts["estimated_reusable_leading_prefix_tokens"],
        "dynamic_before_stable": dynamic_before_stable,
        "late_stable_law_excluded_from_leading_prefix": late_law,
        "body_text_returned": False,
        "message_ids_returned": False,
        "body_hashes_returned": False,
        "private_paths_returned": False,
    }
    if not legacy:
        for field in (
            "known_inter_section_framing_characters",
            "known_inter_section_framing_utf8_bytes",
            "unattributed_residual_characters",
            "unattributed_residual_utf8_bytes",
        ):
            result[field] = int(_require_nonnegative_int(value.get(field), field=field))
        section_characters = sum(item["characters_after_provider_safety"] for item in validated_sections)
        section_bytes = sum(item["utf8_bytes"] for item in validated_sections)
        if (
            section_characters
            + result["known_inter_section_framing_characters"]
            + result["unattributed_residual_characters"]
            != counts["prompt_characters_after_provider_safety"]
            or section_bytes
            + result["known_inter_section_framing_utf8_bytes"]
            + result["unattributed_residual_utf8_bytes"]
            != counts["prompt_utf8_bytes"]
        ):
            raise ValueError("request section/framing/residual accounting does not close")
        expected_framing_count = max(0, len(validated_sections) - 1)
        if (
            result["known_inter_section_framing_characters"]
            != expected_framing_count * len(FLATTENED_SECTION_JOINER)
            or result["known_inter_section_framing_utf8_bytes"]
            != expected_framing_count * len(FLATTENED_SECTION_JOINER.encode("utf-8"))
        ):
            raise ValueError("known request framing does not match the canonical joiner")
    if request_bytes is not None:
        result["request_body_utf8_bytes"] = request_bytes
    return result


def _validate_legacy_usage_observability(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema_version") != LEGACY_USAGE_SCHEMA_VERSION:
        raise ValueError("legacy usage observability schema is invalid")
    _require_exact_fields(
        value,
        required=_LEGACY_USAGE_SCHEMA_FIELDS,
        schema_name="legacy usage observability",
    )
    presence = value.get("source_field_presence")
    parent_present = bool(
        (isinstance(presence, Mapping) and any(item is True for item in presence.values()))
        or value.get("unknown_field_count")
        or value.get("diagnostic_codes")
        or any(
            value.get(field) is not None
            for field in (
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "cached_input_tokens",
                "cache_write_tokens",
                "reasoning_tokens",
                "provider_reported_cost",
            )
        )
    )
    current = dict(value)
    current["source_usage_present"] = parent_present
    validated = validate_usage_observability(current)
    validated.pop("source_usage_present")
    return validated


def validate_response_observability(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("response observability must be an object")
    _require_exact_fields(value, required=_RESPONSE_FIELDS, schema_name="response observability")
    http_status = _require_http_status(value.get("http_status"))
    response_bytes = _require_nonnegative_int(value.get("response_bytes"), field="response_bytes")
    latency = value.get("transport_latency_ms")
    latency = _require_nonnegative_int(latency, field="transport_latency_ms", optional=True)
    usage_value = value.get("usage")
    if not isinstance(usage_value, Mapping):
        raise ValueError("response usage must be a reviewed object")
    normalized_usage = (
        validate_usage_observability(usage_value)
        if "source_usage_present" in usage_value
        else _validate_legacy_usage_observability(usage_value)
    )
    finish_reason = _require_label(value.get("finish_reason"), field="finish_reason", optional=True)
    diagnostics = _require_reason_list(
        value.get("diagnostic_codes"),
        field="diagnostic_codes",
        limit=4,
        allowed=_RESPONSE_DIAGNOSTICS,
    )
    return {
        "http_status": http_status,
        "response_bytes": response_bytes,
        "transport_latency_ms": latency,
        "finish_reason": finish_reason,
        "safe_response_headers": validate_safe_response_headers(value.get("safe_response_headers")),
        "usage": normalized_usage,
        "diagnostic_codes": diagnostics,
    }


def build_response_observability(
    response_body: bytes,
    *,
    http_status: int | None,
    response_headers: Any = None,
    endpoint_family: str,
    latency_ms: int | None = None,
) -> dict[str, Any]:
    usage_value: Any = None
    usage_present = False
    finish_reason: str | None = None
    diagnostics: list[str] = []
    try:
        import json

        payload = json.loads(response_body.decode("utf-8"))
        if isinstance(payload, Mapping):
            usage_present = "usage" in payload
            usage_value = payload.get("usage")
            choices = payload.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
                candidate = choices[0].get("finish_reason")
                if isinstance(candidate, str):
                    finish_reason = _safe_label(candidate, fallback="") or None
            if finish_reason is None:
                for key in ("finish_reason", "stop_reason", "status"):
                    candidate = payload.get(key)
                    if isinstance(candidate, str):
                        finish_reason = _safe_label(candidate, fallback="") or None
                        if finish_reason:
                            break
        else:
            diagnostics.append("non_object_response_envelope")
    except Exception:
        diagnostics.append("response_usage_unavailable")
    return validate_response_observability({
        "http_status": http_status if isinstance(http_status, int) and 100 <= http_status <= 599 else None,
        "response_bytes": len(response_body),
        "transport_latency_ms": _nonnegative_int(latency_ms),
        "finish_reason": finish_reason,
        "safe_response_headers": safe_response_headers(response_headers),
        "usage": normalize_usage(
            usage_value,
            endpoint_family=endpoint_family,
            retain_details=True,
            source_usage_present=usage_present,
        ),
        "diagnostic_codes": diagnostics,
    })


def build_adapter_observability(
    *,
    request_observability: Mapping[str, Any] | None,
    usage: Mapping[str, Any] | None,
    transport_facts: Mapping[str, Any] | None,
    endpoint_family: str,
    client_model_label: str,
    provider_profile: str,
    latency_ms: int,
    finish_reason: str,
    ok: bool,
    provider_call_made: bool,
    trace_owned: bool = False,
    causal_linkage_available: bool = False,
) -> dict[str, Any]:
    ok_value = _require_bool(ok, field="ok")
    provider_call_value = _require_bool(provider_call_made, field="provider_call_made")
    trace_owned_value = _require_bool(trace_owned, field="trace_owned")
    causal_available_value = _require_bool(
        causal_linkage_available, field="causal_linkage_available"
    )
    normalized_usage = normalize_usage(
        usage,
        endpoint_family=endpoint_family,
        retain_details=True,
    )
    legacy_usage_shape = normalized_usage.get("schema_version") == LEGACY_USAGE_SCHEMA_VERSION
    validated_request = validate_request_observability(request_observability)
    transport = dict(transport_facts or {})
    headers = safe_response_headers(transport.get("safe_response_headers"))
    usage_presence = normalized_usage["source_field_presence"]
    cache_read_field_present = any(
        usage_presence.get(field, False)
        for field in (
            "usage.prompt_tokens_details.cached_tokens",
            "usage.input_tokens_details.cached_tokens",
            "usage.cached_input_tokens",
        )
    ) or bool(legacy_usage_shape and normalized_usage.get("cached_input_tokens") is not None)
    cache_write_field_present = any(
        usage_presence.get(field, False)
        for field in (
            "usage.prompt_tokens_details.cache_write_tokens",
            "usage.input_tokens_details.cache_write_tokens",
            "usage.cache_write_tokens",
        )
    ) or bool(legacy_usage_shape and normalized_usage.get("cache_write_tokens") is not None)
    response_facts_available = bool(transport_facts is not None or normalized_usage["source_usage_present"])
    result = {
        "schema_version": ADAPTER_OBSERVABILITY_SCHEMA_VERSION,
        "raw_free": True,
        "request_model_version": (
            validated_request["request_model_version"]
            if validated_request is not None
            else CURRENT_REQUEST_MODEL_VERSION
        ),
        "endpoint_family": _safe_label(endpoint_family),
        "provider_profile": _safe_label(provider_profile),
        "client_model_label": _safe_label(client_model_label),
        "final_model_header": headers.get("final_model"),
        "fallback_observation": headers.get("fallback"),
        "gateway_request_id": headers.get("gateway_request_id"),
        "source_usage_present": normalized_usage["source_usage_present"],
        "cache_read_field_present": cache_read_field_present,
        "cache_write_field_present": cache_write_field_present,
        "cache_fields_present": cache_read_field_present or cache_write_field_present,
        "cached_input_tokens": normalized_usage.get("cached_input_tokens"),
        "cache_write_tokens": normalized_usage.get("cache_write_tokens"),
        "reasoning_tokens": normalized_usage.get("reasoning_tokens"),
        "input_tokens": normalized_usage.get("input_tokens"),
        "output_tokens": normalized_usage.get("output_tokens"),
        "total_tokens": normalized_usage.get("total_tokens"),
        "returned_cache_hit": normalized_usage.get("cache_hit"),
        "request_body_utf8_bytes": _nonnegative_int(transport.get("request_body_utf8_bytes")),
        "response_bytes": _nonnegative_int(transport.get("response_bytes")),
        "http_status": _nonnegative_int(transport.get("http_status")),
        "adapter_latency_ms": _nonnegative_int(latency_ms),
        "finish_reason": _safe_label(finish_reason, fallback="error"),
        "ok": ok_value,
        "provider_call_made": provider_call_value,
        "house_retry_count": 0,
        "house_retry_reasons": [],
        "helper_inclusive_totals_state": "causal_linkage_available_not_aggregated",
        "output_token_limit_state": "advisory_not_sent"
        if endpoint_family == "chat_completions"
        else "endpoint_dependent",
        "request_observability_state": (
            "trace_request_owned"
            if trace_owned_value and validated_request is not None
            else "compact_runtime_only"
            if validated_request is not None
            else "unavailable"
        ),
        "response_observability_state": (
            "trace_response_owned"
            if trace_owned_value and response_facts_available
            else "compact_runtime_only"
            if response_facts_available
            else "unavailable"
        ),
        "causal_linkage_state": (
            "trace_causal_linkage_owned"
            if trace_owned_value and causal_available_value
            else "compact_runtime_only"
            if causal_available_value
            else "unavailable"
        ),
    }
    return validate_adapter_observability(result)


def _validate_compact_observability(
    value: Any,
    *,
    schema_version: str,
    legacy: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema_version") != schema_version:
        raise ValueError("compact observability schema is invalid")
    _require_exact_fields(
        value,
        required=_LEGACY_ADAPTER_COMPACT_FIELDS if legacy else _ADAPTER_COMPACT_FIELDS,
        schema_name="compact observability",
    )
    if _require_bool(value.get("raw_free"), field="raw_free") is not True:
        raise ValueError("compact observability must remain raw-free")
    result = {
        "schema_version": schema_version,
        "raw_free": True,
        "request_model_version": _require_label(value.get("request_model_version"), field="request_model_version"),
        "endpoint_family": _require_label(value.get("endpoint_family"), field="endpoint_family"),
        "provider_profile": _require_label(value.get("provider_profile"), field="provider_profile"),
        "client_model_label": _require_label(value.get("client_model_label"), field="client_model_label"),
        "final_model_header": _require_label(value.get("final_model_header"), field="final_model_header", optional=True),
        "fallback_observation": _require_label(value.get("fallback_observation"), field="fallback_observation", optional=True),
        "gateway_request_id": _require_label(value.get("gateway_request_id"), field="gateway_request_id", optional=True),
        "source_usage_present": _require_bool(value.get("source_usage_present"), field="source_usage_present"),
        "cache_read_field_present": (
            _require_bool(value.get("cache_read_field_present"), field="cache_read_field_present")
            if not legacy
            else bool(value.get("cached_input_tokens") is not None)
        ),
        "cache_write_field_present": (
            _require_bool(value.get("cache_write_field_present"), field="cache_write_field_present")
            if not legacy
            else bool(value.get("cache_write_tokens") is not None)
        ),
        "cache_fields_present": _require_bool(value.get("cache_fields_present"), field="cache_fields_present"),
        "returned_cache_hit": _require_optional_bool(value.get("returned_cache_hit"), field="returned_cache_hit"),
        "http_status": _require_http_status(value.get("http_status")),
        "finish_reason": _require_label(value.get("finish_reason"), field="finish_reason"),
        "ok": _require_bool(value.get("ok"), field="ok"),
        "provider_call_made": _require_bool(value.get("provider_call_made"), field="provider_call_made"),
        "house_retry_count": _require_nonnegative_int(value.get("house_retry_count"), field="house_retry_count"),
        "house_retry_reasons": _require_reason_list(value.get("house_retry_reasons"), field="house_retry_reasons", limit=4),
        "helper_inclusive_totals_state": value.get("helper_inclusive_totals_state"),
        "output_token_limit_state": value.get("output_token_limit_state"),
        "request_observability_state": value.get("request_observability_state"),
        "response_observability_state": value.get("response_observability_state"),
        "causal_linkage_state": value.get("causal_linkage_state"),
    }
    for field in (
        "cached_input_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "request_body_utf8_bytes",
        "response_bytes",
        "adapter_latency_ms",
    ):
        result[field] = _require_nonnegative_int(value.get(field), field=field, optional=True)
    if result["helper_inclusive_totals_state"] not in _HELPER_TOTAL_STATES:
        raise ValueError("unsupported helper-total state")
    if result["output_token_limit_state"] not in _OUTPUT_LIMIT_STATES:
        raise ValueError("unsupported output-limit state")
    if result["request_observability_state"] not in _REQUEST_OBSERVABILITY_STATES:
        raise ValueError("unsupported request-observability state")
    if result["response_observability_state"] not in _RESPONSE_OBSERVABILITY_STATES:
        raise ValueError("unsupported response-observability state")
    if result["causal_linkage_state"] not in _CAUSAL_LINKAGE_STATES:
        raise ValueError("unsupported causal-linkage state")
    if result["house_retry_count"] != 0 or result["house_retry_reasons"]:
        raise ValueError("Gate 1.1 does not permit retry telemetry")
    expected_hit = result["cached_input_tokens"] > 0 if result["cached_input_tokens"] is not None else None
    if result["returned_cache_hit"] != expected_hit:
        raise ValueError("cache-hit evidence does not match cached tokens")
    if result["cached_input_tokens"] is not None and not result["cache_fields_present"]:
        raise ValueError("cached-token evidence requires a present cache field")
    if result["cache_fields_present"] != (
        result["cache_read_field_present"] or result["cache_write_field_present"]
    ) and not legacy:
        raise ValueError("aggregate cache presence does not match read/write presence")
    if result["cached_input_tokens"] is not None and not result["cache_read_field_present"]:
        raise ValueError("cached-token evidence requires a present cache-read field")
    if result["cache_write_tokens"] is not None and not result["cache_write_field_present"]:
        raise ValueError("cache-write evidence requires a present cache-write field")
    if not result["source_usage_present"] and any(
        result[field] is not None
        for field in (
            "cached_input_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
            "input_tokens",
            "output_tokens",
            "total_tokens",
        )
    ):
        raise ValueError("absent usage cannot contain usage totals")
    return result


def _validate_legacy_adapter_observability(value: Mapping[str, Any]) -> dict[str, Any]:
    _require_exact_fields(value, required=_LEGACY_ADAPTER_FIELDS, schema_name="legacy adapter observability")
    if _require_bool(value.get("raw_free"), field="raw_free") is not True:
        raise ValueError("legacy adapter observability must remain raw-free")
    headers = validate_safe_response_headers(value.get("safe_response_headers"))
    for field, header_field in (
        ("gateway_request_id", "gateway_request_id"),
        ("final_model_header", "final_model"),
        ("fallback_observation", "fallback"),
    ):
        if value.get(field) != headers.get(header_field):
            raise ValueError("legacy adapter header projection does not match")
    usage_value = value.get("usage")
    if not isinstance(usage_value, Mapping):
        raise ValueError("legacy adapter usage must be an object")
    usage = (
        validate_usage_observability(usage_value)
        if "source_usage_present" in usage_value
        else _validate_legacy_usage_observability(usage_value)
    )
    request = validate_request_observability(value.get("request_observability"))
    result = {
        "schema_version": LEGACY_ADAPTER_OBSERVABILITY_SCHEMA_VERSION,
        "raw_free": True,
        "request_model_version": _require_label(value.get("request_model_version"), field="request_model_version"),
        "endpoint_family": _require_label(value.get("endpoint_family"), field="endpoint_family"),
        "provider_profile": _require_label(value.get("provider_profile"), field="provider_profile"),
        "client_model_label": _require_label(value.get("client_model_label"), field="client_model_label"),
        "final_model_header": _require_label(value.get("final_model_header"), field="final_model_header", optional=True),
        "fallback_observation": _require_label(value.get("fallback_observation"), field="fallback_observation", optional=True),
        "gateway_request_id": _require_label(value.get("gateway_request_id"), field="gateway_request_id", optional=True),
        "safe_response_headers": headers,
        "usage": usage,
        "cache_fields_present": _require_bool(value.get("cache_fields_present"), field="cache_fields_present"),
        "cached_input_tokens": _require_nonnegative_int(value.get("cached_input_tokens"), field="cached_input_tokens", optional=True),
        "cache_write_tokens": _require_nonnegative_int(value.get("cache_write_tokens"), field="cache_write_tokens", optional=True),
        "returned_cache_hit": _require_optional_bool(value.get("returned_cache_hit"), field="returned_cache_hit"),
        "request_body_utf8_bytes": _require_nonnegative_int(value.get("request_body_utf8_bytes"), field="request_body_utf8_bytes", optional=True),
        "response_bytes": _require_nonnegative_int(value.get("response_bytes"), field="response_bytes", optional=True),
        "http_status": _require_http_status(value.get("http_status")),
        "adapter_latency_ms": _require_nonnegative_int(value.get("adapter_latency_ms"), field="adapter_latency_ms", optional=True),
        "finish_reason": _require_label(value.get("finish_reason"), field="finish_reason"),
        "ok": _require_bool(value.get("ok"), field="ok"),
        "provider_call_made": _require_bool(value.get("provider_call_made"), field="provider_call_made"),
        "house_retry_count": _require_nonnegative_int(value.get("house_retry_count"), field="house_retry_count"),
        "house_retry_reasons": _require_reason_list(value.get("house_retry_reasons"), field="house_retry_reasons", limit=4),
        "helper_inclusive_totals_state": value.get("helper_inclusive_totals_state"),
        "output_token_limit_state": value.get("output_token_limit_state"),
        "request_observability": request,
    }
    if result["helper_inclusive_totals_state"] not in _HELPER_TOTAL_STATES:
        raise ValueError("unsupported legacy helper-total state")
    if result["output_token_limit_state"] not in _OUTPUT_LIMIT_STATES:
        raise ValueError("unsupported legacy output-limit state")
    if result["house_retry_count"] != 0 or result["house_retry_reasons"]:
        raise ValueError("legacy adapter retry telemetry is invalid")
    if result["returned_cache_hit"] != usage.get("cache_hit"):
        raise ValueError("legacy cache-hit evidence does not match usage")
    if result["cached_input_tokens"] != usage.get("cached_input_tokens"):
        raise ValueError("legacy cached-token evidence does not match usage")
    if result["cache_write_tokens"] != usage.get("cache_write_tokens"):
        raise ValueError("legacy cache-write evidence does not match usage")
    return result


def validate_adapter_observability(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("adapter observability schema is invalid")
    schema_version = value.get("schema_version")
    if schema_version == LEGACY_ADAPTER_OBSERVABILITY_SCHEMA_VERSION:
        if "request_observability" in value or "usage" in value or "safe_response_headers" in value:
            return _validate_legacy_adapter_observability(value)
        return _validate_compact_observability(
            value,
            schema_version=LEGACY_ADAPTER_OBSERVABILITY_SCHEMA_VERSION,
            legacy=True,
        )
    if schema_version != ADAPTER_OBSERVABILITY_SCHEMA_VERSION:
        raise ValueError("adapter observability schema is invalid")
    if "request_observability" in value or "usage" in value or "safe_response_headers" in value:
        raise ValueError("current adapter observability must use the compact shape")
    return _validate_compact_observability(value, schema_version=ADAPTER_OBSERVABILITY_SCHEMA_VERSION)


def project_safe_log_observability(value: Any) -> dict[str, Any]:
    validated = validate_adapter_observability(value)
    if "usage" not in validated:
        projected = dict(validated)
    else:
        usage = validated["usage"]
        presence = usage["source_field_presence"]
        projected = {
            "schema_version": SAFE_LOG_OBSERVABILITY_SCHEMA_VERSION,
            "raw_free": True,
            "request_model_version": validated["request_model_version"],
            "endpoint_family": validated["endpoint_family"],
            "provider_profile": validated["provider_profile"],
            "client_model_label": validated["client_model_label"],
            "final_model_header": validated["final_model_header"],
            "fallback_observation": validated["fallback_observation"],
            "gateway_request_id": validated["gateway_request_id"],
            "source_usage_present": bool(
                usage.get("source_usage_present")
                if "source_usage_present" in usage
                else any(presence.values()) or usage.get("diagnostic_codes") or usage.get("unknown_field_count")
            ),
            "cache_read_field_present": bool(
                usage.get("cached_input_tokens") is not None
                or presence.get("usage.prompt_tokens_details.cached_tokens", False)
                or presence.get("usage.input_tokens_details.cached_tokens", False)
                or presence.get("usage.cached_input_tokens", False)
            ),
            "cache_write_field_present": bool(
                usage.get("cache_write_tokens") is not None
                or presence.get("usage.prompt_tokens_details.cache_write_tokens", False)
                or presence.get("usage.input_tokens_details.cache_write_tokens", False)
                or presence.get("usage.cache_write_tokens", False)
            ),
            "cache_fields_present": validated["cache_fields_present"],
            "cached_input_tokens": validated["cached_input_tokens"],
            "cache_write_tokens": validated["cache_write_tokens"],
            "reasoning_tokens": usage.get("reasoning_tokens"),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "returned_cache_hit": validated["returned_cache_hit"],
            "request_body_utf8_bytes": validated["request_body_utf8_bytes"],
            "response_bytes": validated["response_bytes"],
            "http_status": validated["http_status"],
            "adapter_latency_ms": validated["adapter_latency_ms"],
            "finish_reason": validated["finish_reason"],
            "ok": validated["ok"],
            "provider_call_made": validated["provider_call_made"],
            "house_retry_count": validated["house_retry_count"],
            "house_retry_reasons": validated["house_retry_reasons"],
            "helper_inclusive_totals_state": validated["helper_inclusive_totals_state"],
            "output_token_limit_state": validated["output_token_limit_state"],
            "request_observability_state": (
                "compact_runtime_only" if validated["request_observability"] is not None else "unavailable"
            ),
            "response_observability_state": "compact_runtime_only",
            "causal_linkage_state": "unavailable",
        }
    projected["schema_version"] = SAFE_LOG_OBSERVABILITY_SCHEMA_VERSION
    return validate_safe_log_observability(projected)


def validate_safe_log_observability(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping) and value.get("schema_version") == LEGACY_SAFE_LOG_OBSERVABILITY_SCHEMA_VERSION:
        return _validate_compact_observability(
            value,
            schema_version=LEGACY_SAFE_LOG_OBSERVABILITY_SCHEMA_VERSION,
            legacy=True,
        )
    return _validate_compact_observability(value, schema_version=SAFE_LOG_OBSERVABILITY_SCHEMA_VERSION)


def validate_trace_observability(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema_version") != TRACE_OBSERVABILITY_SCHEMA_VERSION:
        raise ValueError("trace observability schema is invalid")
    _require_exact_fields(
        value,
        required={"schema_version"},
        optional=_TRACE_FIELDS - {"schema_version"},
        schema_name="trace observability",
    )
    result: dict[str, Any] = {"schema_version": TRACE_OBSERVABILITY_SCHEMA_VERSION}
    if "request" in value:
        request = validate_request_observability(value.get("request"))
        if request is None:
            raise ValueError("trace request observability cannot be null")
        result["request"] = request
    if "response" in value:
        result["response"] = validate_response_observability(value.get("response"))
    if "adapter" in value:
        result["adapter"] = validate_adapter_observability(value.get("adapter"))
    return result


def merge_trace_observability(existing: Any, update: Any) -> dict[str, Any]:
    if existing is None:
        base = {"schema_version": TRACE_OBSERVABILITY_SCHEMA_VERSION}
    else:
        base = validate_trace_observability(existing)
    if not isinstance(update, Mapping):
        raise ValueError("trace observability update must be an object")
    _require_exact_fields(
        update,
        required=frozenset(),
        optional=_TRACE_FIELDS,
        schema_name="trace observability update",
    )
    if "schema_version" in update and update.get("schema_version") != TRACE_OBSERVABILITY_SCHEMA_VERSION:
        raise ValueError("trace observability update schema is invalid")
    result = dict(base)
    if "request" in update:
        request = validate_request_observability(update.get("request"))
        if request is None:
            raise ValueError("trace request observability cannot be null")
        result["request"] = request
    if "response" in update:
        result["response"] = validate_response_observability(update.get("response"))
    if "adapter" in update:
        result["adapter"] = validate_adapter_observability(update.get("adapter"))
    return validate_trace_observability(result)


__all__ = [
    "ADAPTER_OBSERVABILITY_SCHEMA_VERSION",
    "CAUSAL_SCHEMA_VERSION",
    "CURRENT_REQUEST_MODEL_VERSION",
    "FLATTENED_SECTION_JOINER",
    "HEADER_SCHEMA_VERSION",
    "LEGACY_ADAPTER_OBSERVABILITY_SCHEMA_VERSION",
    "LEGACY_SAFE_LOG_OBSERVABILITY_SCHEMA_VERSION",
    "LEGACY_USAGE_SCHEMA_VERSION",
    "SAFE_LOG_OBSERVABILITY_SCHEMA_VERSION",
    "SECTION_METRICS_SCHEMA_VERSION",
    "TOKEN_ESTIMATOR_VERSION",
    "TRACE_OBSERVABILITY_SCHEMA_VERSION",
    "USAGE_SCHEMA_VERSION",
    "build_adapter_observability",
    "build_causal_linkage",
    "build_flattened_request_observability",
    "build_response_observability",
    "build_section_metric",
    "empty_safe_response_headers",
    "merge_trace_observability",
    "normalize_usage",
    "project_safe_log_observability",
    "safe_response_headers",
    "unpack_http_transport_result",
    "usage_empty",
    "validate_causal_linkage",
    "validate_adapter_observability",
    "validate_request_observability",
    "validate_response_observability",
    "validate_safe_log_observability",
    "validate_safe_response_headers",
    "validate_trace_observability",
]
