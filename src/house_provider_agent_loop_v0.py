"""Injected provider-neutral agent loop with the Gate B fake compatibility name."""

from __future__ import annotations

import asyncio
import inspect
import re
from typing import Any, Awaitable, Callable, Mapping, Sequence

from house_provider_agent_tool_contract_v0 import (
    build_tool_receipt,
    derive_parent_operation_id,
    derive_provider_leg_id,
    normalize_tool_result,
)
from house_provider_tool_normalizers_v0 import (
    ProviderToolNormalizationError,
    normalize_provider_response,
    serialize_tool_results,
)


ProviderCall = Callable[[Mapping[str, Any]], Mapping[str, Any] | Awaitable[Mapping[str, Any]]]
ToolDispatcher = Callable[[Mapping[str, Any]], Any]
EventCallback = Callable[[Mapping[str, Any]], Any]
TerminalResultParser = Callable[[Mapping[str, Any]], Any]


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _emit(event_callback: EventCallback | None, event: Mapping[str, Any]) -> None:
    """Deliver one raw-free lifecycle event; event durability belongs to the injected owner."""
    if event_callback is not None:
        await _await(event_callback(dict(event)))


def _cancelled(cancel_check: Callable[[], bool] | None) -> bool:
    return bool(cancel_check and cancel_check())


