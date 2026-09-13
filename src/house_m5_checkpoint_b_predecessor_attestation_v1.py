"""Pure validator for the M5 Batch 1 predecessor attestation.

This is a control-plane contract owner, not a service route, initializer, or
provider client.  It deliberately contains no filesystem or network writes.
The attestation is a hash-bound reference to accepted historical pre-live
evidence; it is never a copy of the historical attempt and it is not a live
authorization.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


SCHEMA_VERSION = "house_m5_checkpoint_b_predecessor_attestation_v1"
ATTESTATION_FILENAME = (
    "HOUSE_M5_CHECKPOINT_B_BATCH1_PREDECESSOR_ATTESTATION_2026-09-06.json"
)
DEFAULT_ATTESTATION_PATH = Path(__file__).with_name(ATTESTATION_FILENAME)

TARGET_BATCH_ID = "m5_checkpoint_b_batch1_20260906_01"
TARGET_MANIFEST_SHA256 = (
    "9c7b9427a12ab41831bffc2b20496964ae69bb9180f6762f6fe6fb58ade58fdf"
)
TARGET_PACKAGE_COMMIT = "93035070863602edc30fad0127fe86df8ff8695b"
TARGET_PACKAGE_TREE = "d4ebad78efe265b5404215c2fed8c4ab603a1a73"
TARGET_WRAPPER_COMMIT = "2f5d28acae2265be57a85d0798e2da8c3787afcc"
TARGET_WRAPPER_TREE = "f599881f9326af60c67d919a2d43ffa33aa909d3"
TARGET_ROW_ORDER = ("B-01.01", "B-01.02", "B-02", "B-03A")
TARGET_ROW_IDENTITY_SHA256 = (
    "9ad61725daddf5580ba337aac36fdacf53ba53e1349d589ae52c8338ca5def3c"
)

CURRENT_IMPLEMENTATION_COMMIT = (
    "0701aa5b9f010ef2402747f16817edbefe5eace7"
)
CURRENT_IMPLEMENTATION_TREE = "afb3bed74801c2efac88f1a352a774423c698988"
CURRENT_STATUS_LOCK_COMMIT = "fadb28d9bf02c744084de1e11f34fd71a883f81f"
CURRENT_PRODUCTION_SOURCE_SHA256 = {
    "body_app_prototype_v0.py": (
        "e81bb065e8e13621774b142d6afe9a5b479d3c14f7296665a2eec4bc6bf88f1a"
    ),
    "body_gateway_provider_agent_operation_routes_v0.py": (
        "de54f3384df653cf6d7b29865e3570c4808f99c65d3a39383b07ab8488094c23"
    ),
    "house_continuity_v1_2_durable_preparation_outbox_local.py": (
        "5383c455babece99c3eb8d7ee55c3bd2514f5b00aadef65c79fab014415eea0a"
    ),
}

HISTORICAL_PACKAGE_COMMIT = "0c4602b051158c030d92760cfcb749f6632dbfdd"
HISTORICAL_PACKAGE_TREE = "2ddba84e2507fb83d1929127732329340abde6a6"
HISTORICAL_PACKAGE_SHA256 = (
    "8b6297e7e88e8d17da620b7bfb1b1e08057907428c55bb98d19cd1f323040413"
)
HISTORICAL_MANIFEST_SHA256 = (
    "88e40175a96eeb6d10b7a19288f9825b8471821020bdada88457451a09e1d735"
)
HISTORICAL_REHEARSAL_RECEIPT_SHA256 = (
    "62a194cd0d1d0e7258fca335ff9167f6633ded36518fedb648db180b8d949583"
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,220}\Z")


class PredecessorAttestationError(ValueError):
    """Stable, bounded validation failure with no source/body projection."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _require(condition: bool, error_code: str) -> None:
    if not condition:
        raise PredecessorAttestationError(error_code)


def _require_sha(value: Any, error_code: str) -> None:
    _require(
        isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None,
        error_code,
    )


def _require_id(value: Any, error_code: str) -> None:
    _require(
        isinstance(value, str) and _ID_RE.fullmatch(value) is not None,
        error_code,
    )


