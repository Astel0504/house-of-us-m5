"""Synthetic executable dependency fixtures for Continuity V1.2 Gates 1/2."""

from __future__ import annotations

from copy import deepcopy

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
    import hashlib

    return hashlib.sha256(label.encode("utf-8")).hexdigest()


ROOM_ID = "cws_room_" + ("a" * 32)
PROJECT_ID = "cws_prj_" + ("a" * 32)
THREAD_ID = "cws_thr_" + ("a" * 32)
ITEM_ID = "cws_item_" + ("a" * 32)
BINDING_ID = "cws_bind_" + ("a" * 32)
TIMESTAMP_0 = "2026-07-28T00:00:00.000Z"
TIMESTAMP_1 = "2026-07-28T00:00:01.000Z"

PROJECT_SCOPE = {
    "scope_kind": "project",
    "room_id": None,
    "project_id": PROJECT_ID,
    "thread_id": THREAD_ID,
}

CREATION_SEED = {
    "schema_version": CREATION_SEED_SCHEMA_VERSION,
    "seed_id": "cws_seed_" + ("a" * 32),
    "entity_kind": "item",
    "entity_id": ITEM_ID,
    "creation_seed_sha256": _sha("working-set-item-creation-seed"),
    "registered_at": TIMESTAMP_0,
}

_ITEM_SEMANTIC = {
    "item_kind": "active_task",
    "scope": PROJECT_SCOPE,
    "summary": "Prove the corrected Gate-0 contracts.",
    "kind_payload": {
        "task_state": "in_progress",
        "linked_item_ids": [],
    },
}
WORKING_SET_ITEM = {
    "schema_version": WORKING_SET_ITEM_SCHEMA_VERSION,
    "item_id": ITEM_ID,
    "creation_seed_sha256": CREATION_SEED["creation_seed_sha256"],
    "revision": 1,
    **_ITEM_SEMANTIC,
    "lifecycle_state": "active",
    "selection_freshness_state": "fresh",
    "content_sha256": canonical_sha256(_ITEM_SEMANTIC),
    "authorship_kind": "solen_explicit",
    "source_turn_id": "client-turn-a-0001",
    "source_room_id": ROOM_ID,
    "source_operation_id": "provider-operation-a-0001",
    "previous_item_event_sha256": None,
    # Replaced below with the canonically computed first event hash once the
    # event fixture has been constructed.
    "last_item_event_sha256": _sha("item-event-1-construction-seed"),
    "created_at": TIMESTAMP_0,
    "updated_at": TIMESTAMP_0,
}


def _event(
    *,
    sequence: int,
    event_id_hex: str,
    item_revision: int,
    previous_global: str,
    previous_item: str | None,
    event_kind: str,
    semantic_hash: str,
    created_at: str,
) -> dict:
    event = {
        "schema_version": WORKING_SET_EVENT_SCHEMA_VERSION,
        "event_id": "cws_evt_" + event_id_hex,
        "creation_seed_sha256": _sha(f"event-seed-{sequence}"),
        "global_event_sequence": sequence,
        "previous_global_event_sha256": previous_global,
        "event_sha256": "",
        "item_id": ITEM_ID,
        "item_revision": item_revision,
        "previous_item_event_sha256": previous_item,
        "event_kind": event_kind,
        "semantic_content_sha256": semantic_hash,
        "source_turn_id": f"client-turn-a-{sequence:04d}",
        "source_room_id": ROOM_ID,
        "source_operation_id": f"provider-operation-a-{sequence:04d}",
        "created_at": created_at,
    }
    event["event_sha256"] = canonical_sha256(
        {key: value for key, value in event.items() if key != "event_sha256"}
    )
    return event


WORKING_SET_EVENT_1 = _event(
    sequence=1,
    event_id_hex="1" * 32,
    item_revision=1,
    previous_global=_sha("global-genesis"),
    previous_item=None,
    event_kind="create",
    semantic_hash=WORKING_SET_ITEM["content_sha256"],
    created_at=TIMESTAMP_0,
)
WORKING_SET_EVENT_2 = _event(
    sequence=2,
    event_id_hex="2" * 32,
    item_revision=2,
    previous_global=WORKING_SET_EVENT_1["event_sha256"],
    previous_item=WORKING_SET_EVENT_1["event_sha256"],
    event_kind="revise",
    semantic_hash=_sha("item-revision-2"),
    created_at=TIMESTAMP_1,
)
WORKING_SET_ITEM["last_item_event_sha256"] = WORKING_SET_EVENT_1[
    "event_sha256"
]


