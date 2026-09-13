"""Passive raw-free prompt-cache dispatch identities and history.

This owner records only hashes, byte counts, safe runtime identities, provider
usage, and timing. Exact private request/response bodies remain exclusively
owned by Provider Trace Vault. Observations never trigger retries, fallback,
warming calls, route changes, or user-visible failure.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4


SCHEMA_VERSION = "house_prompt_cache_dispatch_observability_v1"
STORE_SCHEMA_VERSION = "house_prompt_cache_dispatch_observability_store_v1"
STORE_DIRECTORY = "prompt_cache_observability"
STORE_FILENAME = "dispatches.sqlite3"
DEPLOYED_COMMIT_ENV = "HOUSE_DEPLOYED_COMMIT"
SQLITE_BUSY_TIMEOUT_SECONDS = 0.25

CACHE_HIT = "confirmed_cache_hit"
CACHE_MISS_NO_PRIOR_HIT = "cache_miss_no_prior_confirmed_hit"
CACHE_MISS_SAME_SIGNATURE = "upstream_cache_miss_same_house_signature"
CACHE_RESULT_UNEXPOSED = "provider_cache_result_unexposed"
PROVIDER_ATTEMPT_FAILED = "provider_attempt_failed"
UPSTREAM_SUBCAUSE_UNKNOWN = "unknown"
KNOWN_TOOL_SERIALIZATION_ISSUE = (
    "candidate_vs_live_tool_object_key_order_differs"
)

_LOWER_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,199}$")
_OBSERVATION_ID_RE = re.compile(r"^pcobs_[0-9a-f]{32}$")
_TRACE_ID_RE = re.compile(r"^ptv1_[0-9a-f]{32}$")
_METADATA_DDL = (
    "CREATE TABLE IF NOT EXISTS prompt_cache_observability_metadata "
    "(schema_version TEXT PRIMARY KEY NOT NULL)"
)
_DISPATCH_DDL = """CREATE TABLE IF NOT EXISTS prompt_cache_dispatches (
    observation_id TEXT PRIMARY KEY NOT NULL,
    cache_signature_sha256 TEXT NOT NULL,
    request_at_utc TEXT NOT NULL,
    response_at_utc TEXT,
    house_turn_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    trace_id TEXT,
    request_observation_json TEXT NOT NULL,
    result_observation_json TEXT,
    confirmed_cache_hit INTEGER,
    classification TEXT
)"""
_SIGNATURE_REQUEST_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS prompt_cache_dispatch_signature_request_idx "
    "ON prompt_cache_dispatches(cache_signature_sha256, request_at_utc)"
)
_SIGNATURE_HIT_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS prompt_cache_dispatch_signature_hit_idx "
    "ON prompt_cache_dispatches(cache_signature_sha256, confirmed_cache_hit, request_at_utc)"
)


class PromptCacheDispatchObservabilityError(RuntimeError):
    pass


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _compact_json_bytes(value: Any, *, sort_keys: bool = False) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=sort_keys,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise PromptCacheDispatchObservabilityError(
            "prompt-cache identity value is not canonically encodable"
        ) from exc


def _safe_id(value: Any, *, fallback: str) -> str:
    candidate = str(value or "").strip()
    return candidate if _SAFE_ID_RE.fullmatch(candidate) else fallback


def _safe_optional_id(value: Any) -> str | None:
    candidate = str(value or "").strip()
    return candidate if _SAFE_ID_RE.fullmatch(candidate) else None


def _safe_sha256(value: Any) -> str | None:
    candidate = str(value or "").strip()
    return candidate if _LOWER_SHA256_RE.fullmatch(candidate) else None


def _utc_text(value: datetime | str | None = None) -> str:
    if value is None:
        current = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        current = value
    elif isinstance(value, str):
        try:
            current = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PromptCacheDispatchObservabilityError(
                "observability timestamp is invalid"
            ) from exc
    else:
        raise PromptCacheDispatchObservabilityError(
            "observability timestamp is invalid"
        )
    if current.tzinfo is None:
        raise PromptCacheDispatchObservabilityError(
            "observability timestamp must be timezone-aware"
        )
    return current.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _elapsed_millis(later: str, earlier: str | None) -> int | None:
    if earlier is None:
        return None
    later_value = datetime.fromisoformat(later.replace("Z", "+00:00"))
    earlier_value = datetime.fromisoformat(earlier.replace("Z", "+00:00"))
    return max(0, int((later_value - earlier_value).total_seconds() * 1000))


def _selection_metadata(request_metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    value = request_metadata.get("standing_root_v2_selection")
    return value if isinstance(value, Mapping) else {}


def _cache_metadata(request_metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    value = request_metadata.get("prompt_cache")
    return value if isinstance(value, Mapping) else {}


def _retention(body: Mapping[str, Any]) -> tuple[str, str]:
    if "prompt_cache_retention" in body:
        return "prompt_cache_retention", str(
            body.get("prompt_cache_retention") or ""
        )
    options = body.get("prompt_cache_options")
    if isinstance(options, Mapping):
        return "prompt_cache_options.ttl", str(options.get("ttl") or "")
    return "", ""


def _deployed_commit(env: Mapping[str, str]) -> tuple[str | None, str]:
    raw = str(env.get(DEPLOYED_COMMIT_ENV) or "").strip().casefold()
    if not raw:
        return None, "unavailable_not_configured"
    if _COMMIT_RE.fullmatch(raw):
        return raw, "configured"
    return None, "invalid_not_recorded"


def _service_identity(
    env: Mapping[str, str],
    *,
    service_boot_id: str | None,
) -> dict[str, Any]:
    invocation = _safe_optional_id(env.get("INVOCATION_ID"))
    boot = _safe_optional_id(service_boot_id)
    return {
        "systemd_invocation_id": invocation,
        "service_boot_id": boot,
        "systemd_invocation_identity_state": (
            "configured" if invocation is not None else "unavailable"
        ),
        "service_boot_identity_state": (
            "configured" if boot is not None else "unavailable"
        ),
    }


def _ordered_tool_identities(
    tools: Sequence[Mapping[str, Any]],
    *,
    tool_identity_by_provider_name: Mapping[str, str],
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for index, tool in enumerate(tools):
        function = (
            tool.get("function")
            if isinstance(tool.get("function"), Mapping)
            else {}
        )
        provider_name = _safe_id(
            function.get("name"),
            fallback=f"unavailable_tool_{index}",
        )
        values.append(
            {
                "index": index,
                "provider_name": provider_name,
                "tool_identity": _safe_id(
                    tool_identity_by_provider_name.get(provider_name),
                    fallback="unavailable",
                ),
            }
        )
    return values


def build_dispatch_request_observation(
    *,
    body: Mapping[str, Any],
    request_body: bytes,
    request_metadata: Mapping[str, Any],
    house_turn_id: str,
    operation_id: str,
    provider_leg_request_id: str,
    provider_profile: str,
    endpoint_family: str,
    tool_identity_by_provider_name: Mapping[str, str],
    env: Mapping[str, str],
    request_at_utc: datetime | str | None = None,
    service_boot_id: str | None = None,
) -> dict[str, Any] | None:
    """Build one raw-free identity from the exact body about to be dispatched."""

    cache = _cache_metadata(request_metadata)
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
    tools_value = body.get("tools")
    tools = (
        list(tools_value)
        if isinstance(tools_value, list)
        and all(isinstance(item, Mapping) for item in tools_value)
        else []
    )
    stable_messages = list(messages[:provider_stable_count])
    dynamic_messages = list(messages[provider_stable_count:])
    stable_message_bytes = _compact_json_bytes(stable_messages)
    tool_block_bytes = _compact_json_bytes(tools)
    dynamic_tail_bytes = _compact_json_bytes(dynamic_messages)
    semantic_surface = {
        "model": body.get("model"),
        "messages": stable_messages,
        "tools": tools,
        "tool_choice": body.get("tool_choice"),
        "parallel_tool_calls": body.get("parallel_tool_calls"),
    }
    semantic_bytes = _compact_json_bytes(semantic_surface, sort_keys=True)
    retention_field, retention_value = _retention(body)
    selection = _selection_metadata(request_metadata)
    cache_key = (
        str(body.get("prompt_cache_key"))
        if isinstance(body.get("prompt_cache_key"), str)
        else None
    )
    model = _safe_id(body.get("model"), fallback="unavailable")
    endpoint = _safe_id(endpoint_family, fallback="unavailable")
    tool_choice = _safe_id(body.get("tool_choice"), fallback="unavailable")
    parallel = (
        body.get("parallel_tool_calls")
        if type(body.get("parallel_tool_calls")) is bool
        else None
    )
    stable_semantic_sha256 = _sha256(semantic_bytes)
    stable_messages_sha256 = _sha256(stable_message_bytes)
    tool_block_sha256 = _sha256(tool_block_bytes)
    signature_payload = {
        "model": model,
        "endpoint_family": endpoint,
        "cache_key": cache_key,
        "retention_field": retention_field,
        "retention_value": retention_value,
        "canonical_semantic_stable_surface_sha256": (
            stable_semantic_sha256
        ),
        "serialized_stable_messages_sha256": stable_messages_sha256,
        "serialized_tool_block_sha256": tool_block_sha256,
        "tool_choice": tool_choice,
        "parallel_tool_calls": parallel,
    }
    signature_bytes = _compact_json_bytes(signature_payload, sort_keys=True)
    deployed_commit, deployed_commit_state = _deployed_commit(env)
    return {
        "schema_version": SCHEMA_VERSION,
        "raw_private_body_present": False,
        "request_at_utc": _utc_text(request_at_utc),
        "house_turn_id": _safe_id(house_turn_id, fallback="unavailable"),
        "operation_id": _safe_id(operation_id, fallback="unavailable"),
        "provider_leg_request_id": _safe_id(
            provider_leg_request_id,
            fallback="unavailable",
        ),
        "effective_assembly": _safe_id(
            selection.get("active_prefix_assembly_version"),
            fallback="unavailable",
        ),
        "effective_profile": _safe_id(
            selection.get("active_prefix_profile"),
            fallback="unavailable",
        ),
        "effective_generation": _safe_id(
            selection.get("active_prefix_generation"),
            fallback="unavailable",
        ),
        "local_assembly_fallback_state": _safe_id(
            selection.get("fallback_state"),
            fallback="unavailable",
        ),
        "deployed_commit": deployed_commit,
        "deployed_commit_state": deployed_commit_state,
        "provider_profile": _safe_id(
            provider_profile,
            fallback="unavailable",
        ),
        "model": model,
        "endpoint_family": endpoint,
        "cache_key": cache_key,
        "requested_retention_field": retention_field,
        "requested_retention_value": retention_value,
        "canonical_semantic_stable_surface": {
            "bytes": len(semantic_bytes),
            "sha256": stable_semantic_sha256,
        },
        "exact_serialized_stable_messages": {
            "bytes": len(stable_message_bytes),
            "sha256": stable_messages_sha256,
            "message_count": provider_stable_count,
        },
        "exact_serialized_tool_block": {
            "bytes": len(tool_block_bytes),
            "sha256": tool_block_sha256,
            "tool_count": len(tools),
            "ordered_tool_identities": _ordered_tool_identities(
                tools,
                tool_identity_by_provider_name=tool_identity_by_provider_name,
            ),
        },
        "tool_choice": tool_choice,
        "parallel_tool_calls": parallel,
        "dynamic_tail": {
            "bytes": len(dynamic_tail_bytes),
            "sha256": _sha256(dynamic_tail_bytes),
            "message_count": len(dynamic_messages),
        },
        "complete_endpoint_request": {
            "bytes": len(request_body),
            "sha256": _sha256(request_body),
        },
        "cache_signature": {
            "schema_version": (
                "house_prompt_cache_provider_input_signature_v1"
            ),
            "sha256": _sha256(signature_bytes),
            "provider_internal_cache_key_claimed": False,
            "components": signature_payload,
        },
        "service_identity": _service_identity(
            env,
            service_boot_id=service_boot_id,
        ),
        "credential_identity": {
            "state": "unavailable_no_existing_safe_owner",
            "credential_slot_id": None,
            "credential_hmac_fingerprint": None,
            "secret_inspected": False,
        },
        "exact_private_body_owner": "provider_trace_vault_v0",
        "known_issues": [
            {
                "issue_id": KNOWN_TOOL_SERIALIZATION_ISSUE,
                "state": "preserved_unmodified",
                "repair_gate": "later_deterministic_serialization_gate",
            }
        ],
    }


def _cache_field_present(usage: Mapping[str, Any]) -> bool:
    presence = (
        usage.get("source_field_presence")
        if isinstance(usage.get("source_field_presence"), Mapping)
        else {}
    )
    return bool(
        usage.get("cached_input_tokens") is not None
        or presence.get("usage.prompt_tokens_details.cached_tokens") is True
        or presence.get("usage.input_tokens_details.cached_tokens") is True
        or presence.get("usage.cached_input_tokens") is True
    )


_RAW_USAGE_SCALAR_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "estimated_cost",
    "provider_reported_cost",
    "currency",
)
_RAW_USAGE_DETAIL_FIELDS = {
    "prompt_tokens_details": ("cached_tokens", "cache_write_tokens"),
    "input_tokens_details": ("cached_tokens", "cache_write_tokens"),
    "completion_tokens_details": ("reasoning_tokens",),
    "output_tokens_details": ("reasoning_tokens",),
}


def _bounded_raw_usage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for field in _RAW_USAGE_SCALAR_FIELDS:
        if field in value and isinstance(value.get(field), (str, int, float)):
            result[field] = value[field]
    for field, allowed_nested_fields in _RAW_USAGE_DETAIL_FIELDS.items():
        details = value.get(field)
        if not isinstance(details, Mapping):
            continue
        selected = {
            nested_field: details[nested_field]
            for nested_field in allowed_nested_fields
            if nested_field in details and isinstance(details.get(nested_field), (int, float))
        }
        if selected:
            result[field] = selected
    return result


def _raw_usage(response_body: bytes | None) -> tuple[dict[str, Any] | None, str | None, str | None]:
    if response_body is None:
        return None, None, None
    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None, None
    if not isinstance(payload, Mapping):
        return None, None, None
    return (
        _bounded_raw_usage(payload.get("usage")),
        _safe_optional_id(payload.get("id")),
        _safe_optional_id(payload.get("model")),
    )


def _safe_headers(value: Mapping[str, Any] | None) -> dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    return {
        "gateway_request_id": _safe_optional_id(
            source.get("gateway_request_id")
        ),
        "final_model": _safe_optional_id(source.get("final_model")),
        "fallback": _safe_optional_id(source.get("fallback")),
    }


class PromptCacheDispatchObservabilityStore:
    """Small persistent raw-free history keyed by House cache signature."""

    def __init__(self, sqlite_path: str | Path) -> None:
        self.path = Path(sqlite_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=SQLITE_BUSY_TIMEOUT_SECONDS,
        )
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute(_METADATA_DDL)
            db.execute(_DISPATCH_DDL)
            db.execute(_SIGNATURE_REQUEST_INDEX_DDL)
            db.execute(_SIGNATURE_HIT_INDEX_DDL)
            versions = [
                row[0]
                for row in db.execute(
                    "SELECT schema_version FROM prompt_cache_observability_metadata"
                )
            ]
            if not versions:
                db.execute(
                    "INSERT INTO prompt_cache_observability_metadata VALUES (?)",
                    (STORE_SCHEMA_VERSION,),
                )
            elif versions != [STORE_SCHEMA_VERSION]:
                raise PromptCacheDispatchObservabilityError(
                    "prompt-cache observability store schema is incompatible"
                )

    def begin_dispatch(
        self,
        request_observation: Mapping[str, Any],
    ) -> dict[str, Any]:
        value = deepcopy(dict(request_observation))
        if (
            value.get("schema_version") != SCHEMA_VERSION
            or value.get("raw_private_body_present") is not False
        ):
            raise PromptCacheDispatchObservabilityError(
                "prompt-cache request observation is invalid"
            )
        signature = (
            value.get("cache_signature", {}).get("sha256")
            if isinstance(value.get("cache_signature"), Mapping)
            else None
        )
        if _safe_sha256(signature) is None:
            raise PromptCacheDispatchObservabilityError(
                "prompt-cache signature is invalid"
            )
        request_at = _utc_text(value.get("request_at_utc"))
        observation_id = f"pcobs_{uuid4().hex}"
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous_request = db.execute(
                "SELECT request_at_utc FROM prompt_cache_dispatches "
                "WHERE cache_signature_sha256=? AND request_at_utc<? "
                "ORDER BY request_at_utc DESC LIMIT 1",
                (signature, request_at),
            ).fetchone()
            previous_hit = db.execute(
                "SELECT request_at_utc FROM prompt_cache_dispatches "
                "WHERE cache_signature_sha256=? AND confirmed_cache_hit=1 "
                "AND request_at_utc<? ORDER BY request_at_utc DESC LIMIT 1",
                (signature, request_at),
            ).fetchone()
            timing = {
                "time_since_previous_same_signature_request_ms": (
                    _elapsed_millis(
                        request_at,
                        previous_request["request_at_utc"],
                    )
                    if previous_request is not None
                    else None
                ),
                "time_since_previous_confirmed_same_signature_hit_ms": (
                    _elapsed_millis(
                        request_at,
                        previous_hit["request_at_utc"],
                    )
                    if previous_hit is not None
                    else None
                ),
            }
            value["timing"] = timing
            db.execute(
                "INSERT INTO prompt_cache_dispatches "
                "(observation_id,cache_signature_sha256,request_at_utc,"
                "house_turn_id,operation_id,request_observation_json) "
                "VALUES (?,?,?,?,?,?)",
                (
                    observation_id,
                    signature,
                    request_at,
                    value["house_turn_id"],
                    value["operation_id"],
                    json.dumps(
                        value,
                        ensure_ascii=True,
                        allow_nan=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                ),
            )
        return {
            "observation_id": observation_id,
            "cache_signature_sha256": signature,
            **timing,
        }

    def complete_dispatch(
        self,
        observation_id: str,
        *,
        trace_id: str | None,
        response_body: bytes | None,
        normalized_usage: Mapping[str, Any] | None,
        safe_response_headers: Mapping[str, Any] | None,
        final_model: str | None,
        dispatch_count: int,
        retry_count: int,
        response_at_utc: datetime | str | None = None,
        transport_error: str | None = None,
    ) -> dict[str, Any]:
        if not _OBSERVATION_ID_RE.fullmatch(str(observation_id or "")):
            raise PromptCacheDispatchObservabilityError(
                "prompt-cache observation identity is invalid"
            )
        if trace_id is not None and not _TRACE_ID_RE.fullmatch(trace_id):
            raise PromptCacheDispatchObservabilityError(
                "provider trace identity is invalid"
            )
        if (
            type(dispatch_count) is not int
            or dispatch_count < 1
            or type(retry_count) is not int
            or retry_count < 0
        ):
            raise PromptCacheDispatchObservabilityError(
                "dispatch/retry counts are invalid"
            )
        usage = (
            deepcopy(dict(normalized_usage))
            if isinstance(normalized_usage, Mapping)
            else {}
        )
        cached_tokens = usage.get("cached_input_tokens")
        cache_field_present = _cache_field_present(usage)
        response_at = _utc_text(response_at_utc)
        raw_usage, provider_response_id, response_model = _raw_usage(
            response_body
        )
        headers = _safe_headers(safe_response_headers)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT request_observation_json FROM prompt_cache_dispatches "
                "WHERE observation_id=?",
                (observation_id,),
            ).fetchone()
            if row is None:
                raise PromptCacheDispatchObservabilityError(
                    "prompt-cache observation does not exist"
                )
            request_observation = json.loads(row["request_observation_json"])
            dispatch_latency_ms = _elapsed_millis(
                response_at,
                request_observation["request_at_utc"],
            )
            prior_hit_ms = request_observation["timing"][
                "time_since_previous_confirmed_same_signature_hit_ms"
            ]
            if transport_error:
                classification = PROVIDER_ATTEMPT_FAILED
                confirmed_hit: int | None = None
            elif cache_field_present and isinstance(cached_tokens, int):
                if cached_tokens > 0:
                    classification = CACHE_HIT
                    confirmed_hit = 1
                elif prior_hit_ms is not None:
                    classification = CACHE_MISS_SAME_SIGNATURE
                    confirmed_hit = 0
                else:
                    classification = CACHE_MISS_NO_PRIOR_HIT
                    confirmed_hit = 0
            else:
                classification = CACHE_RESULT_UNEXPOSED
                confirmed_hit = None
            result = {
                "schema_version": SCHEMA_VERSION,
                "raw_private_body_present": False,
                "response_at_utc": response_at,
                "dispatch_latency_ms": dispatch_latency_ms,
                "trace_id": trace_id,
                "provider_response_id": provider_response_id,
                "gateway_request_id": headers["gateway_request_id"],
                "raw_provider_usage": raw_usage,
                "normalized_house_usage": usage,
                "cache_field_present": cache_field_present,
                "cached_input_tokens": (
                    cached_tokens if isinstance(cached_tokens, int) else None
                ),
                "final_model": (
                    _safe_optional_id(final_model)
                    or headers["final_model"]
                    or response_model
                ),
                "dispatch_count": dispatch_count,
                "retry_count": retry_count,
                "provider_fallback": headers["fallback"],
                "local_fallback_state": request_observation.get(
                    "local_assembly_fallback_state"
                ),
                "classification": classification,
                "upstream_subcause": (
                    UPSTREAM_SUBCAUSE_UNKNOWN
                    if classification == CACHE_MISS_SAME_SIGNATURE
                    else None
                ),
                "transport_error": _safe_optional_id(transport_error),
                "actions": {
                    "retry_triggered": False,
                    "fallback_triggered": False,
                    "cache_warming_triggered": False,
                    "route_switch_triggered": False,
                    "user_visible_failure_triggered": False,
                },
                "private_body_reference": {
                    "owner": "provider_trace_vault_v0",
                    "trace_id": trace_id,
                    "body_copied_into_ordinary_monitoring": False,
                },
            }
            db.execute(
                "UPDATE prompt_cache_dispatches SET response_at_utc=?,trace_id=?,"
                "result_observation_json=?,confirmed_cache_hit=?,classification=? "
                "WHERE observation_id=?",
                (
                    response_at,
                    trace_id,
                    json.dumps(
                        result,
                        ensure_ascii=True,
                        allow_nan=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    confirmed_hit,
                    classification,
                    observation_id,
                ),
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "observation_id": observation_id,
            "cache_signature_sha256": request_observation["cache_signature"][
                "sha256"
            ],
            "classification": classification,
            "upstream_subcause": result["upstream_subcause"],
            "time_since_previous_same_signature_request_ms": (
                request_observation["timing"][
                    "time_since_previous_same_signature_request_ms"
                ]
            ),
            "time_since_previous_confirmed_same_signature_hit_ms": (
                prior_hit_ms
            ),
            "dispatch_latency_ms": dispatch_latency_ms,
            "trace_id": trace_id,
            "raw_private_body_present": False,
            "actions": deepcopy(result["actions"]),
        }

    def update_dispatch_count(
        self,
        observation_id: str,
        *,
        dispatch_count: int,
        retry_count: int = 0,
    ) -> dict[str, Any] | None:
        if not _OBSERVATION_ID_RE.fullmatch(str(observation_id or "")):
            raise PromptCacheDispatchObservabilityError(
                "prompt-cache observation identity is invalid"
            )
        if (
            type(dispatch_count) is not int
            or dispatch_count < 1
            or type(retry_count) is not int
            or retry_count < 0
        ):
            raise PromptCacheDispatchObservabilityError(
                "dispatch/retry counts are invalid"
            )
        with self._connect() as db:
            row = db.execute(
                "SELECT result_observation_json FROM prompt_cache_dispatches "
                "WHERE observation_id=?",
                (observation_id,),
            ).fetchone()
            if row is None or row["result_observation_json"] is None:
                return None
            value = json.loads(row["result_observation_json"])
            value["dispatch_count"] = dispatch_count
            value["retry_count"] = retry_count
            db.execute(
                "UPDATE prompt_cache_dispatches SET result_observation_json=? "
                "WHERE observation_id=?",
                (
                    json.dumps(
                        value,
                        ensure_ascii=True,
                        allow_nan=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    observation_id,
                ),
            )
        return value

    def read_observation(self, observation_id: str) -> dict[str, Any]:
        if not _OBSERVATION_ID_RE.fullmatch(str(observation_id or "")):
            raise PromptCacheDispatchObservabilityError(
                "prompt-cache observation identity is invalid"
            )
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM prompt_cache_dispatches WHERE observation_id=?",
                (observation_id,),
            ).fetchone()
        if row is None:
            raise PromptCacheDispatchObservabilityError(
                "prompt-cache observation does not exist"
            )
        return {
            "observation_id": row["observation_id"],
            "request": json.loads(row["request_observation_json"]),
            "result": (
                json.loads(row["result_observation_json"])
                if row["result_observation_json"] is not None
                else None
            ),
        }

    def list_observations(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT observation_id FROM prompt_cache_dispatches "
                "ORDER BY request_at_utc,observation_id"
            ).fetchall()
        return [self.read_observation(row["observation_id"]) for row in rows]


def safe_runtime_summary(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    signature = _safe_sha256(value.get("cache_signature_sha256"))
    classification = _safe_optional_id(value.get("classification"))
    observation_id = str(value.get("observation_id") or "")
    if (
        signature is None
        or classification is None
        or not _OBSERVATION_ID_RE.fullmatch(observation_id)
        or value.get("raw_private_body_present") is not False
    ):
        return None
    previous_request_ms = value.get(
        "time_since_previous_same_signature_request_ms"
    )
    previous_hit_ms = value.get(
        "time_since_previous_confirmed_same_signature_hit_ms"
    )
    dispatch_latency_ms = value.get("dispatch_latency_ms")
    if (
        previous_request_ms is not None
        and (type(previous_request_ms) is not int or previous_request_ms < 0)
    ) or (
        previous_hit_ms is not None
        and (type(previous_hit_ms) is not int or previous_hit_ms < 0)
    ) or (
        dispatch_latency_ms is not None
        and (type(dispatch_latency_ms) is not int or dispatch_latency_ms < 0)
    ):
        return None
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "recorded",
        "observation_id": observation_id,
        "cache_signature_sha256": signature,
        "provider_internal_cache_key_claimed": False,
        "classification": classification,
        "upstream_subcause": (
            _safe_optional_id(value.get("upstream_subcause"))
        ),
        "time_since_previous_same_signature_request_ms": previous_request_ms,
        "time_since_previous_confirmed_same_signature_hit_ms": previous_hit_ms,
        "dispatch_latency_ms": dispatch_latency_ms,
        "raw_private_body_present": False,
        "actions": {
            "retry_triggered": False,
            "fallback_triggered": False,
            "cache_warming_triggered": False,
            "route_switch_triggered": False,
            "user_visible_failure_triggered": False,
        },
    }


__all__ = [
    "CACHE_HIT",
    "CACHE_MISS_NO_PRIOR_HIT",
    "CACHE_MISS_SAME_SIGNATURE",
    "CACHE_RESULT_UNEXPOSED",
    "DEPLOYED_COMMIT_ENV",
    "KNOWN_TOOL_SERIALIZATION_ISSUE",
    "PROVIDER_ATTEMPT_FAILED",
    "PromptCacheDispatchObservabilityError",
    "PromptCacheDispatchObservabilityStore",
    "SCHEMA_VERSION",
    "STORE_DIRECTORY",
    "STORE_FILENAME",
    "UPSTREAM_SUBCAUSE_UNKNOWN",
    "build_dispatch_request_observation",
    "safe_runtime_summary",
]
