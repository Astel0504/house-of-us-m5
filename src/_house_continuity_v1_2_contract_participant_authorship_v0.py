"""Participant-authorship and joint-attestation contracts for Continuity V1.2."""

from __future__ import annotations

from _house_continuity_v1_2_contract_primitives_v0 import *
from _house_continuity_v1_2_contract_items_events_v0 import (
    ITEM_KINDS,
    RESOLUTION_REASONS,
    SUMMARY_MAX_CHARS,
    validate_item_kind_payload,
)
from _house_continuity_v1_2_contract_capabilities_context_v0 import (
    SEMANTIC_OPERATION_KINDS,
)

ASTEL_COMMAND_SCHEMA_VERSION = "house_continuity_astel_explicit_command_v1"

ASTEL_CONFIRMATION_SCHEMA_VERSION = (
    "house_continuity_astel_confirmation_capability_v1"
)

JOINT_ATTESTATION_SCHEMA_VERSION = (
    "house_continuity_joint_authorship_attestation_v1"
)

def canonical_astel_semantic_command(value: Any) -> dict[str, Any]:
    return {
        key: value[key]
        for key in (
            "operation_kind",
            "item_id",
            "expected_revision",
            "item_kind",
            "scope",
            "summary",
            "kind_payload",
            "semantic_patch",
            "reason_code",
            "successor_item_id",
        )
    }

