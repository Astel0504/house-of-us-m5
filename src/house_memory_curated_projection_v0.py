from __future__ import annotations

from typing import Any, Mapping, Sequence

import house_memory_durable_event_contract_v0 as durable
import house_memory_curated_event_contract_v0 as curated


PROJECTION_SCHEMA_VERSION = "house_memory_curated_projection_v0"
MUTATION_FLAGS = {
    "canonical_record_changed": False,
    "automatic_supersession_made": False,
    "memory_vault_record_mutation_made": False,
    "writeback_candidate_mutation_made": False,
}


def _record_from_event(event: Mapping[str, Any], prior: Mapping[str, Any] | None) -> dict[str, Any]:
    blockers = set(event["blocker_flags"])
    if not event["provenance_present"]:
        blockers.add("missing_source_or_provenance_pointer")
    capabilities = set(event["safe_capability_flags"])
    blocked = bool(blockers)
    prior_status = prior["core_status"] if prior is not None else "normal_reviewed"
    prior_core = prior_status == "core"
    identity_changed = prior is not None and (
        prior["canonical_record_version_hash"] != event["canonical_record_version_hash"]
        or _scope_tuple(prior) != (
            event["participant_scope_code"], event["authority_scope_code"],
            event.get("authority_owner_code", "synthetic_test"), event["audience_scope_code"],
        )
    )
    core_resolution_required = prior_core and (
        identity_changed or bool(prior.get("core_resolution_required"))
    )
    authority_owner = event.get("authority_owner_code", "synthetic_test")
    base_standing = not blocked and "standing_footing_eligible" in capabilities
    return {
        "memory_ref_hash": event["memory_ref_hash"],
        "canonical_record_version_hash": event["canonical_record_version_hash"],
        "participant_scope_code": event["participant_scope_code"],
        "authority_scope_code": event["authority_scope_code"],
        "authority_owner_code": authority_owner,
        "audience_scope_code": event["audience_scope_code"],
        "status_code": event["status_code"],
        "review_state_code": event["review_state_code"],
        "provenance_present": event["provenance_present"],
        "blocker_flags": sorted(blockers),
        "safe_capability_flags": list(event["safe_capability_flags"]),
        "core_status": prior_status,
        "lifecycle_status": prior.get("lifecycle_status", "active") if prior is not None else "active",
        "core_resolution_required": core_resolution_required,
        "base_standing_footing_eligible": base_standing,
        "standing_footing_eligible": (
            prior_status != "quiet"
            and (base_standing or (prior_core and not core_resolution_required and not blocked))
        ),
        "default_surfacing_eligible": (
            prior_status != "quiet"
            and "default_surfacing_eligible" in capabilities
            and not blocked
        ),
        "explicit_search_eligible": "explicit_search_eligible" in capabilities and not blocked,
        "manual_lookup_eligible": "manual_lookup_eligible" in capabilities and not blocked,
        "exact_recall_eligible": "exact_recall_eligible" in capabilities and not blocked,
        "last_event_id": event["event_id"],
        "last_reason_code": event["reason_code"],
        "event_count": int(prior["event_count"]) + 1 if prior else 1,
    }


def _scope_tuple(value: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        value["participant_scope_code"], value["authority_scope_code"],
        value["authority_owner_code"], value["audience_scope_code"],
    )


def _require_current_record(
    records: Mapping[str, Mapping[str, Any]], memory_ref: str, version_hash: str
) -> Mapping[str, Any]:
    record = records.get(memory_ref)
    if record is None:
        raise durable.HouseMemoryDurableEventError("missing_semantic_endpoint", "Semantic action endpoint does not exist.")
    if record["canonical_record_version_hash"] != version_hash:
        raise durable.HouseMemoryDurableEventError("stale_endpoint_version", "Semantic action endpoint version is stale.")
    return record


