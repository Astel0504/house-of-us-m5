"""Operation-bound M4 producer over actual Generation-1, M2, and M3 owners."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping

import api_talk_card_envelope_v0 as api_envelope
import house_continuity_v1_2_milestone2_authority_local as milestone2
import house_continuity_v1_2_milestone3_context_local as milestone3
import house_continuity_v1_2_milestone4_memory_integration_local as milestone4
from house_continuity_v1_2_local_store_v1 import HouseContinuityV12LocalStore
import house_standing_root_v2_production_v1 as production
import provider_visible_text_safety_v0 as provider_text_safety


SCHEMA_VERSION = "house_continuity_milestone5_m4_operation_artifact_v1"
STORE_SCHEMA_VERSION = "house_continuity_milestone5_m4_operation_store_v1"
PHASE_RECEIPT_SCHEMA_VERSION = "house_continuity_milestone5_m4_phase_receipt_v1"
SELECTION_OUTPUT_DOMAIN = "standing_root_generation1_section_outputs_sorted_json_utf8_v1"
ARTIFACT_DOMAIN = "m5_m4_operation_artifact_sorted_json_utf8_v1"
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_PHASES = (
    "candidate",
    "preflight",
    "activation",
    "interception",
    "dispatch",
)
_OUTPUT_ID_BY_AUTHORITY = {
    "memory_g": "memory_context",
    "vault_recall": "vault_recall",
    "exact_recall": "read_mode_exact_text",
    "recent_turns": "recent_visible_exchange",
    "sources": "read_mode_source_context",
}
_ABSENCE_STATE = {
    "memory_g": "authoritative_empty",
    "vault_recall": "no_match",
    "exact_recall": "no_match",
    "recent_turns": "authoritative_empty",
    "sources": "no_match",
}
_INPUT_SECTION_ID = {
    "memory_g": "memory_context",
    "vault_recall": "vault_recall",
    "recent_turns": "recent_visible_exchange",
    "sources": "read_mode_source_context",
}


class Milestone5M4ProducerError(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _fail(code: str) -> None:
    raise Milestone5M4ProducerError(code)


def _identifier(value: Any, *, code: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        _fail(code)
    return value


def _sha(value: Any, *, code: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        _fail(code)
    return value


def _derived_id(prefix: str, value: Any) -> str:
    return prefix + milestone4.canonical_sha256(value)[:32]


def _epoch_millis(value: str) -> int:
    if not isinstance(value, str):
        _fail("m5_m4_timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Milestone5M4ProducerError("m5_m4_timestamp_invalid") from exc
    if parsed.tzinfo is None:
        _fail("m5_m4_timestamp_invalid")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _selection_outputs(
    selection: production.ProductionPromptSelection,
) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(selection, production.ProductionPromptSelection):
        _fail("m5_m4_generation1_selection_owner_invalid")
    outputs = [deepcopy(dict(value)) for value in selection.section_outputs]
    if any(
        not isinstance(value, Mapping)
        or set(value)
        != {
            "section_id",
            "section_class",
            "exactness",
            "update_frequency",
            "rendered_text",
        }
        for value in outputs
    ):
        _fail("m5_m4_generation1_section_output_invalid")
    ids = [str(value["section_id"]) for value in outputs]
    if len(ids) != len(set(ids)):
        _fail("m5_m4_generation1_section_duplicate")
    identity = milestone4.canonical_sha256(
        {
            "outputs": outputs,
            "observability": dict(selection.observability),
            "rendered_text_sha256": hashlib.sha256(
                selection.rendered_text.encode("utf-8")
            ).hexdigest(),
        }
    )
    return outputs, identity


def _m2_claims(projection: Mapping[str, Any]) -> list[dict[str, Any]]:
    claims = []
    for entry in projection["selected_items"]:
        item = entry["item"]
        claims.append(
            {
                "claim_key_hash": milestone4.canonical_sha256(
                    {
                        "item_kind": item["item_kind"],
                        "scope_kind": item["scope_kind"],
                        "room_id": item["room_id"],
                        "project_id": item["project_id"],
                        "thread_id": item["thread_id"],
                    }
                ),
                "value_sha256": str(item["content_sha256"]),
                "observed_at_epoch_millis": _epoch_millis(item["updated_at"]),
            }
        )
    return claims


def _verified_exact_source(
    selection: production.ProductionPromptSelection,
    output: Mapping[str, Any] | None,
) -> dict[str, str] | None:
    if output is None:
        return None
    envelope = selection.envelope
    cards = envelope.get("cards") if isinstance(envelope.get("cards"), Mapping) else {}
    card = (
        cards.get("read_mode_exact_text_card")
        if isinstance(cards.get("read_mode_exact_text_card"), Mapping)
        else {}
    )
    selected = card.get("selected_items")
    if not isinstance(selected, list) or len(selected) != 1:
        _fail("m5_m4_exact_source_owner_verification_required")
    item = selected[0]
    if not isinstance(item, Mapping):
        _fail("m5_m4_exact_source_owner_verification_required")
    source_identity = item.get("source_identity_sha256")
    eligibility_identity = item.get("eligibility_receipt_sha256")
    source_domain = item.get("source_representation_domain")
    canonicalization = item.get("source_canonicalization_version")
    source_text = item.get("exact_text")
    rendered = output.get("rendered_text")
    try:
        derived_evidence = api_envelope.derive_read_mode_exact_text_evidence(
            source_text
        )
    except Exception:
        _fail("m5_m4_exact_source_owner_verification_required")
    if (
        not isinstance(source_identity, str)
        or not _SHA_RE.fullmatch(source_identity)
        or not isinstance(eligibility_identity, str)
        or not _SHA_RE.fullmatch(eligibility_identity)
        or not isinstance(source_domain, str)
        or not _ID_RE.fullmatch(source_domain)
        or not isinstance(canonicalization, str)
        or not _ID_RE.fullmatch(canonicalization)
        or item.get("provider_visible_eligible") is not True
        or not isinstance(source_text, str)
        or not source_text
        or not isinstance(rendered, str)
        or rendered.count(source_text) != 1
        or milestone3.provider_boundary_denial_reason(source_text) is not None
        or source_identity
        != derived_evidence["source_identity_sha256"]
        or eligibility_identity
        != derived_evidence["eligibility_receipt_sha256"]
        or source_domain
        != derived_evidence["source_representation_domain"]
        or canonicalization
        != derived_evidence["source_canonicalization_version"]
        or item.get("eligibility_policy")
        != derived_evidence["eligibility_policy"]
    ):
        _fail("m5_m4_exact_source_owner_verification_required")
    start = rendered.index(source_text)
    return {
        "source_identity": source_identity,
        "eligibility_receipt_identity": eligibility_identity,
        "source_domain": source_domain,
        "source_canonicalization_version": canonicalization,
        "source_text": source_text,
        "provider_prefix": rendered[:start],
        "provider_suffix": rendered[start + len(source_text) :],
    }


def _attachment(
    authority: str,
    *,
    output: Mapping[str, Any] | None,
    predecessor_identity: str,
    memory_journal_identity: str,
    observed_at_epoch_millis: int,
    exact_source: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if authority == "exact_recall" and output is not None and exact_source is None:
        _fail("m5_m4_exact_source_owner_verification_required")
    state = "selected" if output is not None else _ABSENCE_STATE[authority]
    section = None
    selection_identity = milestone4.canonical_sha256(
        {"authority": authority, "state": state, "output": output}
    )
    if output is not None:
        rendered = str(output["rendered_text"])
        denial_reason = milestone3.provider_boundary_denial_reason(rendered)
        safe = provider_text_safety.sanitize_provider_visible_text(rendered)
        exactness = str(output["exactness"])
        if denial_reason is not None:
            state = "denied"
            output = None
            selection_identity = milestone4.canonical_sha256(
                {
                    "authority": authority,
                    "state": state,
                    "denial_reason": denial_reason,
                    "unsafe_output_sha256": hashlib.sha256(
                        rendered.encode("utf-8")
                    ).hexdigest(),
                }
            )
        else:
            if safe != rendered:
                safe += "\n[Provider-visible derived representation.]"
            section = {
                "section_id": (
                    "exact_recall"
                    if authority == "exact_recall"
                    else _INPUT_SECTION_ID[authority]
                ),
                "section_class": (
                    "exact_recall"
                    if authority == "exact_recall"
                    else str(output["section_class"])
                ),
                "exactness": exactness,
                "update_frequency": str(output["update_frequency"]),
                "rendered_text": safe,
            }
    return {
        "attachment_id": _derived_id(
            "m5_m4_attachment_",
            {"authority": authority, "selection_identity": selection_identity},
        ),
        "authority": authority,
        "state": state,
        "provenance": {
            "owner": (
                "api_talk_card_envelope_v0_canonical_source"
                if authority == "exact_recall" and exact_source is not None
                else "house_standing_root_v2_production_v1"
            ),
            "selection_identity": selection_identity,
            "predecessor_identity": predecessor_identity,
            "evidence_domain": SELECTION_OUTPUT_DOMAIN,
            "canonicalization_version": milestone4.CANONICAL_JSON_VERSION,
            "freshness": "current_generation1_candidate",
            "observed_at_epoch_millis": observed_at_epoch_millis,
            "selection_journal_domain": (
                "canonical_source_provider_eligibility_receipt_v1"
                if authority == "exact_recall" and exact_source is not None
                else SELECTION_OUTPUT_DOMAIN
            ),
            "selection_journal_identity": (
                exact_source["eligibility_receipt_identity"]
                if authority == "exact_recall" and exact_source is not None
                else memory_journal_identity
            ),
        },
        "section": section,
        "claims": [],
        "exact_conversion": (
            {
                "source_identity": exact_source["source_identity"],
                "source_domain": exact_source["source_domain"],
                "source_canonicalization_version": exact_source[
                    "source_canonicalization_version"
                ],
                "source_text": exact_source["source_text"],
                "provider_prefix": exact_source["provider_prefix"],
                "provider_suffix": exact_source["provider_suffix"],
                "conversion_identity": "m4_exact_source_prefix_suffix_v1",
            }
            if authority == "exact_recall" and exact_source is not None
            else None
        ),
    }


class Milestone5M4ProducerBridge:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "milestone5_m4_operations.sqlite3"
        self.connection = sqlite3.connect(self.path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operations(
              operation_id TEXT PRIMARY KEY,
              request_sha256 TEXT NOT NULL,
              artifact_json TEXT NOT NULL,
              artifact_sha256 TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS phases(
              operation_id TEXT NOT NULL,
              phase TEXT NOT NULL,
              request_sha256 TEXT NOT NULL,
              receipt_json TEXT NOT NULL,
              PRIMARY KEY(operation_id,phase),
              FOREIGN KEY(operation_id) REFERENCES operations(operation_id)
            );
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
        elif row["value"] != STORE_SCHEMA_VERSION:
            _fail("m5_m4_store_schema_unknown")

    def close(self) -> None:
        self.connection.close()

    def artifact(self, operation_id: str) -> dict[str, Any] | None:
        operation_id = _identifier(operation_id, code="m5_m4_operation_id_invalid")
        row = self.connection.execute(
            "SELECT artifact_json,artifact_sha256 FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        artifact = json.loads(row["artifact_json"])
        artifact_sha256 = artifact.get("artifact_sha256")
        body = {
            key: value
            for key, value in artifact.items()
            if key != "artifact_sha256"
        }
        if (
            artifact_sha256 != row["artifact_sha256"]
            or milestone4.canonical_sha256(body) != row["artifact_sha256"]
        ):
            _fail("m5_m4_artifact_integrity_invalid")
        return artifact

    def build_operation_artifact(
        self,
        *,
        operation_id: str,
        room_id: str,
        client_turn_id: str,
        provider_operation_id: str,
        generation1_selection: production.ProductionPromptSelection,
        working_set_store: HouseContinuityV12LocalStore,
        context_store: milestone3.Milestone3ContextStore,
        now: str,
        budget_chars: int,
        intent_query: str | None = None,
        preserved_dynamic_context: tuple[str, ...] = (),
        final_dynamic_context_suffix: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        operation_id = _identifier(operation_id, code="m5_m4_operation_id_invalid")
        room_id = _identifier(room_id, code="m5_m4_room_id_invalid")
        client_turn_id = _identifier(client_turn_id, code="m5_m4_client_turn_id_invalid")
        provider_operation_id = _identifier(
            provider_operation_id,
            code="m5_m4_provider_operation_id_invalid",
        )
        if not room_id.startswith("cws_room_"):
            _fail("m5_m4_room_id_invalid")
        if not isinstance(working_set_store, HouseContinuityV12LocalStore):
            _fail("m5_m4_m2_owner_invalid")
        if not isinstance(context_store, milestone3.Milestone3ContextStore):
            _fail("m5_m4_m3_owner_invalid")
        observed_at = _epoch_millis(now)
        outputs, predecessor_identity = _selection_outputs(generation1_selection)
        preserved_dynamic_context_sha256 = milestone4.canonical_sha256(
            list(preserved_dynamic_context)
        )
        final_dynamic_context_suffix_sha256 = milestone4.canonical_sha256(
            list(final_dynamic_context_suffix)
        )
        intent_query_sha256 = (
            hashlib.sha256(intent_query.encode("utf-8")).hexdigest()
            if isinstance(intent_query, str)
            else None
        )
        existing_operation = self.connection.execute(
            "SELECT artifact_json FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if existing_operation is not None:
            stored = json.loads(existing_operation["artifact_json"])
            if (
                stored["room_id"] != room_id
                or stored["client_turn_id"] != client_turn_id
                or stored["provider_operation_id"] != provider_operation_id
                or stored["generation1_predecessor_identity"]
                != predecessor_identity
                or stored["preserved_dynamic_context_sha256"]
                != preserved_dynamic_context_sha256
                or stored["final_dynamic_context_suffix_sha256"]
                != final_dynamic_context_suffix_sha256
                or stored["intent_query_sha256"] != intent_query_sha256
                or stored["m4_budget_chars"] != budget_chars
            ):
                _fail("m5_m4_operation_replay_conflict")
            self.bind_phase(
                operation_id=operation_id,
                phase="candidate",
                artifact_sha256=stored["artifact_sha256"],
                phase_input_sha256=stored["request_identity"],
            )
            return stored
        output_by_id = {str(value["section_id"]): value for value in outputs}
        projection = milestone2.read_authoritative_projection(
            working_set_store,
            room_id=room_id,
            now=now,
        )
        required_m2_section = milestone2.provider_section(projection)
        cold = None
        if intent_query is not None:
            if not isinstance(intent_query, str) or not intent_query.strip():
                _fail("m5_m4_intent_query_invalid")
            cold_retrieval = context_store.retrieve_cold(
                room_id=room_id,
                query=intent_query,
                budget_chars=budget_chars,
                attempt_id=_derived_id(
                    "m3_attempt_",
                    {"operation_id": operation_id, "kind": "cold"},
                ),
            )
            cold = (
                cold_retrieval
                if cold_retrieval["receipt"]["state"] == "selected"
                else None
            )
        m3_selection = context_store.assemble_provider_sections(
            room_id=room_id,
            required_m2_section=required_m2_section,
            budget_chars=milestone3.MAX_DYNAMIC_BUDGET_CHARS,
            attempt_id=_derived_id(
                "m3_attempt_",
                {"operation_id": operation_id, "kind": "provider_sections"},
            ),
            explicit_cold_selection=cold,
        )
        if m3_selection["state"] != "selected":
            _fail("m5_m4_m3_selection_failed_closed")
        m3_sections = [
            value
            for value in m3_selection["sections"]
            if value["section_id"] != "continuity_working_set"
        ]
        memory_journal_identity = milestone4.canonical_sha256(
            {
                authority: output_by_id.get(section_id)
                for authority, section_id in _OUTPUT_ID_BY_AUTHORITY.items()
            }
        )
        continuity_journal_identity = milestone4.canonical_sha256(
            {
                "m2_projection_sha256": projection["projection_sha256"],
                "m3_selection_receipt_sha256": m3_selection["receipt"][
                    "receipt_sha256"
                ],
            }
        )
        exact_source = _verified_exact_source(
            generation1_selection,
            output_by_id.get(_OUTPUT_ID_BY_AUTHORITY["exact_recall"]),
        )
        attachments = [
            _attachment(
                authority,
                output=output_by_id.get(_OUTPUT_ID_BY_AUTHORITY[authority]),
                predecessor_identity=predecessor_identity,
                memory_journal_identity=memory_journal_identity,
                observed_at_epoch_millis=observed_at,
                exact_source=(
                    exact_source if authority == "exact_recall" else None
                ),
            )
            for authority in milestone4.ATTACHMENT_AUTHORITIES
        ]
        manifest_value = {
            "schema_version": milestone4.MANIFEST_SCHEMA_VERSION,
            "copy_root_identity": milestone4.copy_root_identity(self.root),
            "room_id": room_id,
            "memory_selection_journal": {
                "owner": "house_standing_root_v2_production_v1",
                "domain": SELECTION_OUTPUT_DOMAIN,
                "identity": memory_journal_identity,
            },
            "continuity_selection_journal": {
                "owner": "milestone2_milestone3_production_owners",
                "domain": "m5_m2_m3_selection_journal_v1",
                "identity": continuity_journal_identity,
            },
            "m2_freshness_epoch_millis": observed_at,
            "m2_claims": _m2_claims(projection),
            "attachments": attachments,
        }
        manifest = milestone4.validate_manifest(
            manifest_value,
            root=self.root,
            room_id=room_id,
        )
        m4_store = milestone4.Milestone4IntegrationStore(
            self.root / "m4_receipts"
        )
        try:
            integrated = m4_store.assemble_provider_sections(
                manifest=manifest,
                required_m2_section=required_m2_section,
                m3_sections=m3_sections,
                budget_chars=budget_chars,
                attempt_id=_derived_id(
                    "m4_attempt_",
                    {"operation_id": operation_id, "kind": "selection"},
                ),
                preserved_dynamic_context=preserved_dynamic_context,
                final_dynamic_context_suffix=final_dynamic_context_suffix,
            )
        finally:
            m4_store.close()
        if integrated["state"] != "selected":
            _fail("m5_m4_budget_failed_closed")
        request_identity = milestone4.canonical_sha256(
            {
                "generation1_predecessor_identity": predecessor_identity,
                "room_id": room_id,
                "client_turn_id": client_turn_id,
                "provider_operation_id": provider_operation_id,
            }
        )
        body = {
            "schema_version": SCHEMA_VERSION,
            "operation_id": operation_id,
            "room_id": room_id,
            "client_turn_id": client_turn_id,
            "provider_operation_id": provider_operation_id,
            "request_identity": request_identity,
            "generation1_predecessor_identity": predecessor_identity,
            "preserved_dynamic_context_sha256": (
                preserved_dynamic_context_sha256
            ),
            "final_dynamic_context_suffix_sha256": (
                final_dynamic_context_suffix_sha256
            ),
            "intent_query_sha256": intent_query_sha256,
            "memory_selection_journal_identity": memory_journal_identity,
            "continuity_selection_journal_identity": continuity_journal_identity,
            "m2_projection_sha256": projection["projection_sha256"],
            "m2_authorship_result_state": projection["authorship_result_state"],
            "m3_projection_sha256": context_store.projection(room_id)[
                "projection_sha256"
            ],
            "m3_selection_receipt_sha256": m3_selection["receipt"][
                "receipt_sha256"
            ],
            "m4_selection_receipt_sha256": integrated["receipt"][
                "receipt_sha256"
            ],
            "m4_selection_attempt_id": integrated["receipt"]["attempt_id"],
            "m4_budget_chars": integrated["receipt"]["budget_chars"],
            "m4_emitted_representation_chars": integrated["receipt"][
                "emitted_representation_chars"
            ],
            "m4_emitted_representation_sha256": integrated["receipt"][
                "emitted_representation_sha256"
            ],
            "manifest_sha256": milestone4.canonical_sha256(manifest),
            "required_m2_section": required_m2_section,
            "m3_sections": m3_sections,
            "sections": integrated["sections"],
            "rollback_identity": milestone4.canonical_sha256(
                {
                    "generation": "generation_1",
                    "predecessor_identity": predecessor_identity,
                }
            ),
            "provider_calls_made": False,
            "canonical_writes": {
                "memory": False,
                "vault": False,
                "m2": False,
                "m3": False,
                "source": False,
                "self_state": False,
            },
            "raw_material_present_in_receipt": False,
        }
        artifact_core = {
            **body,
            "artifact_domain": ARTIFACT_DOMAIN,
        }
        artifact = {
            **artifact_core,
            "artifact_sha256": milestone4.canonical_sha256(artifact_core),
        }
        request = {
            "operation_id": operation_id,
            "request_identity": request_identity,
            "artifact_sha256": artifact["artifact_sha256"],
        }
        request_sha256 = milestone4.canonical_sha256(request)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.connection.execute(
                "SELECT request_sha256,artifact_json FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["request_sha256"] != request_sha256:
                    _fail("m5_m4_operation_replay_conflict")
                stored = json.loads(existing["artifact_json"])
                if stored != artifact:
                    _fail("m5_m4_operation_replay_result_changed")
                self.connection.commit()
                artifact = stored
            else:
                self.connection.execute(
                    "INSERT INTO operations(operation_id,request_sha256,artifact_json,artifact_sha256) VALUES(?,?,?,?)",
                    (
                        operation_id,
                        request_sha256,
                        milestone4.canonical_json_bytes(artifact).decode("utf-8"),
                        artifact["artifact_sha256"],
                    ),
                )
                self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        self.bind_phase(
            operation_id=operation_id,
            phase="candidate",
            artifact_sha256=artifact["artifact_sha256"],
            phase_input_sha256=request_identity,
        )
        return artifact

    def bind_phase(
        self,
        *,
        operation_id: str,
        phase: str,
        artifact_sha256: str,
        phase_input_sha256: str,
    ) -> dict[str, Any]:
        operation_id = _identifier(operation_id, code="m5_m4_operation_id_invalid")
        if phase not in {*_PHASES, "rollback"}:
            _fail("m5_m4_phase_invalid")
        artifact_sha256 = _sha(artifact_sha256, code="m5_m4_artifact_sha_invalid")
        phase_input_sha256 = _sha(
            phase_input_sha256,
            code="m5_m4_phase_input_sha_invalid",
        )
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            operation = self.connection.execute(
                "SELECT artifact_json,artifact_sha256 FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if operation is None or operation["artifact_sha256"] != artifact_sha256:
                _fail("m5_m4_phase_artifact_mismatch")
            artifact = json.loads(operation["artifact_json"])
            predecessor_phase = None
            if phase in _PHASES:
                index = _PHASES.index(phase)
                if index:
                    predecessor_phase = _PHASES[index - 1]
                    predecessor = self.connection.execute(
                        "SELECT receipt_json FROM phases WHERE operation_id=? AND phase=?",
                        (operation_id, predecessor_phase),
                    ).fetchone()
                    if predecessor is None:
                        _fail("m5_m4_phase_predecessor_missing")
            else:
                predecessor = self.connection.execute(
                    "SELECT phase FROM phases WHERE operation_id=? ORDER BY rowid DESC LIMIT 1",
                    (operation_id,),
                ).fetchone()
                if predecessor is None:
                    _fail("m5_m4_phase_predecessor_missing")
                predecessor_phase = predecessor["phase"]
            request = {
                "operation_id": operation_id,
                "phase": phase,
                "artifact_sha256": artifact_sha256,
                "phase_input_sha256": phase_input_sha256,
                "predecessor_phase": predecessor_phase,
            }
            request_sha256 = milestone4.canonical_sha256(request)
            body = {
                "schema_version": PHASE_RECEIPT_SCHEMA_VERSION,
                **request,
                "room_id": artifact["room_id"],
                "client_turn_id": artifact["client_turn_id"],
                "provider_operation_id": artifact["provider_operation_id"],
                "request_identity": artifact["request_identity"],
                "rollback_identity": artifact["rollback_identity"],
                "provider_calls_made": False,
                "raw_material_present": False,
            }
            receipt = {**body, "receipt_sha256": milestone4.canonical_sha256(body)}
            existing = self.connection.execute(
                "SELECT request_sha256,receipt_json FROM phases WHERE operation_id=? AND phase=?",
                (operation_id, phase),
            ).fetchone()
            if existing is not None:
                if existing["request_sha256"] != request_sha256:
                    _fail("m5_m4_phase_replay_conflict")
                stored = json.loads(existing["receipt_json"])
                if stored != receipt:
                    _fail("m5_m4_phase_replay_result_changed")
                self.connection.commit()
                return stored
            self.connection.execute(
                "INSERT INTO phases(operation_id,phase,request_sha256,receipt_json) VALUES(?,?,?,?)",
                (
                    operation_id,
                    phase,
                    request_sha256,
                    milestone4.canonical_json_bytes(receipt).decode("utf-8"),
                ),
            )
            self.connection.commit()
            return receipt
        except Exception:
            self.connection.rollback()
            raise


__all__ = [
    "ARTIFACT_DOMAIN",
    "Milestone5M4ProducerBridge",
    "Milestone5M4ProducerError",
    "PHASE_RECEIPT_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "SELECTION_OUTPUT_DOMAIN",
    "STORE_SCHEMA_VERSION",
]
