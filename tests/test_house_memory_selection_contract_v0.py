from __future__ import annotations

from copy import deepcopy
import unittest

import house_memory_selection_contract_v0 as contract
from house_memory_selection_parity_fixtures_v0 import ProjectionFixture, nomination, opaque, request


class HouseMemorySelectionContractV0Tests(unittest.TestCase):
    def test_quiet_and_cooling_projection_suppress_only_default_paths(self) -> None:
        fixture = ProjectionFixture()
        ref, _ = fixture.add_record("lifecycle-record")
        for lifecycle in ("cooling", "quiet"):
            projection = fixture.projection()
            projection["records"][ref]["lifecycle_status"] = lifecycle
            projection["records"][ref]["base_standing_footing_eligible"] = False
            projection["records"][ref]["standing_footing_eligible"] = False
            projection["records"][ref]["default_surfacing_eligible"] = False
            self.assertIs(projection, contract.validate_projection(projection))
            self.assertTrue(projection["records"][ref]["manual_lookup_eligible"])
            self.assertTrue(projection["records"][ref]["exact_recall_eligible"])

    def test_exact_allowlists_reject_unknown_nested_raw_fields(self) -> None:
        fixture = ProjectionFixture()
        record = fixture.add_record("record")
        valid = request([nomination(record, evidence_code="exact_record_identity", strength=1)])
        self.assertEqual(contract.REQUEST_SCHEMA_VERSION, contract.normalize_request(valid)["schema_version"])
        for mutation in (
            {**valid, "query_text": "forbidden"},
            {**valid, "nominations": [{**valid["nominations"][0], "summary": "forbidden"}]},
            {**valid, "nominations": [{**valid["nominations"][0], "unknown": False}]},
        ):
            with self.assertRaises(contract.HouseMemorySelectionContractError):
                contract.normalize_request(mutation)

    def test_evidence_threshold_normalization_is_explicit(self) -> None:
        fixture = ProjectionFixture()
        record = fixture.add_record("record")
        zero = contract.normalize_nomination(nomination(record, evidence_code="exact_record_identity", strength=0))
        weak_soft = contract.normalize_nomination(nomination(record, evidence_code="soft_lexical", strength=699))
        passing_soft = contract.normalize_nomination(nomination(record, evidence_code="soft_lexical", strength=700))
        self.assertEqual(("none", 0), (zero["evidence_code"], zero["evidence_strength_milli"]))
        self.assertEqual(("none", 0), (weak_soft["evidence_code"], weak_soft["evidence_strength_milli"]))
        self.assertEqual(("soft_lexical", 700), (passing_soft["evidence_code"], passing_soft["evidence_strength_milli"]))
        with self.assertRaises(contract.HouseMemorySelectionContractError) as pool_evidence:
            contract.normalize_nomination(
                nomination(record, evidence_code="exact_record_identity", strength=1000, channel="standing_core")
            )
        self.assertEqual("channel_evidence_mismatch", pool_evidence.exception.error_class)
        standing_none = contract.normalize_nomination(nomination(record, channel="standing_core"))
        self.assertEqual("none", standing_none["evidence_code"])

    def test_bounds_hashes_scopes_and_duplicate_lists_fail_closed(self) -> None:
        fixture = ProjectionFixture()
        record = fixture.add_record("record")
        base = request([nomination(record)])
        bad_values = (
            {**base, "request_ref_hash": "bad"},
            {**base, "max_selected": contract.MAX_SELECTED + 1},
            {**base, "max_relation_fanout": contract.MAX_RELATION_FANOUT_PER_NODE + 1},
            {**base, "allowed_audience_scope_codes": ["astel_only", "astel_only"]},
            {**base, "allowed_export_scope_codes": ["unknown"]},
            {**base, "allowed_export_scope_codes": ["private_house", "group_safe"]},
        )
        for value in bad_values:
            with self.assertRaises(contract.HouseMemorySelectionContractError):
                contract.normalize_request(value)

    def test_input_and_unique_ref_caps_are_order_independent(self) -> None:
        fixture = ProjectionFixture()
        record = fixture.add_record("record")
        too_many = request([nomination(record)] * (contract.MAX_INPUT_NOMINATIONS + 1))
        with self.assertRaises(contract.HouseMemorySelectionContractError) as input_error:
            contract.normalize_request(too_many)
        self.assertEqual("too_many_nominations", input_error.exception.error_class)

        unique = [
            {
                **nomination(record),
                "memory_ref_hash": opaque(f"unique-{index}"),
                "canonical_record_version_hash": opaque(f"unique-{index}-v1"),
            }
            for index in range(contract.MAX_UNIQUE_REFS + 1)
        ]
        with self.assertRaises(contract.HouseMemorySelectionContractError) as ref_error:
            contract.normalize_request(request(unique))
        self.assertEqual("too_many_unique_refs", ref_error.exception.error_class)

    def test_projection_contract_rejects_non_gate2_and_raw_shaped_nested_fields(self) -> None:
        fixture = ProjectionFixture()
        first = fixture.add_record("projection-record")
        second = fixture.add_record("projection-record-two")
        relation_ref = fixture.add_relation(first, second)
        proposal_ref = fixture.add_proposal(first, second)
        projection = fixture.projection()
        self.assertIs(projection, contract.validate_projection(projection))
        with self.assertRaises(contract.HouseMemorySelectionContractError):
            contract.validate_projection({**projection, "raw_body": "x"})
        with self.assertRaises(contract.HouseMemorySelectionContractError):
            contract.validate_projection({"schema_version": "wrong", "records": {}, "relations": {}})
        tampered = []
        wrong_count = deepcopy(projection)
        wrong_count["record_count"] += 1
        tampered.append(wrong_count)
        wrong_refs = deepcopy(projection)
        wrong_refs["record_refs"] = []
        tampered.append(wrong_refs)
        wrong_record_type = deepcopy(projection)
        wrong_record_type["records"][first[0]]["default_surfacing_eligible"] = 1
        tampered.append(wrong_record_type)
        wrong_relation = deepcopy(projection)
        wrong_relation["relations"][relation_ref]["relation_type"] = "unknown"
        tampered.append(wrong_relation)
        raw_proposal = deepcopy(projection)
        raw_proposal["proposals"][proposal_ref]["last_event_id"] = "raw private body text"
        tampered.append(raw_proposal)
        raw_reason = deepcopy(projection)
        raw_reason["records"][first[0]]["last_reason_code"] = "raw_memory_private_detail"
        tampered.append(raw_reason)
        duplicate_blockers = deepcopy(projection)
        duplicate_blockers["records"][first[0]]["blocker_flags"] = [
            "unresolved_contradiction", "unresolved_contradiction"
        ]
        tampered.append(duplicate_blockers)
        unsorted_capabilities = deepcopy(projection)
        unsorted_capabilities["records"][first[0]]["safe_capability_flags"] = [
            "manual_lookup_eligible", "default_surfacing_eligible"
        ]
        tampered.append(unsorted_capabilities)
        duplicate_proposal_blockers = deepcopy(projection)
        duplicate_proposal_blockers["proposals"][proposal_ref]["proposal_blocker_flags"] = [
            "unresolved_contradiction", "unresolved_contradiction"
        ]
        tampered.append(duplicate_proposal_blockers)
        missing_default_capability = deepcopy(projection)
        missing_default_capability["records"][first[0]]["safe_capability_flags"].remove(
            "default_surfacing_eligible"
        )
        tampered.append(missing_default_capability)
        for field in (
            "explicit_search_eligible", "manual_lookup_eligible", "exact_recall_eligible",
            "standing_footing_eligible",
        ):
            mismatch = deepcopy(projection)
            mismatch["records"][first[0]][field] = not mismatch["records"][first[0]][field]
            tampered.append(mismatch)
        invalid_resolution = deepcopy(projection)
        invalid_resolution["records"][first[0]]["core_resolution_required"] = True
        tampered.append(invalid_resolution)
        forged_relation = deepcopy(projection)
        forged_relation_ref = opaque("forged-relation-ref")
        forged_relation["relations"][forged_relation_ref] = forged_relation["relations"].pop(relation_ref)
        forged_relation["relations"][forged_relation_ref]["relation_ref_hash"] = forged_relation_ref
        forged_relation["relation_refs"] = [forged_relation_ref]
        tampered.append(forged_relation)
        reversed_relation = deepcopy(projection)
        relation = reversed_relation["relations"][relation_ref]
        relation["left_memory_ref_hash"], relation["right_memory_ref_hash"] = (
            relation["right_memory_ref_hash"], relation["left_memory_ref_hash"]
        )
        relation["left_canonical_record_version_hash"], relation["right_canonical_record_version_hash"] = (
            relation["right_canonical_record_version_hash"], relation["left_canonical_record_version_hash"]
        )
        tampered.append(reversed_relation)
        forged_relation_eligibility = deepcopy(projection)
        forged_relation_eligibility["relations"][relation_ref]["eligible_for_expansion"] = False
        tampered.append(forged_relation_eligibility)
        forged_proposal = deepcopy(projection)
        forged_proposal_ref = opaque("forged-proposal-ref")
        forged_proposal["proposals"][forged_proposal_ref] = forged_proposal["proposals"].pop(proposal_ref)
        forged_proposal["proposals"][forged_proposal_ref]["proposal_ref_hash"] = forged_proposal_ref
        forged_proposal["proposal_refs"] = [forged_proposal_ref]
        tampered.append(forged_proposal)
        forged_mutation = deepcopy(projection)
        forged_mutation["proposals"][proposal_ref]["canonical_record_changed"] = True
        tampered.append(forged_mutation)
        for value in tampered:
            with self.assertRaises(contract.HouseMemorySelectionContractError):
                contract.validate_projection(value)


if __name__ == "__main__":
    unittest.main()
