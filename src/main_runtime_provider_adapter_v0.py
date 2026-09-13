from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, MutableSequence

import house_provider_chat_serialization_v0 as chat_serialization
import house_prompt_cache_key_policy_v1 as prompt_cache_key
import house_prompt_cache_retention_policy_v1 as prompt_cache_retention
import main_runtime_provider_trace_bridge_v0 as provider_trace_bridge
import provider_observability_v0 as provider_observability


REQUEST_SCHEMA_VERSION = "main_runtime_adapter_request_v0"
RESPONSE_SCHEMA_VERSION = "main_runtime_adapter_response_v0"

DEFAULT_PROVIDER = "fake"
DEFAULT_MODEL = "fake-solen-runtime-v0"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_CONTEXT_PACKET_MAX_CHARS = 20000

FAKE_MODES = {"success", "context_aware_success", "timeout", "malformed_response", "provider_error"}
MOCK_PROVIDER_MODES = {"success", "timeout", "malformed_response", "rate_limit", "provider_error"}
OPENAI_COMPATIBLE_MOCK_MODES = {
    "success",
    "timeout",
    "malformed_response",
    "rate_limit",
    "provider_error",
    "auth_error",
    "unsupported_response_shape",
    "missing_text",
    "usage_absent",
}
OPENAI_COMPATIBLE_TRANSPORT_MODES = {"fixture", "live_http"}
OPENAI_COMPATIBLE_ENDPOINT_FAMILIES = {"responses", "chat_completions"}
# The reviewed House Chat projection uses the canonical GPT-5.5 family name
# for stable identity. OpenRouter requires its provider-qualified spelling at
# the transport boundary. No other projection/configuration mismatch is
# accepted here.
_APPROVED_CHAT_MODEL_ALIASES = frozenset({
    ("gpt-5.5", "openai/gpt-5.5"),
})
_TRANSPORT_OBSERVABILITY_FIELD = "_house_provider_transport_observability"
MOCK_PROVIDER_LABELS = {"mock_provider"}
REAL_PROVIDER_LABELS = {
    "openai",
    "openai_responses",
    "openai_compatible",
    "anthropic_compatible",
    "deepseek",
}
LOCAL_NO_KEY_PROVIDERS = {"fake", "local", "disabled"}
SUPPORTED_PROVIDERS = REAL_PROVIDER_LABELS | MOCK_PROVIDER_LABELS | LOCAL_NO_KEY_PROVIDERS


