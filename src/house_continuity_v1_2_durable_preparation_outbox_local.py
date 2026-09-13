"""Gate-5 synthetic durable preparation outbox.

This owner shares the Gate-4 capability SQLite file so capability consumption
and bundle preparation can commit in one local transaction.  It is not
imported by a runtime route and stores no clear capability, response body,
private carrier, transcript, Memory/Vault/self-state body, or tool body.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from house_complete_continuity_unit_v1_facade import exact_unit_binding
from house_continuity_v1_2_capability_terminal_parser_local import (
    PARSE_RESULT_SCHEMA_VERSION,
    STORE_SCHEMA_VERSION as GATE4_STORE_SCHEMA_VERSION,
    HouseContinuityCapabilityRegistryLocal,
)
from house_continuity_v1_2_cross_gate_receipts_v1 import (
    APPLIED_UNIT_COVERAGE_AUTHORITY_SCHEMA_VERSION,
)
from house_continuity_v1_2_executable_contracts_v0 import (
    CAPABILITY_SCHEMA_VERSION,
    INTENT_PROTOCOL_VERSION,
    OUTBOX_SCHEMA_VERSION,
    HouseContinuityV12ContractError,
    canonical_json_bytes,
    canonical_sha256,
    validate_intent_capability,
    validate_outbox_against_capability,
    validate_outbox_bundle,
    validate_outbox_transition,
)
from house_continuity_v1_2_participant_evidence_local import (
    SEMANTIC_CANDIDATE_SCHEMA_VERSION,
    SOLEN_SOURCE_SCHEMA_VERSION,
    SOLEN_SOURCE_SCHEMA_VERSION_V2,
    semantic_candidate_sha256,
    validate_semantic_candidate,
)
from house_continuity_v1_2_local_store_v1 import (
    ATOMIC_BUNDLE_RECEIPT_SCHEMA_VERSION,
    HouseContinuityLocalStoreError,
    HouseContinuityV12LocalStore,
)


GATE5_STORE_SCHEMA_VERSION = (
    "house_continuity_v1_2_durable_preparation_outbox_local_v2"
)
PREPARATION_RECEIPT_SCHEMA_VERSION = (
    "house_continuity_outbox_preparation_receipt_local_v1"
)
APPLIED_RECEIPT_SCHEMA_VERSION = (
    "house_continuity_outbox_applied_receipt_local_v1"
)
PROVIDER_OPERATION_SCHEMA_VERSION = (
    "house_synthetic_provider_operation_completion_local_v1"
)
_ALLOWED_RETRY_CODES = {
    "working_set_unavailable",
    "cas_dependency_unavailable",
    "lease_expired",
}
LEASE_VERSION = "house_continuity_worker_lease_v1"
MAX_LEASE_DURATION_SECONDS = 300
_HEX = set("0123456789abcdef")
CANONICAL_OUTBOX_BASE_IDENTITY_FIELDS = (
    "capability_id",
    "command_bundle_sha256",
)
_CAPABILITY_ID_RE = re.compile(r"cwcap_[0-9a-f]{32}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_OUTBOX_BASE_IDENTITY_RE = re.compile(
    r"outbox:cwcap_[0-9a-f]{32}:[0-9a-f]{64}"
)
WORKING_SET_IDEMPOTENCY_MAX_CHARS = 160
WORKING_SET_IDEMPOTENCY_DERIVATION_VERSION = (
    "house_continuity_working_set_idempotency_v1"
)
WORKING_SET_IDEMPOTENCY_DERIVATION_NAMESPACE = (
    "house_continuity_working_set_operation"
)
WORKING_SET_IDEMPOTENCY_DERIVED_PREFIX = (
    "cwsik:house_continuity_working_set_operation:v1:sha256:"
)
_WORKING_SET_OPERATION_ROLES = {"semantic", "scope_binding", "coverage"}


class DurablePreparationOutboxLocalError(ValueError):
    """Stable body-free Gate-5 failure."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class RetryableApplicationError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        if error_code not in _ALLOWED_RETRY_CODES:
            raise ValueError("unsupported retry code")
        super().__init__(error_code)
        self.error_code = error_code


class AuthoritativeApplicationConflict(RuntimeError):
    def __init__(self, receipt_id: str, receipt_sha256: str) -> None:
        super().__init__("authoritative_conflict")
        self.receipt_id = receipt_id
        self.receipt_sha256 = receipt_sha256


def canonical_outbox_base_identity(
    capability_id: str, command_bundle_sha256: str
) -> str:
    """Build the immutable base identity used by Working-Set operations.

    The identity is exactly ``outbox:<capability_id>:<command_bundle_sha256>``.
    ``capability_id`` and ``command_bundle_sha256`` are durable outbox fields
    established before preparation commits.  The command hash covers the
    command context IDs/hashes, snapshot sequence/hash, scope-binding revision,
    coverage decision, and normalized semantic/binding operations.  The
    capability ID may be opaque at one-time issuance, but replay loads the
    persisted value; neither a fresh random value, lease, timestamp, process
    boot, nor retry counter participates in derivation.
    """
    if (
        not isinstance(capability_id, str)
        or not isinstance(command_bundle_sha256, str)
        or _CAPABILITY_ID_RE.fullmatch(capability_id) is None
        or _SHA256_RE.fullmatch(command_bundle_sha256) is None
    ):
        raise ValueError("outbox base identity inputs are invalid")
    return f"outbox:{capability_id}:{command_bundle_sha256}"


def _validate_working_set_idempotency_inputs(
    outbox_base_identity: str,
    *,
    operation_role: str,
    operation_key: str,
) -> tuple[str, str]:
    if any(
        not isinstance(value, str) or not value
        for value in (outbox_base_identity, operation_role, operation_key)
    ):
        raise ValueError("Working-Set idempotency identity inputs are invalid")
    if _OUTBOX_BASE_IDENTITY_RE.fullmatch(outbox_base_identity) is None:
        raise ValueError("Working-Set outbox base identity is invalid")
    if operation_role not in _WORKING_SET_OPERATION_ROLES:
        raise ValueError("Working-Set operation role is invalid")
    if operation_role == "semantic":
        legacy_suffix = operation_key
    else:
        if operation_key != operation_role:
            raise ValueError("non-semantic operation key is invalid")
        legacy_suffix = operation_role
    return outbox_base_identity, legacy_suffix


def legacy_working_set_idempotency_key(
    outbox_base_identity: str,
    *,
    operation_role: str,
    operation_key: str,
) -> str:
    """Return the exact pre-correction key for durable replay compatibility.

    Existing Working-Set receipts treat this value as an opaque primary key.
    Preserve it byte-for-byte, including a historical semantic operation key
    that happens to use a reserved non-semantic suffix.  New command
    preparation rejects a role collision before it can create such a record.
    """
    base, legacy_suffix = _validate_working_set_idempotency_inputs(
        outbox_base_identity,
        operation_role=operation_role,
        operation_key=operation_key,
    )
    legacy = f"{base}:{legacy_suffix}"
    if len(legacy) > WORKING_SET_IDEMPOTENCY_MAX_CHARS:
        raise ValueError("legacy Working-Set idempotency key exceeds contract")
    return legacy


def derive_working_set_idempotency_key(
    outbox_base_identity: str,
    *,
    operation_role: str,
    operation_key: str,
) -> str:
    """Derive the durable idempotency key for one Working-Set sub-operation.

    The legacy representation is retained when it fits because already
    persisted under-limit Working-Set records and their replay paths use that
    opaque identity.  Once the legacy representation would exceed the shared
    160-character contract, a versioned, namespace-marked, domain-separated
    SHA-256 of the canonical identity is used.  The derived form contains no
    fresh or mutable runtime value.
    """
    base, legacy_suffix = _validate_working_set_idempotency_inputs(
        outbox_base_identity,
        operation_role=operation_role,
        operation_key=operation_key,
    )
    legacy = f"{base}:{legacy_suffix}"
    if len(legacy) <= WORKING_SET_IDEMPOTENCY_MAX_CHARS:
        return legacy
    canonical_identity = {
        "derivation_version": WORKING_SET_IDEMPOTENCY_DERIVATION_VERSION,
        "identity_namespace": WORKING_SET_IDEMPOTENCY_DERIVATION_NAMESPACE,
        "outbox_base_identity": base,
        "operation_role": operation_role,
        "operation_key": operation_key,
    }
    derived = (
        WORKING_SET_IDEMPOTENCY_DERIVED_PREFIX
        + canonical_sha256(canonical_identity)
    )
    if len(derived) > WORKING_SET_IDEMPOTENCY_MAX_CHARS:
        raise ValueError("derived Working-Set idempotency key exceeds contract")
    return derived


class OutboxApplicationAdapter(Protocol):
    def apply_semantic(
        self,
        bundle: Mapping[str, Any],
        operation: Mapping[str, Any],
        *,
        idempotency_identity: str,
    ) -> Mapping[str, Any]: ...

    def apply_scope_binding(
        self,
        bundle: Mapping[str, Any],
        operation: Mapping[str, Any],
        *,
        idempotency_identity: str,
    ) -> Mapping[str, Any]: ...

    def apply_coverage(
        self,
        bundle: Mapping[str, Any],
        *,
        idempotency_identity: str,
    ) -> Mapping[str, Any]: ...


