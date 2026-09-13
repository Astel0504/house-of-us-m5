"""Raw-free neutral-request summaries and the token-estimation seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

import house_provider_neutral_contract_v1 as contract
import house_provider_neutral_request_v0 as neutral


SUMMARY_SCHEMA_VERSION = "house_provider_neutral_summary_v4"
TOKEN_ESTIMATE_SCHEMA_VERSION = "house_provider_token_estimate_v1"
UTF8_BYTE_UPPER_BOUND_ESTIMATOR_VERSION = "utf8_byte_upper_bound_v0"


@dataclass(frozen=True)
class TokenEstimate:
    estimator_name: str
    estimator_version: str
    estimate_kind: str
    exact_token_count: int | None
    conservative_token_estimate: int | None


class ProviderTextTokenEstimator(Protocol):
    """Interface for later route-specific exact or calibrated estimators."""

    def estimate(self, provider_texts: Sequence[str]) -> TokenEstimate:
        ...


class Utf8ByteUpperBoundEstimator:
    """Conservative multilingual seam; one UTF-8 byte is at most one estimate unit."""

    def estimate(self, provider_texts: Sequence[str]) -> TokenEstimate:
        return TokenEstimate(
            estimator_name="utf8_byte_upper_bound",
            estimator_version=UTF8_BYTE_UPPER_BOUND_ESTIMATOR_VERSION,
            estimate_kind="conservative",
            exact_token_count=None,
            conservative_token_estimate=sum(len(text.encode("utf-8")) for text in provider_texts),
        )


def _validate_estimate(value: TokenEstimate) -> dict[str, object]:
    if not isinstance(value, TokenEstimate):
        raise ValueError("token estimator must return TokenEstimate")
    try:
        estimator_name = contract.validate_raw_free_identifier(
            value.estimator_name,
            field="estimator_name",
        )
        estimator_version = contract.validate_raw_free_identifier(
            value.estimator_version,
            field="estimator_version",
        )
    except contract.NeutralContractError as exc:
        raise ValueError(str(exc)) from exc
    if value.estimate_kind not in {"exact", "conservative"}:
        raise ValueError("token estimate kind is unsupported")
    for field_name, number in (
        ("exact_token_count", value.exact_token_count),
        ("conservative_token_estimate", value.conservative_token_estimate),
    ):
        if number is not None and (type(number) is not int or number < 0):
            raise ValueError(f"{field_name} must be a nonnegative integer or null")
    if value.estimate_kind == "exact":
        if value.exact_token_count is None or value.conservative_token_estimate is not None:
            raise ValueError("exact estimator must return only exact_token_count")
    elif value.conservative_token_estimate is None or value.exact_token_count is not None:
        raise ValueError("conservative estimator must return only conservative_token_estimate")
    return {
        "schema_version": TOKEN_ESTIMATE_SCHEMA_VERSION,
        "estimator_name": estimator_name,
        "estimator_version": estimator_version,
        "estimate_kind": value.estimate_kind,
        "exact_token_count": value.exact_token_count,
        "conservative_token_estimate": value.conservative_token_estimate,
    }


def build_raw_free_neutral_summary(
    request: Mapping[str, object],
    *,
    estimator: ProviderTextTokenEstimator | None = None,
) -> dict[str, object]:
    """Summarize structure and sizes without text, source IDs, or hashes."""

    validated = neutral.validate_neutral_request(request)
    units = list(neutral.iter_provider_visible_units(validated))
    authority_counts = {authority: 0 for authority in neutral.AUTHORITY_CLASSES}
    content_counts = {content_kind: 0 for content_kind in neutral.CONTENT_KINDS}
    transformation_counts = {flag: 0 for flag in neutral.TRANSFORMATION_FLAGS}
    exactness_counts = {exactness: 0 for exactness in neutral.EXACTNESS_VALUES}
    provider_texts: list[str] = []
    for unit in units:
        authority_counts[unit["authority_class"]] += 1
        content_counts[unit["content_kind"]] += 1
        exactness_counts[unit["exactness"]] += 1
        for flag in unit["transformation_flags"]:
            transformation_counts[flag] += 1
        provider_texts.append(unit["provider_text"])
    selected_estimator = estimator or Utf8ByteUpperBoundEstimator()
    token_estimate = _validate_estimate(selected_estimator.estimate(tuple(provider_texts)))
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "request_schema_version": validated["schema_version"],
        "request_model_version": validated["request_model_version"],
        "initiation_type": validated["initiation_type"],
        "unit_counts_by_authority": authority_counts,
        "unit_counts_by_content_kind": content_counts,
        "provider_text_characters": sum(len(text) for text in provider_texts),
        "provider_text_utf8_bytes": sum(len(text.encode("utf-8")) for text in provider_texts),
        "transformation_counts": transformation_counts,
        "exactness_counts": exactness_counts,
        "token_estimate": token_estimate,
    }


def validate_raw_free_neutral_summary(value: Mapping[str, object]) -> dict[str, object]:
    """Validate the exact raw-free projection shape."""

    if not isinstance(value, Mapping):
        raise ValueError("neutral summary must be an object")
    fields = (
        "schema_version",
        "request_schema_version",
        "request_model_version",
        "initiation_type",
        "unit_counts_by_authority",
        "unit_counts_by_content_kind",
        "provider_text_characters",
        "provider_text_utf8_bytes",
        "transformation_counts",
        "exactness_counts",
        "token_estimate",
    )
    if set(value) != set(fields):
        raise ValueError("neutral summary fields are closed")
    if value["schema_version"] != SUMMARY_SCHEMA_VERSION:
        raise ValueError("neutral summary schema version is invalid")
    if value["request_schema_version"] != neutral.REQUEST_SCHEMA_VERSION:
        raise ValueError("neutral summary request schema version is invalid")
    if value["request_model_version"] != neutral.REQUEST_MODEL_VERSION:
        raise ValueError("neutral summary request model version is invalid")
    if value["initiation_type"] not in neutral.INITIATION_TYPES:
        raise ValueError("neutral summary initiation type is invalid")
    expected_maps = (
        ("unit_counts_by_authority", neutral.AUTHORITY_CLASSES),
        ("unit_counts_by_content_kind", neutral.CONTENT_KINDS),
        ("transformation_counts", neutral.TRANSFORMATION_FLAGS),
        ("exactness_counts", neutral.EXACTNESS_VALUES),
    )
    for field, expected_keys in expected_maps:
        counter = value[field]
        if not isinstance(counter, Mapping) or tuple(counter) != tuple(expected_keys):
            raise ValueError(f"neutral summary {field} keys are invalid")
        if any(type(number) is not int or number < 0 for number in counter.values()):
            raise ValueError(f"neutral summary {field} values are invalid")
    for field in ("provider_text_characters", "provider_text_utf8_bytes"):
        if type(value[field]) is not int or value[field] < 0:
            raise ValueError(f"neutral summary {field} is invalid")
    token_estimate = value["token_estimate"]
    if not isinstance(token_estimate, Mapping) or set(token_estimate) != {
        "schema_version",
        "estimator_name",
        "estimator_version",
        "estimate_kind",
        "exact_token_count",
        "conservative_token_estimate",
    }:
        raise ValueError("neutral summary token estimate shape is invalid")
    if token_estimate["schema_version"] != TOKEN_ESTIMATE_SCHEMA_VERSION:
        raise ValueError("neutral summary token estimate schema is invalid")
    try:
        contract.validate_raw_free_identifier(
            token_estimate["estimator_name"],
            field="estimator_name",
        )
        contract.validate_raw_free_identifier(
            token_estimate["estimator_version"],
            field="estimator_version",
        )
    except contract.NeutralContractError as exc:
        raise ValueError(str(exc)) from exc
    estimate_kind = token_estimate["estimate_kind"]
    exact_count = token_estimate["exact_token_count"]
    conservative_count = token_estimate["conservative_token_estimate"]
    if estimate_kind not in {"exact", "conservative"}:
        raise ValueError("neutral summary token estimate kind is invalid")
    for count in (exact_count, conservative_count):
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError("neutral summary token estimate count is invalid")
    if estimate_kind == "exact":
        if exact_count is None or conservative_count is not None:
            raise ValueError("neutral summary exact token estimate is inconsistent")
    elif conservative_count is None or exact_count is not None:
        raise ValueError("neutral summary conservative token estimate is inconsistent")
    return dict(value)
