"""Raw-free cross-gate receipt contracts for Continuity V1.2 local gates."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping

from house_continuity_v1_2_executable_contracts_v0 import canonical_sha256


ACCEPTED_JOINT_RECEIPT_SCHEMA_VERSION = (
    "house_continuity_accepted_joint_receipt_v1"
)
APPLIED_UNIT_COVERAGE_AUTHORITY_SCHEMA_VERSION = (
    "house_continuity_applied_unit_coverage_authority_local_v1"
)
_HASH = re.compile(r"[0-9a-f]{64}")
_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,179}")
_ITEM_ID = re.compile(r"cws_item_[0-9a-f]{32}")
_EVENT_ID = re.compile(r"cws_evt_[0-9a-f]{32}")
_RECEIPT_ID = re.compile(r"cws_jrc_[0-9a-f]{32}")


class CrossGateReceiptError(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _fail(code: str) -> None:
    raise CrossGateReceiptError(code)


def _exact(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(fields):
        _fail("invalid_accepted_joint_receipt_shape")
    return dict(value)


def _match(value: Any, pattern: re.Pattern[str], code: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _fail(code)
    return value


def _timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        _fail("invalid_accepted_joint_timestamp")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail("invalid_accepted_joint_timestamp")
    return value


def validate_accepted_joint_receipt(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "receipt_id",
            "attestation_id",
            "attestation_sha256",
            "astel_evidence_id",
            "astel_event_id",
            "astel_content_sha256",
            "solen_evidence_id",
            "solen_event_id",
            "solen_content_sha256",
            "item_id",
            "expected_revision",
            "scope_sha256",
            "canonical_semantic_sha256",
            "idempotency_identity",
            "committed_at",
            "durably_committed",
            "raw_body_included",
            "receipt_sha256",
        ),
    )
    if raw["schema_version"] != ACCEPTED_JOINT_RECEIPT_SCHEMA_VERSION:
        _fail("invalid_accepted_joint_receipt_schema")
    normalized = {
        "schema_version": ACCEPTED_JOINT_RECEIPT_SCHEMA_VERSION,
        "receipt_id": _match(
            raw["receipt_id"], _RECEIPT_ID, "invalid_joint_receipt_id"
        ),
        "attestation_id": _match(
            raw["attestation_id"], _OPAQUE_ID, "invalid_joint_attestation_id"
        ),
        "attestation_sha256": _match(
            raw["attestation_sha256"], _HASH, "invalid_joint_attestation_hash"
        ),
        "astel_evidence_id": _match(
            raw["astel_evidence_id"], _OPAQUE_ID, "invalid_astel_evidence_id"
        ),
        "astel_event_id": _match(
            raw["astel_event_id"], _EVENT_ID, "invalid_astel_evidence_event"
        ),
        "astel_content_sha256": _match(
            raw["astel_content_sha256"], _HASH, "invalid_astel_content_hash"
        ),
        "solen_evidence_id": _match(
            raw["solen_evidence_id"], _OPAQUE_ID, "invalid_solen_evidence_id"
        ),
        "solen_event_id": _match(
            raw["solen_event_id"], _EVENT_ID, "invalid_solen_evidence_event"
        ),
        "solen_content_sha256": _match(
            raw["solen_content_sha256"], _HASH, "invalid_solen_content_hash"
        ),
        "item_id": _match(raw["item_id"], _ITEM_ID, "invalid_joint_item_id"),
        "expected_revision": raw["expected_revision"],
        "scope_sha256": _match(
            raw["scope_sha256"], _HASH, "invalid_joint_scope_hash"
        ),
        "canonical_semantic_sha256": _match(
            raw["canonical_semantic_sha256"],
            _HASH,
            "invalid_joint_semantic_hash",
        ),
        "idempotency_identity": _match(
            raw["idempotency_identity"],
            _OPAQUE_ID,
            "invalid_joint_idempotency_identity",
        ),
        "committed_at": _timestamp(raw["committed_at"]),
        "durably_committed": raw["durably_committed"],
        "raw_body_included": raw["raw_body_included"],
        "receipt_sha256": _match(
            raw["receipt_sha256"], _HASH, "invalid_joint_receipt_hash"
        ),
    }
    if (
        isinstance(normalized["expected_revision"], bool)
        or not isinstance(normalized["expected_revision"], int)
        or normalized["expected_revision"] < 1
    ):
        _fail("invalid_joint_expected_revision")
    if (
        normalized["astel_evidence_id"] == normalized["solen_evidence_id"]
        or normalized["astel_event_id"] == normalized["solen_event_id"]
    ):
        _fail("nonindependent_joint_receipt_evidence")
    if (
        normalized["astel_content_sha256"]
        != normalized["canonical_semantic_sha256"]
        or normalized["solen_content_sha256"]
        != normalized["canonical_semantic_sha256"]
    ):
        _fail("joint_receipt_semantic_mismatch")
    if (
        normalized["durably_committed"] is not True
        or normalized["raw_body_included"] is not False
    ):
        _fail("joint_receipt_authority_mismatch")
    expected_hash = canonical_sha256(
        {
            key: item
            for key, item in normalized.items()
            if key != "receipt_sha256"
        }
    )
    if normalized["receipt_sha256"] != expected_hash:
        _fail("joint_receipt_sha256_mismatch")
    return normalized


__all__ = [
    "ACCEPTED_JOINT_RECEIPT_SCHEMA_VERSION",
    "APPLIED_UNIT_COVERAGE_AUTHORITY_SCHEMA_VERSION",
    "CrossGateReceiptError",
    "validate_accepted_joint_receipt",
]
