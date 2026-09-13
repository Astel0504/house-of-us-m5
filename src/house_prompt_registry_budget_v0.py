"""Whole-unit local/no-live budgets for prompt registry snapshots.

The limits in this owner are provisional Gate 4 defaults. They are not a
production model policy, a provider cache promise, or a tokenizer claim.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from collections.abc import Sequence

import house_prompt_registry_manifest_v0 as registry_manifest
import house_provider_neutral_observability_v0 as neutral_observability
import provider_visible_text_safety_v0 as provider_text_safety


DEFAULT_BUDGET_POLICY_ID = "house_prompt_registry_budget_policy_v1"
TEST_BUDGET_POLICY_ID = "house_prompt_registry_budget_policy_test_v1"
CARD_PROVIDER_RENDERING_VERSION = "house_prompt_card_rendering_v2"
SELECTION_POLICY_VERSION = "house_prompt_whole_card_selection_v2"

OMISSION_REASONS = (
    "disabled",
    "instruction_law_budget_exceeded",
    "card_class_budget_exceeded",
    "checkpoint_budget_exceeded",
    "stable_context_budget_exceeded",
)


class PromptRegistryBudgetError(ValueError):
    """Raised when a required unit or complete request exceeds a Gate 4 limit."""


@dataclass(frozen=True)
class RegistryBudgetPolicy:
    policy_version: str
    instruction_law_utf8_bytes: int
    card_class_utf8_bytes: tuple[tuple[str, int], ...]
    total_stable_context_utf8_bytes: int
    checkpoint_utf8_bytes: int
    native_history_utf8_bytes: int
    dynamic_context_utf8_bytes: int
    current_input_utf8_bytes: int
    output_reserve_estimate_units: int
    total_input_utf8_bytes: int

    def card_class_limit(self, class_name: str) -> int:
        limits = dict(self.card_class_utf8_bytes)
        try:
            return limits[class_name]
        except KeyError as exc:
            raise PromptRegistryBudgetError(
                "card class has no reviewed budget"
            ) from exc


_UNBOUND_DEFAULT_BUDGET_POLICY = RegistryBudgetPolicy(
    policy_version="unbound",
    instruction_law_utf8_bytes=4_096,
    card_class_utf8_bytes=(
        ("standing_root", 49_152),
        ("astel_profile", 2_048),
        ("solen_profile", 2_048),
        ("relationship_footing", 2_048),
        ("core_memory", 4_096),
        ("capability", 2_048),
        ("approved_reference", 2_048),
        ("room_checkpoint", 2_048),
    ),
    total_stable_context_utf8_bytes=49_152,
    checkpoint_utf8_bytes=2_048,
    native_history_utf8_bytes=8_192,
    dynamic_context_utf8_bytes=4_096,
    current_input_utf8_bytes=4_096,
    output_reserve_estimate_units=8_192,
    total_input_utf8_bytes=98_304,
)


def _policy_state_value(policy: RegistryBudgetPolicy) -> dict[str, object]:
    return {
        "instruction_law_utf8_bytes": policy.instruction_law_utf8_bytes,
        "card_class_utf8_bytes": [
            [class_name, limit]
            for class_name, limit in policy.card_class_utf8_bytes
        ],
        "total_stable_context_utf8_bytes": (
            policy.total_stable_context_utf8_bytes
        ),
        "checkpoint_utf8_bytes": policy.checkpoint_utf8_bytes,
        "native_history_utf8_bytes": policy.native_history_utf8_bytes,
        "dynamic_context_utf8_bytes": policy.dynamic_context_utf8_bytes,
        "current_input_utf8_bytes": policy.current_input_utf8_bytes,
        "output_reserve_estimate_units": (
            policy.output_reserve_estimate_units
        ),
        "total_input_utf8_bytes": policy.total_input_utf8_bytes,
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "card_provider_rendering_version": CARD_PROVIDER_RENDERING_VERSION,
    }


def budget_policy_state_sha256(policy: RegistryBudgetPolicy) -> str:
    encoded = json.dumps(
        _policy_state_value(policy),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bound_policy_version(identity: str, policy: RegistryBudgetPolicy) -> str:
    return f"{identity}_{budget_policy_state_sha256(policy)}"


BUDGET_POLICY_VERSION = _bound_policy_version(
    DEFAULT_BUDGET_POLICY_ID,
    _UNBOUND_DEFAULT_BUDGET_POLICY,
)
DEFAULT_BUDGET_POLICY = replace(
    _UNBOUND_DEFAULT_BUDGET_POLICY,
    policy_version=BUDGET_POLICY_VERSION,
)


def test_only_budget_policy(
    **changes: int | tuple[tuple[str, int], ...],
) -> RegistryBudgetPolicy:
    """Build a self-binding synthetic policy for explicitly named local tests."""

    policy = replace(
        DEFAULT_BUDGET_POLICY,
        policy_version="unbound",
        **changes,
    )
    return replace(
        policy,
        policy_version=_bound_policy_version(TEST_BUDGET_POLICY_ID, policy),
    )


@dataclass(frozen=True)
class ProviderTextUsage:
    characters: int
    utf8_bytes: int
    conservative_estimate_units: int


@dataclass(frozen=True)
class RenderedRegistryEntry:
    entry: registry_manifest.RegistryContent
    source_text: str
    rendered_text: str
    provider_text: str
    usage: ProviderTextUsage
    exactness: str
    transformation_flags: tuple[str, ...]
    provider_safety_redacted: bool


@dataclass(frozen=True)
class RegistryOmission:
    registry_kind: str
    class_name: str
    required_or_optional: str
    reason: str


@dataclass(frozen=True)
class RegistrySelection:
    instruction_law: tuple[RenderedRegistryEntry, ...]
    context_cards: tuple[RenderedRegistryEntry, ...]
    omissions: tuple[RegistryOmission, ...]
    policy: RegistryBudgetPolicy
    estimator_name: str
    estimator_version: str


@dataclass(frozen=True)
class RequestBudgetUsage:
    native_history: ProviderTextUsage
    dynamic_context: ProviderTextUsage
    current_input: ProviderTextUsage
    requested_output_estimate_units: int
    endpoint_utf8_bytes: int


def validate_budget_policy(
    policy: RegistryBudgetPolicy,
) -> RegistryBudgetPolicy:
    if type(policy) is not RegistryBudgetPolicy:
        raise PromptRegistryBudgetError("budget policy has the wrong type")
    if type(policy.policy_version) is not str:
        raise PromptRegistryBudgetError("budget policy version has the wrong type")
    if type(policy.card_class_utf8_bytes) is not tuple or any(
        type(pair) is not tuple
        or len(pair) != 2
        or type(pair[0]) is not str
        or type(pair[1]) is not int
        for pair in policy.card_class_utf8_bytes
    ):
        raise PromptRegistryBudgetError(
            "card-class budgets must be exact text/integer tuples"
        )
    class_limits = dict(policy.card_class_utf8_bytes)
    if (
        len(class_limits) != len(policy.card_class_utf8_bytes)
        or tuple(class_limits) != registry_manifest.CARD_CLASS_ORDER
    ):
        raise PromptRegistryBudgetError(
            "budget policy must define every card class in canonical order"
        )
    values = (
        policy.instruction_law_utf8_bytes,
        *class_limits.values(),
        policy.total_stable_context_utf8_bytes,
        policy.checkpoint_utf8_bytes,
        policy.native_history_utf8_bytes,
        policy.dynamic_context_utf8_bytes,
        policy.current_input_utf8_bytes,
        policy.output_reserve_estimate_units,
        policy.total_input_utf8_bytes,
    )
    if any(type(value) is not int or value <= 0 for value in values):
        raise PromptRegistryBudgetError("all budget limits must be positive integers")
    accepted_versions = {
        _bound_policy_version(DEFAULT_BUDGET_POLICY_ID, policy),
        _bound_policy_version(TEST_BUDGET_POLICY_ID, policy),
    }
    if policy.policy_version not in accepted_versions:
        raise PromptRegistryBudgetError(
            "budget policy identity is not bound to its exact numeric state"
        )
    return policy


def provider_text_usage(texts: Sequence[str]) -> ProviderTextUsage:
    if isinstance(texts, (str, bytes)) or not isinstance(texts, Sequence):
        raise PromptRegistryBudgetError("budget text values must be a sequence")
    values = tuple(texts)
    if any(not isinstance(text, str) for text in values):
        raise PromptRegistryBudgetError("budget text values must be strings")
    estimate = neutral_observability.Utf8ByteUpperBoundEstimator().estimate(values)
    conservative = estimate.conservative_token_estimate
    if (
        estimate.estimator_name != "utf8_byte_upper_bound"
        or estimate.estimator_version
        != neutral_observability.UTF8_BYTE_UPPER_BOUND_ESTIMATOR_VERSION
        or estimate.estimate_kind != "conservative"
        or conservative is None
    ):
        raise PromptRegistryBudgetError(
            "the reviewed conservative estimator identity changed"
        )
    utf8_bytes = sum(len(text.encode("utf-8")) for text in values)
    if conservative != utf8_bytes:
        raise PromptRegistryBudgetError(
            "the UTF-8 upper-bound estimator is internally inconsistent"
        )
    return ProviderTextUsage(
        characters=sum(len(text) for text in values),
        utf8_bytes=utf8_bytes,
        conservative_estimate_units=conservative,
    )


def render_registry_entry(
    entry: registry_manifest.RegistryContent,
) -> RenderedRegistryEntry:
    """Render one semantic label and body without exposing registry metadata."""

    if not isinstance(
        entry,
        (
            registry_manifest.InstructionLawEntry,
            registry_manifest.ContextCardEntry,
        ),
    ):
        raise PromptRegistryBudgetError("registry entry has no typed authority owner")
    source_text = entry.content_text
    provider_body = source_text
    if (
        isinstance(entry, registry_manifest.ContextCardEntry)
        and entry.class_name == "standing_root"
    ):
        authoring_heading, separator, provider_body = source_text.partition(
            "\n\n"
        )
        if (
            separator != "\n\n"
            or not authoring_heading.startswith("# ")
            or "\n" in authoring_heading
            or not provider_body
        ):
            raise PromptRegistryBudgetError(
                "standing-root content requires one authoring H1 before its body"
            )
    rendered_text = f"{entry.semantic_label}\n{provider_body}"
    provider_text = provider_text_safety.sanitize_provider_visible_text(
        rendered_text
    )
    provider_redacted = provider_text != rendered_text
    flags = (
        ("provider_safety_redacted", "structured_rendered")
        if provider_redacted
        else ("structured_rendered",)
    )
    exactness = (
        "mixed"
        if entry.exactness == "exact" or provider_redacted
        else entry.exactness
    )
    return RenderedRegistryEntry(
        entry=entry,
        source_text=source_text,
        rendered_text=rendered_text,
        provider_text=provider_text,
        usage=provider_text_usage((provider_text,)),
        exactness=exactness,
        transformation_flags=flags,
        provider_safety_redacted=provider_redacted,
    )


def _omission(
    entry: registry_manifest.RegistryContent,
    *,
    registry_kind: str,
    reason: str,
) -> RegistryOmission:
    if reason not in OMISSION_REASONS:
        raise PromptRegistryBudgetError("omission reason is not closed")
    return RegistryOmission(
        registry_kind=registry_kind,
        class_name=entry.class_name,
        required_or_optional=entry.required_or_optional,
        reason=reason,
    )


def select_registry_entries(
    pair: registry_manifest.RegistryPair,
    *,
    policy: RegistryBudgetPolicy = DEFAULT_BUDGET_POLICY,
) -> RegistrySelection:
    """Select complete entries by priority, then return canonical render order."""

    if type(pair) is not registry_manifest.RegistryPair:
        raise PromptRegistryBudgetError("registry pair has the wrong direct type")
    selected_policy = validate_budget_policy(policy)
    omissions: list[RegistryOmission] = []

    law_rendered: dict[str, RenderedRegistryEntry] = {}
    for entry in pair.instruction_law.entries:
        if not entry.enabled:
            if entry.required_or_optional == "required":
                raise PromptRegistryBudgetError(
                    "a required instruction-law slot cannot be disabled"
                )
            omissions.append(
                _omission(entry, registry_kind="instruction_law", reason="disabled")
            )
            continue
        law_rendered[entry.slot_key] = render_registry_entry(entry)

    required_law = tuple(
        item
        for item in law_rendered.values()
        if item.entry.required_or_optional == "required"
    )
    law_bytes = sum(item.usage.utf8_bytes for item in required_law)
    if law_bytes > selected_policy.instruction_law_utf8_bytes:
        raise PromptRegistryBudgetError(
            "required instruction law exceeds its whole-unit budget"
        )
    selected_law_slots = {item.entry.slot_key for item in required_law}
    optional_law = sorted(
        (
            item
            for item in law_rendered.values()
            if item.entry.required_or_optional == "optional"
        ),
        key=lambda item: (
            item.entry.selection_priority,
            registry_manifest.LAW_CLASS_ORDER.index(item.entry.class_name),
            item.entry.slot_key,
            item.entry.content_version,
        ),
    )
    for item in optional_law:
        if law_bytes + item.usage.utf8_bytes <= selected_policy.instruction_law_utf8_bytes:
            selected_law_slots.add(item.entry.slot_key)
            law_bytes += item.usage.utf8_bytes
        else:
            omissions.append(
                _omission(
                    item.entry,
                    registry_kind="instruction_law",
                    reason="instruction_law_budget_exceeded",
                )
            )
    if not selected_law_slots:
        raise PromptRegistryBudgetError(
            "at least one enabled instruction-law slot is required"
        )

    card_rendered: dict[str, RenderedRegistryEntry] = {}
    for entry in pair.context_cards.entries:
        if not entry.enabled:
            if entry.required_or_optional == "required":
                raise PromptRegistryBudgetError(
                    "a required context-card slot cannot be disabled"
                )
            omissions.append(
                _omission(entry, registry_kind="context_card", reason="disabled")
            )
            continue
        card_rendered[entry.slot_key] = render_registry_entry(entry)

    selected_card_slots: set[str] = set()
    class_bytes = {
        class_name: 0 for class_name in registry_manifest.CARD_CLASS_ORDER
    }
    checkpoint_bytes = 0
    stable_bytes = 0
    required_cards = tuple(
        item
        for item in card_rendered.values()
        if item.entry.required_or_optional == "required"
    )
    for item in required_cards:
        class_name = item.entry.class_name
        class_bytes[class_name] += item.usage.utf8_bytes
        stable_bytes += item.usage.utf8_bytes
        if class_name == "room_checkpoint":
            checkpoint_bytes += item.usage.utf8_bytes
        selected_card_slots.add(item.entry.slot_key)
    for class_name, used in class_bytes.items():
        if used > selected_policy.card_class_limit(class_name):
            raise PromptRegistryBudgetError(
                f"required {class_name} cards exceed their whole-card budget"
            )
    if checkpoint_bytes > selected_policy.checkpoint_utf8_bytes:
        raise PromptRegistryBudgetError(
            "required checkpoint cards exceed their whole-card budget"
        )
    if stable_bytes > selected_policy.total_stable_context_utf8_bytes:
        raise PromptRegistryBudgetError(
            "required context cards exceed the total stable-context budget"
        )

    optional_cards = sorted(
        (
            item
            for item in card_rendered.values()
            if item.entry.required_or_optional == "optional"
        ),
        key=lambda item: (
            item.entry.selection_priority,
            registry_manifest.CARD_STABILITY_ORDER.index(
                item.entry.stability_class
            ),
            registry_manifest.CARD_CLASS_ORDER.index(item.entry.class_name),
            item.entry.slot_key,
            item.entry.content_version,
        ),
    )
    for item in optional_cards:
        class_name = item.entry.class_name
        size = item.usage.utf8_bytes
        if class_bytes[class_name] + size > selected_policy.card_class_limit(
            class_name
        ):
            reason = "card_class_budget_exceeded"
        elif (
            class_name == "room_checkpoint"
            and checkpoint_bytes + size > selected_policy.checkpoint_utf8_bytes
        ):
            reason = "checkpoint_budget_exceeded"
        elif stable_bytes + size > selected_policy.total_stable_context_utf8_bytes:
            reason = "stable_context_budget_exceeded"
        else:
            selected_card_slots.add(item.entry.slot_key)
            class_bytes[class_name] += size
            stable_bytes += size
            if class_name == "room_checkpoint":
                checkpoint_bytes += size
            continue
        omissions.append(
            _omission(item.entry, registry_kind="context_card", reason=reason)
        )

    selected_law = tuple(
        law_rendered[entry.slot_key]
        for entry in pair.instruction_law.entries
        if entry.slot_key in selected_law_slots
    )
    selected_cards = tuple(
        card_rendered[entry.slot_key]
        for entry in pair.context_cards.entries
        if entry.slot_key in selected_card_slots
    )
    return RegistrySelection(
        instruction_law=selected_law,
        context_cards=selected_cards,
        omissions=tuple(omissions),
        policy=selected_policy,
        estimator_name="utf8_byte_upper_bound",
        estimator_version=(
            neutral_observability.UTF8_BYTE_UPPER_BOUND_ESTIMATOR_VERSION
        ),
    )


def validate_request_budgets(
    *,
    native_history_texts: Sequence[str],
    dynamic_context_texts: Sequence[str],
    current_input_text: str,
    requested_output_estimate_units: int,
    endpoint_body: bytes,
    policy: RegistryBudgetPolicy = DEFAULT_BUDGET_POLICY,
) -> RequestBudgetUsage:
    selected_policy = validate_budget_policy(policy)
    history = provider_text_usage(native_history_texts)
    dynamic = provider_text_usage(dynamic_context_texts)
    current = provider_text_usage((current_input_text,))
    if history.utf8_bytes > selected_policy.native_history_utf8_bytes:
        raise PromptRegistryBudgetError("native history exceeds its budget")
    if dynamic.utf8_bytes > selected_policy.dynamic_context_utf8_bytes:
        raise PromptRegistryBudgetError("dynamic context exceeds its budget")
    if current.utf8_bytes > selected_policy.current_input_utf8_bytes:
        raise PromptRegistryBudgetError("current input exceeds its budget")
    if (
        type(requested_output_estimate_units) is not int
        or requested_output_estimate_units < 0
        or requested_output_estimate_units
        > selected_policy.output_reserve_estimate_units
    ):
        raise PromptRegistryBudgetError("requested output exceeds its reserve")
    if not isinstance(endpoint_body, bytes):
        raise PromptRegistryBudgetError("endpoint body must be serialized bytes")
    endpoint_bytes = len(endpoint_body)
    if endpoint_bytes > selected_policy.total_input_utf8_bytes:
        raise PromptRegistryBudgetError(
            "serialized endpoint body exceeds the total input reserve"
        )
    return RequestBudgetUsage(
        native_history=history,
        dynamic_context=dynamic,
        current_input=current,
        requested_output_estimate_units=requested_output_estimate_units,
        endpoint_utf8_bytes=endpoint_bytes,
    )
