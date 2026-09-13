"""Literal approved-design fixtures for House Continuity V1.2 Gate 0.

This module is synthetic-only. It constructs exact V1/V1.1/V1.2 contract
objects and their independent event-chain identities without importing any
runtime, provider, persistence, Memory, or self-state owner.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any, Mapping

from house_continuity_v1_2_executable_contracts_v0 import (
    COMPLETE_UNIT_SCHEMA_VERSION,
    CREATION_SEED_SCHEMA_VERSION,
    EXACT_ANCHOR_SCHEMA_VERSION,
    SCOPE_BINDING_EVENT_SCHEMA_VERSION,
    SCOPE_BINDING_SCHEMA_VERSION,
    WORKING_SET_EVENT_SCHEMA_VERSION,
    WORKING_SET_ITEM_SCHEMA_VERSION,
    canonical_sha256,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


ROOM_ID = "cws_room_" + ("a" * 32)
PREDECESSOR_ROOM_ID = "cws_room_" + ("b" * 32)
PROJECT_ID = "cws_prj_" + ("a" * 32)
THREAD_ID = "cws_thr_" + ("a" * 32)
ITEM_ID = "cws_item_" + ("a" * 32)
SECOND_ITEM_ID = "cws_item_" + ("c" * 32)
SUCCESSOR_ITEM_ID = "cws_item_" + ("b" * 32)
EVENT_1_ID = "cws_evt_" + ("1" * 32)
BINDING_EVENT_1_ID = "cws_evt_" + ("2" * 32)
EVENT_2_ID = "cws_evt_" + ("3" * 32)
BINDING_EVENT_2_ID = "cws_evt_" + ("4" * 32)
SECOND_ITEM_EVENT_ID = "cws_evt_" + ("5" * 32)
ANCHOR_ID = "cws_anchor_" + ("a" * 32)
TIMESTAMP_0 = "2026-07-28T00:00:00.000Z"
TIMESTAMP_1 = "2026-07-28T00:00:01.000Z"
TIMESTAMP_2 = "2026-07-28T00:00:02.000Z"
TIMESTAMP_3 = "2026-07-28T00:00:03.000Z"

ROOM_SCOPE_WITH_LINEAGE = {
    "scope_kind": "room",
    "room_id": ROOM_ID,
    "project_id": PROJECT_ID,
    "thread_id": THREAD_ID,
}
PROJECT_SCOPE = {
    "scope_kind": "project",
    "room_id": None,
    "project_id": PROJECT_ID,
    "thread_id": THREAD_ID,
}
GLOBAL_SCOPE = {
    "scope_kind": "global",
    "room_id": None,
    "project_id": None,
    "thread_id": None,
}

ITEM_KIND_PAYLOADS = {
    "active_topic": {
        "topic_state": "current",
        "linked_item_ids": [],
    },
    "active_task": {
        "task_state": "in_progress",
        "linked_item_ids": [],
        "completion_evidence_refs": [],
    },
    "question": {
        "question_owner": "astel",
        "answer_state": "unanswered",
        "linked_item_ids": [],
    },
    "commitment": {
        "committed_by": "solen",
        "commitment_state": "pending",
        "linked_item_ids": [],
    },
    "decision": {
        "decision_state": "provisional",
        "decision_scope": "project",
        "linked_item_ids": [],
    },
    "temporary_fact": {
        "fact_state": "observed",
        "source_class": "current_room",
        "linked_item_ids": [],
    },
    "emotional_thread": {
        "thread_state": "open",
        "expressed_by": "astel",
        "linked_item_ids": [],
    },
    "pending_review": {
        "review_kind": "parallel_conflict",
        "conflicting_item_ids": [],
        "conflicting_event_ids": [],
        "linked_item_ids": [],
    },
    "completed_tool_result_ref": {
        "task_item_id": ITEM_ID,
        "operation_ref": "operation-ref-0001",
        "operation_state": "completed",
        "result_summary": "The synthetic Gate-0 operation completed.",
        "result_ref_sha256": _sha("synthetic-tool-result"),
    },
}

CREATION_SEED = {
    "schema_version": CREATION_SEED_SCHEMA_VERSION,
    "entity_kind": "item",
    "entity_id": ITEM_ID,
    "creation_seed_sha256": _sha("working-set-item-creation-seed"),
    "created_at": TIMESTAMP_0,
}

SCOPE_BINDING_1 = {
    "schema_version": SCOPE_BINDING_SCHEMA_VERSION,
    "room_id": ROOM_ID,
    "project_id": PROJECT_ID,
    "thread_id": None,
    "predecessor_room_id": PREDECESSOR_ROOM_ID,
    "binding_source": "explicit_inherit",
    "binding_revision": 1,
    "idempotency_key": "binding-command-0001",
    "created_at": TIMESTAMP_0,
    "updated_at": TIMESTAMP_0,
}
SCOPE_BINDING_2 = {
    **SCOPE_BINDING_1,
    "thread_id": THREAD_ID,
    "binding_source": "reviewed_rebind",
    "binding_revision": 2,
    "idempotency_key": "binding-command-0002",
    "updated_at": TIMESTAMP_3,
}
SCOPE_BINDING = SCOPE_BINDING_2


_ITEM_SEMANTIC = {
    "item_kind": "active_task",
    "scope": PROJECT_SCOPE,
    "summary": "Prove literal Gate-0 design conformance.",
    "kind_payload": ITEM_KIND_PAYLOADS["active_task"],
}
_ITEM_CONTENT_SHA256 = canonical_sha256(_ITEM_SEMANTIC)


def _event_payload_hash(value: Mapping[str, Any]) -> str:
    chain_fields = {
        "event_payload_sha256",
        "global_event_sequence",
        "prior_global_event_sha256",
        "global_event_sha256",
        "item_event_sequence",
        "prior_item_event_sha256",
        "item_event_sha256",
        "binding_event_sequence",
        "prior_binding_event_sha256",
        "binding_event_sha256",
    }
    return canonical_sha256(
        {key: item for key, item in value.items() if key not in chain_fields}
    )


def _global_hash(value: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "global_event_sequence": value["global_event_sequence"],
            "prior_global_event_sha256": value[
                "prior_global_event_sha256"
            ],
            "event_id": value["event_id"],
            "event_payload_sha256": value["event_payload_sha256"],
        }
    )


def _item_hash(value: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "item_id": value["item_id"],
            "item_event_sequence": value["item_event_sequence"],
            "prior_item_event_sha256": value["prior_item_event_sha256"],
            "event_id": value["event_id"],
            "event_payload_sha256": value["event_payload_sha256"],
        }
    )


def _binding_hash(value: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "room_id": value["room_id"],
            "binding_event_sequence": value["binding_event_sequence"],
            "prior_binding_event_sha256": value[
                "prior_binding_event_sha256"
            ],
            "event_id": value["event_id"],
            "event_payload_sha256": value["event_payload_sha256"],
        }
    )


def _item_event(
    *,
    event_id: str,
    global_sequence: int,
    prior_global: str | None,
    item_sequence: int,
    prior_item: str | None,
    event_kind: str,
    from_lifecycle: str | None,
    to_lifecycle: str,
    expected_revision: int,
    patch: dict[str, Any],
    created_at: str,
    item_id: str = ITEM_ID,
) -> dict[str, Any]:
    value = {
        "schema_version": WORKING_SET_EVENT_SCHEMA_VERSION,
        "event_id": event_id,
        "creation_seed_sha256": _sha(f"seed-{event_id}"),
        "event_payload_sha256": "",
        "global_event_sequence": global_sequence,
        "prior_global_event_sha256": prior_global,
        "global_event_sha256": "",
        "item_id": item_id,
        "item_event_sequence": item_sequence,
        "prior_item_event_sha256": prior_item,
        "item_event_sha256": "",
        "event_kind": event_kind,
        "from_lifecycle_state": from_lifecycle,
        "to_lifecycle_state": to_lifecycle,
        "expected_revision": expected_revision,
        "new_revision": expected_revision + 1,
        "patch": patch,
        "actor_kind": "solen_explicit",
        "actor_ref": "house_talk_continuity_authorship_intent_v1",
        "idempotency_key": f"item-event-{item_sequence}",
        "command_sha256": _sha(f"item-command-{item_sequence}"),
        "source_turn_ids": [f"client-turn-{item_sequence}"],
        "source_room_ids": [ROOM_ID],
        "source_operation_ids": [f"provider-operation-{item_sequence}"],
        "source_proposal_ids": [],
        "created_at": created_at,
    }
    value["event_payload_sha256"] = _event_payload_hash(value)
    value["global_event_sha256"] = _global_hash(value)
    value["item_event_sha256"] = _item_hash(value)
    return value


def _binding_event(
    *,
    event_id: str,
    global_sequence: int,
    prior_global: str,
    binding_sequence: int,
    prior_binding: str | None,
    event_kind: str,
    expected_revision: int,
    from_binding: dict[str, Any] | None,
    to_binding: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    value = {
        "schema_version": SCOPE_BINDING_EVENT_SCHEMA_VERSION,
        "event_id": event_id,
        "creation_seed_sha256": _sha(f"seed-{event_id}"),
        "event_payload_sha256": "",
        "global_event_sequence": global_sequence,
        "prior_global_event_sha256": prior_global,
        "global_event_sha256": "",
        "room_id": ROOM_ID,
        "binding_event_sequence": binding_sequence,
        "prior_binding_event_sha256": prior_binding,
        "binding_event_sha256": "",
        "event_kind": event_kind,
        "expected_binding_revision": expected_revision,
        "new_binding_revision": expected_revision + 1,
        "from_binding": from_binding,
        "to_binding": to_binding,
        "actor_kind": "astel_explicit",
        "actor_ref": "house_continuity_astel_explicit_command_v1",
        "idempotency_key": f"binding-event-{binding_sequence}",
        "command_sha256": _sha(f"binding-command-{binding_sequence}"),
        "source_turn_ids": [f"client-binding-turn-{binding_sequence}"],
        "source_room_ids": [ROOM_ID],
        "source_operation_ids": [],
        "created_at": created_at,
    }
    value["event_payload_sha256"] = _event_payload_hash(value)
    value["global_event_sha256"] = _global_hash(value)
    value["binding_event_sha256"] = _binding_hash(value)
    return value


WORKING_SET_EVENT_1 = _item_event(
    event_id=EVENT_1_ID,
    global_sequence=1,
    prior_global=None,
    item_sequence=1,
    prior_item=None,
    event_kind="create",
    from_lifecycle=None,
    to_lifecycle="active",
    expected_revision=0,
    patch=_ITEM_SEMANTIC,
    created_at=TIMESTAMP_0,
)
SCOPE_BINDING_EVENT_1 = _binding_event(
    event_id=BINDING_EVENT_1_ID,
    global_sequence=2,
    prior_global=WORKING_SET_EVENT_1["global_event_sha256"],
    binding_sequence=1,
    prior_binding=None,
    event_kind="inherit",
    expected_revision=0,
    from_binding=None,
    to_binding=SCOPE_BINDING_1,
    created_at=TIMESTAMP_1,
)
WORKING_SET_EVENT_2 = _item_event(
    event_id=EVENT_2_ID,
    global_sequence=3,
    prior_global=SCOPE_BINDING_EVENT_1["global_event_sha256"],
    item_sequence=2,
    prior_item=WORKING_SET_EVENT_1["item_event_sha256"],
    event_kind="confirm",
    from_lifecycle="active",
    to_lifecycle="active",
    expected_revision=1,
    patch={},
    created_at=TIMESTAMP_2,
)
SCOPE_BINDING_EVENT_2 = _binding_event(
    event_id=BINDING_EVENT_2_ID,
    global_sequence=4,
    prior_global=WORKING_SET_EVENT_2["global_event_sha256"],
    binding_sequence=2,
    prior_binding=SCOPE_BINDING_EVENT_1["binding_event_sha256"],
    event_kind="rebind",
    expected_revision=1,
    from_binding=SCOPE_BINDING_1,
    to_binding=SCOPE_BINDING_2,
    created_at=TIMESTAMP_3,
)
SECOND_ITEM_EVENT_1 = _item_event(
    event_id=SECOND_ITEM_EVENT_ID,
    global_sequence=5,
    prior_global=SCOPE_BINDING_EVENT_2["global_event_sha256"],
    item_sequence=1,
    prior_item=None,
    event_kind="create",
    from_lifecycle=None,
    to_lifecycle="active",
    expected_revision=0,
    patch={
        "item_kind": "question",
        "scope": PROJECT_SCOPE,
        "summary": "Independently prove the second per-item chain.",
        "kind_payload": ITEM_KIND_PAYLOADS["question"],
    },
    created_at="2026-07-28T00:00:04.000Z",
    item_id=SECOND_ITEM_ID,
)

WORKING_SET_ITEM = {
    "schema_version": WORKING_SET_ITEM_SCHEMA_VERSION,
    "item_id": ITEM_ID,
    "creation_seed_sha256": CREATION_SEED["creation_seed_sha256"],
    "scope_kind": PROJECT_SCOPE["scope_kind"],
    "room_id": PROJECT_SCOPE["room_id"],
    "project_id": PROJECT_SCOPE["project_id"],
    "thread_id": PROJECT_SCOPE["thread_id"],
    "item_kind": _ITEM_SEMANTIC["item_kind"],
    "lifecycle_state": "active",
    "summary": _ITEM_SEMANTIC["summary"],
    "kind_payload": _ITEM_SEMANTIC["kind_payload"],
    "authorship_kind": "solen_explicit",
    "author_participants": ["solen"],
    "semantic_authority_code": "participant_authored",
    "command_owner": "house_talk_continuity_authorship_intent_v1",
    "authorship_evidence_refs": [
        {
            "participant": "solen",
            "evidence_id": "solen-evidence-0001",
            "event_id": EVENT_1_ID,
            "content_sha256": _ITEM_CONTENT_SHA256,
        }
    ],
    "derivation_owner": None,
    "derivation_version": None,
    "confidence_millis": 1000,
    "source_turn_ids": ["client-turn-1"],
    "source_room_ids": [ROOM_ID],
    "source_operation_ids": ["provider-operation-1"],
    "source_proposal_ids": [],
    "exact_anchor_refs": [],
    "revision": 1,
    "base_event_id": EVENT_1_ID,
    "content_sha256": _ITEM_CONTENT_SHA256,
    "idempotency_key": "working-set-item-create-0001",
    "created_at": TIMESTAMP_0,
    "updated_at": TIMESTAMP_0,
    "last_confirmed_at": TIMESTAMP_0,
    "fresh_until": "2026-08-04T00:00:00.000Z",
    "aging_after": "2026-08-27T00:00:00.000Z",
    "dormant_after": "2026-10-26T00:00:00.000Z",
    "expires_at": None,
    "freshness_policy_code": "active_task_v1_1",
    "resolved_at": None,
    "abandoned_at": None,
    "resolution_reason_code": None,
    "abandonment_reason_code": None,
    "supersedes_item_ids": [],
    "superseded_by_item_id": None,
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


ASTEL_WORKING_SET_ITEM = deepcopy(WORKING_SET_ITEM)
ASTEL_WORKING_SET_ITEM.update(
    {
        "authorship_kind": "astel_explicit",
        "author_participants": ["astel"],
        "command_owner": "house_continuity_astel_explicit_command_v1",
        "authorship_evidence_refs": [
            {
                "participant": "astel",
                "evidence_id": "astel-evidence-0001",
                "event_id": EVENT_1_ID,
                "content_sha256": _ITEM_CONTENT_SHA256,
            }
        ],
        "idempotency_key": "working-set-astel-0001",
    }
)

JOINT_WORKING_SET_ITEM = deepcopy(WORKING_SET_ITEM)
JOINT_WORKING_SET_ITEM.update(
    {
        "authorship_kind": "joint_explicit",
        "author_participants": ["astel", "solen"],
        "command_owner": "house_continuity_joint_authorship_attestation_v1",
        "authorship_evidence_refs": [
            {
                "participant": "astel",
                "evidence_id": "astel-evidence-0001",
                "event_id": EVENT_1_ID,
                "content_sha256": _ITEM_CONTENT_SHA256,
            },
            {
                "participant": "solen",
                "evidence_id": "solen-evidence-0001",
                "event_id": EVENT_2_ID,
                "content_sha256": _ITEM_CONTENT_SHA256,
            },
        ],
        "idempotency_key": "working-set-joint-0001",
    }
)

ROOM_LINEAGE_WORKING_SET_ITEM = deepcopy(WORKING_SET_ITEM)
_ROOM_LINEAGE_SEMANTIC = {
    **_ITEM_SEMANTIC,
    "scope": ROOM_SCOPE_WITH_LINEAGE,
}
_ROOM_LINEAGE_CONTENT_SHA256 = canonical_sha256(_ROOM_LINEAGE_SEMANTIC)
ROOM_LINEAGE_WORKING_SET_ITEM.update(
    {
        **ROOM_SCOPE_WITH_LINEAGE,
        "content_sha256": _ROOM_LINEAGE_CONTENT_SHA256,
        "authorship_evidence_refs": [
            {
                "participant": "solen",
                "evidence_id": "solen-room-lineage-evidence-0001",
                "event_id": EVENT_1_ID,
                "content_sha256": _ROOM_LINEAGE_CONTENT_SHA256,
            }
        ],
        "idempotency_key": "working-set-room-lineage-0001",
    }
)

_TOOL_SEMANTIC = {
    "item_kind": "completed_tool_result_ref",
    "scope": PROJECT_SCOPE,
    "summary": "Reference the bounded synthetic completed tool result.",
    "kind_payload": ITEM_KIND_PAYLOADS["completed_tool_result_ref"],
}
STRUCTURED_TOOL_WORKING_SET_ITEM = deepcopy(WORKING_SET_ITEM)
STRUCTURED_TOOL_WORKING_SET_ITEM.update(
    {
        "item_kind": _TOOL_SEMANTIC["item_kind"],
        "summary": _TOOL_SEMANTIC["summary"],
        "kind_payload": _TOOL_SEMANTIC["kind_payload"],
        "content_sha256": canonical_sha256(_TOOL_SEMANTIC),
        "authorship_kind": "structured_tool_event",
        "author_participants": [],
        "semantic_authority_code": "structured_event",
        "command_owner": "house_continuity_structured_tool_event_v1",
        "authorship_evidence_refs": [],
        "freshness_policy_code": "completed_tool_result_ref_v1_1",
        "expires_at": "2026-10-27T00:00:00.000Z",
        "idempotency_key": "working-set-tool-0001",
    }
)

_CLIENT_SEMANTIC = {
    "item_kind": "decision",
    "scope": PROJECT_SCOPE,
    "summary": "Keep the Gate-0 correction synthetic-only.",
    "kind_payload": ITEM_KIND_PAYLOADS["decision"],
}
STRUCTURED_CLIENT_WORKING_SET_ITEM = deepcopy(WORKING_SET_ITEM)
STRUCTURED_CLIENT_WORKING_SET_ITEM.update(
    {
        "item_kind": _CLIENT_SEMANTIC["item_kind"],
        "summary": _CLIENT_SEMANTIC["summary"],
        "kind_payload": _CLIENT_SEMANTIC["kind_payload"],
        "content_sha256": canonical_sha256(_CLIENT_SEMANTIC),
        "authorship_kind": "structured_client_event",
        "author_participants": [],
        "semantic_authority_code": "structured_event",
        "command_owner": "house_continuity_structured_client_event_v1",
        "authorship_evidence_refs": [],
        "freshness_policy_code": "decision_v1_1",
        "idempotency_key": "working-set-client-0001",
    }
)

EVENT_CHAIN_CHECKPOINT_AFTER_TWO = {
    "global_event_sequence": 2,
    "global_event_sha256": SCOPE_BINDING_EVENT_1["global_event_sha256"],
    "item_heads": {
        ITEM_ID: {
            "sequence": 1,
            "sha256": WORKING_SET_EVENT_1["item_event_sha256"],
        }
    },
    "binding_heads": {
        ROOM_ID: {
            "sequence": 1,
            "sha256": SCOPE_BINDING_EVENT_1["binding_event_sha256"],
        }
    },
}

EXACT_ANCHOR_REF = {
    "schema_version": EXACT_ANCHOR_SCHEMA_VERSION,
    "anchor_id": ANCHOR_ID,
    "source_class": "complete_continuity_unit",
    "source_ref": "complete-unit-source-0001",
    "room_id": ROOM_ID,
    "turn_id": "client-turn-1",
    "operation_id": None,
    "message_order_start": 40,
    "message_order_end": 41,
    "content_sha256": _sha("exact-anchor-content"),
    "exact_body_stored": False,
}
LEGACY_EXACT_ANCHOR_REF = {
    **EXACT_ANCHOR_REF,
    "source_class": "android_complete_unit",
}


def _message(
    *,
    message_id: str,
    parent_turn_id: str,
    side: str,
    speaker: str,
    text: str,
    created_at_epoch_millis: int,
    operation_id: str | None = None,
    event_kind: str | None = None,
    operation_state: str | None = None,
    segment_index: int = 0,
    segment_count: int = 1,
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "parent_turn_id": parent_turn_id,
        "segment_index": segment_index,
        "segment_count": segment_count,
        "side": side,
        "speaker": speaker,
        "text": text,
        "route_label": "house-talk",
        "created_at_epoch_millis": created_at_epoch_millis,
        "complete": True,
        "operation_id": operation_id,
        "event_kind": event_kind,
        "operation_state": operation_state,
        "exact_or_derived": "exact",
    }


VISIBLE_EXCHANGE_UNIT = {
    "schema_version": COMPLETE_UNIT_SCHEMA_VERSION,
    "producer_class": "android_talk_continuity_units_v0",
    "producer_schema_version": "current",
    "unit_id": "ccu_" + ("a" * 32),
    "unit_kind": "visible_exchange",
    "grouping_id": "visible-group-0001",
    "source_start_id": "source-visible-0001",
    "source_end_id": "source-visible-0002",
    "source_ids": ["source-visible-0001", "source-visible-0002"],
    "rendered_source_ids": ["source-visible-0001", "source-visible-0002"],
    "exact_or_derived": "exact",
    "continuity_status": "complete",
    "complete": True,
    "operation_id": None,
    "messages": [
        _message(
            message_id="message-visible-0001",
            parent_turn_id="client-turn-visible-0001",
            side="astel",
            speaker="Astel",
            text="Exact Astel bytes.",
            created_at_epoch_millis=1785168000000,
        ),
        _message(
            message_id="message-visible-0002",
            parent_turn_id="client-turn-visible-0001",
            side="solen",
            speaker="Solen",
            text="Exact Solen bytes.",
            created_at_epoch_millis=1785168001000,
        ),
    ],
    "source_payload_sha256": _sha("visible-source-payload"),
    "transport_bytes_unchanged": True,
    "persisted_by_working_set": False,
    "memory_vault_truth": False,
    "self_state": False,
    "action_permission": False,
}

OPERATION_ID = "provider-operation-unit-0001"
PROVIDER_AGENT_OPERATION_UNIT = {
    **VISIBLE_EXCHANGE_UNIT,
    "unit_id": "ccu_" + ("b" * 32),
    "unit_kind": "provider_agent_operation",
    "grouping_id": "operation-group-0001",
    "source_start_id": "source-operation-0001",
    "source_end_id": "source-operation-0002",
    "source_ids": ["source-operation-0001", "source-operation-0002"],
    "rendered_source_ids": ["source-operation-0002"],
    "operation_id": OPERATION_ID,
    "messages": [
        _message(
            message_id="message-operation-0001",
            parent_turn_id="client-turn-operation-0001",
            side="solen",
            speaker="Solen",
            text="Working on it.",
            created_at_epoch_millis=1785168002000,
            operation_id=OPERATION_ID,
            event_kind="acknowledgement",
            operation_state="acknowledged",
        ),
        _message(
            message_id="message-operation-0002",
            parent_turn_id="client-turn-operation-0001",
            side="tool",
            speaker="House tool",
            text="The exact synthetic operation completed.",
            created_at_epoch_millis=1785168003000,
            operation_id=OPERATION_ID,
            event_kind="terminal_result",
            operation_state="completed",
        ),
    ],
    "source_payload_sha256": _sha("operation-source-payload"),
}
COMPLETE_CONTINUITY_UNIT = VISIBLE_EXCHANGE_UNIT

POSITIVE_DEPENDENCY_FIXTURES = {
    "creation_seed_registry": CREATION_SEED,
    "scope_binding": SCOPE_BINDING,
    "working_set_item": WORKING_SET_ITEM,
    "astel_working_set_item": ASTEL_WORKING_SET_ITEM,
    "joint_working_set_item": JOINT_WORKING_SET_ITEM,
    "structured_client_working_set_item": STRUCTURED_CLIENT_WORKING_SET_ITEM,
    "structured_tool_working_set_item": STRUCTURED_TOOL_WORKING_SET_ITEM,
    "room_lineage_working_set_item": ROOM_LINEAGE_WORKING_SET_ITEM,
    "working_set_event_1": WORKING_SET_EVENT_1,
    "working_set_event_2": WORKING_SET_EVENT_2,
    "scope_binding_event_1": SCOPE_BINDING_EVENT_1,
    "scope_binding_event_2": SCOPE_BINDING_EVENT_2,
    "second_item_event_1": SECOND_ITEM_EVENT_1,
    "exact_anchor_ref": EXACT_ANCHOR_REF,
    "legacy_exact_anchor_ref": LEGACY_EXACT_ANCHOR_REF,
    "visible_exchange_unit": VISIBLE_EXCHANGE_UNIT,
    "provider_agent_operation_unit": PROVIDER_AGENT_OPERATION_UNIT,
}

EVENT_CHAIN_FIXTURES = {
    "events": [
        WORKING_SET_EVENT_1,
        SCOPE_BINDING_EVENT_1,
        WORKING_SET_EVENT_2,
        SCOPE_BINDING_EVENT_2,
        SECOND_ITEM_EVENT_1,
    ],
    "partial_events": [
        WORKING_SET_EVENT_2,
        SCOPE_BINDING_EVENT_2,
        SECOND_ITEM_EVENT_1,
    ],
    "partial_checkpoint": EVENT_CHAIN_CHECKPOINT_AFTER_TWO,
}


def dependency_adversarial_fixtures() -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}

    bad_seed = deepcopy(CREATION_SEED)
    bad_seed["creation_seed_sha256"] = "short"
    cases["creation_seed_invalid_full_sha"] = {
        "validator": "creation_seed_registry",
        "value": bad_seed,
        "expected_error": "invalid_creation_seed_sha256",
    }

    bad_binding = deepcopy(SCOPE_BINDING)
    bad_binding["binding_revision"] = 0
    cases["scope_binding_zero_revision"] = {
        "validator": "scope_binding",
        "value": bad_binding,
        "expected_error": "invalid_binding_revision",
    }

    bad_item = deepcopy(WORKING_SET_ITEM)
    bad_item["content_sha256"] = _sha("wrong-item-content")
    cases["working_set_item_content_mismatch"] = {
        "validator": "working_set_item",
        "value": bad_item,
        "expected_error": "item_content_sha256_mismatch",
    }

    mutable_freshness = deepcopy(WORKING_SET_ITEM)
    mutable_freshness["selection_freshness_state"] = "fresh"
    cases["working_set_item_stored_freshness_forbidden"] = {
        "validator": "working_set_item",
        "value": mutable_freshness,
        "expected_error": "invalid_working_set_item_fields",
    }

    collapsed = deepcopy(WORKING_SET_EVENT_1)
    collapsed["item_event_sha256"] = collapsed["global_event_sha256"]
    cases["collapsed_global_item_event_identity"] = {
        "validator": "working_set_event",
        "value": collapsed,
        "expected_error": "item_event_sha256_mismatch",
    }

    arbitrary_start = deepcopy(WORKING_SET_EVENT_2)
    cases["arbitrary_non_genesis_chain_start"] = {
        "validator": "event_chain_without_checkpoint",
        "value": [arbitrary_start],
        "expected_error": "partial_chain_checkpoint_required",
    }

    bad_anchor = deepcopy(EXACT_ANCHOR_REF)
    bad_anchor["message_order_end"] = 39
    cases["exact_anchor_reversed_boundary"] = {
        "validator": "exact_anchor_ref",
        "value": bad_anchor,
        "expected_error": "invalid_source_boundary",
    }

    simplified_unit = {
        "schema_version": COMPLETE_UNIT_SCHEMA_VERSION,
        "unit_id": VISIBLE_EXCHANGE_UNIT["unit_id"],
        "source_payload_sha256": VISIBLE_EXCHANGE_UNIT[
            "source_payload_sha256"
        ],
        "byte_count": 2048,
    }
    cases["simplified_complete_unit_without_messages"] = {
        "validator": "complete_continuity_unit",
        "value": simplified_unit,
        "expected_error": "invalid_complete_continuity_unit_fields",
    }

    incomplete = deepcopy(VISIBLE_EXCHANGE_UNIT)
    incomplete["complete"] = False
    cases["incomplete_complete_unit"] = {
        "validator": "complete_continuity_unit",
        "value": incomplete,
        "expected_error": "invalid_complete_unit_authority",
    }

    mixed = deepcopy(VISIBLE_EXCHANGE_UNIT)
    mixed["messages"][1]["exact_or_derived"] = "derived"
    cases["mixed_exact_derived_complete_unit"] = {
        "validator": "complete_continuity_unit",
        "value": mixed,
        "expected_error": "incomplete_or_derived_message",
    }

    missing_sibling = deepcopy(VISIBLE_EXCHANGE_UNIT)
    missing_sibling["messages"][0]["segment_count"] = 2
    cases["missing_split_sibling"] = {
        "validator": "complete_continuity_unit",
        "value": missing_sibling,
        "expected_error": "missing_split_sibling",
    }

    acknowledgement_only = deepcopy(PROVIDER_AGENT_OPERATION_UNIT)
    acknowledgement_only["messages"] = acknowledgement_only["messages"][:1]
    acknowledgement_only["source_end_id"] = acknowledgement_only[
        "source_start_id"
    ]
    acknowledgement_only["source_ids"] = acknowledgement_only["source_ids"][:1]
    acknowledgement_only["rendered_source_ids"] = acknowledgement_only[
        "source_ids"
    ][:]
    cases["acknowledgement_not_superseded"] = {
        "validator": "complete_continuity_unit",
        "value": acknowledgement_only,
        "expected_error": "operation_finality_missing",
    }

    future_producer = deepcopy(VISIBLE_EXCHANGE_UNIT)
    future_producer["producer_class"] = "future_complete_unit_producer"
    cases["future_complete_unit_producer"] = {
        "validator": "complete_continuity_unit",
        "value": future_producer,
        "expected_error": "invalid_complete_unit_producer",
    }

    impossible_timestamp = deepcopy(WORKING_SET_ITEM)
    impossible_timestamp["updated_at"] = "2026-02-30T00:00:00.000Z"
    cases["working_set_item_impossible_timestamp"] = {
        "validator": "working_set_item",
        "value": impossible_timestamp,
        "expected_error": "invalid_updated_at",
    }
    return cases


ADVERSARIAL_DEPENDENCY_FIXTURES = dependency_adversarial_fixtures()


def _working_set_item_for_kind(
    kind: str,
    *,
    authorship_kind: str = "solen_explicit",
) -> dict[str, Any]:
    source = (
        STRUCTURED_TOOL_WORKING_SET_ITEM
        if authorship_kind == "structured_tool_event"
        else WORKING_SET_ITEM
    )
    value = deepcopy(source)
    semantic = {
        "item_kind": kind,
        "scope": PROJECT_SCOPE,
        "summary": f"Synthetic closure fixture for {kind}.",
        "kind_payload": ITEM_KIND_PAYLOADS[kind],
    }
    content_sha256 = canonical_sha256(semantic)
    value.update(
        {
            "item_kind": kind,
            "summary": semantic["summary"],
            "kind_payload": semantic["kind_payload"],
            "content_sha256": content_sha256,
            "freshness_policy_code": f"{kind}_v1_1",
        }
    )
    for evidence in value["authorship_evidence_refs"]:
        evidence["content_sha256"] = content_sha256
    return value


def closure_adversarial_fixtures() -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}

    wrong_policy = deepcopy(WORKING_SET_ITEM)
    wrong_policy["freshness_policy_code"] = "question_v1_1"
    cases["active_task_question_freshness_policy"] = {
        "value": wrong_policy,
        "expected_error": "freshness_policy_kind_mismatch",
    }

    expiring_review = _working_set_item_for_kind("pending_review")
    expiring_review["expires_at"] = "2026-10-27T00:00:00.000Z"
    cases["participant_pending_review_hard_expiry"] = {
        "value": expiring_review,
        "expected_error": "participant_semantic_hard_expiry_forbidden",
    }

    temporary_without_expiry = _working_set_item_for_kind("temporary_fact")
    cases["temporary_fact_without_hard_expiry"] = {
        "value": temporary_without_expiry,
        "expected_error": "bounded_hard_expiry_required",
    }

    tool_without_expiry = deepcopy(STRUCTURED_TOOL_WORKING_SET_ITEM)
    tool_without_expiry["expires_at"] = None
    cases["completed_tool_result_without_hard_expiry"] = {
        "value": tool_without_expiry,
        "expected_error": "bounded_hard_expiry_required",
    }

    active_cleanup = deepcopy(WORKING_SET_ITEM)
    active_cleanup["cleanup_state"] = "cleanup_eligible"
    active_cleanup["cleanup_eligible_at"] = active_cleanup["updated_at"]
    cases["active_item_cleanup_eligible"] = {
        "value": active_cleanup,
        "expected_error": "active_cleanup_eligible_forbidden",
    }

    terminal_cleanup_before_update = deepcopy(WORKING_SET_ITEM)
    terminal_cleanup_before_update.update(
        {
            "lifecycle_state": "resolved",
            "resolved_at": terminal_cleanup_before_update["created_at"],
            "resolution_reason_code": "completed",
            "cleanup_state": "cleanup_eligible",
            "cleanup_eligible_at": "2026-07-27T23:59:59.999Z",
        }
    )
    cases["terminal_cleanup_before_update"] = {
        "value": terminal_cleanup_before_update,
        "expected_error": "invalid_cleanup_eligible_timestamp",
    }

    resolved_before_creation = deepcopy(WORKING_SET_ITEM)
    resolved_before_creation.update(
        {
            "lifecycle_state": "resolved",
            "resolved_at": "2026-07-27T23:59:59.999Z",
            "resolution_reason_code": "completed",
        }
    )
    cases["resolved_timestamp_before_creation"] = {
        "value": resolved_before_creation,
        "expected_error": "invalid_resolved_timestamp",
    }

    abandoned_before_creation = deepcopy(WORKING_SET_ITEM)
    abandoned_before_creation.update(
        {
            "lifecycle_state": "abandoned",
            "abandoned_at": "2026-07-27T23:59:59.999Z",
            "abandonment_reason_code": "explicitly_abandoned",
        }
    )
    cases["abandoned_timestamp_before_creation"] = {
        "value": abandoned_before_creation,
        "expected_error": "invalid_abandoned_timestamp",
    }

    expired_before_expiry = _working_set_item_for_kind("temporary_fact")
    expired_before_expiry.update(
        {
            "lifecycle_state": "expired",
            "expires_at": "2026-10-27T00:00:00.000Z",
        }
    )
    cases["expired_update_precedes_expiry"] = {
        "value": expired_before_expiry,
        "expected_error": "invalid_expired_timestamp",
    }

    return cases


CLOSURE_ADVERSARIAL_FIXTURES = closure_adversarial_fixtures()


INHERITED_ITEM_EVENT_KIND_FIXTURES = {
    event_kind: _item_event(
        event_id="cws_evt_" + f"{index:032x}",
        global_sequence=index,
        prior_global=_sha(f"inherited-global-{index - 1}"),
        item_sequence=index,
        prior_item=_sha(f"inherited-item-{index - 1}"),
        event_kind=event_kind,
        from_lifecycle="active",
        to_lifecycle="active",
        expected_revision=index - 1,
        patch={},
        created_at=f"2026-07-29T00:00:{index:02d}.000Z",
    )
    for index, event_kind in enumerate(
        (
            "mark_cleanup_eligible",
            "merge_disjoint",
            "conflict_recorded",
            "scope_rebind_reference",
        ),
        10,
    )
}
