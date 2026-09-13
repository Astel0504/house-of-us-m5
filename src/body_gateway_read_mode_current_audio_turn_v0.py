from __future__ import annotations

import re
from typing import Any, Callable, Mapping


FIELD_NAME = "read_mode_current_audio_recognition"
SNAPSHOT_FIELDS = {"audio_recognition", "talk_projection"}
AUDIO_RECOGNITION_FIELDS = {
    "transcript",
    "meaning",
    "audio_events",
    "voice_observations",
    "emotion_intent_observations",
    "background_observations",
    "uncertainties",
    "language",
    "source_strength",
    "recognition_provenance",
    "contract_version",
}
TALK_PROJECTION_FIELDS = {
    "text",
    "text_source",
    "provider_visible_context",
    "raw_audio_included",
}
CONTRACT_VERSION = "body_android_audio_understanding_current_turn_v0"
RECOGNITION_PROVENANCE = "house_audio_current_turn_v0"
PROVIDER_VISIBLE_CONTEXT = "Astel's current audio is available here as English recognized material."
MAX_CURRENT_TURN_ATTACHMENT_ITEMS = 3
MAX_TRANSCRIPT_CHARS = 2400
MAX_MEANING_CHARS = 1000
MAX_OBSERVATION_ITEMS = 8
MAX_OBSERVATION_CHARS = 220

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{8,}", re.IGNORECASE),
    re.compile(r"(?:authorization|api[_-]?key|token|password)\s*[:=]\s*\S+", re.IGNORECASE),
)
RAW_OR_LOCAL_PATTERNS = (
    re.compile(r"data:audio", re.IGNORECASE),
    re.compile(r";base64,", re.IGNORECASE),
    re.compile(r"(?:content|file)://", re.IGNORECASE),
    re.compile(r"(?:^|\s)[A-Za-z]:[\\/]"),
    re.compile(r"(?:^|\s)/(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+"),
    re.compile(r"(?:^|\s)\\\\[^\\\s]+\\[^\\\s]+"),
)


class CurrentAudioTurnError(ValueError):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.message = message


