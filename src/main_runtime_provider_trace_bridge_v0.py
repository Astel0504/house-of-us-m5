"""Best-effort trace capture around one live main-runtime provider attempt."""

from __future__ import annotations

from copy import deepcopy
import time
from typing import Any, Callable, Mapping

import provider_observability_v0 as provider_observability
import provider_trace_vault_v0 as trace_vault
import house_continuity_v1_2_gate12r_control as gate12r_control


HTTPTransport = Callable[
    [str, Mapping[str, str], bytes, int],
    tuple[int, bytes] | tuple[int, bytes, Mapping[str, Any]],
]
ReasonLabeler = Callable[[BaseException], str]
Normalizer = Callable[[Mapping[str, Any]], tuple[str, str, dict[str, Any]]]
_CAPTURE_ERRORS = (trace_vault.ProviderTraceVaultError, OSError)


class ProviderTraceBridge:
    """Keeps trace persistence failures orthogonal to provider behavior."""

    def __init__(
        self,
        *,
        root: str | None,
        operation_id: str,
        request_id: str | None,
        provider_label: str,
        model_label: str,
        endpoint_family: str,
        reason_labeler: ReasonLabeler,
        policy_house_turn_id: str | None = None,
        policy_purpose: str | None = None,
        causal_linkage: Mapping[str, Any] | None = None,
        request_observability: Mapping[str, Any] | None = None,
        attempt_number: int = 1,
    ) -> None:
        self.operation_id = operation_id
        self.request_id = request_id
        self.provider_label = provider_label
        self.model_label = model_label
        self.endpoint_family = endpoint_family
        self.reason_labeler = reason_labeler
        self.policy_house_turn_id = policy_house_turn_id
        self.policy_purpose = policy_purpose
        self.attempt_number = (
            attempt_number
            if isinstance(attempt_number, int) and not isinstance(attempt_number, bool) and attempt_number >= 1
            else 1
        )
        self.causal_linkage = deepcopy(dict(causal_linkage)) if isinstance(causal_linkage, Mapping) else None
        self.request_observability = (
            deepcopy(dict(request_observability)) if isinstance(request_observability, Mapping) else None
        )
        self.vault: trace_vault.ProviderTraceVault | None = None
        self.receipt: trace_vault.ProviderTraceReceipt | None = None
        self.capture_failed = False
        self.capture_failure_stage: str | None = None
        self.observability_failed = False
        self.observability_failure_stage: str | None = None
        self.observability: dict[str, Any] = {
            "schema_version": provider_observability.TRACE_OBSERVABILITY_SCHEMA_VERSION
        }
        self._request_started_monotonic: float | None = None
        if root is not None:
            try:
                self.vault = trace_vault.ProviderTraceVault(root)
            except _CAPTURE_ERRORS:
                self.capture_failed = True
                self.capture_failure_stage = "vault_init"

    @property
    def response_received(self) -> bool:
        return bool(self.receipt is not None and self.receipt.response_received)

    def begin_request(self, request_body: bytes) -> None:
        """Capture the exact serialized body immediately before transport."""
        self._request_started_monotonic = time.monotonic()
        policy_linkage = (
            {
                "house_turn_id": self.policy_house_turn_id,
                "purpose": self.policy_purpose,
                "provider_operation_id": self.operation_id,
            }
            if self.policy_house_turn_id and self.policy_purpose
            else (
                deepcopy(dict(self.causal_linkage))
                if isinstance(self.causal_linkage, Mapping)
                else None
            )
        )
        # The transport policy consumes the adapter-owned turn and purpose
        # before best-effort trace validation can discard malformed telemetry.
        gate12r_control.enforce_external_call_policy(policy_linkage)
        import house_continuity_v1_2_gate12s_control as gate12s_control

        gate12s_control.enforce_external_call_policy(policy_linkage)
        causal_linkage = None
        diagnostics: list[str] = []
        if self.causal_linkage is not None:
            try:
                causal_linkage = provider_observability.validate_causal_linkage(self.causal_linkage)
            except Exception:
                self.mark_observability_failure("causal_linkage_validation")
                diagnostics.append("causal_linkage_invalid")
        self.causal_linkage = causal_linkage
        request_observability = None
        if self.request_observability is not None:
            try:
                request_observability = provider_observability.validate_request_observability(
                    self.request_observability
                )
                if request_observability is not None:
                    request_observability["request_body_utf8_bytes"] = len(request_body)
                    request_observability = provider_observability.validate_request_observability(
                        request_observability
                    )
            except Exception:
                request_observability = None
                self.mark_observability_failure("request_observability_validation")
                diagnostics.append("request_observability_invalid")
        self._write(
            "request_capture",
            "begin_attempt",
            request_body,
            operation_id=self.operation_id,
            request_id=self.request_id,
            provider_label=self.provider_label,
            model_label=self.model_label,
            endpoint_family=self.endpoint_family,
            attempt_number=self.attempt_number,
            causal_linkage=causal_linkage,
            request_observability=request_observability,
        )
        for diagnostic in diagnostics:
            self._record_observability_diagnostic(diagnostic)
        if request_observability is not None:
            try:
                self.observability = provider_observability.merge_trace_observability(
                    self.observability,
                    {"request": request_observability},
                )
            except ValueError:
                self.observability_failed = True
                self.observability_failure_stage = "request_observability"

    def record_response(
        self,
        response_body: bytes,
        *,
        http_status: int | None,
        response_headers: Mapping[str, Any] | None = None,
    ) -> None:
        """Capture an exact response before any caller-owned parsing or validation."""
        self._write(
            "response_capture",
            "record_response",
            response_body,
            http_status=http_status,
        )
        latency_ms = None
        if self._request_started_monotonic is not None:
            latency_ms = max(0, int((time.monotonic() - self._request_started_monotonic) * 1000))
        try:
            response_observability = provider_observability.build_response_observability(
                response_body,
                http_status=http_status,
                response_headers=response_headers,
                endpoint_family=self.endpoint_family,
                latency_ms=latency_ms,
            )
            self.record_observability({"response": response_observability})
        except Exception:
            self.observability_failed = True
            self.observability_failure_stage = "response_observability"

    def record_transport_error(self, exc: BaseException) -> None:
        self._write(
            "transport",
            "record_transport_error",
            reason_label=self.reason_labeler(exc),
        )

    def stage_callback(self) -> Callable[[str, str, str | None], None]:
        """Return a raw-free callback suitable for adapters with their own stages."""
        return self.record_stage

    def wrap_transport(self, transport: HTTPTransport) -> HTTPTransport:
        def traced_transport(
            url: str,
            headers: Mapping[str, str],
            body: bytes,
            timeout_seconds: int,
        ) -> tuple[int, bytes] | tuple[int, bytes, Mapping[str, Any]]:
            try:
                import house_continuity_v1_2_gate12s_control as gate12s_control

                gate12s_control.validate_final_request_boundary(
                    house_turn_id=self.policy_house_turn_id,
                    purpose=self.policy_purpose,
                    provider_operation_id=self.operation_id,
                    request_body=body,
                )
                self.begin_request(body)
                intercepted = gate12s_control.intercept_final_transport(
                    house_turn_id=self.policy_house_turn_id,
                    purpose=self.policy_purpose,
                    provider_operation_id=self.operation_id,
                    request_body=body,
                )
                result = (
                    intercepted
                    if intercepted is not None
                    else transport(url, headers, body, timeout_seconds)
                )
            except Exception as exc:
                self.record_transport_error(exc)
                raise
            status_code, response_body, safe_headers = provider_observability.unpack_http_transport_result(result)
            self.record_response(
                response_body,
                http_status=status_code,
                response_headers=safe_headers,
            )
            return result

        return traced_transport

    def run_validated_client(self, call: Callable[[], Mapping[str, Any]]) -> Mapping[str, Any]:
        try:
            payload = call()
        except Exception as exc:
            if self.response_received:
                self.record_stage("http_payload_validation", "rejected", self.reason_labeler(exc))
            raise
        if self.response_received:
            self.record_stage("http_payload_validation", "accepted")
        return payload

    def normalize(self, normalizer: Normalizer, payload: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
        try:
            normalized = normalizer(payload)
        except Exception as exc:
            if self.response_received:
                self.record_stage("provider_normalization", "rejected", self.reason_labeler(exc))
            raise
        if self.response_received:
            self.record_stage("provider_normalization", "accepted")
        return normalized

    def record_stage(self, stage: str, outcome: str, reason_label: str | None = None) -> None:
        self._write(
            stage,
            "record_stage",
            stage=stage,
            outcome=outcome,
            reason_label=reason_label,
        )

    def safe_log_fields(self) -> dict[str, Any]:
        if self.capture_failed:
            return {
                "provider_trace_status": "capture_failed",
                "provider_trace_failure_stage": self.capture_failure_stage,
            }
        if self.receipt is not None:
            fields = {
                "provider_trace_status": "captured",
                "provider_trace_observability_state": (
                    "trace_owned" if len(self.observability) > 1 else "unavailable"
                ),
                "provider_trace_causal_linkage_state": (
                    "trace_owned" if self.causal_linkage is not None else "unavailable"
                ),
            }
            if self.observability_failed:
                fields["provider_observability_status"] = "partial"
                fields["provider_observability_failure_stage"] = self.observability_failure_stage
            return fields
        return {}

    def record_observability(self, update: Mapping[str, Any]) -> None:
        """Best-effort raw-free manifest update; never changes provider behavior."""

        try:
            self.observability = provider_observability.merge_trace_observability(
                self.observability,
                update,
            )
        except ValueError:
            self.observability_failed = True
            self.observability_failure_stage = "observability_validation"
            self._record_observability_diagnostic("observability_update_invalid")
            return
        if self.vault is None or self.receipt is None or self.capture_failed:
            return
        try:
            self.receipt = self.vault.record_observability(self.receipt.trace_id, update)
        except _CAPTURE_ERRORS:
            self.observability_failed = True
            self.observability_failure_stage = "observability_persistence"

    def mark_observability_failure(self, stage: str) -> None:
        """Retain one bounded safe failure label without affecting the attempt."""

        self.observability_failed = True
        self.observability_failure_stage = stage

    def _record_observability_diagnostic(self, diagnostic: str) -> None:
        if self.vault is None or self.receipt is None or self.capture_failed:
            return
        try:
            self.receipt = self.vault.record_observability_diagnostic(
                self.receipt.trace_id,
                diagnostic,
            )
        except _CAPTURE_ERRORS:
            self.observability_failed = True
            self.observability_failure_stage = "observability_diagnostic_persistence"

    def _write(self, failure_stage: str, method_name: str, *args: Any, **kwargs: Any) -> None:
        if self.vault is None or self.capture_failed:
            return
        if method_name != "begin_attempt":
            if self.receipt is None:
                return
            args = (self.receipt.trace_id, *args)
        try:
            method = getattr(self.vault, method_name)
            self.receipt = method(*args, **kwargs)
        except _CAPTURE_ERRORS:
            self.capture_failed = True
            self.capture_failure_stage = failure_stage


__all__ = ["ProviderTraceBridge"]
