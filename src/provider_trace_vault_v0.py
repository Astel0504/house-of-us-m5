"""Private backend storage for exact provider-attempt request and response bytes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Mapping
from uuid import uuid4

import provider_observability_v0 as provider_observability


SCHEMA = "house_provider_trace_vault_attempt_v0"
REQUEST_FILE = "request.body"
RESPONSE_FILE = "response.body"
MANIFEST_FILE = "manifest.json"

_TRACE_ID_RE = re.compile(r"ptv1_[0-9a-f]{32}")
_SAFE_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}")
_SAFE_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SAFE_MODEL_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+-]{0,127}")
_ALLOWED_OUTCOMES = frozenset({"accepted", "rejected", "transport_error"})
_OBSERVABILITY_DIAGNOSTICS = frozenset(
    {
        "causal_linkage_invalid",
        "observability_update_invalid",
        "request_observability_invalid",
        "response_observability_invalid",
    }
)
_MUTATION_LOCK = threading.RLock()


class ProviderTraceVaultError(ValueError):
    """Raised when a trace request or stored trace is invalid."""


@dataclass(frozen=True)
class ProviderTraceReceipt:
    """Raw-free identity and size receipt safe for ordinary diagnostics."""

    trace_id: str
    request_sha256: str
    request_byte_count: int
    response_sha256: str | None
    response_byte_count: int | None
    response_received: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "request_sha256": self.request_sha256,
            "request_byte_count": self.request_byte_count,
            "response_sha256": self.response_sha256,
            "response_byte_count": self.response_byte_count,
            "response_received": self.response_received,
        }


def _utc_timestamp(value: datetime | None = None) -> str:
    current = value if value is not None else datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ProviderTraceVaultError("timestamps must be timezone-aware")
    return current.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _require_bytes(value: Any, *, field: str) -> bytes:
    if type(value) is not bytes:
        raise ProviderTraceVaultError(f"{field} must be bytes")
    return value


def _safe_identifier(value: Any, *, field: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not _SAFE_IDENTIFIER_RE.fullmatch(value):
        raise ProviderTraceVaultError(f"{field} must be a short safe identifier")
    return value


def _safe_label(value: Any, *, field: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not _SAFE_LABEL_RE.fullmatch(value):
        raise ProviderTraceVaultError(f"{field} must be a short safe label")
    return value


def _safe_model_label(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 255 or "://" in value or "\\" in value:
        raise ProviderTraceVaultError("model_label must be a short safe model identity")
    segments = value.split("/")
    if any(segment in {"", ".", ".."} or not _SAFE_MODEL_SEGMENT_RE.fullmatch(segment) for segment in segments):
        raise ProviderTraceVaultError("model_label must be a short safe model identity")
    return value


def _validate_trace_id(trace_id: Any) -> str:
    if not isinstance(trace_id, str) or not _TRACE_ID_RE.fullmatch(trace_id):
        raise ProviderTraceVaultError("trace_id must use the ptv1_<32 lowercase hex> form")
    return trace_id


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _best_effort_chmod(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        # Windows and some mounted filesystems cannot express POSIX owner-only modes.
        pass


def _private_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o2750)
    _best_effort_chmod(path, 0o2750)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_bytes(path: Path, body: bytes) -> None:
    _private_mkdir(path.parent)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        _best_effort_chmod(temp_path, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _best_effort_chmod(path, 0o640)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _atomic_write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    payload = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write_bytes(path, payload)


class ProviderTraceVault:
    """Owns durable, per-attempt provider trace artifacts under one private root."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)
        _private_mkdir(self.root)

    def begin_attempt(
        self,
        request_body: bytes,
        *,
        operation_id: str,
        request_id: str | None,
        provider_label: str,
        model_label: str,
        endpoint_family: str,
        attempt_number: int,
        causal_linkage: Mapping[str, Any] | None = None,
        request_observability: Mapping[str, Any] | None = None,
        trace_id: str | None = None,
        started_at: datetime | None = None,
    ) -> ProviderTraceReceipt:
        body = _require_bytes(request_body, field="request_body")
        operation = _safe_identifier(operation_id, field="operation_id")
        request = _safe_identifier(request_id, field="request_id", optional=True)
        provider = _safe_label(provider_label, field="provider_label")
        model = _safe_model_label(model_label)
        endpoint = _safe_label(endpoint_family, field="endpoint_family")
        if not isinstance(attempt_number, int) or isinstance(attempt_number, bool) or attempt_number < 1:
            raise ProviderTraceVaultError("attempt_number must be a positive integer")
        selected_trace_id = _validate_trace_id(trace_id) if trace_id is not None else f"ptv1_{uuid4().hex}"
        now = _utc_timestamp(started_at)
        request_sha = _sha256(body)
        observability_diagnostics: list[str] = []
        try:
            safe_causal_linkage = provider_observability.validate_causal_linkage(causal_linkage)
        except Exception:
            safe_causal_linkage = None
            observability_diagnostics.append("causal_linkage_invalid")
        try:
            safe_observability = (
                provider_observability.merge_trace_observability(
                    None,
                    {"request": request_observability},
                )
                if request_observability is not None
                else None
            )
        except Exception:
            safe_observability = None
            observability_diagnostics.append("request_observability_invalid")

        with _MUTATION_LOCK:
            trace_dir = self._trace_dir(selected_trace_id)
            if trace_dir.exists():
                raise ProviderTraceVaultError("trace_id already exists")
            _private_mkdir(trace_dir)
            _atomic_write_bytes(trace_dir / REQUEST_FILE, body)
            manifest: dict[str, Any] = {
                "schema": SCHEMA,
                "trace_id": selected_trace_id,
                "operation_id": operation,
                "request_id": request,
                "provider_label": provider,
                "model_label": model,
                "endpoint_family": endpoint,
                "attempt_number": attempt_number,
                "started_at_utc": now,
                "updated_at_utc": now,
                "http_status": None,
                "response_received": False,
                "request": {
                    "file": REQUEST_FILE,
                    "byte_count": len(body),
                    "sha256": request_sha,
                },
                "response": None,
                "stages": [
                    {
                        "stage": "request_capture",
                        "outcome": "accepted",
                        "at_utc": now,
                        "reason_label": None,
                    }
                ],
            }
            if safe_causal_linkage is not None:
                manifest["causal_linkage"] = safe_causal_linkage
            if safe_observability is not None:
                manifest["observability"] = safe_observability
            if observability_diagnostics:
                manifest["observability_diagnostics"] = observability_diagnostics
            _atomic_write_manifest(trace_dir / MANIFEST_FILE, manifest)
        return self._receipt(manifest)

    def record_response(
        self,
        trace_id: str,
        response_body: bytes,
        *,
        http_status: int | None,
        received_at: datetime | None = None,
    ) -> ProviderTraceReceipt:
        body = _require_bytes(response_body, field="response_body")
        if http_status is not None and (
            not isinstance(http_status, int)
            or isinstance(http_status, bool)
            or not 100 <= http_status <= 599
        ):
            raise ProviderTraceVaultError("http_status must be null or an HTTP status from 100 to 599")
        now = _utc_timestamp(received_at)
        with _MUTATION_LOCK:
            trace_dir, manifest = self._load_trace(trace_id)
            if manifest["response_received"]:
                raise ProviderTraceVaultError("response already recorded for trace")
            _atomic_write_bytes(trace_dir / RESPONSE_FILE, body)
            manifest["http_status"] = http_status
            manifest["response_received"] = True
            manifest["response"] = {
                "file": RESPONSE_FILE,
                "byte_count": len(body),
                "sha256": _sha256(body),
            }
            manifest["updated_at_utc"] = now
            manifest["stages"].append(
                {
                    "stage": "response_capture",
                    "outcome": "accepted",
                    "at_utc": now,
                    "reason_label": None,
                }
            )
            _atomic_write_manifest(trace_dir / MANIFEST_FILE, manifest)
        return self._receipt(manifest)

    def record_stage(
        self,
        trace_id: str,
        *,
        stage: str,
        outcome: str,
        reason_label: str | None = None,
        recorded_at: datetime | None = None,
    ) -> ProviderTraceReceipt:
        stage_label = _safe_label(stage, field="stage")
        if outcome not in _ALLOWED_OUTCOMES:
            raise ProviderTraceVaultError("outcome must be accepted, rejected, or transport_error")
        reason = _safe_label(reason_label, field="reason_label", optional=True)
        now = _utc_timestamp(recorded_at)
        with _MUTATION_LOCK:
            trace_dir, manifest = self._load_trace(trace_id)
            manifest["stages"].append(
                {
                    "stage": stage_label,
                    "outcome": outcome,
                    "at_utc": now,
                    "reason_label": reason,
                }
            )
            manifest["updated_at_utc"] = now
            _atomic_write_manifest(trace_dir / MANIFEST_FILE, manifest)
        return self._receipt(manifest)

    def record_transport_error(
        self,
        trace_id: str,
        *,
        reason_label: str,
        recorded_at: datetime | None = None,
    ) -> ProviderTraceReceipt:
        return self.record_stage(
            trace_id,
            stage="transport",
            outcome="transport_error",
            reason_label=reason_label,
            recorded_at=recorded_at,
        )

    def record_observability(
        self,
        trace_id: str,
        observability: Mapping[str, Any],
        *,
        recorded_at: datetime | None = None,
    ) -> ProviderTraceReceipt:
        """Merge one versioned raw-free observability update into a trace manifest."""

        now = _utc_timestamp(recorded_at)
        with _MUTATION_LOCK:
            trace_dir, manifest = self._load_trace(trace_id)
            try:
                manifest["observability"] = provider_observability.merge_trace_observability(
                    manifest.get("observability"),
                    observability,
                )
            except Exception:
                diagnostics = manifest.setdefault("observability_diagnostics", [])
                if "observability_update_invalid" not in diagnostics:
                    diagnostics.append("observability_update_invalid")
            manifest["updated_at_utc"] = now
            _atomic_write_manifest(trace_dir / MANIFEST_FILE, manifest)
        return self._receipt(manifest)

    def record_observability_diagnostic(
        self,
        trace_id: str,
        diagnostic: str,
        *,
        recorded_at: datetime | None = None,
    ) -> ProviderTraceReceipt:
        """Record one fixed raw-free telemetry failure without touching captured bodies."""

        if diagnostic not in _OBSERVABILITY_DIAGNOSTICS:
            raise ProviderTraceVaultError("observability diagnostic is not reviewed")
        now = _utc_timestamp(recorded_at)
        with _MUTATION_LOCK:
            trace_dir, manifest = self._load_trace(trace_id)
            diagnostics = manifest.setdefault("observability_diagnostics", [])
            if diagnostic not in diagnostics:
                diagnostics.append(diagnostic)
            manifest["updated_at_utc"] = now
            _atomic_write_manifest(trace_dir / MANIFEST_FILE, manifest)
        return self._receipt(manifest)

    def read_manifest(self, trace_id: str) -> dict[str, Any]:
        with _MUTATION_LOCK:
            _, manifest = self._load_trace(trace_id)
        return json.loads(json.dumps(manifest))

    def read_request_body(self, trace_id: str) -> bytes:
        trace_dir, manifest = self._load_trace(trace_id)
        return self._read_verified_body(trace_dir / REQUEST_FILE, manifest["request"], field="request")

    def read_response_body(self, trace_id: str) -> bytes | None:
        trace_dir, manifest = self._load_trace(trace_id)
        if not manifest["response_received"]:
            return None
        return self._read_verified_body(trace_dir / RESPONSE_FILE, manifest["response"], field="response")

    def _trace_dir(self, trace_id: str) -> Path:
        validated = _validate_trace_id(trace_id)
        candidate = self.root / validated
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ProviderTraceVaultError("trace path escapes vault root") from exc
        if candidate.is_symlink():
            raise ProviderTraceVaultError("trace path must not be a symbolic link")
        return resolved

    def _load_trace(self, trace_id: str) -> tuple[Path, dict[str, Any]]:
        trace_dir = self._trace_dir(trace_id)
        manifest_path = trace_dir / MANIFEST_FILE
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise ProviderTraceVaultError("trace manifest does not exist")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProviderTraceVaultError("trace manifest is unreadable") from exc
        if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
            raise ProviderTraceVaultError("trace manifest schema is invalid")
        if manifest.get("trace_id") != _validate_trace_id(trace_id):
            raise ProviderTraceVaultError("trace manifest identity does not match its directory")
        if not isinstance(manifest.get("stages"), list):
            raise ProviderTraceVaultError("trace manifest stage history is invalid")
        return trace_dir, manifest

    @staticmethod
    def _read_verified_body(path: Path, identity: Any, *, field: str) -> bytes:
        if not isinstance(identity, Mapping) or path.is_symlink() or not path.is_file():
            raise ProviderTraceVaultError(f"stored {field} body is unavailable")
        body = path.read_bytes()
        if identity.get("byte_count") != len(body) or identity.get("sha256") != _sha256(body):
            raise ProviderTraceVaultError(f"stored {field} body identity does not match its manifest")
        return body

    @staticmethod
    def _receipt(manifest: Mapping[str, Any]) -> ProviderTraceReceipt:
        request = manifest["request"]
        response = manifest.get("response")
        return ProviderTraceReceipt(
            trace_id=str(manifest["trace_id"]),
            request_sha256=str(request["sha256"]),
            request_byte_count=int(request["byte_count"]),
            response_sha256=str(response["sha256"]) if isinstance(response, Mapping) else None,
            response_byte_count=int(response["byte_count"]) if isinstance(response, Mapping) else None,
            response_received=bool(manifest["response_received"]),
        )


__all__ = [
    "ProviderTraceReceipt",
    "ProviderTraceVault",
    "ProviderTraceVaultError",
    "SCHEMA",
]