def _exact_mapping(value: Any, expected_fields: set[str], *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CurrentAudioTurnError("invalid_current_audio_snapshot", f"{path} must be an object.")
    if set(value) != expected_fields:
        raise CurrentAudioTurnError("invalid_current_audio_schema", f"{path} has an invalid field set.")
    return value


def _safe_text(value: Any, *, path: str, max_chars: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise CurrentAudioTurnError("invalid_current_audio_text", f"{path} must be text.")
    if not value.strip() or len(value) > max_chars or "\x00" in value:
        if not required and not value:
            return ""
        raise CurrentAudioTurnError("invalid_current_audio_text", f"{path} is empty or exceeds its limit.")
    for pattern in SECRET_PATTERNS + RAW_OR_LOCAL_PATTERNS:
        if pattern.search(value):
            raise CurrentAudioTurnError(
                "forbidden_current_audio_material",
                "Current audio recognition contains forbidden raw, secret, URI, or local-path material.",
            )
    return value


def _safe_list(value: Any, *, path: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_OBSERVATION_ITEMS:
        raise CurrentAudioTurnError("invalid_current_audio_observations", f"{path} must be a bounded list.")
    return [
        _safe_text(item, path=f"{path}[{index}]", max_chars=MAX_OBSERVATION_CHARS)
        for index, item in enumerate(value)
    ]


def _attachment_count(value: Any, *, field_name: str) -> int:
    if value is None:
        return 0
    if not isinstance(value, list):
        raise CurrentAudioTurnError(
            "invalid_current_turn_attachment_list",
            f"{field_name} must be a list when present.",
        )
    return len(value)


def validate_snapshot(
    value: Any,
    *,
    read_mode_source_summaries: Any = None,
    read_mode_exact_text_attachments: Any = None,
) -> dict[str, Any] | None:
    source_count = _attachment_count(
        read_mode_source_summaries,
        field_name="read_mode_source_summaries",
    )
    exact_count = _attachment_count(
        read_mode_exact_text_attachments,
        field_name="read_mode_exact_text_attachments",
    )
    if value is None:
        return None
    snapshot = _exact_mapping(value, SNAPSHOT_FIELDS, path=FIELD_NAME)
    if 1 + source_count + exact_count > MAX_CURRENT_TURN_ATTACHMENT_ITEMS:
        raise CurrentAudioTurnError(
            "current_turn_attachment_limit_exceeded",
            "Current audio and media or Source attachments exceed the three-item turn limit.",
        )
    recognition = _exact_mapping(
        snapshot.get("audio_recognition"),
        AUDIO_RECOGNITION_FIELDS,
        path=f"{FIELD_NAME}.audio_recognition",
    )
    projection = _exact_mapping(
        snapshot.get("talk_projection"),
        TALK_PROJECTION_FIELDS,
        path=f"{FIELD_NAME}.talk_projection",
    )
    transcript_value = recognition.get("transcript")
    if transcript_value is None:
        transcript = None
    else:
        transcript = _safe_text(
            transcript_value,
            path=f"{FIELD_NAME}.audio_recognition.transcript",
            max_chars=MAX_TRANSCRIPT_CHARS,
        )
    meaning = _safe_text(
        recognition.get("meaning"),
        path=f"{FIELD_NAME}.audio_recognition.meaning",
        max_chars=MAX_MEANING_CHARS,
    )
    language = recognition.get("language")
    source_strength = recognition.get("source_strength")
    if language != "en":
        raise CurrentAudioTurnError("invalid_current_audio_language", "Current audio recognition language must be English.")
    if source_strength not in {"transcript", "meaning_only"}:
        raise CurrentAudioTurnError(
            "invalid_current_audio_source_strength",
            "Current audio source strength is invalid.",
        )
    if (source_strength == "transcript") != bool(transcript):
        raise CurrentAudioTurnError(
            "current_audio_transcript_strength_mismatch",
            "Current audio transcript and source strength do not match.",
        )
    if recognition.get("recognition_provenance") != RECOGNITION_PROVENANCE:
        raise CurrentAudioTurnError(
            "invalid_current_audio_provenance",
            "Current audio recognition provenance is invalid.",
        )
    if recognition.get("contract_version") != CONTRACT_VERSION:
        raise CurrentAudioTurnError(
            "invalid_current_audio_contract",
            "Current audio recognition contract version is invalid.",
        )
    text_source = projection.get("text_source")
    expected_text_source = "transcript" if transcript else "meaning"
    expected_text = transcript or meaning
    if text_source != expected_text_source or projection.get("text") != expected_text:
        raise CurrentAudioTurnError(
            "current_audio_talk_projection_mismatch",
            "Current audio Talk projection does not match the recognition snapshot.",
        )
    if projection.get("provider_visible_context") != PROVIDER_VISIBLE_CONTEXT:
        raise CurrentAudioTurnError(
            "invalid_current_audio_provider_context",
            "Current audio provider-visible context is invalid.",
        )
    if projection.get("raw_audio_included") is not False:
        raise CurrentAudioTurnError(
            "raw_current_audio_not_allowed",
            "Raw audio is not allowed in the current Talk snapshot.",
        )
    canonical = {
        "audio_recognition": {
            "transcript": transcript,
            "meaning": meaning,
            "audio_events": _safe_list(
                recognition.get("audio_events"),
                path=f"{FIELD_NAME}.audio_recognition.audio_events",
            ),
            "voice_observations": _safe_list(
                recognition.get("voice_observations"),
                path=f"{FIELD_NAME}.audio_recognition.voice_observations",
            ),
            "emotion_intent_observations": _safe_list(
                recognition.get("emotion_intent_observations"),
                path=f"{FIELD_NAME}.audio_recognition.emotion_intent_observations",
            ),
            "background_observations": _safe_list(
                recognition.get("background_observations"),
                path=f"{FIELD_NAME}.audio_recognition.background_observations",
            ),
            "uncertainties": _safe_list(
                recognition.get("uncertainties"),
                path=f"{FIELD_NAME}.audio_recognition.uncertainties",
            ),
            "language": "en",
            "source_strength": source_strength,
            "recognition_provenance": RECOGNITION_PROVENANCE,
            "contract_version": CONTRACT_VERSION,
        },
        "talk_projection": {
            "text": _safe_text(
                projection.get("text"),
                path=f"{FIELD_NAME}.talk_projection.text",
                max_chars=MAX_TRANSCRIPT_CHARS,
            ),
            "text_source": expected_text_source,
            "provider_visible_context": PROVIDER_VISIBLE_CONTEXT,
            "raw_audio_included": False,
        },
    }
    return canonical


def normalize_turn_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    snapshot = validate_snapshot(
        payload.get(FIELD_NAME),
        read_mode_source_summaries=payload.get("read_mode_source_summaries"),
        read_mode_exact_text_attachments=payload.get("read_mode_exact_text_attachments"),
    )
    if snapshot is not None:
        normalized[FIELD_NAME] = snapshot
    return normalized


def current_message(payload: Mapping[str, Any], *, clean_text: Callable[..., str]) -> str:
    typed_message = clean_text(payload.get("message"), max_chars=4000)
    if typed_message:
        return typed_message
    snapshot = validate_snapshot(
        payload.get(FIELD_NAME),
        read_mode_source_summaries=payload.get("read_mode_source_summaries"),
        read_mode_exact_text_attachments=payload.get("read_mode_exact_text_attachments"),
    )
    if snapshot is None:
        return ""
    return snapshot["talk_projection"]["text"]


def build_provider_card(value: Any) -> dict[str, Any]:
    snapshot = validate_snapshot(value)
    if snapshot is None:
        return {
            "availability": {
                "status": "skipped",
                "source_kind": "current_audio_recognition",
                "source_id": "current_audio_recognition_card_v0",
                "freshness": "current_turn",
                "visible_to_model": False,
                "diagnostics_only": True,
                "reason": "No current audio recognition is attached for this turn.",
            },
            "provider_visible": False,
            "raw_access": False,
            "diagnostics": {"selected_count": 0, "raw_audio_included": False},
        }
    return {
        "availability": {
            "status": "available",
            "source_kind": "current_audio_recognition",
            "source_id": "current_audio_recognition_card_v0",
            "freshness": "current_turn",
            "visible_to_model": True,
            "diagnostics_only": False,
            "reason": "",
        },
        "provider_visible": True,
        "snapshot": snapshot,
        "raw_access": False,
        "memory_write_made": False,
        "source_write_made": False,
        "persistence_made": False,
        "diagnostics": {"selected_count": 1, "raw_audio_included": False},
    }


def render_provider_lines(card: Mapping[str, Any]) -> list[str]:
    snapshot = card.get("snapshot") if isinstance(card.get("snapshot"), Mapping) else {}
    recognition = (
        snapshot.get("audio_recognition")
        if isinstance(snapshot.get("audio_recognition"), Mapping)
        else {}
    )
    projection = snapshot.get("talk_projection") if isinstance(snapshot.get("talk_projection"), Mapping) else {}
    if not recognition or not projection:
        return []
    lines = [f"- {projection['provider_visible_context']}"]
    if recognition.get("transcript"):
        lines.append(f"- Recognized speech: {recognition['transcript']}")
    lines.append(f"- Meaning: {recognition['meaning']}")
    categories = (
        ("Audio events", "audio_events"),
        ("Voice", "voice_observations"),
        ("Emotion or intent", "emotion_intent_observations"),
        ("Background", "background_observations"),
        ("Uncertainties", "uncertainties"),
    )
    for label, key in categories:
        values = recognition.get(key) if isinstance(recognition.get(key), list) else []
        for item in values:
            lines.append(f"- {label}: {item}")
    return lines
