"""Focused Gate-1 tests for the synthetic/local Continuity V1.2 store."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import house_continuity_v1_2_contract_fixtures_v0 as gate0
import house_continuity_v1_2_literal_conformance_fixtures_v0 as literal
from house_continuity_v1_2_executable_contracts_v0 import (
    HouseContinuityV12ContractError,
    canonical_sha256,
)
from house_continuity_v1_2_local_store_v1 import (
    HouseContinuityLocalStoreError,
    HouseContinuityV12LocalStore,
)


class HouseContinuityV12LocalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="house-continuity-gate1-"
        )
        self.root = Path(self.temporary.name)
        self.store = HouseContinuityV12LocalStore(
            self.root, synthetic_only=True
        )
        self.event_counter = 100

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def assert_store_error(self, code, function, *args, **kwargs):
        with self.assertRaises(HouseContinuityLocalStoreError) as caught:
            function(*args, **kwargs)
        self.assertEqual(code, caught.exception.error_code)

    def event_id(self):
        self.event_counter += 1
        return "cws_evt_" + f"{self.event_counter:032x}"

    def command_hash(self, label):
        return canonical_sha256({"synthetic_gate1_command": label})

    def create_item(self, item=None, *, label="create"):
        value = deepcopy(literal.WORKING_SET_ITEM if item is None else item)
        event_id = value["base_event_id"]
        command_hash = self.command_hash(label)
        event = self.store.prepare_item_event(
            event_id=event_id,
            event_kind="create",
            next_item=value,
            expected_revision=0,
            actor_kind=value["authorship_kind"],
            actor_ref=value["command_owner"],
            idempotency_key=value["idempotency_key"],
            command_sha256=command_hash,
            created_at=value["created_at"],
        )
        receipt = self.store.apply_item_event(event, value)
        return value, event, receipt

    def evolve(
        self,
        current,
        *,
        event_kind,
        at,
        actor_kind="solen_explicit",
        actor_ref="house_talk_continuity_authorship_intent_v1",
        **changes,
    ):
        value = deepcopy(current)
        event_id = self.event_id()
        value.update(changes)
        value.update(
            {
                "revision": current["revision"] + 1,
                "base_event_id": event_id,
                "idempotency_key": f"gate1-{event_kind}-{self.event_counter}",
                "updated_at": at,
            }
        )
        if any(
            key in changes
            for key in (
                "item_kind",
                "scope_kind",
                "room_id",
                "project_id",
                "thread_id",
                "summary",
                "kind_payload",
            )
        ):
            scope = {
                "scope_kind": value["scope_kind"],
                "room_id": value["room_id"],
                "project_id": value["project_id"],
                "thread_id": value["thread_id"],
            }
            value["content_sha256"] = canonical_sha256(
                {
                    "item_kind": value["item_kind"],
                    "scope": scope,
                    "summary": value["summary"],
                    "kind_payload": value["kind_payload"],
                }
            )
            for evidence in value["authorship_evidence_refs"]:
                evidence["content_sha256"] = value["content_sha256"]
        command_hash = self.command_hash(value["idempotency_key"])
        event = self.store.prepare_item_event(
            event_id=event_id,
            event_kind=event_kind,
            next_item=value,
            expected_revision=current["revision"],
            actor_kind=actor_kind,
            actor_ref=actor_ref,
            idempotency_key=value["idempotency_key"],
            command_sha256=command_hash,
            created_at=at,
        )
        return value, event

    def test_synthetic_local_boundary_and_authoritative_empty(self):
        self.assert_store_error(
            "synthetic_only_required",
            HouseContinuityV12LocalStore,
            self.root,
            synthetic_only=False,
        )
        projection = self.store.read_projection(
            now="2026-07-29T00:00:00.000Z",
            room_id=literal.ROOM_ID,
            project_id=literal.PROJECT_ID,
            thread_id=literal.THREAD_ID,
        )
        self.assertTrue(projection["authoritative_empty"])
        self.assertEqual([], projection["selected"])
        self.assertFalse(hasattr(self.store, "delete_item"))

    def test_create_confirm_revise_resolve_and_reopen(self):
        item, _, _ = self.create_item()
        confirmed, event = self.evolve(
            item,
            event_kind="confirm",
            at="2026-07-29T00:00:00.000Z",
            last_confirmed_at="2026-07-29T00:00:00.000Z",
            fresh_until="2026-08-05T00:00:00.000Z",
            aging_after="2026-08-28T00:00:00.000Z",
            dormant_after="2026-10-27T00:00:00.000Z",
        )
        self.store.apply_item_event(event, confirmed)

        revised_payload = deepcopy(confirmed["kind_payload"])
        revised_payload["task_state"] = "blocked"
        revised, event = self.evolve(
            confirmed,
            event_kind="revise",
            at="2026-07-30T00:00:00.000Z",
            summary="Complete Gate 1 after resolving the exact local blocker.",
            kind_payload=revised_payload,
        )
        self.store.apply_item_event(event, revised)

        resolved, event = self.evolve(
            revised,
            event_kind="resolve",
            at="2026-07-31T00:00:00.000Z",
            lifecycle_state="resolved",
            resolved_at="2026-07-31T00:00:00.000Z",
            resolution_reason_code="completed",
        )
        self.store.apply_item_event(event, resolved)

        reopened, event = self.evolve(
            resolved,
            event_kind="reopen",
            at="2026-08-01T00:00:00.000Z",
            lifecycle_state="active",
            resolved_at=None,
            resolution_reason_code=None,
            reopens_item_id=resolved["item_id"],
            last_confirmed_at="2026-08-01T00:00:00.000Z",
            fresh_until="2026-08-08T00:00:00.000Z",
            aging_after="2026-08-31T00:00:00.000Z",
            dormant_after="2026-10-30T00:00:00.000Z",
        )
        self.store.apply_item_event(event, reopened)
        self.assertEqual("active", self.store.read_item(item["item_id"])["lifecycle_state"])
        self.assertTrue(self.store.doctor()["replay_exact"])

    def test_abandon_and_cleanup_retention_without_deletion(self):
        item, _, _ = self.create_item()
        abandoned, event = self.evolve(
            item,
            event_kind="abandon",
            at="2026-07-29T00:00:00.000Z",
            actor_kind="astel_explicit",
            actor_ref="house_continuity_astel_explicit_command_v1",
            authorship_kind="astel_explicit",
            author_participants=["astel"],
            command_owner="house_continuity_astel_explicit_command_v1",
            authorship_evidence_refs=deepcopy(
                literal.ASTEL_WORKING_SET_ITEM["authorship_evidence_refs"]
            ),
            lifecycle_state="abandoned",
            abandoned_at="2026-07-29T00:00:00.000Z",
            abandonment_reason_code="explicitly_abandoned",
        )
        self.store.apply_item_event(event, abandoned)

        too_early, early_event = self.evolve(
            abandoned,
            event_kind="mark_cleanup_eligible",
            at="2027-07-28T00:00:00.000Z",
            actor_kind="deterministic_lifecycle",
            actor_ref="house_continuity_cleanup_v1",
            cleanup_state="cleanup_eligible",
            cleanup_eligible_at="2027-07-28T00:00:00.000Z",
        )
        self.assert_store_error(
            "cleanup_retention_not_reached",
            self.store.apply_item_event,
            early_event,
            too_early,
        )

        eligible, event = self.evolve(
            abandoned,
            event_kind="mark_cleanup_eligible",
            at="2027-07-29T00:00:00.000Z",
            actor_kind="deterministic_lifecycle",
            actor_ref="house_continuity_cleanup_v1",
            cleanup_state="cleanup_eligible",
            cleanup_eligible_at="2027-07-29T00:00:00.000Z",
        )
        self.store.apply_item_event(event, eligible)
        self.assertIsNotNone(self.store.read_item(item["item_id"]))
        self.assertEqual(
            "cleanup_eligible",
            self.store.read_item(item["item_id"])["cleanup_state"],
        )

    def test_hard_expiry_only_for_allowed_kinds(self):
        temporary = literal._working_set_item_for_kind("temporary_fact")
        temporary["expires_at"] = "2026-10-27T00:00:00.000Z"
        temporary["idempotency_key"] = "gate1-temporary-create"
        temporary["base_event_id"] = self.event_id()
        item, _, _ = self.create_item(temporary, label="temporary")
        expired, event = self.evolve(
            item,
            event_kind="expire",
            at="2026-10-27T00:00:00.000Z",
            actor_kind="deterministic_lifecycle",
            actor_ref="house_continuity_expiry_v1",
            lifecycle_state="expired",
        )
        self.store.apply_item_event(event, expired)
        self.assertEqual("expired", self.store.read_item(item["item_id"])["lifecycle_state"])

        semantic_store_root = self.root / "semantic"
        semantic_store_root.mkdir()
        with HouseContinuityV12LocalStore(
            semantic_store_root, synthetic_only=True
        ) as semantic_store:
            semantic = deepcopy(literal.WORKING_SET_ITEM)
            semantic["base_event_id"] = "cws_evt_" + ("e" * 32)
            create = semantic_store.prepare_item_event(
                event_id=semantic["base_event_id"],
                event_kind="create",
                next_item=semantic,
                expected_revision=0,
                actor_kind="solen_explicit",
                actor_ref=semantic["command_owner"],
                idempotency_key=semantic["idempotency_key"],
                command_sha256=self.command_hash("semantic-create"),
                created_at=semantic["created_at"],
            )
            semantic_store.apply_item_event(create, semantic)
            invalid = deepcopy(semantic)
            invalid.update(
                {
                    "revision": 2,
                    "base_event_id": "cws_evt_" + ("f" * 32),
                    "idempotency_key": "semantic-expire",
                    "updated_at": "2026-10-27T00:00:00.000Z",
                    "lifecycle_state": "expired",
                    "expires_at": "2026-10-27T00:00:00.000Z",
                }
            )
            with self.assertRaises(HouseContinuityV12ContractError):
                semantic_store.prepare_item_event(
                    event_id=invalid["base_event_id"],
                    event_kind="expire",
                    next_item=invalid,
                    expected_revision=semantic["revision"],
                    actor_kind="deterministic_lifecycle",
                    actor_ref="house_continuity_expiry_v1",
                    idempotency_key=invalid["idempotency_key"],
                    command_sha256=self.command_hash("semantic-expire"),
                    created_at=invalid["updated_at"],
                )

    def test_supersede_requires_compatible_linked_successor(self):
        original, _, _ = self.create_item()
        successor = deepcopy(literal.WORKING_SET_ITEM)
        successor.update(
            {
                "item_id": "cws_item_" + ("9" * 32),
                "creation_seed_sha256": canonical_sha256("successor-seed"),
                "base_event_id": self.event_id(),
                "idempotency_key": "successor-create",
                "supersedes_item_ids": [original["item_id"]],
            }
        )
        self.create_item(successor, label="successor")
        superseded, event = self.evolve(
            original,
            event_kind="supersede",
            at="2026-07-29T00:00:00.000Z",
            lifecycle_state="superseded",
            superseded_by_item_id=successor["item_id"],
        )
        self.store.apply_item_event(event, superseded)
        self.assertEqual(
            "superseded",
            self.store.read_item(original["item_id"])["lifecycle_state"],
        )

    def test_attest_joint_persists_only_validated_joint_state(self):
        item, _, _ = self.create_item()
        self.store.put_joint_attestation(gate0.JOINT_ATTESTATION)
        joint = deepcopy(item)
        joint.update(
            {
                "authorship_kind": "joint_explicit",
                "author_participants": ["astel", "solen"],
                "command_owner": (
                    "house_continuity_joint_authorship_attestation_v1"
                ),
                "authorship_evidence_refs": deepcopy(
                    literal.JOINT_WORKING_SET_ITEM[
                        "authorship_evidence_refs"
                    ]
                ),
            }
        )
        joint, event = self.evolve(
            item,
            event_kind="attest_joint",
            at="2026-07-29T00:00:00.000Z",
            actor_kind="joint_explicit",
            actor_ref="house_continuity_joint_authorship_attestation_v1",
            authorship_kind=joint["authorship_kind"],
            author_participants=joint["author_participants"],
            command_owner=joint["command_owner"],
            authorship_evidence_refs=joint["authorship_evidence_refs"],
        )
        receipt = {
            "schema_version": "house_continuity_accepted_joint_receipt_v1",
            "receipt_id": "cws_jrc_" + ("1" * 32),
            "attestation_id": "cws_jat_" + ("1" * 32),
            "attestation_sha256": canonical_sha256(
                {"synthetic_joint_attestation": event["idempotency_key"]}
            ),
            "astel_evidence_id": joint["authorship_evidence_refs"][0][
                "evidence_id"
            ],
            "astel_event_id": joint["authorship_evidence_refs"][0]["event_id"],
            "astel_content_sha256": joint["content_sha256"],
            "solen_evidence_id": joint["authorship_evidence_refs"][1][
                "evidence_id"
            ],
            "solen_event_id": joint["authorship_evidence_refs"][1]["event_id"],
            "solen_content_sha256": joint["content_sha256"],
            "item_id": joint["item_id"],
            "expected_revision": event["expected_revision"],
            "scope_sha256": canonical_sha256(
                {
                    "scope_kind": joint["scope_kind"],
                    "room_id": joint["room_id"],
                    "project_id": joint["project_id"],
                    "thread_id": joint["thread_id"],
                }
            ),
            "canonical_semantic_sha256": joint["content_sha256"],
            "idempotency_identity": event["idempotency_key"],
            "committed_at": event["created_at"],
            "durably_committed": True,
            "raw_body_included": False,
            "receipt_sha256": "",
        }
        receipt["receipt_sha256"] = canonical_sha256(
            {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        )
        self.assert_store_error(
            "accepted_joint_receipt_required",
            self.store.apply_item_event,
            event,
            joint,
        )
        self.store.put_accepted_joint_receipt(receipt)
        self.store.apply_item_event(
            event, joint, accepted_joint_receipt=receipt
        )
        self.assertEqual(
            "joint_explicit",
            self.store.read_item(item["item_id"])["authorship_kind"],
        )

    def test_exact_retry_command_collision_cas_and_terminal_protection(self):
        item, event, receipt = self.create_item()
        self.assertEqual(receipt, self.store.apply_item_event(event, item))

        confirmed, collision = self.evolve(
            item,
            event_kind="confirm",
            at="2026-07-29T00:00:00.000Z",
            last_confirmed_at="2026-07-29T00:00:00.000Z",
            fresh_until="2026-08-05T00:00:00.000Z",
            aging_after="2026-08-28T00:00:00.000Z",
            dormant_after="2026-10-27T00:00:00.000Z",
        )
        collision["idempotency_key"] = event["idempotency_key"]
        collision["event_payload_sha256"] = literal._event_payload_hash(collision)
        collision["global_event_sha256"] = literal._global_hash(collision)
        collision["item_event_sha256"] = literal._item_hash(collision)
        self.assert_store_error(
            "idempotency_key_command_mismatch",
            self.store.apply_item_event,
            collision,
            confirmed,
        )

        stale_next, stale_event = self.evolve(
            item,
            event_kind="revise",
            at="2026-07-30T00:00:00.000Z",
            summary="Stale parallel semantic rewrite.",
        )
        resolved, resolve_event = self.evolve(
            item,
            event_kind="resolve",
            at="2026-07-29T00:00:00.000Z",
            lifecycle_state="resolved",
            resolved_at="2026-07-29T00:00:00.000Z",
            resolution_reason_code="completed",
        )
        self.store.apply_item_event(resolve_event, resolved)
        self.assert_store_error(
            "stale_expected_revision",
            self.store.apply_item_event,
            stale_event,
            stale_next,
        )

    def test_disjoint_stale_merge_and_changed_field_conflict(self):
        base, _, _ = self.create_item()
        first_payload = deepcopy(base["kind_payload"])
        first_payload["task_state"] = "blocked"
        first, first_event = self.evolve(
            base,
            event_kind="revise",
            at="2026-07-29T00:00:00.000Z",
            kind_payload=first_payload,
        )
        self.store.apply_item_event(first_event, first)

        merged = deepcopy(first)
        merged["source_turn_ids"] = base["source_turn_ids"] + [
            "client-turn-disjoint"
        ]
        merged, merge_event = self.evolve(
            first,
            event_kind="merge_disjoint",
            at="2026-07-30T00:00:00.000Z",
            source_turn_ids=merged["source_turn_ids"],
        )
        self.store.apply_disjoint_merge(
            base_revision=1,
            event=merge_event,
            next_item=merged,
        )
        self.assertIn(
            "client-turn-disjoint",
            self.store.read_item(base["item_id"])["source_turn_ids"],
        )

        conflicting_payload = deepcopy(merged["kind_payload"])
        conflicting_payload["task_state"] = "waiting"
        conflict, conflict_event = self.evolve(
            merged,
            event_kind="merge_disjoint",
            at="2026-07-31T00:00:00.000Z",
            kind_payload=conflicting_payload,
        )
        self.assert_store_error(
            "merge_field_changed_since_base",
            self.store.apply_disjoint_merge,
            base_revision=1,
            event=conflict_event,
            next_item=conflict,
        )

    def test_explicit_conflict_receipt_preserves_semantics(self):
        item, _, _ = self.create_item()
        conflict, event = self.evolve(
            item,
            event_kind="conflict_recorded",
            at="2026-07-29T00:00:00.000Z",
            actor_kind="deterministic_lifecycle",
            actor_ref="house_continuity_parallel_conflict_v1",
        )
        self.assert_store_error(
            "conflict_reason_required",
            self.store.apply_item_event,
            event,
            conflict,
        )
        receipt = self.store.apply_item_event(
            event,
            conflict,
            conflict_reason_code="explicit_equal_agency_conflict",
        )
        self.assertEqual(
            "explicit_equal_agency_conflict",
            receipt["conflict_reason_code"],
        )
        self.assertEqual(
            item["summary"], self.store.read_item(item["item_id"])["summary"]
        )
        review = literal._working_set_item_for_kind("pending_review")
        review.update(
            {
                "item_id": "cws_item_" + ("8" * 32),
                "creation_seed_sha256": canonical_sha256("review-seed"),
                "base_event_id": self.event_id(),
                "idempotency_key": "explicit-conflict-review",
            }
        )
        self.create_item(review, label="explicit-conflict-review")
        self.assertEqual(
            "pending_review",
            self.store.read_item(review["item_id"])["item_kind"],
        )

        shadow = deepcopy(self.store.read_item(item["item_id"]))
        shadow.update(
            {
                "authorship_kind": "deterministic_shadow",
                "author_participants": [],
                "semantic_authority_code": "shadow_only",
                "command_owner": "heuristic_owner",
                "authorship_evidence_refs": [],
            }
        )
        with self.assertRaises(HouseContinuityV12ContractError):
            self.store.prepare_item_event(
                event_id=self.event_id(),
                event_kind="revise",
                next_item=shadow,
                expected_revision=item["revision"],
                actor_kind="deterministic_lifecycle",
                actor_ref="heuristic_owner",
                idempotency_key="shadow-overwrite",
                command_sha256=self.command_hash("shadow-overwrite"),
                created_at="2026-07-30T00:00:00.000Z",
            )

    def test_transition_actor_patch_and_scope_reference_guards(self):
        item, _, _ = self.create_item()
        smuggled, smuggled_event = self.evolve(
            item,
            event_kind="confirm",
            at="2026-07-29T00:00:00.000Z",
            summary="Confirm must not rewrite this summary.",
        )
        self.assert_store_error(
            "event_patch_field_forbidden",
            self.store.apply_item_event,
            smuggled_event,
            smuggled,
        )

        wrong_scope, wrong_scope_event = self.evolve(
            item,
            event_kind="revise",
            at="2026-07-29T00:00:00.000Z",
            project_id="cws_prj_" + ("f" * 32),
        )
        self.assert_store_error(
            "immutable_item_field_changed",
            self.store.apply_item_event,
            wrong_scope_event,
            wrong_scope,
        )

        active_resolve, active_resolve_event = self.evolve(
            item,
            event_kind="resolve",
            at="2026-07-29T00:00:00.000Z",
        )
        self.assert_store_error(
            "invalid_lifecycle_transition",
            self.store.apply_item_event,
            active_resolve_event,
            active_resolve,
        )

        resolved, deterministic_resolve = self.evolve(
            item,
            event_kind="resolve",
            at="2026-07-29T00:00:00.000Z",
            actor_kind="deterministic_lifecycle",
            actor_ref="forbidden-deterministic-resolution",
            lifecycle_state="resolved",
            resolved_at="2026-07-29T00:00:00.000Z",
            resolution_reason_code="completed",
        )
        self.assert_store_error(
            "actor_transition_incompatible",
            self.store.apply_item_event,
            deterministic_resolve,
            resolved,
        )

        source_room = "cws_room_" + ("e" * 32)
        referenced, reference_event = self.evolve(
            item,
            event_kind="scope_rebind_reference",
            at="2026-07-30T00:00:00.000Z",
            source_room_ids=item["source_room_ids"] + [source_room],
        )
        self.store.apply_item_event(reference_event, referenced)
        self.assertIn(
            source_room,
            self.store.read_item(item["item_id"])["source_room_ids"],
        )

    def test_binding_transitions_and_decline_cannot_leave_bound_target(self):
        binding = deepcopy(literal.SCOPE_BINDING)
        binding.update(
            {
                "binding_revision": 1,
                "predecessor_room_id": None,
                "binding_source": "explicit_thread",
                "idempotency_key": "gate1-binding-create",
                "created_at": "2026-07-28T00:00:00.000Z",
                "updated_at": "2026-07-28T00:00:00.000Z",
            }
        )
        event = self.store.prepare_binding_event(
            event_id=self.event_id(),
            event_kind="bind",
            to_binding=binding,
            expected_binding_revision=0,
            actor_kind="astel_explicit",
            actor_ref="house_continuity_astel_explicit_command_v1",
            idempotency_key=binding["idempotency_key"],
            command_sha256=self.command_hash("binding-create"),
            created_at=binding["created_at"],
        )
        self.store.apply_binding_event(event)
        self.assert_store_error(
            "stale_binding_revision",
            self.store.prepare_binding_event,
            event_id=self.event_id(),
            event_kind="rebind",
            to_binding={
                **binding,
                "binding_revision": 2,
                "idempotency_key": "stale-binding-preparation",
                "updated_at": "2026-07-29T00:00:00.000Z",
            },
            expected_binding_revision=0,
            actor_kind="astel_explicit",
            actor_ref="house_continuity_astel_explicit_command_v1",
            idempotency_key="stale-binding-preparation",
            command_sha256=self.command_hash("stale-binding-preparation"),
            created_at="2026-07-29T00:00:00.000Z",
        )

        bound_decline = deepcopy(binding)
        bound_decline.update(
            {
                "binding_revision": 2,
                "idempotency_key": "bound-decline",
                "updated_at": "2026-07-29T00:00:00.000Z",
            }
        )
        invalid_event = self.store.prepare_binding_event(
            event_id=self.event_id(),
            event_kind="decline",
            to_binding=bound_decline,
            expected_binding_revision=binding["binding_revision"],
            actor_kind="astel_explicit",
            actor_ref="house_continuity_astel_explicit_command_v1",
            idempotency_key=bound_decline["idempotency_key"],
            command_sha256=self.command_hash("bound-decline"),
            created_at=bound_decline["updated_at"],
        )
        self.assert_store_error(
            "decline_must_leave_unbound_target",
            self.store.apply_binding_event,
            invalid_event,
        )

        unbound = deepcopy(bound_decline)
        unbound.update(
            {
                "project_id": None,
                "thread_id": None,
                "binding_source": "new_unbound",
                "idempotency_key": "valid-decline",
            }
        )
        valid_event = self.store.prepare_binding_event(
            event_id=self.event_id(),
            event_kind="decline",
            to_binding=unbound,
            expected_binding_revision=binding["binding_revision"],
            actor_kind="astel_explicit",
            actor_ref="house_continuity_astel_explicit_command_v1",
            idempotency_key=unbound["idempotency_key"],
            command_sha256=self.command_hash("valid-decline"),
            created_at=unbound["updated_at"],
        )
        self.store.apply_binding_event(valid_event)
        self.assertIsNone(
            self.store.read_binding(binding["room_id"])["project_id"]
        )

    def test_dormancy_wake_is_read_only(self):
        item, _, _ = self.create_item()
        before = self.store.event_count()
        unrelated = self.store.read_projection(
            now="2027-01-01T00:00:00.000Z",
            room_id="cws_room_" + ("f" * 32),
            project_id="cws_prj_" + ("f" * 32),
            thread_id=None,
        )
        self.assertTrue(unrelated["authoritative_empty"])
        same_scope = self.store.read_projection(
            now="2027-01-01T00:00:00.000Z",
            room_id=literal.ROOM_ID,
            project_id=literal.PROJECT_ID,
            thread_id=literal.THREAD_ID,
        )
        self.assertEqual("dormant", same_scope["selected"][0]["selection_freshness"])
        self.assertTrue(same_scope["selected"][0]["wake_applied"])
        self.assertEqual(
            ["exact_project_scope_continuation"],
            same_scope["selected"][0]["wake_reason_codes"],
        )
        self.assertEqual(before, self.store.event_count())
        self.assertEqual(item["revision"], self.store.read_item(item["item_id"])["revision"])

    def test_dormant_global_requires_an_explicit_approved_wake_reason(self):
        global_item = deepcopy(literal.WORKING_SET_ITEM)
        global_item.update(
            {
                "item_id": "cws_item_" + ("6" * 32),
                "creation_seed_sha256": canonical_sha256("global-item-seed"),
                "scope_kind": "global",
                "room_id": None,
                "project_id": None,
                "thread_id": None,
                "base_event_id": self.event_id(),
                "idempotency_key": "gate1-global-create",
            }
        )
        global_item["content_sha256"] = canonical_sha256(
            {
                "item_kind": global_item["item_kind"],
                "scope": {
                    "scope_kind": "global",
                    "room_id": None,
                    "project_id": None,
                    "thread_id": None,
                },
                "summary": global_item["summary"],
                "kind_payload": global_item["kind_payload"],
            }
        )
        global_item["authorship_evidence_refs"][0][
            "content_sha256"
        ] = global_item["content_sha256"]
        self.create_item(global_item, label="global-create")
        dormant = self.store.read_projection(
            now="2027-01-01T00:00:00.000Z",
            room_id=literal.ROOM_ID,
            project_id=literal.PROJECT_ID,
            thread_id=literal.THREAD_ID,
        )
        self.assertTrue(dormant["authoritative_empty"])
        explicit = self.store.read_projection(
            now="2027-01-01T00:00:00.000Z",
            room_id=literal.ROOM_ID,
            project_id=literal.PROJECT_ID,
            thread_id=literal.THREAD_ID,
            exact_relevance_item_ids=(global_item["item_id"],),
        )
        self.assertEqual(global_item["item_id"], explicit["selected"][0]["item"]["item_id"])
        self.assertTrue(explicit["selected"][0]["wake_applied"])
        self.assertIn(
            "exact_relevance",
            explicit["selected"][0]["wake_reason_codes"],
        )

    def test_due_expiry_blocks_projection_until_event_is_appended(self):
        temporary = literal._working_set_item_for_kind("temporary_fact")
        temporary.update(
            {
                "base_event_id": self.event_id(),
                "idempotency_key": "gate1-expiry-due-create",
                "expires_at": "2026-10-27T00:00:00.000Z",
            }
        )
        self.create_item(temporary, label="expiry-due")
        due = self.store.read_projection(
            now="2026-10-28T00:00:00.000Z",
            room_id=temporary["room_id"],
            project_id=temporary["project_id"],
            thread_id=temporary["thread_id"],
        )
        self.assertEqual("expiry_due", due["selection_state"])
        self.assertFalse(due["authoritative_empty"])
        self.assertEqual([temporary["item_id"]], due["expiry_due_item_ids"])
        self.assertEqual([], due["selected"])
        unrelated = self.store.read_projection(
            now="2026-10-28T00:00:00.000Z",
            room_id="cws_room_" + ("b" * 32),
            project_id="cws_prj_" + ("b" * 32),
            thread_id="cws_thr_" + ("b" * 32),
        )
        self.assertEqual("ready", unrelated["selection_state"])
        self.assertTrue(unrelated["authoritative_empty"])
        self.assertEqual([], unrelated["expiry_due_item_ids"])

    def test_event_seed_stale_preparation_and_actor_binding_fail_closed(self):
        item, event, _ = self.create_item()
        seed_rows = {
            row["entity_id"]: row
            for row in self.store._connection.execute(
                "SELECT entity_id,entity_kind,creation_seed_sha256,created_at"
                " FROM creation_seeds"
            )
        }
        self.assertEqual("item", seed_rows[item["item_id"]]["entity_kind"])
        self.assertEqual("event", seed_rows[event["event_id"]]["entity_kind"])
        self.assertNotEqual(
            seed_rows[item["item_id"]]["creation_seed_sha256"],
            seed_rows[event["event_id"]]["creation_seed_sha256"],
        )
        self.assert_store_error(
            "creation_seed_collision",
            self.store.register_creation_seed,
            event["event_id"],
            "f" * 64,
            entity_kind="event",
            created_at=event["created_at"],
        )
        stale = deepcopy(item)
        stale.update(
            {
                "revision": 2,
                "base_event_id": self.event_id(),
                "idempotency_key": "stale-prepare",
                "updated_at": "2026-07-29T00:00:00.000Z",
            }
        )
        self.assert_store_error(
            "stale_expected_revision",
            self.store.prepare_item_event,
            event_id=stale["base_event_id"],
            event_kind="confirm",
            next_item=stale,
            expected_revision=0,
            actor_kind="solen_explicit",
            actor_ref="house_talk_continuity_authorship_intent_v1",
            idempotency_key=stale["idempotency_key"],
            command_sha256=self.command_hash("stale-prepare"),
            created_at=stale["updated_at"],
        )
        wrong, wrong_event = self.evolve(
            item,
            event_kind="confirm",
            at="2026-07-29T00:00:00.000Z",
            actor_ref="arbitrary-actor",
        )
        self.assert_store_error(
            "actor_ref_mismatch",
            self.store.apply_item_event,
            wrong_event,
            wrong,
        )

    def test_atomic_snapshot_cannot_mix_item_rows_and_new_global_head(self):
        item, _, _ = self.create_item()
        writer = HouseContinuityV12LocalStore(self.root, synthetic_only=True)
        try:
            revised = deepcopy(item)
            revised.update(
                {
                    "revision": 2,
                    "base_event_id": self.event_id(),
                    "idempotency_key": "snapshot-race-revise",
                    "updated_at": "2026-07-29T00:00:00.000Z",
                    "summary": "Committed concurrently after item read.",
                }
            )
            revised["content_sha256"] = canonical_sha256(
                {
                    "item_kind": revised["item_kind"],
                    "scope": {
                        "scope_kind": revised["scope_kind"],
                        "room_id": revised["room_id"],
                        "project_id": revised["project_id"],
                        "thread_id": revised["thread_id"],
                    },
                    "summary": revised["summary"],
                    "kind_payload": revised["kind_payload"],
                }
            )
            revised["authorship_evidence_refs"][0][
                "content_sha256"
            ] = revised["content_sha256"]
            event = writer.prepare_item_event(
                event_id=revised["base_event_id"],
                event_kind="revise",
                next_item=revised,
                expected_revision=1,
                actor_kind="solen_explicit",
                actor_ref="house_talk_continuity_authorship_intent_v1",
                idempotency_key=revised["idempotency_key"],
                command_sha256=self.command_hash("snapshot-race"),
                created_at=revised["updated_at"],
            )
            projection = self.store.read_projection(
                now="2026-07-29T00:00:00.000Z",
                room_id=item["room_id"],
                project_id=item["project_id"],
                thread_id=item["thread_id"],
                after_items_read_for_test=lambda: writer.apply_item_event(
                    event, revised
                ),
            )
            self.assertEqual(1, projection["snapshot_global_event_sequence"])
            self.assertEqual(1, projection["selected"][0]["item"]["revision"])
            self.assertEqual(2, writer.read_item(item["item_id"])["revision"])
        finally:
            writer.close()

    def test_atomic_bound_projection_cannot_mix_binding_and_item_head(self):
        binding = deepcopy(literal.SCOPE_BINDING)
        binding.update(
            {
                "binding_revision": 1,
                "predecessor_room_id": None,
                "binding_source": "explicit_thread",
                "idempotency_key": "bound-snapshot-create",
            }
        )
        binding_event = self.store.prepare_binding_event(
            event_id=self.event_id(),
            event_kind="bind",
            to_binding=binding,
            expected_binding_revision=0,
            actor_kind="astel_explicit",
            actor_ref="house_continuity_astel_explicit_command_v1",
            idempotency_key=binding["idempotency_key"],
            command_sha256=self.command_hash("bound-snapshot-create"),
            created_at=binding["created_at"],
        )
        self.store.apply_binding_event(binding_event)
        item, _, _ = self.create_item(label="bound-snapshot-item")
        writer = HouseContinuityV12LocalStore(self.root, synthetic_only=True)
        try:
            rebound = deepcopy(binding)
            rebound.update(
                {
                    "binding_revision": 2,
                    "project_id": "cws_prj_" + "f" * 32,
                    "thread_id": None,
                    "binding_source": "explicit_project",
                    "idempotency_key": "bound-snapshot-rebind",
                    "updated_at": "2026-07-29T00:01:00.000Z",
                }
            )
            rebound_event = writer.prepare_binding_event(
                event_id=self.event_id(),
                event_kind="rebind",
                to_binding=rebound,
                expected_binding_revision=1,
                actor_kind="astel_explicit",
                actor_ref="house_continuity_astel_explicit_command_v1",
                idempotency_key=rebound["idempotency_key"],
                command_sha256=self.command_hash("bound-snapshot-rebind"),
                created_at=rebound["updated_at"],
            )
            result = self.store.read_bound_projection(
                now="2026-07-29T00:00:00.000Z",
                room_id=binding["room_id"],
                after_binding_read_for_test=lambda: writer.apply_binding_event(
                    rebound_event
                ),
            )
            self.assertEqual(1, result["binding"]["binding_revision"])
            self.assertEqual(
                [item["item_id"]],
                [
                    entry["item"]["item_id"]
                    for entry in result["projection"]["selected"]
                ],
            )
            self.assertEqual(
                2,
                result["projection"]["snapshot_global_event_sequence"],
            )
            self.assertEqual(
                2,
                writer.read_binding(binding["room_id"])["binding_revision"],
            )
        finally:
            writer.close()

    def test_sqlite_lock_and_uniqueness_fail_with_body_free_codes(self):
        item, _, _ = self.create_item()
        revised, event = self.evolve(
            item,
            event_kind="confirm",
            at="2026-07-29T00:00:00.000Z",
        )
        locker = sqlite3.connect(str(self.store.database_path), timeout=0.1)
        try:
            locker.execute("BEGIN IMMEDIATE")
            self.assert_store_error(
                "sqlite_write_locked",
                self.store.apply_item_event,
                event,
                revised,
            )
            locker.rollback()
        finally:
            locker.close()

        duplicate_item = deepcopy(literal.WORKING_SET_ITEM)
        duplicate_item.update(
            {
                "item_id": "cws_item_" + ("5" * 32),
                "creation_seed_sha256": canonical_sha256("duplicate-item-seed"),
                "base_event_id": item["base_event_id"],
                "idempotency_key": "duplicate-event-id",
            }
        )
        duplicate = self.store.prepare_item_event(
            event_id=duplicate_item["base_event_id"],
            event_kind="create",
            next_item=duplicate_item,
            expected_revision=0,
            actor_kind="solen_explicit",
            actor_ref="house_talk_continuity_authorship_intent_v1",
            idempotency_key=duplicate_item["idempotency_key"],
            command_sha256=self.command_hash("duplicate-event-id"),
            created_at=duplicate_item["created_at"],
        )
        self.assert_store_error(
            "transactional_identity_conflict",
            self.store.apply_item_event,
            duplicate,
            duplicate_item,
        )

    def test_coverage_outbox_collision_registry_and_replay(self):
        safe = gate0.coverage_fixture("solen_no_semantic_delta")
        self.assertEqual(safe, self.store.put_unit_coverage(safe))
        self.assertEqual(safe, self.store.put_unit_coverage(safe))

        pending = deepcopy(gate0.OUTBOX_STATE_FIXTURES["prepared_waiting_visible"])
        self.store.put_outbox_bundle(
            pending, transition_event="atomic_prepare_before_visible"
        )
        visible = deepcopy(
            gate0.OUTBOX_STATE_FIXTURES["visible_released_waiting_unit"]
        )
        self.store.put_outbox_bundle(
            visible, transition_event="visible_released"
        )
        ready = deepcopy(gate0.OUTBOX_STATE_FIXTURES["ready_to_apply"])
        self.store.put_outbox_bundle(ready, transition_event="exact_unit_bound")
        applying = deepcopy(gate0.OUTBOX_STATE_FIXTURES["applying"])
        self.store.put_outbox_bundle(applying, transition_event="lease")
        applied = deepcopy(gate0.OUTBOX_STATE_FIXTURES["applied"])
        self.store.put_outbox_bundle(
            applied, transition_event="all_receipts_committed"
        )

        self.store.register_creation_seed(
            "cwcap_" + ("a" * 32),
            "a" * 64,
            entity_kind="capability",
            created_at="2026-07-28T00:00:00.000Z",
        )
        self.assert_store_error(
            "creation_seed_collision",
            self.store.register_creation_seed,
            "cwcap_" + ("a" * 32),
            "b" * 64,
            entity_kind="capability",
            created_at="2026-07-28T00:00:00.000Z",
        )
        self.assertTrue(self.store.doctor()["replay_exact"])

    def test_restart_replay_and_chain_corruption_fail_closed(self):
        self.create_item()
        database_path = self.store.database_path
        self.store.close()
        self.store = HouseContinuityV12LocalStore(
            self.root, synthetic_only=True
        )
        self.assertTrue(self.store.doctor()["replay_exact"])
        self.store.close()
        connection = sqlite3.connect(str(database_path))
        try:
            row = connection.execute(
                "SELECT global_sequence,event_json FROM events LIMIT 1"
            ).fetchone()
            event = __import__("json").loads(row[1])
            event["global_event_sha256"] = "0" * 64
            connection.execute(
                "UPDATE events SET event_json=? WHERE global_sequence=?",
                (__import__("json").dumps(event), row[0]),
            )
            connection.commit()
        finally:
            connection.close()
        self.store = HouseContinuityV12LocalStore(
            self.root, synthetic_only=True
        )
        with self.assertRaises(HouseContinuityV12ContractError):
            self.store.doctor()

    def test_store_identity_is_pinned_and_missing_or_mismatched_meta_fails(self):
        for mutation, expected in (
            (
                "DELETE FROM store_meta WHERE key='store_id'",
                "store_metadata_missing",
            ),
            (
                "UPDATE store_meta SET value='wrong' WHERE key='schema_version'",
                "store_schema_version_mismatch",
            ),
            (
                "UPDATE store_meta SET value='invalid-store-id'"
                " WHERE key='store_id'",
                "store_id_invalid",
            ),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory(
                prefix="house-continuity-gate1-meta-"
            ) as root:
                store = HouseContinuityV12LocalStore(
                    root, synthetic_only=True
                )
                store_id = store.store_id
                self.assertTrue(store_id.startswith("cws_store_"))
                store.close()
                connection = sqlite3.connect(
                    str(
                        Path(root)
                        / "house_continuity_v1_2_local.sqlite3"
                    )
                )
                try:
                    connection.execute(mutation)
                    connection.commit()
                finally:
                    connection.close()
                self.assert_store_error(
                    expected,
                    HouseContinuityV12LocalStore,
                    root,
                    synthetic_only=True,
                )

    def test_pre_lineage_store_read_does_not_mutate_schema(self):
        database_path = self.store.database_path
        self.store.close()
        connection = sqlite3.connect(str(database_path))
        try:
            connection.execute("DROP TABLE projection_lineage")
            connection.commit()
            before = connection.execute(
                "SELECT name,sql FROM sqlite_master"
                " WHERE type='table' ORDER BY name"
            ).fetchall()
        finally:
            connection.close()

        self.store = HouseContinuityV12LocalStore(
            self.root, synthetic_only=True
        )
        self.assertEqual([], self.store.read_projection_lineage())
        self.assertEqual(0, self.store.doctor()["projection_lineage_count"])
        self.store.close()
        connection = sqlite3.connect(str(database_path))
        try:
            after = connection.execute(
                "SELECT name,sql FROM sqlite_master"
                " WHERE type='table' ORDER BY name"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(before, after)
        self.store = HouseContinuityV12LocalStore(
            self.root, synthetic_only=True
        )

    def test_doctor_checks_event_indexes_history_seeds_and_receipts(self):
        corruptions = {
            "event_index": (
                "UPDATE events SET owner_id='cws_item_"
                + ("f" * 32)
                + "'",
                "event_index_json_mismatch",
            ),
            "history_index": (
                "UPDATE item_history SET revision=99",
                "item_history_index_json_mismatch",
            ),
            "item_index": (
                "UPDATE items SET revision=99",
                "item_index_json_mismatch",
            ),
            "event_seed": (
                "UPDATE creation_seeds SET creation_seed_sha256='"
                + ("f" * 64)
                + "' WHERE entity_kind='event'",
                "event_creation_seed_binding_mismatch",
            ),
            "idempotency_receipt": (
                "UPDATE idempotency_receipts SET command_sha256='"
                + ("f" * 64)
                + "'",
                "idempotency_receipt_mismatch",
            ),
        }
        for label, (statement, expected) in corruptions.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                prefix=f"house-continuity-gate1-doctor-{label}-"
            ) as root:
                store = HouseContinuityV12LocalStore(
                    root, synthetic_only=True
                )
                item = deepcopy(literal.WORKING_SET_ITEM)
                event = store.prepare_item_event(
                    event_id=item["base_event_id"],
                    event_kind="create",
                    next_item=item,
                    expected_revision=0,
                    actor_kind=item["authorship_kind"],
                    actor_ref=item["command_owner"],
                    idempotency_key=item["idempotency_key"],
                    command_sha256=self.command_hash(
                        f"doctor-{label}-create"
                    ),
                    created_at=item["created_at"],
                )
                store.apply_item_event(event, item)
                store._connection.execute(statement)
                store._connection.commit()
                self.assert_store_error(expected, store.doctor)
                store.close()

    def test_global_item_and_binding_chain_corruption_each_fail_closed(self):
        for owner, hash_field in (
            ("global", "global_event_sha256"),
            ("item", "item_event_sha256"),
            ("binding", "binding_event_sha256"),
        ):
            with self.subTest(owner=owner), tempfile.TemporaryDirectory(
                prefix=f"house-continuity-gate1-{owner}-"
            ) as root:
                store = HouseContinuityV12LocalStore(
                    root, synthetic_only=True
                )
                item = deepcopy(literal.WORKING_SET_ITEM)
                create = store.prepare_item_event(
                    event_id=item["base_event_id"],
                    event_kind="create",
                    next_item=item,
                    expected_revision=0,
                    actor_kind="solen_explicit",
                    actor_ref=item["command_owner"],
                    idempotency_key=item["idempotency_key"],
                    command_sha256=self.command_hash(f"{owner}-create"),
                    created_at=item["created_at"],
                )
                store.apply_item_event(create, item)
                target_sequence = 1
                if owner == "binding":
                    binding = deepcopy(literal.SCOPE_BINDING)
                    binding.update(
                        {
                            "binding_revision": 1,
                            "predecessor_room_id": None,
                            "binding_source": "explicit_thread",
                            "idempotency_key": "chain-binding",
                            "created_at": "2026-07-29T00:00:00.000Z",
                            "updated_at": "2026-07-29T00:00:00.000Z",
                        }
                    )
                    binding_event = store.prepare_binding_event(
                        event_id="cws_evt_" + ("d" * 32),
                        event_kind="bind",
                        to_binding=binding,
                        expected_binding_revision=0,
                        actor_kind="astel_explicit",
                        actor_ref=(
                            "house_continuity_astel_explicit_command_v1"
                        ),
                        idempotency_key=binding["idempotency_key"],
                        command_sha256=self.command_hash("chain-binding"),
                        created_at=binding["created_at"],
                    )
                    store.apply_binding_event(binding_event)
                    target_sequence = 2
                database_path = store.database_path
                store.close()
                connection = sqlite3.connect(str(database_path))
                try:
                    row = connection.execute(
                        "SELECT event_json FROM events"
                        " WHERE global_sequence=?",
                        (target_sequence,),
                    ).fetchone()
                    event = __import__("json").loads(row[0])
                    event[hash_field] = "0" * 64
                    connection.execute(
                        "UPDATE events SET event_json=?"
                        " WHERE global_sequence=?",
                        (
                            __import__("json").dumps(event),
                            target_sequence,
                        ),
                    )
                    connection.commit()
                finally:
                    connection.close()
                with HouseContinuityV12LocalStore(
                    root, synthetic_only=True
                ) as reopened:
                    with self.assertRaises(
                        HouseContinuityV12ContractError
                    ):
                        reopened.doctor()

    def test_raw_private_shapes_and_legacy_joint_owner_fail_closed(self):
        raw = deepcopy(literal.WORKING_SET_ITEM)
        raw["raw_transcript"] = "synthetic forbidden sentinel"
        with self.assertRaises(HouseContinuityV12ContractError):
            self.store.prepare_item_event(
                event_id=raw["base_event_id"],
                event_kind="create",
                next_item=raw,
                expected_revision=0,
                actor_kind="solen_explicit",
                actor_ref=raw["command_owner"],
                idempotency_key=raw["idempotency_key"],
                command_sha256=self.command_hash("raw"),
                created_at=raw["created_at"],
            )
        legacy = deepcopy(literal.WORKING_SET_ITEM)
        legacy.pop("authorship_evidence_refs")
        legacy["schema_version"] = "house_continuity_working_set_item_v1_1"
        compatible = self.store.read_legacy_v1_1_item(legacy)
        self.assertFalse(compatible["provider_visible_eligible"])
        legacy.update(
            {
                "authorship_kind": "joint_explicit",
                "command_owner": "house_talk_continuity_authorship_intent_v1",
            }
        )
        self.assert_store_error(
            "legacy_joint_solen_owner_invalid",
            self.store.read_legacy_v1_1_item,
            legacy,
        )


if __name__ == "__main__":
    unittest.main()