def expected_attestation_body() -> dict[str, Any]:
    """Return the exact reviewed body, excluding its self-hash."""

    return {
        "schema_version": SCHEMA_VERSION,
        "attestation_kind": "accepted_historical_pre_live_proof",
        "authorization_state": "reference_only_not_live_authorization",
        "target": {
            "batch_id": TARGET_BATCH_ID,
            "manifest_sha256": TARGET_MANIFEST_SHA256,
            "package_commit": TARGET_PACKAGE_COMMIT,
            "package_tree": TARGET_PACKAGE_TREE,
            "operator_wrapper_commit": TARGET_WRAPPER_COMMIT,
            "operator_wrapper_tree": TARGET_WRAPPER_TREE,
            "row_order": list(TARGET_ROW_ORDER),
            "row_identity_sha256": TARGET_ROW_IDENTITY_SHA256,
            "first_row_predecessor": {
                "scenario": "B-01.01",
                "reference": "B-00:accepted_immutable",
                "status": "accepted_immutable",
                "historical_identity_is_reference_only": True,
            },
        },
        "accepted_current_deployment": {
            "implementation_commit": CURRENT_IMPLEMENTATION_COMMIT,
            "implementation_tree": CURRENT_IMPLEMENTATION_TREE,
            "deployment_status_lock_commit": CURRENT_STATUS_LOCK_COMMIT,
            "production_source_sha256": dict(CURRENT_PRODUCTION_SOURCE_SHA256),
        },
        "historical_predecessor": {
            "reference_only": True,
            "root_reference": (
                "examples/private-root-not-included/continuity-v1-2-gate12s-"
                "m5-checkpoint-b-index-refresh-corrected-root"
            ),
            "authorization_package": {
                "file": "HOUSE_M5_CHECKPOINT_B_CORRECTED_AUTHORIZATION_PACKAGE_2026-08-04.md",
                "commit": HISTORICAL_PACKAGE_COMMIT,
                "tree": HISTORICAL_PACKAGE_TREE,
                "file_sha256": HISTORICAL_PACKAGE_SHA256,
                "review_verdict": "PASS",
                "rehearsal_receipt_sha256": HISTORICAL_REHEARSAL_RECEIPT_SHA256,
            },
            "identity_manifest": {
                "file": "HOUSE_M5_CHECKPOINT_B_POST_BOOTSTRAP_IDENTITY_MANIFEST_2026-08-22.json",
                "sha256": HISTORICAL_MANIFEST_SHA256,
            },
            "historical_candidate": {
                "implementation_commit": "2d22c024d38b88df29fd804fa8729152fcd23e14",
                "implementation_tree": "b69e3266f926d01346368398864e5f3ec16a154e",
                "pointer_dropin_sha256": (
                    "91d3001b04067b498fa107f3f5c34d022de4ad6c72c5cdc09b5ed14d4ed061bc"
                ),
                "control_database_pre_authorization_sha256": (
                    "9d49a5c082347197ee2aed6adfc252a39599f89f369d22d460019dba614464b4"
                ),
                "pre_authorization_review_state": "pending",
                "pre_authorization_live_latch": {
                    "state": "unarmed",
                    "revision": 1,
                    "client_turn_id": None,
                },
                "pre_live_posture": {
                    "m5_effective": "off",
                    "gate12s_effective": "off",
                    "generation_effective": "house_standing_root_v2_generation_1",
                },
            },
            "successful_intercepted_rehearsal": {
                "turn_id": "msg_astel_m5_checkpoint_b_gate12s_index_refresh_corrected_bootstrap_20260822_01",
                "provider_operation_id": "hpaop_37143a642ead8b51ff2c13a4ef3e7235b5ce393ae2fc386ee2cafd931fecd67d",
                "request_sha256": "33d429150fac15ae1640918c43413dc9c5c48425936cf75039d1999b319c0515",
                "attempt_state": "completed",
                "capability_issued": True,
                "capability_consumed": True,
                "main_transport_authorized": True,
                "external_transport_count": 0,
                "intercepted_transport_count": 1,
                "attempt_receipt_sha256": "ef68b8eb05ceb00a989b904070099b18dfbd17fd1efa73ca6bbe5795601498c9",
                "outbox_bundle_id": "cws_out_ccdd2197ab03301b4a5d9176c43f68c3",
                "complete_unit_id": "ccu_7cd2849e9df184c11e76a2fb6995b95a",
                "bound_successor_evidence_sha256": "da47a89fa8903bb7eb1a4cba5f292b3418f5b49798e366d8e7d6c3e7191617bd",
                "outcome_receipt_sha256": "a7224818206ee78671572e5ebfdc010510e447e52a43710e36f9545b9482101c",
                "execution_stdout_sha256": "5b620799347f42fe3507fa4b04d7c1a2c2555c0e557eb141db4e41403898e8df",
                "execution_stderr_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "android_sync_state": "synced",
                "runtime_index_refresh": {
                    "enabled": False,
                    "ok": True,
                    "state": "disabled",
                },
                "working_set_state": "canonical_initialized_semantically_empty",
                "completion_state": "ready_to_apply_shadow_only",
                "unit_binding_state": "bound",
                "semantic_application_enabled": False,
                "safe_for_source_eviction": False,
                "automatic_retry_planned": False,
            },
            "reviewed_full_rehearsal": {
                "receipt_sha256": HISTORICAL_REHEARSAL_RECEIPT_SHA256,
                "review_verdict": "PASS",
                "matrix_identity_count": 14,
                "canonical_binding_event_count": 3,
                "sequential_rearm_count": 13,
                "accepted_operation_count": 12,
                "honest_no_delta_count": 2,
                "network_transport_count": 0,
                "provider_transport_count": 0,
                "helper_transport_count": 0,
                "tool_transport_count": 0,
            },
        },
        "replay_and_fresh_root_contract": {
            "historical_attempt_content_is_not_imported": True,
            "historical_root_is_not_reopened": True,
            "new_root_must_be_absent_before_creation": True,
            "new_control_attempt_count_must_be_zero": True,
            "new_control_binding_count_must_be_zero": True,
            "new_rehearsal_latch_must_be_unarmed_revision_1": True,
            "new_live_latch_must_be_unarmed_revision_1": True,
            "new_review_state_must_be_pending_before_attestation": True,
            "attestation_must_be_recorded_by_canonical_control_owner": True,
            "direct_sqlite_review_marker_write_forbidden": True,
            "root_path_not_an_identity_input": True,
            "runtime_randomness_not_an_identity_input": True,
            "lease_or_timestamp_not_an_identity_input": True,
        },
    }


