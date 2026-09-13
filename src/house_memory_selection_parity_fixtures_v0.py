"""Synthetic, raw-free Gate 3 fixture builders."""

from __future__ import annotations

from typing import Any, Sequence

import house_memory_durable_event_contract_v0 as durable
import house_memory_curated_event_contract_v0 as events
import house_memory_durable_event_contract_v0 as event_dispatch
import house_memory_selection_contract_v0 as contract


def opaque(label: str) -> str:
    return durable.synthetic_hash(label)


class ProjectionFixture:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def add_record(
        self,
        label: str,
        *,
        core: bool = False,
        blocker_flags: Sequence[str] = (),
        default_eligible: bool = True,
        standing_eligible: bool = False,
        authority_scope_code: str = "reviewed_memory",
        audience_scope_code: str = "astel_solen_private",
        explicit_eligible: bool = True,
        manual_eligible: bool = True,
        exact_eligible: bool = True,
    ) -> tuple[str, str]:
        memory_ref = opaque(label)
        version_ref = opaque(f"{label}-v1")
        capabilities = []
        if explicit_eligible:
            capabilities.append("explicit_search_eligible")
        if manual_eligible:
            capabilities.append("manual_lookup_eligible")
        if exact_eligible:
            capabilities.append("exact_recall_eligible")
        if default_eligible:
            capabilities.append("default_surfacing_eligible")
        if standing_eligible:
            capabilities.append("standing_footing_eligible")
        self._append(
            action_code="record_observed",
            memory_ref_hash=memory_ref,
            canonical_record_version_hash=version_ref,
            authority_scope_code=authority_scope_code,
            audience_scope_code=audience_scope_code,
            blocker_flags=list(blocker_flags),
            safe_capability_flags=capabilities,
        )
        if core:
            self._append(
                action_code="set_core",
                memory_ref_hash=memory_ref,
                canonical_record_version_hash=version_ref,
                authority_scope_code=authority_scope_code,
                actor_type="house_backend",
                actor_ref_hash=opaque("backend"),
                payload={
                    "payload_schema_version": events.CORE_PAYLOAD_SCHEMA_VERSION,
                    "requested_by_actor_type": "astel",
                    "requested_by_actor_ref_hash": opaque("requester"),
                    "request_intent_hash": opaque(f"{label}-request"),
                    "approved_by_actor_type": "solen",
                    "approved_by_actor_ref_hash": opaque("approver"),
                    "approval_intent_hash": opaque(f"{label}-approval"),
                    "confirmed": True,
                },
            )
        return memory_ref, version_ref

    def add_relation(
        self,
        left: tuple[str, str],
        right: tuple[str, str],
        *,
        relation_type: str = "complements",
        strength_milli: int = 800,
    ) -> str:
        relation_ref = events.compute_relation_ref(
            left_memory_ref_hash=left[0], right_memory_ref_hash=right[0], relation_type=relation_type,
            participant_scope_code="astel_solen", authority_scope_code="reviewed_memory",
            authority_owner_code="astel_solen", audience_scope_code="astel_solen_private",
        )
        self._append(
            action_code="relation_asserted", memory_ref_hash=left[0],
            canonical_record_version_hash=left[1],
            payload={
                "payload_schema_version": events.RELATION_PAYLOAD_SCHEMA_VERSION,
                "relation_ref_hash": relation_ref,
                "left_memory_ref_hash": left[0],
                "left_canonical_record_version_hash": left[1],
                "right_memory_ref_hash": right[0],
                "right_canonical_record_version_hash": right[1],
                "relation_type": relation_type,
                "strength_milli": strength_milli,
                "evidence_ref_hash": opaque(f"relation-evidence-{len(self.events)}"),
            },
        )
        return relation_ref

    def remove_core(self, record: tuple[str, str]) -> None:
        self._append(
            action_code="remove_core", memory_ref_hash=record[0],
            canonical_record_version_hash=record[1], actor_type="house_backend",
            actor_ref_hash=opaque("backend"),
            payload={
                "payload_schema_version": events.CORE_PAYLOAD_SCHEMA_VERSION,
                "requested_by_actor_type": "astel",
                "requested_by_actor_ref_hash": opaque("requester"),
                "request_intent_hash": opaque(f"{record[0]}-remove-request"),
                "approved_by_actor_type": "solen",
                "approved_by_actor_ref_hash": opaque("approver"),
                "approval_intent_hash": opaque(f"{record[0]}-remove-approval"),
                "confirmed": True,
            },
        )

    def add_proposal(self, primary: tuple[str, str], comparison: tuple[str, str]) -> str:
        action_ref = opaque(f"action-{len(self.events) + 1}")
        candidate_ref = opaque(f"proposal-candidate-{len(self.events) + 1}")
        proposal_ref = events.compute_proposal_ref(
            action_ref_hash=action_ref, proposal_kind="merge_candidate",
            primary_memory_ref_hash=primary[0], primary_canonical_record_version_hash=primary[1],
            comparison_memory_ref_hash=comparison[0],
            comparison_canonical_record_version_hash=comparison[1], candidate_ref_hash=candidate_ref,
        )
        self._append(
            action_code="evolution_proposal_created", action_ref_hash=action_ref,
            memory_ref_hash=primary[0], canonical_record_version_hash=primary[1],
            payload={
                "payload_schema_version": events.PROPOSAL_PAYLOAD_SCHEMA_VERSION,
                "proposal_ref_hash": proposal_ref,
                "proposal_kind": "merge_candidate",
                "proposal_basis": "synthetic_fixture",
                "primary_memory_ref_hash": primary[0],
                "primary_canonical_record_version_hash": primary[1],
                "comparison_memory_ref_hash": comparison[0],
                "comparison_canonical_record_version_hash": comparison[1],
                "candidate_ref_hash": candidate_ref,
                "proposal_origin_action_ref_hash": action_ref,
            },
        )
        return proposal_ref

    def _append(self, **overrides: Any) -> dict[str, Any]:
        sequence = len(self.events) + 1
        candidate = {
            "event_sequence": sequence,
            "previous_event_id": self.events[-1]["event_id"] if self.events else "",
            "occurred_at": f"2026-07-10T14:{sequence // 60:02d}:{sequence % 60:02d}.000000Z",
            "action_code": "record_observed",
            "memory_ref_hash": opaque(f"record-{sequence}"),
            "canonical_record_version_hash": opaque(f"version-{sequence}"),
            "actor_type": "astel",
            "actor_ref_hash": opaque("actor-astel"),
            "action_ref_hash": opaque(f"action-{sequence}"),
            "participant_scope_code": "astel_solen",
            "authority_scope_code": "reviewed_memory",
            "authority_owner_code": "astel_solen",
            "audience_scope_code": "astel_solen_private",
            "reason_code": "synthetic_fixture",
            "payload": {"payload_schema_version": events.OBSERVATION_PAYLOAD_SCHEMA_VERSION},
        }
        candidate.update(overrides)
        event = events.build_event(**candidate)
        self.events.append(event)
        return event

    def projection(self) -> dict[str, Any]:
        return event_dispatch.replay_events(self.events)


