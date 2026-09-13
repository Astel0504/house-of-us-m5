"""Default-off Milestone-4 assembly over frozen Memory G and M2/M3 outputs.

This owner consumes already-selected, copy-backed provider sections.  It does
not retrieve, activate, promote, or write Memory, Vault, Source, M2, or M3
authority.  Its only persistence is an append-only raw-free selection and
rollback receipt journal.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "house_continuity_v1_2_milestone4_memory_integration_local_v1"
STORE_SCHEMA_VERSION = "house_continuity_milestone4_integration_store_v1"
MANIFEST_SCHEMA_VERSION = "house_continuity_milestone4_copy_manifest_v1"
SELECTION_RECEIPT_SCHEMA_VERSION = "house_continuity_milestone4_selection_receipt_v1"
ROLLBACK_RECEIPT_SCHEMA_VERSION = "house_continuity_milestone4_rollback_receipt_v1"
CANONICAL_JSON_VERSION = "sorted_json_utf8_v1"
PROVIDER_PARAGRAPH_DOMAIN = "m4_provider_visible_paragraph_utf8_v1"
PROVIDER_LIST_DOMAIN = "m4_dynamic_context_field_sorted_json_utf8_v1"
PROVIDER_LIST_CONVERSION = "m4_dynamic_context_field_projection_v1"
RECEIPT_DOMAIN = "m4_raw_free_receipt_sorted_json_utf8_v1"
ADMISSION_POLICY_VERSION = "m5_intent_recent_before_ambient_no_leapfrog_v1"

SWITCH_ENV = "HOUSE_CONTINUITY_V1_2_MILESTONE4_MEMORY_INTEGRATION"
ROOT_ENV = "HOUSE_CONTINUITY_V1_2_MILESTONE2_ROOT"
SELECTOR_ENV = "HOUSE_CONTINUITY_V1_2_MILESTONE4_SELECTOR"
BUDGET_ENV = "HOUSE_CONTINUITY_V1_2_MILESTONE4_BUDGET_CHARS"
OFF = "off"
ON = "on"
COPY_REHEARSAL = "copy_rehearsal"
DEFAULT_BUDGET_CHARS = 24_000
MAX_BUDGET_CHARS = 200_000

ATTACHMENT_AUTHORITIES = (
    "memory_g",
    "vault_recall",
    "exact_recall",
    "recent_turns",
    "sources",
)
ATTACHMENT_STATES = frozenset(
    {"selected", "authoritative_empty", "no_match", "unavailable", "denied"}
)
OUTPUT_SECTION_BY_AUTHORITY = {
    "memory_g": "m4_memory_g_context",
    "vault_recall": "m4_vault_recall",
    "exact_recall": "m4_exact_recall",
    "m2_continuity": "continuity_working_set",
    "m3_cold": "continuity_cold_context",
    "m3_warm": "continuity_warm_context",
    "m3_hot": "continuity_hot_context",
    "recent_turns": "m4_recent_turns",
    "sources": "m4_source_context",
}
INPUT_SECTION_CONTRACT_BY_AUTHORITY = {
    "memory_g": (
        "memory_context",
        frozenset({"vault_memory_recall", "memory_context"}),
        frozenset({"per_turn"}),
    ),
    "vault_recall": (
        "vault_recall",
        frozenset({"vault_memory_recall", "vault_recall"}),
        frozenset({"per_turn"}),
    ),
    "exact_recall": (
        "exact_recall",
        frozenset({"exact_recall"}),
        frozenset({"per_turn"}),
    ),
    "m2_continuity": (
        "continuity_working_set",
        frozenset({"continuity_working_set"}),
        frozenset({"per_turn"}),
    ),
    "m3_cold": (
        "continuity_cold_context",
        frozenset({"continuity_cold_context"}),
        frozenset({"per_turn"}),
    ),
    "m3_warm": (
        "continuity_warm_context",
        frozenset({"continuity_warm_context"}),
        frozenset({"per_turn"}),
    ),
    "m3_hot": (
        "continuity_hot_context",
        frozenset({"continuity_hot_context"}),
        frozenset({"per_turn"}),
    ),
    "recent_turns": (
        "recent_visible_exchange",
        frozenset({"recent_exact_current_session", "recent_visible_exchange"}),
        frozenset({"append_only", "per_turn"}),
    ),
    "sources": (
        "read_mode_source_context",
        frozenset({"timeline_source_attachment", "read_mode_source_context"}),
        frozenset({"per_turn"}),
    ),
}
OUTPUT_SECTION_ORDER = (
    "m4_memory_g_context",
    "m4_vault_recall",
    "m4_exact_recall",
    "continuity_working_set",
    "m4_authority_conflict_notice",
    "continuity_cold_context",
    "continuity_warm_context",
    "continuity_hot_context",
    "m4_recent_turns",
    "m4_source_context",
)
MANDATORY_INTENT_SECTION_IDS = frozenset(
    {"m4_exact_recall", "continuity_cold_context"}
)
OPTIONAL_ADMISSION_PRIORITY = (
    "continuity_hot_context",
    "m4_recent_turns",
    "continuity_warm_context",
    "m4_source_context",
    "m4_memory_g_context",
    "m4_vault_recall",
)
MANAGED_INPUT_SECTION_IDS = frozenset(
    {
        "memory_context",
        "vault_recall",
        "read_mode_exact_text",
        "recent_visible_exchange",
        "read_mode_source_context",
        *OUTPUT_SECTION_ORDER,
    }
)
_M3_AUTHORITY_BY_SECTION = {
    "continuity_cold_context": "m3_cold",
    "continuity_warm_context": "m3_warm",
    "continuity_hot_context": "m3_hot",
}
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n[ \t]*\n")


class Milestone4IntegrationError(ValueError):
    pass


def _fail(code: str) -> None:
    raise Milestone4IntegrationError(code)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def copy_root_identity(root: str | Path) -> str:
    resolved = str(Path(root).resolve()).replace("\\", "/").casefold()
    return hashlib.sha256(
        ("house:m4:copy-root:v1\n" + resolved).encode("utf-8")
    ).hexdigest()


def _identifier(value: Any, *, code: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        _fail(code)
    return value


def _sha(value: Any, *, code: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        _fail(code)
    return value


def _strict_int(value: Any, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail("m4_integer_invalid")
    return value


def _exact_fields(value: Any, fields: set[str], *, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        _fail(code)
    return value


def _normalized_section(value: Any, *, authority: str) -> dict[str, str]:
    raw = _exact_fields(
        value,
        {
            "section_id",
            "section_class",
            "exactness",
            "update_frequency",
            "rendered_text",
        },
        code="m4_section_shape_invalid",
    )
    expected_id, accepted_classes, accepted_frequencies = (
        INPUT_SECTION_CONTRACT_BY_AUTHORITY[authority]
    )
    if (
        raw.get("section_id") != expected_id
        or raw.get("section_class") not in accepted_classes
        or raw.get("update_frequency") not in accepted_frequencies
    ):
        _fail("m4_section_authority_mismatch")
    if (
        raw.get("exactness") not in {"exact", "derived", "mixed"}
        or not isinstance(raw.get("rendered_text"), str)
        or not raw["rendered_text"].strip()
    ):
        _fail("m4_section_value_invalid")
    section_id = OUTPUT_SECTION_BY_AUTHORITY[authority]
    return {
        "section_id": section_id,
        "section_class": section_id,
        "exactness": str(raw["exactness"]),
        "update_frequency": "per_turn",
        "rendered_text": str(raw["rendered_text"]),
    }


def _normalize_journal(value: Any, *, code: str) -> dict[str, str]:
    raw = _exact_fields(
        value,
        {"owner", "domain", "identity"},
        code=code,
    )
    return {
        "owner": _identifier(raw["owner"], code=code),
        "domain": _identifier(raw["domain"], code=code),
        "identity": _sha(raw["identity"], code=code),
    }


def _normalize_claim(value: Any) -> dict[str, Any]:
    raw = _exact_fields(
        value,
        {"claim_key_hash", "value_sha256", "observed_at_epoch_millis"},
        code="m4_claim_invalid",
    )
    return {
        "claim_key_hash": _sha(raw["claim_key_hash"], code="m4_claim_invalid"),
        "value_sha256": _sha(raw["value_sha256"], code="m4_claim_invalid"),
        "observed_at_epoch_millis": _strict_int(
            raw["observed_at_epoch_millis"]
        ),
    }


def _normalize_provenance(value: Any) -> dict[str, Any]:
    raw = _exact_fields(
        value,
        {
            "owner",
            "selection_identity",
            "predecessor_identity",
            "evidence_domain",
            "canonicalization_version",
            "freshness",
            "observed_at_epoch_millis",
            "selection_journal_domain",
            "selection_journal_identity",
        },
        code="m4_provenance_invalid",
    )
    predecessor = raw["predecessor_identity"]
    if predecessor is not None:
        predecessor = _sha(predecessor, code="m4_provenance_invalid")
    observed = raw["observed_at_epoch_millis"]
    if observed is not None:
        observed = _strict_int(observed)
    return {
        "owner": _identifier(raw["owner"], code="m4_provenance_invalid"),
        "selection_identity": _sha(
            raw["selection_identity"], code="m4_provenance_invalid"
        ),
        "predecessor_identity": predecessor,
        "evidence_domain": _identifier(
            raw["evidence_domain"], code="m4_provenance_invalid"
        ),
        "canonicalization_version": _identifier(
            raw["canonicalization_version"], code="m4_provenance_invalid"
        ),
        "freshness": _identifier(
            raw["freshness"], code="m4_provenance_invalid"
        ),
        "observed_at_epoch_millis": observed,
        "selection_journal_domain": _identifier(
            raw["selection_journal_domain"], code="m4_provenance_invalid"
        ),
        "selection_journal_identity": _sha(
            raw["selection_journal_identity"], code="m4_provenance_invalid"
        ),
    }


def _normalize_exact_conversion(value: Any, *, section: Mapping[str, str]) -> dict[str, Any]:
    raw = _exact_fields(
        value,
        {
            "source_identity",
            "source_domain",
            "source_canonicalization_version",
            "source_text",
            "provider_prefix",
            "provider_suffix",
            "conversion_identity",
        },
        code="m4_exact_conversion_invalid",
    )
    for field in ("source_text", "provider_prefix", "provider_suffix"):
        if not isinstance(raw[field], str):
            _fail("m4_exact_conversion_invalid")
    if (
        raw["conversion_identity"] != "m4_exact_source_prefix_suffix_v1"
        or section["exactness"] != "exact"
        or section["rendered_text"]
        != raw["provider_prefix"] + raw["source_text"] + raw["provider_suffix"]
    ):
        _fail("m4_exact_source_not_preserved")
    return {
        "source_identity": _sha(
            raw["source_identity"], code="m4_exact_conversion_invalid"
        ),
        "source_domain": _identifier(
            raw["source_domain"], code="m4_exact_conversion_invalid"
        ),
        "source_canonicalization_version": _identifier(
            raw["source_canonicalization_version"],
            code="m4_exact_conversion_invalid",
        ),
        "source_text": raw["source_text"],
        "provider_prefix": raw["provider_prefix"],
        "provider_suffix": raw["provider_suffix"],
        "conversion_identity": raw["conversion_identity"],
    }


def _normalize_attachment(value: Any) -> dict[str, Any]:
    raw = _exact_fields(
        value,
        {
            "attachment_id",
            "authority",
            "state",
            "provenance",
            "section",
            "claims",
            "exact_conversion",
        },
        code="m4_attachment_invalid",
    )
    authority = raw["authority"]
    state = raw["state"]
    if authority not in ATTACHMENT_AUTHORITIES or state not in ATTACHMENT_STATES:
        _fail("m4_attachment_invalid")
    section = None
    if state == "selected":
        section = _normalized_section(raw["section"], authority=authority)
    elif raw["section"] is not None:
        _fail("m4_absence_section_invalid")
    claims_raw = raw["claims"]
    if not isinstance(claims_raw, list):
        _fail("m4_claim_invalid")
    claims = [_normalize_claim(item) for item in claims_raw]
    if len({item["claim_key_hash"] for item in claims}) != len(claims):
        _fail("m4_claim_duplicate")
    exact_conversion = raw["exact_conversion"]
    if authority == "exact_recall" and state == "selected":
        exact_conversion = _normalize_exact_conversion(
            exact_conversion, section=section
        )
    elif exact_conversion is not None:
        _fail("m4_exact_conversion_unexpected")
    return {
        "attachment_id": _identifier(
            raw["attachment_id"], code="m4_attachment_invalid"
        ),
        "authority": authority,
        "state": state,
        "provenance": _normalize_provenance(raw["provenance"]),
        "section": section,
        "claims": claims,
        "exact_conversion": exact_conversion,
    }


def validate_manifest(
    value: Any, *, root: str | Path, room_id: str
) -> dict[str, Any]:
    raw = _exact_fields(
        value,
        {
            "schema_version",
            "copy_root_identity",
            "room_id",
            "memory_selection_journal",
            "continuity_selection_journal",
            "m2_freshness_epoch_millis",
            "m2_claims",
            "attachments",
        },
        code="m4_manifest_invalid",
    )
    if (
        raw["schema_version"] != MANIFEST_SCHEMA_VERSION
        or raw["copy_root_identity"] != copy_root_identity(root)
        or raw["room_id"] != room_id
    ):
        _fail("m4_manifest_binding_invalid")
    memory_journal = _normalize_journal(
        raw["memory_selection_journal"], code="m4_memory_journal_invalid"
    )
    continuity_journal = _normalize_journal(
        raw["continuity_selection_journal"],
        code="m4_continuity_journal_invalid",
    )
    if (
        memory_journal["owner"] == continuity_journal["owner"]
        or memory_journal["domain"] == continuity_journal["domain"]
        or memory_journal["identity"] == continuity_journal["identity"]
    ):
        _fail("m4_authority_journals_not_separate")
    attachments_raw = raw["attachments"]
    if not isinstance(attachments_raw, list):
        _fail("m4_manifest_invalid")
    attachments = [_normalize_attachment(item) for item in attachments_raw]
    authorities = [item["authority"] for item in attachments]
    if tuple(authorities) != ATTACHMENT_AUTHORITIES:
        _fail("m4_attachment_order_invalid")
    m2_claims_raw = raw["m2_claims"]
    if not isinstance(m2_claims_raw, list):
        _fail("m4_claim_invalid")
    m2_claims = [_normalize_claim(item) for item in m2_claims_raw]
    if len({item["claim_key_hash"] for item in m2_claims}) != len(m2_claims):
        _fail("m4_claim_duplicate")
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "copy_root_identity": raw["copy_root_identity"],
        "room_id": room_id,
        "memory_selection_journal": memory_journal,
        "continuity_selection_journal": continuity_journal,
        "m2_freshness_epoch_millis": _strict_int(
            raw["m2_freshness_epoch_millis"]
        ),
        "m2_claims": m2_claims,
        "attachments": attachments,
    }


def _section_identity(section: Mapping[str, Any]) -> dict[str, str]:
    return {
        "section_id": str(section["section_id"]),
        "section_sha256": canonical_sha256(section),
        "section_domain": "m4_typed_provider_section_sorted_json_utf8_v1",
        "canonicalization_version": CANONICAL_JSON_VERSION,
    }


def _provider_list_representation(sections: Sequence[Mapping[str, Any]]) -> str:
    texts = [str(section["rendered_text"]) for section in sections]
    return _dynamic_context_field_representation(texts)


def _dynamic_context_field_representation(values: Sequence[str]) -> str:
    return '"dynamic_context":' + canonical_json_bytes(list(values)).decode("utf-8")


def _final_provider_list_representation(
    sections: Sequence[Mapping[str, Any]],
    *,
    preserved_dynamic_context: Sequence[str],
    final_dynamic_context_suffix: Sequence[str],
) -> str:
    return _dynamic_context_field_representation(
        [
            *preserved_dynamic_context,
            *(str(section["rendered_text"]) for section in sections),
            *final_dynamic_context_suffix,
        ]
    )


def _safe_attachment_receipt(attachment: Mapping[str, Any]) -> dict[str, Any]:
    provenance = attachment["provenance"]
    exact_conversion = attachment["exact_conversion"]
    return {
        "attachment_id": attachment["attachment_id"],
        "authority": attachment["authority"],
        "state": attachment["state"],
        "authority_owner": provenance["owner"],
        "selection_identity": provenance["selection_identity"],
        "predecessor_identity": provenance["predecessor_identity"],
        "evidence_domain": provenance["evidence_domain"],
        "canonicalization_version": provenance["canonicalization_version"],
        "freshness": provenance["freshness"],
        "observed_at_epoch_millis": provenance["observed_at_epoch_millis"],
        "selection_journal_domain": provenance["selection_journal_domain"],
        "selection_journal_identity": provenance["selection_journal_identity"],
        "selected_section_identity": (
            _section_identity(attachment["section"])
            if attachment["section"] is not None
            else None
        ),
        "exact_conversion": (
            {
                "source_identity": exact_conversion["source_identity"],
                "source_domain": exact_conversion["source_domain"],
                "source_canonicalization_version": exact_conversion[
                    "source_canonicalization_version"
                ],
                "source_text_sha256": _text_sha256(
                    exact_conversion["source_text"]
                ),
                "provider_text_sha256": _text_sha256(
                    attachment["section"]["rendered_text"]
                ),
                "output_domain": PROVIDER_PARAGRAPH_DOMAIN,
                "output_canonicalization_version": "utf8_no_normalization_v1",
                "conversion_identity": exact_conversion["conversion_identity"],
                "source_subsequence_preserved": True,
                "cross_domain_equal": None,
                "comparison_state": "canonical_conversion_bound",
            }
            if exact_conversion is not None
            else None
        ),
    }


def evidence_equality_receipt(
    *,
    left_bytes: bytes,
    left_domain: str,
    left_canonicalization_version: str,
    left_identity: str,
    right_bytes: bytes,
    right_domain: str,
    right_canonicalization_version: str,
    right_identity: str,
    conversion_identity: str | None = None,
) -> dict[str, Any]:
    same_domain = (
        left_domain == right_domain
        and left_canonicalization_version == right_canonicalization_version
    )
    if not same_domain and conversion_identity is None:
        state = "domain_mismatch"
        equal = None
    elif not same_domain:
        state = "canonical_conversion_required"
        equal = None
    else:
        state = "same_domain_compared"
        equal = left_bytes == right_bytes
    return {
        "left_domain": left_domain,
        "left_canonicalization_version": left_canonicalization_version,
        "left_identity": left_identity,
        "left_sha256": hashlib.sha256(left_bytes).hexdigest(),
        "right_domain": right_domain,
        "right_canonicalization_version": right_canonicalization_version,
        "right_identity": right_identity,
        "right_sha256": hashlib.sha256(right_bytes).hexdigest(),
        "conversion_identity": conversion_identity,
        "comparison_state": state,
        "equal": equal,
    }


def validate_integrated_sections(
    values: Sequence[Mapping[str, Any]] | None,
) -> tuple[dict[str, str], ...]:
    if values is None or not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        _fail("m4_integrated_sections_invalid")
    normalized = []
    seen = []
    for value in values:
        if not isinstance(value, Mapping) or set(value) != {
            "section_id",
            "section_class",
            "exactness",
            "update_frequency",
            "rendered_text",
        }:
            _fail("m4_integrated_sections_invalid")
        section_id = value.get("section_id")
        if (
            section_id not in OUTPUT_SECTION_ORDER
            or value.get("section_class") != section_id
            or value.get("exactness") not in {"exact", "derived", "mixed"}
            or value.get("update_frequency") != "per_turn"
            or not isinstance(value.get("rendered_text"), str)
            or not value["rendered_text"].strip()
        ):
            _fail("m4_integrated_sections_invalid")
        seen.append(section_id)
        normalized.append(deepcopy(dict(value)))
    if (
        len(seen) != len(set(seen))
        or seen != sorted(seen, key=OUTPUT_SECTION_ORDER.index)
        or seen.count("continuity_working_set") != 1
    ):
        _fail("m4_integrated_sections_invalid")
    return tuple(normalized)


class Milestone4IntegrationStore:
    """Append-only raw-free M4 receipt owner; never a semantic authority."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "milestone4_receipts.sqlite3"
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)"
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS receipts(
              attempt_id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              request_sha256 TEXT NOT NULL,
              receipt_json TEXT NOT NULL
            )
            """
        )
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO metadata(key,value) VALUES('schema_version',?)",
                (STORE_SCHEMA_VERSION,),
            )
            self.connection.commit()
        elif row["value"] != STORE_SCHEMA_VERSION:
            self.connection.close()
            _fail("m4_store_schema_unknown")

    def close(self) -> None:
        self.connection.close()

    def receipt(self, attempt_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT receipt_json FROM receipts WHERE attempt_id=?", (attempt_id,)
        ).fetchone()
        return json.loads(row["receipt_json"]) if row is not None else None

    def _persist_receipt(
        self,
        *,
        attempt_id: str,
        kind: str,
        request: Mapping[str, Any],
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        attempt_id = _identifier(attempt_id, code="m4_attempt_id_invalid")
        request_sha = canonical_sha256(request)
        receipt_body = dict(body)
        receipt = {
            **receipt_body,
            "receipt_domain": RECEIPT_DOMAIN,
            "receipt_canonicalization_version": CANONICAL_JSON_VERSION,
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.connection.execute(
                "SELECT kind,request_sha256,receipt_json FROM receipts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if existing is not None:
                stored = json.loads(existing["receipt_json"])
                if existing["kind"] != kind or existing["request_sha256"] != request_sha:
                    _fail("m4_attempt_replay_conflict")
                if stored != receipt:
                    _fail("m4_attempt_replay_result_changed")
                self.connection.commit()
                return stored
            self.connection.execute(
                "INSERT INTO receipts(attempt_id,kind,request_sha256,receipt_json) VALUES(?,?,?,?)",
                (
                    attempt_id,
                    kind,
                    request_sha,
                    canonical_json_bytes(receipt).decode("utf-8"),
                ),
            )
            self.connection.commit()
            return receipt
        except Exception:
            self.connection.rollback()
            raise

    def assemble_provider_sections(
        self,
        *,
        manifest: Mapping[str, Any],
        required_m2_section: Mapping[str, Any],
        m3_sections: Sequence[Mapping[str, Any]],
        budget_chars: int,
        attempt_id: str,
        preserved_dynamic_context: Sequence[str] = (),
        final_dynamic_context_suffix: Sequence[str] = (),
    ) -> dict[str, Any]:
        budget_chars = _strict_int(budget_chars, minimum=1)
        if budget_chars > MAX_BUDGET_CHARS:
            _fail("m4_budget_invalid")
        for values in (preserved_dynamic_context, final_dynamic_context_suffix):
            if (
                not isinstance(values, Sequence)
                or isinstance(values, (str, bytes))
                or any(not isinstance(value, str) for value in values)
            ):
                _fail("m4_final_dynamic_context_invalid")
        preserved_dynamic_context = tuple(preserved_dynamic_context)
        final_dynamic_context_suffix = tuple(final_dynamic_context_suffix)
        if (
            not isinstance(required_m2_section, Mapping)
            or required_m2_section.get("section_id") != "continuity_working_set"
        ):
            _fail("m4_required_m2_missing")
        m2_section = _normalized_section(
            required_m2_section, authority="m2_continuity"
        )
        if not isinstance(m3_sections, Sequence) or isinstance(m3_sections, (str, bytes)):
            _fail("m4_m3_sections_invalid")
        normalized_m3: list[dict[str, Any]] = []
        for section in m3_sections:
            if not isinstance(section, Mapping):
                _fail("m4_m3_sections_invalid")
            authority = _M3_AUTHORITY_BY_SECTION.get(section.get("section_id"))
            if authority is None:
                _fail("m4_m3_sections_invalid")
            normalized_m3.append(
                {
                    "authority": authority,
                    "section": _normalized_section(section, authority=authority),
                }
            )
        if [item["authority"] for item in normalized_m3] != sorted(
            [item["authority"] for item in normalized_m3],
            key=("m3_cold", "m3_warm", "m3_hot").index,
        ):
            _fail("m4_m3_sections_invalid")

        attachments = [deepcopy(item) for item in manifest["attachments"]]
        m2_claims = {item["claim_key_hash"]: item for item in manifest["m2_claims"]}
        conflict_receipts = []
        suppressed_attachment_ids: set[str] = set()
        for attachment in attachments:
            if attachment["authority"] != "memory_g" or attachment["state"] != "selected":
                continue
            for claim in attachment["claims"]:
                active = m2_claims.get(claim["claim_key_hash"])
                if active is None or active["value_sha256"] == claim["value_sha256"]:
                    continue
                suppressed_attachment_ids.add(attachment["attachment_id"])
                conflict_receipts.append(
                    {
                        "claim_key_hash": claim["claim_key_hash"],
                        "memory_value_sha256": claim["value_sha256"],
                        "m2_value_sha256": active["value_sha256"],
                        "memory_observed_at_epoch_millis": claim[
                            "observed_at_epoch_millis"
                        ],
                        "m2_observed_at_epoch_millis": active[
                            "observed_at_epoch_millis"
                        ],
                        "freshness_relation": (
                            "m2_newer"
                            if active["observed_at_epoch_millis"]
                            > claim["observed_at_epoch_millis"]
                            else "same_time"
                            if active["observed_at_epoch_millis"]
                            == claim["observed_at_epoch_millis"]
                            else "memory_newer_but_m2_active_authority"
                        ),
                        "resolution": "m2_active_authority_wins",
                        "canonical_memory_rewritten": False,
                        "canonical_m2_rewritten": False,
                    }
                )

        candidates: list[dict[str, Any]] = []
        for attachment in attachments:
            if (
                attachment["state"] == "selected"
                and attachment["attachment_id"] not in suppressed_attachment_ids
            ):
                candidates.append(
                    {
                        "authority": attachment["authority"],
                        "attachment": attachment,
                        "section": deepcopy(attachment["section"]),
                    }
                )
        candidates.append(
            {
                "authority": "m2_continuity",
                "attachment": None,
                "section": m2_section,
            }
        )
        if conflict_receipts:
            candidates.append(
                {
                    "authority": "m2_conflict_notice",
                    "attachment": None,
                    "section": {
                        "section_id": "m4_authority_conflict_notice",
                        "section_class": "m4_authority_conflict_notice",
                        "exactness": "derived",
                        "update_frequency": "per_turn",
                        "rendered_text": (
                            "Memory/continuity authority note:\n"
                            "- Older or conflicting durable memory was withheld; "
                            "current structured continuity remains active truth."
                        ),
                    },
                }
            )
        candidates.extend(
            {
                "authority": item["authority"],
                "attachment": None,
                "section": item["section"],
            }
            for item in normalized_m3
        )
        candidates.sort(
            key=lambda item: OUTPUT_SECTION_ORDER.index(item["section"]["section_id"])
        )

        paragraph_entries = []
        for candidate_index, candidate in enumerate(candidates):
            text = candidate["section"]["rendered_text"]
            paragraphs = [item for item in _PARAGRAPH_SPLIT_RE.split(text) if item]
            for paragraph_index, paragraph in enumerate(paragraphs):
                paragraph_entries.append(
                    {
                        "candidate_index": candidate_index,
                        "paragraph_index": paragraph_index,
                        "text": paragraph,
                        "sha256": _text_sha256(paragraph),
                        "exactness": candidate["section"]["exactness"],
                    }
                )
        winners: dict[str, dict[str, Any]] = {}
        exactness_rank = {"derived": 0, "mixed": 1, "exact": 2}
        for entry in paragraph_entries:
            current = winners.get(entry["text"])
            entry_section_id = candidates[entry["candidate_index"]]["section"][
                "section_id"
            ]
            entry_rank = (
                3
                if entry_section_id
                in {"continuity_working_set", "m4_authority_conflict_notice"}
                else exactness_rank[entry["exactness"]]
            )
            current_section_id = (
                candidates[current["candidate_index"]]["section"]["section_id"]
                if current is not None
                else None
            )
            current_rank = (
                3
                if current_section_id
                in {"continuity_working_set", "m4_authority_conflict_notice"}
                else exactness_rank[current["exactness"]]
                if current is not None
                else -1
            )
            if current is None or entry_rank > current_rank:
                winners[entry["text"]] = entry
        duplicate_receipts = []
        losing_entries_by_candidate: dict[int, list[dict[str, Any]]] = {}

        def source_descriptor(candidate: Mapping[str, Any]) -> dict[str, Any]:
            if candidate["attachment"] is not None:
                provenance = candidate["attachment"]["provenance"]
                return {
                    "domain": provenance["evidence_domain"],
                    "canonicalization_version": provenance[
                        "canonicalization_version"
                    ],
                    "identity": provenance["selection_identity"],
                }
            section_id = candidate["section"]["section_id"]
            return {
                "domain": (
                    "m2_provider_section_sorted_json_utf8_v1"
                    if section_id == "continuity_working_set"
                    else "m4_raw_free_authority_conflict_receipt_v1"
                    if section_id == "m4_authority_conflict_notice"
                    else "m3_typed_provider_section_sorted_json_utf8_v1"
                ),
                "canonicalization_version": CANONICAL_JSON_VERSION,
                "identity": canonical_sha256(candidate["section"]),
            }

        for entry in paragraph_entries:
            winner = winners[entry["text"]]
            if entry is winner:
                continue
            left = candidates[entry["candidate_index"]]
            right = candidates[winner["candidate_index"]]
            duplicate_section_ids = {
                left["section"]["section_id"], right["section"]["section_id"]
            }
            duplicate_exactness = {
                left["section"]["exactness"], right["section"]["exactness"]
            }
            if (
                "continuity_working_set" in duplicate_section_ids
                and "exact" in duplicate_exactness
            ):
                _fail("m4_exact_m2_duplicate_conflict")
            if left["section"]["section_id"] in {
                "continuity_working_set",
                "m4_authority_conflict_notice",
            }:
                _fail("m4_required_section_duplicate")
            losing_entries_by_candidate.setdefault(
                entry["candidate_index"], []
            ).append(entry)
            left_source = source_descriptor(left)
            right_source = source_descriptor(right)
            duplicate_receipts.append(
                {
                    "provider_paragraph_sha256": entry["sha256"],
                    "omitted_section_id": left["section"]["section_id"],
                    "retained_section_id": right["section"]["section_id"],
                    "reason": "pending_dedup_action",
                    "whole_section_omitted": None,
                    "exact_source_clipped": False,
                    "provider_domain_comparison": evidence_equality_receipt(
                        left_bytes=entry["text"].encode("utf-8"),
                        left_domain=PROVIDER_PARAGRAPH_DOMAIN,
                        left_canonicalization_version="utf8_no_normalization_v1",
                        left_identity=entry["sha256"],
                        right_bytes=winner["text"].encode("utf-8"),
                        right_domain=PROVIDER_PARAGRAPH_DOMAIN,
                        right_canonicalization_version="utf8_no_normalization_v1",
                        right_identity=winner["sha256"],
                    ),
                    "source_domain_comparison": {
                        "left_domain": left_source["domain"],
                        "left_canonicalization_version": left_source[
                            "canonicalization_version"
                        ],
                        "left_identity": left_source["identity"],
                        "right_domain": right_source["domain"],
                        "right_canonicalization_version": right_source[
                            "canonicalization_version"
                        ],
                        "right_identity": right_source["identity"],
                        "conversion_identity": None,
                        "comparison_state": "source_bytes_unavailable",
                        "equal": None,
                    },
                }
            )
        deduplicated_candidates = []
        dedup_action_by_section_id: dict[str, str] = {}
        dedup_transformed_section_ids: set[str] = set()
        for index, candidate in enumerate(candidates):
            losing_entries = losing_entries_by_candidate.get(index, [])
            section_id = candidate["section"]["section_id"]
            if not losing_entries:
                deduplicated_candidates.append(deepcopy(candidate))
                continue
            candidate_entries = [
                item
                for item in paragraph_entries
                if item["candidate_index"] == index
            ]
            if len(losing_entries) == len(candidate_entries):
                dedup_action_by_section_id[section_id] = "whole_section_omitted"
                continue
            if (
                candidate["section"]["exactness"] == "exact"
                or section_id in _M3_AUTHORITY_BY_SECTION
            ):
                _fail("m4_partial_dedup_unsafe")
            kept_paragraphs = [
                item["text"]
                for item in candidate_entries
                if item not in losing_entries
            ]
            updated = deepcopy(candidate)
            updated["section"]["rendered_text"] = "\n\n".join(kept_paragraphs)
            deduplicated_candidates.append(updated)
            dedup_action_by_section_id[section_id] = "duplicate_paragraph_removed"
            dedup_transformed_section_ids.add(section_id)
        for duplicate_receipt in duplicate_receipts:
            action = dedup_action_by_section_id[
                duplicate_receipt["omitted_section_id"]
            ]
            duplicate_receipt["reason"] = action
            duplicate_receipt["whole_section_omitted"] = (
                action == "whole_section_omitted"
            )
            duplicate_receipt["conversion_identity"] = (
                "m4_remove_duplicate_paragraphs_join_v1"
                if action == "duplicate_paragraph_removed"
                else "m4_whole_section_duplicate_omission_v1"
            )
        dedup_surviving_section_ids = {
            item["section"]["section_id"] for item in deduplicated_candidates
        }

        relationship_receipts = []
        selected_attachments = [
            item for item in attachments if item["state"] == "selected"
        ]
        for left_index, left in enumerate(selected_attachments):
            left_claims = {item["claim_key_hash"]: item for item in left["claims"]}
            for right in selected_attachments[left_index + 1 :]:
                for key in sorted(left_claims.keys() & {item["claim_key_hash"] for item in right["claims"]}):
                    right_claim = next(item for item in right["claims"] if item["claim_key_hash"] == key)
                    if left_claims[key]["value_sha256"] != right_claim["value_sha256"]:
                        continue
                    if left["section"]["rendered_text"] == right["section"]["rendered_text"]:
                        continue
                    left_section_id = OUTPUT_SECTION_BY_AUTHORITY[left["authority"]]
                    right_section_id = OUTPUT_SECTION_BY_AUTHORITY[right["authority"]]
                    relationship_receipts.append(
                        {
                            "claim_key_hash": key,
                            "value_sha256": right_claim["value_sha256"],
                            "left_attachment_id": left["attachment_id"],
                            "right_attachment_id": right["attachment_id"],
                            "relationship": "related_not_canonically_equal",
                            "provider_representation_equal": False,
                            "source_equality": None,
                            "comparison_state": "domain_mismatch",
                            "both_retained": (
                                left_section_id in dedup_surviving_section_ids
                                and right_section_id in dedup_surviving_section_ids
                            ),
                        }
                    )

        mandatory_ids = {"continuity_working_set"}
        if conflict_receipts:
            mandatory_ids.add("m4_authority_conflict_notice")
        mandatory_ids.update(
            item["section"]["section_id"]
            for item in deduplicated_candidates
            if item["section"]["section_id"] in MANDATORY_INTENT_SECTION_IDS
        )
        selected_sections = [
            deepcopy(item["section"])
            for item in deduplicated_candidates
            if item["section"]["section_id"] in mandatory_ids
        ]
        mandatory_representation = _final_provider_list_representation(
            selected_sections,
            preserved_dynamic_context=preserved_dynamic_context,
            final_dynamic_context_suffix=final_dynamic_context_suffix,
        )
        if len(mandatory_representation) > budget_chars:
            body = {
                "schema_version": SELECTION_RECEIPT_SCHEMA_VERSION,
                "attempt_id": attempt_id,
                "state": (
                    "required_intent_evidence_budget_failed_closed"
                    if mandatory_ids & MANDATORY_INTENT_SECTION_IDS
                    else "required_m2_budget_failed_closed"
                ),
                "provider_render_order": list(OUTPUT_SECTION_ORDER),
                "admission_policy_version": ADMISSION_POLICY_VERSION,
                "mandatory_section_ids": sorted(
                    mandatory_ids,
                    key=OUTPUT_SECTION_ORDER.index,
                ),
                "budget_chars": budget_chars,
                "budget_domain": PROVIDER_LIST_DOMAIN,
                "budget_canonicalization_version": CANONICAL_JSON_VERSION,
                "conversion_identity": PROVIDER_LIST_CONVERSION,
                "required_representation_chars": len(mandatory_representation),
                "preserved_dynamic_context_count": len(preserved_dynamic_context),
                "final_dynamic_context_suffix_count": len(final_dynamic_context_suffix),
                "m2_suppressed": False,
                "selected_section_identities": [],
                "admission_receipts": [
                    {
                        "section_id": item["section"]["section_id"],
                        "state": "failed_closed_required_budget",
                        "priority_rank": None,
                        "reason": "mandatory_representation_exceeds_budget",
                    }
                    for item in deduplicated_candidates
                ],
                "omission_receipts": [],
                "raw_material_present_in_receipt": False,
                "canonical_writes": {
                    "memory": False,
                    "vault": False,
                    "m2": False,
                    "m3": False,
                    "self_state": False,
                    "source": False,
                },
            }
            request = {
                "operation": "selection",
                "manifest_sha256": canonical_sha256(manifest),
                "m2_section_sha256": canonical_sha256(m2_section),
                "m3_sections_sha256": canonical_sha256(
                    [item["section"] for item in normalized_m3]
                ),
                "budget_chars": budget_chars,
                "preserved_dynamic_context_sha256": canonical_sha256(
                    list(preserved_dynamic_context)
                ),
                "final_dynamic_context_suffix_sha256": canonical_sha256(
                    list(final_dynamic_context_suffix)
                ),
            }
            receipt = self._persist_receipt(
                attempt_id=attempt_id, kind="selection", request=request, body=body
            )
            return {"state": "failed_closed", "sections": [], "receipt": receipt}

        selected_ids = {section["section_id"] for section in selected_sections}
        omission_receipts = []
        admission_receipts = [
            {
                "section_id": section["section_id"],
                "state": "admitted_mandatory",
                "priority_rank": None,
                "reason": "m2_or_intent_bound_required",
            }
            for section in selected_sections
        ]
        optional_by_id = {
            item["section"]["section_id"]: item
            for item in deduplicated_candidates
            if item["section"]["section_id"] not in mandatory_ids
        }
        blocked_by_higher_priority = False
        for priority_rank, section_id in enumerate(OPTIONAL_ADMISSION_PRIORITY):
            candidate = optional_by_id.get(section_id)
            if candidate is None:
                continue
            section = candidate["section"]
            if blocked_by_higher_priority:
                omission_receipts.append(
                    {
                        "section_id": section_id,
                        "section_sha256": canonical_sha256(section),
                        "reason": "lower_priority_blocked_after_budget_omission",
                        "exact_source_clipped": False,
                    }
                )
                admission_receipts.append(
                    {
                        "section_id": section_id,
                        "state": "omitted",
                        "priority_rank": priority_rank,
                        "reason": "lower_priority_blocked_after_budget_omission",
                    }
                )
                continue
            insert_at = sum(
                OUTPUT_SECTION_ORDER.index(existing["section_id"])
                < OUTPUT_SECTION_ORDER.index(section["section_id"])
                for existing in selected_sections
            )
            proposal = [*selected_sections]
            proposal.insert(insert_at, deepcopy(section))
            if len(
                _final_provider_list_representation(
                    proposal,
                    preserved_dynamic_context=preserved_dynamic_context,
                    final_dynamic_context_suffix=final_dynamic_context_suffix,
                )
            ) <= budget_chars:
                selected_sections = proposal
                selected_ids.add(section["section_id"])
                admission_receipts.append(
                    {
                        "section_id": section_id,
                        "state": "admitted_optional",
                        "priority_rank": priority_rank,
                        "reason": "fits_budget_at_priority",
                    }
                )
            else:
                blocked_by_higher_priority = True
                omission_receipts.append(
                    {
                        "section_id": section["section_id"],
                        "section_sha256": canonical_sha256(section),
                        "reason": "whole_section_budget_omission",
                        "exact_source_clipped": False,
                    }
                )
                admission_receipts.append(
                    {
                        "section_id": section_id,
                        "state": "omitted",
                        "priority_rank": priority_rank,
                        "reason": "whole_section_budget_omission",
                    }
                )
        selected_sections.sort(key=lambda item: OUTPUT_SECTION_ORDER.index(item["section_id"]))
        selected_sections = list(validate_integrated_sections(selected_sections))
        emitted = _final_provider_list_representation(
            selected_sections,
            preserved_dynamic_context=preserved_dynamic_context,
            final_dynamic_context_suffix=final_dynamic_context_suffix,
        )
        request = {
            "operation": "selection",
            "manifest_sha256": canonical_sha256(manifest),
            "m2_section_sha256": canonical_sha256(m2_section),
            "m3_sections_sha256": canonical_sha256(
                [item["section"] for item in normalized_m3]
            ),
            "budget_chars": budget_chars,
            "preserved_dynamic_context_sha256": canonical_sha256(
                list(preserved_dynamic_context)
            ),
            "final_dynamic_context_suffix_sha256": canonical_sha256(
                list(final_dynamic_context_suffix)
            ),
        }
        selected_attachment_by_section_id = {
            OUTPUT_SECTION_BY_AUTHORITY[item["authority"]]: item
            for item in attachments
            if item["state"] == "selected"
            and item["attachment_id"] not in suppressed_attachment_ids
        }
        section_authority_receipts = []
        for selected_section in selected_sections:
            section_id = selected_section["section_id"]
            selected_attachment = selected_attachment_by_section_id.get(section_id)
            if selected_attachment is not None:
                provenance = selected_attachment["provenance"]
                authority = selected_attachment["authority"]
                owner = provenance["owner"]
                selection_identity = provenance["selection_identity"]
                predecessor_identity = provenance["predecessor_identity"]
                evidence_domain = provenance["evidence_domain"]
                canonicalization_version = provenance["canonicalization_version"]
                freshness = provenance["freshness"]
                observed_at = provenance["observed_at_epoch_millis"]
                journal_domain = provenance["selection_journal_domain"]
                journal_identity = provenance["selection_journal_identity"]
                conversion_identity = (
                    selected_attachment["exact_conversion"]["conversion_identity"]
                    if selected_attachment["exact_conversion"] is not None
                    else "m4_remove_duplicate_paragraphs_join_v1"
                    if section_id in dedup_transformed_section_ids
                    else "m4_selected_section_projection_v1"
                )
            elif section_id == "continuity_working_set":
                authority = "m2_continuity"
                owner = "house_continuity_v1_2_milestone2_authority_local"
                selection_identity = canonical_sha256(m2_section)
                predecessor_identity = manifest["continuity_selection_journal"][
                    "identity"
                ]
                evidence_domain = "m2_provider_section_sorted_json_utf8_v1"
                canonicalization_version = CANONICAL_JSON_VERSION
                freshness = "active_current_truth"
                observed_at = manifest["m2_freshness_epoch_millis"]
                journal_domain = manifest["continuity_selection_journal"]["domain"]
                journal_identity = manifest["continuity_selection_journal"][
                    "identity"
                ]
                conversion_identity = "m2_provider_section_projection_v1"
            elif section_id == "m4_authority_conflict_notice":
                authority = "m4_conflict_receipt_projection"
                owner = SCHEMA_VERSION
                selection_identity = canonical_sha256(conflict_receipts)
                predecessor_identity = canonical_sha256(m2_section)
                evidence_domain = "m4_raw_free_authority_conflict_receipt_v1"
                canonicalization_version = CANONICAL_JSON_VERSION
                freshness = "current_selection_attempt"
                observed_at = manifest["m2_freshness_epoch_millis"]
                journal_domain = RECEIPT_DOMAIN
                journal_identity = canonical_sha256(request)
                conversion_identity = "m4_conflict_notice_projection_v1"
            else:
                authority = _M3_AUTHORITY_BY_SECTION[section_id]
                owner = "house_continuity_v1_2_milestone3_context_local"
                selection_identity = canonical_sha256(selected_section)
                predecessor_identity = manifest["continuity_selection_journal"][
                    "identity"
                ]
                evidence_domain = "m3_typed_provider_section_sorted_json_utf8_v1"
                canonicalization_version = CANONICAL_JSON_VERSION
                freshness = (
                    "recent_canonical_conversation_evidence"
                    if authority == "m3_hot"
                    else "derived_archived_conversation_evidence"
                )
                observed_at = None
                journal_domain = manifest["continuity_selection_journal"]["domain"]
                journal_identity = manifest["continuity_selection_journal"][
                    "identity"
                ]
                conversion_identity = "m3_provider_section_projection_v1"
            section_authority_receipts.append(
                {
                    "section_id": section_id,
                    "authority": authority,
                    "authority_owner": owner,
                    "selection_identity": selection_identity,
                    "predecessor_identity": predecessor_identity,
                    "evidence_domain": evidence_domain,
                    "canonicalization_version": canonicalization_version,
                    "freshness": freshness,
                    "observed_at_epoch_millis": observed_at,
                    "selection_journal_domain": journal_domain,
                    "selection_journal_identity": journal_identity,
                    "conversion_identity": conversion_identity,
                    "emitted_representation_domain": PROVIDER_PARAGRAPH_DOMAIN,
                    "emitted_representation_canonicalization_version": (
                        "utf8_no_normalization_v1"
                    ),
                    "emitted_representation_sha256": _text_sha256(
                        selected_section["rendered_text"]
                    ),
                }
            )
        body = {
            "schema_version": SELECTION_RECEIPT_SCHEMA_VERSION,
            "attempt_id": attempt_id,
            "state": "selected",
            "assembly_order": list(OUTPUT_SECTION_ORDER),
            "provider_render_order": list(OUTPUT_SECTION_ORDER),
            "admission_policy_version": ADMISSION_POLICY_VERSION,
            "optional_admission_priority": list(OPTIONAL_ADMISSION_PRIORITY),
            "attached_authorities": [
                item["authority"] for item in deduplicated_candidates
                if item["section"]["section_id"] in selected_ids
            ],
            "attachment_receipts": [
                _safe_attachment_receipt(item) for item in attachments
            ],
            "memory_selection_journal": manifest["memory_selection_journal"],
            "continuity_selection_journal": manifest[
                "continuity_selection_journal"
            ],
            "journals_separate": True,
            "selected_section_identities": [
                _section_identity(section) for section in selected_sections
            ],
            "section_authority_receipts": section_authority_receipts,
            "conflict_receipts": conflict_receipts,
            "duplicate_receipts": duplicate_receipts,
            "related_representation_receipts": relationship_receipts,
            "suppressed_attachment_ids": sorted(suppressed_attachment_ids),
            "absence_states": {
                item["authority"]: item["state"]
                for item in attachments
                if item["state"] != "selected"
            },
            "exact_recall_no_match_substituted": False,
            "budget_chars": budget_chars,
            "budget_domain": PROVIDER_LIST_DOMAIN,
            "budget_canonicalization_version": CANONICAL_JSON_VERSION,
            "conversion_identity": PROVIDER_LIST_CONVERSION,
            "emitted_representation_chars": len(emitted),
            "emitted_representation_utf8_bytes": len(emitted.encode("utf-8")),
            "emitted_representation_sha256": _text_sha256(emitted),
            "preserved_dynamic_context_count": len(preserved_dynamic_context),
            "preserved_dynamic_context_sha256": canonical_sha256(
                list(preserved_dynamic_context)
            ),
            "final_dynamic_context_suffix_count": len(final_dynamic_context_suffix),
            "final_dynamic_context_suffix_sha256": canonical_sha256(
                list(final_dynamic_context_suffix)
            ),
            "omission_receipts": omission_receipts,
            "admission_receipts": admission_receipts,
            "m2_suppressed": False,
            "exact_source_clipped": False,
            "memory_g_activated_by_cold": False,
            "durable_memory_promoted": False,
            "promotion_proposal_created": False,
            "durable_promotion_path": "existing_reviewed_memory_authority_only",
            "source_eviction_enabled": False,
            "canonical_writes": {
                "memory": False,
                "vault": False,
                "m2": False,
                "m3": False,
                "self_state": False,
                "source": False,
            },
            "raw_material_present_in_receipt": False,
        }
        receipt = self._persist_receipt(
            attempt_id=attempt_id, kind="selection", request=request, body=body
        )
        if receipt["selected_section_identities"] != [
            _section_identity(section) for section in selected_sections
        ]:
            _fail("m4_attempt_replay_projection_changed")
        return {"state": "selected", "sections": selected_sections, "receipt": receipt}

    def persist_selector_rollback(
        self,
        *,
        attempt_id: str,
        selection_attempt_id: str,
        selected_dynamic_context: Sequence[str],
        prior_dynamic_context: Sequence[str],
        integrated_sections: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        selection = self.receipt(selection_attempt_id)
        normalized = list(validate_integrated_sections(integrated_sections))
        identities = [_section_identity(section) for section in normalized]
        if (
            selection is None
            or selection.get("state") != "selected"
            or selection.get("selected_section_identities") != identities
        ):
            _fail("m4_selector_selection_binding_invalid")
        derived_prior = list(selected_dynamic_context)
        for section in normalized:
            text = section["rendered_text"]
            if derived_prior.count(text) != 1:
                _fail("m4_selector_selected_projection_invalid")
            derived_prior.remove(text)
        comparison = evidence_equality_receipt(
            left_bytes=canonical_json_bytes(derived_prior),
            left_domain="generation2_dynamic_context_list_sorted_json_utf8_v1",
            left_canonicalization_version=CANONICAL_JSON_VERSION,
            left_identity=canonical_sha256(derived_prior),
            right_bytes=canonical_json_bytes(list(prior_dynamic_context)),
            right_domain="generation2_dynamic_context_list_sorted_json_utf8_v1",
            right_canonicalization_version=CANONICAL_JSON_VERSION,
            right_identity=canonical_sha256(list(prior_dynamic_context)),
        )
        if comparison["equal"] is not True:
            _fail("m4_selector_prior_projection_mismatch")
        request = {
            "operation": "selector_rollback",
            "selection_attempt_id": selection_attempt_id,
            "selection_receipt_sha256": selection["receipt_sha256"],
            "selected_dynamic_context_sha256": canonical_sha256(
                list(selected_dynamic_context)
            ),
            "prior_dynamic_context_sha256": canonical_sha256(
                list(prior_dynamic_context)
            ),
            "integrated_section_identities": identities,
        }
        body = {
            "schema_version": ROLLBACK_RECEIPT_SCHEMA_VERSION,
            "attempt_id": attempt_id,
            "state": "restored",
            "selection_attempt_id": selection_attempt_id,
            "selection_receipt_sha256": selection["receipt_sha256"],
            "selection_receipt_domain": RECEIPT_DOMAIN,
            "restored_projection_comparison": comparison,
            "canonical_records_rewritten": False,
            "memory_journal_rewritten": False,
            "continuity_journal_rewritten": False,
            "m2_records_rewritten": False,
            "m3_records_rewritten": False,
        }
        return self._persist_receipt(
            attempt_id=attempt_id, kind="selector_rollback", request=request, body=body
        )

    def doctor(self) -> dict[str, Any]:
        integrity = self.connection.execute("PRAGMA integrity_check").fetchone()[0]
        count = self.connection.execute("SELECT COUNT(*) AS count FROM receipts").fetchone()[
            "count"
        ]
        return {
            "schema_version": STORE_SCHEMA_VERSION,
            "state": "healthy" if integrity == "ok" else "failed_closed",
            "integrity": integrity,
            "receipt_count": count,
            "semantic_authority_owned": False,
            "raw_receipts": False,
        }


@dataclass(frozen=True)
class Milestone4Generation2Projection:
    selection_attempt_id: str
    budget_chars: int
    emitted_representation_chars: int
    emitted_representation_sha256: str
    sections: tuple[Mapping[str, Any], ...] = field(repr=False)


def attest_generation2_dynamic_context(
    projection: Milestone4Generation2Projection,
    actual_dynamic_context: Sequence[str],
) -> dict[str, Any]:
    if (
        not isinstance(projection, Milestone4Generation2Projection)
        or not isinstance(actual_dynamic_context, Sequence)
        or isinstance(actual_dynamic_context, (str, bytes))
        or any(not isinstance(value, str) for value in actual_dynamic_context)
    ):
        _fail("m4_final_dynamic_context_invalid")
    emitted = _dynamic_context_field_representation(actual_dynamic_context)
    if (
        len(emitted) != projection.emitted_representation_chars
        or _text_sha256(emitted) != projection.emitted_representation_sha256
        or len(emitted) > projection.budget_chars
    ):
        _fail("m4_final_dynamic_context_attestation_failed")
    return {
        "state": "exact_final_dynamic_context_attested",
        "selection_attempt_id": projection.selection_attempt_id,
        "evidence_domain": PROVIDER_LIST_DOMAIN,
        "canonicalization_version": CANONICAL_JSON_VERSION,
        "conversion_identity": PROVIDER_LIST_CONVERSION,
        "emitted_representation_chars": len(emitted),
        "emitted_representation_sha256": _text_sha256(emitted),
        "budget_chars": projection.budget_chars,
        "within_budget": True,
    }


def _control_state(env: Mapping[str, str]) -> tuple[str, str]:
    mode = str(env.get(SWITCH_ENV, OFF)).strip().casefold()
    selector = str(env.get(SELECTOR_ENV, OFF)).strip().casefold()
    if mode not in {OFF, COPY_REHEARSAL} or selector not in {OFF, ON}:
        _fail("m4_control_state_invalid")
    if mode == OFF and selector != OFF:
        _fail("m4_control_state_invalid")
    return mode, selector


def generation2_projection_from_env(
    env: Mapping[str, str],
    *,
    room_id: str,
    required_m2_section: Mapping[str, Any] | None,
    m3_sections: Sequence[Mapping[str, Any]],
    preserved_dynamic_context: Sequence[str] = (),
    final_dynamic_context_suffix: Sequence[str] = (),
) -> Milestone4Generation2Projection | None:
    mode, selector = _control_state(env)
    if mode == OFF or selector == OFF:
        return None
    root_value = env.get(ROOT_ENV)
    if not isinstance(root_value, str) or not root_value.strip():
        _fail("m4_copy_root_unavailable")
    root = Path(root_value)
    integration_root = root / "memory_integration"
    manifest_path = integration_root / "selection_manifest.json"
    if not root.is_dir() or not manifest_path.is_file():
        _fail("m4_copy_root_unavailable")
    try:
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Milestone4IntegrationError("m4_manifest_unreadable") from exc
    manifest = validate_manifest(raw_manifest, root=root, room_id=room_id)
    budget_raw = str(env.get(BUDGET_ENV, DEFAULT_BUDGET_CHARS)).strip()
    try:
        budget = int(budget_raw)
    except ValueError as exc:
        raise Milestone4IntegrationError("m4_budget_invalid") from exc
    request_basis = {
        "manifest_sha256": canonical_sha256(manifest),
        "m2_section_sha256": canonical_sha256(required_m2_section),
        "m3_sections_sha256": canonical_sha256(list(m3_sections)),
        "budget": budget,
        "preserved_dynamic_context_sha256": canonical_sha256(
            list(preserved_dynamic_context)
        ),
        "final_dynamic_context_suffix_sha256": canonical_sha256(
            list(final_dynamic_context_suffix)
        ),
    }
    attempt_id = "m4_route_" + canonical_sha256(request_basis)[:32]
    store = Milestone4IntegrationStore(integration_root / "journal")
    try:
        result = store.assemble_provider_sections(
            manifest=manifest,
            required_m2_section=required_m2_section,
            m3_sections=m3_sections,
            budget_chars=budget,
            attempt_id=attempt_id,
            preserved_dynamic_context=preserved_dynamic_context,
            final_dynamic_context_suffix=final_dynamic_context_suffix,
        )
        if result["state"] != "selected":
            _fail("m4_generation2_selection_failed_closed")
        receipt = result["receipt"]
        return Milestone4Generation2Projection(
            selection_attempt_id=attempt_id,
            budget_chars=budget,
            emitted_representation_chars=receipt["emitted_representation_chars"],
            emitted_representation_sha256=receipt[
                "emitted_representation_sha256"
            ],
            sections=tuple(result["sections"]),
        )
    finally:
        store.close()


def generation2_sections_from_env(
    env: Mapping[str, str],
    *,
    room_id: str,
    required_m2_section: Mapping[str, Any] | None,
    m3_sections: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...] | None:
    projection = generation2_projection_from_env(
        env,
        room_id=room_id,
        required_m2_section=required_m2_section,
        m3_sections=m3_sections,
    )
    return None if projection is None else projection.sections


__all__ = [
    "ATTACHMENT_AUTHORITIES",
    "BUDGET_ENV",
    "CANONICAL_JSON_VERSION",
    "COPY_REHEARSAL",
    "MANAGED_INPUT_SECTION_IDS",
    "MANIFEST_SCHEMA_VERSION",
    "Milestone4Generation2Projection",
    "Milestone4IntegrationError",
    "Milestone4IntegrationStore",
    "OFF",
    "ON",
    "OUTPUT_SECTION_ORDER",
    "PROVIDER_LIST_DOMAIN",
    "ROOT_ENV",
    "SCHEMA_VERSION",
    "SELECTOR_ENV",
    "STORE_SCHEMA_VERSION",
    "SWITCH_ENV",
    "canonical_json_bytes",
    "canonical_sha256",
    "copy_root_identity",
    "evidence_equality_receipt",
    "attest_generation2_dynamic_context",
    "generation2_projection_from_env",
    "generation2_sections_from_env",
    "validate_integrated_sections",
    "validate_manifest",
]
