"""Canonical operation-bound room and scope authority for Gate-12S."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping

import house_continuity_v1_2_contract_schema_v0 as contracts
from house_continuity_v1_2_local_store_v1 import HouseContinuityV12LocalStore
import house_continuity_v1_2_milestone2_authority_local as milestone2


ROUTE_REQUEST_SCHEMA_VERSION = (
    "house_continuity_v1_2_route_binding_request_v1"
)
REOPEN_REQUEST_SCHEMA_VERSION = (
    "house_continuity_v1_2_canonical_room_reopen_request_v1"
)
ROUTE_BINDING_SCHEMA_VERSION = (
    "house_continuity_v1_2_operation_route_binding_v1"
)
ROOM_IDENTITY_STABLE = "current_session_context_local_session"
ROOM_IDENTITY_LEGACY = "legacy_transient_session"
REOPEN_NONE = "none"
REOPEN_EXISTING = "explicit_existing"
SEMANTIC_EVALUATION_REQUEST_FIELD = "semantic_evaluation_request"

_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,180}")
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_CREATE_KINDS = [
    "active_topic",
    "active_task",
    "question",
    "commitment",
    "decision",
    "temporary_fact",
    "emotional_thread",
    "pending_review",
]


class HouseContinuityRouteBindingError(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _fail(code: str) -> None:
    raise HouseContinuityRouteBindingError(code)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def derive_room_id(stable_room_reference: str) -> str:
    if (
        not isinstance(stable_room_reference, str)
        or _ID_RE.fullmatch(stable_room_reference) is None
    ):
        _fail("route_stable_room_reference_invalid")
    return "cws_room_" + _sha(
        "gate12-room:" + stable_room_reference
    )[:32]


def request_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        _fail("route_binding_payload_invalid")
    transient_session_id = str(payload.get("session_id") or "").strip()
    if _ID_RE.fullmatch(transient_session_id) is None:
        _fail("route_transient_session_invalid")
    context = payload.get("current_session_context")
    if context is not None and not isinstance(context, Mapping):
        _fail("route_current_session_context_invalid")
    stable_value = (
        str(context.get("local_session_id") or "").strip()
        if isinstance(context, Mapping)
        else ""
    )
    if stable_value:
        if _ID_RE.fullmatch(stable_value) is None:
            _fail("route_stable_room_reference_invalid")
        stable_room_reference = stable_value
        identity_source = ROOM_IDENTITY_STABLE
    else:
        stable_room_reference = transient_session_id
        identity_source = ROOM_IDENTITY_LEGACY
    reopen = (
        context.get("house_continuity_room_reopen")
        if isinstance(context, Mapping)
        else None
    )
    if reopen is not None and not isinstance(reopen, Mapping):
        _fail("route_reopen_request_invalid")
    semantic_evaluation_request = (
        context.get(SEMANTIC_EVALUATION_REQUEST_FIELD)
        if isinstance(context, Mapping)
        else None
    )
    if semantic_evaluation_request is not None:
        try:
            semantic_evaluation_request = (
                contracts.validate_semantic_evaluation_request(
                    semantic_evaluation_request
                )
            )
        except Exception as exc:
            _fail(
                getattr(
                    exc,
                    "error_code",
                    "route_semantic_evaluation_request_invalid",
                )
            )
    request = {
        "schema_version": ROUTE_REQUEST_SCHEMA_VERSION,
        "transient_session_id": transient_session_id,
        "stable_room_reference": stable_room_reference,
        "room_identity_source": identity_source,
        "reopen": None if reopen is None else dict(reopen),
        SEMANTIC_EVALUATION_REQUEST_FIELD: semantic_evaluation_request,
    }
    return validate_route_request(request)


def validate_route_request(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "transient_session_id",
        "stable_room_reference",
        "room_identity_source",
        "reopen",
    }
    if not isinstance(value, Mapping) or not (
        set(value) == required
        or set(value) == required | {SEMANTIC_EVALUATION_REQUEST_FIELD}
    ):
        _fail("route_binding_request_invalid")
    if value["schema_version"] != ROUTE_REQUEST_SCHEMA_VERSION:
        _fail("route_binding_request_schema_invalid")
    transient = value["transient_session_id"]
    stable = value["stable_room_reference"]
    source = value["room_identity_source"]
    if (
        not isinstance(transient, str)
        or _ID_RE.fullmatch(transient) is None
        or not isinstance(stable, str)
        or _ID_RE.fullmatch(stable) is None
        or source not in {ROOM_IDENTITY_STABLE, ROOM_IDENTITY_LEGACY}
        or (source == ROOM_IDENTITY_LEGACY and stable != transient)
    ):
        _fail("route_binding_request_identity_invalid")
    reopen = value["reopen"]
    normalized_reopen = None
    if reopen is not None:
        reopen_expected = {
            "schema_version",
            "room_id",
            "project_id",
            "binding_revision",
            "binding_sha256",
        }
        if not isinstance(reopen, Mapping) or set(reopen) != reopen_expected:
            _fail("route_reopen_request_invalid")
        if reopen["schema_version"] != REOPEN_REQUEST_SCHEMA_VERSION:
            _fail("route_reopen_request_schema_invalid")
        room_id = reopen["room_id"]
        project_id = reopen["project_id"]
        revision = reopen["binding_revision"]
        binding_sha256 = reopen["binding_sha256"]
        if (
            not isinstance(room_id, str)
            or not room_id.startswith("cws_room_")
            or _ID_RE.fullmatch(room_id) is None
            or (
                project_id is not None
                and (
                    not isinstance(project_id, str)
                    or not project_id.startswith("cws_prj_")
                    or _ID_RE.fullmatch(project_id) is None
                )
            )
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
            or not isinstance(binding_sha256, str)
            or _SHA_RE.fullmatch(binding_sha256) is None
        ):
            _fail("route_reopen_request_identity_invalid")
        normalized_reopen = {
            "schema_version": REOPEN_REQUEST_SCHEMA_VERSION,
            "room_id": room_id,
            "project_id": project_id,
            "binding_revision": revision,
            "binding_sha256": binding_sha256,
        }
    semantic_evaluation_request = value.get(
        SEMANTIC_EVALUATION_REQUEST_FIELD
    )
    if semantic_evaluation_request is not None:
        try:
            semantic_evaluation_request = (
                contracts.validate_semantic_evaluation_request(
                    semantic_evaluation_request
                )
            )
        except Exception as exc:
            _fail(
                getattr(
                    exc,
                    "error_code",
                    "route_semantic_evaluation_request_invalid",
                )
            )
    return {
        "schema_version": ROUTE_REQUEST_SCHEMA_VERSION,
        "transient_session_id": transient,
        "stable_room_reference": stable,
        "room_identity_source": source,
        "reopen": normalized_reopen,
        SEMANTIC_EVALUATION_REQUEST_FIELD: semantic_evaluation_request,
    }


def _command_item(item: Mapping[str, Any]) -> dict[str, Any]:
    lifecycle = item["lifecycle_state"]
    allowed_operations = (
        ["confirm", "revise", "resolve"]
        if lifecycle == "active"
        else ["reopen"]
        if lifecycle in {"resolved", "abandoned"}
        else []
    )
    return {
        "item_id": item["item_id"],
        "revision": item["revision"],
        "item_kind": item["item_kind"],
        "lifecycle_state": lifecycle,
        "scope": {
            "scope_kind": item["scope_kind"],
            "room_id": item["room_id"],
            "project_id": item["project_id"],
            "thread_id": item["thread_id"],
        },
        "summary": item["summary"],
        "kind_payload": deepcopy(item["kind_payload"]),
        "content_sha256": item["content_sha256"],
        "allowed_operations": allowed_operations,
        "offered_successor_item_ids": [],
    }


def _create_offer(
    operation_id: str, scope_kind: str, scope: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "offer_id": "cws_offer_"
        + _sha("gate12-offer:" + operation_id + ":" + scope_kind)[:32],
        "scope": dict(scope),
        "allowed_item_kinds": list(_CREATE_KINDS),
    }


def resolve_operation_binding(
    *,
    working_set_root: str | Path,
    route_request: Mapping[str, Any],
    operation_id: str,
    now: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request = validate_route_request(route_request)
    if _ID_RE.fullmatch(operation_id) is None:
        _fail("route_operation_id_invalid")
    root = Path(working_set_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with HouseContinuityV12LocalStore(
        root, synthetic_only=False, production_candidate=True
    ) as store:
        reopen = request["reopen"]
        derived_room_id = derive_room_id(request["stable_room_reference"])
        if reopen is None:
            room_id = derived_room_id
            reopen_mode = REOPEN_NONE
            reopen_request_sha256 = None
        else:
            room_id = reopen["room_id"]
            reopen_mode = REOPEN_EXISTING
            reopen_request_sha256 = contracts.canonical_sha256(reopen)
        projection = milestone2.read_authoritative_projection(
            store, room_id=room_id, now=now
        )
        binding = projection["binding"]
        canonical_binding_sha256 = (
            None
            if binding is None
            else contracts.canonical_sha256(binding)
        )
        if reopen is not None:
            if binding is None:
                _fail("route_reopen_binding_missing")
            if (
                reopen["room_id"] != binding["room_id"]
                or reopen["project_id"] != binding["project_id"]
                or reopen["binding_revision"]
                != binding["binding_revision"]
                or reopen["binding_sha256"]
                != canonical_binding_sha256
            ):
                _fail("route_reopen_binding_mismatch")
        project_id = None if binding is None else binding["project_id"]
        thread_id = None if binding is None else binding["thread_id"]
        binding_revision = (
            1 if binding is None else binding["binding_revision"]
        )
        route_binding = {
            "schema_version": ROUTE_BINDING_SCHEMA_VERSION,
            "transient_session_id": request["transient_session_id"],
            "stable_room_reference": request["stable_room_reference"],
            "room_identity_source": request["room_identity_source"],
            "room_id": room_id,
            "derived_room_id": derived_room_id,
            "project_id": project_id,
            "thread_id": thread_id,
            "scope_binding_revision": binding_revision,
            "canonical_scope_binding_sha256": canonical_binding_sha256,
            "reopen_mode": reopen_mode,
            "reopen_request_sha256": reopen_request_sha256,
        }
        route_binding = validate_operation_binding(route_binding)
        global_scope = {
            "scope_kind": "global",
            "room_id": None,
            "project_id": None,
            "thread_id": None,
        }
        room_scope = {
            "scope_kind": "room",
            "room_id": room_id,
            "project_id": project_id,
            "thread_id": thread_id,
        }
        create_offers = [
            _create_offer(operation_id, "global", global_scope)
        ]
        if project_id is not None:
            create_offers.append(
                _create_offer(
                    operation_id,
                    "project",
                    {
                        "scope_kind": "project",
                        "room_id": None,
                        "project_id": project_id,
                        "thread_id": None,
                    },
                )
            )
        create_offers.append(
            _create_offer(operation_id, "room", room_scope)
        )
        snapshot_sha256 = projection["snapshot_global_event_sha256"]
        if snapshot_sha256 is None:
            snapshot_sha256 = _sha("gate12-empty-snapshot")
        seed = _sha("gate12-context:" + operation_id)
        context_body = {
                "schema_version": contracts.COMMAND_CONTEXT_SCHEMA_VERSION,
                "context_id": "cws_ctx_" + seed[:32],
                "creation_seed_sha256": seed,
                "snapshot_global_event_sequence": projection[
                    "snapshot_global_event_sequence"
                ],
                "snapshot_global_event_sha256": snapshot_sha256,
                "room_id": room_id,
                "scope_binding_revision": binding_revision,
                contracts.SEMANTIC_NOVELTY_POLICY_FIELD: (
                    contracts.SEMANTIC_NOVELTY_POLICY_VERSION
                ),
                "items": [
                    _command_item(entry["item"])
                    for entry in projection["selected_items"][:8]
                ],
                "create_offers": create_offers,
                "provisional_scope_binding_choices": [],
                "authority": dict(contracts.COMMAND_CONTEXT_AUTHORITY),
            }
        context = contracts.validate_command_context(context_body)
        semantic_evaluation_request = request.get(
            SEMANTIC_EVALUATION_REQUEST_FIELD
        )
        if semantic_evaluation_request is not None:
            context_body[contracts.SEMANTIC_EVALUATION_FIELD] = {
                "schema_version": contracts.SEMANTIC_EVALUATION_SCHEMA_VERSION,
                "request_relation": semantic_evaluation_request[
                    "request_relation"
                ],
                "authoritative_projection_sha256": (
                    contracts.authoritative_projection_sha256(context)
                ),
            }
            context = contracts.validate_command_context(context_body)
        return route_binding, context


def validate_operation_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schema_version",
        "transient_session_id",
        "stable_room_reference",
        "room_identity_source",
        "room_id",
        "derived_room_id",
        "project_id",
        "thread_id",
        "scope_binding_revision",
        "canonical_scope_binding_sha256",
        "reopen_mode",
        "reopen_request_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        _fail("route_operation_binding_invalid")
    if value["schema_version"] != ROUTE_BINDING_SCHEMA_VERSION:
        _fail("route_operation_binding_schema_invalid")
    transient = value["transient_session_id"]
    stable = value["stable_room_reference"]
    source = value["room_identity_source"]
    room_id = value["room_id"]
    derived_room_id = value["derived_room_id"]
    project_id = value["project_id"]
    thread_id = value["thread_id"]
    revision = value["scope_binding_revision"]
    canonical_sha256 = value["canonical_scope_binding_sha256"]
    reopen_mode = value["reopen_mode"]
    reopen_sha256 = value["reopen_request_sha256"]
    if (
        not isinstance(transient, str)
        or _ID_RE.fullmatch(transient) is None
        or not isinstance(stable, str)
        or _ID_RE.fullmatch(stable) is None
        or source not in {ROOM_IDENTITY_STABLE, ROOM_IDENTITY_LEGACY}
        or not isinstance(room_id, str)
        or not room_id.startswith("cws_room_")
        or _ID_RE.fullmatch(room_id) is None
        or derived_room_id != derive_room_id(stable)
        or (
            project_id is not None
            and (
                not isinstance(project_id, str)
                or not project_id.startswith("cws_prj_")
                or _ID_RE.fullmatch(project_id) is None
            )
        )
        or (
            thread_id is not None
            and (
                project_id is None
                or not isinstance(thread_id, str)
                or _ID_RE.fullmatch(thread_id) is None
            )
        )
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
        or (
            canonical_sha256 is not None
            and (
                not isinstance(canonical_sha256, str)
                or _SHA_RE.fullmatch(canonical_sha256) is None
            )
        )
        or reopen_mode not in {REOPEN_NONE, REOPEN_EXISTING}
        or (
            reopen_sha256 is not None
            and (
                not isinstance(reopen_sha256, str)
                or _SHA_RE.fullmatch(reopen_sha256) is None
            )
        )
        or (reopen_mode == REOPEN_NONE and reopen_sha256 is not None)
        or (
            reopen_mode == REOPEN_EXISTING
            and (
                reopen_sha256 is None
                or canonical_sha256 is None
            )
        )
    ):
        _fail("route_operation_binding_identity_invalid")
    return deepcopy(dict(value))


__all__ = [
    "HouseContinuityRouteBindingError",
    "REOPEN_REQUEST_SCHEMA_VERSION",
    "ROUTE_BINDING_SCHEMA_VERSION",
    "ROUTE_REQUEST_SCHEMA_VERSION",
    "SEMANTIC_EVALUATION_REQUEST_FIELD",
    "derive_room_id",
    "request_from_payload",
    "resolve_operation_binding",
    "validate_operation_binding",
    "validate_route_request",
]