def _binding_event(
    *,
    sequence: int,
    revision: int,
    previous_global: str,
    previous_binding: str | None,
    event_kind: str,
    created_at: str,
) -> dict:
    event = {
        "schema_version": SCOPE_BINDING_EVENT_SCHEMA_VERSION,
        "event_id": "cws_evt_" + f"{sequence + 10:032x}",
        "creation_seed_sha256": _sha(f"binding-event-seed-{sequence}"),
        "binding_id": BINDING_ID,
        "binding_revision": revision,
        "previous_binding_event_sha256": previous_binding,
        "global_event_sequence": sequence,
        "previous_global_event_sha256": previous_global,
        "event_sha256": "",
        "event_kind": event_kind,
        "scope_sha256": canonical_sha256(PROJECT_SCOPE),
        "created_at": created_at,
    }
    event["event_sha256"] = canonical_sha256(
        {key: value for key, value in event.items() if key != "event_sha256"}
    )
    return event


SCOPE_BINDING_EVENT_1 = _binding_event(
    sequence=3,
    revision=1,
    previous_global=WORKING_SET_EVENT_2["event_sha256"],
    previous_binding=None,
    event_kind="bind",
    created_at=TIMESTAMP_1,
)
SCOPE_BINDING_EVENT_2 = _binding_event(
    sequence=4,
    revision=2,
    previous_global=SCOPE_BINDING_EVENT_1["event_sha256"],
    previous_binding=SCOPE_BINDING_EVENT_1["event_sha256"],
    event_kind="rebind",
    created_at="2026-07-28T00:00:02.000Z",
)

SCOPE_BINDING = {
    "schema_version": SCOPE_BINDING_SCHEMA_VERSION,
    "binding_id": BINDING_ID,
    "creation_seed_sha256": _sha("binding-seed"),
    "room_id": ROOM_ID,
    "project_id": PROJECT_ID,
    "thread_id": THREAD_ID,
    "revision": 2,
    "state": "bound",
    "global_event_sequence": 4,
    "global_event_sha256": SCOPE_BINDING_EVENT_2["event_sha256"],
    "binding_event_sha256": SCOPE_BINDING_EVENT_2["event_sha256"],
    "updated_at": "2026-07-28T00:00:02.000Z",
}

EXACT_ANCHOR_REF = {
    "schema_version": EXACT_ANCHOR_SCHEMA_VERSION,
    "anchor_id": "cws_anchor_" + ("a" * 32),
    "owner_code": "house_complete_continuity_unit_v1",
    "room_id": ROOM_ID,
    "complete_unit_id": "ccu_" + ("a" * 32),
    "complete_unit_sha256": _sha("complete-unit-bytes"),
    "source_start_sequence": 40,
    "source_end_sequence": 41,
    "raw_body_included": False,
}

COMPLETE_CONTINUITY_UNIT = {
    "schema_version": COMPLETE_UNIT_SCHEMA_VERSION,
    "unit_id": "ccu_" + ("a" * 32),
    "producer_code": "android_complete_continuity_unit",
    "producer_native_unit_id": "android-unit-a-0001",
    "room_id": ROOM_ID,
    "client_turn_id": "client-turn-a-0001",
    "provider_operation_id": "provider-operation-a-0001",
    "unit_sha256": _sha("complete-unit-bytes"),
    "byte_count": 2048,
    "complete": True,
    "raw_bytes_migrated": False,
    "created_at": TIMESTAMP_0,
}

POSITIVE_DEPENDENCY_FIXTURES = {
    "creation_seed_registry": CREATION_SEED,
    "scope_binding": SCOPE_BINDING,
    "working_set_item": WORKING_SET_ITEM,
    "working_set_event_1": WORKING_SET_EVENT_1,
    "working_set_event_2": WORKING_SET_EVENT_2,
    "scope_binding_event_1": SCOPE_BINDING_EVENT_1,
    "scope_binding_event_2": SCOPE_BINDING_EVENT_2,
    "exact_anchor_ref": EXACT_ANCHOR_REF,
    "complete_continuity_unit": COMPLETE_CONTINUITY_UNIT,
}