def validate_astel_explicit_command(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "client_command_id",
            "client_turn_id",
            "room_id",
            "participant_id",
            "confirmation_mode",
            "confirmation_capability",
            "operation_kind",
            "item_id",
            "expected_revision",
            "item_kind",
            "scope",
            "summary",
            "kind_payload",
            "semantic_patch",
            "reason_code",
            "successor_item_id",
            "candidate_content_sha256",
            "idempotency_key",
            "created_at",
        ),
        path="astel_explicit_command",
    )
    if raw["schema_version"] != ASTEL_COMMAND_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported Astel command.")
    if raw["participant_id"] != "astel":
        _error("invalid_astel_participant", "Participant must be Astel.")
    mode = _code(
        raw["confirmation_mode"],
        name="confirmation_mode",
        allowed=("direct_structured_action", "reviewed_candidate_confirmation"),
    )
    operation_kind = _code(
        raw["operation_kind"],
        name="operation_kind",
        allowed=SEMANTIC_OPERATION_KINDS + ("abandon",),
    )
    item_id = _nullable_id(
        raw["item_id"], name="item_id", kind="item_id"
    )
    expected_revision = _integer(
        raw["expected_revision"], name="expected_revision", minimum=0
    )
    item_kind = (
        None
        if raw["item_kind"] is None
        else _code(raw["item_kind"], name="item_kind", allowed=ITEM_KINDS)
    )
    scope = (
        None
        if raw["scope"] is None
        else normalize_scope(raw["scope"], path="astel_explicit_command.scope")
    )
    summary = (
        None
        if raw["summary"] is None
        else _string(raw["summary"], name="summary", maximum=SUMMARY_MAX_CHARS)
    )
    kind_payload = (
        None
        if raw["kind_payload"] is None
        else validate_item_kind_payload(item_kind, raw["kind_payload"])
    )
    if not isinstance(raw["semantic_patch"], Mapping):
        _error("invalid_astel_semantic_patch", "Semantic patch must be an object.")
    _reject_private(raw["semantic_patch"], path="astel_explicit_command.semantic_patch")
    reason_code = (
        None
        if raw["reason_code"] is None
        else _code(
            raw["reason_code"],
            name="reason_code",
            allowed=RESOLUTION_REASONS
            + (
                "explicitly_abandoned",
                "replaced",
                "out_of_scope",
                "no_longer_wanted",
            ),
        )
    )
    successor_item_id = _nullable_id(
        raw["successor_item_id"],
        name="successor_item_id",
        kind="item_id",
    )
    if operation_kind == "create":
        if (
            item_id is not None
            or expected_revision != 0
            or item_kind is None
            or scope is None
            or summary is None
            or kind_payload is None
            or raw["semantic_patch"]
            or reason_code is not None
            or successor_item_id is not None
        ):
            _error("invalid_astel_create", "Astel create shape is exact.")
        if item_kind == "completed_tool_result_ref":
            _error(
                "completed_tool_result_authority_mismatch",
                "Participant commands cannot manufacture tool results.",
            )
        semantic_patch = {}
    elif operation_kind == "revise":
        if (
            item_id is None
            or expected_revision < 1
            or item_kind is None
            or scope is not None
            or summary is not None
            or kind_payload is not None
            or reason_code is not None
            or successor_item_id is not None
            or not raw["semantic_patch"]
            or not set(raw["semantic_patch"]).issubset({"summary", "kind_payload"})
        ):
            _error("invalid_astel_revise", "Astel revise patch is exact.")
        semantic_patch = {}
        if "summary" in raw["semantic_patch"]:
            semantic_patch["summary"] = _string(
                raw["semantic_patch"]["summary"],
                name="patch_summary",
                maximum=SUMMARY_MAX_CHARS,
            )
        if "kind_payload" in raw["semantic_patch"]:
            semantic_patch["kind_payload"] = validate_item_kind_payload(
                item_kind,
                raw["semantic_patch"]["kind_payload"],
                partial=True,
            )
    else:
        if (
            item_id is None
            or expected_revision < 1
            or item_kind is not None
            or scope is not None
            or summary is not None
            or kind_payload is not None
            or raw["semantic_patch"]
        ):
            _error(
                "invalid_astel_lifecycle_command",
                "Astel lifecycle command cannot carry semantic rewrite fields.",
            )
        semantic_patch = {}
        if operation_kind == "resolve":
            if reason_code not in RESOLUTION_REASONS or successor_item_id is not None:
                _error("invalid_astel_resolve", "Resolve requires exact reason.")
        elif operation_kind == "supersede":
            if reason_code is not None or successor_item_id is None:
                _error(
                    "invalid_astel_supersede",
                    "Supersede requires exact successor.",
                )
        elif operation_kind == "abandon":
            if reason_code not in (
                "explicitly_abandoned",
                "replaced",
                "out_of_scope",
                "no_longer_wanted",
            ) or successor_item_id is not None:
                _error("invalid_astel_abandon", "Abandon requires exact reason.")
        elif reason_code is not None or successor_item_id is not None:
            _error(
                "invalid_astel_lifecycle_command",
                "Confirm/reopen carry no reason or successor.",
            )
    semantic = {
        "operation_kind": operation_kind,
        "item_id": item_id,
        "expected_revision": expected_revision,
        "item_kind": item_kind,
        "scope": scope,
        "summary": summary,
        "kind_payload": kind_payload,
        "semantic_patch": semantic_patch,
        "reason_code": reason_code,
        "successor_item_id": successor_item_id,
    }
    candidate_hash = _hash(
        raw["candidate_content_sha256"], name="candidate_content_sha256"
    )
    if canonical_sha256(semantic) != candidate_hash:
        _error(
            "candidate_content_sha256_mismatch",
            "Candidate digest does not cover exact semantic bytes.",
        )
    capability = raw["confirmation_capability"]
    if mode == "direct_structured_action":
        if capability is not None:
            _error(
                "unexpected_confirmation_capability",
                "Direct action has no confirmation capability.",
            )
    elif (
        not isinstance(capability, str)
        or _ASTEL_CONFIRMATION_RE.fullmatch(capability) is None
    ):
        _error(
            "invalid_confirmation_capability",
            "Reviewed confirmation requires a one-use capability.",
        )
    return {
        "schema_version": ASTEL_COMMAND_SCHEMA_VERSION,
        "client_command_id": _id(
            raw["client_command_id"], name="client_command_id"
        ),
        "client_turn_id": _id(raw["client_turn_id"], name="client_turn_id"),
        "room_id": _id(raw["room_id"], name="room_id", kind="room_id"),
        "participant_id": "astel",
        "confirmation_mode": mode,
        "confirmation_capability": capability,
        **semantic,
        "candidate_content_sha256": candidate_hash,
        "idempotency_key": _string(
            raw["idempotency_key"], name="idempotency_key", maximum=160
        ),
        "created_at": _timestamp(raw["created_at"], name="created_at"),
        "authorship_kind": "astel_explicit",
        "author_participants": ["astel"],
    }

