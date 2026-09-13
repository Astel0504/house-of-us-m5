"""Durable MCP catalog and compact tool dispatcher for House.

The broker persists credential-free server configuration and discovered tool
schemas.  Live MCP transports are deliberately injected by the caller; this
module does not read credentials, open network connections, or create local
processes by itself.

Connection caching plus connect/list/call/disconnect lifecycle is adapted from
AionsHome ``aion-chat/mcp_client.py`` at commit
6cf08792c5c8858f740a81f5cd097e9cbcfa6532 (MIT License):
https://github.com/death34018-hue/AionsHome
House adds durable safe configuration, schema bindings, per-tool availability,
and raw-free health/error projection.

Upstream MIT notice:
Copyright (c) 2026 death34018-hue

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import copy
from functools import wraps
import json
import re
import threading
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import parse_qsl, urlsplit

import house_provider_agent_tool_contract_v0 as tool_contract


SCHEMA_VERSION = "house_mcp_tool_broker_v0"
CATALOG_SCHEMA_VERSION = "house_mcp_tool_catalog_v0"
CATALOG_BINDING_SCHEMA_VERSION = "house_mcp_tool_catalog_source_binding_v1"
SERVER_SCHEMA_VERSION = "house_mcp_server_config_v0"
TOOL_SCHEMA_VERSION = "house_mcp_discovered_tool_v0"
CONNECTION_TEST_SCHEMA_VERSION = "house_mcp_connection_test_v0"
DISCOVERY_SCHEMA_VERSION = "house_mcp_tool_discovery_v0"
HEALTH_SCHEMA_VERSION = "house_mcp_tool_broker_health_v0"
CALL_SCHEMA_VERSION = "house_mcp_tool_call_result_v0"

TRANSPORTS = frozenset({"streamable_http", "sse", "stdio", "in_process"})
REMOTE_TRANSPORTS = frozenset({"streamable_http", "sse"})
LOCAL_TRANSPORTS = TRANSPORTS - REMOTE_TRANSPORTS
PROVIDER_CAPABILITY_PROFILES = frozenset({"unreviewed", "read_only_low_v0"})
DEFAULT_PROVIDER_CAPABILITY_PROFILE = "unreviewed"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_TOKEN_MARKER_RE = re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|bearer|authorization|secret|password)")
_SENSITIVE_QUERY_KEYS = frozenset({
    "token", "access_token", "api_key", "key", "secret", "client_secret",
    "password", "authorization", "signature", "sig",
})


class McpToolBrokerError(ValueError):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class


class McpSession(Protocol):
    def list_tools(self) -> list[Mapping[str, Any]]: ...

    def call_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> Any: ...


SessionConnector = Callable[[Mapping[str, Any]], McpSession]


def _serialized(method: Callable[..., Any]) -> Callable[..., Any]:
    """Serialize one broker instance across catalog and session operations."""

    @wraps(method)
    def locked(self: "HouseMcpToolBroker", *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return locked


def _safe_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise McpToolBrokerError("invalid_identity", f"{field} is malformed.")
    return value


def _safe_text(value: Any, field: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise McpToolBrokerError("invalid_config", f"{field} must be text.")
    text = " ".join(value.strip().split())
    if not text or len(text) > limit:
        raise McpToolBrokerError("invalid_config", f"{field} is outside its bound.")
    return text


def _safe_error_class(exc: BaseException) -> str:
    value = getattr(exc, "error_class", None) or type(exc).__name__
    text = re.sub(r"[^A-Za-z0-9_.:-]", "_", str(value))[:120]
    return text or "mcp_connection_failed"


def _remote_endpoint(value: Any) -> str:
    endpoint = _safe_text(value, "endpoint_url", limit=1000)
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise McpToolBrokerError("invalid_endpoint", "Remote endpoint must be an HTTP(S) URL.")
    if parsed.username is not None or parsed.password is not None:
        raise McpToolBrokerError("endpoint_contains_credentials", "Endpoint must not embed credentials.")
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    sensitive_query = any(
        re.sub(r"-", "_", key.casefold()) in _SENSITIVE_QUERY_KEYS
        or any(
            re.sub(r"-", "_", key.casefold()).endswith(f"_{suffix}")
            for suffix in ("token", "key", "secret", "password", "authorization", "signature")
        )
        or value.strip().casefold().startswith("bearer ")
        for key, value in query_pairs
    )
    if parsed.fragment or _TOKEN_MARKER_RE.search(parsed.path) or sensitive_query:
        raise McpToolBrokerError(
            "endpoint_contains_credentials", "Endpoint must not contain fragment or credential material."
        )
    return endpoint


def _backend_target(value: Any) -> str:
    target = _safe_text(value, "backend_target", limit=256)
    if _TARGET_RE.fullmatch(target) is None or any(marker in target for marker in ("?", "#", "=")):
        raise McpToolBrokerError("invalid_backend_target", "Backend target is malformed.")
    return target


def _credential_ref(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    return _safe_id(value, "credential_ref_id")


def _provider_capability_profile(value: Any) -> str:
    if value not in PROVIDER_CAPABILITY_PROFILES:
        raise McpToolBrokerError(
            "invalid_provider_capability_profile",
            "Tool provider capability profile is unsupported.",
        )
    return str(value)


def _server_record(
    *,
    server_id: Any,
    human_name: Any,
    transport: Any,
    endpoint_url: Any = None,
    backend_target: Any = None,
    credential_ref_id: Any = None,
    enabled: Any = True,
    prior: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    sid = _safe_id(server_id, "server_id")
    if transport not in TRANSPORTS:
        raise McpToolBrokerError("unsupported_transport", "MCP transport is unsupported.")
    if not isinstance(enabled, bool):
        raise McpToolBrokerError("invalid_config", "enabled must be boolean.")
    if transport in REMOTE_TRANSPORTS:
        endpoint = _remote_endpoint(endpoint_url)
        target = None
        if backend_target not in {None, ""}:
            raise McpToolBrokerError("invalid_config", "Remote transports do not accept a backend target.")
    else:
        target = _backend_target(backend_target)
        endpoint = None
        if endpoint_url not in {None, ""}:
            raise McpToolBrokerError("invalid_config", "Local transports do not accept an endpoint URL.")
    previous = prior if isinstance(prior, Mapping) else {}
    return {
        "schema_version": SERVER_SCHEMA_VERSION,
        "server_id": sid,
        "human_name": _safe_text(human_name, "human_name", limit=160),
        "transport": transport,
        "endpoint_url": endpoint,
        "backend_target": target,
        "credential_ref_id": _credential_ref(credential_ref_id),
        "enabled": enabled,
        "last_test_state": previous.get("last_test_state", "not_tested"),
        "last_error_class": previous.get("last_error_class"),
    }


def _empty_catalog() -> dict[str, Any]:
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "servers": {},
        "tools": {},
        "source_bindings": {},
    }


class HouseMcpToolBroker:
    def __init__(self, catalog_path: str | Path, *, connector: SessionConnector | None = None) -> None:
        self.catalog_path = Path(catalog_path)
        self._connector = connector
        self._sessions: dict[str, McpSession] = {}
        self._lock = threading.RLock()
        if not self.catalog_path.exists():
            self._write(_empty_catalog())
        else:
            self._read()

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise McpToolBrokerError("malformed_catalog", "MCP catalog could not be read.") from exc
        if not isinstance(payload, Mapping) or payload.get("schema_version") != CATALOG_SCHEMA_VERSION:
            raise McpToolBrokerError("malformed_catalog", "MCP catalog schema is unsupported.")
        servers = payload.get("servers")
        tools = payload.get("tools")
        source_bindings = payload.get("source_bindings", {})
        if (
            not isinstance(servers, Mapping)
            or not isinstance(tools, Mapping)
            or not isinstance(source_bindings, Mapping)
        ):
            raise McpToolBrokerError("malformed_catalog", "MCP catalog collections are malformed.")
        validated_servers: dict[str, Any] = {}
        for server_id, server in servers.items():
            if not isinstance(server, Mapping) or server.get("server_id") != server_id:
                raise McpToolBrokerError("malformed_catalog", "MCP server record is malformed.")
            validated_servers[server_id] = _server_record(
                server_id=server_id,
                human_name=server.get("human_name"),
                transport=server.get("transport"),
                endpoint_url=server.get("endpoint_url"),
                backend_target=server.get("backend_target"),
                credential_ref_id=server.get("credential_ref_id"),
                enabled=server.get("enabled"),
                prior=server,
            )
        return {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "servers": validated_servers,
            "tools": copy.deepcopy(dict(tools)),
            "source_bindings": copy.deepcopy(dict(source_bindings)),
        }

    def _write(self, payload: Mapping[str, Any]) -> None:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.catalog_path.with_suffix(self.catalog_path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8"
        )
        temp_path.replace(self.catalog_path)

    def _server(self, server_id: str, *, require_enabled: bool = False) -> dict[str, Any]:
        catalog = self._read()
        server = catalog["servers"].get(_safe_id(server_id, "server_id"))
        if server is None:
            raise McpToolBrokerError("server_not_found", "MCP server is not configured.")
        if require_enabled and server["enabled"] is not True:
            raise McpToolBrokerError("server_disabled", "MCP server is disabled.")
        return server

    @_serialized
    def add_server(
        self,
        *,
        server_id: str,
        human_name: str,
        transport: str,
        endpoint_url: str | None = None,
        backend_target: str | None = None,
        credential_ref_id: str | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        catalog = self._read()
        if server_id in catalog["servers"]:
            raise McpToolBrokerError("server_already_exists", "MCP server is already configured.")
        record = _server_record(
            server_id=server_id,
            human_name=human_name,
            transport=transport,
            endpoint_url=endpoint_url,
            backend_target=backend_target,
            credential_ref_id=credential_ref_id,
            enabled=enabled,
        )
        catalog["servers"][record["server_id"]] = record
        self._write(catalog)
        return copy.deepcopy(record)

    @_serialized
    def update_server(self, server_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {
            "human_name", "transport", "endpoint_url", "backend_target",
            "credential_ref_id", "enabled",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise McpToolBrokerError("invalid_config", "Unknown MCP server configuration field.")
        catalog = self._read()
        current = catalog["servers"].get(_safe_id(server_id, "server_id"))
        if current is None:
            raise McpToolBrokerError("server_not_found", "MCP server is not configured.")
        values = {key: changes.get(key, current.get(key)) for key in allowed}
        updated = _server_record(server_id=server_id, prior=current, **values)
        connection_fields = ("transport", "endpoint_url", "backend_target", "credential_ref_id")
        connection_changed = any(current.get(key) != updated.get(key) for key in connection_fields)
        catalog["servers"][server_id] = updated
        if connection_changed:
            catalog["tools"] = {
                key: value for key, value in catalog["tools"].items()
                if not isinstance(value, Mapping) or value.get("server_id") != server_id
            }
        self.disconnect(server_id)
        self._write(catalog)
        return copy.deepcopy(updated)

    @_serialized
    def disable_server(self, server_id: str) -> dict[str, Any]:
        return self.update_server(server_id, enabled=False)

    @_serialized
    def list_servers(self) -> list[dict[str, Any]]:
        catalog = self._read()
        health = {item["server_id"]: item for item in self.safe_health()["servers"]}
        return [
            {**copy.deepcopy(server), **health[server_id]}
            for server_id, server in sorted(catalog["servers"].items())
        ]

    @_serialized
    def list_tools(self, server_id: str | None = None) -> list[dict[str, Any]]:
        """Return safe summaries for all discovered tools, including unavailable ones."""

        catalog = self._read()
        selected_server_id = None
        if server_id is not None:
            selected_server_id = _safe_id(server_id, "server_id")
            if selected_server_id not in catalog["servers"]:
                raise McpToolBrokerError("server_not_found", "MCP server is not configured.")
        tools = [
            self._tool_summary(tool)
            for tool in catalog["tools"].values()
            if isinstance(tool, Mapping)
            and (selected_server_id is None or tool.get("server_id") == selected_server_id)
        ]
        return sorted(tools, key=lambda item: item["tool_identity"])

    @_serialized
    def connect(self, server_id: str) -> McpSession:
        server = self._server(server_id, require_enabled=True)
        if server_id in self._sessions:
            return self._sessions[server_id]
        if self._connector is None:
            raise McpToolBrokerError("connector_not_configured", "No MCP session connector is configured.")
        try:
            session = self._connector(copy.deepcopy(server))
        except Exception as exc:  # noqa: BLE001 - project only safe failure class.
            self._record_test(server_id, "failed", _safe_error_class(exc))
            raise McpToolBrokerError("connection_failed", "MCP connection failed.") from exc
        if not callable(getattr(session, "list_tools", None)) or not callable(getattr(session, "call_tool", None)):
            self._record_test(server_id, "failed", "invalid_session")
            raise McpToolBrokerError("invalid_session", "MCP connector returned an invalid session.")
        self._sessions[server_id] = session
        return session

    @_serialized
    def disconnect(self, server_id: str) -> None:
        session = self._sessions.pop(server_id, None)
        close = getattr(session, "close", None) if session is not None else None
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - disconnect is best-effort and raw-free.
                pass

    @_serialized
    def reconnect(self, server_id: str) -> McpSession:
        self.disconnect(server_id)
        return self.connect(server_id)

    def _record_test(self, server_id: str, state: str, error_class: str | None) -> None:
        catalog = self._read()
        server = catalog["servers"].get(server_id)
        if server is None:
            return
        server["last_test_state"] = state
        server["last_error_class"] = error_class
        self._write(catalog)

    @_serialized
    def test_connection(self, server_id: str) -> dict[str, Any]:
        try:
            self.connect(server_id)
        except McpToolBrokerError as exc:
            return {
                "schema_version": CONNECTION_TEST_SCHEMA_VERSION,
                "server_id": server_id,
                "ok": False,
                "state": "failed",
                "error_class": exc.error_class,
                "raw_content_present": False,
            }
        self._record_test(server_id, "connected", None)
        return {
            "schema_version": CONNECTION_TEST_SCHEMA_VERSION,
            "server_id": server_id,
            "ok": True,
            "state": "connected",
            "error_class": None,
            "raw_content_present": False,
        }

    @_serialized
    def discover_tools(self, server_id: str) -> dict[str, Any]:
        session = self.connect(server_id)
        try:
            discovered = session.list_tools()
        except Exception as exc:  # noqa: BLE001 - project only safe failure class.
            error_class = _safe_error_class(exc)
            self._record_test(server_id, "failed", error_class)
            raise McpToolBrokerError("discovery_failed", "MCP tool discovery failed.") from exc
        if not isinstance(discovered, list):
            raise McpToolBrokerError("invalid_tool_catalog", "MCP tool discovery must return a list.")
        catalog = self._read()
        prior_tools = catalog["tools"]
        records: dict[str, dict[str, Any]] = {}
        for value in discovered:
            if not isinstance(value, Mapping):
                raise McpToolBrokerError("invalid_tool_catalog", "Discovered MCP tool is malformed.")
            tool_name = _safe_id(value.get("name"), "tool_name")
            description_value = value.get("description", "")
            description = " ".join(str(description_value).strip().split())[:800]
            input_schema = value.get("input_schema", {"type": "object", "properties": {}})
            try:
                schema_sha256 = tool_contract.canonical_sha256(input_schema)
            except tool_contract.ProviderAgentToolContractError as exc:
                raise McpToolBrokerError("invalid_tool_schema", "Discovered MCP schema is malformed.") from exc
            tool_identity = f"mcp/{server_id}/{tool_name}"
            tool_schema_identity = f"mcp_schema/{schema_sha256}"
            previous = prior_tools.get(tool_identity)
            same_schema = bool(
                isinstance(previous, Mapping)
                and previous.get("tool_schema_identity") == tool_schema_identity
            )
            available = bool(same_schema and previous.get("available_to_solen") is True)
            provider_capability_profile = DEFAULT_PROVIDER_CAPABILITY_PROFILE
            if same_schema:
                previous_profile = previous.get(
                    "provider_capability_profile", DEFAULT_PROVIDER_CAPABILITY_PROFILE
                )
                provider_capability_profile = _provider_capability_profile(previous_profile)
            records[tool_identity] = {
                "schema_version": TOOL_SCHEMA_VERSION,
                "server_id": server_id,
                "tool_name": tool_name,
                "tool_identity": tool_identity,
                "description": description,
                "input_schema": copy.deepcopy(input_schema),
                "schema_sha256": schema_sha256,
                "tool_schema_identity": tool_schema_identity,
                "available_to_solen": available,
                "provider_capability_profile": provider_capability_profile,
            }
        catalog["tools"] = {
            key: value for key, value in prior_tools.items()
            if not isinstance(value, Mapping) or value.get("server_id") != server_id
        }
        catalog["tools"].update(records)
        self._write(catalog)
        self._record_test(server_id, "connected", None)
        return {
            "schema_version": DISCOVERY_SCHEMA_VERSION,
            "server_id": server_id,
            "ok": True,
            "tool_count": len(records),
            "tools": [self._tool_summary(value) for value in sorted(records.values(), key=lambda item: item["tool_identity"])],
            "raw_content_present": False,
        }

    @_serialized
    def install_bound_tools(
        self,
        server_id: str,
        *,
        definitions: list[Mapping[str, Any]],
        source_schema_version: str,
        source_sha256: str,
        available_to_solen: bool,
        provider_capability_profile: str = DEFAULT_PROVIDER_CAPABILITY_PROFILE,
    ) -> dict[str, Any]:
        """Atomically install an exact reviewed source catalog for one server."""
        sid = _safe_id(server_id, "server_id")
        if not isinstance(definitions, list) or not definitions:
            raise McpToolBrokerError(
                "invalid_tool_catalog", "Bound MCP tool catalog must be a non-empty list."
            )
        source_version = _safe_text(
            source_schema_version, "source_schema_version", limit=160
        )
        if not re.fullmatch(r"[0-9a-f]{64}", str(source_sha256)):
            raise McpToolBrokerError(
                "invalid_binding_hash", "Bound MCP tool catalog SHA-256 is malformed."
            )
        computed_source_sha256 = tool_contract.canonical_sha256(definitions)
        if computed_source_sha256 != source_sha256:
            raise McpToolBrokerError(
                "source_binding_mismatch",
                "Bound MCP tool catalog does not match its reviewed source digest.",
            )
        if not isinstance(available_to_solen, bool):
            raise McpToolBrokerError(
                "invalid_config", "available_to_solen must be boolean."
            )
        profile = _provider_capability_profile(provider_capability_profile)
        catalog = self._read()
        if sid not in catalog["servers"]:
            raise McpToolBrokerError(
                "server_not_found", "MCP server is not configured."
            )
        records: dict[str, dict[str, Any]] = {}
        for value in definitions:
            if not isinstance(value, Mapping):
                raise McpToolBrokerError(
                    "invalid_tool_catalog", "Bound MCP tool is malformed."
                )
            tool_name = _safe_id(value.get("name"), "tool_name")
            tool_identity = f"mcp/{sid}/{tool_name}"
            if tool_identity in records:
                raise McpToolBrokerError(
                    "invalid_tool_catalog", "Bound MCP tool identity is duplicated."
                )
            description = " ".join(str(value.get("description", "")).strip().split())[:800]
            input_schema = value.get(
                "input_schema", {"type": "object", "properties": {}}
            )
            try:
                schema_sha256 = tool_contract.canonical_sha256(input_schema)
            except tool_contract.ProviderAgentToolContractError as exc:
                raise McpToolBrokerError(
                    "invalid_tool_schema", "Bound MCP schema is malformed."
                ) from exc
            records[tool_identity] = {
                "schema_version": TOOL_SCHEMA_VERSION,
                "server_id": sid,
                "tool_name": tool_name,
                "tool_identity": tool_identity,
                "description": description,
                "input_schema": copy.deepcopy(input_schema),
                "schema_sha256": schema_sha256,
                "tool_schema_identity": f"mcp_schema/{schema_sha256}",
                "available_to_solen": available_to_solen,
                "provider_capability_profile": profile,
            }
        next_tools = {
            key: value
            for key, value in catalog["tools"].items()
            if not isinstance(value, Mapping) or value.get("server_id") != sid
        }
        next_tools.update(records)
        binding = {
            "schema_version": CATALOG_BINDING_SCHEMA_VERSION,
            "server_id": sid,
            "source_schema_version": source_version,
            "source_sha256": source_sha256,
            "tool_count": len(records),
        }
        changed = (
            catalog["tools"] != next_tools
            or catalog["source_bindings"].get(sid) != binding
        )
        if changed:
            catalog["tools"] = next_tools
            catalog["source_bindings"][sid] = binding
            self._write(catalog)
        return {
            **copy.deepcopy(binding),
            "ok": True,
            "changed": changed,
            "available_tool_count": sum(
                item["available_to_solen"] is True for item in records.values()
            ),
        }

    @_serialized
    def source_binding(self, server_id: str) -> dict[str, Any] | None:
        catalog = self._read()
        binding = catalog["source_bindings"].get(_safe_id(server_id, "server_id"))
        return copy.deepcopy(dict(binding)) if isinstance(binding, Mapping) else None

    @_serialized
    def toggle_tool(
        self,
        tool_identity: str,
        *,
        available_to_solen: bool,
        provider_capability_profile: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(available_to_solen, bool):
            raise McpToolBrokerError("invalid_availability", "Tool availability must be boolean.")
        catalog = self._read()
        tool = catalog["tools"].get(tool_identity)
        if not isinstance(tool, Mapping):
            raise McpToolBrokerError("tool_not_found", "MCP tool is not discovered.")
        updated = dict(tool)
        updated["available_to_solen"] = available_to_solen
        if provider_capability_profile is not None:
            updated["provider_capability_profile"] = _provider_capability_profile(
                provider_capability_profile
            )
        else:
            updated.setdefault(
                "provider_capability_profile", DEFAULT_PROVIDER_CAPABILITY_PROFILE
            )
        catalog["tools"][tool_identity] = updated
        self._write(catalog)
        return self._tool_summary(updated)

    @staticmethod
    def _tool_summary(tool: Mapping[str, Any]) -> dict[str, Any]:
        summary = {
            key: copy.deepcopy(tool.get(key))
            for key in (
                "server_id", "tool_name", "tool_identity", "description",
                "tool_schema_identity", "schema_sha256", "available_to_solen",
            )
        }
        summary["provider_capability_profile"] = _provider_capability_profile(
            tool.get("provider_capability_profile", DEFAULT_PROVIDER_CAPABILITY_PROFILE)
        )
        return summary

    @_serialized
    def search_tools(self, query: str = "", *, limit: int = 20) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise McpToolBrokerError("invalid_limit", "Search limit is outside its bound.")
        needle = str(query or "").strip().casefold()
        catalog = self._read()
        enabled_servers = {key for key, value in catalog["servers"].items() if value.get("enabled") is True}
        matches: list[dict[str, Any]] = []
        for tool in catalog["tools"].values():
            if not isinstance(tool, Mapping) or tool.get("server_id") not in enabled_servers:
                continue
            if tool.get("available_to_solen") is not True:
                continue
            haystack = " ".join(str(tool.get(key, "")) for key in ("tool_name", "tool_identity", "description")).casefold()
            if needle and needle not in haystack:
                continue
            matches.append(self._tool_summary(tool))
        return sorted(matches, key=lambda item: item["tool_identity"])[:limit]

    @_serialized
    def load_tool(self, tool_identity: str, *, require_available: bool = True) -> dict[str, Any]:
        catalog = self._read()
        tool = catalog["tools"].get(tool_identity)
        if not isinstance(tool, Mapping):
            raise McpToolBrokerError("tool_not_found", "MCP tool is not discovered.")
        server = catalog["servers"].get(tool.get("server_id"))
        if not isinstance(server, Mapping) or server.get("enabled") is not True:
            raise McpToolBrokerError("server_disabled", "MCP server is disabled.")
        if require_available and tool.get("available_to_solen") is not True:
            raise McpToolBrokerError("tool_unavailable", "MCP tool is not available to Solen.")
        return copy.deepcopy(dict(tool))

    @_serialized
    def known_tool_schemas(self) -> dict[str, str]:
        return {
            item["tool_identity"]: item["tool_schema_identity"]
            for item in self.search_tools(limit=100)
        }

    @_serialized
    def call_tool(
        self,
        tool_identity: str,
        arguments: Mapping[str, Any],
        *,
        expected_tool_schema_identity: str | None = None,
    ) -> dict[str, Any]:
        tool = self.load_tool(tool_identity)
        if expected_tool_schema_identity is not None and expected_tool_schema_identity != tool["tool_schema_identity"]:
            raise McpToolBrokerError("tool_schema_identity_mismatch", "MCP tool schema identity changed.")
        if not isinstance(arguments, Mapping):
            raise McpToolBrokerError("invalid_arguments", "MCP tool arguments must be an object.")
        try:
            arguments_sha256 = tool_contract.canonical_sha256(arguments)
            result = self.connect(tool["server_id"]).call_tool(tool["tool_name"], copy.deepcopy(dict(arguments)))
            result_sha256 = tool_contract.canonical_sha256(result)
        except tool_contract.ProviderAgentToolContractError as exc:
            raise McpToolBrokerError("invalid_tool_payload", "MCP tool payload is not canonical JSON.") from exc
        except McpToolBrokerError:
            raise
        except Exception as exc:  # noqa: BLE001 - never project raw tool/provider errors.
            raise McpToolBrokerError("tool_call_failed", "MCP tool call failed.") from exc
        return {
            "schema_version": CALL_SCHEMA_VERSION,
            "tool_identity": tool_identity,
            "tool_schema_identity": tool["tool_schema_identity"],
            "arguments_sha256": arguments_sha256,
            "result_sha256": result_sha256,
            "result": copy.deepcopy(result),
            "raw_content_present": True,
        }

    @_serialized
    def safe_health(self) -> dict[str, Any]:
        catalog = self._read()
        servers: list[dict[str, Any]] = []
        for server_id, server in sorted(catalog["servers"].items()):
            tools = [
                value for value in catalog["tools"].values()
                if isinstance(value, Mapping) and value.get("server_id") == server_id
            ]
            servers.append({
                "server_id": server_id,
                "human_name": server["human_name"],
                "enabled": server["enabled"],
                "connected": server_id in self._sessions,
                "tool_count": len(tools),
                "available_tool_count": sum(item.get("available_to_solen") is True for item in tools),
                "last_test_state": server.get("last_test_state", "not_tested"),
                "last_error_class": server.get("last_error_class"),
            })
        return {
            "schema_version": HEALTH_SCHEMA_VERSION,
            "ok": True,
            "server_count": len(servers),
            "connected_count": sum(item["connected"] for item in servers),
            "enabled_count": sum(item["enabled"] for item in servers),
            "servers": servers,
            "source_bindings": copy.deepcopy(catalog["source_bindings"]),
            "raw_content_present": False,
        }


__all__ = [
    "CALL_SCHEMA_VERSION", "CATALOG_BINDING_SCHEMA_VERSION", "CATALOG_SCHEMA_VERSION", "CONNECTION_TEST_SCHEMA_VERSION",
    "DISCOVERY_SCHEMA_VERSION", "HEALTH_SCHEMA_VERSION", "HouseMcpToolBroker",
    "DEFAULT_PROVIDER_CAPABILITY_PROFILE", "McpToolBrokerError",
    "PROVIDER_CAPABILITY_PROFILES", "SCHEMA_VERSION", "SERVER_SCHEMA_VERSION",
    "TOOL_SCHEMA_VERSION", "TRANSPORTS",
]
