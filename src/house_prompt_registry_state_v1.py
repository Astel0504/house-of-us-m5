"""Sealed local/no-live registry integrity, epoch, and activation state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import house_prompt_registry_budget_v0 as registry_budget
import house_prompt_registry_manifest_v0 as registry_manifest
import house_provider_chat_adapter_v0 as chat_adapter
import house_provider_chat_serialization_v0 as chat_serialization
import house_provider_neutral_contract_v1 as neutral_contract
import house_provider_neutral_request_v0 as neutral


EPOCH_MANIFEST_SCHEMA_VERSION = "house_prompt_registry_epoch_manifest_v1"
VALIDATED_REGISTRY_STATE_VERSION = "house_prompt_validated_registry_state_v1"
REGISTRY_SNAPSHOT_VERSION = "house_prompt_registry_snapshot_v1"
REGISTRY_NEUTRAL_BUILDER_VERSION = "house_prompt_registry_neutral_builder_v1"
REGISTRY_OBSERVABILITY_VERSION = "house_prompt_registry_observability_v1"
SYNTHETIC_FIXTURE_SET_VERSION = "prompt_caching_gate4_synthetic_fixture_v1"
STANDING_ROOT_V2_CONTENT_SET_VERSION = "house_standing_root_v2_content_set_v1"
MAX_EPOCH_JSON_BYTES = 64 * 1024

EPOCH_FIELDS = (
    "schema_version",
    "snapshot_epoch",
    "instruction_law_registry_epoch",
    "context_card_registry_epoch",
    "checkpoint_epoch",
    "generation_policy_epoch",
    "structured_output_epoch",
    "privacy_provider_safety_policy_epoch",
    "neutral_contract_version",
    "neutral_request_schema_version",
    "chat_projection_version",
    "chat_adapter_version",
    "chat_developer_wrapper_version",
    "chat_stable_context_wrapper_version",
    "chat_current_turn_wrapper_version",
    "chat_segment_framing_version",
    "chat_endpoint_serialization_version",
    "model_route_epoch",
    "proactive_schema_epoch",
    "tool_schema_epoch",
    "budget_policy_version",
    "card_provider_rendering_version",
    "registry_observability_version",
    "synthetic_fixture_set_version",
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_STATE_TOKEN = object()


class PromptRegistryStateError(ValueError):
    """Raised when owner-private registry state is not fully bound."""


@dataclass(frozen=True)
class RegistryEpochManifest:
    schema_version: str
    snapshot_epoch: str
    instruction_law_registry_epoch: str
    context_card_registry_epoch: str
    checkpoint_epoch: str
    generation_policy_epoch: str
    structured_output_epoch: str
    privacy_provider_safety_policy_epoch: str
    neutral_contract_version: str
    neutral_request_schema_version: str
    chat_projection_version: str
    chat_adapter_version: str
    chat_developer_wrapper_version: str
    chat_stable_context_wrapper_version: str
    chat_current_turn_wrapper_version: str
    chat_segment_framing_version: str
    chat_endpoint_serialization_version: str
    model_route_epoch: str
    proactive_schema_epoch: str
    tool_schema_epoch: str
    budget_policy_version: str
    card_provider_rendering_version: str
    registry_observability_version: str
    synthetic_fixture_set_version: str


def _identifier(value: Any, *, field: str) -> str:
    if type(value) is not str or not _IDENTIFIER_RE.fullmatch(value):
        raise PromptRegistryStateError(
            f"{field} must be a bounded ASCII identifier"
        )
    return value


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def checkpoint_identity(
    registries: registry_manifest.RegistryPair,
) -> tuple[str, str, str] | None:
    checkpoints = tuple(
        entry
        for entry in registries.context_cards.entries
        if entry.class_name == "room_checkpoint" and entry.enabled
    )
    if len(checkpoints) > 1:
        raise PromptRegistryStateError(
            "the singular checkpoint contract allows at most one enabled entry"
        )
    if not checkpoints:
        return None
    checkpoint = checkpoints[0]
    return (
        checkpoint.slot_key,
        checkpoint.content_version,
        checkpoint.content_sha256,
    )


def checkpoint_state_sha256(
    identity: tuple[str, str, str] | None,
) -> str:
    return _canonical_sha256(
        {
            "contract": "singular_room_checkpoint_v1",
            "identity": list(identity) if identity is not None else None,
        }
    )


def bound_checkpoint_epoch(
    identity: tuple[str, str, str] | None,
) -> str:
    if identity is None:
        return "checkpoint_none_v1"
    return f"checkpoint_epoch_{checkpoint_state_sha256(identity)}"


def _snapshot_lineage_value(
    epochs: RegistryEpochManifest,
    *,
    registries: registry_manifest.RegistryPair,
    policy: registry_budget.RegistryBudgetPolicy,
    private_content_mode: registry_manifest.PrivateContentMode,
) -> dict[str, Any]:
    return {
        "epoch_manifest_schema_version": epochs.schema_version,
        "instruction_law_registry_state_sha256": (
            registry_manifest.registry_state_sha256(
                registries.instruction_law,
                registry_kind="instruction_law",
            )
        ),
        "context_card_registry_state_sha256": (
            registry_manifest.registry_state_sha256(
                registries.context_cards,
                registry_kind="context_card",
            )
        ),
        "checkpoint_state_sha256": checkpoint_state_sha256(
            checkpoint_identity(registries)
        ),
        "budget_policy_state_sha256": (
            registry_budget.budget_policy_state_sha256(policy)
        ),
        "private_content_mode": private_content_mode.value,
        "epochs_and_versions": {
            field: getattr(epochs, field)
            for field in EPOCH_FIELDS
            if field not in {"schema_version", "snapshot_epoch"}
        },
        "integrity_lock_schema_version": (
            registry_manifest.INTEGRITY_LOCK_SCHEMA_VERSION
        ),
        "selection_policy_version": registry_budget.SELECTION_POLICY_VERSION,
        "validated_registry_state_version": VALIDATED_REGISTRY_STATE_VERSION,
        "registry_snapshot_version": REGISTRY_SNAPSHOT_VERSION,
        "registry_neutral_builder_version": REGISTRY_NEUTRAL_BUILDER_VERSION,
    }


def snapshot_state_sha256(
    epochs: RegistryEpochManifest,
    *,
    registries: registry_manifest.RegistryPair,
    policy: registry_budget.RegistryBudgetPolicy,
    private_content_mode: registry_manifest.PrivateContentMode,
) -> str:
    return _canonical_sha256(
        _snapshot_lineage_value(
            epochs,
            registries=registries,
            policy=policy,
            private_content_mode=private_content_mode,
        )
    )


def bound_snapshot_epoch(state_sha256: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", state_sha256):
        raise PromptRegistryStateError("snapshot state digest is invalid")
    return f"snapshot_epoch_{state_sha256}"


def _parse_epoch_manifest(path: Path) -> RegistryEpochManifest:
    value = registry_manifest.load_strict_json_object(
        path,
        label="registry epoch manifest",
        max_bytes=MAX_EPOCH_JSON_BYTES,
    )
    if len(value) != len(EPOCH_FIELDS) or set(value) != set(EPOCH_FIELDS):
        raise PromptRegistryStateError(
            "registry epoch manifest fields are not exact"
        )
    if value["schema_version"] != EPOCH_MANIFEST_SCHEMA_VERSION:
        raise PromptRegistryStateError(
            "registry epoch manifest schema is unsupported"
        )
    parsed = {
        field: _identifier(value[field], field=field)
        for field in EPOCH_FIELDS
        if field != "schema_version"
    }
    return RegistryEpochManifest(
        schema_version=EPOCH_MANIFEST_SCHEMA_VERSION,
        **parsed,
    )


def validate_epoch_manifest(
    epochs: RegistryEpochManifest,
    *,
    registries: registry_manifest.RegistryPair,
    policy: registry_budget.RegistryBudgetPolicy,
    private_content_mode: registry_manifest.PrivateContentMode,
) -> RegistryEpochManifest:
    if type(epochs) is not RegistryEpochManifest:
        raise PromptRegistryStateError(
            "registry epoch manifest has the wrong direct type"
        )
    for field in EPOCH_FIELDS:
        _identifier(getattr(epochs, field), field=field)
    if epochs.schema_version != EPOCH_MANIFEST_SCHEMA_VERSION:
        raise PromptRegistryStateError(
            "registry epoch manifest schema is unsupported"
        )
    if type(private_content_mode) is not registry_manifest.PrivateContentMode:
        raise PromptRegistryStateError(
            "private content mode has the wrong closed type"
        )
    selected_policy = registry_budget.validate_budget_policy(policy)
    standing_root_present = any(
        entry.class_name == "standing_root"
        for entry in registries.context_cards.entries
    )
    expected_content_set_version = (
        STANDING_ROOT_V2_CONTENT_SET_VERSION
        if standing_root_present
        else SYNTHETIC_FIXTURE_SET_VERSION
    )
    expected_versions = {
        "instruction_law_registry_epoch": (
            registries.instruction_law.registry_epoch
        ),
        "context_card_registry_epoch": registries.context_cards.registry_epoch,
        "checkpoint_epoch": bound_checkpoint_epoch(
            checkpoint_identity(registries)
        ),
        "neutral_contract_version": neutral_contract.CONTRACT_SCHEMA_VERSION,
        "neutral_request_schema_version": neutral.REQUEST_SCHEMA_VERSION,
        "chat_projection_version": chat_adapter.CHAT_PROJECTION_VERSION,
        "chat_adapter_version": chat_adapter.CHAT_ADAPTER_VERSION,
        "chat_developer_wrapper_version": chat_adapter.DEVELOPER_WRAPPER_VERSION,
        "chat_stable_context_wrapper_version": (
            chat_adapter.STABLE_CONTEXT_WRAPPER_VERSION
        ),
        "chat_current_turn_wrapper_version": (
            chat_adapter.CURRENT_TURN_WRAPPER_VERSION
        ),
        "chat_segment_framing_version": chat_adapter.SEGMENT_FRAMING_VERSION,
        "chat_endpoint_serialization_version": (
            chat_serialization.CHAT_ENDPOINT_SERIALIZATION_VERSION
        ),
        "budget_policy_version": selected_policy.policy_version,
        "card_provider_rendering_version": (
            registry_budget.CARD_PROVIDER_RENDERING_VERSION
        ),
        "registry_observability_version": REGISTRY_OBSERVABILITY_VERSION,
        "synthetic_fixture_set_version": expected_content_set_version,
    }
    for field, expected in expected_versions.items():
        if getattr(epochs, field) != expected:
            raise PromptRegistryStateError(
                f"registry epoch manifest {field} is inconsistent"
            )
    digest = snapshot_state_sha256(
        epochs,
        registries=registries,
        policy=selected_policy,
        private_content_mode=private_content_mode,
    )
    if epochs.snapshot_epoch != bound_snapshot_epoch(digest):
        raise PromptRegistryStateError(
            "snapshot semantic lineage is not bound to snapshot_epoch"
        )
    return epochs


def _validate_lock(
    lock: registry_manifest.RegistryIntegrityLock,
    *,
    registries: registry_manifest.RegistryPair,
    epochs: RegistryEpochManifest,
    policy: registry_budget.RegistryBudgetPolicy,
    private_content_mode: registry_manifest.PrivateContentMode,
) -> None:
    law_digest = registry_manifest.registry_state_sha256(
        registries.instruction_law,
        registry_kind="instruction_law",
    )
    card_digest = registry_manifest.registry_state_sha256(
        registries.context_cards,
        registry_kind="context_card",
    )
    if (
        lock.instruction_law_registry.registry_epoch
        != registries.instruction_law.registry_epoch
        or lock.instruction_law_registry.state_sha256 != law_digest
        or lock.context_card_registry.registry_epoch
        != registries.context_cards.registry_epoch
        or lock.context_card_registry.state_sha256 != card_digest
    ):
        raise PromptRegistryStateError(
            "registry state lock disagrees with loaded manifests"
        )
    policy_digest = registry_budget.budget_policy_state_sha256(policy)
    if (
        lock.budget_policy.policy_version != policy.policy_version
        or lock.budget_policy.state_sha256 != policy_digest
    ):
        raise PromptRegistryStateError(
            "budget policy state lock disagrees with exact policy values"
        )
    checkpoint = checkpoint_identity(registries)
    expected_checkpoint = (
        (None, None, None) if checkpoint is None else checkpoint
    )
    if (
        lock.checkpoint.checkpoint_epoch != epochs.checkpoint_epoch
        or (
            lock.checkpoint.slot_key,
            lock.checkpoint.content_version,
            lock.checkpoint.content_sha256,
        )
        != expected_checkpoint
    ):
        raise PromptRegistryStateError(
            "checkpoint lock disagrees with the singular checkpoint identity"
        )
    snapshot_digest = snapshot_state_sha256(
        epochs,
        registries=registries,
        policy=policy,
        private_content_mode=private_content_mode,
    )
    if (
        lock.snapshot.snapshot_epoch != epochs.snapshot_epoch
        or lock.snapshot.state_sha256 != snapshot_digest
    ):
        raise PromptRegistryStateError(
            "snapshot lock disagrees with the complete lineage state"
        )


def _attestation_digest(
    *,
    registries: registry_manifest.RegistryPair,
    epochs: RegistryEpochManifest,
    policy: registry_budget.RegistryBudgetPolicy,
    lock: registry_manifest.RegistryIntegrityLock,
    private_content_mode: registry_manifest.PrivateContentMode,
    authority_kind: str,
) -> str:
    return _canonical_sha256(
        {
            "validated_state_version": VALIDATED_REGISTRY_STATE_VERSION,
            "instruction_law_state": (
                registry_manifest.registry_state_sha256(
                    registries.instruction_law,
                    registry_kind="instruction_law",
                )
            ),
            "context_card_state": registry_manifest.registry_state_sha256(
                registries.context_cards,
                registry_kind="context_card",
            ),
            "epochs": asdict(epochs),
            "budget_policy_state": registry_budget.budget_policy_state_sha256(
                policy
            ),
            "integrity_lock": asdict(lock),
            "private_content_mode": private_content_mode.value,
            "authority_kind": authority_kind,
        }
    )


class ValidatedRegistryState:
    """Sealed authority object created only by the reviewed file loader."""

    __slots__ = (
        "_registries",
        "_epochs",
        "_policy",
        "_integrity_lock",
        "_private_content_mode",
        "_authority_kind",
        "_attestation",
        "_sealed",
    )

    def __init__(
        self,
        *,
        registries: registry_manifest.RegistryPair,
        epochs: RegistryEpochManifest,
        policy: registry_budget.RegistryBudgetPolicy,
        integrity_lock: registry_manifest.RegistryIntegrityLock,
        private_content_mode: registry_manifest.PrivateContentMode,
        authority_kind: str,
        attestation: str,
        _token: object,
    ) -> None:
        if _token is not _STATE_TOKEN:
            raise PromptRegistryStateError(
                "validated registry state can only be created by its loader"
            )
        object.__setattr__(self, "_registries", registries)
        object.__setattr__(self, "_epochs", epochs)
        object.__setattr__(self, "_policy", policy)
        object.__setattr__(self, "_integrity_lock", integrity_lock)
        object.__setattr__(self, "_private_content_mode", private_content_mode)
        object.__setattr__(self, "_authority_kind", authority_kind)
        object.__setattr__(self, "_attestation", attestation)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("validated registry state is sealed")

    @property
    def registries(self) -> registry_manifest.RegistryPair:
        return self._registries

    @property
    def epochs(self) -> RegistryEpochManifest:
        return self._epochs

    @property
    def policy(self) -> registry_budget.RegistryBudgetPolicy:
        return self._policy

    @property
    def private_content_mode(self) -> registry_manifest.PrivateContentMode:
        return self._private_content_mode

    @property
    def authority_kind(self) -> str:
        return self._authority_kind

    def assert_attested(self) -> None:
        registry_manifest.revalidate_loaded_registry_pair(self._registries)
        validate_epoch_manifest(
            self._epochs,
            registries=self._registries,
            policy=self._policy,
            private_content_mode=self._private_content_mode,
        )
        _validate_lock(
            self._integrity_lock,
            registries=self._registries,
            epochs=self._epochs,
            policy=self._policy,
            private_content_mode=self._private_content_mode,
        )
        expected = _attestation_digest(
            registries=self._registries,
            epochs=self._epochs,
            policy=self._policy,
            lock=self._integrity_lock,
            private_content_mode=self._private_content_mode,
            authority_kind=self._authority_kind,
        )
        if self._attestation != expected:
            raise PromptRegistryStateError(
                "validated registry state attestation no longer matches"
            )


def _seal_state(
    *,
    registries: registry_manifest.RegistryPair,
    epochs: RegistryEpochManifest,
    policy: registry_budget.RegistryBudgetPolicy,
    integrity_lock: registry_manifest.RegistryIntegrityLock,
    private_content_mode: registry_manifest.PrivateContentMode,
    authority_kind: str,
) -> ValidatedRegistryState:
    if authority_kind not in {"reviewed_files", "synthetic_test_only"}:
        raise PromptRegistryStateError(
            "validated registry authority kind is not closed"
        )
    validate_epoch_manifest(
        epochs,
        registries=registries,
        policy=policy,
        private_content_mode=private_content_mode,
    )
    _validate_lock(
        integrity_lock,
        registries=registries,
        epochs=epochs,
        policy=policy,
        private_content_mode=private_content_mode,
    )
    return ValidatedRegistryState(
        registries=registries,
        epochs=epochs,
        policy=policy,
        integrity_lock=integrity_lock,
        private_content_mode=private_content_mode,
        authority_kind=authority_kind,
        attestation=_attestation_digest(
            registries=registries,
            epochs=epochs,
            policy=policy,
            lock=integrity_lock,
            private_content_mode=private_content_mode,
            authority_kind=authority_kind,
        ),
        _token=_STATE_TOKEN,
    )


def load_validated_registry_state(
    *,
    instruction_law_root: Path,
    context_card_root: Path,
    integrity_lock_path: Path,
    epoch_manifest_path: Path,
    policy: registry_budget.RegistryBudgetPolicy = (
        registry_budget.DEFAULT_BUDGET_POLICY
    ),
    private_content_mode: registry_manifest.PrivateContentMode = (
        registry_manifest.PrivateContentMode.DISABLED
    ),
) -> ValidatedRegistryState:
    """Load the only activation-safe registry authority from reviewed files."""

    if type(private_content_mode) is not registry_manifest.PrivateContentMode:
        raise PromptRegistryStateError(
            "private_content_mode must use the closed PrivateContentMode policy"
        )
    selected_policy = registry_budget.validate_budget_policy(policy)
    integrity_lock = registry_manifest.load_integrity_lock(
        integrity_lock_path
    )
    registries = registry_manifest._load_registry_pair_from_lock(
        instruction_law_root=instruction_law_root,
        context_card_root=context_card_root,
        integrity_lock=integrity_lock,
        private_content_mode=private_content_mode,
    )
    epochs = _parse_epoch_manifest(epoch_manifest_path)
    return _seal_state(
        registries=registries,
        epochs=epochs,
        policy=selected_policy,
        integrity_lock=integrity_lock,
        private_content_mode=private_content_mode,
        authority_kind="reviewed_files",
    )


def load_test_only_registry_state(
    *,
    instruction_law_root: Path,
    context_card_root: Path,
    integrity_lock_path: Path,
    epoch_manifest_path: Path,
    policy: registry_budget.RegistryBudgetPolicy,
) -> ValidatedRegistryState:
    """Create an explicit synthetic-only policy override outside activation."""

    selected_policy = registry_budget.validate_budget_policy(policy)
    if not selected_policy.policy_version.startswith(
        f"{registry_budget.TEST_BUDGET_POLICY_ID}_"
    ):
        raise PromptRegistryStateError(
            "test-only state requires a reviewed synthetic policy identity"
        )
    base_lock = registry_manifest.load_integrity_lock(integrity_lock_path)
    registries = registry_manifest._load_registry_pair_from_lock(
        instruction_law_root=instruction_law_root,
        context_card_root=context_card_root,
        integrity_lock=base_lock,
        private_content_mode=registry_manifest.PrivateContentMode.DISABLED,
    )
    base_epochs = _parse_epoch_manifest(epoch_manifest_path)
    epochs = replace(
        base_epochs,
        budget_policy_version=selected_policy.policy_version,
        snapshot_epoch="pending_snapshot_epoch",
    )
    snapshot_digest = snapshot_state_sha256(
        epochs,
        registries=registries,
        policy=selected_policy,
        private_content_mode=registry_manifest.PrivateContentMode.DISABLED,
    )
    epochs = replace(
        epochs,
        snapshot_epoch=bound_snapshot_epoch(snapshot_digest),
    )
    lock = replace(
        base_lock,
        budget_policy=registry_manifest.BudgetStateBinding(
            policy_version=selected_policy.policy_version,
            state_sha256=registry_budget.budget_policy_state_sha256(
                selected_policy
            ),
        ),
        snapshot=registry_manifest.SnapshotStateBinding(
            snapshot_epoch=epochs.snapshot_epoch,
            state_sha256=snapshot_state_sha256(
                epochs,
                registries=registries,
                policy=selected_policy,
                private_content_mode=(
                    registry_manifest.PrivateContentMode.DISABLED
                ),
            ),
        ),
    )
    return _seal_state(
        registries=registries,
        epochs=epochs,
        policy=selected_policy,
        integrity_lock=lock,
        private_content_mode=registry_manifest.PrivateContentMode.DISABLED,
        authority_kind="synthetic_test_only",
    )