def nomination(
    record: tuple[str, str],
    *,
    evidence_code: str = "none",
    strength: int = 0,
    scope: str = "both",
    channel: str = "synthetic_fixture",
) -> dict[str, Any]:
    return {
        "memory_ref_hash": record[0],
        "canonical_record_version_hash": record[1],
        "selection_scope_code": scope,
        "source_channel_code": channel,
        "evidence_code": evidence_code,
        "evidence_strength_milli": strength,
    }


def request(
    nominations: Sequence[dict[str, Any]], *, mode: str = "ordinary_talk",
    capability: str = "ambient_detail", cap: int = 3, fanout: int = 4,
    audiences: Sequence[str] = ("astel_solen_private", "astel_only"),
    exports: Sequence[str] = ("private_house",),
) -> dict[str, Any]:
    return {
        "schema_version": contract.REQUEST_SCHEMA_VERSION,
        "request_ref_hash": opaque(f"request-{mode}-{len(nominations)}"),
        "mode": mode,
        "requested_capability_code": capability,
        "allowed_audience_scope_codes": list(audiences),
        "allowed_export_scope_codes": list(exports),
        "max_selected": cap,
        "max_relation_fanout": fanout,
        "nominations": list(nominations),
    }


__all__ = ["ProjectionFixture", "nomination", "opaque", "request"]