def validate_astel_confirmation_capability(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "confirmation_capability_id",
            "creation_seed_sha256",
            "capability_sha256",
            "candidate_content_sha256",
            "canonical_candidate",
            "client_turn_id",
            "room_id",
            "target_item_id",
            "target_revision",
            "create_scope",
            "state",
            "issued_at",
            "expires_at",
            "consumed_at",
            "replay_attempt_count",
        ),
        path="astel_confirmation_capability",
    )
    if raw["schema_version"] != ASTEL_CONFIRMATION_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported confirmation capability.")
    candidate_raw = _exact(
        raw["canonical_candidate"],
        (
            "operation_kind",
            "item_id",
            "expected_revision",
            "item_kind",
            "scope",
            "summary",
            "kind_payload",
            "semantic_patch",
            "reason_code",
            "successor_item_id",
        ),
        path="astel_confirmation_capability.canonical_candidate",
    )
    semantic = canonical_astel_semantic_command(
        validate_astel_explicit_command(
            {
                "schema_version": ASTEL_COMMAND_SCHEMA_VERSION,
                "client_command_id": "reviewed-candidate",
                "client_turn_id": raw["client_turn_id"],
                "room_id": raw["room_id"],
                "participant_id": "astel",
                "confirmation_mode": "direct_structured_action",
                "confirmation_capability": None,
                **candidate_raw,
                "candidate_content_sha256": raw[
                    "candidate_content_sha256"
                ],
                "idempotency_key": "reviewed-candidate-validation",
                "created_at": raw["issued_at"],
            }
        )
    )
    candidate_hash = _hash(
        raw["candidate_content_sha256"], name="candidate_content_sha256"
    )
    if canonical_sha256(semantic) != candidate_hash:
        _error("candidate_binding_mismatch", "Candidate bytes differ.")
    item_id = _nullable_id(
        raw["target_item_id"], name="target_item_id", kind="item_id"
    )
    revision = _integer(raw["target_revision"], name="target_revision")
    create_scope = (
        None
        if raw["create_scope"] is None
        else normalize_scope(raw["create_scope"], path="create_scope")
    )
    if (item_id is None) == (create_scope is None):
        _error(
            "invalid_confirmation_target",
            "Capability binds exactly one existing target or create scope.",
        )
    if item_id is None and revision != 0:
        _error("invalid_confirmation_target", "Create target uses revision zero.")
    if item_id is not None and revision < 1:
        _error("invalid_confirmation_target", "Item target uses positive revision.")
    state = _code(
        raw["state"],
        name="state",
        allowed=("issued", "consumed", "expired", "invalidated"),
    )
    consumed = raw["consumed_at"]
    if state == "consumed":
        consumed = _timestamp(consumed, name="consumed_at")
    elif consumed is not None:
        _error("unexpected_consumed_at", "Only consumed state has consumed_at.")
    issued = _timestamp(raw["issued_at"], name="issued_at")
    expires = _timestamp(raw["expires_at"], name="expires_at")
    if _timestamp_value(expires) <= _timestamp_value(issued):
        _error("invalid_confirmation_expiry", "Expiry must follow issue.")
    if consumed is not None and not (
        _timestamp_value(issued)
        <= _timestamp_value(consumed)
        <= _timestamp_value(expires)
    ):
        _error(
            "invalid_confirmation_consumption_time",
            "Consumption must fall within issuance and expiry.",
        )
    return {
        "schema_version": ASTEL_CONFIRMATION_SCHEMA_VERSION,
        "confirmation_capability_id": _id(
            raw["confirmation_capability_id"],
            name="confirmation_capability_id",
            kind="confirmation_capability_id",
        ),
        "creation_seed_sha256": _hash(
            raw["creation_seed_sha256"], name="creation_seed_sha256"
        ),
        "capability_sha256": _hash(
            raw["capability_sha256"], name="capability_sha256"
        ),
        "candidate_content_sha256": candidate_hash,
        "canonical_candidate": semantic,
        "client_turn_id": _id(
            raw["client_turn_id"], name="client_turn_id"
        ),
        "room_id": _id(raw["room_id"], name="room_id", kind="room_id"),
        "target_item_id": item_id,
        "target_revision": revision,
        "create_scope": create_scope,
        "state": state,
        "issued_at": issued,
        "expires_at": expires,
        "consumed_at": consumed,
        "replay_attempt_count": _integer(
            raw["replay_attempt_count"], name="replay_attempt_count"
        ),
    }

