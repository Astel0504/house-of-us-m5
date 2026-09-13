"""Provider-safe projection of reviewed read-only House MCP tools.

The MCP broker keeps the exact durable tool identity and schema authority.
This module adds only the provider-facing alias, native schema shape, and a
canonical capability-decision binding used by the provider-agent loop.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Mapping

import house_provider_agent_tool_contract_v0 as tool_contract


SCHEMA_VERSION = "house_provider_tool_surface_v0"
CAPABILITY_DECISION_SCHEMA_VERSION = "house_provider_tool_capability_decision_v0"

_PROVIDER_KEYS = {
    ("openai", "chat_completions"),
    ("openai", "responses"),
    ("anthropic", "messages"),
    ("gemini", "generate_content"),
}
_ALIAS_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ALIAS_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")

DEFAULT_REVIEWED_READ_ONLY_CAPABILITIES: dict[str, dict[str, str]] = {
    "memory_door": {
        "capability_id": "mcp.safe_memory_status_retrieval",
        "action_class": "safe_lookup",
        "risk_level": "low",
    },
    "browser": {
        "capability_id": "mcp.public_browser_read",
        "action_class": "public_web_read",
        "risk_level": "low",
    },
}

GENERIC_READ_ONLY_CAPABILITY_PROFILE = "read_only_low_v0"
GENERIC_REVIEWED_READ_ONLY_CAPABILITY: dict[str, str] = {
    "capability_id": "mcp.generic_read_only",
    "action_class": "safe_lookup",
    "risk_level": "low",
}


class ProviderToolSurfaceError(ValueError):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class


def _provider(provider_family: str, provider_endpoint: str) -> tuple[str, str]:
    key = (str(provider_family or "").strip().lower(), str(provider_endpoint or "").strip().lower())
    if key not in _PROVIDER_KEYS:
        raise ProviderToolSurfaceError(
            "unsupported_provider_endpoint", "Provider endpoint is unsupported."
        )
    return key


def provider_safe_tool_name(tool_identity: str) -> str:
    """Return one stable portable function name for an exact broker identity."""
    if not isinstance(tool_identity, str) or not tool_identity.strip():
        raise ProviderToolSurfaceError("invalid_tool_identity", "Tool identity is malformed.")
    identity = tool_identity.strip()
    try:
        digest = tool_contract.canonical_sha256({"tool_identity": identity})[:12]
    except tool_contract.ProviderAgentToolContractError as exc:
        raise ProviderToolSurfaceError("invalid_tool_identity", "Tool identity is malformed.") from exc
    readable = _ALIAS_UNSAFE_RE.sub("_", identity).strip("_-") or "tool"
    prefix = ("house_" + readable)[:51].rstrip("_-") or "house_tool"
    alias = f"{prefix}_{digest}"
    if _ALIAS_RE.fullmatch(alias) is None:
        raise ProviderToolSurfaceError("invalid_provider_alias", "Provider tool alias is malformed.")
    return alias


def _reviewed_capabilities(
    values: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, str]]:
    source: Mapping[str, Mapping[str, Any]] = (
        values if values is not None else DEFAULT_REVIEWED_READ_ONLY_CAPABILITIES
    )
    reviewed: dict[str, dict[str, str]] = {}
    for server_id, decision in source.items():
        if not isinstance(server_id, str) or not server_id or not isinstance(decision, Mapping):
            raise ProviderToolSurfaceError(
                "invalid_reviewed_capability", "Reviewed capability mapping is malformed."
            )
        projected: dict[str, str] = {}
        for field in ("capability_id", "action_class", "risk_level"):
            value = decision.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ProviderToolSurfaceError(
                    "invalid_reviewed_capability", "Reviewed capability mapping is malformed."
                )
            projected[field] = value.strip()
        reviewed[server_id] = projected
    return reviewed


def _capability_decision(tool: Mapping[str, Any], reviewed: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schema_version": CAPABILITY_DECISION_SCHEMA_VERSION,
        "capability_id": reviewed["capability_id"],
        "executor_family": "mcp_tool_broker",
        "decision": "allowed",
        "decision_scope": "protected_standing_live_read_only",
        "action_class": reviewed["action_class"],
        "risk_level": reviewed["risk_level"],
        "server_id": tool["server_id"],
        "tool_identity": tool["tool_identity"],
        "tool_schema_identity": tool["tool_schema_identity"],
        "server_enabled": True,
        "available_to_solen": True,
        "reviewed_read_only": True,
    }


def _native_definition(
    key: tuple[str, str], *, name: str, description: str, input_schema: Mapping[str, Any]
) -> dict[str, Any]:
    schema = copy.deepcopy(dict(input_schema))
    if key == ("openai", "chat_completions"):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": schema,
            },
        }
    if key == ("openai", "responses"):
        return {
            "type": "function",
            "name": name,
            "description": description,
            "parameters": schema,
        }
    if key == ("anthropic", "messages"):
        return {"name": name, "description": description, "input_schema": schema}
    return {
        "functionDeclarations": [
            {"name": name, "description": description, "parameters": schema}
        ]
    }


def build_provider_tool_surface(
    *,
    provider_family: str,
    provider_endpoint: str,
    broker: Any,
    reviewed_read_only_capabilities: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a native provider tool surface from broker-authorized tools only."""
    key = _provider(provider_family, provider_endpoint)
    if not callable(getattr(broker, "search_tools", None)) or not callable(
        getattr(broker, "load_tool", None)
    ):
        raise ProviderToolSurfaceError("invalid_broker", "MCP tool broker is unavailable.")
    reviewed_by_server = _reviewed_capabilities(reviewed_read_only_capabilities)
    try:
        summaries = broker.search_tools(limit=100)
    except Exception as exc:  # broker errors remain raw-free at this boundary
        raise ProviderToolSurfaceError("broker_search_failed", "MCP tool search failed.") from exc
    if not isinstance(summaries, list):
        raise ProviderToolSurfaceError("malformed_tool_catalog", "MCP tool search result is malformed.")

    tools: list[dict[str, Any]] = []
    definitions: list[dict[str, Any]] = []
    known_tool_schemas: dict[str, str] = {}
    bindings: dict[str, str] = {}
    decisions: dict[str, dict[str, Any]] = {}
    identity_by_name: dict[str, str] = {}
    name_by_identity: dict[str, str] = {}

    for summary in sorted(summaries, key=lambda item: str(item.get("tool_identity", ""))):
        if not isinstance(summary, Mapping) or summary.get("available_to_solen") is not True:
            continue
        server_id = summary.get("server_id")
        tool_identity = summary.get("tool_identity")
        if not isinstance(tool_identity, str) or not tool_identity:
            raise ProviderToolSurfaceError("malformed_tool_catalog", "MCP tool identity is malformed.")
        try:
            loaded = broker.load_tool(tool_identity)
        except Exception as exc:
            raise ProviderToolSurfaceError("broker_load_failed", "MCP tool schema load failed.") from exc
        if not isinstance(loaded, Mapping):
            raise ProviderToolSurfaceError("malformed_tool_catalog", "MCP tool record is malformed.")
        reviewed = reviewed_by_server.get(server_id) if isinstance(server_id, str) else None
        if (
            reviewed is None
            and loaded.get("provider_capability_profile")
            == GENERIC_READ_ONLY_CAPABILITY_PROFILE
        ):
            reviewed = GENERIC_REVIEWED_READ_ONLY_CAPABILITY
        if reviewed is None:
            continue
        if (
            loaded.get("tool_identity") != tool_identity
            or loaded.get("server_id") != server_id
            or loaded.get("tool_schema_identity") != summary.get("tool_schema_identity")
            or loaded.get("available_to_solen") is not True
        ):
            raise ProviderToolSurfaceError(
                "tool_catalog_identity_mismatch", "MCP tool record changed during surface build."
            )
        schema_identity = loaded.get("tool_schema_identity")
        input_schema = loaded.get("input_schema")
        if not isinstance(schema_identity, str) or not schema_identity or not isinstance(input_schema, Mapping):
            raise ProviderToolSurfaceError("malformed_tool_schema", "MCP tool schema is malformed.")
        try:
            tool_contract.canonical_sha256(input_schema)
        except tool_contract.ProviderAgentToolContractError as exc:
            raise ProviderToolSurfaceError("malformed_tool_schema", "MCP tool schema is malformed.") from exc
        provider_name = provider_safe_tool_name(tool_identity)
        if provider_name in identity_by_name and identity_by_name[provider_name] != tool_identity:
            raise ProviderToolSurfaceError("provider_alias_collision", "Provider tool aliases collide.")
        description = " ".join(str(loaded.get("description") or "House tool").split())[:800]
        decision = _capability_decision(loaded, reviewed)
        decision_binding = tool_contract.canonical_sha256(decision)
        projection = {
            "provider_name": provider_name,
            "tool_identity": tool_identity,
            "tool_schema_identity": schema_identity,
            "description": description,
            "capability_id": reviewed["capability_id"],
            "capability_decision_binding_sha256": decision_binding,
        }
        tools.append(projection)
        definitions.append(
            _native_definition(
                key,
                name=provider_name,
                description=description,
                input_schema=input_schema,
            )
        )
        known_tool_schemas[tool_identity] = schema_identity
        bindings[tool_identity] = decision_binding
        decisions[tool_identity] = decision
        identity_by_name[provider_name] = tool_identity
        name_by_identity[tool_identity] = provider_name

    return {
        "schema_version": SCHEMA_VERSION,
        "provider_family": key[0],
        "provider_endpoint": key[1],
        "tools": tools,
        "provider_tool_definitions": definitions,
        "known_tool_schemas": known_tool_schemas,
        "capability_decision_bindings": bindings,
        "capability_decisions": decisions,
        "tool_identity_by_provider_name": identity_by_name,
        "provider_name_by_tool_identity": name_by_identity,
        "raw_content_present": False,
    }


__all__ = [
    "CAPABILITY_DECISION_SCHEMA_VERSION",
    "DEFAULT_REVIEWED_READ_ONLY_CAPABILITIES",
    "GENERIC_READ_ONLY_CAPABILITY_PROFILE",
    "GENERIC_REVIEWED_READ_ONLY_CAPABILITY",
    "ProviderToolSurfaceError",
    "SCHEMA_VERSION",
    "build_provider_tool_surface",
    "provider_safe_tool_name",
]