EXPECTED_ATTESTATION_SHA256 = canonical_sha256(expected_attestation_body())


def _target_row_identities(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            key: row[key]
            for key in (
                "sequence",
                "scenario",
                "session_id",
                "stable_room_reference",
                "room_id",
                "project_id",
                "turn_id",
                "operation_id",
                "request_sha256",
                "expected_action",
            )
        }
        for row in manifest["batch"]["rows"]
    ]


def _validate_manifest_binding(manifest: Mapping[str, Any]) -> None:
    claimed_manifest_sha256 = manifest.get("manifest_sha256")
    _require_sha(
        claimed_manifest_sha256,
        "predecessor_target_manifest_hash_invalid",
    )
    manifest_body = dict(manifest)
    manifest_body.pop("manifest_sha256", None)
    _require(
        canonical_sha256(manifest_body) == claimed_manifest_sha256,
        "predecessor_target_manifest_content_hash_mismatch",
    )
    _require(
        manifest.get("manifest_id") == TARGET_BATCH_ID,
        "predecessor_target_batch_id_mismatch",
    )
    _require(
        manifest.get("manifest_sha256") == TARGET_MANIFEST_SHA256,
        "predecessor_target_manifest_mismatch",
    )
    accepted = manifest.get("accepted_deployment")
    _require(
        isinstance(accepted, Mapping)
        and accepted.get("implementation_commit") == CURRENT_IMPLEMENTATION_COMMIT
        and accepted.get("implementation_tree") == CURRENT_IMPLEMENTATION_TREE
        and accepted.get("status_lock_commit") == CURRENT_STATUS_LOCK_COMMIT,
        "predecessor_target_deployment_mismatch",
    )
    rows = manifest.get("batch", {}).get("rows")
    _require(
        isinstance(rows, list)
        and tuple(row.get("scenario") for row in rows) == TARGET_ROW_ORDER,
        "predecessor_target_row_order_mismatch",
    )
    _require(
        canonical_sha256(_target_row_identities(manifest))
        == TARGET_ROW_IDENTITY_SHA256,
        "predecessor_target_row_identity_mismatch",
    )