def validate_astel_reviewed_command_against_capability(
    command: Any,
    capability: Any,
) -> dict[str, Any]:
    normalized_command = validate_astel_explicit_command(command)
    normalized_capability = validate_astel_confirmation_capability(capability)
    if normalized_command["confirmation_mode"] != "reviewed_candidate_confirmation":
        _error("review_capability_not_applicable", "Command is not reviewed mode.")
    clear_capability_sha256 = hashlib.sha256(
        normalized_command["confirmation_capability"].encode("ascii")
    ).hexdigest()
    semantic = canonical_astel_semantic_command(normalized_command)
    item_id = semantic["item_id"]
    bindings_match = (
        normalized_capability["state"] == "issued"
        and clear_capability_sha256
        == normalized_capability["capability_sha256"]
        and normalized_command["candidate_content_sha256"]
        == normalized_capability["candidate_content_sha256"]
        and semantic == normalized_capability["canonical_candidate"]
        and normalized_command["client_turn_id"]
        == normalized_capability["client_turn_id"]
        and normalized_command["room_id"] == normalized_capability["room_id"]
        and item_id == normalized_capability["target_item_id"]
        and semantic["expected_revision"]
        == normalized_capability["target_revision"]
        and (
            normalized_capability["create_scope"] == semantic["scope"]
            if item_id is None
            else normalized_capability["create_scope"] is None
        )
    )
    if not bindings_match:
        _error(
            "astel_confirmation_binding_mismatch",
            "Reviewed command differs from its one-use capability.",
        )
    return {
        "schema_version": "house_continuity_validated_astel_confirmation_v1",
        "command": normalized_command,
        "confirmation_capability_id": normalized_capability[
            "confirmation_capability_id"
        ],
        "candidate_content_sha256": normalized_command[
            "candidate_content_sha256"
        ],
    }

def _joint_evidence(value: Any, *, participant: str) -> dict[str, str]:
    raw = _exact(
        value,
        ("evidence_id", "event_id", "participant", "content_sha256"),
        path=f"joint_attestation.{participant}_evidence",
    )
    if raw["participant"] != participant:
        _error(
            "joint_participant_mismatch",
            "Joint evidence participant differs from its lane.",
        )
    return {
        "evidence_id": _id(raw["evidence_id"], name="evidence_id"),
        "event_id": _id(raw["event_id"], name="event_id", kind="event_id"),
        "participant": participant,
        "content_sha256": _hash(
            raw["content_sha256"], name="content_sha256"
        ),
    }

def validate_joint_attestation(value: Any) -> dict[str, Any]:
    raw = _exact(
        value,
        (
            "schema_version",
            "attestation_id",
            "creation_seed_sha256",
            "item_id",
            "expected_revision",
            "canonical_semantic_sha256",
            "scope_sha256",
            "astel_evidence",
            "solen_evidence",
            "idempotency_key",
            "created_at",
        ),
        path="joint_attestation",
    )
    if raw["schema_version"] != JOINT_ATTESTATION_SCHEMA_VERSION:
        _error("invalid_schema_version", "Unsupported joint attestation.")
    semantic_hash = _hash(
        raw["canonical_semantic_sha256"],
        name="canonical_semantic_sha256",
    )
    astel = _joint_evidence(raw["astel_evidence"], participant="astel")
    solen = _joint_evidence(raw["solen_evidence"], participant="solen")
    if (
        astel["evidence_id"] == solen["evidence_id"]
        or astel["event_id"] == solen["event_id"]
    ):
        _error(
            "nonindependent_joint_evidence",
            "Joint authorship requires two independent evidence records.",
        )
    if (
        astel["content_sha256"] != semantic_hash
        or solen["content_sha256"] != semantic_hash
    ):
        _error(
            "joint_semantic_hash_mismatch",
            "Both evidence records bind the same semantic digest.",
        )
    return {
        "schema_version": JOINT_ATTESTATION_SCHEMA_VERSION,
        "attestation_id": _id(
            raw["attestation_id"], name="attestation_id"
        ),
        "creation_seed_sha256": _hash(
            raw["creation_seed_sha256"], name="creation_seed_sha256"
        ),
        "item_id": _id(raw["item_id"], name="item_id", kind="item_id"),
        "expected_revision": _integer(
            raw["expected_revision"], name="expected_revision", minimum=1
        ),
        "canonical_semantic_sha256": semantic_hash,
        "scope_sha256": _hash(raw["scope_sha256"], name="scope_sha256"),
        "astel_evidence": astel,
        "solen_evidence": solen,
        "idempotency_key": _string(
            raw["idempotency_key"], name="idempotency_key", maximum=160
        ),
        "created_at": _timestamp(raw["created_at"], name="created_at"),
        "authorship_kind": "joint_explicit",
        "author_participants": ["astel", "solen"],
    }

__all__ = [
    "ASTEL_COMMAND_SCHEMA_VERSION",
    "ASTEL_CONFIRMATION_SCHEMA_VERSION",
    "JOINT_ATTESTATION_SCHEMA_VERSION",
    "canonical_astel_semantic_command",
    "validate_astel_explicit_command",
    "validate_astel_confirmation_capability",
    "validate_astel_reviewed_command_against_capability",
    "_joint_evidence",
    "validate_joint_attestation",
]
