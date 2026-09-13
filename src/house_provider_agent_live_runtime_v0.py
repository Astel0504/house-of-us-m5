"""Traced live provider-agent runtime for the protected House tool branch.

This owner joins the existing main-model configuration/HTTP transport, the
provider-neutral agent loop, Provider Trace Vault, the reviewed MCP tool
surface, and the durable tool ledger.  It does not select models, wire Talk
routes, retry provider calls, or expose raw provider/tool bodies.
"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

import house_prompt_cache_dispatch_observability_v1 as cache_dispatch_observability
import house_provider_tool_surface_v0 as provider_tool_surface
import house_continuity_v1_2_structured_terminal_result_v1 as structured_terminal
import main_runtime_provider_adapter_v0 as provider_adapter
import provider_observability_v0 as provider_observability
from house_mcp_tool_broker_v0 import HouseMcpToolBroker
from house_provider_agent_loop_v0 import run_provider_agent_loop
from house_provider_agent_tool_contract_v0 import (
    ProviderAgentToolContractError,
    derive_parent_operation_id,
    derive_provider_leg_id,
)
from house_provider_agent_tool_runtime_v0 import HouseProviderAgentToolRuntime
from house_tool_operation_ledger_v0 import ToolOperationLedger
from main_runtime_provider_trace_bridge_v0 import ProviderTraceBridge


SCHEMA_VERSION = "house_provider_agent_live_runtime_v0"
ENABLED_ENV = "HOUSE_PROVIDER_AGENT_TOOLS_ENABLED"
BACKEND_ROOT_ENV = "HOUSE_API_TALK_RUNTIME_ROOT"
TRACE_ROOT_ENV = "HOUSE_PROVIDER_TRACE_VAULT_ROOT"
ENABLED_VALUE = "1"
LEDGER_DIRECTORY = "provider_agent_tools"
LEDGER_FILENAME = "tool_operations.sqlite3"
TOOL_BRANCH_VISIBLE_ACK_INSTRUCTION = (
    "If you choose a tool, include one short, natural acknowledgement to Astel in that first "
    "tool-call message saying what you're checking. Once you have what you need, give her a "
    "separate natural answer with what you found."
)


@dataclass(frozen=True)
class PreparedInitialProviderRequest:
    stable_operation_id: str
    parent_operation_id: str
    provider: str
    model: str
    endpoint_family: str
    request_body: bytes = field(repr=False)
    request_body_sha256: str
    provider_tool_surface: Mapping[str, Any] = field(repr=False)
PROMPT_CACHE_REQUEST_OBSERVABILITY_SCHEMA_VERSION = (
    "house_provider_agent_prompt_cache_request_observability_v1"
)

HTTPTransport = Callable[
    [str, Mapping[str, str], bytes, int],
    tuple[int, bytes] | tuple[int, bytes, Mapping[str, Any]],
]
EventCallback = Callable[[Mapping[str, Any]], Any | Awaitable[Any]]
_STABLE_OPERATION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}")


def _safe_error(code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return provider_adapter.error_obj(code, message, retryable)


def _provider_agent_projection(
    *,
    parent_operation_id: str | None,
    provider_leg_count: int = 0,
    tool_call_count: int = 0,
    tool_receipt_count: int = 0,
    trace_records: list[dict[str, Any]] | None = None,
    prompt_cache_request_observability: Mapping[str, Any] | None = None,
    prompt_cache_dispatch_observability: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "parent_operation_id": parent_operation_id,
        "provider_leg_count": provider_leg_count,
        "tool_call_count": tool_call_count,
        "tool_receipt_count": tool_receipt_count,
        "provider_trace_receipts": list(trace_records or []),
        "prompt_cache_request_observability": (
            copy.deepcopy(dict(prompt_cache_request_observability))
            if isinstance(prompt_cache_request_observability, Mapping)
            else None
        ),
        "prompt_cache_dispatch_observability": (
            cache_dispatch_observability.safe_runtime_summary(
                prompt_cache_dispatch_observability
            )
        ),
        "raw_provider_content_present": False,
        "raw_tool_content_present": False,
    }


def _response(
    *,
    request: Mapping[str, Any],
    config: provider_adapter.MainModelConfig,
    ok: bool,
    parent_operation_id: str | None,
    assistant_text: str = "",
    usage: Mapping[str, Any] | None = None,
    error: Mapping[str, Any] | None = None,
    provider_leg_count: int = 0,
    tool_call_count: int = 0,
    tool_receipt_count: int = 0,
    trace_records: list[dict[str, Any]] | None = None,
    prompt_cache_request_observability: Mapping[str, Any] | None = None,
    prompt_cache_dispatch_observability: Mapping[str, Any] | None = None,
    latency_ms: int = 0,
) -> dict[str, Any]:
    result = provider_adapter.build_response(
        request=request,
        config=config,
        ok=ok,
        assistant_text=assistant_text,
        finish_reason="stop",
        errors=[dict(error)] if isinstance(error, Mapping) else [],
        usage=usage,
        latency_ms=latency_ms,
    )
    provider = result.get("provider")
    if isinstance(provider, dict):
        provider["tools_used"] = tool_call_count > 0
    provider_calls_made = provider_leg_count > 0
    result["provider_calls_made"] = provider_calls_made
    result["external_provider_calls_made"] = provider_calls_made
    result["provider_agent"] = _provider_agent_projection(
        parent_operation_id=parent_operation_id,
        provider_leg_count=provider_leg_count,
        tool_call_count=tool_call_count,
        tool_receipt_count=tool_receipt_count,
        trace_records=trace_records,
        prompt_cache_request_observability=(
            prompt_cache_request_observability
        ),
        prompt_cache_dispatch_observability=(
            prompt_cache_dispatch_observability
        ),
    )
    return result


def _attach_dispatch_facts(
    response: dict[str, Any],
    dispatched_request_sha256: list[str],
) -> dict[str, Any]:
    response["_house_provider_dispatch_facts"] = {
        "exact_dispatched_request_sha256": (
            dispatched_request_sha256[0] if dispatched_request_sha256 else ""
        ),
        "provider_dispatch_count": len(dispatched_request_sha256),
        "provider_retry_count": 0,
        "provider_fallback_count": 0,
    }
    return response


def _stable_operation(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    selected = value.strip()
    return selected if _STABLE_OPERATION_RE.fullmatch(selected) is not None else None


def _sum_usage(values: list[Mapping[str, Any]]) -> dict[str, Any]:
    result = provider_adapter.usage_empty()
    for field in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
    ):
        numbers = [item.get(field) for item in values if isinstance(item.get(field), int)]
        if numbers:
            result[field] = sum(numbers)
    costs = [item.get("estimated_cost") for item in values if isinstance(item.get("estimated_cost"), (int, float))]
    if costs:
        result["estimated_cost"] = sum(costs)
    currencies = {
        item.get("currency") for item in values
        if isinstance(item.get("currency"), str) and item.get("currency")
    }
    if len(currencies) == 1:
        result["currency"] = next(iter(currencies))
    return result


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False))


def _service_boot_id() -> str | None:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="ascii"
        ).strip()
    except (OSError, UnicodeError):
        return None
    return value or None


def _prompt_cache_request_observability(
    body: Mapping[str, Any],
    *,
    request_metadata: Mapping[str, Any],
) -> dict[str, Any] | None:
    cache = (
        request_metadata.get("prompt_cache")
        if isinstance(request_metadata.get("prompt_cache"), Mapping)
        else {}
    )
    stable_count = cache.get("stable_message_count")
    messages = body.get("messages")
    if (
        cache.get("effective_mode") != "stable_prefix"
        or type(stable_count) is not int
        or stable_count < 1
        or not isinstance(messages, list)
        or any(not isinstance(item, Mapping) for item in messages)
    ):
        return None
    provider_stable_count = stable_count + 1
    if provider_stable_count >= len(messages):
        return None
    tools = body.get("tools") if isinstance(body.get("tools"), list) else []
    surface = {
        "model": body.get("model"),
        "messages": [
            {
                "role": item.get("role"),
                "content": item.get("content"),
            }
            for item in messages[:provider_stable_count]
        ],
        "tools": tools,
        "tool_choice": body.get("tool_choice"),
        "parallel_tool_calls": body.get("parallel_tool_calls"),
    }
    encoded = json.dumps(
        surface,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    if "prompt_cache_retention" in body:
        retention_field = "prompt_cache_retention"
        retention_value = str(body.get("prompt_cache_retention") or "")
    elif isinstance(body.get("prompt_cache_options"), Mapping):
        retention_field = "prompt_cache_options.ttl"
        retention_value = str(
            body["prompt_cache_options"].get("ttl") or ""
        )
    else:
        retention_field = ""
        retention_value = ""
    return {
        "schema_version": PROMPT_CACHE_REQUEST_OBSERVABILITY_SCHEMA_VERSION,
        "provider_prefix_identity_state": "provider_agent_initial_surface",
        "provider_prefix_sha256": hashlib.sha256(encoded).hexdigest(),
        "provider_prefix_utf8_bytes": len(encoded),
        "provider_stable_message_count": provider_stable_count,
        "provider_tool_definition_count": len(tools),
        "provider_retention_field": retention_field,
        "provider_retention_value": retention_value,
        "provider_prompt_cache_key_present": "prompt_cache_key" in body,
        "raw_provider_content_present": False,
    }


def _tool_branch_initial_messages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError("Provider-agent initial messages are malformed.")
    return [
        {"role": "system", "content": TOOL_BRANCH_VISIBLE_ACK_INSTRUCTION},
        *[_json_copy(dict(item)) for item in value],
    ]


def _assistant_message(response: Mapping[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise provider_adapter.ProviderPayloadError(
            "malformed_provider_response", "Chat Completions response has no first choice."
        )
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise provider_adapter.ProviderPayloadError(
            "malformed_provider_response", "Chat Completions response has no assistant message."
        )
    return _json_copy(dict(message))


def _messages_for_leg(loop_request: Mapping[str, Any]) -> list[dict[str, Any]]:
    initial = loop_request.get("initial_input")
    prior = loop_request.get("prior_provider_responses")
    batches = loop_request.get("tool_result_batches")
    if not isinstance(initial, list) or not isinstance(prior, list) or not isinstance(batches, list):
        raise provider_adapter.ProviderPayloadError(
            "invalid_agent_leg", "Provider-agent leg input is malformed."
        )
    messages = [_json_copy(dict(item)) for item in initial if isinstance(item, Mapping)]
    if len(messages) != len(initial) or len(prior) != len(batches):
        raise provider_adapter.ProviderPayloadError(
            "invalid_agent_leg", "Provider-agent leg history is malformed."
        )
    for response, batch in zip(prior, batches):
        if not isinstance(response, Mapping) or not isinstance(batch, list):
            raise provider_adapter.ProviderPayloadError(
                "invalid_agent_leg", "Provider-agent leg history is malformed."
            )
        messages.append(_assistant_message(response))
        for item in batch:
            if not isinstance(item, Mapping):
                raise provider_adapter.ProviderPayloadError(
                    "invalid_agent_leg", "Provider-agent tool result history is malformed."
                )
            messages.append(_json_copy(dict(item)))
    return messages


def _provider_agent_base_and_surface(
    request: Mapping[str, Any],
    *,
    config: provider_adapter.MainModelConfig,
    broker: HouseMcpToolBroker,
    reviewed_read_only_capabilities: Mapping[str, Mapping[str, Any]] | None,
    operation_bound_tool_surface: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the canonical tool surface and provider-agent base body."""

    surface = (
        copy.deepcopy(dict(operation_bound_tool_surface))
        if operation_bound_tool_surface is not None
        else provider_tool_surface.build_provider_tool_surface(
            provider_family="openai",
            provider_endpoint="chat_completions",
            broker=broker,
            reviewed_read_only_capabilities=reviewed_read_only_capabilities,
        )
    )
    if not surface["provider_tool_definitions"]:
        raise provider_tool_surface.ProviderToolSurfaceError(
            "no_available_tools",
            "No reviewed read-only tools are available to Solen.",
        )
    structured_mode = (
        surface.get("terminal_result_required") is True
        if operation_bound_tool_surface is not None
        else structured_terminal.generation2_structured_mode(request)
    )
    if structured_mode and operation_bound_tool_surface is None:
        surface = copy.deepcopy(surface)
        surface["provider_tool_definitions"].append(
            structured_terminal.provider_tool_definition()
        )
        surface["terminal_result_required"] = True
    try:
        structured_terminal.validate_strict_tool_definitions(
            surface["provider_tool_definitions"]
        )
    except structured_terminal.StructuredTerminalSchemaCompatibilityError as exc:
        raise provider_tool_surface.ProviderToolSurfaceError(
            exc.error_class,
            "Provider strict tool schema is incompatible.",
        ) from exc
    stats = provider_adapter.context_packet_stats(
        request.get("context_packet")
        if isinstance(request.get("context_packet"), Mapping)
        else None
    )
    base_body = provider_adapter.build_openai_compatible_chat_completions_http_body(
        request, config, stats
    )
    if structured_mode:
        # Strict Generation-2 terminal requests use the provider-supported
        # lowest-variance sampling setting. This narrows proposal variability
        # without changing the semantic validator or durable write authority.
        base_body["temperature"] = 0
    base_body["messages"] = _tool_branch_initial_messages(base_body.get("messages"))
    return base_body, surface


