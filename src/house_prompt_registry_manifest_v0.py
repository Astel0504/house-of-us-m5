"""Strict local/no-live manifests and content loading for prompt registries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

import provider_visible_text_safety_v0 as provider_text_safety


INSTRUCTION_LAW_MANIFEST_SCHEMA_VERSION = (
    "house_prompt_instruction_law_manifest_v1"
)
CONTEXT_CARD_MANIFEST_SCHEMA_VERSION = "house_prompt_context_card_manifest_v1"
INTEGRITY_LOCK_SCHEMA_VERSION = "house_prompt_registry_integrity_lock_v1"

MANIFEST_FILENAME = "manifest.json"
MAX_MANIFEST_JSON_BYTES = 256 * 1024
MAX_INTEGRITY_LOCK_JSON_BYTES = 256 * 1024
MAX_CONTENT_FILE_BYTES = 128 * 1024
MAX_REGISTRY_ENTRIES = 128

LAW_ENTRY_FIELDS = (
    "slot_key",
    "law_class",
    "semantic_label",
    "content_relative_path",
    "content_version",
    "required_or_optional",
    "selection_priority",
    "stability_class",
    "exactness",
    "source_class",
    "content_kind",
    "derivation_version",
    "sensitivity_class",
    "enabled",
    "budget_class",
)
CARD_ENTRY_FIELDS = (
    "slot_key",
    "card_class",
    "semantic_label",
    "content_relative_path",
    "content_version",
    "required_or_optional",
    "selection_priority",
    "stability_class",
    "exactness",
    "source_class",
    "content_kind",
    "derivation_version",
    "sensitivity_class",
    "enabled",
    "budget_class",
)

LAW_CLASS_ORDER = (
    "solen_core_law",
    "house_response_law",
    "memory_authorship_law",
    "provider_privacy_law",
    "capability_law",
    "proactive_schema_law",
)
CARD_STABILITY_ORDER = (
    "very_slow",
    "slow",
    "checkpoint",
)
CARD_CLASS_ORDER = (
    "standing_root",
    "astel_profile",
    "solen_profile",
    "relationship_footing",
    "core_memory",
    "capability",
    "approved_reference",
    "room_checkpoint",
)

LAW_CLASS_RULES = {
    "solen_core_law": {
        "source_classes": {"house_behavior_law"},
        "content_kinds": {
            "exact_source_text",
            "house_derived_text",
        },
    },
    "house_response_law": {
        "source_classes": {"house_behavior_law"},
        "content_kinds": {
            "exact_source_text",
            "house_derived_text",
        },
    },
    "memory_authorship_law": {
        "source_classes": {"house_behavior_law"},
        "content_kinds": {
            "exact_source_text",
            "house_derived_text",
        },
    },
    "provider_privacy_law": {
        "source_classes": {"house_behavior_law"},
        "content_kinds": {
            "exact_source_text",
            "house_derived_text",
        },
    },
    "capability_law": {
        "source_classes": {"house_behavior_law"},
        "content_kinds": {
            "exact_source_text",
            "house_derived_text",
        },
    },
    "proactive_schema_law": {
        "source_classes": {"house_behavior_law"},
        "content_kinds": {
            "exact_source_text",
            "house_derived_text",
        },
    },
}

CARD_CLASS_RULES = {
    "standing_root": {
        "stability_classes": {"very_slow"},
        "source_classes": {
            "astel_profile",
            "solen_profile",
            "relationship_footing",
            "capability_description",
        },
        "content_kinds": {"house_derived_text"},
    },
    "astel_profile": {
        "stability_classes": {"very_slow"},
        "source_classes": {"astel_profile"},
        "content_kinds": {"house_derived_text"},
    },
    "solen_profile": {
        "stability_classes": {"very_slow"},
        "source_classes": {"solen_profile"},
        "content_kinds": {"house_derived_text"},
    },
    "relationship_footing": {
        "stability_classes": {"very_slow"},
        "source_classes": {"relationship_footing"},
        "content_kinds": {"house_derived_text"},
    },
    "core_memory": {
        "stability_classes": {"slow"},
        "source_classes": {"memory"},
        "content_kinds": {"house_derived_text"},
    },
    "capability": {
        "stability_classes": {"slow"},
        "source_classes": {"capability_description"},
        "content_kinds": {"house_derived_text"},
    },
    "approved_reference": {
        "stability_classes": {"slow"},
        "source_classes": {"memory", "attachment", "room_checkpoint"},
        "content_kinds": {
            "exact_source_text",
            "code_source_quotation",
            "house_derived_text",
        },
    },
    "room_checkpoint": {
        "stability_classes": {"checkpoint"},
        "source_classes": {"room_checkpoint"},
        "content_kinds": {"future_card_checkpoint"},
    },
}

SENSITIVITY_CLASSES = (
    "synthetic",
    "owner_approved_low_sensitivity",
    "private",
)
REQUIRED_VALUES = ("required", "optional")
SINGLETON_LAW_CLASSES = frozenset(LAW_CLASS_ORDER)

_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_DEVICE_NAMES = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class PromptRegistryManifestError(ValueError):
    """Raised when a registry manifest, root, or content file is invalid."""


class PrivateContentMode(Enum):
    """Closed local policy for loading owner-private registry content."""

    DISABLED = "disabled"
    OWNER_AUTHORIZED_PRIVATE = "owner_authorized_private"


@dataclass(frozen=True)
class RegistryContent:
    slot_key: str
    class_name: str
    semantic_label: str
    content_relative_path: str
    content_version: str
    required_or_optional: str
    selection_priority: int
    stability_class: str
    exactness: str
    source_class: str
    content_kind: str
    derivation_version: str | None
    sensitivity_class: str
    enabled: bool
    budget_class: str
    content_sha256: str
    resolved_path: Path
    content_text: str


@dataclass(frozen=True)
class InstructionLawEntry(RegistryContent):
    """Typed owner that can produce instruction-law units only."""


@dataclass(frozen=True)
class ContextCardEntry(RegistryContent):
    """Typed owner that can produce descriptive context-card units only."""


@dataclass(frozen=True)
class InstructionLawRegistry:
    schema_version: str
    registry_epoch: str
    entries: tuple[InstructionLawEntry, ...]


@dataclass(frozen=True)
class ContextCardRegistry:
    schema_version: str
    registry_epoch: str
    entries: tuple[ContextCardEntry, ...]


@dataclass(frozen=True)
class RegistryPair:
    instruction_law: InstructionLawRegistry
    context_cards: ContextCardRegistry


@dataclass(frozen=True)
class RegistryStateBinding:
    registry_epoch: str
    state_sha256: str


@dataclass(frozen=True)
class BudgetStateBinding:
    policy_version: str
    state_sha256: str


@dataclass(frozen=True)
class CheckpointStateBinding:
    checkpoint_epoch: str
    slot_key: str | None
    content_version: str | None
    content_sha256: str | None


@dataclass(frozen=True)
class SnapshotStateBinding:
    snapshot_epoch: str
    state_sha256: str


@dataclass(frozen=True)
class RegistryIntegrityLock:
    schema_version: str
    instruction_law_registry: RegistryStateBinding
    context_card_registry: RegistryStateBinding
    budget_policy: BudgetStateBinding
    checkpoint: CheckpointStateBinding
    snapshot: SnapshotStateBinding
    entries: tuple[tuple[str, str, str, str], ...]


def _closed_object(
    value: Any,
    *,
    fields: Sequence[str],
    label: str,
) -> Mapping[str, Any]:
    if (
        not isinstance(value, Mapping)
        or len(value) != len(fields)
        or set(value) != set(fields)
    ):
        raise PromptRegistryManifestError(f"{label} fields are not exact")
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


def _identifier(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise PromptRegistryManifestError(
            f"{label} must be a bounded lowercase ASCII identifier"
        )
    return value


def _text(value: Any, *, label: str, max_chars: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > max_chars:
        raise PromptRegistryManifestError(f"{label} must be bounded nonempty text")
    if "\x00" in value:
        raise PromptRegistryManifestError(f"{label} contains NUL")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PromptRegistryManifestError(
            f"{label} must contain Unicode scalar text"
        ) from exc
    return value


def _enum(value: Any, allowed: Sequence[str], *, label: str) -> str:
    if value not in allowed:
        raise PromptRegistryManifestError(f"{label} is unsupported")
    return str(value)


def _reject_float(value: str) -> None:
    raise PromptRegistryManifestError("registry JSON does not allow floats")


def _reject_constant(value: str) -> None:
    raise PromptRegistryManifestError("registry JSON constant is unsupported")


def _reject_duplicate_object_pairs(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PromptRegistryManifestError(
                "registry JSON contains a duplicate object key"
            )
        value[key] = item
    return value


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & reparse_flag)


def _safe_file_bytes(
    path: Path,
    *,
    label: str,
    max_bytes: int,
) -> bytes:
    if _is_link_or_reparse(path) or not path.is_file():
        raise PromptRegistryManifestError(f"{label} must be a regular non-link file")
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise PromptRegistryManifestError(f"{label} must be a regular file")
    if info.st_size > max_bytes:
        raise PromptRegistryManifestError(f"{label} exceeds its local loader limit")
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raise PromptRegistryManifestError(f"{label} exceeds its local loader limit")
    return raw


def _strict_json_file(
    path: Path,
    *,
    label: str,
    max_bytes: int,
) -> Mapping[str, Any]:
    raw = _safe_file_bytes(path, label=label, max_bytes=max_bytes)
    if raw.startswith(b"\xef\xbb\xbf"):
        raise PromptRegistryManifestError(f"{label} must not contain a UTF-8 BOM")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PromptRegistryManifestError(f"{label} must be strict UTF-8") from exc
    try:
        value = json.loads(
            text,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_object_pairs,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, PromptRegistryManifestError):
            raise
        raise PromptRegistryManifestError(f"{label} JSON is invalid") from exc
    if not isinstance(value, Mapping):
        raise PromptRegistryManifestError(f"{label} must be a JSON object")
    return value


def load_strict_json_object(
    path: Path,
    *,
    label: str,
    max_bytes: int = MAX_MANIFEST_JSON_BYTES,
) -> Mapping[str, Any]:
    """Load one BOM-free, duplicate-key-free, closed-owner JSON object."""

    if type(max_bytes) is not int or max_bytes <= 0:
        raise PromptRegistryManifestError("JSON loader limit must be a positive integer")
    return _strict_json_file(path, label=label, max_bytes=max_bytes)


def _root(path: Path, *, label: str) -> Path:
    if (
        not path.is_absolute()
        or _is_link_or_reparse(path)
        or not path.is_dir()
    ):
        raise PromptRegistryManifestError(
            f"{label} must be an absolute non-link directory"
        )
    resolved = path.resolve(strict=True)
    if resolved != path:
        raise PromptRegistryManifestError(f"{label} must already be canonical")
    return resolved


def _relative_content_path(value: Any, *, label: str) -> PurePosixPath:
    text = _text(value, label=label, max_chars=240)
    if "\\" in text or text.startswith(("/", "//")):
        raise PromptRegistryManifestError(
            f"{label} must use relative forward-slash path syntax"
        )
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != text
        or any(
            ":" in part
            or part.endswith((" ", "."))
            or any(character in '<>"|?*' or ord(character) < 32 for character in part)
            or part.rstrip(" .").split(".", 1)[0].casefold()
            in _WINDOWS_DEVICE_NAMES
            for part in path.parts
        )
    ):
        raise PromptRegistryManifestError(f"{label} is not a safe relative path")
    return path


def _content_path(root: Path, relative: PurePosixPath, *, label: str) -> Path:
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if _is_link_or_reparse(current):
            raise PromptRegistryManifestError(f"{label} contains a link")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PromptRegistryManifestError(f"{label} does not exist") from exc
    if not resolved.is_relative_to(root):
        raise PromptRegistryManifestError(f"{label} escapes its registry root")
    if resolved != candidate or candidate.is_symlink():
        raise PromptRegistryManifestError(f"{label} is not canonical")
    return resolved


def _content_text(
    path: Path,
    *,
    canonical_house_text: bool,
    label: str,
) -> tuple[str, str]:
    raw = _safe_file_bytes(
        path,
        label=label,
        max_bytes=MAX_CONTENT_FILE_BYTES,
    )
    if raw.startswith(b"\xef\xbb\xbf"):
        raise PromptRegistryManifestError(f"{label} must not contain a UTF-8 BOM")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PromptRegistryManifestError(f"{label} must be strict UTF-8") from exc
    if not text or not text.strip():
        raise PromptRegistryManifestError(f"{label} must contain nonempty text")
    if "\x00" in text:
        raise PromptRegistryManifestError(f"{label} contains NUL")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PromptRegistryManifestError(
            f"{label} must contain Unicode scalar text"
        ) from exc
    if canonical_house_text and (
        "\r" in text or unicodedata.normalize("NFC", text) != text
    ):
        raise PromptRegistryManifestError(
            f"{label} must use canonical NFC text with LF line endings"
        )
    return text, hashlib.sha256(raw).hexdigest()


def _semantic_label(value: Any, *, label: str) -> str:
    text = _text(value, label=label, max_chars=160)
    if "\r" in text or "\n" in text or unicodedata.normalize("NFC", text) != text:
        raise PromptRegistryManifestError(
            f"{label} must be one canonical NFC line"
        )
    if provider_text_safety.contains_forbidden_text(text):
        raise PromptRegistryManifestError(
            f"{label} violates provider-visible safety"
        )
    return text


def _entry_common(
    item: Mapping[str, Any],
    *,
    class_field: str,
    class_order: Sequence[str],
    root: Path,
    registry_kind: str,
    locks: Mapping[tuple[str, str, str], str],
    private_content_mode: PrivateContentMode,
) -> dict[str, Any]:
    slot_key = _identifier(item["slot_key"], label="slot_key")
    class_name = _enum(item[class_field], class_order, label=class_field)
    semantic_label = _semantic_label(
        item["semantic_label"],
        label="semantic_label",
    )
    relative = _relative_content_path(
        item["content_relative_path"],
        label="content_relative_path",
    )
    content_version = _identifier(
        item["content_version"],
        label="content_version",
    )
    required = _enum(
        item["required_or_optional"],
        REQUIRED_VALUES,
        label="required_or_optional",
    )
    priority = item["selection_priority"]
    if type(priority) is not int or not 0 <= priority <= 1_000_000:
        raise PromptRegistryManifestError(
            "selection_priority must be an integer from 0 through 1000000"
        )
    exactness = _enum(
        item["exactness"],
        ("exact", "derived"),
        label="exactness",
    )
    source_class = _identifier(item["source_class"], label="source_class")
    content_kind = _identifier(item["content_kind"], label="content_kind")
    derivation_raw = item["derivation_version"]
    derivation = (
        None
        if derivation_raw is None
        else _identifier(derivation_raw, label="derivation_version")
    )
    sensitivity = _enum(
        item["sensitivity_class"],
        SENSITIVITY_CLASSES,
        label="sensitivity_class",
    )
    if (
        sensitivity == "private"
        and private_content_mode is not PrivateContentMode.OWNER_AUTHORIZED_PRIVATE
    ):
        raise PromptRegistryManifestError(
            "private registry content is not enabled for this local gate"
        )
    enabled = item["enabled"]
    if type(enabled) is not bool:
        raise PromptRegistryManifestError("enabled must be a boolean")
    budget_class = _identifier(item["budget_class"], label="budget_class")
    if exactness == "exact":
        if content_kind not in {"exact_source_text", "code_source_quotation"}:
            raise PromptRegistryManifestError(
                "exact registry content requires an exact-source content kind"
            )
        if derivation is not None:
            raise PromptRegistryManifestError(
                "exact registry content cannot declare derivation"
            )
    else:
        if content_kind not in {
            "house_derived_text",
            "structured_data",
            "future_card_checkpoint",
        }:
            raise PromptRegistryManifestError(
                "derived registry content requires a derived content kind"
            )
        if derivation is None:
            raise PromptRegistryManifestError(
                "derived registry content requires derivation_version"
            )

    path = _content_path(root, relative, label=f"content for {slot_key}")
    canonical_house_text = (
        registry_kind == "instruction_law" or exactness == "derived"
    )
    content_text, actual_digest = _content_text(
        path,
        canonical_house_text=canonical_house_text,
        label=f"content for {slot_key}",
    )
    lock_key = (registry_kind, slot_key, content_version)
    locked_digest = locks.get(lock_key)
    if locked_digest is None or actual_digest != locked_digest:
        raise PromptRegistryManifestError(
            "content integrity changed without a matching versioned lock"
        )

    return {
        "slot_key": slot_key,
        "class_name": class_name,
        "semantic_label": semantic_label,
        "content_relative_path": relative.as_posix(),
        "content_version": content_version,
        "required_or_optional": required,
        "selection_priority": priority,
        "exactness": exactness,
        "source_class": source_class,
        "content_kind": content_kind,
        "derivation_version": derivation,
        "sensitivity_class": sensitivity,
        "enabled": enabled,
        "budget_class": budget_class,
        "content_sha256": locked_digest,
        "resolved_path": path,
        "content_text": content_text,
    }


def _sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise PromptRegistryManifestError(f"{label} must be a lowercase SHA-256")
    return value


def _registry_state_binding(
    value: Any,
    *,
    label: str,
) -> RegistryStateBinding:
    item = _closed_object(
        value,
        fields=("registry_epoch", "state_sha256"),
        label=label,
    )
    return RegistryStateBinding(
        registry_epoch=_identifier(
            item["registry_epoch"],
            label=f"{label}.registry_epoch",
        ),
        state_sha256=_sha256(
            item["state_sha256"],
            label=f"{label}.state_sha256",
        ),
    )


def load_integrity_lock(path: Path) -> RegistryIntegrityLock:
    value = _strict_json_file(
        path,
        label="registry integrity lock",
        max_bytes=MAX_INTEGRITY_LOCK_JSON_BYTES,
    )
    _closed_object(
        value,
        fields=(
            "schema_version",
            "instruction_law_registry",
            "context_card_registry",
            "budget_policy",
            "checkpoint",
            "snapshot",
            "entries",
        ),
        label="registry integrity lock",
    )
    if value["schema_version"] != INTEGRITY_LOCK_SCHEMA_VERSION:
        raise PromptRegistryManifestError(
            "registry integrity lock schema is unsupported"
        )
    entries = value["entries"]
    if not isinstance(entries, list):
        raise PromptRegistryManifestError("integrity lock entries must be a list")
    if len(entries) > MAX_REGISTRY_ENTRIES * 2:
        raise PromptRegistryManifestError(
            "integrity lock exceeds the total registry entry limit"
        )
    locks: dict[tuple[str, str, str], str] = {}
    for index, raw in enumerate(entries):
        item = _closed_object(
            raw,
            fields=(
                "registry_kind",
                "slot_key",
                "content_version",
                "content_sha256",
            ),
            label=f"integrity lock entry {index}",
        )
        kind = _enum(
            item["registry_kind"],
            ("instruction_law", "context_card"),
            label="registry_kind",
        )
        slot = _identifier(item["slot_key"], label="slot_key")
        version = _identifier(item["content_version"], label="content_version")
        digest = _sha256(
            item["content_sha256"],
            label="integrity lock content_sha256",
        )
        key = (kind, slot, version)
        if key in locks:
            raise PromptRegistryManifestError(
                "integrity lock contains a duplicate slot/version"
            )
        locks[key] = digest
    budget = _closed_object(
        value["budget_policy"],
        fields=("policy_version", "state_sha256"),
        label="budget policy state binding",
    )
    checkpoint = _closed_object(
        value["checkpoint"],
        fields=(
            "checkpoint_epoch",
            "slot_key",
            "content_version",
            "content_sha256",
        ),
        label="checkpoint state binding",
    )
    checkpoint_values = (
        checkpoint["slot_key"],
        checkpoint["content_version"],
        checkpoint["content_sha256"],
    )
    if all(item is None for item in checkpoint_values):
        slot_key = None
        content_version = None
        content_sha256 = None
    elif any(item is None for item in checkpoint_values):
        raise PromptRegistryManifestError(
            "checkpoint identity fields must be all present or all null"
        )
    else:
        slot_key = _identifier(checkpoint["slot_key"], label="checkpoint.slot_key")
        content_version = _identifier(
            checkpoint["content_version"],
            label="checkpoint.content_version",
        )
        content_sha256 = _sha256(
            checkpoint["content_sha256"],
            label="checkpoint.content_sha256",
        )
    snapshot = _closed_object(
        value["snapshot"],
        fields=("snapshot_epoch", "state_sha256"),
        label="snapshot state binding",
    )
    return RegistryIntegrityLock(
        schema_version=INTEGRITY_LOCK_SCHEMA_VERSION,
        instruction_law_registry=_registry_state_binding(
            value["instruction_law_registry"],
            label="instruction-law registry state binding",
        ),
        context_card_registry=_registry_state_binding(
            value["context_card_registry"],
            label="context-card registry state binding",
        ),
        budget_policy=BudgetStateBinding(
            policy_version=_identifier(
                budget["policy_version"],
                label="budget_policy.policy_version",
            ),
            state_sha256=_sha256(
                budget["state_sha256"],
                label="budget_policy.state_sha256",
            ),
        ),
        checkpoint=CheckpointStateBinding(
            checkpoint_epoch=_identifier(
                checkpoint["checkpoint_epoch"],
                label="checkpoint.checkpoint_epoch",
            ),
            slot_key=slot_key,
            content_version=content_version,
            content_sha256=content_sha256,
        ),
        snapshot=SnapshotStateBinding(
            snapshot_epoch=_identifier(
                snapshot["snapshot_epoch"],
                label="snapshot.snapshot_epoch",
            ),
            state_sha256=_sha256(
                snapshot["state_sha256"],
                label="snapshot.state_sha256",
            ),
        ),
        entries=tuple(
            (kind, slot, version, digest)
            for (kind, slot, version), digest in sorted(locks.items())
        ),
    )


def _manifest(
    root: Path,
    *,
    registry_kind: str,
    locks: Mapping[tuple[str, str, str], str],
    private_content_mode: PrivateContentMode,
) -> InstructionLawRegistry | ContextCardRegistry:
    canonical_root = _root(root, label=f"{registry_kind} root")
    value = _strict_json_file(
        canonical_root / MANIFEST_FILENAME,
        label=f"{registry_kind} manifest",
        max_bytes=MAX_MANIFEST_JSON_BYTES,
    )
    _closed_object(
        value,
        fields=("schema_version", "registry_epoch", "entries"),
        label=f"{registry_kind} manifest",
    )
    epoch = _identifier(value["registry_epoch"], label="registry_epoch")
    raw_entries = value["entries"]
    if not isinstance(raw_entries, list):
        raise PromptRegistryManifestError("registry entries must be a list")
    if len(raw_entries) > MAX_REGISTRY_ENTRIES:
        raise PromptRegistryManifestError(
            "registry manifest exceeds the entry-count limit"
        )

    if registry_kind == "instruction_law":
        expected_schema = INSTRUCTION_LAW_MANIFEST_SCHEMA_VERSION
        entry_fields = LAW_ENTRY_FIELDS
        class_field = "law_class"
        class_order = LAW_CLASS_ORDER
    else:
        expected_schema = CONTEXT_CARD_MANIFEST_SCHEMA_VERSION
        entry_fields = CARD_ENTRY_FIELDS
        class_field = "card_class"
        class_order = CARD_CLASS_ORDER
    if value["schema_version"] != expected_schema:
        raise PromptRegistryManifestError("registry manifest schema is unsupported")

    entries: list[InstructionLawEntry | ContextCardEntry] = []
    slot_keys: set[str] = set()
    resolved_paths: set[Path] = set()
    for index, raw in enumerate(raw_entries):
        item = _closed_object(
            raw,
            fields=entry_fields,
            label=f"{registry_kind} entry {index}",
        )
        common = _entry_common(
            item,
            class_field=class_field,
            class_order=class_order,
            root=canonical_root,
            registry_kind=registry_kind,
            locks=locks,
            private_content_mode=private_content_mode,
        )
        slot_key = common["slot_key"]
        resolved_path = common["resolved_path"]
        if slot_key in slot_keys:
            raise PromptRegistryManifestError(
                "registry contains a duplicate stable slot key"
            )
        if resolved_path in resolved_paths:
            raise PromptRegistryManifestError(
                "registry contains a duplicate resolved content path"
            )
        slot_keys.add(slot_key)
        resolved_paths.add(resolved_path)

        if registry_kind == "instruction_law":
            stability = _enum(
                item["stability_class"],
                ("immutable", "versioned"),
                label="stability_class",
            )
            rules = LAW_CLASS_RULES[common["class_name"]]
            if (
                common["source_class"] not in rules["source_classes"]
                or common["content_kind"] not in rules["content_kinds"]
                or common["budget_class"] != "instruction_law"
            ):
                raise PromptRegistryManifestError(
                    "instruction-law class/source/content/budget combination is invalid"
                )
            entries.append(
                InstructionLawEntry(
                    **common,
                    stability_class=stability,
                )
            )
        else:
            stability = _enum(
                item["stability_class"],
                CARD_STABILITY_ORDER,
                label="stability_class",
            )
            rules = CARD_CLASS_RULES[common["class_name"]]
            if (
                stability not in rules["stability_classes"]
                or common["source_class"] not in rules["source_classes"]
                or common["content_kind"] not in rules["content_kinds"]
                or common["budget_class"] != common["class_name"]
            ):
                raise PromptRegistryManifestError(
                    "context-card class/stability/source/content/budget combination is invalid"
                )
            entries.append(
                ContextCardEntry(
                    **common,
                    stability_class=stability,
                )
            )

    if registry_kind == "instruction_law":
        class_counts: dict[str, int] = {}
        for entry in entries:
            class_counts[entry.class_name] = class_counts.get(entry.class_name, 0) + 1
        if any(
            class_name in SINGLETON_LAW_CLASSES and count > 1
            for class_name, count in class_counts.items()
        ):
            raise PromptRegistryManifestError(
                "instruction-law singleton class appears more than once"
            )
        ordered = tuple(
            sorted(
                entries,
                key=lambda entry: (
                    LAW_CLASS_ORDER.index(entry.class_name),
                    entry.selection_priority,
                    entry.slot_key,
                    entry.content_version,
                ),
            )
        )
        return InstructionLawRegistry(
            schema_version=expected_schema,
            registry_epoch=epoch,
            entries=ordered,  # type: ignore[arg-type]
        )
    if (
        sum(
            1
            for entry in entries
            if entry.class_name == "room_checkpoint" and entry.enabled
        )
        > 1
    ):
        raise PromptRegistryManifestError(
            "the singular checkpoint contract allows at most one enabled checkpoint"
        )
    ordered = tuple(
        sorted(
            entries,
            key=lambda entry: (
                CARD_STABILITY_ORDER.index(entry.stability_class),
                CARD_CLASS_ORDER.index(entry.class_name),
                entry.selection_priority,
                entry.slot_key,
                entry.content_version,
            ),
        )
    )
    return ContextCardRegistry(
        schema_version=expected_schema,
        registry_epoch=epoch,
        entries=ordered,  # type: ignore[arg-type]
    )


def _registry_entry_state(entry: RegistryContent) -> dict[str, Any]:
    return {
        "slot_key": entry.slot_key,
        "class_name": entry.class_name,
        "semantic_label": entry.semantic_label,
        "content_relative_path": entry.content_relative_path,
        "content_version": entry.content_version,
        "required_or_optional": entry.required_or_optional,
        "selection_priority": entry.selection_priority,
        "stability_class": entry.stability_class,
        "exactness": entry.exactness,
        "source_class": entry.source_class,
        "content_kind": entry.content_kind,
        "derivation_version": entry.derivation_version,
        "sensitivity_class": entry.sensitivity_class,
        "enabled": entry.enabled,
        "budget_class": entry.budget_class,
        "content_sha256": entry.content_sha256,
    }


def registry_state_sha256(
    registry: InstructionLawRegistry | ContextCardRegistry,
    *,
    registry_kind: str,
) -> str:
    """Hash all ordered semantic metadata and content locks, excluding the epoch."""

    if registry_kind == "instruction_law":
        if type(registry) is not InstructionLawRegistry:
            raise PromptRegistryManifestError(
                "instruction-law registry has the wrong direct type"
            )
        expected_schema = INSTRUCTION_LAW_MANIFEST_SCHEMA_VERSION
        entry_type = InstructionLawEntry
    elif registry_kind == "context_card":
        if type(registry) is not ContextCardRegistry:
            raise PromptRegistryManifestError(
                "context-card registry has the wrong direct type"
            )
        expected_schema = CONTEXT_CARD_MANIFEST_SCHEMA_VERSION
        entry_type = ContextCardEntry
    else:
        raise PromptRegistryManifestError("registry kind is unsupported")
    if registry.schema_version != expected_schema or type(registry.entries) is not tuple:
        raise PromptRegistryManifestError("registry direct fields are invalid")
    if any(type(entry) is not entry_type for entry in registry.entries):
        raise PromptRegistryManifestError("registry entry has the wrong direct type")
    return _canonical_sha256(
        {
            "registry_kind": registry_kind,
            "schema_version": registry.schema_version,
            "entries": [
                _registry_entry_state(entry)
                for entry in registry.entries
            ],
        }
    )


def bound_registry_epoch(registry_kind: str, state_sha256: str) -> str:
    digest = _sha256(state_sha256, label="registry state_sha256")
    prefixes = {
        "instruction_law": "instruction_law_epoch",
        "context_card": "context_card_epoch",
    }
    try:
        prefix = prefixes[registry_kind]
    except KeyError as exc:
        raise PromptRegistryManifestError("registry kind is unsupported") from exc
    return f"{prefix}_{digest}"


def _content_lock_map(
    integrity_lock: RegistryIntegrityLock,
) -> dict[tuple[str, str, str], str]:
    return {
        (kind, slot, version): digest
        for kind, slot, version, digest in integrity_lock.entries
    }


def _validate_registry_binding(
    registry: InstructionLawRegistry | ContextCardRegistry,
    *,
    registry_kind: str,
    binding: RegistryStateBinding,
) -> None:
    digest = registry_state_sha256(registry, registry_kind=registry_kind)
    expected_epoch = bound_registry_epoch(registry_kind, digest)
    if (
        registry.registry_epoch != expected_epoch
        or binding.registry_epoch != expected_epoch
        or binding.state_sha256 != digest
    ):
        raise PromptRegistryManifestError(
            f"{registry_kind} semantic state is not bound to its epoch"
        )


def revalidate_loaded_registry_pair(pair: RegistryPair) -> RegistryPair:
    """Re-attest direct dataclass fields and their still-loaded source files."""

    if (
        type(pair) is not RegistryPair
        or type(pair.instruction_law) is not InstructionLawRegistry
        or type(pair.context_cards) is not ContextCardRegistry
    ):
        raise PromptRegistryManifestError("registry pair has the wrong direct type")
    registries = (
        ("instruction_law", pair.instruction_law, InstructionLawEntry),
        ("context_card", pair.context_cards, ContextCardEntry),
    )
    for registry_kind, registry, entry_type in registries:
        if type(registry.entries) is not tuple:
            raise PromptRegistryManifestError("registry entries must be an exact tuple")
        for entry in registry.entries:
            if type(entry) is not entry_type:
                raise PromptRegistryManifestError(
                    "registry entry has the wrong direct type"
                )
            scalar_types = (
                (entry.slot_key, str),
                (entry.class_name, str),
                (entry.semantic_label, str),
                (entry.content_relative_path, str),
                (entry.content_version, str),
                (entry.required_or_optional, str),
                (entry.selection_priority, int),
                (entry.stability_class, str),
                (entry.exactness, str),
                (entry.source_class, str),
                (entry.content_kind, str),
                (entry.sensitivity_class, str),
                (entry.enabled, bool),
                (entry.budget_class, str),
                (entry.content_sha256, str),
                (entry.content_text, str),
            )
            if (
                any(
                    type(value) is not expected
                    for value, expected in scalar_types
                )
                or not isinstance(entry.resolved_path, Path)
            ):
                raise PromptRegistryManifestError(
                    "registry entry contains an invalid direct field type"
                )
            if entry.derivation_version is not None and type(
                entry.derivation_version
            ) is not str:
                raise PromptRegistryManifestError(
                    "registry derivation_version has the wrong direct type"
                )
            raw = _safe_file_bytes(
                entry.resolved_path,
                label=f"content for {entry.slot_key}",
                max_bytes=MAX_CONTENT_FILE_BYTES,
            )
            try:
                text = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise PromptRegistryManifestError(
                    "loaded registry content is no longer strict UTF-8"
                ) from exc
            if (
                text != entry.content_text
                or hashlib.sha256(raw).hexdigest() != entry.content_sha256
            ):
                raise PromptRegistryManifestError(
                    "loaded registry content no longer matches its attested file"
                )
        digest = registry_state_sha256(
            registry,
            registry_kind=registry_kind,
        )
        if registry.registry_epoch != bound_registry_epoch(
            registry_kind,
            digest,
        ):
            raise PromptRegistryManifestError(
                f"{registry_kind} direct state is not bound to its epoch"
            )
    return pair


def _load_registry_pair_from_lock(
    *,
    instruction_law_root: Path,
    context_card_root: Path,
    integrity_lock: RegistryIntegrityLock,
    private_content_mode: PrivateContentMode,
) -> RegistryPair:
    locks = _content_lock_map(integrity_lock)
    law = _manifest(
        instruction_law_root,
        registry_kind="instruction_law",
        locks=locks,
        private_content_mode=private_content_mode,
    )
    cards = _manifest(
        context_card_root,
        registry_kind="context_card",
        locks=locks,
        private_content_mode=private_content_mode,
    )
    assert isinstance(law, InstructionLawRegistry)
    assert isinstance(cards, ContextCardRegistry)
    expected_locks = {
        (
            "instruction_law",
            entry.slot_key,
            entry.content_version,
        )
        for entry in law.entries
    } | {
        (
            "context_card",
            entry.slot_key,
            entry.content_version,
        )
        for entry in cards.entries
    }
    if set(locks) != expected_locks:
        raise PromptRegistryManifestError(
            "integrity lock entries must exactly match both registries"
        )
    _validate_registry_binding(
        law,
        registry_kind="instruction_law",
        binding=integrity_lock.instruction_law_registry,
    )
    _validate_registry_binding(
        cards,
        registry_kind="context_card",
        binding=integrity_lock.context_card_registry,
    )
    return RegistryPair(instruction_law=law, context_cards=cards)


def load_registry_pair(
    *,
    instruction_law_root: Path,
    context_card_root: Path,
    integrity_lock_path: Path,
    private_content_mode: PrivateContentMode = PrivateContentMode.DISABLED,
) -> RegistryPair:
    """Load both typed registries against one owner-private integrity lock."""

    if type(private_content_mode) is not PrivateContentMode:
        raise PromptRegistryManifestError(
            "private_content_mode must use the closed PrivateContentMode policy"
        )
    integrity_lock = load_integrity_lock(integrity_lock_path)
    return _load_registry_pair_from_lock(
        instruction_law_root=instruction_law_root,
        context_card_root=context_card_root,
        integrity_lock=integrity_lock,
        private_content_mode=private_content_mode,
    )