def _refresh_proposal_state(proposal: dict[str, Any], records: Mapping[str, Mapping[str, Any]]) -> None:
    endpoints = [records[proposal["primary_memory_ref_hash"]], records[proposal["comparison_memory_ref_hash"]]]
    proposal["core_involved"] = any(record["core_status"] == "core" for record in endpoints)
    proposal["core_resolution_required"] = any(record["core_resolution_required"] for record in endpoints)
    if proposal["state"] in {"withdrawn", "stale"}:
        return
    proposal["state"] = "check_needed" if (
        proposal["core_involved"]
        or proposal["core_resolution_required"]
        or proposal["proposal_blocker_flags"]
        or any(record["blocker_flags"] for record in endpoints)
    ) else "proposed"


def _refresh_touching_relations(
    memory_ref: str, relations: dict[str, dict[str, Any]], records: Mapping[str, Mapping[str, Any]]
) -> None:
    for relation in relations.values():
        if relation["state"] != "active" or memory_ref not in {
            relation["left_memory_ref_hash"], relation["right_memory_ref_hash"]
        }:
            continue
        left = records[relation["left_memory_ref_hash"]]
        right = records[relation["right_memory_ref_hash"]]
        relation["eligible_for_expansion"] = not left["blocker_flags"] and not right["blocker_flags"]


def _stale_touching(
    memory_ref: str, relations: dict[str, dict[str, Any]], proposals: dict[str, dict[str, Any]],
    resolutions: dict[str, dict[str, Any]] | None = None,
) -> None:
    for relation in relations.values():
        if relation["state"] == "active" and memory_ref in {
            relation["left_memory_ref_hash"], relation["right_memory_ref_hash"]
        }:
            relation["state"] = "stale_endpoint_version"
            relation["eligible_for_expansion"] = False
    for proposal in proposals.values():
        if proposal["state"] in {"proposed", "check_needed"} and memory_ref in {
            proposal["primary_memory_ref_hash"], proposal["comparison_memory_ref_hash"]
        }:
            proposal["state"] = "stale"
    for resolution in (resolutions or {}).values():
        if resolution["state"] in {"active", "check_needed"} and memory_ref in {
            resolution["primary_memory_ref_hash"], resolution["comparison_memory_ref_hash"]
        }:
            resolution["state"] = "stale_endpoint_version"