def _provider_agent_leg_body_bytes(
    base_body: Mapping[str, Any],
    surface: Mapping[str, Any],
    loop_request: Mapping[str, Any],
) -> bytes:
    """Serialize exactly one provider-agent leg through the canonical owner."""

    body_map = copy.deepcopy(dict(base_body))
    body_map["messages"] = _messages_for_leg(loop_request)
    if loop_request.get("tools_enabled") is True:
        body_map["tools"] = copy.deepcopy(surface["provider_tool_definitions"])
        if surface.get("terminal_result_required") is True:
            body_map["tool_choice"] = structured_terminal.forced_tool_choice()
            body_map["parallel_tool_calls"] = False
        else:
            body_map["tool_choice"] = "auto"
            body_map["parallel_tool_calls"] = True
    else:
        body_map.pop("tools", None)
        body_map.pop("tool_choice", None)
        body_map.pop("parallel_tool_calls", None)
    body_map["stream"] = False
    return json.dumps(
        body_map,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def prepare_initial_provider_request(
    request: Mapping[str, Any],
    *,
    stable_operation_id: str,
    provider_operation_id: str | None = None,
    broker: HouseMcpToolBroker | None,
    env: Mapping[str, str] | None = None,
    reviewed_read_only_capabilities: (
        Mapping[str, Mapping[str, Any]] | None
    ) = None,
    operation_bound_tool_surface: Mapping[str, Any] | None = None,
) -> PreparedInitialProviderRequest:
    """Build the exact first provider leg without transport or runtime writes."""

    source = env if env is not None else os.environ
    config = provider_adapter.load_main_model_config(source)
    stable = _stable_operation(stable_operation_id)
    if stable is None:
        raise provider_adapter.ProviderPayloadError(
            "missing_stable_operation",
            "A stable client turn identity is required.",
        )
    if broker is None:
        raise provider_adapter.ProviderPayloadError(
            "tool_broker_unavailable",
            "Tool broker is unavailable.",
        )
    parent = (
        provider_operation_id
        if isinstance(provider_operation_id, str)
        and re.fullmatch(r"hpaop_[0-9a-f]{64}", provider_operation_id)
        else None
    )
    if provider_operation_id is not None and parent is None:
        raise provider_adapter.ProviderPayloadError(
            "invalid_parent_operation",
            "Provider operation identity is malformed.",
        )
    if parent is None:
        parent = derive_parent_operation_id(
            {"stable_operation_id": stable}
        )
    config_errors = provider_adapter.preflight_provider_config(config)
    if config_errors:
        first = config_errors[0]
        raise provider_adapter.ProviderPayloadError(
            str(first.get("error_class") or "provider_config_invalid"),
            "Provider configuration is unavailable.",
        )
    request_errors = provider_adapter.validate_runtime_request(request)
    if request_errors:
        first = request_errors[0]
        raise provider_adapter.ProviderPayloadError(
            str(first.get("error_class") or "invalid_runtime_request"),
            "Runtime request is malformed.",
        )
    base_body, surface = _provider_agent_base_and_surface(
        request,
        config=config,
        broker=broker,
        reviewed_read_only_capabilities=reviewed_read_only_capabilities,
        operation_bound_tool_surface=operation_bound_tool_surface,
    )
    loop_request = {
        "provider_family": "openai",
        "provider_endpoint": "chat_completions",
        "parent_operation_id": parent,
        "provider_leg_ordinal": 0,
        "provider_leg_id": derive_provider_leg_id(parent, 0),
        "tools_enabled": True,
        "initial_input": list(base_body["messages"]),
        "prior_provider_responses": [],
        "tool_result_batches": [],
    }
    body = _provider_agent_leg_body_bytes(
        base_body,
        surface,
        loop_request,
    )
    return PreparedInitialProviderRequest(
        stable_operation_id=stable,
        parent_operation_id=parent,
        provider=config.provider,
        model=config.model,
        endpoint_family=config.openai_compatible_endpoint,
        request_body=body,
        request_body_sha256=hashlib.sha256(body).hexdigest(),
        provider_tool_surface=copy.deepcopy(surface),
    )


def _trace_record(
    bridge: ProviderTraceBridge,
    *,
    provider_leg_ordinal: int,
    provider_leg_request_id: str,
) -> dict[str, Any]:
    fields = bridge.safe_log_fields()
    receipt = bridge.receipt.as_dict() if bridge.receipt is not None else None
    return {
        "provider_leg_ordinal": provider_leg_ordinal,
        "provider_leg_request_id": provider_leg_request_id,
        "status": fields.get("provider_trace_status", "not_captured"),
        "failure_stage": fields.get("provider_trace_failure_stage"),
        "receipt": copy.deepcopy(receipt) if isinstance(receipt, Mapping) else None,
        "causal_linkage": None,
        "observability": None,
        "causal_linkage_state": fields.get("provider_trace_causal_linkage_state", "unavailable"),
        "observability_state": fields.get("provider_trace_observability_state", "unavailable"),
    }


async def run_provider_agent_live_runtime_async(
    request: Mapping[str, Any],
    *,
    stable_operation_id: str,
    broker: HouseMcpToolBroker | None,
    env: Mapping[str, str] | None = None,
    http_transport: HTTPTransport | None = None,
    reviewed_read_only_capabilities: Mapping[str, Mapping[str, Any]] | None = None,
    max_provider_legs: int = 8,
    event_callback: EventCallback | None = None,
    gate11_initial_request_capture: list[bytes] | None = None,
    forbid_tool_dispatch: bool = False,
    prepared_initial_request: PreparedInitialProviderRequest | None = None,
) -> dict[str, Any]:
    """Run one protected, explicit, traced model-tool-model operation."""
    started = time.perf_counter()
    source = env if env is not None else os.environ
    config = provider_adapter.load_main_model_config(source)
    parent_operation_id: str | None = None

    def failure(code: str, message: str, retryable: bool = False) -> dict[str, Any]:
        return _response(
            request=request,
            config=config,
            ok=False,
            parent_operation_id=parent_operation_id,
            error=_safe_error(code, message, retryable),
            latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
        )

    if str(source.get(ENABLED_ENV) or "").strip() != ENABLED_VALUE:
        return failure("provider_agent_tools_disabled", "Provider-agent tools are disabled.")
    if broker is None:
        return failure("tool_broker_unavailable", "Tool broker is unavailable.")
    stable = _stable_operation(stable_operation_id)
    if stable is None:
        return failure("missing_stable_operation", "A stable client turn identity is required.")
    if prepared_initial_request is not None:
        parent_operation_id = (
            prepared_initial_request.parent_operation_id
        )
    else:
        try:
            parent_operation_id = derive_parent_operation_id({"stable_operation_id": stable})
        except ProviderAgentToolContractError:
            return failure("invalid_stable_operation", "Stable client turn identity is malformed.")
    if not isinstance(max_provider_legs, int) or isinstance(max_provider_legs, bool) or max_provider_legs < 1:
        return failure("invalid_max_provider_legs", "Provider leg limit is malformed.")
    backend_root = str(source.get(BACKEND_ROOT_ENV) or "").strip()
    if not backend_root:
        return failure("missing_runtime_root", "Provider-agent runtime root is not configured.")
    trace_root = str(source.get(TRACE_ROOT_ENV) or "").strip()
    if not trace_root:
        return failure("missing_provider_trace_root", "Provider Trace Vault root is not configured.")
    if config.provider != "openai_compatible":
        return failure("unsupported_provider", "Provider-agent V1 requires the OpenAI-compatible provider.")
    if config.openai_compatible_transport != "live_http":
        return failure("unsupported_provider_transport", "Provider-agent V1 requires live HTTP transport.")
    if config.openai_compatible_endpoint != "chat_completions":
        return failure("unsupported_provider_endpoint", "Provider-agent V1 requires Chat Completions.")
    if not config.supports_tools:
        return failure("model_tools_unsupported", "The selected model is not marked tool-capable.")
    config_errors = provider_adapter.preflight_provider_config(config)
    if config_errors:
        first = config_errors[0]
        return failure(
            str(first.get("error_class") or "provider_config_invalid"),
            str(first.get("message") or "Provider configuration is unavailable."),
            bool(first.get("retryable")),
        )
    request_errors = provider_adapter.validate_runtime_request(request)
    if request_errors:
        first = request_errors[0]
        return failure(
            str(first.get("error_class") or "invalid_runtime_request"),
            str(first.get("message") or "Runtime request is malformed."),
            False,
        )

    try:
        base_body, surface = _provider_agent_base_and_surface(
            request,
            config=config,
            broker=broker,
            reviewed_read_only_capabilities=reviewed_read_only_capabilities,
            operation_bound_tool_surface=(
                prepared_initial_request.provider_tool_surface
                if prepared_initial_request is not None
                else None
            ),
        )
    except provider_tool_surface.ProviderToolSurfaceError as exc:
        return failure(exc.error_class, "Provider tool surface is unavailable.")
    if prepared_initial_request is not None:
        initial_loop_request = {
            "provider_family": "openai",
            "provider_endpoint": "chat_completions",
            "parent_operation_id": parent_operation_id,
            "provider_leg_ordinal": 0,
            "provider_leg_id": derive_provider_leg_id(
                parent_operation_id,
                0,
            ),
            "tools_enabled": True,
            "initial_input": list(base_body["messages"]),
            "prior_provider_responses": [],
            "tool_result_batches": [],
        }
        reconstructed = _provider_agent_leg_body_bytes(
            base_body,
            surface,
            initial_loop_request,
        )
        if (
            prepared_initial_request.stable_operation_id != stable
            or prepared_initial_request.parent_operation_id
            != parent_operation_id
            or prepared_initial_request.provider != config.provider
            or prepared_initial_request.model != config.model
            or prepared_initial_request.endpoint_family
            != config.openai_compatible_endpoint
            or prepared_initial_request.request_body != reconstructed
            or prepared_initial_request.request_body_sha256
            != hashlib.sha256(reconstructed).hexdigest()
        ):
            return failure(
                "prepared_initial_request_mismatch",
                "Prepared provider request identity changed before transport.",
            )

    try:
        ledger = ToolOperationLedger(
            Path(backend_root) / LEDGER_DIRECTORY / LEDGER_FILENAME
        )
        dispatcher = HouseProviderAgentToolRuntime(broker, ledger)
    except (OSError, ValueError) as exc:
        code = getattr(exc, "error_class", "provider_agent_runtime_unavailable")
        return failure(str(code), "Provider-agent runtime could not initialize.")
    cache_observation_store = None
    try:
        cache_observation_store = (
            cache_dispatch_observability.PromptCacheDispatchObservabilityStore(
                Path(backend_root)
                / cache_dispatch_observability.STORE_DIRECTORY
                / cache_dispatch_observability.STORE_FILENAME
            )
        )
    except Exception:
        # Passive cache monitoring cannot change provider behavior.
        cache_observation_store = None

    trace_records: list[dict[str, Any]] = []
    leg_usage: list[Mapping[str, Any]] = []
    last_transport_error: str | None = None
    selected_transport = http_transport or provider_adapter.openai_compatible_default_http_transport
    api_key = str(source.get("MAIN_MODEL_API_KEY") or "")
    url = provider_adapter.openai_compatible_responses_url(
        config.base_url, config.openai_compatible_endpoint
    )
    request_metadata = request.get("metadata") if isinstance(request.get("metadata"), Mapping) else {}
    provider_profile = str(request_metadata.get("provider_profile") or config.provider)
    prompt_cache_request_observation: dict[str, Any] | None = None
    prompt_cache_dispatch_observation: dict[str, Any] | None = None
    prompt_cache_observation_id: str | None = None
    dispatched_request_sha256: list[str] = []

    def provider_call(loop_request: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal last_transport_error
        nonlocal prompt_cache_request_observation
        nonlocal prompt_cache_dispatch_observation
        nonlocal prompt_cache_observation_id
        ordinal = int(loop_request.get("provider_leg_ordinal", -1))
        parent = str(loop_request.get("parent_operation_id") or "")
        leg_request_id = derive_provider_leg_id(parent, ordinal)
        attempt_number = ordinal + 1
        attempt_reason = "initial" if ordinal == 0 else "tool_followup"
        causal_linkage = None
        try:
            causal_linkage = provider_observability.build_causal_linkage(
                house_turn_id=stable,
                parent_trace_id=None,
                operation_id=parent,
                purpose="provider_agent_leg",
                input_provenance_classes=("flattened_house_context", "provider_agent_history"),
                output_destination_class="provider_agent_loop",
                attempt_number=attempt_number,
                attempt_reason=attempt_reason,
                provider_profile=provider_profile,
                client_model_label=config.model,
                endpoint_family=config.openai_compatible_endpoint,
            )
        except Exception:
            pass
        bridge = ProviderTraceBridge(
            root=trace_root,
            operation_id=parent,
            request_id=leg_request_id,
            provider_label=config.provider,
            model_label=config.model,
            endpoint_family=config.openai_compatible_endpoint,
            reason_labeler=provider_adapter._provider_trace_reason_label,
            policy_house_turn_id=stable,
            policy_purpose="provider_agent_leg",
            causal_linkage=causal_linkage,
            attempt_number=attempt_number,
        )
        response_body: bytes | None = None
        safe_response_headers: Mapping[str, Any] | None = None
        try:
            rebuilt_body = _provider_agent_leg_body_bytes(
                base_body,
                surface,
                loop_request,
            )
            body = (
                prepared_initial_request.request_body
                if ordinal == 0
                and prepared_initial_request is not None
                else rebuilt_body
            )
            if (
                ordinal == 0
                and prepared_initial_request is not None
                and (
                    parent
                    != prepared_initial_request.parent_operation_id
                    or body != rebuilt_body
                )
            ):
                raise provider_adapter.ProviderPayloadError(
                    "prepared_initial_request_mismatch",
                    "Prepared provider request identity changed.",
                )
            body_map = json.loads(body.decode("utf-8"))
            if ordinal == 0 and gate11_initial_request_capture is not None:
                gate11_initial_request_capture.append(bytes(body))
            if ordinal == 0:
                prompt_cache_request_observation = (
                    _prompt_cache_request_observability(
                        body_map,
                        request_metadata=request_metadata,
                    )
                )
            if ordinal == 0 and cache_observation_store is not None:
                try:
                    request_observation = (
                        cache_dispatch_observability.build_dispatch_request_observation(
                            body=body_map,
                            request_body=body,
                            request_metadata=request_metadata,
                            house_turn_id=stable,
                            operation_id=parent,
                            provider_leg_request_id=leg_request_id,
                            provider_profile=provider_profile,
                            endpoint_family=config.openai_compatible_endpoint,
                            tool_identity_by_provider_name=surface[
                                "tool_identity_by_provider_name"
                            ],
                            env=source,
                            service_boot_id=_service_boot_id(),
                        )
                    )
                    if request_observation is not None:
                        begun = cache_observation_store.begin_dispatch(
                            request_observation
                        )
                        prompt_cache_observation_id = begun[
                            "observation_id"
                        ]
                except Exception:
                    prompt_cache_observation_id = None
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            traced_transport = bridge.wrap_transport(selected_transport)
            dispatched_request_sha256.append(hashlib.sha256(body).hexdigest())
            status_code, response_body, safe_response_headers = provider_observability.unpack_http_transport_result(
                traced_transport(url, headers, body, config.timeout_seconds)
            )
            payload = bridge.run_validated_client(
                lambda: provider_adapter.parse_openai_compatible_http_payload(
                    status_code, response_body
                )
            )
            usage_value = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else None
            normalized_leg_usage = provider_adapter.normalize_usage(
                usage_value,
                endpoint_family="chat_completions",
                retain_details=True,
            )
            leg_usage.append(normalized_leg_usage)
            if (
                ordinal == 0
                and cache_observation_store is not None
                and prompt_cache_observation_id is not None
            ):
                try:
                    prompt_cache_dispatch_observation = (
                        cache_observation_store.complete_dispatch(
                            prompt_cache_observation_id,
                            trace_id=(
                                bridge.receipt.trace_id
                                if bridge.receipt is not None
                                else None
                            ),
                            response_body=response_body,
                            normalized_usage=normalized_leg_usage,
                            safe_response_headers=safe_response_headers,
                            final_model=(
                                str(payload.get("model"))
                                if isinstance(payload.get("model"), str)
                                else None
                            ),
                            dispatch_count=1,
                            retry_count=0,
                        )
                    )
                except Exception:
                    prompt_cache_dispatch_observation = None
            return payload
        except Exception as exc:
            last_transport_error = provider_adapter._provider_trace_reason_label(exc)
            if (
                ordinal == 0
                and cache_observation_store is not None
                and prompt_cache_observation_id is not None
                and prompt_cache_dispatch_observation is None
            ):
                try:
                    prompt_cache_dispatch_observation = (
                        cache_observation_store.complete_dispatch(
                            prompt_cache_observation_id,
                            trace_id=(
                                bridge.receipt.trace_id
                                if bridge.receipt is not None
                                else None
                            ),
                            response_body=response_body,
                            normalized_usage=None,
                            safe_response_headers=safe_response_headers,
                            final_model=None,
                            dispatch_count=1,
                            retry_count=0,
                            transport_error=last_transport_error,
                        )
                    )
                except Exception:
                    prompt_cache_dispatch_observation = None
            raise
        finally:
            trace_records.append(
                _trace_record(
                    bridge,
                    provider_leg_ordinal=ordinal,
                    provider_leg_request_id=leg_request_id,
                )
            )

    outcome = await run_provider_agent_loop(
        provider_family="openai",
        provider_endpoint="chat_completions",
        operation_basis={"stable_operation_id": stable},
        parent_operation_id=(
            parent_operation_id
            if prepared_initial_request is not None
            else None
        ),
        initial_input=base_body["messages"],
        known_tool_schemas=surface["known_tool_schemas"],
        capability_decision_bindings=surface["capability_decision_bindings"],
        tool_identity_by_provider_name=surface["tool_identity_by_provider_name"],
        provider_name_by_tool_identity=surface["provider_name_by_tool_identity"],
        provider_call=provider_call,
        dispatcher=dispatcher,
        max_provider_legs=max_provider_legs,
        event_callback=event_callback,
        forbid_tool_dispatch=forbid_tool_dispatch,
        terminal_result_parser=(
            structured_terminal.parse_chat_completions_terminal_result
            if surface.get("terminal_result_required") is True
            else None
        ),
    )
    leg_count = int(outcome.get("provider_leg_count") or 0)
    call_count = len(outcome.get("tool_calls") or [])
    receipt_count = len(outcome.get("tool_receipts") or [])
    usage = _sum_usage(leg_usage)
    if (
        cache_observation_store is not None
        and prompt_cache_observation_id is not None
        and prompt_cache_dispatch_observation is not None
        and leg_count >= 1
    ):
        try:
            cache_observation_store.update_dispatch_count(
                prompt_cache_observation_id,
                dispatch_count=leg_count,
                retry_count=0,
            )
        except Exception:
            pass
    latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    if outcome.get("state") == "completed" and isinstance(outcome.get("final_text"), str) and outcome["final_text"].strip():
        completed = _response(
                request=request,
                config=config,
                ok=True,
                parent_operation_id=parent_operation_id,
                assistant_text=outcome["final_text"],
                usage=usage,
                provider_leg_count=leg_count,
                tool_call_count=call_count,
                tool_receipt_count=receipt_count,
                trace_records=trace_records,
                prompt_cache_request_observability=(
                    prompt_cache_request_observation
                ),
                prompt_cache_dispatch_observability=(
                    prompt_cache_dispatch_observation
                ),
                latency_ms=latency_ms,
            )
        private_terminal_result = outcome.get(
            "private_terminal_result"
        )
        if isinstance(
            private_terminal_result,
            structured_terminal.StructuredTerminalResult,
        ):
            completed["_house_private_terminal_result"] = (
                private_terminal_result
            )
        return _attach_dispatch_facts(
            completed, dispatched_request_sha256
        )
    error_class = str(
        last_transport_error or outcome.get("error_class") or "provider_agent_failed"
    )
    return _attach_dispatch_facts(
        _response(
            request=request,
            config=config,
            ok=False,
            parent_operation_id=parent_operation_id,
            usage=usage,
            error=_safe_error(error_class, "Provider-agent operation did not complete.", False),
            provider_leg_count=leg_count,
            tool_call_count=call_count,
            tool_receipt_count=receipt_count,
            trace_records=trace_records,
            prompt_cache_request_observability=(
                prompt_cache_request_observation
            ),
            prompt_cache_dispatch_observability=(
                prompt_cache_dispatch_observation
            ),
            latency_ms=latency_ms,
        ),
        dispatched_request_sha256,
    )


def run_provider_agent_live_runtime(
    request: Mapping[str, Any],
    *,
    stable_operation_id: str,
    broker: HouseMcpToolBroker | None,
    env: Mapping[str, str] | None = None,
    http_transport: HTTPTransport | None = None,
    reviewed_read_only_capabilities: Mapping[str, Mapping[str, Any]] | None = None,
    max_provider_legs: int = 8,
    event_callback: EventCallback | None = None,
    gate11_initial_request_capture: list[bytes] | None = None,
    forbid_tool_dispatch: bool = False,
    prepared_initial_request: PreparedInitialProviderRequest | None = None,
) -> dict[str, Any]:
    """Synchronous Body-runtime entrypoint; no provider retry is performed."""
    return asyncio.run(
        run_provider_agent_live_runtime_async(
            request,
            stable_operation_id=stable_operation_id,
            broker=broker,
            env=env,
            http_transport=http_transport,
            reviewed_read_only_capabilities=reviewed_read_only_capabilities,
            max_provider_legs=max_provider_legs,
            event_callback=event_callback,
            gate11_initial_request_capture=gate11_initial_request_capture,
            forbid_tool_dispatch=forbid_tool_dispatch,
            prepared_initial_request=prepared_initial_request,
        )
    )


__all__ = [
    "BACKEND_ROOT_ENV",
    "ENABLED_ENV",
    "LEDGER_DIRECTORY",
    "LEDGER_FILENAME",
    "PROMPT_CACHE_REQUEST_OBSERVABILITY_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "TOOL_BRANCH_VISIBLE_ACK_INSTRUCTION",
    "TRACE_ROOT_ENV",
    "EventCallback",
    "PreparedInitialProviderRequest",
    "prepare_initial_provider_request",
    "run_provider_agent_live_runtime",
    "run_provider_agent_live_runtime_async",
]