class Gate1AtomicOutboxApplicationAdapter:
    """One-bundle adapter over the accepted Gate-1 append-only store."""

    def __init__(self, store: HouseContinuityV12LocalStore):
        self.store = store

    def apply_bundle_atomic(
        self,
        bundle: Mapping[str, Any],
        durable_context: Mapping[str, Any],
        unit_binding: Mapping[str, Any],
        *,
        committed_at: str,
    ) -> dict[str, Any]:
        operation_contexts = {
            item["operation_key"]: item
            for item in durable_context["operation_contexts"]
        }
        application_input_sha256 = canonical_sha256(
            {
                "bundle_id": bundle["bundle_id"],
                "command_bundle_sha256": bundle[
                    "command_bundle_sha256"
                ],
                "durable_operation_context": durable_context,
                "unit_binding": unit_binding,
            }
        )
        existing_atomic = self.store._connection.execute(
            "SELECT receipt_json FROM atomic_bundle_receipts"
            " WHERE bundle_id=?",
            (bundle["bundle_id"],),
        ).fetchone()
        # Preflight every existing target before any append. Operation N cannot
        # leave operations 1..N-1 committed when its expectation is stale.
        if existing_atomic is None:
            for operation in bundle["normalized_semantic_operations"]:
                if operation["operation_kind"] == "create":
                    continue
                identity = operation_contexts[operation["operation_key"]]
                offered = identity["offered_item"]
                current = self.store.read_item(operation["item_id"])
                if (
                    current is None
                    or current["revision"]
                    != operation["expected_revision"]
                    or current["item_kind"] != offered["item_kind"]
                    or self._scope(current) != offered["scope"]
                    or current["summary"] != offered["summary"]
                    or current["kind_payload"]
                    != offered["kind_payload"]
                    or current["content_sha256"]
                    != offered["content_sha256"]
                    or current["lifecycle_state"]
                    != offered["lifecycle_state"]
                ):
                    self._conflict(
                        bundle, "stale_or_substituted_target"
                    )
        binding_operation = bundle["normalized_scope_binding_operation"]
        if binding_operation is not None and existing_atomic is None:
            current_binding = self.store.read_binding(bundle["room_id"])
            if (
                current_binding is None
                or current_binding["binding_revision"]
                != binding_operation["expected_binding_revision"]
            ):
                self._conflict(bundle, "stale_scope_binding")

        item_event_ids: list[str] = []
        application_receipts: dict[str, dict[str, Any]] = {}
        binding_event_id = None
        try:
            with self.store.outbox_bundle_transaction():
                existing = self.store._connection.execute(
                    "SELECT receipt_json FROM atomic_bundle_receipts"
                    " WHERE bundle_id=?",
                    (bundle["bundle_id"],),
                ).fetchone()
                if existing is None:
                    for operation in bundle[
                        "normalized_semantic_operations"
                    ]:
                        candidate, next_item, event = (
                            self._prepare_item_application(
                                bundle,
                                operation,
                                operation_contexts[
                                    operation["operation_key"]
                                ],
                                committed_at=committed_at,
                            )
                        )
                        self.store.apply_item_event(event, next_item)
                        item_event_ids.append(event["event_id"])
                        application_receipts[
                            "semantic:" + operation["operation_key"]
                        ] = self._application_receipt(
                            bundle,
                            "semantic:" + operation["operation_key"],
                            event["event_id"],
                            candidate,
                        )
                    if binding_operation is not None:
                        binding_event = self._prepare_binding_event(
                            bundle,
                            binding_operation,
                            durable_context["scope_binding_context"],
                            committed_at=committed_at,
                        )
                        self.store.apply_binding_event(binding_event)
                        binding_event_id = binding_event["event_id"]
                        application_receipts["scope_binding"] = (
                            self._application_receipt(
                                bundle,
                                "scope_binding",
                                binding_event_id,
                                None,
                            )
                        )
                    coverage = self._coverage(
                        bundle,
                        unit_binding,
                        item_event_ids=item_event_ids,
                        binding_event_id=binding_event_id,
                        committed_at=committed_at,
                    )
                    self.store.put_unit_coverage(coverage)
                    application_receipts["coverage"] = (
                        self._application_receipt(
                            bundle,
                            "coverage",
                            coverage["coverage_id"],
                            None,
                        )
                    )
                    atomic = self._atomic_receipt(
                        bundle,
                        application_input_sha256,
                        item_event_ids=item_event_ids,
                        binding_event_id=binding_event_id,
                        coverage_id=coverage["coverage_id"],
                        committed_at=committed_at,
                    )
                    self.store.put_atomic_bundle_receipt(atomic)
                else:
                    atomic = json.loads(existing["receipt_json"])
                    if (
                        atomic["application_input_sha256"]
                        != application_input_sha256
                    ):
                        _fail("atomic_bundle_identity_conflict")
                    item_event_ids = list(atomic["item_event_ids"])
                    binding_event_id = atomic["binding_event_id"]
                    for operation, event_id in zip(
                        bundle["normalized_semantic_operations"],
                        item_event_ids,
                        strict=True,
                    ):
                        candidate = self._semantic_candidate(
                            bundle,
                            operation,
                            operation_contexts[
                                operation["operation_key"]
                            ],
                        )
                        application_receipts[
                            "semantic:" + operation["operation_key"]
                        ] = self._application_receipt(
                            bundle,
                            "semantic:" + operation["operation_key"],
                            event_id,
                            candidate,
                        )
                    if binding_event_id is not None:
                        application_receipts["scope_binding"] = (
                            self._application_receipt(
                                bundle,
                                "scope_binding",
                                binding_event_id,
                                None,
                            )
                        )
                    application_receipts["coverage"] = (
                        self._application_receipt(
                            bundle,
                            "coverage",
                            atomic["coverage_id"],
                            None,
                        )
                    )
        except HouseContinuityLocalStoreError as exc:
            if exc.error_code in {
                "stale_expected_revision",
                "stale_binding_revision",
                "event_chain_head_mismatch",
                "binding_chain_head_mismatch",
                "authorized_successor_relationship_required",
            }:
                self._conflict(bundle, exc.error_code)
            raise
        return {
            "atomic_bundle_receipt": atomic,
            "application_receipts": application_receipts,
            "raw_body_included": False,
        }

    @staticmethod
    def _scope(item: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "scope_kind": item["scope_kind"],
            "room_id": item["room_id"],
            "project_id": item["project_id"],
            "thread_id": item["thread_id"],
        }

    def _semantic_candidate(
        self,
        bundle: Mapping[str, Any],
        operation: Mapping[str, Any],
        identity: Mapping[str, Any],
    ) -> dict[str, Any]:
        if operation["operation_kind"] == "create":
            summary = operation["summary"]
            payload = deepcopy(operation["kind_payload"])
            item_id = None
        else:
            offered = identity["offered_item"]
            summary = offered["summary"]
            payload = deepcopy(offered["kind_payload"])
            item_id = operation["item_id"]
            if operation["operation_kind"] == "revise":
                if operation["summary"] is not None:
                    summary = operation["summary"]
                payload.update(operation["kind_payload"])
        return validate_semantic_candidate(
            {
                "schema_version": SEMANTIC_CANDIDATE_SCHEMA_VERSION,
                "item_id": item_id,
                "expected_revision": operation["expected_revision"],
                "item_kind": operation["item_kind"],
                "scope": deepcopy(operation["scope"]),
                "summary": summary,
                "kind_payload": payload,
            }
        )

    def _prepare_item_application(
        self,
        bundle: Mapping[str, Any],
        operation: Mapping[str, Any],
        identity: Mapping[str, Any],
        *,
        committed_at: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        candidate = self._semantic_candidate(
            bundle, operation, identity
        )
        event_id = "cws_evt_" + canonical_sha256(
            {
                "bundle_id": bundle["bundle_id"],
                "operation_key": operation["operation_key"],
                "namespace": "gate5_atomic_item_event_v1",
            }
        )[:32]
        semantic_sha = semantic_candidate_sha256(candidate)
        evidence_ref = {
            "evidence_id": (
                "cws_pev_"
                + canonical_sha256(
                    {
                        "bundle_id": bundle["bundle_id"],
                        "operation_key": operation["operation_key"],
                        "semantic_sha256": semantic_sha,
                    }
                )[:32]
            ),
            "event_id": event_id,
            "participant": "solen",
            "content_sha256": semantic_sha,
        }
        if operation["operation_kind"] == "create":
            item_id = "cws_item_" + canonical_sha256(
                {
                    "bundle_id": bundle["bundle_id"],
                    "operation_key": operation["operation_key"],
                    "namespace": "gate5_atomic_created_item_v1",
                }
            )[:32]
            next_item = self._new_item(
                bundle,
                candidate,
                item_id=item_id,
                event_id=event_id,
                evidence_ref=evidence_ref,
                committed_at=committed_at,
                operation_key=operation["operation_key"],
            )
        else:
            current = self.store.read_item(operation["item_id"])
            if current is None:
                self._conflict(bundle, "missing_target")
            next_item = deepcopy(current)
            next_item.update(
                {
                    "revision": current["revision"] + 1,
                    "base_event_id": event_id,
                    "idempotency_key": derive_working_set_idempotency_key(
                        bundle["idempotency_identity"],
                        operation_role="semantic",
                        operation_key=operation["operation_key"],
                    ),
                    "updated_at": committed_at,
                    "authorship_kind": "solen_explicit",
                    "author_participants": ["solen"],
                    "semantic_authority_code": "participant_authored",
                    "command_owner": (
                        "house_talk_continuity_authorship_intent_v1"
                    ),
                    "authorship_evidence_refs": [evidence_ref],
                    "source_turn_ids": [bundle["client_turn_id"]],
                    "source_room_ids": [bundle["room_id"]],
                    "source_operation_ids": [
                        bundle["provider_operation_id"]
                    ],
                    "source_proposal_ids": [],
                }
            )
            next_item["summary"] = candidate["summary"]
            next_item["kind_payload"] = deepcopy(
                candidate["kind_payload"]
            )
            next_item["content_sha256"] = semantic_sha
            kind = operation["operation_kind"]
            if kind == "confirm":
                self._refresh(next_item, committed_at)
            elif kind == "resolve":
                next_item.update(
                    {
                        "lifecycle_state": "resolved",
                        "resolved_at": committed_at,
                        "resolution_reason_code": operation[
                            "reason_code"
                        ],
                    }
                )
            elif kind == "supersede":
                next_item.update(
                    {
                        "lifecycle_state": "superseded",
                        "superseded_by_item_id": operation[
                            "superseded_by_item_id"
                        ],
                    }
                )
            elif kind == "reopen":
                next_item.update(
                    {
                        "lifecycle_state": "active",
                        "resolved_at": None,
                        "resolution_reason_code": None,
                        "abandoned_at": None,
                        "abandonment_reason_code": None,
                        "reopens_item_id": current["item_id"],
                    }
                )
                self._refresh(next_item, committed_at)
        command_sha = canonical_sha256(
            {
                "command_bundle_sha256": bundle[
                    "command_bundle_sha256"
                ],
                "operation": operation,
                "semantic_sha256": semantic_sha,
            }
        )
        event = self.store.prepare_item_event(
            event_id=event_id,
            event_kind=operation["operation_kind"],
            next_item=next_item,
            expected_revision=operation["expected_revision"],
            actor_kind="solen_explicit",
            actor_ref="house_talk_continuity_authorship_intent_v1",
            idempotency_key=next_item["idempotency_key"],
            command_sha256=command_sha,
            created_at=committed_at,
        )
        return candidate, next_item, event

    def _new_item(
        self,
        bundle: Mapping[str, Any],
        candidate: Mapping[str, Any],
        *,
        item_id: str,
        event_id: str,
        evidence_ref: Mapping[str, Any],
        committed_at: str,
        operation_key: str,
    ) -> dict[str, Any]:
        scope = candidate["scope"]
        expiry = (
            self._shift(committed_at, days=30)
            if candidate["item_kind"]
            in {"temporary_fact", "completed_tool_result_ref"}
            else None
        )
        expiring = expiry is not None
        return {
            "schema_version": "house_continuity_working_set_item_v1_2",
            "item_id": item_id,
            "creation_seed_sha256": canonical_sha256(
                {
                    "item_id": item_id,
                    "bundle_id": bundle["bundle_id"],
                    "namespace": "gate5_atomic_created_item_v1",
                }
            ),
            "scope_kind": scope["scope_kind"],
            "room_id": scope["room_id"],
            "project_id": scope["project_id"],
            "thread_id": scope["thread_id"],
            "item_kind": candidate["item_kind"],
            "lifecycle_state": "active",
            "summary": candidate["summary"],
            "kind_payload": deepcopy(candidate["kind_payload"]),
            "content_sha256": semantic_candidate_sha256(candidate),
            "author_participants": ["solen"],
            "authorship_kind": "solen_explicit",
            "semantic_authority_code": "participant_authored",
            "command_owner": (
                "house_talk_continuity_authorship_intent_v1"
            ),
            "authorship_evidence_refs": [deepcopy(evidence_ref)],
            "derivation_owner": None,
            "derivation_version": None,
            "confidence_millis": 1000,
            "source_turn_ids": [bundle["client_turn_id"]],
            "source_room_ids": [bundle["room_id"]],
            "source_operation_ids": [bundle["provider_operation_id"]],
            "source_proposal_ids": [],
            "exact_anchor_refs": [],
            "base_event_id": event_id,
            "revision": 1,
            "idempotency_key": derive_working_set_idempotency_key(
                bundle["idempotency_identity"],
                operation_role="semantic",
                operation_key=operation_key,
            ),
            "created_at": committed_at,
            "updated_at": committed_at,
            "last_confirmed_at": committed_at,
            "fresh_until": self._shift(
                committed_at, days=3 if expiring else 7
            ),
            "aging_after": self._shift(
                committed_at, days=7 if expiring else 30
            ),
            "dormant_after": self._shift(
                committed_at, days=14 if expiring else 90
            ),
            "expires_at": expiry,
            "freshness_policy_code": candidate["item_kind"] + "_v1_1",
            "resolved_at": None,
            "resolution_reason_code": None,
            "abandoned_at": None,
            "abandonment_reason_code": None,
            "superseded_by_item_id": None,
            "supersedes_item_ids": [],
            "reopens_item_id": None,
            "cleanup_state": "retained",
            "cleanup_eligible_at": None,
            "provider_visible_eligible": True,
            "memory_vault_truth": False,
            "exact_evidence": False,
            "self_state": False,
            "action_permission": False,
            "raw_history_included": False,
        }

    @staticmethod
    def _shift(value: str, *, days: int) -> str:
        shifted = _time(value) + timedelta(days=days)
        return shifted.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    def _refresh(self, item: dict[str, Any], at: str) -> None:
        item.update(
            {
                "last_confirmed_at": at,
                "fresh_until": self._shift(at, days=7),
                "aging_after": self._shift(at, days=30),
                "dormant_after": self._shift(at, days=90),
            }
        )

    def _prepare_binding_event(
        self,
        bundle: Mapping[str, Any],
        operation: Mapping[str, Any],
        context: Mapping[str, Any],
        *,
        committed_at: str,
    ) -> dict[str, Any]:
        current = self.store.read_binding(bundle["room_id"])
        choice = context["offered_choice"]
        target_scope = choice["target_scope"]
        if target_scope is None:
            project_id = None
            thread_id = None
            source = "new_unbound"
            kind = "decline"
        else:
            project_id = target_scope["project_id"]
            thread_id = target_scope["thread_id"]
            source = "explicit_inherit"
            kind = "inherit"
        to_binding = {
            "schema_version": "house_continuity_scope_binding_v1",
            "room_id": bundle["room_id"],
            "project_id": project_id,
            "thread_id": thread_id,
            "predecessor_room_id": choice["predecessor_room_id"],
            "binding_source": source,
            "binding_revision": current["binding_revision"] + 1,
            "idempotency_key": derive_working_set_idempotency_key(
                bundle["idempotency_identity"],
                operation_role="scope_binding",
                operation_key="scope_binding",
            ),
            "created_at": current["created_at"],
            "updated_at": committed_at,
        }
        event_id = "cws_evt_" + canonical_sha256(
            {
                "bundle_id": bundle["bundle_id"],
                "choice_code": operation["choice_code"],
                "namespace": "gate5_atomic_binding_event_v1",
            }
        )[:32]
        return self.store.prepare_binding_event(
            event_id=event_id,
            event_kind=kind,
            room_id=bundle["room_id"],
            from_binding=current,
            to_binding=to_binding,
            expected_binding_revision=operation[
                "expected_binding_revision"
            ],
            actor_kind="solen_explicit",
            actor_ref="house_talk_continuity_authorship_intent_v1",
            idempotency_key=to_binding["idempotency_key"],
            command_sha256=canonical_sha256(
                {
                    "command_bundle_sha256": bundle[
                        "command_bundle_sha256"
                    ],
                    "scope_binding_operation": operation,
                    "scope_binding_context": context,
                }
            ),
            created_at=committed_at,
        )

    @staticmethod
    def _coverage(
        bundle: Mapping[str, Any],
        unit_binding: Mapping[str, Any],
        *,
        item_event_ids: list[str],
        binding_event_id: str | None,
        committed_at: str,
    ) -> dict[str, Any]:
        state = (
            "participant_semantic_coverage"
            if bundle["normalized_semantic_operations"]
            or bundle["normalized_scope_binding_operation"] is not None
            else "solen_no_semantic_delta"
        )
        authority_refs = [
            *item_event_ids,
            *([] if binding_event_id is None else [binding_event_id]),
        ] or [bundle["capability_id"]]
        coverage_id = "cws_cov_" + canonical_sha256(
            {
                "bundle_id": bundle["bundle_id"],
                "complete_unit_id": unit_binding["unit_id"],
                "coverage_state": state,
            }
        )[:32]
        return {
            "schema_version": "house_continuity_unit_coverage_v1",
            "coverage_id": coverage_id,
            "creation_seed_sha256": canonical_sha256(
                {
                    "coverage_id": coverage_id,
                    "bundle_id": bundle["bundle_id"],
                    "namespace": "gate5_atomic_coverage_v1",
                }
            ),
            "room_id": bundle["room_id"],
            "complete_unit_id": unit_binding["unit_id"],
            "complete_unit_sha256": unit_binding[
                "source_payload_sha256"
            ],
            "coverage_state": state,
            "authority_refs": authority_refs,
            "exact_survival_ref": None,
            "coverage_finalized": True,
            "safe_for_source_eviction": True,
            "snapshot_global_event_sequence": bundle[
                "snapshot_global_event_sequence"
            ],
            "created_at": committed_at,
        }

    @staticmethod
    def _application_receipt(
        bundle: Mapping[str, Any],
        key: str,
        receipt_id: str,
        candidate: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        body = {
            "bundle_id": bundle["bundle_id"],
            "receipt_key": key,
            "receipt_id": receipt_id,
            "committed": True,
            "semantic_candidate": candidate,
            "raw_body_included": False,
        }
        return {
            "receipt_id": receipt_id,
            "receipt_sha256": canonical_sha256(body),
            "committed": True,
            "semantic_candidate": deepcopy(candidate),
            "raw_body_included": False,
        }

    @staticmethod
    def _atomic_receipt(
        bundle: Mapping[str, Any],
        application_input_sha256: str,
        *,
        item_event_ids: list[str],
        binding_event_id: str | None,
        coverage_id: str,
        committed_at: str,
    ) -> dict[str, Any]:
        body = {
            "schema_version": ATOMIC_BUNDLE_RECEIPT_SCHEMA_VERSION,
            "bundle_id": bundle["bundle_id"],
            "command_bundle_sha256": bundle[
                "command_bundle_sha256"
            ],
            "application_input_sha256": application_input_sha256,
            "item_event_ids": item_event_ids,
            "binding_event_id": binding_event_id,
            "coverage_id": coverage_id,
            "committed_at": committed_at,
            "committed": True,
            "raw_body_included": False,
        }
        sha = canonical_sha256(body)
        return {
            "receipt_id": "cws_bundle_receipt_" + sha[:32],
            **body,
            "receipt_sha256": sha,
        }

    @staticmethod
    def _conflict(
        bundle: Mapping[str, Any], reason: str
    ) -> None:
        receipt_id = "cws_conflict_" + canonical_sha256(
            {
                "bundle_id": bundle["bundle_id"],
                "command_bundle_sha256": bundle[
                    "command_bundle_sha256"
                ],
                "reason_code": reason,
            }
        )[:32]
        receipt_sha = canonical_sha256(
            {
                "bundle_id": bundle["bundle_id"],
                "receipt_key": "conflict",
                "receipt_id": receipt_id,
                "committed": True,
                "semantic_candidate": None,
                "raw_body_included": False,
            }
        )
        raise AuthoritativeApplicationConflict(
            receipt_id, receipt_sha
        )

def _fail(code: str) -> None:
    raise DurablePreparationOutboxLocalError(code)


def _json(value: Mapping[str, Any]) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _load(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        _fail("stored_gate5_shape_invalid")
    return loaded


def _time(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        _fail("invalid_gate5_timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail("invalid_gate5_timestamp")
    if parsed.tzinfo != timezone.utc:
        _fail("invalid_gate5_timestamp")
    return parsed


def _sha(value: str, *, code: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in _HEX for char in value)
    ):
        _fail(code)
    return value


def _id(value: str, *, prefix: str | None = None, code: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        _fail(code)
    if prefix is not None and (
        not value.startswith(prefix) or len(value) != len(prefix) + 32
    ):
        _fail(code)
    return value


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _receipt_id(kind: str, identity: Mapping[str, Any]) -> str:
    return f"cws_{kind}_{canonical_sha256(identity)[:32]}"


class HouseContinuityDurablePreparationOutboxLocal:
    """Private synthetic outbox with atomic Gate-4 capability consumption."""

    def __init__(
        self,
        root: str | Path,
        *,
        synthetic_only: bool = False,
        protected_shadow_only: bool = False,
    ):
        if synthetic_only is not True and protected_shadow_only is not True:
            _fail("synthetic_only_required")
        if synthetic_only is True and protected_shadow_only is True:
            _fail("one_local_or_protected_shadow_mode_required")
        self.root = Path(root).resolve()
        if not self.root.exists() or not self.root.is_dir():
            _fail("existing_local_root_required")
        self.database_path = (
            self.root / "continuity_capability_terminal_parser_local.sqlite3"
        )
        if not self.database_path.exists():
            _fail("gate4_capability_store_required")
        self._connection = sqlite3.connect(
            str(self.database_path), timeout=0.1, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        if self._connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            self._connection.close()
            _fail("sqlite_foreign_keys_unavailable")
        self._gate5_schema_preexisting = (
            self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table'"
                " AND name='gate5_meta'"
            ).fetchone()
            is not None
        )
        self._create_schema()
        self._verify_store_identity()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "HouseContinuityDurablePreparationOutboxLocal":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS gate5_meta(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provider_operations(
              provider_operation_id TEXT PRIMARY KEY,
              client_turn_id TEXT NOT NULL,
              room_id TEXT NOT NULL,
              terminal_response_sha256 TEXT NOT NULL,
              visible_response_sha256 TEXT NOT NULL,
              visible_state TEXT NOT NULL,
              revision INTEGER NOT NULL,
              record_sha256 TEXT NOT NULL,
              record_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox_bundles(
              bundle_id TEXT PRIMARY KEY,
              capability_id TEXT NOT NULL UNIQUE,
              state TEXT NOT NULL,
              idempotency_identity TEXT NOT NULL UNIQUE,
              command_bundle_sha256 TEXT NOT NULL,
              revision INTEGER NOT NULL,
              record_sha256 TEXT NOT NULL,
              operation_context_bindings_sha256 TEXT NOT NULL,
              operation_context_bindings_json TEXT NOT NULL,
              record_json TEXT NOT NULL,
              FOREIGN KEY(capability_id) REFERENCES capabilities(capability_id)
            );
            CREATE TABLE IF NOT EXISTS preparation_receipts(
              receipt_id TEXT PRIMARY KEY,
              bundle_id TEXT NOT NULL UNIQUE,
              receipt_sha256 TEXT NOT NULL UNIQUE,
              receipt_json TEXT NOT NULL,
              FOREIGN KEY(bundle_id) REFERENCES outbox_bundles(bundle_id)
            );
            CREATE TABLE IF NOT EXISTS application_receipts(
              bundle_id TEXT NOT NULL,
              receipt_key TEXT NOT NULL,
              receipt_id TEXT NOT NULL,
              receipt_sha256 TEXT NOT NULL,
              semantic_candidate_json TEXT,
              receipt_json TEXT NOT NULL,
              PRIMARY KEY(bundle_id,receipt_key),
              UNIQUE(receipt_id),
              FOREIGN KEY(bundle_id) REFERENCES outbox_bundles(bundle_id)
            );
            CREATE TABLE IF NOT EXISTS worker_leases(
              bundle_id TEXT PRIMARY KEY,
              lease_token_sha256 TEXT NOT NULL,
              lease_expires_at TEXT NOT NULL,
              attempt_count INTEGER NOT NULL,
              acquired_bundle_revision INTEGER NOT NULL,
              lease_version TEXT NOT NULL,
              FOREIGN KEY(bundle_id) REFERENCES outbox_bundles(bundle_id)
            );
            CREATE TABLE IF NOT EXISTS applied_receipts(
              receipt_id TEXT PRIMARY KEY,
              bundle_id TEXT NOT NULL UNIQUE,
              receipt_sha256 TEXT NOT NULL UNIQUE,
              receipt_json TEXT NOT NULL,
              FOREIGN KEY(bundle_id) REFERENCES outbox_bundles(bundle_id)
            );
            CREATE TABLE IF NOT EXISTS atomic_working_set_receipts(
              bundle_id TEXT PRIMARY KEY,
              receipt_id TEXT NOT NULL UNIQUE,
              receipt_sha256 TEXT NOT NULL UNIQUE,
              receipt_json TEXT NOT NULL,
              FOREIGN KEY(bundle_id) REFERENCES outbox_bundles(bundle_id)
            );
            """
        )
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            rows = dict(
                self._connection.execute(
                    "SELECT key,value FROM gate5_meta"
                )
            )
            if not rows:
                if self._gate5_schema_preexisting:
                    _fail("gate5_store_metadata_missing")
                self._connection.executemany(
                    "INSERT INTO gate5_meta(key,value) VALUES(?,?)",
                    (
                        ("schema_version", GATE5_STORE_SCHEMA_VERSION),
                        ("store_id", "gate5_" + secrets.token_hex(16)),
                    ),
                )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def _verify_store_identity(self) -> None:
        gate4 = dict(
            self._connection.execute("SELECT key,value FROM store_meta")
        )
        if (
            set(gate4) != {"schema_version", "store_id"}
            or gate4["schema_version"] != GATE4_STORE_SCHEMA_VERSION
            or not gate4["store_id"].startswith("gate4_")
            or len(gate4["store_id"]) != 38
        ):
            _fail("gate4_store_metadata_mismatch")
        gate5 = dict(
            self._connection.execute("SELECT key,value FROM gate5_meta")
        )
        if (
            set(gate5) != {"schema_version", "store_id"}
            or gate5["schema_version"] != GATE5_STORE_SCHEMA_VERSION
            or not gate5["store_id"].startswith("gate5_")
            or len(gate5["store_id"]) != 38
        ):
            _fail("gate5_store_metadata_mismatch")

    def record_provider_operation(
        self,
        *,
        provider_operation_id: str,
        client_turn_id: str,
        room_id: str,
        terminal_response_sha256: str,
        visible_response_sha256: str,
        completed_at: str,
        complete_unit_expectation: Mapping[str, Any],
    ) -> dict[str, Any]:
        record = {
            "schema_version": PROVIDER_OPERATION_SCHEMA_VERSION,
            "provider_operation_id": _id(
                provider_operation_id, code="invalid_provider_operation_id"
            ),
            "client_turn_id": _id(
                client_turn_id, code="invalid_client_turn_id"
            ),
            "room_id": _id(room_id, prefix="cws_room_", code="invalid_room_id"),
            "terminal_response_sha256": _sha(
                terminal_response_sha256,
                code="invalid_terminal_response_sha256",
            ),
            "visible_response_sha256": _sha(
                visible_response_sha256,
                code="invalid_visible_response_sha256",
            ),
            "visible_state": "retained_not_released",
            "completed_at": completed_at,
            "first_preparation_attempt_at": None,
            "last_preparation_error_code": None,
            "visible_released_at": None,
            "complete_unit_binding": None,
            "complete_unit_expectation": deepcopy(
                dict(complete_unit_expectation)
            ),
            "raw_body_included": False,
        }
        record = self._validate_operation(record)
        row = self._connection.execute(
            "SELECT record_json FROM provider_operations"
            " WHERE provider_operation_id=?",
            (provider_operation_id,),
        ).fetchone()
        if row is not None:
            existing = _load(row["record_json"])
            if existing != record:
                _fail("provider_operation_identity_conflict")
            return existing
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                "INSERT INTO provider_operations VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    provider_operation_id,
                    client_turn_id,
                    room_id,
                    terminal_response_sha256,
                    visible_response_sha256,
                    record["visible_state"],
                    1,
                    canonical_sha256(record),
                    _json(record),
                ),
            )
            self._connection.commit()
        except sqlite3.IntegrityError as exc:
            self._connection.rollback()
            raise DurablePreparationOutboxLocalError(
                "provider_operation_identity_conflict"
            ) from exc
        except sqlite3.OperationalError as exc:
            self._connection.rollback()
            self._sqlite_error(exc)
        return record

    def finalize_complete_unit_expectation(
        self,
        provider_operation_id: str,
        *,
        complete_unit_expectation: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Bind delayed Android delivery identities before unit publication."""

        operation = self._operation(provider_operation_id)
        current = operation["complete_unit_expectation"]
        if current.get("expectation_state") == "finalized":
            if dict(current) != dict(complete_unit_expectation):
                _fail("complete_unit_expectation_identity_conflict")
            return deepcopy(operation)
        changed = deepcopy(operation)
        changed["complete_unit_expectation"] = deepcopy(
            dict(complete_unit_expectation)
        )
        changed = self._validate_operation(changed)
        self._replace_operation(changed, previous=operation)
        return changed

    def record_preparation_failure(
        self,
        provider_operation_id: str,
        *,
        at: str,
        error_code: str = "preparation_failed_retryable",
    ) -> dict[str, Any]:
        if error_code != "preparation_failed_retryable":
            _fail("invalid_preparation_error_code")
        operation = self._operation(provider_operation_id)
        if operation["visible_state"] == "delivery_cancelled":
            _fail("operation_delivery_cancelled")
        changed = deepcopy(operation)
        changed["first_preparation_attempt_at"] = (
            changed["first_preparation_attempt_at"] or at
        )
        changed["last_preparation_error_code"] = error_code
        _time(at)
        self._replace_operation(changed, previous=operation)
        return changed

    def record_visible_release(
        self,
        provider_operation_id: str,
        *,
        at: str,
        reconcile_outbox: bool = True,
    ) -> dict[str, Any]:
        operation = self._operation(provider_operation_id)
        _time(at)
        if operation["visible_state"] == "visible_released":
            if operation["visible_released_at"] != at:
                _fail("visible_release_identity_conflict")
        elif operation["visible_state"] != "retained_not_released":
            _fail("visible_release_forbidden")
        else:
            changed = deepcopy(operation)
            changed["visible_state"] = "visible_released"
            changed["visible_released_at"] = at
            self._replace_operation(changed, previous=operation)
            operation = changed
        if reconcile_outbox:
            self.reconcile_visible_release(provider_operation_id, at=at)
        return operation

    def cancel_before_visible(
        self, bundle_id: str, *, at: str
    ) -> dict[str, Any]:
        bundle = self.read_bundle(bundle_id)
        if bundle is None:
            _fail("outbox_bundle_not_found")
        operation = self._operation(bundle["provider_operation_id"])
        if operation["visible_state"] != "retained_not_released":
            _fail("visible_delivery_already_released")
        changed_operation = deepcopy(operation)
        changed_operation["visible_state"] = "delivery_cancelled"
        changed = deepcopy(bundle)
        changed.update(
            {
                "state": "cancelled_before_visible",
                "terminal_code": "cancelled_before_visible",
                "updated_at": at,
            }
        )
        self._transition(
            bundle, changed, event="visible_delivery_permanently_cancelled"
        )
        operation_row = self._connection.execute(
            "SELECT revision,record_sha256,record_json"
            " FROM provider_operations WHERE provider_operation_id=?",
            (operation["provider_operation_id"],),
        ).fetchone()
        bundle_row = self._connection.execute(
            "SELECT revision,record_sha256,record_json"
            " FROM outbox_bundles WHERE bundle_id=?",
            (bundle_id,),
        ).fetchone()
        if (
            operation_row is None
            or bundle_row is None
            or _load(operation_row["record_json"]) != operation
            or _load(bundle_row["record_json"]) != bundle
        ):
            _fail("cancel_before_visible_cas_conflict")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._write_operation(
                changed_operation,
                expected_revision=operation_row["revision"],
                expected_record_sha256=operation_row["record_sha256"],
            )
            self._write_bundle(
                changed,
                expected_revision=bundle_row["revision"],
                expected_record_sha256=bundle_row["record_sha256"],
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return validate_outbox_bundle(changed)

    def prepare(
        self,
        parse_result: Mapping[str, Any],
        *,
        now: str,
        failpoint: str | None = None,
    ) -> dict[str, Any]:
        parsed = self._validated_parse_result(parse_result)
        capability = self._capability(parsed["capability_id"])
        operation = self._operation(capability["provider_operation_id"])
        if self._operation_binding(operation, capability, parsed) is False:
            _fail("preparation_binding_mismatch")
        if failpoint == "before_transaction":
            _fail("simulated_crash_before_preparation")

        command = parsed["validated_command_bundle"]
        intent = command["intent"]
        context = {
            key: command[key]
            for key in (
                "command_context_id",
                "command_context_sha256",
                "snapshot_global_event_sequence",
                "snapshot_global_event_sha256",
                "scope_binding_revision",
            )
        }
        command_hash = canonical_sha256(
            {
                **context,
                "coverage_decision": intent["coverage_decision"],
                "normalized_semantic_operations": intent[
                    "semantic_operations"
                ],
                "normalized_scope_binding_operation": intent[
                    "scope_binding_operation"
                ],
            }
        )
        bundle_id = "cws_out_" + canonical_sha256(
            {
                "capability_id": capability["capability_id"],
                "terminal_response_sha256": parsed["response_sha256"],
                "command_bundle_sha256": command_hash,
                "namespace": OUTBOX_SCHEMA_VERSION,
            }
        )[:32]
        existing = self._bundle_for_capability(capability["capability_id"])
        if existing is not None:
            candidate_identity = (
                bundle_id,
                parsed["response_sha256"],
                parsed["visible_sha256"],
                command_hash,
            )
            existing_identity = (
                existing["bundle_id"],
                existing["terminal_response_sha256"],
                existing["visible_response_sha256"],
                existing["command_bundle_sha256"],
            )
            if candidate_identity != existing_identity:
                _fail("same_capability_different_command")
            return self.preparation_receipt(existing["bundle_id"])
        semantic_operation_keys = {
            operation["operation_key"]
            for operation in intent["semantic_operations"]
        }
        if "coverage" in semantic_operation_keys or (
            intent["scope_binding_operation"] is not None
            and "scope_binding" in semantic_operation_keys
        ):
            _fail("working_set_legacy_operation_key_collision")
        if capability["state"] != "issued":
            _fail("capability_not_issued_for_preparation")

        if operation["visible_state"] == "visible_released":
            if (
                operation["first_preparation_attempt_at"] is None
                or operation["last_preparation_error_code"]
                != "preparation_failed_retryable"
            ):
                _fail("preparation_recovery_precondition_missing")
            state = "visible_released_waiting_unit"
            prepared_at = operation["first_preparation_attempt_at"]
            visible_at = operation["visible_released_at"]
        elif operation["visible_state"] == "retained_not_released":
            state = "prepared_waiting_visible"
            prepared_at = now
            visible_at = None
        else:
            _fail("operation_delivery_cancelled")
        if _time(prepared_at) > _time(now):
            _fail("preparation_time_regression")
        creation_seed = canonical_sha256(
            {
                "bundle_id": bundle_id,
                "capability_id": capability["capability_id"],
                "created_at": prepared_at,
                "namespace": OUTBOX_SCHEMA_VERSION,
            }
        )
        bundle = validate_outbox_bundle(
            {
                "schema_version": OUTBOX_SCHEMA_VERSION,
                "bundle_id": bundle_id,
                "creation_seed_sha256": creation_seed,
                "capability_id": capability["capability_id"],
                "capability_sha256": capability["capability_sha256"],
                "client_turn_id": capability["client_turn_id"],
                "room_id": capability["room_id"],
                "provider_operation_id": capability[
                    "provider_operation_id"
                ],
                "protocol_version": capability["protocol_version"],
                **context,
                "terminal_response_sha256": parsed["response_sha256"],
                "visible_response_sha256": parsed["visible_sha256"],
                "unit_binding_state": "pending_complete_unit",
                "covered_complete_unit_ids": [],
                "covered_complete_unit_sha256s": [],
                "coverage_decision": intent["coverage_decision"],
                "normalized_semantic_operations": intent[
                    "semantic_operations"
                ],
                "normalized_scope_binding_operation": intent[
                    "scope_binding_operation"
                ],
                "command_bundle_sha256": command_hash,
                "idempotency_identity": canonical_outbox_base_identity(
                    capability["capability_id"], command_hash
                ),
                "state": state,
                "application_attempt_count": 0,
                "next_retry_at": None,
                "last_error_code": None,
                "terminal_code": None,
                "working_set_receipt_ids": [],
                "coverage_receipt_ids": [],
                "prepared_at": prepared_at,
                "visible_released_at": visible_at,
                "applied_at": None,
                "updated_at": now,
            }
        )
        consumed = deepcopy(capability)
        consumed.update(
            {
                "state": "prepared_consumed",
                "consumed_at": now,
                "outbox_bundle_id": bundle_id,
                "terminal_response_sha256": parsed["response_sha256"],
            }
        )
        try:
            consumed = validate_intent_capability(consumed)
            validate_outbox_against_capability(bundle, consumed)
        except HouseContinuityV12ContractError as exc:
            raise DurablePreparationOutboxLocalError(
                exc.error_code
            ) from exc
        receipt = self._preparation_receipt(bundle, at=now)
        operation_context_bindings = deepcopy(
            command["gate5_durable_operation_context"]
        )
        operation_context_bindings_sha256 = canonical_sha256(
            operation_context_bindings
        )
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            capability_row = self._connection.execute(
                "SELECT revision,record_sha256,record_json"
                " FROM capabilities WHERE capability_id=?",
                (capability["capability_id"],),
            ).fetchone()
            if (
                capability_row is None
                or _load(capability_row["record_json"]) != capability
                or capability["state"] != "issued"
            ):
                _fail("capability_changed_before_preparation")
            next_capability_revision = capability_row["revision"] + 1
            next_capability_sha = canonical_sha256(consumed)
            transition_body = {
                "capability_id": consumed["capability_id"],
                "capability_revision": next_capability_revision,
                "client_turn_id": consumed["client_turn_id"],
                "room_id": consumed["room_id"],
                "provider_operation_id": consumed["provider_operation_id"],
                "protocol_version": consumed["protocol_version"],
                "terminal_response_sha256": parsed["response_sha256"],
                "result_code": "durable_preparation_committed",
                "created_at": now,
                "raw_body_included": False,
            }
            transition_sha = canonical_sha256(transition_body)
            transition_receipt = {
                "receipt_id": "gate4_receipt_" + transition_sha[:32],
                **transition_body,
                "receipt_sha256": transition_sha,
            }
            self._connection.execute(
                "INSERT INTO outbox_bundles VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    bundle["bundle_id"],
                    bundle["capability_id"],
                    bundle["state"],
                    bundle["idempotency_identity"],
                    bundle["command_bundle_sha256"],
                    1,
                    canonical_sha256(bundle),
                    operation_context_bindings_sha256,
                    json.dumps(
                        operation_context_bindings,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    _json(bundle),
                ),
            )
            self._connection.execute(
                "INSERT INTO preparation_receipts VALUES(?,?,?,?)",
                (
                    receipt["receipt_id"],
                    bundle["bundle_id"],
                    receipt["receipt_sha256"],
                    _json(receipt),
                ),
            )
            self._connection.execute(
                "UPDATE capabilities SET state=?,replay_attempt_count=?,"
                "revision=?,record_sha256=?,record_json=?"
                " WHERE capability_id=? AND state='issued'"
                " AND revision=? AND record_sha256=?",
                (
                    consumed["state"],
                    consumed["replay_attempt_count"],
                    next_capability_revision,
                    next_capability_sha,
                    _json(consumed),
                    consumed["capability_id"],
                    capability_row["revision"],
                    capability_row["record_sha256"],
                ),
            )
            if self._connection.execute("SELECT changes()").fetchone()[0] != 1:
                _fail("capability_changed_before_preparation")
            self._connection.execute(
                "INSERT INTO parser_receipts"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,0)",
                (
                    transition_receipt["receipt_id"],
                    transition_receipt["capability_id"],
                    transition_receipt["capability_revision"],
                    transition_receipt["client_turn_id"],
                    transition_receipt["room_id"],
                    transition_receipt["provider_operation_id"],
                    transition_receipt["protocol_version"],
                    transition_receipt["terminal_response_sha256"],
                    transition_receipt["result_code"],
                    transition_receipt["created_at"],
                    transition_receipt["receipt_sha256"],
                ),
            )
            self._connection.commit()
        except DurablePreparationOutboxLocalError as exc:
            self._connection.rollback()
            if exc.error_code == "capability_changed_before_preparation":
                converged = self._converged_preparation_receipt(bundle)
                if converged is not None:
                    return converged
            raise
        except sqlite3.IntegrityError as exc:
            self._connection.rollback()
            converged = self._converged_preparation_receipt(bundle)
            if converged is not None:
                return converged
            raise DurablePreparationOutboxLocalError(
                "outbox_identity_conflict"
            ) from exc
        except sqlite3.OperationalError as exc:
            self._connection.rollback()
            if "locked" in str(exc).lower():
                converged = self._converged_preparation_receipt(bundle)
                if converged is not None:
                    return converged
            self._sqlite_error(exc)
        if failpoint == "after_commit":
            _fail("simulated_crash_after_preparation_commit")
        return receipt

    def _converged_preparation_receipt(
        self, candidate: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        existing = self._bundle_for_capability(
            candidate["capability_id"]
        )
        if existing is None:
            return None
        identity_fields = (
            "bundle_id",
            "capability_id",
            "terminal_response_sha256",
            "visible_response_sha256",
            "command_bundle_sha256",
            "idempotency_identity",
        )
        if any(
            existing[field] != candidate[field]
            for field in identity_fields
        ):
            _fail("same_capability_different_command")
        return self.preparation_receipt(existing["bundle_id"])

    def preparation_receipt(self, bundle_id: str) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT receipt_json FROM preparation_receipts WHERE bundle_id=?",
            (bundle_id,),
        ).fetchone()
        if row is None:
            _fail("preparation_receipt_not_found")
        return _load(row["receipt_json"])

    def preparation_receipt_for_capability(
        self, capability_id: str
    ) -> dict[str, Any] | None:
        bundle = self._bundle_for_capability(capability_id)
        if bundle is None:
            return None
        return self.preparation_receipt(bundle["bundle_id"])

    def reconcile_visible_release(
        self, provider_operation_id: str, *, at: str
    ) -> dict[str, Any] | None:
        operation = self._operation(provider_operation_id)
        if operation["visible_state"] != "visible_released":
            return None
        row = self._connection.execute(
            "SELECT record_json FROM outbox_bundles"
            " WHERE capability_id=(SELECT capability_id FROM capabilities"
            " WHERE provider_operation_id=?)",
            (provider_operation_id,),
        ).fetchone()
        if row is None:
            return None
        bundle = validate_outbox_bundle(_load(row["record_json"]))
        if bundle["state"] != "prepared_waiting_visible":
            return bundle
        changed = deepcopy(bundle)
        changed.update(
            {
                "state": "visible_released_waiting_unit",
                "visible_released_at": operation["visible_released_at"],
                "updated_at": at,
            }
        )
        self._transition(bundle, changed, event="visible_released")
        self._replace_bundle(changed, previous=bundle)
        return validate_outbox_bundle(changed)

    def publish_complete_unit(
        self,
        provider_operation_id: str,
        facade: Mapping[str, Any],
    ) -> dict[str, Any]:
        binding = exact_unit_binding(dict(facade))
        operation = self._operation(provider_operation_id)
        self._verify_complete_unit_correlation(
            operation, dict(facade), binding
        )
        changed = deepcopy(operation)
        if changed["complete_unit_binding"] not in (None, binding):
            _fail("complete_unit_binding_mismatch")
        changed["complete_unit_binding"] = binding
        self._replace_operation(changed, previous=operation)
        return binding

    def bind_complete_unit(
        self, bundle_id: str, *, now: str
    ) -> dict[str, Any]:
        bundle = self._required_bundle(bundle_id)
        if bundle["state"] == "ready_to_apply":
            return bundle
        if bundle["state"] != "visible_released_waiting_unit":
            _fail("outbox_not_waiting_for_unit")
        operation = self._operation(bundle["provider_operation_id"])
        binding = operation["complete_unit_binding"]
        if binding is None:
            _fail("complete_unit_binding_missing")
        changed = deepcopy(bundle)
        changed.update(
            {
                "state": "ready_to_apply",
                "unit_binding_state": "bound",
                "covered_complete_unit_ids": [binding["unit_id"]],
                "covered_complete_unit_sha256s": [
                    binding["source_payload_sha256"]
                ],
                "updated_at": now,
            }
        )
        self._transition(bundle, changed, event="exact_unit_bound")
        self._replace_bundle(changed, previous=bundle)
        return validate_outbox_bundle(changed)

    def acquire_lease(
        self,
        bundle_id: str,
        *,
        clear_lease_token: str,
        now: str,
        expires_at: str,
    ) -> dict[str, Any]:
        now_time = _time(now)
        expiry_time = _time(expires_at)
        if (
            expiry_time <= now_time
            or expiry_time - now_time
            > timedelta(seconds=MAX_LEASE_DURATION_SECONDS)
        ):
            _fail("invalid_lease_expiry")
        try:
            token_sha = _digest(clear_lease_token.encode("ascii"))
        except (AttributeError, UnicodeEncodeError):
            _fail("invalid_lease_token")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT revision,record_sha256,record_json"
                " FROM outbox_bundles WHERE bundle_id=?",
                (bundle_id,),
            ).fetchone()
            if row is None:
                _fail("outbox_bundle_not_found")
            bundle = validate_outbox_bundle(_load(row["record_json"]))
            lease = self._lease(bundle_id)
            if bundle["state"] == "applying":
                if (
                    lease is not None
                    and lease["lease_token_sha256"] == token_sha
                    and _time(lease["lease_expires_at"]) > now_time
                ):
                    self._connection.commit()
                    return bundle
                if (
                    lease is None
                    or _time(lease["lease_expires_at"]) > now_time
                ):
                    _fail("worker_lease_active")
                retryable = deepcopy(bundle)
                retryable.update(
                    {
                        "state": "retryable_failure",
                        "next_retry_at": now,
                        "last_error_code": "lease_expired",
                        "updated_at": now,
                    }
                )
                self._transition(
                    bundle,
                    retryable,
                    event="infrastructure_failure",
                )
                self._write_bundle(
                    retryable,
                    expected_revision=row["revision"],
                    expected_record_sha256=row["record_sha256"],
                )
                self._connection.execute(
                    "DELETE FROM worker_leases WHERE bundle_id=?",
                    (bundle_id,),
                )
                bundle = retryable
                row = self._connection.execute(
                    "SELECT revision,record_sha256,record_json"
                    " FROM outbox_bundles WHERE bundle_id=?",
                    (bundle_id,),
                ).fetchone()
            if bundle["state"] not in {
                "ready_to_apply",
                "retryable_failure",
            }:
                _fail("outbox_not_leaseable")
            event = (
                "lease"
                if bundle["state"] == "ready_to_apply"
                else "retry"
            )
            changed = deepcopy(bundle)
            changed.update(
                {
                    "state": "applying",
                    "application_attempt_count": (
                        bundle["application_attempt_count"] + 1
                    ),
                    "next_retry_at": None,
                    "last_error_code": None,
                    "updated_at": now,
                }
            )
            self._transition(bundle, changed, event=event)
            self._write_bundle(
                changed,
                expected_revision=row["revision"],
                expected_record_sha256=row["record_sha256"],
            )
            self._connection.execute(
                "INSERT INTO worker_leases VALUES(?,?,?,?,?,?)",
                (
                    bundle_id,
                    token_sha,
                    expires_at,
                    changed["application_attempt_count"],
                    row["revision"] + 1,
                    LEASE_VERSION,
                ),
            )
            self._connection.commit()
        except DurablePreparationOutboxLocalError:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise DurablePreparationOutboxLocalError(
                "worker_lease_identity_conflict"
            ) from exc
        except sqlite3.OperationalError as exc:
            if self._connection.in_transaction:
                self._connection.rollback()
            self._sqlite_error(exc)
        return validate_outbox_bundle(changed)

    def apply(
        self,
        bundle_id: str,
        adapter: OutboxApplicationAdapter,
        *,
        clear_lease_token: str,
        now: str,
        failpoint: str | None = None,
    ) -> dict[str, Any]:
        bundle = self._required_bundle(bundle_id)
        if bundle["state"] in {"applied", "conflict_recorded"}:
            return self.outcome(bundle_id)
        if bundle["state"] != "applying":
            _fail("outbox_not_applying")
        self._verify_lease(bundle_id, clear_lease_token, now=now)
        try:
            if isinstance(adapter, Gate1AtomicOutboxApplicationAdapter):
                operation = self._operation(
                    bundle["provider_operation_id"]
                )
                unit_binding = operation["complete_unit_binding"]
                if unit_binding is None:
                    _fail("complete_unit_binding_missing")
                result = adapter.apply_bundle_atomic(
                    bundle,
                    self._durable_operation_context(bundle_id),
                    unit_binding,
                    committed_at=now,
                )
                self._store_atomic_working_set_receipt(
                    bundle, result["atomic_bundle_receipt"]
                )
                if failpoint in {
                    "after_semantic_commit_before_receipt",
                    "after_working_set_transaction_before_receipts",
                }:
                    _fail("simulated_crash_after_working_set_commit")
                for key, receipt in result[
                    "application_receipts"
                ].items():
                    self._store_application_receipt(
                        bundle,
                        key,
                        receipt,
                        semantic_required=key.startswith("semantic:"),
                    )
            else:
                for operation in bundle["normalized_semantic_operations"]:
                    key = "semantic:" + operation["operation_key"]
                    if self._application_receipt(bundle_id, key) is None:
                        receipt = adapter.apply_semantic(
                            bundle,
                            operation,
                            idempotency_identity=(
                                derive_working_set_idempotency_key(
                                    bundle["idempotency_identity"],
                                    operation_role="semantic",
                                    operation_key=operation["operation_key"],
                                )
                            ),
                        )
                        if failpoint == "after_semantic_commit_before_receipt":
                            _fail("simulated_crash_after_working_set_commit")
                        self._store_application_receipt(
                            bundle, key, receipt, semantic_required=True
                        )
                binding_operation = bundle[
                    "normalized_scope_binding_operation"
                ]
                if binding_operation is not None:
                    key = "scope_binding"
                    if self._application_receipt(bundle_id, key) is None:
                        receipt = adapter.apply_scope_binding(
                            bundle,
                            binding_operation,
                            idempotency_identity=(
                                derive_working_set_idempotency_key(
                                    bundle["idempotency_identity"],
                                    operation_role="scope_binding",
                                    operation_key="scope_binding",
                                )
                            ),
                        )
                        self._store_application_receipt(
                            bundle,
                            key,
                            receipt,
                            semantic_required=False,
                        )
                if self._application_receipt(bundle_id, "coverage") is None:
                    receipt = adapter.apply_coverage(
                        bundle,
                        idempotency_identity=derive_working_set_idempotency_key(
                            bundle["idempotency_identity"],
                            operation_role="coverage",
                            operation_key="coverage",
                        ),
                    )
                    self._store_application_receipt(
                        bundle,
                        "coverage",
                        receipt,
                        semantic_required=False,
                    )
        except AuthoritativeApplicationConflict as exc:
            self._store_application_receipt(
                bundle,
                "conflict",
                {
                    "receipt_id": exc.receipt_id,
                    "receipt_sha256": exc.receipt_sha256,
                    "committed": True,
                    "semantic_candidate": None,
                    "raw_body_included": False,
                },
                semantic_required=False,
            )
            return self._mark_conflict(bundle, exc.receipt_id, at=now)
        except RetryableApplicationError as exc:
            return self._mark_retryable(bundle, exc.error_code, at=now)

        semantic_ids = [
            self._application_receipt(
                bundle_id, "semantic:" + operation["operation_key"]
            )["receipt_id"]
            for operation in bundle["normalized_semantic_operations"]
        ]
        if bundle["normalized_scope_binding_operation"] is not None:
            semantic_ids.append(
                self._application_receipt(
                    bundle_id, "scope_binding"
                )["receipt_id"]
            )
        coverage = self._application_receipt(bundle_id, "coverage")
        if coverage is None:
            _fail("coverage_receipt_missing")
        if failpoint == "after_application_receipts_before_marker":
            _fail("simulated_crash_after_working_set_commit")
        changed = deepcopy(self._required_bundle(bundle_id))
        changed.update(
            {
                "state": "applied",
                "working_set_receipt_ids": semantic_ids,
                "coverage_receipt_ids": [coverage["receipt_id"]],
                "terminal_code": "applied",
                "applied_at": now,
                "updated_at": now,
            }
        )
        self._transition(
            self._required_bundle(bundle_id),
            changed,
            event="all_receipts_committed",
        )
        applied_receipt = self._applied_receipt(changed, at=now)
        bundle_row = self._connection.execute(
            "SELECT revision,record_sha256,record_json"
            " FROM outbox_bundles WHERE bundle_id=?",
            (bundle_id,),
        ).fetchone()
        if (
            bundle_row is None
            or _load(bundle_row["record_json"])
            != self._required_bundle(bundle_id)
        ):
            _fail("outbox_bundle_cas_conflict")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._write_bundle(
                changed,
                expected_revision=bundle_row["revision"],
                expected_record_sha256=bundle_row["record_sha256"],
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO applied_receipts VALUES(?,?,?,?)",
                (
                    applied_receipt["receipt_id"],
                    bundle_id,
                    applied_receipt["receipt_sha256"],
                    _json(applied_receipt),
                ),
            )
            self._connection.execute(
                "DELETE FROM worker_leases WHERE bundle_id=?", (bundle_id,)
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return applied_receipt

    def outcome(self, bundle_id: str) -> dict[str, Any]:
        bundle = self._required_bundle(bundle_id)
        if bundle["state"] == "applied":
            row = self._connection.execute(
                "SELECT receipt_json FROM applied_receipts WHERE bundle_id=?",
                (bundle_id,),
            ).fetchone()
            if row is None:
                _fail("applied_receipt_missing")
            return _load(row["receipt_json"])
        return {
            "schema_version": "house_continuity_outbox_outcome_local_v1",
            "bundle_id": bundle_id,
            "state": bundle["state"],
            "committed_continuity": False,
            "safe_for_source_eviction": False,
            "raw_body_included": False,
        }

    def unit_coverage_applied_source(
        self, bundle_id: str
    ) -> dict[str, Any]:
        """Return body-free proof that this bundle's unit coverage committed."""

        bundle = self._required_bundle(bundle_id)
        if bundle["state"] != "applied":
            _fail("outbox_not_applied")
        if (
            len(bundle["covered_complete_unit_ids"]) != 1
            or len(bundle["covered_complete_unit_sha256s"]) != 1
        ):
            _fail("applied_unit_binding_invalid")
        atomic = self._atomic_working_set_receipt(bundle_id)
        if atomic is None:
            _fail("real_atomic_working_set_receipt_required")
        applied = self.outcome(bundle_id)
        coverage = Gate1AtomicOutboxApplicationAdapter._coverage(
            bundle,
            {
                "unit_id": bundle["covered_complete_unit_ids"][0],
                "source_payload_sha256": (
                    bundle["covered_complete_unit_sha256s"][0]
                ),
            },
            item_event_ids=list(atomic["item_event_ids"]),
            binding_event_id=atomic["binding_event_id"],
            committed_at=atomic["committed_at"],
        )
        if coverage["coverage_id"] != atomic["coverage_id"]:
            _fail("applied_coverage_identity_mismatch")
        decision = (
            "semantic_operations"
            if coverage["coverage_state"] == "participant_semantic_coverage"
            else "no_semantic_delta"
        )
        body = {
            "schema_version": (
                APPLIED_UNIT_COVERAGE_AUTHORITY_SCHEMA_VERSION
            ),
            "coverage_id": coverage["coverage_id"],
            "coverage_record_sha256": canonical_sha256(coverage),
            "complete_unit_id": coverage["complete_unit_id"],
            "complete_unit_sha256": coverage["complete_unit_sha256"],
            "coverage_state": coverage["coverage_state"],
            "coverage_authority_refs": coverage["authority_refs"],
            "coverage_decision": decision,
            "complete_meaningful_delta_attested": True,
            "outbox_bundle_id": bundle_id,
            "command_bundle_sha256": bundle["command_bundle_sha256"],
            "atomic_working_set_receipt_id": atomic["receipt_id"],
            "atomic_working_set_receipt_sha256": atomic["receipt_sha256"],
            "terminal_applied_receipt_id": applied["receipt_id"],
            "terminal_applied_receipt_sha256": applied["receipt_sha256"],
            "applied_at": bundle["applied_at"],
            "raw_body_included": False,
        }
        receipt_sha256 = canonical_sha256(body)
        return {
            **body,
            "receipt_id": "cws_covauth_" + receipt_sha256[:32],
            "receipt_sha256": receipt_sha256,
        }

    def selection_state(self, bundle_id: str) -> dict[str, Any]:
        bundle = self._required_bundle(bundle_id)
        applied = (
            bundle["state"] == "applied"
            and self._atomic_working_set_receipt(bundle_id) is not None
        )
        return {
            "bundle_id": bundle_id,
            "outbox_state": bundle["state"],
            "authoritative_for_selection": applied,
            "continuity_outcome": (
                "applied"
                if applied
                else (
                    "conflict_or_rejected"
                    if bundle["state"]
                    in {"conflict_recorded", "cancelled_before_visible"}
                    else "pending_preparation_or_application"
                )
            ),
            "raw_body_included": False,
        }

    def solen_applied_source(
        self, bundle_id: str, operation_key: str
    ) -> dict[str, Any]:
        bundle = self._required_bundle(bundle_id)
        if bundle["state"] != "applied":
            _fail("outbox_not_applied")
        if self._atomic_working_set_receipt(bundle_id) is None:
            _fail("real_atomic_working_set_receipt_required")
        receipt = self._application_receipt(
            bundle_id, "semantic:" + operation_key
        )
        if receipt is None or receipt["semantic_candidate"] is None:
            _fail("semantic_application_receipt_missing")
        applied = self.outcome(bundle_id)
        operation = next(
            (
                item
                for item in bundle["normalized_semantic_operations"]
                if item["operation_key"] == operation_key
            ),
            None,
        )
        if operation is None:
            _fail("semantic_operation_receipt_unoffered")
        semantic_sha = semantic_candidate_sha256(
            receipt["semantic_candidate"]
        )
        source_event_id = "cws_evt_" + canonical_sha256(
            {
                "bundle_id": bundle_id,
                "operation_key": operation_key,
                "applied_receipt_sha256": applied["receipt_sha256"],
            }
        )[:32]
        return {
            "schema_version": SOLEN_SOURCE_SCHEMA_VERSION_V2,
            "source_event_id": source_event_id,
            "source_kind": "applied_solen_outbox",
            "participant_id": "solen",
            "authorship_kind": "solen_explicit",
            "command_owner": (
                "house_talk_continuity_authorship_intent_v1"
            ),
            "client_turn_id": bundle["client_turn_id"],
            "room_id": bundle["room_id"],
            "provider_operation_id": bundle["provider_operation_id"],
            "outbox_bundle_id": bundle_id,
            "outbox_state": "applied",
            "outbox_applied_receipt_sha256": applied["receipt_sha256"],
            "operation_kind": operation["operation_kind"],
            "reason_code": operation["reason_code"],
            "successor_item_id": operation[
                "superseded_by_item_id"
            ],
            "semantic_candidate_sha256": semantic_sha,
            "application_receipt_id": receipt["receipt_id"],
            "application_receipt_sha256": receipt["receipt_sha256"],
            "terminal_applied_receipt_id": applied["receipt_id"],
            "semantic_candidate": receipt["semantic_candidate"],
            "created_at": bundle["applied_at"],
        }

    def read_bundle(self, bundle_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT record_json FROM outbox_bundles WHERE bundle_id=?",
            (bundle_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            return validate_outbox_bundle(_load(row["record_json"]))
        except HouseContinuityV12ContractError as exc:
            raise DurablePreparationOutboxLocalError(
                exc.error_code
            ) from exc

    def doctor(self) -> dict[str, Any]:
        self._verify_store_identity()
        if self._connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            _fail("gate5_foreign_keys_unavailable")
        if self._connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] != "ok":
            _fail("gate5_sqlite_integrity_failure")
        if list(self._connection.execute("PRAGMA foreign_key_check")):
            _fail("gate5_foreign_key_failure")
        with HouseContinuityCapabilityRegistryLocal(
            self.database_path.parent, synthetic_only=True
        ) as gate4:
            gate4_report = gate4.doctor(require_outbox_links=True)
        bundle_count = 0
        for row in self._connection.execute(
            "SELECT bundle_id,capability_id,state,idempotency_identity,"
            "command_bundle_sha256,revision,record_sha256,"
            "operation_context_bindings_sha256,"
            "operation_context_bindings_json,record_json"
            " FROM outbox_bundles"
        ):
            bundle = validate_outbox_bundle(_load(row["record_json"]))
            if (
                row["bundle_id"] != bundle["bundle_id"]
                or row["capability_id"] != bundle["capability_id"]
                or row["state"] != bundle["state"]
                or row["idempotency_identity"]
                != bundle["idempotency_identity"]
                or row["command_bundle_sha256"]
                != bundle["command_bundle_sha256"]
                or row["revision"] < 1
                or row["record_sha256"] != canonical_sha256(bundle)
            ):
                _fail("outbox_index_json_mismatch")
            try:
                operation_bindings = json.loads(
                    row["operation_context_bindings_json"]
                )
            except json.JSONDecodeError:
                _fail("operation_context_bindings_integrity_failure")
            if (
                not isinstance(operation_bindings, dict)
                or row["operation_context_bindings_sha256"]
                != canonical_sha256(operation_bindings)
                or len(operation_bindings.get("operation_contexts", []))
                != len(bundle["normalized_semantic_operations"])
                or {
                    item.get("operation_key") for item in operation_bindings
                    .get("operation_contexts", [])
                }
                != {
                    item["operation_key"]
                    for item in bundle["normalized_semantic_operations"]
                }
            ):
                _fail("operation_context_bindings_integrity_failure")
            durable_context = self._durable_operation_context(
                bundle["bundle_id"]
            )
            for identity in durable_context["operation_contexts"]:
                expected_identity = canonical_sha256(
                    {
                        key: value
                        for key, value in identity.items()
                        if key != "identity_sha256"
                    }
                )
                if identity.get("identity_sha256") != expected_identity:
                    _fail(
                        "operation_context_bindings_integrity_failure"
                    )
            capability = self._capability(bundle["capability_id"])
            validate_outbox_against_capability(bundle, capability)
            self.preparation_receipt(bundle["bundle_id"])
            if bundle["state"] == "applied":
                self.outcome(bundle["bundle_id"])
            lease_count = self._connection.execute(
                "SELECT COUNT(*) FROM worker_leases WHERE bundle_id=?",
                (bundle["bundle_id"],),
            ).fetchone()[0]
            applied_count = self._connection.execute(
                "SELECT COUNT(*) FROM applied_receipts WHERE bundle_id=?",
                (bundle["bundle_id"],),
            ).fetchone()[0]
            if (
                (bundle["state"] == "applying" and lease_count != 1)
                or (bundle["state"] != "applying" and lease_count != 0)
                or (bundle["state"] == "applied" and applied_count != 1)
                or (bundle["state"] != "applied" and applied_count != 0)
            ):
                _fail("outbox_state_cardinality_failure")
            bundle_count += 1
        for row in self._connection.execute(
            "SELECT provider_operation_id,client_turn_id,room_id,"
            "terminal_response_sha256,visible_response_sha256,visible_state,"
            "revision,record_sha256,record_json FROM provider_operations"
        ):
            operation = self._validate_operation(_load(row["record_json"]))
            if (
                any(
                    row[field] != operation[field]
                    for field in (
                        "provider_operation_id",
                        "client_turn_id",
                        "room_id",
                        "terminal_response_sha256",
                        "visible_response_sha256",
                        "visible_state",
                    )
                )
                or row["revision"] < 1
                or row["record_sha256"] != canonical_sha256(operation)
            ):
                _fail("provider_operation_index_json_mismatch")
        for row in self._connection.execute(
            "SELECT receipt_id,bundle_id,receipt_sha256,receipt_json"
            " FROM preparation_receipts"
        ):
            receipt = _load(row["receipt_json"])
            if (
                row["receipt_id"] != receipt.get("receipt_id")
                or row["bundle_id"] != receipt.get("bundle_id")
                or row["receipt_sha256"] != receipt.get("receipt_sha256")
                or canonical_sha256(
                    {
                        key: value
                        for key, value in receipt.items()
                        if key != "receipt_sha256"
                    }
                )
                != receipt.get("receipt_sha256")
            ):
                _fail("preparation_receipt_integrity_failure")
        for row in self._connection.execute(
            "SELECT bundle_id,receipt_key,receipt_id,receipt_sha256,"
            "semantic_candidate_json,receipt_json"
            " FROM application_receipts"
        ):
            receipt = _load(row["receipt_json"])
            expected = canonical_sha256(
                {
                    "bundle_id": row["bundle_id"],
                    "receipt_key": row["receipt_key"],
                    "receipt_id": receipt.get("receipt_id"),
                    "committed": receipt.get("committed"),
                    "semantic_candidate": receipt.get(
                        "semantic_candidate"
                    ),
                    "raw_body_included": receipt.get(
                        "raw_body_included"
                    ),
                }
            )
            if (
                row["receipt_id"] != receipt.get("receipt_id")
                or row["receipt_sha256"] != receipt.get("receipt_sha256")
                or expected != receipt.get("receipt_sha256")
                or (
                    None
                    if row["semantic_candidate_json"] is None
                    else _load(row["semantic_candidate_json"])
                )
                != receipt.get("semantic_candidate")
            ):
                _fail("application_receipt_integrity_failure")
        for row in self._connection.execute(
            "SELECT receipt_id,bundle_id,receipt_sha256,receipt_json"
            " FROM applied_receipts"
        ):
            receipt = _load(row["receipt_json"])
            if (
                row["receipt_id"] != receipt.get("receipt_id")
                or row["bundle_id"] != receipt.get("bundle_id")
                or row["receipt_sha256"] != receipt.get("receipt_sha256")
                or canonical_sha256(
                    {
                        key: value
                        for key, value in receipt.items()
                        if key != "receipt_sha256"
                    }
                )
                != receipt.get("receipt_sha256")
            ):
                _fail("applied_receipt_integrity_failure")
        atomic_working_set_count = 0
        for row in self._connection.execute(
            "SELECT bundle_id,receipt_id,receipt_sha256,receipt_json"
            " FROM atomic_working_set_receipts"
        ):
            atomic_working_set_count += 1
            receipt = _load(row["receipt_json"])
            body = {
                key: value
                for key, value in receipt.items()
                if key not in {"receipt_id", "receipt_sha256"}
            }
            sha = canonical_sha256(body)
            if (
                row["bundle_id"] != receipt.get("bundle_id")
                or row["receipt_id"] != receipt.get("receipt_id")
                or row["receipt_sha256"]
                != receipt.get("receipt_sha256")
                or receipt.get("receipt_sha256") != sha
                or receipt.get("receipt_id")
                != "cws_bundle_receipt_" + sha[:32]
                or receipt.get("committed") is not True
                or receipt.get("raw_body_included") is not False
            ):
                _fail("atomic_working_set_receipt_integrity_failure")
        for lease in self._connection.execute(
            "SELECT l.*,b.state,b.revision AS bundle_revision,"
            "b.record_json FROM worker_leases l"
            " JOIN outbox_bundles b ON b.bundle_id=l.bundle_id"
        ):
            bundle = validate_outbox_bundle(_load(lease["record_json"]))
            if (
                lease["state"] != "applying"
                or bundle["state"] != "applying"
                or lease["lease_version"] != LEASE_VERSION
                or lease["attempt_count"]
                != bundle["application_attempt_count"]
                or lease["acquired_bundle_revision"]
                != lease["bundle_revision"]
                or _time(lease["lease_expires_at"])
                <= _time(bundle["updated_at"])
                or _time(lease["lease_expires_at"])
                - _time(bundle["updated_at"])
                > timedelta(seconds=MAX_LEASE_DURATION_SECONDS)
            ):
                _fail("worker_lease_integrity_failure")
        for table, columns in (
            ("outbox_bundles", "record_json"),
            ("provider_operations", "record_json"),
            ("preparation_receipts", "receipt_json"),
            ("application_receipts", "receipt_json"),
            ("applied_receipts", "receipt_json"),
            ("atomic_working_set_receipts", "receipt_json"),
        ):
            for row in self._connection.execute(
                f"SELECT {columns} FROM {table}"
            ):
                encoded = row[0]
                lowered = encoded.lower()
                if any(
                    marker in lowered
                    for marker in (
                        '"clear_capability":',
                        '"response_body":',
                        '"private_carrier":',
                        '"memory_body":',
                        '"vault_body":',
                        '"self_state_body":',
                        '"credential":',
                        '"authorization":',
                    )
                ):
                    _fail("raw_or_private_material_detected")
        for suffix in ("", "-wal"):
            candidate = Path(str(self.database_path) + suffix)
            if not candidate.exists():
                continue
            data = candidate.read_bytes()
            if (
                b"<house-continuity-intent>" in data
                or b"<house-memory-intent>" in data
                or re.search(rb"cwc_[A-Za-z0-9_-]{43}", data)
            ):
                _fail("raw_or_private_material_detected")
        return {
            "schema_version": "house_continuity_gate5_doctor_v1",
            "store_id": dict(
                self._connection.execute(
                    "SELECT key,value FROM gate5_meta"
                )
            )["store_id"],
            "bundle_count": bundle_count,
            "atomic_working_set_receipt_count": (
                atomic_working_set_count
            ),
            "fixture_only_applied_bundle_count": (
                self._connection.execute(
                    "SELECT COUNT(*) FROM outbox_bundles b"
                    " WHERE b.state='applied' AND NOT EXISTS"
                    " (SELECT 1 FROM atomic_working_set_receipts a"
                    " WHERE a.bundle_id=b.bundle_id)"
                ).fetchone()[0]
            ),
            "gate4_doctor": gate4_report,
            "foreign_keys_enabled": True,
            "raw_body_detected": False,
        }

    def _validated_parse_result(
        self, value: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            _fail("invalid_parse_result")
        required = {
            "schema_version",
            "response_sha256",
            "visible_bytes",
            "visible_sha256",
            "stripped_private_ranges",
            "continuity_state",
            "memory_disposition",
            "continuity_write_permitted",
            "memory_write_permitted",
            "any_write_permitted",
            "normalized_intent",
            "validated_command_bundle",
            "capability_id",
            "capability_effect",
            "memory_candidate_bytes",
            "second_provider_call_count",
            "raw_body_persisted",
        }
        if set(value) != required:
            _fail("invalid_parse_result_shape")
        if (
            value["schema_version"] != PARSE_RESULT_SCHEMA_VERSION
            or value["continuity_state"] != "accepted_known_capability"
            or value["continuity_write_permitted"] is not True
            or value["capability_effect"]
            != "pending_gate5_durable_preparation"
            or value["second_provider_call_count"] != 0
            or value["raw_body_persisted"] is not False
        ):
            _fail("parse_result_not_preparable")
        if not isinstance(value["visible_bytes"], bytes):
            _fail("invalid_visible_bytes")
        if _digest(value["visible_bytes"]) != value["visible_sha256"]:
            _fail("visible_response_sha256_mismatch")
        _sha(value["response_sha256"], code="invalid_response_sha256")
        if not isinstance(value["validated_command_bundle"], Mapping):
            _fail("validated_command_bundle_required")
        return deepcopy(dict(value))

    def _operation_binding(
        self,
        operation: Mapping[str, Any],
        capability: Mapping[str, Any],
        parsed: Mapping[str, Any],
    ) -> bool:
        command = parsed["validated_command_bundle"]
        return (
            operation["provider_operation_id"]
            == capability["provider_operation_id"]
            and operation["client_turn_id"] == capability["client_turn_id"]
            and operation["room_id"] == capability["room_id"]
            and operation["terminal_response_sha256"]
            == parsed["response_sha256"]
            and operation["visible_response_sha256"]
            == parsed["visible_sha256"]
            and parsed["capability_id"] == capability["capability_id"]
            and command["command_context_id"]
            == capability["command_context_id"]
            and command["command_context_sha256"]
            == capability["command_context_sha256"]
        )

    def _operation(self, operation_id: str) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT record_json FROM provider_operations"
            " WHERE provider_operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            _fail("provider_operation_not_found")
        return self._validate_operation(_load(row["record_json"]))

    def _replace_operation(
        self,
        record: Mapping[str, Any],
        *,
        previous: Mapping[str, Any],
    ) -> None:
        row = self._connection.execute(
            "SELECT revision,record_sha256,record_json"
            " FROM provider_operations WHERE provider_operation_id=?",
            (record["provider_operation_id"],),
        ).fetchone()
        if row is None:
            _fail("provider_operation_not_found")
        if _load(row["record_json"]) != previous:
            _fail("provider_operation_cas_conflict")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._write_operation(
                record,
                expected_revision=row["revision"],
                expected_record_sha256=row["record_sha256"],
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def _write_operation(
        self,
        record: Mapping[str, Any],
        *,
        expected_revision: int,
        expected_record_sha256: str,
    ) -> None:
        record = self._validate_operation(record)
        changed = self._connection.execute(
            "UPDATE provider_operations SET visible_state=?,revision=?,"
            "record_sha256=?,record_json=? WHERE provider_operation_id=?"
            " AND revision=? AND record_sha256=?",
            (
                record["visible_state"],
                expected_revision + 1,
                canonical_sha256(record),
                _json(record),
                record["provider_operation_id"],
                expected_revision,
                expected_record_sha256,
            ),
        ).rowcount
        if changed != 1:
            _fail("provider_operation_cas_conflict")

    def _validate_operation(
        self, value: Mapping[str, Any]
    ) -> dict[str, Any]:
        fields = {
            "schema_version",
            "provider_operation_id",
            "client_turn_id",
            "room_id",
            "terminal_response_sha256",
            "visible_response_sha256",
            "visible_state",
            "completed_at",
            "first_preparation_attempt_at",
            "last_preparation_error_code",
            "visible_released_at",
            "complete_unit_binding",
            "complete_unit_expectation",
            "raw_body_included",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            _fail("invalid_provider_operation_shape")
        if (
            value["schema_version"] != PROVIDER_OPERATION_SCHEMA_VERSION
            or value["raw_body_included"] is not False
        ):
            _fail("invalid_provider_operation_authority")
        state = value["visible_state"]
        if state not in {
            "retained_not_released",
            "visible_released",
            "delivery_cancelled",
        }:
            _fail("invalid_provider_operation_state")
        completed = _time(value["completed_at"])
        first_attempt = (
            None
            if value["first_preparation_attempt_at"] is None
            else _time(value["first_preparation_attempt_at"])
        )
        visible = (
            None
            if value["visible_released_at"] is None
            else _time(value["visible_released_at"])
        )
        if first_attempt is not None and first_attempt < completed:
            _fail("provider_operation_time_regression")
        if visible is not None and visible < completed:
            _fail("provider_operation_time_regression")
        if (state == "visible_released") != (visible is not None):
            _fail("invalid_visible_release_state")
        error = value["last_preparation_error_code"]
        if (error is not None) != (first_attempt is not None) or error not in {
            None,
            "preparation_failed_retryable",
        }:
            _fail("invalid_preparation_failure_state")
        binding = value["complete_unit_binding"]
        if binding is not None:
            expected_binding_fields = {
                "schema_version",
                "unit_id",
                "unit_kind",
                "producer_class",
                "source_payload_sha256",
                "source_start_id",
                "source_end_id",
                "operation_id",
                "complete",
                "raw_body_included",
            }
            if (
                not isinstance(binding, Mapping)
                or set(binding) != expected_binding_fields
                or binding["schema_version"]
                != "house_complete_continuity_unit_binding_v1"
                or binding["complete"] is not True
                or binding["raw_body_included"] is not False
            ):
                _fail("invalid_complete_unit_binding")
            _sha(
                binding["source_payload_sha256"],
                code="invalid_complete_unit_binding",
            )
        expectation = value["complete_unit_expectation"]
        expected_fields = {
            "expectation_state",
            "client_turn_id",
            "room_id",
            "permitted_unit_kinds",
            "expected_source_start_id",
            "expected_source_end_id",
            "expected_astel_message_id",
            "expected_solen_message_ids",
            "expected_solen_visible_sha256",
            "expected_provider_operation_id",
            "expectation_sha256",
            "raw_body_included",
        }
        if not isinstance(expectation, Mapping) or set(expectation) != expected_fields:
            _fail("invalid_complete_unit_expectation")
        expectation_body = {
            key: deepcopy(expectation[key])
            for key in expected_fields
            if key != "expectation_sha256"
        }
        expectation_state = expectation["expectation_state"]
        if (
            expectation_state not in {"pending_android_sync", "finalized"}
            or expectation["client_turn_id"] != value["client_turn_id"]
            or expectation["room_id"] != value["room_id"]
            or not isinstance(expectation["permitted_unit_kinds"], list)
            or not expectation["permitted_unit_kinds"]
            or len(set(expectation["permitted_unit_kinds"]))
            != len(expectation["permitted_unit_kinds"])
            or any(
                kind not in {"visible_exchange", "provider_agent_operation"}
                for kind in expectation["permitted_unit_kinds"]
            )
            or not isinstance(expectation["expected_solen_message_ids"], list)
            or len(set(expectation["expected_solen_message_ids"]))
            != len(expectation["expected_solen_message_ids"])
            or expectation["raw_body_included"] is not False
            or expectation["expectation_sha256"]
            != canonical_sha256(expectation_body)
        ):
            _fail("invalid_complete_unit_expectation")
        if expectation_state == "pending_android_sync":
            if (
                expectation["expected_source_start_id"]
                != expectation["expected_astel_message_id"]
                or expectation["expected_source_end_id"] is not None
                or expectation["expected_solen_message_ids"] != []
                or expectation["expected_solen_visible_sha256"] is None
                or expectation["expected_provider_operation_id"] is not None
            ):
                _fail("invalid_pending_complete_unit_expectation")
        elif (
            expectation["expected_source_end_id"] is None
            or not expectation["expected_solen_message_ids"]
            or expectation["expected_solen_visible_sha256"] is None
        ):
            _fail("invalid_final_complete_unit_expectation")
        for field in (
            "expected_source_start_id",
            "expected_astel_message_id",
        ):
            _id(expectation[field], code="invalid_complete_unit_expectation")
        if expectation["expected_source_end_id"] is not None:
            _id(
                expectation["expected_source_end_id"],
                code="invalid_complete_unit_expectation",
            )
        for message_id in expectation["expected_solen_message_ids"]:
            _id(message_id, code="invalid_complete_unit_expectation")
        if expectation["expected_solen_visible_sha256"] is not None:
            _sha(
                expectation["expected_solen_visible_sha256"],
                code="invalid_complete_unit_expectation",
            )
        expected_operation_id = expectation[
            "expected_provider_operation_id"
        ]
        if expected_operation_id is not None:
            _id(
                expected_operation_id,
                code="invalid_complete_unit_expectation",
            )
        return deepcopy(dict(value))

    def _verify_complete_unit_correlation(
        self,
        operation: Mapping[str, Any],
        facade: Mapping[str, Any],
        binding: Mapping[str, Any],
    ) -> None:
        expectation = operation["complete_unit_expectation"]
        if expectation.get("expectation_state") != "finalized":
            _fail("complete_unit_expectation_not_finalized")
        messages = facade.get("messages")
        if not isinstance(messages, list) or len(messages) < 2:
            _fail("complete_unit_operation_correlation_mismatch")
        astel = messages[0]
        solen = messages[1:]
        solen_visible_projection = [
            message.get("text") for message in solen
        ]
        if (
            binding["unit_kind"]
            not in expectation["permitted_unit_kinds"]
            or binding["source_start_id"]
            != expectation["expected_source_start_id"]
            or binding["source_end_id"]
            != expectation["expected_source_end_id"]
            or astel.get("message_id")
            != expectation["expected_astel_message_id"]
            or [message.get("message_id") for message in solen]
            != expectation["expected_solen_message_ids"]
            or canonical_sha256(solen_visible_projection)
            != expectation["expected_solen_visible_sha256"]
            or binding["operation_id"]
            != expectation["expected_provider_operation_id"]
        ):
            _fail("complete_unit_operation_correlation_mismatch")

    def _capability(
        self, capability_id: str, *, in_transaction: bool = False
    ) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT record_json FROM capabilities WHERE capability_id=?",
            (capability_id,),
        ).fetchone()
        if row is None:
            _fail("capability_not_found")
        try:
            return validate_intent_capability(_load(row["record_json"]))
        except HouseContinuityV12ContractError as exc:
            raise DurablePreparationOutboxLocalError(
                exc.error_code
            ) from exc

    def _bundle_for_capability(
        self, capability_id: str
    ) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT record_json FROM outbox_bundles WHERE capability_id=?",
            (capability_id,),
        ).fetchone()
        return (
            None
            if row is None
            else validate_outbox_bundle(_load(row["record_json"]))
        )

    def _required_bundle(self, bundle_id: str) -> dict[str, Any]:
        bundle = self.read_bundle(bundle_id)
        if bundle is None:
            _fail("outbox_bundle_not_found")
        return bundle

    def _replace_bundle(
        self,
        record: Mapping[str, Any],
        *,
        previous: Mapping[str, Any],
    ) -> None:
        normalized = validate_outbox_bundle(record)
        row = self._connection.execute(
            "SELECT revision,record_sha256,record_json"
            " FROM outbox_bundles WHERE bundle_id=?",
            (normalized["bundle_id"],),
        ).fetchone()
        if row is None:
            _fail("outbox_bundle_not_found")
        if _load(row["record_json"]) != previous:
            _fail("outbox_bundle_cas_conflict")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._write_bundle(
                normalized,
                expected_revision=row["revision"],
                expected_record_sha256=row["record_sha256"],
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def _write_bundle(
        self,
        record: Mapping[str, Any],
        *,
        expected_revision: int,
        expected_record_sha256: str,
    ) -> None:
        changed = self._connection.execute(
            "UPDATE outbox_bundles SET state=?,revision=?,record_sha256=?,"
            "record_json=? WHERE bundle_id=? AND revision=?"
            " AND record_sha256=?",
            (
                record["state"],
                expected_revision + 1,
                canonical_sha256(record),
                _json(record),
                record["bundle_id"],
                expected_revision,
                expected_record_sha256,
            ),
        ).rowcount
        if changed != 1:
            _fail("outbox_bundle_cas_conflict")

    def _transition(
        self,
        previous: Mapping[str, Any] | None,
        candidate: Mapping[str, Any],
        *,
        event: str,
    ) -> None:
        try:
            validate_outbox_transition(previous, candidate, event=event)
        except HouseContinuityV12ContractError as exc:
            raise DurablePreparationOutboxLocalError(
                exc.error_code
            ) from exc

    def _preparation_receipt(
        self, bundle: Mapping[str, Any], *, at: str
    ) -> dict[str, Any]:
        receipt = {
            "schema_version": PREPARATION_RECEIPT_SCHEMA_VERSION,
            "receipt_id": _receipt_id(
                "prep",
                {
                    "bundle_id": bundle["bundle_id"],
                    "command_bundle_sha256": bundle["command_bundle_sha256"],
                },
            ),
            "bundle_id": bundle["bundle_id"],
            "capability_id": bundle["capability_id"],
            "terminal_response_sha256": bundle[
                "terminal_response_sha256"
            ],
            "command_bundle_sha256": bundle["command_bundle_sha256"],
            "prepared_state": bundle["state"],
            "created_at": at,
            "raw_body_included": False,
            "receipt_sha256": "",
        }
        receipt["receipt_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in receipt.items()
                if key != "receipt_sha256"
            }
        )
        return receipt

    def _store_application_receipt(
        self,
        bundle: Mapping[str, Any],
        key: str,
        value: Mapping[str, Any],
        *,
        semantic_required: bool,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping) or set(value) != {
            "receipt_id",
            "receipt_sha256",
            "committed",
            "semantic_candidate",
            "raw_body_included",
        }:
            _fail("invalid_application_receipt_shape")
        if value["committed"] is not True or value["raw_body_included"] is not False:
            _fail("application_receipt_not_committed")
        receipt_id = _id(value["receipt_id"], code="invalid_application_receipt_id")
        receipt_sha = _sha(
            value["receipt_sha256"], code="invalid_application_receipt_sha256"
        )
        candidate = value["semantic_candidate"]
        if semantic_required:
            candidate = validate_semantic_candidate(candidate)
            self._verify_semantic_receipt_candidate(bundle, key, candidate)
        elif candidate is not None:
            _fail("unexpected_semantic_candidate")
        expected_receipt_sha = canonical_sha256(
            {
                "bundle_id": bundle["bundle_id"],
                "receipt_key": key,
                "receipt_id": receipt_id,
                "committed": True,
                "semantic_candidate": candidate,
                "raw_body_included": False,
            }
        )
        if receipt_sha != expected_receipt_sha:
            _fail("application_receipt_sha256_mismatch")
        stored = {
            "receipt_id": receipt_id,
            "receipt_sha256": receipt_sha,
            "committed": True,
            "semantic_candidate": candidate,
            "raw_body_included": False,
        }
        existing = self._application_receipt(bundle["bundle_id"], key)
        if existing is not None:
            if existing != stored:
                _fail("application_receipt_identity_conflict")
            return existing
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                "INSERT INTO application_receipts VALUES(?,?,?,?,?,?)",
                (
                    bundle["bundle_id"],
                    key,
                    receipt_id,
                    receipt_sha,
                    None if candidate is None else _json(candidate),
                    _json(stored),
                ),
            )
            self._connection.commit()
        except sqlite3.IntegrityError as exc:
            self._connection.rollback()
            raise DurablePreparationOutboxLocalError(
                "application_receipt_identity_conflict"
            ) from exc
        return stored

    def _store_atomic_working_set_receipt(
        self,
        bundle: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        required = {
            "receipt_id",
            "schema_version",
            "bundle_id",
            "command_bundle_sha256",
            "application_input_sha256",
            "item_event_ids",
            "binding_event_id",
            "coverage_id",
            "committed_at",
            "committed",
            "raw_body_included",
            "receipt_sha256",
        }
        if not isinstance(receipt, Mapping) or set(receipt) != required:
            _fail("invalid_atomic_working_set_receipt")
        normalized = deepcopy(dict(receipt))
        body = {
            key: value
            for key, value in normalized.items()
            if key not in {"receipt_id", "receipt_sha256"}
        }
        sha = canonical_sha256(body)
        if (
            normalized["schema_version"]
            != ATOMIC_BUNDLE_RECEIPT_SCHEMA_VERSION
            or normalized["bundle_id"] != bundle["bundle_id"]
            or normalized["command_bundle_sha256"]
            != bundle["command_bundle_sha256"]
            or normalized["receipt_sha256"] != sha
            or normalized["receipt_id"]
            != "cws_bundle_receipt_" + sha[:32]
            or normalized["committed"] is not True
            or normalized["raw_body_included"] is not False
        ):
            _fail("invalid_atomic_working_set_receipt")
        existing = self._atomic_working_set_receipt(bundle["bundle_id"])
        if existing is not None:
            if existing != normalized:
                _fail("atomic_working_set_receipt_identity_conflict")
            return existing
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                "INSERT INTO atomic_working_set_receipts VALUES(?,?,?,?)",
                (
                    bundle["bundle_id"],
                    normalized["receipt_id"],
                    normalized["receipt_sha256"],
                    _json(normalized),
                ),
            )
            self._connection.commit()
        except sqlite3.IntegrityError as exc:
            self._connection.rollback()
            raise DurablePreparationOutboxLocalError(
                "atomic_working_set_receipt_identity_conflict"
            ) from exc
        return normalized

    def _atomic_working_set_receipt(
        self, bundle_id: str
    ) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT receipt_json FROM atomic_working_set_receipts"
            " WHERE bundle_id=?",
            (bundle_id,),
        ).fetchone()
        return None if row is None else _load(row["receipt_json"])

    def _verify_semantic_receipt_candidate(
        self,
        bundle: Mapping[str, Any],
        key: str,
        candidate: Mapping[str, Any],
    ) -> None:
        operation_key = key.removeprefix("semantic:")
        operation = next(
            (
                item
                for item in bundle["normalized_semantic_operations"]
                if item["operation_key"] == operation_key
            ),
            None,
        )
        if operation is None:
            _fail("semantic_operation_receipt_unoffered")
        durable_context = self._durable_operation_context(
            bundle["bundle_id"]
        )
        identity = next(
            (
                item
                for item in durable_context["operation_contexts"]
                if item["operation_key"] == operation_key
            ),
            None,
        )
        if (
            identity is None
            or identity["operation_kind"] != operation["operation_kind"]
            or identity["operation_sha256"]
            != canonical_sha256(operation)
        ):
            _fail("semantic_operation_context_binding_mismatch")
        if (
            candidate["item_id"] != operation["item_id"]
            or candidate["expected_revision"]
            != operation["expected_revision"]
            or candidate["item_kind"] != operation["item_kind"]
            or candidate["scope"] != operation["scope"]
        ):
            _fail("semantic_application_candidate_binding_mismatch")
        if operation["operation_kind"] == "create":
            if (
                candidate["summary"] != operation["summary"]
                or candidate["kind_payload"] != operation["kind_payload"]
            ):
                _fail("semantic_application_candidate_binding_mismatch")
            return
        offered = identity["offered_item"]
        if offered is None:
            _fail("semantic_operation_context_binding_mismatch")
        expected_summary = offered["summary"]
        expected_payload = deepcopy(offered["kind_payload"])
        if operation["operation_kind"] == "revise":
            if operation["summary"] is not None:
                expected_summary = operation["summary"]
            expected_payload.update(operation["kind_payload"])
        if (
            candidate["summary"] != expected_summary
            or candidate["kind_payload"] != expected_payload
        ):
            _fail("semantic_application_candidate_binding_mismatch")
        expected_content_sha = canonical_sha256(
            {
                "item_kind": candidate["item_kind"],
                "scope": candidate["scope"],
                "summary": expected_summary,
                "kind_payload": expected_payload,
            }
        )
        if operation["operation_kind"] in {
            "confirm",
            "resolve",
            "supersede",
            "reopen",
        } and expected_content_sha != offered["content_sha256"]:
            _fail("preserved_semantic_content_mismatch")
        if operation["operation_kind"] == "supersede":
            successor = identity["offered_successor_item"]
            if successor is None:
                _fail("semantic_application_candidate_binding_mismatch")
            expected_relationship = canonical_sha256(
                {
                    "item_id": offered["item_id"],
                    "successor_item_id": successor["item_id"],
                    "item_kind": offered["item_kind"],
                    "scope": offered["scope"],
                }
            )
            context_binding = next(
                item
                for item in self._durable_operation_bindings(
                    bundle["bundle_id"]
                )
                if item["operation_key"] == operation_key
            )
            if (
                successor["item_id"]
                != operation["superseded_by_item_id"]
                or context_binding["successor_relationship_sha256"]
                != expected_relationship
            ):
                _fail("semantic_application_candidate_binding_mismatch")

    def _durable_operation_context(
        self, bundle_id: str
    ) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT operation_context_bindings_sha256,"
            "operation_context_bindings_json FROM outbox_bundles"
            " WHERE bundle_id=?",
            (bundle_id,),
        ).fetchone()
        if row is None:
            _fail("outbox_bundle_not_found")
        try:
            context = json.loads(row["operation_context_bindings_json"])
        except json.JSONDecodeError:
            _fail("operation_context_bindings_integrity_failure")
        if (
            not isinstance(context, dict)
            or row["operation_context_bindings_sha256"]
            != canonical_sha256(context)
            or context.get("raw_body_included") is not False
            or context.get("context_sha256")
            != canonical_sha256(
                {
                    key: value
                    for key, value in context.items()
                    if key != "context_sha256"
                }
            )
        ):
            _fail("operation_context_bindings_integrity_failure")
        return context

    def _durable_operation_bindings(
        self, bundle_id: str
    ) -> list[dict[str, Any]]:
        context = self._durable_operation_context(bundle_id)
        return [
            {
                "operation_key": item["operation_key"],
                "successor_relationship_sha256": (
                    None
                    if item["operation_kind"] != "supersede"
                    else canonical_sha256(
                        {
                            "item_id": item["offered_item"]["item_id"],
                            "successor_item_id": item[
                                "offered_successor_item"
                            ]["item_id"],
                            "item_kind": item["offered_item"]["item_kind"],
                            "scope": item["offered_item"]["scope"],
                        }
                    )
                ),
            }
            for item in context["operation_contexts"]
        ]

    def _application_receipt(
        self, bundle_id: str, key: str
    ) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT receipt_json FROM application_receipts"
            " WHERE bundle_id=? AND receipt_key=?",
            (bundle_id, key),
        ).fetchone()
        return None if row is None else _load(row["receipt_json"])

    def _lease(self, bundle_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM worker_leases WHERE bundle_id=?", (bundle_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def _verify_lease(
        self, bundle_id: str, clear_token: str, *, now: str
    ) -> None:
        lease = self._lease(bundle_id)
        if lease is None:
            _fail("worker_lease_missing")
        try:
            token_sha = _digest(clear_token.encode("ascii"))
        except (AttributeError, UnicodeEncodeError):
            _fail("invalid_lease_token")
        if (
            token_sha != lease["lease_token_sha256"]
            or _time(lease["lease_expires_at"]) <= _time(now)
            or lease["lease_version"] != LEASE_VERSION
        ):
            _fail("worker_lease_invalid_or_expired")
        bundle_row = self._connection.execute(
            "SELECT revision FROM outbox_bundles WHERE bundle_id=?",
            (bundle_id,),
        ).fetchone()
        if (
            bundle_row is None
            or bundle_row["revision"]
            != lease["acquired_bundle_revision"]
        ):
            _fail("worker_lease_bundle_revision_mismatch")

    def _mark_retryable(
        self, bundle: Mapping[str, Any], code: str, *, at: str
    ) -> dict[str, Any]:
        if code not in _ALLOWED_RETRY_CODES:
            _fail("unsupported_retry_code")
        previous = self._required_bundle(bundle["bundle_id"])
        changed = deepcopy(previous)
        changed.update(
            {
                "state": "retryable_failure",
                "next_retry_at": at,
                "last_error_code": code,
                "updated_at": at,
            }
        )
        self._transition(
            previous,
            changed,
            event="infrastructure_failure",
        )
        row = self._connection.execute(
            "SELECT revision,record_sha256 FROM outbox_bundles"
            " WHERE bundle_id=?",
            (bundle["bundle_id"],),
        ).fetchone()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._write_bundle(
                changed,
                expected_revision=row["revision"],
                expected_record_sha256=row["record_sha256"],
            )
            self._connection.execute(
                "DELETE FROM worker_leases WHERE bundle_id=?",
                (bundle["bundle_id"],),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return self.outcome(bundle["bundle_id"])

    def _mark_conflict(
        self, bundle: Mapping[str, Any], receipt_id: str, *, at: str
    ) -> dict[str, Any]:
        receipt_id = _id(receipt_id, code="invalid_conflict_receipt_id")
        previous = self._required_bundle(bundle["bundle_id"])
        changed = deepcopy(previous)
        changed.update(
            {
                "state": "conflict_recorded",
                "working_set_receipt_ids": [receipt_id],
                "terminal_code": "authoritative_conflict",
                "updated_at": at,
            }
        )
        self._transition(
            previous,
            changed,
            event="authoritative_conflict_receipt",
        )
        row = self._connection.execute(
            "SELECT revision,record_sha256 FROM outbox_bundles"
            " WHERE bundle_id=?",
            (bundle["bundle_id"],),
        ).fetchone()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._write_bundle(
                changed,
                expected_revision=row["revision"],
                expected_record_sha256=row["record_sha256"],
            )
            self._connection.execute(
                "DELETE FROM worker_leases WHERE bundle_id=?",
                (bundle["bundle_id"],),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return self.outcome(bundle["bundle_id"])

    def _applied_receipt(
        self, bundle: Mapping[str, Any], *, at: str
    ) -> dict[str, Any]:
        receipt = {
            "schema_version": APPLIED_RECEIPT_SCHEMA_VERSION,
            "receipt_id": _receipt_id(
                "applied",
                {
                    "bundle_id": bundle["bundle_id"],
                    "working_set_receipt_ids": bundle[
                        "working_set_receipt_ids"
                    ],
                    "coverage_receipt_ids": bundle[
                        "coverage_receipt_ids"
                    ],
                },
            ),
            "bundle_id": bundle["bundle_id"],
            "capability_id": bundle["capability_id"],
            "command_bundle_sha256": bundle["command_bundle_sha256"],
            "working_set_receipt_ids": bundle["working_set_receipt_ids"],
            "coverage_receipt_ids": bundle["coverage_receipt_ids"],
            "applied_at": at,
            "raw_body_included": False,
            "receipt_sha256": "",
        }
        receipt["receipt_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in receipt.items()
                if key != "receipt_sha256"
            }
        )
        return receipt

    @staticmethod
    def _sqlite_error(exc: sqlite3.OperationalError) -> None:
        if "locked" in str(exc).lower():
            raise DurablePreparationOutboxLocalError(
                "sqlite_write_locked"
            ) from exc
        raise DurablePreparationOutboxLocalError(
            "sqlite_write_failure"
        ) from exc


__all__ = [
    "APPLIED_RECEIPT_SCHEMA_VERSION",
    "APPLIED_UNIT_COVERAGE_AUTHORITY_SCHEMA_VERSION",
    "AuthoritativeApplicationConflict",
    "CANONICAL_OUTBOX_BASE_IDENTITY_FIELDS",
    "DurablePreparationOutboxLocalError",
    "GATE5_STORE_SCHEMA_VERSION",
    "HouseContinuityDurablePreparationOutboxLocal",
    "OutboxApplicationAdapter",
    "PREPARATION_RECEIPT_SCHEMA_VERSION",
    "PROVIDER_OPERATION_SCHEMA_VERSION",
    "RetryableApplicationError",
    "WORKING_SET_IDEMPOTENCY_DERIVATION_NAMESPACE",
    "WORKING_SET_IDEMPOTENCY_DERIVATION_VERSION",
    "WORKING_SET_IDEMPOTENCY_DERIVED_PREFIX",
    "WORKING_SET_IDEMPOTENCY_MAX_CHARS",
    "canonical_outbox_base_identity",
    "derive_working_set_idempotency_key",
    "legacy_working_set_idempotency_key",
]
