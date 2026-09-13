"""Durable dispatcher joining normalized provider calls to the MCP broker."""

from __future__ import annotations

from typing import Any, Mapping

from house_mcp_tool_broker_v0 import HouseMcpToolBroker, McpToolBrokerError
from house_provider_agent_tool_contract_v0 import normalize_tool_result
from house_tool_operation_ledger_v0 import ToolOperationLedger, ToolOperationLedgerError


class HouseProviderAgentToolRuntimeError(RuntimeError):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class


class HouseProviderAgentToolRuntime:
    """Callable loop dispatcher with durable terminal replay and no policy role."""

    def __init__(self, broker: HouseMcpToolBroker, ledger: ToolOperationLedger) -> None:
        self.broker = broker
        self.ledger = ledger

    def __call__(self, tool_call: Mapping[str, Any]) -> dict[str, Any]:
        return self.dispatch(tool_call)

    def dispatch(self, tool_call: Mapping[str, Any]) -> dict[str, Any]:
        try:
            registration = self.ledger.register_call(tool_call)
        except ToolOperationLedgerError as exc:
            raise HouseProviderAgentToolRuntimeError(exc.error_class, str(exc)) from exc

        replay = registration.get("replay_payload")
        if registration.get("disposition") in {"completed_replay", "failed_replay"}:
            if isinstance(replay, Mapping):
                return dict(replay)
            raise HouseProviderAgentToolRuntimeError(
                "terminal_replay_payload_missing", "Terminal tool replay payload is unavailable."
            )
        if registration.get("should_dispatch") is not True:
            raise HouseProviderAgentToolRuntimeError(
                f"tool_call_{registration.get('state', 'unknown')}",
                "Tool call is not dispatchable.",
            )

        try:
            running = self.ledger.mark_running(str(tool_call.get("tool_call_id")))
        except ToolOperationLedgerError as exc:
            raise HouseProviderAgentToolRuntimeError(exc.error_class, str(exc)) from exc
        if running.get("disposition") != "running":
            raise HouseProviderAgentToolRuntimeError(
                "tool_call_already_running", "Another runtime already owns this tool call."
            )

        if tool_call.get("argument_parse_state") != "complete":
            result = normalize_tool_result(
                tool_call,
                state="failed",
                result={"available": False},
                error_class=f"arguments_{tool_call.get('argument_parse_state', 'invalid')}",
            )
        else:
            try:
                broker_result = self.broker.call_tool(
                    str(tool_call.get("tool_identity")),
                    tool_call.get("arguments"),
                    expected_tool_schema_identity=str(tool_call.get("tool_schema_identity")),
                )
                broker_payload = broker_result["result"]
                artifact_refs = ()
                if isinstance(broker_payload, Mapping):
                    top_level_refs = broker_payload.get("artifact_refs", ())
                    if isinstance(top_level_refs, list):
                        artifact_refs = top_level_refs
                result = normalize_tool_result(
                    tool_call,
                    state="succeeded",
                    result=broker_payload,
                    artifact_refs=artifact_refs,
                )
            except McpToolBrokerError as exc:
                result = normalize_tool_result(
                    tool_call,
                    state="failed",
                    result={"available": False},
                    error_class=exc.error_class,
                )

        try:
            self.ledger.record_result(result)
        except ToolOperationLedgerError as exc:
            raise HouseProviderAgentToolRuntimeError(exc.error_class, str(exc)) from exc
        return result


__all__ = ["HouseProviderAgentToolRuntime", "HouseProviderAgentToolRuntimeError"]