def replay_mixed_events(
    events: Sequence[Mapping[str, Any]], *, expected_cursor: str | None = None
) -> dict[str, Any]:
    records: dict[str, dict[str, Any]] = {}
    relations: dict[str, dict[str, Any]] = {}
    proposals: dict[str, dict[str, Any]] = {}
    resolutions: dict[str, dict[str, Any]] = {}
    seen_action_refs: set[str] = set()
    v1_action_refs: set[str] = set()
    previous_id = ""
    chain_hashes: list[str] = []

    for expected_sequence, raw in enumerate(events, start=1):
        event = durable.normalize_event(raw)
        if event["event_sequence"] != expected_sequence or event["previous_event_id"] != previous_id:
            raise durable.HouseMemoryDurableEventError(
                "invalid_replay_order", "Replay events must form one contiguous canonical chain."
            )
        previous_id = event["event_id"]
        chain_hashes.append(previous_id)
        is_v1 = event["schema_version"] == curated.EVENT_SCHEMA_VERSION
        action_ref = event["action_ref_hash"]
        if (is_v1 and action_ref in seen_action_refs) or (not is_v1 and action_ref in v1_action_refs):
            raise durable.HouseMemoryDurableEventError(
                "duplicate_action_ref", "An action ref used by v1 must be unique across the mixed chain."
            )
        seen_action_refs.add(action_ref)
        if is_v1:
            v1_action_refs.add(action_ref)
        action = event["action_code"]

        if action == "metadata_repair_reconciled":
            prior = records.get(event["memory_ref_hash"])
            if prior is None:
                raise durable.HouseMemoryDurableEventError(
                    "record_missing", "Metadata repair reconciliation requires an existing record."
                )
            payload = event["payload"]
            if prior["canonical_record_version_hash"] != payload["prior_canonical_record_version_hash"]:
                raise durable.HouseMemoryDurableEventError(
                    "repair_prior_version_mismatch", "Metadata repair prior version is not current."
                )
            if _scope_tuple(prior) != (
                event["participant_scope_code"], event["authority_scope_code"],
                event.get("authority_owner_code", "synthetic_test"), event["audience_scope_code"],
            ):
                raise durable.HouseMemoryDurableEventError(
                    "semantic_scope_mismatch", "Repair reconciliation scope differs from its record."
                )
            semantic_fields = {
                "status_code": event["status_code"],
                "review_state_code": event["review_state_code"],
                "provenance_present": event["provenance_present"],
                "blocker_flags": event["blocker_flags"],
                "safe_capability_flags": event["safe_capability_flags"],
            }
            if any(prior[field] != value for field, value in semantic_fields.items()):
                raise durable.HouseMemoryDurableEventError(
                    "repair_semantic_state_mismatch",
                    "Metadata repair reconciliation cannot change durable semantic state.",
                )
            reconciled = dict(prior)
            reconciled.update({
                "canonical_record_version_hash": event["canonical_record_version_hash"],
                "last_event_id": event["event_id"],
                "last_reason_code": event["reason_code"],
                "event_count": int(prior["event_count"]) + 1,
            })
            records[event["memory_ref_hash"]] = reconciled
            _stale_touching(event["memory_ref_hash"], relations, proposals, resolutions)
            continue

        if action in {"record_observed", "record_version_observed"}:
            prior = records.get(event["memory_ref_hash"])
            if is_v1 and action == "record_observed" and prior is not None:
                raise durable.HouseMemoryDurableEventError(
                    "record_already_exists", "record_observed only creates an absent record."
                )
            if is_v1 and action == "record_version_observed" and prior is None:
                raise durable.HouseMemoryDurableEventError(
                    "record_missing", "record_version_observed only updates an existing record."
                )
            identity_changed = prior is not None and (
                prior["canonical_record_version_hash"] != event["canonical_record_version_hash"]
                or _scope_tuple(prior) != (
                    event["participant_scope_code"], event["authority_scope_code"],
                    event.get("authority_owner_code", "synthetic_test"), event["audience_scope_code"],
                )
            )
            records[event["memory_ref_hash"]] = _record_from_event(event, prior)
            if identity_changed:
                _stale_touching(event["memory_ref_hash"], relations, proposals, resolutions)
            else:
                _refresh_touching_relations(event["memory_ref_hash"], relations, records)
                for proposal in proposals.values():
                    if event["memory_ref_hash"] in {
                        proposal["primary_memory_ref_hash"], proposal["comparison_memory_ref_hash"]
                    }:
                        _refresh_proposal_state(proposal, records)
            continue

        record = _require_current_record(records, event["memory_ref_hash"], event["canonical_record_version_hash"])
        independent_authority_envelope = (
            action == "reviewed_evolution_applied"
            or (action in {"relation_asserted", "relation_retracted"}
                and event["payload"].get("payload_schema_version") == curated.RELATION_PAYLOAD_V2_SCHEMA_VERSION)
        )
        if not independent_authority_envelope and _scope_tuple(record) != _scope_tuple(event):
            raise durable.HouseMemoryDurableEventError("semantic_scope_mismatch", "Semantic action scope differs from its record.")

        if action in {"set_core", "remove_core"}:
            if record["core_status"] == "quiet":
                raise durable.HouseMemoryDurableEventError(
                    "core_record_quiet", "A quiet record must be restored before a Core action."
                )
            if action == "set_core":
                if not record["provenance_present"]:
                    raise durable.HouseMemoryDurableEventError("core_missing_provenance", "Core requires source provenance.")
                if record["blocker_flags"]:
                    raise durable.HouseMemoryDurableEventError("core_record_blocked", "Blocked records cannot become Core.")
                accepted_authority = (
                    record["authority_scope_code"] == "reviewed_memory"
                    and record["review_state_code"] == "reviewed"
                ) or (
                    record["authority_scope_code"] == "solen_active_memory"
                    and record["review_state_code"] == "standing_consent_active"
                    and record["authority_owner_code"] in {"solen", "house_standing_consent"}
                )
                if record["status_code"] != "approved" or not accepted_authority:
                    raise durable.HouseMemoryDurableEventError("core_authority_invalid", "Core requires accepted memory authority.")
                record["core_status"] = "core"
                record["core_resolution_required"] = False
                record["standing_footing_eligible"] = True
            else:
                record["core_status"] = "normal_reviewed"
                record["core_resolution_required"] = False
                record["standing_footing_eligible"] = record["base_standing_footing_eligible"]
            record["last_event_id"] = event["event_id"]
            record["last_reason_code"] = event["reason_code"]
            record["event_count"] += 1
            for proposal in proposals.values():
                if event["memory_ref_hash"] in {proposal["primary_memory_ref_hash"], proposal["comparison_memory_ref_hash"]}:
                    _refresh_proposal_state(proposal, records)
            continue

        if action in {"quiet", "restore_normal"}:
            if action == "quiet":
                if record["core_status"] == "core" or record["core_resolution_required"]:
                    raise durable.HouseMemoryDurableEventError(
                        "quiet_core_forbidden", "Core or unresolved Core records cannot become quiet."
                    )
                if record["core_status"] != "normal_reviewed":
                    raise durable.HouseMemoryDurableEventError(
                        "quiet_transition_invalid", "Only a normal reviewed record can become quiet."
                    )
                record["core_status"] = "quiet"
                record["lifecycle_status"] = "quiet"
                record["standing_footing_eligible"] = False
                record["default_surfacing_eligible"] = False
            else:
                if record["core_status"] != "quiet":
                    raise durable.HouseMemoryDurableEventError(
                        "restore_normal_transition_invalid", "Only a quiet record can return to normal."
                    )
                record["core_status"] = "normal_reviewed"
                record["lifecycle_status"] = "active"
                record["standing_footing_eligible"] = record["base_standing_footing_eligible"]
                record["default_surfacing_eligible"] = (
                    "default_surfacing_eligible" in record["safe_capability_flags"]
                    and not record["blocker_flags"]
                )
            record["last_event_id"] = event["event_id"]
            record["last_reason_code"] = event["reason_code"]
            record["event_count"] += 1
            continue

        if action in {"automatic_cooling", "automatic_quiet", "lifecycle_wakeup"}:
            payload = event["payload"]
            if record["lifecycle_status"] != payload["prior_lifecycle_state"]:
                raise durable.HouseMemoryDurableEventError(
                    "lifecycle_transition_stale", "Lifecycle transition prior state is stale.")
            protected = set(payload["reason_inputs"]["protected_class_codes"])
            if action == "automatic_cooling":
                if record["core_status"] == "core" or record["core_resolution_required"] or record["blocker_flags"]:
                    raise durable.HouseMemoryDurableEventError(
                        "automatic_cooling_blocked", "Core or check-needed records cannot cool automatically.")
                record["lifecycle_status"] = "cooling"
                record["standing_footing_eligible"] = False
                record["default_surfacing_eligible"] = False
            elif action == "automatic_quiet":
                if (record["core_status"] == "core" or record["core_resolution_required"]
                        or record["blocker_flags"] or protected):
                    raise durable.HouseMemoryDurableEventError(
                        "automatic_quiet_blocked", "Protected or check-needed records cannot quiet automatically.")
                record["lifecycle_status"] = "quiet"
                record["standing_footing_eligible"] = False
                record["default_surfacing_eligible"] = False
            else:
                record["lifecycle_status"] = "active"
                if record["core_status"] == "quiet":
                    # Legacy quiet overloaded the Core axis.  Waking that legacy
                    # state restores its historical normal-reviewed meaning.
                    record["core_status"] = "normal_reviewed"
                record["standing_footing_eligible"] = (
                    record["base_standing_footing_eligible"]
                    or (record["core_status"] == "core" and not record["core_resolution_required"]
                        and not record["blocker_flags"]))
                record["default_surfacing_eligible"] = (
                    "default_surfacing_eligible" in record["safe_capability_flags"]
                    and not record["blocker_flags"])
            record["last_event_id"] = event["event_id"]
            record["last_reason_code"] = event["reason_code"]
            record["event_count"] += 1
            continue

        payload = event["payload"]
        if action == "reviewed_evolution_applied":
            if not event["provenance_present"]:
                raise durable.HouseMemoryDurableEventError(
                    "evolution_missing_provenance", "Reviewed evolution evidence requires provenance."
                )
            primary = _require_current_record(
                records, payload["primary_memory_ref_hash"], payload["primary_applied_version_hash"]
            )
            comparison = _require_current_record(
                records, payload["comparison_memory_ref_hash"], payload["comparison_applied_version_hash"]
            )
            for endpoint in (primary, comparison):
                if (endpoint["participant_scope_code"] != event["participant_scope_code"]
                        or endpoint["audience_scope_code"] != event["audience_scope_code"]):
                    raise durable.HouseMemoryDurableEventError(
                        "evolution_endpoint_scope_mismatch", "Evolution evidence must remain within both endpoint scopes."
                    )
            if payload["approved_by_actor_type"] != event["actor_type"] or payload["approved_by_actor_ref_hash"] != event["actor_ref_hash"]:
                raise durable.HouseMemoryDurableEventError("evolution_approval_actor_mismatch", "Evolution approval actor differs.")
            core_involved = primary["core_status"] == "core" or comparison["core_status"] == "core"
            core_check_needed = bool(core_involved or primary["core_resolution_required"] or comparison["core_resolution_required"])
            if payload["core_involved"] != core_involved or payload["core_check_needed"] != core_check_needed:
                raise durable.HouseMemoryDurableEventError("evolution_core_projection_mismatch", "Evolution Core state differs from endpoints.")
            blockers = sorted(set(event["blocker_flags"]) | set(primary["blocker_flags"]) | set(comparison["blocker_flags"]))
            state = "check_needed" if core_check_needed or blockers or payload["disposition_code"] == "check_needed" else "active"
            if state == "check_needed" and payload["disposition_code"] != "check_needed":
                raise durable.HouseMemoryDurableEventError("evolution_disposition_check_needed", "Blocked evolution must remain check-needed.")
            resolution_ref = payload["resolution_ref_hash"]
            prior_resolution = resolutions.get(resolution_ref)
            projected = {
                **payload,
                "participant_scope_code": event["participant_scope_code"],
                "audience_scope_code": event["audience_scope_code"],
                "resolution_blocker_flags": blockers,
                "state": state,
                "canonical_record_changed": False,
                "core_moved_or_removed": False,
                "selection_expansion_authorized": False,
                "last_event_id": event["event_id"],
            }
            if prior_resolution is not None:
                comparable = {key: value for key, value in projected.items() if key != "last_event_id"}
                prior_comparable = {key: value for key, value in prior_resolution.items() if key != "last_event_id"}
                if comparable != prior_comparable:
                    raise durable.HouseMemoryDurableEventError("evolution_resolution_rewrite", "Evolution resolution identity cannot be rewritten.")
            resolutions[resolution_ref] = projected
            record["last_event_id"] = event["event_id"]
            record["last_reason_code"] = event["reason_code"]
            record["event_count"] += 1
            continue
        if action in {"relation_asserted", "relation_retracted"}:
            if not event["provenance_present"]:
                raise durable.HouseMemoryDurableEventError(
                    "relation_missing_provenance", "Relation actions require provenance."
                )
            if event["actor_type"] == "house_backend":
                raise durable.HouseMemoryDurableEventError(
                    "relation_backend_actor_forbidden", "Relation actions require a participant actor."
                )
            if action == "relation_asserted" and event["blocker_flags"]:
                raise durable.HouseMemoryDurableEventError(
                    "relation_assertion_blocked", "Blocked relation assertions cannot be accepted."
                )
            if event["memory_ref_hash"] not in {
                payload["left_memory_ref_hash"], payload["right_memory_ref_hash"]
            }:
                raise durable.HouseMemoryDurableEventError(
                    "relation_endpoint_mismatch", "Relation envelope must bind one endpoint."
                )
            is_relation_v2 = payload["payload_schema_version"] == curated.RELATION_PAYLOAD_V2_SCHEMA_VERSION
            relation_ref = payload["relation_ref_hash"]
            prior_relation = relations.get(relation_ref)
            stale_v2_retraction = bool(
                is_relation_v2 and action == "relation_retracted" and prior_relation is not None
                and prior_relation.get("state") == "stale_endpoint_version"
            )
            if stale_v2_retraction:
                left = records.get(payload["left_memory_ref_hash"])
                right = records.get(payload["right_memory_ref_hash"])
                if not isinstance(left, Mapping) or not isinstance(right, Mapping):
                    raise durable.HouseMemoryDurableEventError("missing_relation_endpoint", "Relation endpoint is missing.")
            else:
                left = _require_current_record(records, payload["left_memory_ref_hash"], payload["left_canonical_record_version_hash"])
                right = _require_current_record(records, payload["right_memory_ref_hash"], payload["right_canonical_record_version_hash"])
            if is_relation_v2:
                if not ((event["actor_type"] == "astel" and event["authority_scope_code"] == "reviewed_memory"
                         and event["authority_owner_code"] == "astel")
                        or (event["actor_type"] == "solen" and event["authority_scope_code"] == "solen_active_memory"
                            and event["authority_owner_code"] in {"solen", "house_standing_consent"})):
                    raise durable.HouseMemoryDurableEventError("relation_approval_authority_invalid", "Relation approval authority is invalid.")
                if (not stale_v2_retraction and (not left["provenance_present"] or not right["provenance_present"]
                        or left["participant_scope_code"] != payload["participant_scope_code"]
                        or right["participant_scope_code"] != payload["participant_scope_code"]
                        or left["audience_scope_code"] != payload["audience_scope_code"]
                        or right["audience_scope_code"] != payload["audience_scope_code"]
                        or left["authority_scope_code"] != payload["left_authority_scope_code"]
                        or left["authority_owner_code"] != payload["left_authority_owner_code"]
                        or right["authority_scope_code"] != payload["right_authority_scope_code"]
                        or right["authority_owner_code"] != payload["right_authority_owner_code"])):
                    raise durable.HouseMemoryDurableEventError("relation_scope_mismatch", "Relation endpoint footing differs.")
                if action == "relation_asserted" and (left["blocker_flags"] or right["blocker_flags"]):
                    raise durable.HouseMemoryDurableEventError("relation_assertion_blocked", "Blocked endpoints cannot receive a relation.")
            elif _scope_tuple(left) != _scope_tuple(event) or _scope_tuple(right) != _scope_tuple(event):
                raise durable.HouseMemoryDurableEventError("relation_scope_mismatch", "Relation endpoint scopes must match.")
            if (
                action == "relation_asserted"
                and prior_relation is not None
                and prior_relation["state"] == "retracted"
            ):
                raise durable.HouseMemoryDurableEventError(
                    "relation_terminal", "A retracted relation cannot be resurrected."
                )
            if (
                action == "relation_asserted"
                and prior_relation is not None
                and prior_relation["state"] == "active"
                and any(prior_relation.get(key) != value for key, value in payload.items())
            ):
                raise durable.HouseMemoryDurableEventError(
                    "active_relation_rewrite",
                    "An active relation cannot be rewritten by another assertion.",
                )
            if action == "relation_retracted" and relation_ref not in relations:
                raise durable.HouseMemoryDurableEventError("missing_relation", "Retracted relation does not exist.")
            if action == "relation_retracted" and any(
                relations[relation_ref].get(key) != value for key, value in payload.items()
            ):
                raise durable.HouseMemoryDurableEventError(
                    "relation_retraction_mismatch", "Retraction payload must match the asserted relation."
                )
            relations[relation_ref] = {
                **payload,
                "participant_scope_code": event["participant_scope_code"],
                "authority_scope_code": event["authority_scope_code"],
                "authority_owner_code": event["authority_owner_code"],
                "audience_scope_code": event["audience_scope_code"],
                "state": "active" if action == "relation_asserted" else "retracted",
                "eligible_for_expansion": action == "relation_asserted" and not left["blocker_flags"] and not right["blocker_flags"],
                "last_event_id": event["event_id"],
            }
            record["last_event_id"] = event["event_id"]
            record["last_reason_code"] = event["reason_code"]
            record["event_count"] += 1
            continue

        if event["memory_ref_hash"] != payload["primary_memory_ref_hash"]:
            raise durable.HouseMemoryDurableEventError(
                "proposal_primary_endpoint_mismatch", "Proposal envelope must bind the primary endpoint."
            )
        proposal_ref = payload["proposal_ref_hash"]
        if action == "evolution_proposal_withdrawn":
            if proposal_ref not in proposals:
                raise durable.HouseMemoryDurableEventError("missing_proposal", "Withdrawn proposal does not exist.")
            if any(proposals[proposal_ref].get(key) != value for key, value in payload.items()):
                raise durable.HouseMemoryDurableEventError(
                    "proposal_withdrawal_mismatch", "Withdrawal payload must match the created proposal."
                )
            proposals[proposal_ref]["state"] = "withdrawn"
            proposals[proposal_ref]["last_event_id"] = event["event_id"]
        else:
            if not event["provenance_present"]:
                raise durable.HouseMemoryDurableEventError(
                    "proposal_missing_provenance", "Proposal creation requires provenance."
                )
            primary = _require_current_record(
                records, payload["primary_memory_ref_hash"], payload["primary_canonical_record_version_hash"]
            )
            comparison = _require_current_record(
                records, payload["comparison_memory_ref_hash"], payload["comparison_canonical_record_version_hash"]
            )
            if _scope_tuple(primary) != _scope_tuple(event) or _scope_tuple(comparison) != _scope_tuple(event):
                raise durable.HouseMemoryDurableEventError("proposal_scope_mismatch", "Proposal endpoint scopes must match.")
            proposals[proposal_ref] = {
                **payload,
                "participant_scope_code": event["participant_scope_code"],
                "authority_scope_code": event["authority_scope_code"],
                "authority_owner_code": event["authority_owner_code"],
                "audience_scope_code": event["audience_scope_code"],
                "state": "proposed",
                "core_involved": False,
                "core_resolution_required": False,
                "proposal_blocker_flags": list(event["blocker_flags"]),
                **MUTATION_FLAGS,
                "last_event_id": event["event_id"],
            }
            _refresh_proposal_state(proposals[proposal_ref], records)
        record["last_event_id"] = event["event_id"]
        record["last_reason_code"] = event["reason_code"]
        record["event_count"] += 1

    cursor = durable.replay_cursor(len(events), previous_id)
    if expected_cursor is not None and expected_cursor != cursor:
        raise durable.HouseMemoryDurableEventError("replay_cursor_mismatch", "Replay cursor does not match state.")
    return {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "replay_cursor": cursor,
        "event_count": len(events),
        "record_count": len(records),
        "relation_count": len(relations),
        "proposal_count": len(proposals),
        "resolution_count": len(resolutions),
        "last_event_id": previous_id,
        "event_chain_checksum": durable.canonical_sha256(chain_hashes),
        "record_refs": sorted(records),
        "relation_refs": sorted(relations),
        "proposal_refs": sorted(proposals),
        "resolution_refs": sorted(resolutions),
        "records": {key: records[key] for key in sorted(records)},
        "relations": {key: relations[key] for key in sorted(relations)},
        "proposals": {key: proposals[key] for key in sorted(proposals)},
        "resolutions": {key: resolutions[key] for key in sorted(resolutions)},
    }