def validate_fresh_root_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the pre-creation shape without opening or creating a root."""

    expected = {
        "root_exists": False,
        "historical_attempts_imported": False,
        "attempt_count": 0,
        "binding_count": 0,
        "review_state": "pending",
        "rehearsal_latch": {"state": "unarmed", "revision": 1, "client_turn_id": None},
        "live_latch": {"state": "unarmed", "revision": 1, "client_turn_id": None},
        "semantic_item_count": 0,
        "semantic_event_count": 0,
    }
    _require(dict(snapshot) == expected, "predecessor_fresh_root_shape_invalid")
    return deepcopy(expected)


def validate_attestation(
    attestation: Mapping[str, Any],
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the exact reviewed attestation and optional target manifest."""

    _require(isinstance(attestation, Mapping), "predecessor_attestation_not_object")
    copy = json.loads(json.dumps(attestation))
    declared = copy.pop("attestation_sha256", None)
    _require_sha(declared, "predecessor_attestation_hash_invalid")
    expected = expected_attestation_body()
    _require(copy == expected, "predecessor_attestation_body_mismatch")
    _require(
        canonical_sha256(copy) == declared == EXPECTED_ATTESTATION_SHA256,
        "predecessor_attestation_hash_mismatch",
    )
    if manifest is not None:
        _validate_manifest_binding(manifest)
        _require(
            manifest["manifest_sha256"]
            == copy["target"]["manifest_sha256"],
            "predecessor_manifest_attestation_mismatch",
        )
    return {**copy, "attestation_sha256": declared}


def load_attestation(
    path: str | Path = DEFAULT_ATTESTATION_PATH,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PredecessorAttestationError("predecessor_attestation_read_failed") from exc
    return validate_attestation(value, manifest)


def attestation_review_marker(attestation: Mapping[str, Any]) -> str:
    """Return the marker the canonical control owner may durably record."""

    validated = validate_attestation(attestation)
    return "passed:predecessor-attestation:" + validated["attestation_sha256"]


def validate_target_row(
    attestation: Mapping[str, Any],
    *,
    scenario: str,
    turn_id: str,
    operation_id: str,
    manifest: Mapping[str, Any] | None = None,
) -> None:
    validated = validate_attestation(attestation, manifest)
    _require(scenario in TARGET_ROW_ORDER, "predecessor_row_scenario_invalid")
    _require_id(turn_id, "predecessor_row_turn_invalid")
    _require_id(operation_id, "predecessor_row_operation_invalid")
    expected_rows = validated["target"]["row_order"]
    _require(scenario in expected_rows, "predecessor_row_not_manifest_bound")
    if manifest is not None:
        rows = {
            row["scenario"]: row for row in manifest["batch"]["rows"]
        }
        expected = rows.get(scenario)
        _require(isinstance(expected, Mapping), "predecessor_row_not_manifest_bound")
        _require(
            turn_id == expected["turn_id"]
            and operation_id == expected["operation_id"],
            "predecessor_row_identity_mismatch",
        )
    else:
        # Without a manifest, still reject identities from another namespace.
        _require(
            turn_id.startswith("msg_astel_m5_checkpoint_b_batch1_20260906_01_"),
            "predecessor_row_turn_outside_manifest_domain",
        )
        _require(
            operation_id.startswith("hpaop_") and len(operation_id) == 70,
            "predecessor_row_operation_outside_manifest_domain",
        )


def canonical_owner_contract() -> dict[str, Any]:
    """Describe the small owner API needed to integrate this contract.

    The current deployed owner still exposes only mark_rehearsal_review_pass,
    which intentionally requires local attempt evidence.  A future reviewed
    control-plane owner must add a distinct method with these preconditions;
    this function is descriptive and performs no durable write.
    """

    return {
        "method": "mark_predecessor_attestation_pass",
        "input": "validated exact attestation body and expected target manifest",
        "preconditions": [
            "control doctor healthy",
            "attempt count zero",
            "operation binding count zero",
            "both latches unarmed at revision 1 with no client turn",
            "review state pending",
            "attestation hash and target identities exact",
        ],
        "durable_marker": (
            "passed:predecessor-attestation:" + EXPECTED_ATTESTATION_SHA256
        ),
        "must_not": [
            "read or copy historical attempt contents",
            "reopen historical root",
            "accept arbitrary new attestation hashes",
            "write directly from the operator into SQLite",
            "arm or dispatch a row as part of marking",
        ],
    }