async def run_provider_agent_loop(
    *,
    provider_family: str,
    provider_endpoint: str,
    operation_basis: Mapping[str, Any],
    parent_operation_id: str | None = None,
    initial_input: Sequence[Mapping[str, Any]],
    known_tool_schemas: Mapping[str, str],
    capability_decision_bindings: Mapping[str, str],
    tool_identity_by_provider_name: Mapping[str, str] | None = None,
    provider_name_by_tool_identity: Mapping[str, str] | None = None,
    provider_call: ProviderCall,
    dispatcher: ToolDispatcher,
    cancel_check: Callable[[], bool] | None = None,
    max_provider_legs: int = 8,
    event_callback: EventCallback | None = None,
    forbid_tool_dispatch: bool = False,
    terminal_result_parser: TerminalResultParser | None = None,
) -> dict[str, Any]:
    """Run bounded tool legs plus one reserved tools-disabled synthesis leg."""
    if not isinstance(max_provider_legs, int) or isinstance(max_provider_legs, bool) or max_provider_legs < 1:
        raise ValueError("max_provider_legs must be a positive integer")
    if parent_operation_id is not None:
        if (
            not isinstance(parent_operation_id, str)
            or re.fullmatch(
                r"hpaop_[0-9a-f]{64}",
                parent_operation_id,
            )
            is None
        ):
            raise ValueError("parent_operation_id is malformed")
    else:
        parent_operation_id = derive_parent_operation_id(
            operation_basis
        )
    prior_responses: list[Mapping[str, Any]] = []
    result_batches: list[list[dict[str, Any]]] = []
    calls: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    acknowledgement_emitted = False

    # ``max_provider_legs`` remains the tool/research budget.  The extra
    # iteration is a different, tools-disabled synthesis opportunity rather
    # than another chance to dispatch tools.
    for ordinal in range(max_provider_legs + 1):
        tools_enabled = ordinal < max_provider_legs
        leg_id = derive_provider_leg_id(parent_operation_id, ordinal)
        if _cancelled(cancel_check):
            await _emit(event_callback, {
                "event_type": "operation_cancelled",
                "parent_operation_id": parent_operation_id,
                "provider_leg_ordinal": ordinal,
                "stage": "before_provider_leg",
                "terminal_state": "cancelled",
            })
            return _outcome("cancelled", parent_operation_id, ordinal, calls, results, receipts)
        request = {
            "provider_family": provider_family,
            "provider_endpoint": provider_endpoint,
            "parent_operation_id": parent_operation_id,
            "provider_leg_ordinal": ordinal,
            "provider_leg_id": leg_id,
            "tools_enabled": tools_enabled,
            "initial_input": list(initial_input),
            "prior_provider_responses": list(prior_responses),
            "tool_result_batches": list(result_batches),
        }
        await _emit(event_callback, {
            "event_type": "provider_leg_started",
            "parent_operation_id": parent_operation_id,
            "provider_leg_id": leg_id,
            "provider_leg_ordinal": ordinal,
            "stage": "provider_leg_started" if tools_enabled else "final_synthesis_started",
            "stage_category": "provider" if tools_enabled else "synthesis",
        })
        try:
            raw_response = await _await(provider_call(request))
            if terminal_result_parser is not None:
                terminal_result = terminal_result_parser(raw_response)
                visible = getattr(terminal_result, "visible_response", None)
                if not isinstance(visible, str) or not visible.strip():
                    raise ProviderToolNormalizationError(
                        "terminal_visible_response_invalid",
                        "Terminal result has no visible response.",
                    )
                await _emit(event_callback, {
                    "event_type": "assistant_final",
                    "parent_operation_id": parent_operation_id,
                    "provider_leg_id": leg_id,
                    "provider_leg_ordinal": ordinal,
                    "visible_text": visible,
                    "terminal_state": "completed",
                    "terminal_result_locally_consumed": True,
                })
                return _outcome(
                    "completed",
                    parent_operation_id,
                    ordinal + 1,
                    calls,
                    results,
                    receipts,
                    final_text=visible,
                    private_terminal_result=terminal_result,
                )
            normalized = normalize_provider_response(
                provider_family=provider_family,
                provider_endpoint=provider_endpoint,
                response=raw_response,
                parent_operation_id=parent_operation_id,
                provider_leg_ordinal=ordinal,
                known_tool_schemas=known_tool_schemas,
                capability_decision_bindings=capability_decision_bindings,
                tool_identity_by_provider_name=tool_identity_by_provider_name,
            )
        except ProviderToolNormalizationError as exc:
            await _emit(event_callback, {
                "event_type": "operation_failed",
                "parent_operation_id": parent_operation_id,
                "provider_leg_id": leg_id,
                "provider_leg_ordinal": ordinal,
                "stage": "provider_response_normalization",
                "terminal_state": "failed",
                "safe_error_class": exc.error_class,
            })
            return _outcome("failed", parent_operation_id, ordinal + 1, calls, results, receipts,
                            error_class=exc.error_class)
        except Exception as exc:  # injected transport failure; no hidden retry
            safe_error_class = str(
                getattr(exc, "error_class", type(exc).__name__)
            )
            await _emit(event_callback, {
                "event_type": "operation_failed",
                "parent_operation_id": parent_operation_id,
                "provider_leg_id": leg_id,
                "provider_leg_ordinal": ordinal,
                "stage": (
                    "terminal_result_validation"
                    if terminal_result_parser is not None
                    and hasattr(exc, "error_class")
                    else "provider_call"
                ),
                "terminal_state": "failed",
                "safe_error_class": safe_error_class,
            })
            return _outcome("failed", parent_operation_id, ordinal + 1, calls, results, receipts,
                            error_class=safe_error_class)
        prior_responses.append(raw_response)
        leg_calls = normalized["tool_calls"]
        if not leg_calls:
            final_text = normalized["text"]
            if isinstance(final_text, str) and final_text.strip():
                await _emit(event_callback, {
                    "event_type": "assistant_final",
                    "parent_operation_id": parent_operation_id,
                    "provider_leg_id": leg_id,
                    "provider_leg_ordinal": ordinal,
                    "visible_text": final_text.strip(),
                    "terminal_state": "completed",
                })
                return _outcome("completed", parent_operation_id, ordinal + 1, calls, results, receipts,
                                final_text=final_text)
            await _emit(event_callback, {
                "event_type": "operation_failed",
                "parent_operation_id": parent_operation_id,
                "provider_leg_id": leg_id,
                "provider_leg_ordinal": ordinal,
                "stage": "final_response",
                "terminal_state": "failed",
                "safe_error_class": "empty_final_response",
            })
            return _outcome(
                "failed", parent_operation_id, ordinal + 1, calls, results, receipts,
                error_class="empty_final_response",
            )
        if not tools_enabled:
            await _emit(event_callback, {
                "event_type": "operation_failed",
                "parent_operation_id": parent_operation_id,
                "provider_leg_id": leg_id,
                "provider_leg_ordinal": ordinal,
                "stage": "tools_disabled_synthesis",
                "terminal_state": "failed",
                "safe_error_class": "tools_requested_on_synthesis_leg",
            })
            return _outcome(
                "failed", parent_operation_id, ordinal + 1, calls, results, receipts,
                error_class="tools_requested_on_synthesis_leg",
            )
        if forbid_tool_dispatch:
            await _emit(event_callback, {
                "event_type": "operation_failed",
                "parent_operation_id": parent_operation_id,
                "provider_leg_id": leg_id,
                "provider_leg_ordinal": ordinal,
                "stage": "gate12_tool_dispatch_forbidden",
                "terminal_state": "failed",
                "safe_error_class": "tool_dispatch_forbidden",
            })
            return _outcome(
                "failed",
                parent_operation_id,
                ordinal + 1,
                calls,
                results,
                receipts,
                error_class="tool_dispatch_forbidden",
            )
        acknowledgement = normalized["text"]
        if (
            not acknowledgement_emitted
            and isinstance(acknowledgement, str)
            and acknowledgement.strip()
        ):
            await _emit(event_callback, {
                "event_type": "assistant_acknowledgement",
                "parent_operation_id": parent_operation_id,
                "provider_leg_id": leg_id,
                "provider_leg_ordinal": ordinal,
                "visible_text": acknowledgement.strip(),
            })
            acknowledgement_emitted = True
        calls.extend(leg_calls)
        if _cancelled(cancel_check):
            await _emit(event_callback, {
                "event_type": "operation_cancelled",
                "parent_operation_id": parent_operation_id,
                "provider_leg_id": leg_id,
                "provider_leg_ordinal": ordinal,
                "stage": "before_tool_dispatch",
                "terminal_state": "cancelled",
            })
            return _outcome("cancelled", parent_operation_id, ordinal + 1, calls, results, receipts)

        async def dispatch(call: Mapping[str, Any]) -> dict[str, Any]:
            safe_identity = {
                "parent_operation_id": parent_operation_id,
                "provider_leg_id": leg_id,
                "provider_leg_ordinal": ordinal,
                "tool_call_id": call.get("tool_call_id"),
                "tool_identity": call.get("tool_identity"),
                "stage_category": "tool",
            }
            await _emit(event_callback, {
                **safe_identity,
                "event_type": "tool_stage_changed",
                "stage": "tool_dispatch_started",
            })
            if call.get("argument_parse_state") != "complete":
                normalized_result = normalize_tool_result(
                    call, state="failed", result={"available": False},
                    error_class=f"arguments_{call.get('argument_parse_state')}",
                )
                await _emit(event_callback, {
                    **safe_identity,
                    "event_type": "tool_stage_changed",
                    "stage": "tool_dispatch_failed",
                })
                return normalized_result
            try:
                dispatched = await _await(dispatcher(call))
                if isinstance(dispatched, Mapping) and "state" in dispatched:
                    state = str(dispatched["state"])
                    payload = dispatched.get("result")
                    artifacts = dispatched.get("artifact_refs", ())
                    error = dispatched.get("error_class")
                else:
                    state, payload, artifacts, error = "succeeded", dispatched, (), None
                normalized_result = normalize_tool_result(
                    call, state=state, result=payload, artifact_refs=artifacts, error_class=error,
                )
                await _emit(event_callback, {
                    **safe_identity,
                    "event_type": "tool_stage_changed",
                    "stage": "tool_dispatch_succeeded" if state == "succeeded" else "tool_dispatch_failed",
                })
                return normalized_result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                normalized_result = normalize_tool_result(
                    call, state="failed", result={"available": False}, error_class=type(exc).__name__,
                )
                await _emit(event_callback, {
                    **safe_identity,
                    "event_type": "tool_stage_changed",
                    "stage": "tool_dispatch_failed",
                })
                return normalized_result

        leg_results = list(await asyncio.gather(*(dispatch(call) for call in leg_calls)))
        results.extend(leg_results)
        receipts.extend(build_tool_receipt(result) for result in leg_results)
        result_batches.append(
            serialize_tool_results(
                provider_family,
                provider_endpoint,
                leg_results,
                provider_name_by_tool_identity=provider_name_by_tool_identity,
            )
        )
        await _emit(event_callback, {
            "event_type": "provider_continuing",
            "parent_operation_id": parent_operation_id,
            "provider_leg_id": leg_id,
            "provider_leg_ordinal": ordinal,
            "stage_category": "provider",
            "stage": "tool_results_ready",
        })

    raise AssertionError("provider-agent loop exhausted without a terminal outcome")


def _outcome(
    state: str,
    parent_operation_id: str,
    provider_leg_count: int,
    calls: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    receipts: Sequence[Mapping[str, Any]],
    *,
    final_text: str | None = None,
    error_class: str | None = None,
    private_terminal_result: Any = None,
) -> dict[str, Any]:
    return {
        "state": state,
        "parent_operation_id": parent_operation_id,
        "provider_leg_count": provider_leg_count,
        "final_text": final_text,
        "error_class": error_class,
        "tool_calls": list(calls),
        "tool_results": list(results),
        "tool_receipts": list(receipts),
        "private_terminal_result": private_terminal_result,
    }


async def run_fake_provider_agent_loop(**kwargs: Any) -> dict[str, Any]:
    """Compatibility name retained for the original fixture-only Gate B callers."""
    return await run_provider_agent_loop(**kwargs)


__all__ = ["EventCallback", "run_fake_provider_agent_loop", "run_provider_agent_loop"]