EVENT_CHAIN_FIXTURES = {
    "global_chain": [
        WORKING_SET_EVENT_1["event_sha256"],
        WORKING_SET_EVENT_2["event_sha256"],
        SCOPE_BINDING_EVENT_1["event_sha256"],
        SCOPE_BINDING_EVENT_2["event_sha256"],
    ],
    "item_chain": [
        WORKING_SET_EVENT_1["event_sha256"],
        WORKING_SET_EVENT_2["event_sha256"],
    ],
    "binding_chain": [
        SCOPE_BINDING_EVENT_1["event_sha256"],
        SCOPE_BINDING_EVENT_2["event_sha256"],
    ],
}


def dependency_adversarial_fixtures() -> dict[str, dict]:
    cases: dict[str, dict] = {}
    bad_seed = deepcopy(CREATION_SEED)
    bad_seed["creation_seed_sha256"] = "short"
    cases["creation_seed_invalid_full_sha"] = {
        "validator": "creation_seed_registry",
        "value": bad_seed,
        "expected_error": "invalid_creation_seed_sha256",
    }
    bad_binding = deepcopy(SCOPE_BINDING)
    bad_binding["revision"] = 0
    cases["scope_binding_zero_revision"] = {
        "validator": "scope_binding",
        "value": bad_binding,
        "expected_error": "invalid_revision",
    }
    bad_item = deepcopy(WORKING_SET_ITEM)
    bad_item["content_sha256"] = _sha("wrong-item-content")
    cases["working_set_item_content_mismatch"] = {
        "validator": "working_set_item",
        "value": bad_item,
        "expected_error": "item_content_sha256_mismatch",
    }
    bad_event = deepcopy(WORKING_SET_EVENT_2)
    bad_event["previous_global_event_sha256"] = _sha("wrong-global-predecessor")
    cases["working_set_event_hash_mismatch"] = {
        "validator": "working_set_event",
        "value": bad_event,
        "expected_error": "event_sha256_mismatch",
    }
    bad_binding_event = deepcopy(SCOPE_BINDING_EVENT_2)
    bad_binding_event["previous_binding_event_sha256"] = _sha("wrong-binding")
    cases["scope_binding_event_hash_mismatch"] = {
        "validator": "scope_binding_event",
        "value": bad_binding_event,
        "expected_error": "event_sha256_mismatch",
    }
    bad_anchor = deepcopy(EXACT_ANCHOR_REF)
    bad_anchor["source_end_sequence"] = 39
    cases["exact_anchor_reversed_boundary"] = {
        "validator": "exact_anchor_ref",
        "value": bad_anchor,
        "expected_error": "invalid_source_boundary",
    }
    bad_unit = deepcopy(COMPLETE_CONTINUITY_UNIT)
    bad_unit["raw_bytes_migrated"] = True
    cases["complete_unit_storage_migration_forbidden"] = {
        "validator": "complete_continuity_unit",
        "value": bad_unit,
        "expected_error": "forbidden_authority_true",
    }
    return cases


ADVERSARIAL_DEPENDENCY_FIXTURES = dependency_adversarial_fixtures()

# Gate-0 literal-conformance amendment: the approved-design fixtures are the
# sole exported dependency set. The definitions above remain readable only as
# historical correction-base construction evidence and are not registered as
# executable fixtures.
from house_continuity_v1_2_literal_conformance_fixtures_v0 import (  # noqa: E402
    ADVERSARIAL_DEPENDENCY_FIXTURES,
    COMPLETE_CONTINUITY_UNIT,
    CREATION_SEED,
    EVENT_CHAIN_CHECKPOINT_AFTER_TWO,
    EVENT_CHAIN_FIXTURES,
    EXACT_ANCHOR_REF,
    ITEM_KIND_PAYLOADS,
    LEGACY_EXACT_ANCHOR_REF,
    POSITIVE_DEPENDENCY_FIXTURES,
    PROJECT_SCOPE,
    PROVIDER_AGENT_OPERATION_UNIT,
    ROOM_ID,
    ROOM_SCOPE_WITH_LINEAGE,
    SECOND_ITEM_EVENT_1,
    SCOPE_BINDING,
    SCOPE_BINDING_EVENT_1,
    SCOPE_BINDING_EVENT_2,
    VISIBLE_EXCHANGE_UNIT,
    WORKING_SET_EVENT_1,
    WORKING_SET_EVENT_2,
    WORKING_SET_ITEM,
)