class MockProviderRateLimitError(RuntimeError):
    def __init__(self, message: str = "", *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class MockProviderAuthError(RuntimeError):
    def __init__(self, message: str = "", *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProviderHTTPStatusError(RuntimeError):
    def __init__(self, status_code: int, provider_error_code_safe: str = "") -> None:
        super().__init__(f"provider http status {status_code}")
        self.status_code = status_code
        self.provider_error_code_safe = provider_error_code_safe


class ProviderPayloadError(ValueError):
    def __init__(
        self,
        error_class: str,
        message: str,
        *,
        retryable: bool = False,
        provider_error_code_safe: str = "",
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.retryable = retryable
        self.provider_error_code_safe = provider_error_code_safe


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def parse_int(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class MainModelConfig:
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    model_configured: bool = True
    base_url: str = ""
    api_key_configured: bool = False
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    supports_streaming: bool = False
    supports_tools: bool = False
    supports_structured_output: bool = True
    max_input_tokens: int = 0
    max_output_tokens: int = 0
    fake_mode: str = "success"
    mock_provider_mode: str = "success"
    openai_compatible_mock_mode: str = "success"
    openai_compatible_transport: str = "fixture"
    openai_compatible_endpoint: str = "responses"
    live_http_approved: bool = False
    prompt_cache_key_configured_mode: str = "default_on"
    prompt_cache_key_enabled: bool = True
    prompt_cache_retention_configured_mode: str = "default_on"
    prompt_cache_retention_enabled: bool = True

    def safe_summary(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "model_configured": self.model_configured,
            "base_url_configured": bool(self.base_url),
            "api_key_configured": self.api_key_configured,
            "timeout_seconds": self.timeout_seconds,
            "supports_streaming": self.supports_streaming,
            "supports_tools": self.supports_tools,
            "supports_structured_output": self.supports_structured_output,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "fake_mode": self.fake_mode if self.provider == "fake" else None,
            "mock_provider_mode": self.mock_provider_mode if self.provider in MOCK_PROVIDER_LABELS else None,
            "openai_compatible_mock_mode": self.openai_compatible_mock_mode
            if self.provider == "openai_compatible"
            else None,
            "openai_compatible_transport": self.openai_compatible_transport
            if self.provider == "openai_compatible"
            else None,
            "openai_compatible_endpoint": self.openai_compatible_endpoint
            if self.provider == "openai_compatible"
            else None,
            "live_http_approved": self.live_http_approved
            if self.provider in {"openai_compatible", "anthropic_compatible"}
            else None,
            "prompt_cache_key_configured_mode": (
                self.prompt_cache_key_configured_mode
                if self.provider == "openai_compatible"
                else None
            ),
            "prompt_cache_key_enabled": (
                self.prompt_cache_key_enabled
                if self.provider == "openai_compatible"
                else None
            ),
            "prompt_cache_retention_configured_mode": (
                self.prompt_cache_retention_configured_mode
                if self.provider == "openai_compatible"
                else None
            ),
            "prompt_cache_retention_enabled": (
                self.prompt_cache_retention_enabled
                if self.provider == "openai_compatible"
                else None
            ),
        }


def load_main_model_config(env: Mapping[str, str] | None = None) -> MainModelConfig:
    env_map = env if env is not None else os.environ
    provider = env_map.get("MAIN_MODEL_PROVIDER", DEFAULT_PROVIDER).strip() or DEFAULT_PROVIDER
    raw_model = env_map.get("MAIN_MODEL_NAME", "").strip()
    model = raw_model or DEFAULT_MODEL
    fake_mode = env_map.get("MAIN_MODEL_FAKE_MODE", "success").strip() or "success"
    if fake_mode not in FAKE_MODES:
        fake_mode = "provider_error"
    mock_provider_mode = env_map.get("MAIN_MODEL_MOCK_PROVIDER_MODE", "success").strip() or "success"
    if mock_provider_mode not in MOCK_PROVIDER_MODES:
        mock_provider_mode = "provider_error"
    openai_compatible_mock_mode = env_map.get("MAIN_MODEL_OPENAI_COMPATIBLE_MOCK_MODE", "success").strip() or "success"
    if openai_compatible_mock_mode not in OPENAI_COMPATIBLE_MOCK_MODES:
        openai_compatible_mock_mode = "provider_error"
    openai_compatible_transport = env_map.get("MAIN_MODEL_OPENAI_COMPATIBLE_TRANSPORT", "fixture").strip() or "fixture"
    if openai_compatible_transport not in OPENAI_COMPATIBLE_TRANSPORT_MODES:
        openai_compatible_transport = "fixture"
    openai_compatible_endpoint = env_map.get("MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT", "responses").strip() or "responses"
    cache_key_configured_mode, cache_key_enabled = (
        prompt_cache_key.configured_feature_mode(env_map)
    )
    retention_configured_mode, retention_enabled = (
        prompt_cache_retention.configured_feature_mode(env_map)
    )
    return MainModelConfig(
        provider=provider,
        model=model,
        model_configured=bool(raw_model),
        base_url=env_map.get("MAIN_MODEL_BASE_URL", "").strip(),
        api_key_configured=bool(env_map.get("MAIN_MODEL_API_KEY")),
        timeout_seconds=parse_int(
            env_map.get("MAIN_MODEL_TIMEOUT_SECONDS"),
            default=DEFAULT_TIMEOUT_SECONDS,
        ),
        supports_streaming=parse_bool(env_map.get("MAIN_MODEL_SUPPORTS_STREAMING")),
        supports_tools=parse_bool(env_map.get("MAIN_MODEL_SUPPORTS_TOOLS")),
        supports_structured_output=parse_bool(
            env_map.get("MAIN_MODEL_SUPPORTS_STRUCTURED_OUTPUT"),
            default=True,
        ),
        max_input_tokens=parse_int(env_map.get("MAIN_MODEL_MAX_INPUT_TOKENS"), default=0),
        max_output_tokens=parse_int(env_map.get("MAIN_MODEL_MAX_OUTPUT_TOKENS"), default=0),
        fake_mode=fake_mode,
        mock_provider_mode=mock_provider_mode,
        openai_compatible_mock_mode=openai_compatible_mock_mode,
        openai_compatible_transport=openai_compatible_transport,
        openai_compatible_endpoint=openai_compatible_endpoint,
        live_http_approved=parse_bool(env_map.get("HOUSE_ALLOW_MAIN_RUNTIME_LIVE_HTTP")),
        prompt_cache_key_configured_mode=cache_key_configured_mode,
        prompt_cache_key_enabled=cache_key_enabled,
        prompt_cache_retention_configured_mode=retention_configured_mode,
        prompt_cache_retention_enabled=retention_enabled,
    )


def _provider_trace_bridge(
    request: Mapping[str, Any],
    config: MainModelConfig,
    endpoint_family: str,
    env: Mapping[str, str] | None,
) -> provider_trace_bridge.ProviderTraceBridge | None:
    env_map = env if env is not None else os.environ
    raw_root = env_map.get("HOUSE_PROVIDER_TRACE_VAULT_ROOT", "")
    root = raw_root.strip() if isinstance(raw_root, str) else ""
    if not root:
        return None
    request_id_value = request.get("request_id")
    request_id = request_id_value if isinstance(request_id_value, str) else None
    operation_value = request.get("turn_id") or request_id
    operation_id = operation_value if isinstance(operation_value, str) else "provider_attempt"
    metadata = request.get("metadata") if isinstance(request.get("metadata"), Mapping) else {}
    observability_metadata = (
        metadata.get("provider_observability")
        if isinstance(metadata.get("provider_observability"), Mapping)
        else {}
    )
    causal_linkage = (
        observability_metadata.get("causal_linkage")
        if isinstance(observability_metadata.get("causal_linkage"), Mapping)
        else None
    )
    request_observability = (
        observability_metadata.get("request")
        if isinstance(observability_metadata.get("request"), Mapping)
        else None
    )
    if causal_linkage is None:
        try:
            causal_linkage = provider_observability.build_causal_linkage(
                house_turn_id=operation_id,
                parent_trace_id=None,
                operation_id=operation_id,
                purpose="main_talk",
                input_provenance_classes=("flattened_house_context", "current_talk_turn"),
                output_destination_class="talk_response",
                attempt_number=1,
                attempt_reason="initial",
                provider_profile=str(metadata.get("provider_profile") or config.provider),
                client_model_label=config.model,
                endpoint_family=endpoint_family,
            )
        except ValueError:
            causal_linkage = None
    return provider_trace_bridge.ProviderTraceBridge(
        root=root,
        operation_id=operation_id,
        request_id=request_id,
        provider_label=config.provider,
        model_label=config.model,
        endpoint_family=endpoint_family,
        reason_labeler=_provider_trace_reason_label,
        causal_linkage=causal_linkage,
        request_observability=request_observability,
    )


def _provider_trace_reason_label(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ProviderPayloadError):
        return exc.error_class
    if isinstance(exc, MockProviderAuthError):
        return "auth_error"
    if isinstance(exc, MockProviderRateLimitError):
        return "rate_limit"
    if isinstance(exc, ProviderHTTPStatusError):
        return "provider_http_status"
    return "provider_error"


def build_runtime_request(
    *,
    request_id: str,
    session_id: str,
    user_text: str,
    conversation_id: str | None = None,
    turn_id: str | None = None,
    context_packet: Mapping[str, Any] | None = None,
    instruction_bundle: Mapping[str, Any] | None = None,
    tool_policy: Mapping[str, Any] | None = None,
    response_mode: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    safety_logging: Mapping[str, Any] | None = None,
    chat_projection: Any = None,
) -> dict[str, Any]:
    request = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "request_id": request_id,
        "conversation_id": conversation_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "user_message": {
            "text": user_text,
            "created_at": utc_timestamp(),
            "source": "local_gateway",
            "content_class": "ordinary_chat",
        },
        "context_packet": dict(context_packet) if context_packet is not None else None,
        "instruction_bundle": dict(
            instruction_bundle
            or {
                "bundle_id": "solen_runtime_instructions_v0",
                "version": "0.1",
                "source_pointer": "local/runtime/instructions",
            }
        ),
        "tool_policy": dict(
            tool_policy
            or {
                "mode": "none",
                "allowed_tools": [],
                "disallowed_tools": [
                    "memory_write",
                    "archive_mutation",
                    "notion_write",
                    "provider_archive_processing",
                ],
                "tool_result_policy": "gateway_mediated",
            }
        ),
        "response_mode": dict(
            response_mode
            or {
                "streaming": False,
                "structured": False,
                "max_output_tokens": None,
            }
        ),
        "metadata": dict(metadata or {}),
        "safety_logging": dict(
            safety_logging
            or {
                "log_user_message": False,
                "log_context_packet_text": False,
                "log_provider_response_text": False,
            }
        ),
    }
    if chat_projection is not None:
        request["chat_projection"] = chat_projection
    return request


def validate_runtime_request(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if request.get("schema_version") != REQUEST_SCHEMA_VERSION:
        errors.append(error_obj("invalid_schema_version", "Request schema_version is invalid.", False))
    if not request.get("request_id"):
        errors.append(error_obj("missing_request_id", "Request id is required.", False))
    if not (request.get("session_id") or request.get("conversation_id")):
        errors.append(
            error_obj("missing_session_or_conversation", "Session id or conversation id is required.", False)
        )
    user_message = request.get("user_message")
    if not isinstance(user_message, Mapping) or not str(user_message.get("text", "")).strip():
        errors.append(error_obj("missing_user_message", "User message text is required.", False))
    context_packet = request.get("context_packet")
    if context_packet is not None:
        if not isinstance(context_packet, Mapping):
            errors.append(error_obj("invalid_context_packet", "Context packet must be an object or null.", False))
        elif context_packet.get("schema_version") != "context_packet_v0":
            errors.append(error_obj("invalid_context_packet", "Context packet schema_version is invalid.", False))
    for field in ("instruction_bundle", "tool_policy", "response_mode", "safety_logging"):
        if not isinstance(request.get(field), Mapping):
            errors.append(error_obj(f"missing_{field}", f"{field} object is required.", False))
    chat_projection = request.get("chat_projection")
    if chat_projection is not None:
        try:
            chat_serialization.validate_chat_projection(chat_projection)
        except (TypeError, ValueError):
            errors.append(
                error_obj(
                    "invalid_chat_projection",
                    "Chat projection is not an attested House projection.",
                    False,
                )
            )
    return errors


def context_packet_stats(context_packet: Mapping[str, Any] | None) -> dict[str, Any]:
    if not context_packet:
        return {
            "context_present": False,
            "context_record_count": 0,
            "context_evidence_ref_count": 0,
            "context_source_note_count": 0,
            "context_confidence_note_count": 0,
            "context_safety_note_count": 0,
            "safe_source_names": [],
            "context_packet_chars": 0,
        }
    records = context_packet.get("records", [])
    recall_items = context_packet.get("conversation_recall", [])
    source_notes = context_packet.get("source_notes", [])
    confidence_notes = context_packet.get("confidence_notes", [])
    safety_notes = context_packet.get("safety_notes", [])
    if not isinstance(records, list):
        records = []
    if not isinstance(recall_items, list):
        recall_items = []
    if not isinstance(source_notes, list):
        source_notes = []
    if not isinstance(confidence_notes, list):
        confidence_notes = []
    if not isinstance(safety_notes, list):
        safety_notes = []
    source_names = safe_context_source_names(records)
    evidence_ref_count = sum(
        1 for item in recall_items if isinstance(item, Mapping) and isinstance(item.get("evidence_ref"), Mapping)
    )
    return {
        "context_present": True,
        "context_record_count": len(records),
        "context_evidence_ref_count": evidence_ref_count,
        "context_source_note_count": len(source_notes),
        "context_confidence_note_count": len(confidence_notes),
        "context_safety_note_count": len(safety_notes),
        "safe_source_names": source_names,
        "context_packet_chars": len(json.dumps(context_packet, sort_keys=True, ensure_ascii=False)),
    }


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def runtime_profile_metadata_stats(request: Mapping[str, Any]) -> dict[str, Any]:
    metadata = request.get("metadata") if isinstance(request.get("metadata"), Mapping) else {}
    profile = (
        metadata.get("runtime_profile_packet_metadata")
        if isinstance(metadata.get("runtime_profile_packet_metadata"), Mapping)
        else {}
    )
    active_counts = (
        profile.get("active_setting_counts")
        if isinstance(profile.get("active_setting_counts"), Mapping)
        else {}
    )
    return {
        "profile_packet_present": bool(profile.get("profile_packet_present")),
        "active_astel_setting_count": safe_int(active_counts.get("astel")),
        "active_solen_setting_count": safe_int(active_counts.get("solen")),
        "active_house_setting_count": safe_int(active_counts.get("house")),
        "profile_warning_count": safe_int(profile.get("warning_count")),
        "profile_policy_action": str(profile.get("policy_action") or "none")[:80],
    }


def safe_context_source_names(records: list[Any], *, limit: int = 3) -> list[str]:
    names: list[str] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if record.get("source_type") != "project_doc":
            continue
        name = str(record.get("source_name") or "").strip()
        if not name.endswith(".md"):
            continue
        safe_name = "".join(char for char in name if char.isalnum() or char in {"_", "-", "."})[:80]
        if safe_name and safe_name not in names:
            names.append(safe_name)
        if len(names) >= limit:
            break
    return names


def error_obj(
    error_class: str,
    message: str,
    retryable: bool,
    *,
    provider_error_code_safe: str = "",
    http_status_class: str = "",
    http_status_code: int | None = None,
) -> dict[str, Any]:
    payload = {
        "error_class": error_class,
        "message": message,
        "retryable": retryable,
    }
    if provider_error_code_safe:
        payload["provider_error_code_safe"] = provider_error_code_safe
    if http_status_class:
        payload["http_status_class"] = http_status_class
    if isinstance(http_status_code, int) and 100 <= http_status_code <= 599:
        payload["http_status_code"] = http_status_code
    return payload


def provider_metadata(config: MainModelConfig) -> dict[str, Any]:
    return {
        "provider": config.provider,
        "model": config.model,
        "base_url_configured": bool(config.base_url),
        "streaming_used": False,
        "tools_used": False,
        "structured_output_used": False,
    }


def usage_empty() -> dict[str, Any]:
    return provider_observability.usage_empty()


def normalize_usage(
    value: Any = None,
    *,
    endpoint_family: str | None = None,
    retain_details: bool = False,
    source_usage_present: bool | None = None,
) -> dict[str, Any]:
    return provider_observability.normalize_usage(
        value,
        endpoint_family=endpoint_family,
        retain_details=retain_details,
        source_usage_present=source_usage_present,
    )


def sanitize_provider_error_code(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text or len(text) > 80:
        return ""
    lowered = text.lower()
    unsafe_fragments = (
        "http://",
        "https://",
        "bearer ",
        "authorization",
        "api_key",
        "apikey",
        "token",
        "secret",
        "password",
        "please answer",
        "write one short",
        "astel",
        "solen",
    )
    if any(fragment in lowered for fragment in unsafe_fragments):
        return ""
    if not all(char.isalnum() or char in {"_", "-", ".", ":"} for char in text):
        return ""
    return text[:80]


def extract_safe_provider_error_code(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    candidates: list[Any] = []
    error_value = payload.get("error")
    if isinstance(error_value, Mapping):
        candidates.extend([error_value.get("code"), error_value.get("type")])
    candidates.extend([payload.get("code"), payload.get("type")])
    for candidate in candidates:
        safe_code = sanitize_provider_error_code(candidate)
        if safe_code:
            return safe_code
    return ""


def parse_json_object_safely(body_bytes: bytes) -> Mapping[str, Any] | None:
    try:
        text = body_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if text.lstrip().startswith("data:"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    return payload


def build_response(
    *,
    request: Mapping[str, Any],
    config: MainModelConfig,
    ok: bool,
    assistant_text: str = "",
    finish_reason: str = "stop",
    warnings: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
    usage: Mapping[str, Any] | None = None,
    latency_ms: int = 0,
) -> dict[str, Any]:
    return {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "ok": ok,
        "request_id": request.get("request_id"),
        "conversation_id": request.get("conversation_id"),
        "session_id": request.get("session_id"),
        "provider": provider_metadata(config),
        "assistant_text": assistant_text if ok else "",
        "tool_requests": [],
        "usage": normalize_usage(usage),
        "latency_ms": latency_ms,
        "finish_reason": finish_reason if ok else "error",
        "warnings": warnings or [],
        "errors": errors or [],
        "policy_action": "none",
    }


def validate_runtime_response(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if response.get("schema_version") != RESPONSE_SCHEMA_VERSION:
        errors.append(error_obj("invalid_response_schema", "Response schema_version is invalid.", False))
    if "ok" not in response:
        errors.append(error_obj("invalid_response", "Response ok field is required.", False))
    if not isinstance(response.get("provider"), Mapping):
        errors.append(error_obj("invalid_response", "Response provider metadata is required.", False))
    if not isinstance(response.get("tool_requests"), list):
        errors.append(error_obj("invalid_response", "Response tool_requests must be a list.", False))
    if response.get("policy_action") != "none":
        errors.append(error_obj("invalid_policy_action", "policy_action must remain none.", False))
    if response.get("ok") is False and response.get("assistant_text"):
        errors.append(error_obj("invalid_failure_response", "Failure response must not include assistant text.", False))
    return errors


def append_safe_log(
    safe_logs: MutableSequence[dict[str, Any]] | None,
    *,
    request: Mapping[str, Any],
    config: MainModelConfig,
    response: Mapping[str, Any],
    stats: Mapping[str, Any],
    latency_ms: int,
    provider_trace: provider_trace_bridge.ProviderTraceBridge | None = None,
) -> None:
    if safe_logs is None:
        return
    error_class = None
    errors = response.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, Mapping):
            error_class = first.get("error_class")
            provider_error_code_safe = first.get("provider_error_code_safe")
            http_status_code = first.get("http_status_code")
        else:
            provider_error_code_safe = None
            http_status_code = None
    else:
        provider_error_code_safe = None
        http_status_code = None
    profile_stats = runtime_profile_metadata_stats(request)
    entry = {
            "timestamp": utc_timestamp(),
            "request_id": request.get("request_id"),
            "session_id": request.get("session_id"),
            "provider": config.provider,
            "model": config.model,
            "ok": response.get("ok"),
            "latency_ms": latency_ms,
            "error_class": error_class,
            "provider_error_code_safe": provider_error_code_safe,
            "http_status_code": http_status_code if isinstance(http_status_code, int) else None,
            "context_present": stats.get("context_present"),
            "context_record_count": stats.get("context_record_count"),
            "context_evidence_ref_count": stats.get("context_evidence_ref_count"),
            "context_source_note_count": stats.get("context_source_note_count"),
            "context_confidence_note_count": stats.get("context_confidence_note_count"),
            "context_safety_note_count": stats.get("context_safety_note_count"),
            "profile_packet_present": profile_stats["profile_packet_present"],
            "profile_warning_count": profile_stats["profile_warning_count"],
            "profile_policy_action": profile_stats["profile_policy_action"],
            "input_tokens": (response.get("usage") or {}).get("input_tokens")
            if isinstance(response.get("usage"), Mapping)
            else None,
            "output_tokens": (response.get("usage") or {}).get("output_tokens")
            if isinstance(response.get("usage"), Mapping)
            else None,
            "total_tokens": (response.get("usage") or {}).get("total_tokens")
            if isinstance(response.get("usage"), Mapping)
            else None,
            "cached_input_tokens": (response.get("usage") or {}).get("cached_input_tokens")
            if isinstance(response.get("usage"), Mapping)
            else None,
            "cache_write_tokens": (response.get("usage") or {}).get("cache_write_tokens")
            if isinstance(response.get("usage"), Mapping)
            else None,
            "reasoning_tokens": (response.get("usage") or {}).get("reasoning_tokens")
            if isinstance(response.get("usage"), Mapping)
            else None,
            "tool_policy_mode": (request.get("tool_policy") or {}).get("mode")
            if isinstance(request.get("tool_policy"), Mapping)
            else None,
        }
    if "observability" in response:
        try:
            entry["provider_observability"] = provider_observability.project_safe_log_observability(
                response.get("observability")
            )
        except (TypeError, ValueError):
            entry["provider_observability_status"] = "invalid_omitted"
    if provider_trace is not None:
        entry.update(provider_trace.safe_log_fields())
    safe_logs.append(entry)


def preflight_provider_config(config: MainModelConfig) -> list[dict[str, Any]]:
    if config.provider not in SUPPORTED_PROVIDERS:
        return [error_obj("unsupported_provider", "Main model provider is not supported.", False)]
    if config.provider == "disabled":
        return [error_obj("provider_disabled", "Main model provider is disabled.", False)]
    if config.provider in (REAL_PROVIDER_LABELS | MOCK_PROVIDER_LABELS) and not config.api_key_configured:
        return [error_obj("missing_api_key", "Provider API key is not configured.", False)]
    if config.provider == "openai_compatible" and not config.base_url:
        return [error_obj("missing_base_url", "OpenAI-compatible provider base URL is not configured.", False)]
    if config.provider == "anthropic_compatible" and not config.base_url:
        return [error_obj("missing_base_url", "Anthropic-compatible provider base URL is not configured.", False)]
    if config.provider == "openai_compatible" and config.openai_compatible_transport == "live_http":
        if not config.live_http_approved:
            return [error_obj("live_http_disabled", "OpenAI-compatible live HTTP path is disabled by default.", False)]
        if not config.model_configured:
            return [error_obj("missing_model", "OpenAI-compatible provider model is not configured.", False)]
        if config.openai_compatible_endpoint not in OPENAI_COMPATIBLE_ENDPOINT_FAMILIES:
            return [error_obj("unsupported_endpoint_family", "OpenAI-compatible endpoint family is not supported.", False)]
    if config.provider == "anthropic_compatible":
        if not config.live_http_approved:
            return [error_obj("live_http_disabled", "Anthropic-compatible live HTTP path is disabled by default.", False)]
        if not config.model_configured:
            return [error_obj("missing_model", "Anthropic-compatible provider model is not configured.", False)]
    return []


def preflight_request_against_config(
    request: Mapping[str, Any],
    config: MainModelConfig,
    stats: Mapping[str, Any],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    chat_projection = request.get("chat_projection")
    if chat_projection is not None:
        if (
            config.provider != "openai_compatible"
            or config.openai_compatible_endpoint != "chat_completions"
        ):
            errors.append(
                error_obj(
                    "chat_projection_route_mismatch",
                    "Chat projection requires the OpenAI-compatible Chat Completions route.",
                    False,
                )
            )
        else:
            try:
                projection_body = (
                    chat_serialization.endpoint_request_from_chat_projection(
                        chat_projection
                    )
                )
            except (TypeError, ValueError):
                errors.append(
                    error_obj(
                        "invalid_chat_projection",
                        "Chat projection is not an attested House projection.",
                        False,
                    )
                )
            else:
                if projection_body.get("model") != config.model:
                    errors.append(
                        error_obj(
                            "chat_projection_model_mismatch",
                            "Chat projection model does not match the selected runtime model.",
                            False,
                        )
                    )
    tool_policy = request.get("tool_policy") if isinstance(request.get("tool_policy"), Mapping) else {}
    tool_mode = tool_policy.get("mode", "none")
    if tool_mode not in {None, "", "none"} and (not config.supports_tools or config.provider == "openai_compatible"):
        error_class = (
            "unsupported_tool_mode"
            if config.provider == "openai_compatible" and config.openai_compatible_transport == "live_http"
            else "unsupported_tools"
        )
        errors.append(error_obj(error_class, "Provider does not support requested tool mode.", False))
    if config.provider == "openai_compatible" and config.openai_compatible_transport == "live_http":
        if request.get("context_packet") is not None:
            errors.append(error_obj("context_packet_not_allowed", "Live HTTP adapter path does not accept context packets in v0.", False))
        metadata = request.get("metadata") if isinstance(request.get("metadata"), Mapping) else {}
        forbidden_metadata = {
            "memory_vault",
            "memory_records",
            "solen_room",
            "archive_recall",
            "context_packet",
            "current_state_context",
            "raw_profile_json",
            "raw_solen_core_seed",
            "full_profile_json",
        }
        if any(key in metadata for key in forbidden_metadata):
            errors.append(error_obj("unsafe_request_field", "Live HTTP adapter path received forbidden metadata fields.", False))
    max_chars = DEFAULT_CONTEXT_PACKET_MAX_CHARS
    if config.max_input_tokens > 0:
        max_chars = min(max_chars, config.max_input_tokens * 4)
    if stats.get("context_packet_chars", 0) > max_chars:
        errors.append(error_obj("context_packet_too_large", "Context packet is too large for adapter call.", False))
    return errors


def run_fake_provider(
    request: Mapping[str, Any],
    config: MainModelConfig,
    stats: Mapping[str, Any],
) -> Mapping[str, Any]:
    mode = config.fake_mode
    if mode == "timeout":
        raise TimeoutError("fake provider timeout")
    if mode == "provider_error":
        raise RuntimeError("fake provider error")
    if mode == "malformed_response":
        return {"not_schema_version": RESPONSE_SCHEMA_VERSION, "ok": "maybe"}
    if mode == "context_aware_success":
        profile_stats = runtime_profile_metadata_stats(request)
        profile_text = (
            "Profile packet present: yes. "
            f"Profile policy action: {profile_stats['profile_policy_action']}."
            if profile_stats["profile_packet_present"]
            else "Profile packet present: no."
        )
        if not stats.get("context_present"):
            return {
                "assistant_text": (
                    "[fake runtime / context-aware] No context packet was attached. "
                    f"{profile_text} "
                    "This is a deterministic metadata-only test response, not the final Solen voice."
                )
            }
        metadata = request.get("metadata") if isinstance(request.get("metadata"), Mapping) else {}
        source_route = str(metadata.get("recall_source_route") or "none")
        source_names = stats.get("safe_source_names") if isinstance(stats.get("safe_source_names"), list) else []
        source_text = f" Sources: {', '.join(source_names)}." if source_names else ""
        return {
            "assistant_text": (
                "[fake runtime / context-aware] Context packet present: yes. "
                f"Records: {stats.get('context_record_count', 0)}. "
                f"Evidence refs: {stats.get('context_evidence_ref_count', 0)}. "
                f"Source notes: {stats.get('context_source_note_count', 0)}. "
                f"Confidence notes: {stats.get('context_confidence_note_count', 0)}. "
                f"Source route: {source_route}."
                f"{source_text} "
                f"{profile_text} "
                "This is a deterministic metadata-only test response, not the final Solen voice."
            )
        }
    context_word = "yes" if stats.get("context_present") else "no"
    profile_stats = runtime_profile_metadata_stats(request)
    profile_word = "yes" if profile_stats["profile_packet_present"] else "no"
    return {
        "assistant_text": (
            "[fake runtime] I received this turn through the local runtime adapter. "
            f"Context packet present: {context_word}. "
            f"Context record count: {stats.get('context_record_count', 0)}. "
            f"Profile packet present: {profile_word}. "
            "This is a deterministic placeholder response for gateway testing."
        )
    }


def build_mock_provider_request(
    request: Mapping[str, Any],
    config: MainModelConfig,
    stats: Mapping[str, Any],
) -> dict[str, Any]:
    response_mode = request.get("response_mode") if isinstance(request.get("response_mode"), Mapping) else {}
    profile_stats = runtime_profile_metadata_stats(request)
    return {
        "schema_version": "mock_provider_request_v0",
        "request_id": request.get("request_id"),
        "provider": config.provider,
        "model": config.model,
        "input_summary": {
            "user_message_present": bool((request.get("user_message") or {}).get("text"))
            if isinstance(request.get("user_message"), Mapping)
            else False,
            "context_present": bool(stats.get("context_present")),
            "context_record_count": stats.get("context_record_count", 0),
            "profile_packet_present": profile_stats["profile_packet_present"],
        },
        "response_options": {
            "stream": bool(response_mode.get("streaming")),
            "structured": bool(response_mode.get("structured")),
            "max_output_tokens": response_mode.get("max_output_tokens"),
        },
    }


def run_mock_provider_client(mock_request: Mapping[str, Any], config: MainModelConfig) -> Mapping[str, Any]:
    mode = config.mock_provider_mode
    if mode == "timeout":
        raise TimeoutError("mock provider timeout")
    if mode == "rate_limit":
        raise MockProviderRateLimitError("mock provider rate limit")
    if mode == "provider_error":
        raise RuntimeError("mock provider error")
    if mode == "malformed_response":
        return {"schema_version": "mock_provider_response_v0", "status": "completed"}
    return {
        "schema_version": "mock_provider_response_v0",
        "status": "completed",
        "output_text": "[mock provider] Provider-neutral mocked response reached the adapter.",
        "finish_reason": "stop",
        "usage": {
            "input_tokens": 11,
            "output_tokens": 9,
            "total_tokens": 20,
            "estimated_cost": 0,
            "currency": "USD",
        },
    }


def normalize_mock_provider_response(provider_payload: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if provider_payload.get("schema_version") != "mock_provider_response_v0":
        raise ValueError("invalid mock provider schema")
    if provider_payload.get("status") != "completed":
        raise ValueError("mock provider did not complete")
    output_text = provider_payload.get("output_text")
    if not isinstance(output_text, str) or not output_text.strip():
        raise ValueError("mock provider output text is missing")
    finish_reason = provider_payload.get("finish_reason")
    if not isinstance(finish_reason, str) or not finish_reason.strip():
        finish_reason = "stop"
    usage = normalize_usage(provider_payload.get("usage") if isinstance(provider_payload.get("usage"), Mapping) else None)
    return output_text, finish_reason, usage


def build_openai_compatible_responses_request(
    request: Mapping[str, Any],
    config: MainModelConfig,
    stats: Mapping[str, Any],
) -> dict[str, Any]:
    response_mode = request.get("response_mode") if isinstance(request.get("response_mode"), Mapping) else {}
    endpoint_family = config.openai_compatible_endpoint
    schema_version = (
        "openai_compatible_chat_completions_request_fixture_v0"
        if endpoint_family == "chat_completions"
        else "openai_compatible_responses_request_fixture_v0"
    )
    return {
        "schema_version": schema_version,
        "request_id": request.get("request_id"),
        "provider": config.provider,
        "model": config.model,
        "endpoint_family": endpoint_family,
        "input_summary": {
            "user_message_present": bool((request.get("user_message") or {}).get("text"))
            if isinstance(request.get("user_message"), Mapping)
            else False,
            "context_present": bool(stats.get("context_present")),
            "context_record_count": stats.get("context_record_count", 0),
        },
        "response_options": {
            "stream": bool(response_mode.get("streaming")),
            "structured": bool(response_mode.get("structured")),
            "max_output_tokens": response_mode.get("max_output_tokens"),
            "tool_mode": (request.get("tool_policy") or {}).get("mode")
            if isinstance(request.get("tool_policy"), Mapping)
            else None,
        },
    }


def openai_compatible_responses_url(base_url: str, endpoint_family: str) -> str:
    endpoint_paths = {
        "responses": "responses",
        "chat_completions": "chat/completions",
    }
    if endpoint_family not in endpoint_paths:
        raise ProviderPayloadError("unsupported_endpoint_family", "OpenAI-compatible endpoint family is not supported.")
    normalized = str(base_url or "").strip().rstrip("/")
    if not normalized:
        raise ProviderPayloadError("missing_base_url", "OpenAI-compatible provider base URL is not configured.")
    endpoint_path = endpoint_paths[endpoint_family]
    if normalized.endswith(f"/{endpoint_path}"):
        return normalized
    return f"{normalized}/{endpoint_path}"


def _prompt_cache_metadata(request: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = (
        request.get("metadata")
        if isinstance(request.get("metadata"), Mapping)
        else {}
    )
    cache = (
        metadata.get("prompt_cache")
        if isinstance(metadata.get("prompt_cache"), Mapping)
        else {}
    )
    return cache


def _prompt_cache_stable_prefix_effective(request: Mapping[str, Any]) -> bool:
    return (
        _prompt_cache_metadata(request).get("effective_mode")
        == "stable_prefix"
    )


def _attach_prompt_cache_controls(
    body: dict[str, Any],
    *,
    request: Mapping[str, Any],
    config: MainModelConfig,
) -> dict[str, Any]:
    stable_prefix_effective = _prompt_cache_stable_prefix_effective(request)
    decision = prompt_cache_retention.decide_retention(
        provider=config.provider,
        endpoint_family=config.openai_compatible_endpoint,
        model=config.model,
        stable_prefix_effective=stable_prefix_effective,
        configured_mode=config.prompt_cache_retention_configured_mode,
        enabled=config.prompt_cache_retention_enabled,
    )
    body.update(decision.request_fields)
    key_decision = prompt_cache_key.decide_cache_key(
        provider=config.provider,
        endpoint_family=config.openai_compatible_endpoint,
        stable_prefix_effective=stable_prefix_effective,
        prefix_sha256=_prompt_cache_metadata(request).get("prefix_sha256"),
        configured_mode=config.prompt_cache_key_configured_mode,
        enabled=config.prompt_cache_key_enabled,
    )
    body.update(key_decision.request_fields)
    return body


def build_openai_compatible_responses_http_body(
    request: Mapping[str, Any],
    config: MainModelConfig,
    stats: Mapping[str, Any],
) -> dict[str, Any]:
    response_mode = request.get("response_mode") if isinstance(request.get("response_mode"), Mapping) else {}
    profile_stats = runtime_profile_metadata_stats(request)
    user_message = request.get("user_message") if isinstance(request.get("user_message"), Mapping) else {}
    user_text = user_message.get("text")
    if not isinstance(user_text, str) or not user_text.strip():
        raise ProviderPayloadError("missing_user_message", "User message text is required.")
    instructions = (
        "House API Talk path. Answer the current message naturally from the attached House cards. "
        f"Runtime profile packet present: {'yes' if profile_stats['profile_packet_present'] else 'no'}. "
        f"Profile policy action: {profile_stats['profile_policy_action']}."
    )
    body: dict[str, Any] = {
        "model": config.model,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": user_text,
                    }
                ],
            }
        ],
        "instructions": instructions,
        "stream": False,
        "store": False,
    }
    max_output_tokens = response_mode.get("max_output_tokens")
    if isinstance(max_output_tokens, int) and max_output_tokens > 0:
        body["max_output_tokens"] = max_output_tokens
    return _attach_prompt_cache_controls(
        body,
        request=request,
        config=config,
    )


def build_openai_compatible_chat_completions_http_body(
    request: Mapping[str, Any],
    config: MainModelConfig,
    stats: Mapping[str, Any],
) -> dict[str, Any]:
    chat_projection = request.get("chat_projection")
    if chat_projection is not None:
        try:
            body = chat_serialization.endpoint_request_from_chat_projection(
                chat_projection
            )
        except (TypeError, ValueError) as exc:
            raise ProviderPayloadError(
                "invalid_chat_projection",
                "Chat projection is not an attested House projection.",
            ) from exc
        projected_model = body.get("model")
        if projected_model != config.model:
            if (projected_model, config.model) not in _APPROVED_CHAT_MODEL_ALIASES:
                raise ProviderPayloadError(
                    "chat_projection_model_mismatch",
                    "Chat projection model does not match the selected runtime model.",
                )
            # The projection's family label remains the stable identity input;
            # only the provider routing alias changes in the endpoint body.
            body = {**body, "model": config.model}
        return _attach_prompt_cache_controls(
            body,
            request=request,
            config=config,
        )
    user_message = request.get("user_message") if isinstance(request.get("user_message"), Mapping) else {}
    user_text = user_message.get("text")
    if not isinstance(user_text, str) or not user_text.strip():
        raise ProviderPayloadError("missing_user_message", "User message text is required.")
    body = {
        "model": config.model,
        "messages": [
            {
                "role": "user",
                "content": user_text,
            }
        ],
        "stream": False,
    }
    return _attach_prompt_cache_controls(
        body,
        request=request,
        config=config,
    )


def anthropic_compatible_messages_url(base_url: str) -> str:
    normalized = str(base_url or "").strip().rstrip("/")
    if not normalized:
        raise ProviderPayloadError("missing_base_url", "Anthropic-compatible provider base URL is not configured.")
    if normalized.endswith("/messages"):
        return normalized
    return f"{normalized}/messages"


def build_anthropic_compatible_messages_http_body(
    request: Mapping[str, Any],
    config: MainModelConfig,
    stats: Mapping[str, Any],
) -> dict[str, Any]:
    response_mode = request.get("response_mode") if isinstance(request.get("response_mode"), Mapping) else {}
    user_message = request.get("user_message") if isinstance(request.get("user_message"), Mapping) else {}
    user_text = user_message.get("text")
    if not isinstance(user_text, str) or not user_text.strip():
        raise ProviderPayloadError("missing_user_message", "User message text is required.")
    max_tokens = response_mode.get("max_output_tokens")
    if not isinstance(max_tokens, int) or max_tokens <= 0:
        max_tokens = config.max_output_tokens if config.max_output_tokens > 0 else 1024
    return {
        "model": config.model,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": user_text,
            }
        ],
        "stream": False,
    }


def build_openai_compatible_live_http_body(
    request: Mapping[str, Any],
    config: MainModelConfig,
    stats: Mapping[str, Any],
) -> dict[str, Any]:
    response_mode = request.get("response_mode") if isinstance(request.get("response_mode"), Mapping) else {}
    tool_policy = request.get("tool_policy") if isinstance(request.get("tool_policy"), Mapping) else {}
    tool_mode = tool_policy.get("mode", "none")
    if tool_mode not in {None, "", "none"}:
        raise ProviderPayloadError("unsupported_tool_mode", "Live HTTP adapter path requires tool mode none.")
    if config.openai_compatible_endpoint == "chat_completions":
        return build_openai_compatible_chat_completions_http_body(request, config, stats)
    return build_openai_compatible_responses_http_body(request, config, stats)


def openai_compatible_default_http_transport(
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    timeout_seconds: int,
) -> tuple[int, bytes, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=body,
        headers=dict(headers),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return (
                int(response.status),
                response.read(),
                provider_observability.safe_response_headers(response.headers),
            )
    except urllib.error.HTTPError as exc:
        try:
            body_bytes = exc.read()
        finally:
            exc.close()
        return int(exc.code), body_bytes, provider_observability.safe_response_headers(exc.headers)
    except TimeoutError:
        raise
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            raise TimeoutError("OpenAI-compatible live HTTP request timed out") from exc
        raise ProviderPayloadError("network_error", "OpenAI-compatible live HTTP request failed.") from exc


def parse_openai_compatible_http_payload(status_code: int, body_bytes: bytes) -> Mapping[str, Any]:
    if status_code < 200 or status_code >= 300:
        provider_error_code_safe = extract_safe_provider_error_code(parse_json_object_safely(body_bytes))
        if status_code in {401, 403}:
            raise MockProviderAuthError("openai-compatible live HTTP auth error", status_code=status_code)
        if status_code == 429:
            raise MockProviderRateLimitError("openai-compatible live HTTP rate limit", status_code=status_code)
        raise ProviderHTTPStatusError(status_code, provider_error_code_safe=provider_error_code_safe)
    try:
        text = body_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProviderPayloadError("malformed_provider_response", "Provider response was not UTF-8 JSON.") from exc
    if text.lstrip().startswith("data:"):
        raise ProviderPayloadError("unexpected_streaming_response", "Streaming/event responses are not supported in v0.")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderPayloadError("malformed_json", "Provider response was not valid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise ProviderPayloadError("malformed_provider_response", "Provider response must be a JSON object.")
    return payload


def run_anthropic_compatible_live_http_client(
    request: Mapping[str, Any],
    config: MainModelConfig,
    stats: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    http_transport: provider_trace_bridge.HTTPTransport | None = None,
) -> Mapping[str, Any]:
    env_map = env if env is not None else os.environ
    api_key = env_map.get("MAIN_MODEL_API_KEY", "").strip()
    if not api_key:
        raise ProviderPayloadError("missing_api_key", "Provider API key is not configured.")
    url = anthropic_compatible_messages_url(config.base_url)
    body_map = build_anthropic_compatible_messages_http_body(request, config, stats)
    body = json.dumps(body_map, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    transport = http_transport or openai_compatible_default_http_transport
    status_code, body_bytes, safe_headers = provider_observability.unpack_http_transport_result(
        transport(url, headers, body, config.timeout_seconds)
    )
    payload = dict(parse_openai_compatible_http_payload(status_code, body_bytes))
    payload[_TRANSPORT_OBSERVABILITY_FIELD] = {
        "request_body_utf8_bytes": len(body),
        "response_bytes": len(body_bytes),
        "http_status": status_code,
        "safe_response_headers": safe_headers,
    }
    return payload


def run_openai_compatible_live_http_client(
    request: Mapping[str, Any],
    config: MainModelConfig,
    stats: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    http_transport: provider_trace_bridge.HTTPTransport | None = None,
) -> Mapping[str, Any]:
    if not config.live_http_approved:
        raise ProviderPayloadError("live_http_disabled", "OpenAI-compatible live HTTP path is disabled by default.")
    if not config.api_key_configured:
        raise ProviderPayloadError("missing_api_key", "Provider API key is not configured.")
    if not config.base_url:
        raise ProviderPayloadError("missing_base_url", "OpenAI-compatible provider base URL is not configured.")
    if not config.model_configured:
        raise ProviderPayloadError("missing_model", "OpenAI-compatible provider model is not configured.")
    if config.openai_compatible_endpoint not in OPENAI_COMPATIBLE_ENDPOINT_FAMILIES:
        raise ProviderPayloadError("unsupported_endpoint_family", "OpenAI-compatible endpoint family is not supported.")

    env_map = env if env is not None else os.environ
    api_key = env_map.get("MAIN_MODEL_API_KEY", "")
    if not api_key:
        raise ProviderPayloadError("missing_api_key", "Provider API key is not configured.")
    url = openai_compatible_responses_url(config.base_url, config.openai_compatible_endpoint)
    body_map = build_openai_compatible_live_http_body(request, config, stats)
    body = json.dumps(body_map, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    transport = http_transport or openai_compatible_default_http_transport
    status_code, body_bytes, safe_headers = provider_observability.unpack_http_transport_result(
        transport(url, headers, body, config.timeout_seconds)
    )
    payload = dict(parse_openai_compatible_http_payload(status_code, body_bytes))
    payload[_TRANSPORT_OBSERVABILITY_FIELD] = {
        "request_body_utf8_bytes": len(body),
        "request_body_sha256": hashlib.sha256(body).hexdigest(),
        "response_bytes": len(body_bytes),
        "http_status": status_code,
        "safe_response_headers": safe_headers,
    }
    return payload


def run_openai_compatible_fixture_client(
    fixture_request: Mapping[str, Any],
    config: MainModelConfig,
) -> Mapping[str, Any]:
    mode = config.openai_compatible_mock_mode
    if mode == "timeout":
        raise TimeoutError("openai-compatible fixture timeout")
    if mode == "rate_limit":
        raise MockProviderRateLimitError("openai-compatible fixture rate limit")
    if mode == "auth_error":
        raise MockProviderAuthError("openai-compatible fixture auth error")
    if mode == "provider_error":
        raise RuntimeError("openai-compatible fixture provider error")
    if mode == "malformed_response":
        return {"id": 123, "object": "response", "status": "completed", "output": []}
    if mode == "unsupported_response_shape":
        return {
            "id": "unsupported_fixture_001",
            "object": "provider.specific.unknown",
            "payload": {"text": "unsupported fixture text must not be extracted"},
        }
    if mode == "missing_text":
        if config.openai_compatible_endpoint == "chat_completions":
            return {
                "id": "chatcmpl_fixture_missing_text",
                "object": "chat.completion",
                "model": config.model,
                "choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 13, "completion_tokens": 0, "total_tokens": 13},
            }
        return {
            "id": "resp_fixture_missing_text",
            "object": "response",
            "status": "completed",
            "model": config.model,
            "output": [{"type": "message", "content": [{"type": "output_text"}]}],
            "usage": {"input_tokens": 13, "output_tokens": 0, "total_tokens": 13},
        }
    usage = None
    if mode != "usage_absent":
        if config.openai_compatible_endpoint == "chat_completions":
            usage = {
                "prompt_tokens": 17,
                "completion_tokens": 12,
                "total_tokens": 29,
                "estimated_cost": 0,
                "currency": "USD",
            }
        else:
            usage = {
                "input_tokens": 17,
                "output_tokens": 12,
                "total_tokens": 29,
                "estimated_cost": 0,
                "currency": "USD",
            }
    if config.openai_compatible_endpoint == "chat_completions":
        payload = {
            "id": "chatcmpl_fixture_001",
            "object": "chat.completion",
            "model": config.model,
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "[openai-compatible mock] Chat Completions fixture reached the adapter.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "provider_label": config.provider,
            "fixture_request_id": fixture_request.get("request_id"),
        }
        if usage is not None:
            payload["usage"] = usage
        return payload
    payload = {
        "id": "resp_fixture_001",
        "object": "response",
        "status": "completed",
        "model": config.model,
        "output": [
            {
                "type": "message",
                "id": "msg_fixture_001",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": "[openai-compatible mock] Responses-style fixture reached the adapter.",
                    }
                ],
            }
        ],
        "finish_reason": "stop",
        "provider_label": config.provider,
        "fixture_request_id": fixture_request.get("request_id"),
    }
    if usage is not None:
        payload["usage"] = usage
    return payload


def _extract_text_from_content_value(value: Any) -> list[str]:
    fragments: list[str] = []
    if isinstance(value, str) and value.strip():
        fragments.append(value)
    elif isinstance(value, Mapping):
        content_type = value.get("type")
        if content_type in {"function_call", "tool_call"} or value.get("tool_calls") or value.get("function_call"):
            raise ProviderPayloadError(
                "provider_tool_request",
                "Provider attempted a tool request in tool-disabled mode.",
            )
        if content_type in {"output_text", "text", None}:
            text = value.get("text")
            if isinstance(text, str) and text.strip():
                fragments.append(text)
        nested_content = value.get("content")
        if isinstance(nested_content, (str, list, Mapping)):
            fragments.extend(_extract_text_from_content_value(nested_content))
    elif isinstance(value, list):
        for item in value:
            fragments.extend(_extract_text_from_content_value(item))
    return fragments


def _unwrap_openai_compatible_success_payload(provider_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("data", "result"):
        nested = provider_payload.get(key)
        if not isinstance(nested, Mapping):
            continue
        if any(field in nested for field in ("object", "output_text", "output", "choices")):
            return nested
    return provider_payload


def extract_openai_compatible_output_text(provider_payload: Mapping[str, Any]) -> str:
    top_level_text = provider_payload.get("output_text")
    if isinstance(top_level_text, str) and top_level_text.strip():
        return top_level_text
    output = provider_payload.get("output")
    fragments: list[str] = []
    output_present = isinstance(output, list)
    if output_present:
        for item in output:
            if not isinstance(item, Mapping):
                continue
            item_type = item.get("type")
            if item_type in {"function_call", "tool_call"}:
                raise ProviderPayloadError(
                    "provider_tool_request",
                    "Provider attempted a tool request in tool-disabled mode.",
                )
            if item_type in {"output_text", "text"}:
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    fragments.append(text)
            content = item.get("content")
            if isinstance(content, (str, list, Mapping)):
                fragments.extend(_extract_text_from_content_value(content))
            message = item.get("message")
            if isinstance(message, Mapping):
                fragments.extend(_extract_text_from_content_value(message.get("content")))

    choices = provider_payload.get("choices")
    choices_present = isinstance(choices, list)
    if choices_present:
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            message = choice.get("message")
            if isinstance(message, Mapping):
                if message.get("tool_calls") or message.get("function_call"):
                    raise ProviderPayloadError(
                        "provider_tool_request",
                        "Provider attempted a tool request in tool-disabled mode.",
                    )
                fragments.extend(_extract_text_from_content_value(message.get("content")))
            fragments.extend(_extract_text_from_content_value(choice.get("text")))

    if not fragments:
        if choices_present and not choices:
            raise ProviderPayloadError(
                "unsupported_response_shape",
                "OpenAI-compatible provider response included an empty choices shape.",
            )
        if not output_present and not choices_present:
            raise ProviderPayloadError(
                "unsupported_response_shape",
                "OpenAI-compatible provider response did not include a supported text-bearing shape.",
            )
        raise ProviderPayloadError(
            "missing_output_text",
            "Responses fixture did not include an output_text text path.",
        )
    return "\n".join(fragments)


def normalize_openai_compatible_response(
    provider_payload: Mapping[str, Any],
    *,
    endpoint_family: str | None = None,
) -> tuple[str, str, dict[str, Any]]:
    if not isinstance(provider_payload, Mapping):
        raise ProviderPayloadError("malformed_provider_response", "Provider response must be an object.")
    provider_payload = _unwrap_openai_compatible_success_payload(provider_payload)
    object_type = provider_payload.get("object")
    if object_type not in {"response", "chat.completion", None}:
        raise ProviderPayloadError(
            "unsupported_response_shape",
            "OpenAI-compatible Responses mock only accepts Responses-style fixtures.",
        )
    if object_type == "response" and (not isinstance(provider_payload.get("id"), str) or not provider_payload.get("id")):
        raise ProviderPayloadError("malformed_provider_response", "Responses fixture id is missing.")
    output_text = extract_openai_compatible_output_text(provider_payload)
    status = provider_payload.get("status")
    if object_type == "response" and status not in {"completed", None} and not output_text:
        raise ProviderPayloadError(
            "provider_error",
            "Responses fixture did not complete.",
            retryable=True,
            provider_error_code_safe=extract_safe_provider_error_code(provider_payload),
        )
    finish_reason = provider_payload.get("finish_reason") or status or "completed"
    choices = provider_payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, Mapping) and isinstance(first_choice.get("finish_reason"), str):
            finish_reason = first_choice["finish_reason"]
    if not isinstance(finish_reason, str) or not finish_reason.strip():
        finish_reason = "completed"
    inferred_endpoint = endpoint_family
    if inferred_endpoint is None:
        inferred_endpoint = "responses" if object_type == "response" else "chat_completions" if object_type == "chat.completion" else None
    usage = normalize_usage(
        provider_payload.get("usage"),
        endpoint_family=inferred_endpoint,
        retain_details=True,
        source_usage_present="usage" in provider_payload,
    )
    return output_text, finish_reason, usage


def normalize_anthropic_compatible_response(provider_payload: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if not isinstance(provider_payload, Mapping):
        raise ProviderPayloadError("malformed_provider_response", "Provider response must be an object.")
    content = provider_payload.get("content")
    fragments: list[str] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, Mapping):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                fragments.append(text.strip())
    elif isinstance(content, str) and content.strip():
        fragments.append(content.strip())
    output_text = "\n".join(fragments).strip()
    if not output_text:
        raise ProviderPayloadError("missing_output_text", "Anthropic-compatible provider response had no text output.")
    finish_reason = provider_payload.get("stop_reason")
    if not isinstance(finish_reason, str) or not finish_reason.strip():
        finish_reason = "stop"
    raw_usage = provider_payload.get("usage")
    usage = dict(raw_usage) if isinstance(raw_usage, Mapping) else raw_usage
    if not isinstance(usage, dict):
        return output_text, finish_reason, normalize_usage(
            usage,
            endpoint_family="messages",
            retain_details=True,
            source_usage_present="usage" in provider_payload,
        )
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if (
        "total_tokens" not in usage
        and isinstance(input_tokens, int)
        and isinstance(output_tokens, int)
    ):
        usage["total_tokens"] = input_tokens + output_tokens
    return output_text, finish_reason, normalize_usage(
        usage,
        endpoint_family="messages",
        retain_details=True,
        source_usage_present="usage" in provider_payload,
    )


def call_main_runtime(
    request: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    safe_logs: MutableSequence[dict[str, Any]] | None = None,
    http_transport: provider_trace_bridge.HTTPTransport | None = None,
) -> dict[str, Any]:
    start = time.monotonic()
    config = load_main_model_config(env)
    chat_projection = request.get("chat_projection")
    safe_request = deepcopy(dict(request))
    if chat_projection is not None:
        # The projection is immutable and carries an owner-private attestation.
        # deepcopy would duplicate that authority object and invalidate it.
        safe_request["chat_projection"] = chat_projection
    stats = context_packet_stats(safe_request.get("context_packet"))
    active_provider_trace: provider_trace_bridge.ProviderTraceBridge | None = None
    transport_observability: Mapping[str, Any] | None = None

    errors = validate_runtime_request(safe_request)
    errors.extend(preflight_provider_config(config))
    errors.extend(preflight_request_against_config(safe_request, config, stats))
    if errors:
        latency_ms = int((time.monotonic() - start) * 1000)
        response = build_response(
            request=safe_request,
            config=config,
            ok=False,
            errors=errors,
            latency_ms=latency_ms,
        )
        append_safe_log(safe_logs, request=safe_request, config=config, response=response, stats=stats, latency_ms=latency_ms)
        return response

    if config.provider not in {"fake", "mock_provider", "openai_compatible", "anthropic_compatible"}:
        latency_ms = int((time.monotonic() - start) * 1000)
        response = build_response(
            request=safe_request,
            config=config,
            ok=False,
            errors=[
                error_obj(
                    "real_provider_not_implemented",
                    "Real provider calls are not implemented in v0 fake-adapter lane.",
                    False,
                )
            ],
            latency_ms=latency_ms,
        )
        append_safe_log(safe_logs, request=safe_request, config=config, response=response, stats=stats, latency_ms=latency_ms)
        return response

    if config.provider == "fake":
        try:
            provider_payload = run_fake_provider(safe_request, config, stats)
        except TimeoutError:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[error_obj("timeout", "Provider call timed out.", True)],
                latency_ms=latency_ms,
            )
        except Exception:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[error_obj("provider_error", "Provider returned an adapter-level error.", True)],
                latency_ms=latency_ms,
            )
        else:
            if not isinstance(provider_payload, Mapping) or not isinstance(provider_payload.get("assistant_text"), str):
                latency_ms = int((time.monotonic() - start) * 1000)
                response = build_response(
                    request=safe_request,
                    config=config,
                    ok=False,
                    errors=[
                        error_obj(
                            "malformed_provider_response",
                            "Provider response did not match the expected fake-provider shape.",
                            False,
                        )
                    ],
                    latency_ms=latency_ms,
                )
            else:
                latency_ms = int((time.monotonic() - start) * 1000)
                response = build_response(
                    request=safe_request,
                    config=config,
                    ok=True,
                    assistant_text=provider_payload["assistant_text"],
                    latency_ms=latency_ms,
                )
    elif config.provider == "mock_provider":
        try:
            mock_request = build_mock_provider_request(safe_request, config, stats)
            provider_payload = run_mock_provider_client(mock_request, config)
            assistant_text, finish_reason, usage = normalize_mock_provider_response(provider_payload)
        except TimeoutError:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[error_obj("timeout", "Provider call timed out.", True)],
                latency_ms=latency_ms,
            )
        except MockProviderRateLimitError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[
                    error_obj(
                        "rate_limit",
                        "Provider rate limit was reached.",
                        True,
                        http_status_code=getattr(exc, "status_code", None),
                    )
                ],
                latency_ms=latency_ms,
            )
        except ValueError:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[
                    error_obj(
                        "malformed_provider_response",
                        "Provider response did not match the expected mock-provider shape.",
                        False,
                    )
                ],
                latency_ms=latency_ms,
            )
        except Exception:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[error_obj("provider_error", "Provider returned an adapter-level error.", True)],
                latency_ms=latency_ms,
            )
        else:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=True,
                assistant_text=assistant_text,
                finish_reason=finish_reason,
                usage=usage,
                latency_ms=latency_ms,
            )
    elif config.provider == "openai_compatible":
        provider_calls_made = False
        try:
            if config.openai_compatible_transport == "live_http":
                provider_calls_made = True
                active_provider_trace = _provider_trace_bridge(
                    safe_request,
                    config,
                    config.openai_compatible_endpoint,
                    env,
                )
                selected_transport = http_transport or openai_compatible_default_http_transport
                traced_transport = (
                    active_provider_trace.wrap_transport(selected_transport)
                    if active_provider_trace is not None
                    else http_transport
                )
                live_call = lambda: run_openai_compatible_live_http_client(
                    safe_request,
                    config,
                    stats,
                    env=env,
                    http_transport=traced_transport,
                )
                provider_payload = (
                    active_provider_trace.run_validated_client(live_call)
                    if active_provider_trace is not None
                    else live_call()
                )
            else:
                fixture_request = build_openai_compatible_responses_request(safe_request, config, stats)
                provider_payload = run_openai_compatible_fixture_client(fixture_request, config)
            if isinstance(provider_payload.get(_TRANSPORT_OBSERVABILITY_FIELD), Mapping):
                transport_observability = provider_payload[_TRANSPORT_OBSERVABILITY_FIELD]
            openai_normalizer = lambda payload: normalize_openai_compatible_response(
                payload,
                endpoint_family=config.openai_compatible_endpoint,
            )
            assistant_text, finish_reason, usage = (
                active_provider_trace.normalize(openai_normalizer, provider_payload)
                if active_provider_trace is not None
                else openai_normalizer(provider_payload)
            )
        except TimeoutError:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[error_obj("timeout", "Provider call timed out.", True)],
                latency_ms=latency_ms,
            )
        except MockProviderRateLimitError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[
                    error_obj(
                        "rate_limit",
                        "Provider rate limit was reached.",
                        True,
                        http_status_code=getattr(exc, "status_code", None),
                    )
                ],
                latency_ms=latency_ms,
            )
        except MockProviderAuthError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[
                    error_obj(
                        "auth_error",
                        "Provider authentication failed.",
                        False,
                        http_status_code=getattr(exc, "status_code", None),
                    )
                ],
                latency_ms=latency_ms,
            )
        except ProviderPayloadError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[
                    error_obj(
                        exc.error_class,
                        "Provider response did not match the expected Responses fixture shape.",
                        exc.retryable,
                        provider_error_code_safe=exc.provider_error_code_safe,
                    )
                ],
                latency_ms=latency_ms,
            )
        except ProviderHTTPStatusError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            if 400 <= exc.status_code <= 499:
                error_class = "provider_4xx"
                status_class = "4xx"
            elif 500 <= exc.status_code <= 599:
                error_class = "provider_5xx"
                status_class = "5xx"
            else:
                error_class = "provider_non_2xx"
                status_class = "non_2xx"
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[
                    error_obj(
                        error_class,
                        "Provider returned a non-2xx HTTP status.",
                        True,
                        provider_error_code_safe=exc.provider_error_code_safe,
                        http_status_class=status_class,
                        http_status_code=exc.status_code,
                    )
                ],
                latency_ms=latency_ms,
            )
        except Exception:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[error_obj("provider_error", "Provider returned an adapter-level error.", True)],
                latency_ms=latency_ms,
            )
        else:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=True,
                assistant_text=assistant_text,
                finish_reason=finish_reason,
                usage=usage,
                latency_ms=latency_ms,
            )
        if provider_calls_made:
            response["provider_calls_made"] = True
            response["external_provider_calls_made"] = True
    elif config.provider == "anthropic_compatible":
        provider_calls_made = False
        try:
            provider_calls_made = True
            active_provider_trace = _provider_trace_bridge(safe_request, config, "messages", env)
            selected_transport = http_transport or openai_compatible_default_http_transport
            traced_transport = (
                active_provider_trace.wrap_transport(selected_transport)
                if active_provider_trace is not None
                else http_transport
            )
            live_call = lambda: run_anthropic_compatible_live_http_client(
                safe_request,
                config,
                stats,
                env=env,
                http_transport=traced_transport,
            )
            provider_payload = (
                active_provider_trace.run_validated_client(live_call)
                if active_provider_trace is not None
                else live_call()
            )
            if isinstance(provider_payload.get(_TRANSPORT_OBSERVABILITY_FIELD), Mapping):
                transport_observability = provider_payload[_TRANSPORT_OBSERVABILITY_FIELD]
            assistant_text, finish_reason, usage = (
                active_provider_trace.normalize(normalize_anthropic_compatible_response, provider_payload)
                if active_provider_trace is not None
                else normalize_anthropic_compatible_response(provider_payload)
            )
        except TimeoutError:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[error_obj("timeout", "Provider call timed out.", True)],
                latency_ms=latency_ms,
            )
        except MockProviderAuthError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[
                    error_obj(
                        "auth_error",
                        "Provider authentication failed.",
                        False,
                        http_status_code=getattr(exc, "status_code", None),
                    )
                ],
                latency_ms=latency_ms,
            )
        except ProviderPayloadError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[
                    error_obj(
                        exc.error_class,
                        "Provider response did not match the expected Anthropic Messages shape.",
                        exc.retryable,
                        provider_error_code_safe=exc.provider_error_code_safe,
                    )
                ],
                latency_ms=latency_ms,
            )
        except ProviderHTTPStatusError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            if 400 <= exc.status_code <= 499:
                error_class = "provider_4xx"
                status_class = "4xx"
            elif 500 <= exc.status_code <= 599:
                error_class = "provider_5xx"
                status_class = "5xx"
            else:
                error_class = "provider_non_2xx"
                status_class = "non_2xx"
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[
                    error_obj(
                        error_class,
                        "Provider returned a non-2xx HTTP status.",
                        True,
                        provider_error_code_safe=exc.provider_error_code_safe,
                        http_status_class=status_class,
                        http_status_code=exc.status_code,
                    )
                ],
                latency_ms=latency_ms,
            )
        except Exception:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=False,
                errors=[error_obj("provider_error", "Provider returned an adapter-level error.", True)],
                latency_ms=latency_ms,
            )
        else:
            latency_ms = int((time.monotonic() - start) * 1000)
            response = build_response(
                request=safe_request,
                config=config,
                ok=True,
                assistant_text=assistant_text,
                finish_reason=finish_reason,
                usage=usage,
                latency_ms=latency_ms,
            )
        if provider_calls_made:
            response["provider_calls_made"] = True
            response["external_provider_calls_made"] = True

    metadata = safe_request.get("metadata") if isinstance(safe_request.get("metadata"), Mapping) else {}
    observability_metadata = (
        metadata.get("provider_observability")
        if isinstance(metadata.get("provider_observability"), Mapping)
        else {}
    )
    request_observability = (
        observability_metadata.get("request")
        if isinstance(observability_metadata.get("request"), Mapping)
        else None
    )
    if transport_observability is None and active_provider_trace is not None:
        trace_response = active_provider_trace.observability.get("response")
        if isinstance(trace_response, Mapping):
            transport_observability = {
                "request_body_utf8_bytes": (
                    active_provider_trace.observability.get("request", {}).get("request_body_utf8_bytes")
                    if isinstance(active_provider_trace.observability.get("request"), Mapping)
                    else None
                ),
                "response_bytes": trace_response.get("response_bytes"),
                "http_status": trace_response.get("http_status"),
                "safe_response_headers": trace_response.get("safe_response_headers"),
            }
    if active_provider_trace is not None or request_observability is not None or transport_observability is not None:
        try:
            adapter_observability = provider_observability.build_adapter_observability(
                request_observability=request_observability,
                usage=response.get("usage") if isinstance(response.get("usage"), Mapping) else None,
                transport_facts=transport_observability,
                endpoint_family=(
                    config.openai_compatible_endpoint
                    if config.provider == "openai_compatible"
                    else "messages"
                ),
                client_model_label=config.model,
                provider_profile=str(metadata.get("provider_profile") or config.provider),
                latency_ms=int(response.get("latency_ms") or 0),
                finish_reason=str(response.get("finish_reason") or "error"),
                ok=response.get("ok") is True,
                provider_call_made=bool(response.get("external_provider_calls_made")),
                trace_owned=bool(
                    active_provider_trace is not None
                    and active_provider_trace.receipt is not None
                ),
                causal_linkage_available=bool(
                    active_provider_trace is not None
                    and active_provider_trace.causal_linkage is not None
                ),
            )
            response["observability"] = adapter_observability
            if active_provider_trace is not None:
                active_provider_trace.record_observability({"adapter": adapter_observability})
        except Exception:
            if active_provider_trace is not None:
                active_provider_trace.mark_observability_failure("adapter_observability")

    response_errors = validate_runtime_response(response)
    if active_provider_trace is not None:
        active_provider_trace.record_stage(
            "runtime_response_validation",
            "rejected" if response_errors else "accepted",
            "adapter_response_invalid" if response_errors else None,
        )
    if response_errors:
        response = build_response(
            request=safe_request,
            config=config,
            ok=False,
            errors=[error_obj("malformed_adapter_response", "Adapter built an invalid response envelope.", False)],
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    if (
        config.provider == "openai_compatible"
        and config.openai_compatible_transport == "live_http"
        and config.openai_compatible_endpoint == "chat_completions"
        and str(
            (env or {}).get("HOUSE_CONTINUITY_V1_2_BACKEND_SHADOW_COMPARE") or ""
        ).strip()
        == "shadow_compare"
        and isinstance(transport_observability, Mapping)
        and isinstance(transport_observability.get("request_body_sha256"), str)
    ):
        # Private raw-free handoff for Gate-11 byte-invariance proof.  This is
        # attached only after the public adapter envelope has validated.
        response["_house_provider_dispatch_facts"] = {
            "schema_version": "house_provider_dispatch_facts_v1",
            "exact_dispatched_request_sha256": transport_observability[
                "request_body_sha256"
            ],
            "provider_dispatch_count": 1 if provider_calls_made else 0,
            "provider_retry_count": 0,
            "provider_fallback_count": 0,
        }

    if active_provider_trace is not None:
        active_provider_trace.record_stage(
            "final_runtime",
            "accepted" if response.get("ok") is True else "rejected",
            None if response.get("ok") is True else "runtime_rejected",
        )

    append_safe_log(
        safe_logs,
        request=safe_request,
        config=config,
        response=response,
        stats=stats,
        latency_ms=response.get("latency_ms", 0),
        provider_trace=active_provider_trace,
    )
    return response


def get_safe_config_summary(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    return load_main_model_config(env).safe_summary()
