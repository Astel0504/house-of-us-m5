"""Canonical byte fixtures for the future V1.2 terminal private-tail parser.

This module records bytes and expected classifications only. It intentionally
does not implement, import, or invoke the runtime parser.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


KNOWN_CAPABILITY = "cwc_" + ("A" * 43)
UNKNOWN_CAPABILITY = "cwc_" + ("Z" * 43)
CONTINUITY_OPEN = "<house-continuity-intent>"
CONTINUITY_CLOSE = "</house-continuity-intent>"
MEMORY_OPEN = "<house-memory-intent>"
MEMORY_CLOSE = "</house-memory-intent>"
MAX_TERMINAL_WHITESPACE_BYTES = 8
MAX_CONTINUITY_CANDIDATE_BYTES = 12_000


def _intent(capability: str = KNOWN_CAPABILITY) -> str:
    return json.dumps(
        {
            "capability": capability,
            "schema_version": "house_talk_continuity_authorship_intent_v1",
            "protocol_version": "house_continuity_private_carrier_v1_2",
            "coverage_decision": "no_semantic_delta",
            "semantic_operations": [],
            "scope_binding_operation": None,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )


VALID_CONTINUITY = CONTINUITY_OPEN + _intent() + CONTINUITY_CLOSE
UNKNOWN_CONTINUITY = CONTINUITY_OPEN + _intent(UNKNOWN_CAPABILITY) + CONTINUITY_CLOSE
VALID_MEMORY = (
    MEMORY_OPEN
    + '{"action":"create","memory":"Synthetic candidate only."}'
    + MEMORY_CLOSE
)
INVALID_MEMORY = MEMORY_OPEN + '{"action":"create","memory":}' + MEMORY_CLOSE


def _ranges(response: str, needles: list[str]) -> list[dict[str, int | str]]:
    result = []
    cursor = 0
    encoded = response.encode("utf-8")
    for owner_and_needle in needles:
        owner, needle = owner_and_needle.split(":", 1)
        start_char = response.index(needle, cursor)
        end_char = start_char + len(needle)
        start = len(response[:start_char].encode("utf-8"))
        end = len(response[:end_char].encode("utf-8"))
        assert encoded[start:end] == needle.encode("utf-8")
        result.append({"owner": owner, "start": start, "end": end})
        cursor = end_char
    return result


def _fixture(
    *,
    response: str,
    visible: str,
    private_needles: list[str],
    continuity_state: str,
    memory_disposition: str,
    continuity_write_permitted: bool,
    memory_write_permitted: bool,
) -> dict[str, Any]:
    response_bytes = response.encode("utf-8")
    visible_bytes = visible.encode("utf-8")
    return {
        "response_utf8_hex": response_bytes.hex(),
        "response_utf8_sha256": hashlib.sha256(response_bytes).hexdigest(),
        "expected_visible_utf8_hex": visible_bytes.hex(),
        "expected_visible_utf8_sha256": hashlib.sha256(visible_bytes).hexdigest(),
        "expected_stripped_private_ranges": _ranges(response, private_needles),
        "continuity_state": continuity_state,
        "memory_disposition": memory_disposition,
        "continuity_write_permitted": continuity_write_permitted,
        "memory_write_permitted": memory_write_permitted,
        "any_write_permitted": (
            continuity_write_permitted or memory_write_permitted
        ),
    }


VISIBLE = "Visible response."
_VALID_CONTINUITY_RESPONSE = VISIBLE + "\n" + VALID_CONTINUITY
_MEMORY_RESPONSE = VISIBLE + "\n" + VALID_MEMORY
_BOTH_RESPONSE = VISIBLE + "\n" + VALID_CONTINUITY + "\n" + VALID_MEMORY

TERMINAL_PRIVATE_TAIL_FIXTURES = {
    "visible_only": _fixture(
        response=VISIBLE,
        visible=VISIBLE,
        private_needles=[],
        continuity_state="authorship_not_supplied",
        memory_disposition="not_supplied",
        continuity_write_permitted=False,
        memory_write_permitted=False,
    ),
    "continuity_only": _fixture(
        response=_VALID_CONTINUITY_RESPONSE,
        visible=VISIBLE + "\n",
        private_needles=["continuity:" + VALID_CONTINUITY],
        continuity_state="accepted_known_capability",
        memory_disposition="not_supplied",
        continuity_write_permitted=True,
        memory_write_permitted=False,
    ),
    "memory_only": _fixture(
        response=_MEMORY_RESPONSE,
        visible=VISIBLE + "\n",
        private_needles=["memory:" + VALID_MEMORY],
        continuity_state="authorship_not_supplied",
        memory_disposition="delegate_valid_candidate_to_existing_memory_owner",
        continuity_write_permitted=False,
        memory_write_permitted=True,
    ),
    "continuity_then_memory": _fixture(
        response=_BOTH_RESPONSE,
        visible=VISIBLE + "\n\n",
        private_needles=[
            "continuity:" + VALID_CONTINUITY,
            "memory:" + VALID_MEMORY,
        ],
        continuity_state="accepted_known_capability",
        memory_disposition="delegate_valid_candidate_to_existing_memory_owner",
        continuity_write_permitted=True,
        memory_write_permitted=True,
    ),
    "quoted_tag": _fixture(
        response='He wrote "' + VALID_CONTINUITY + '" as an example.',
        visible='He wrote "' + VALID_CONTINUITY + '" as an example.',
        private_needles=[],
        continuity_state="literal_visible",
        memory_disposition="not_supplied",
        continuity_write_permitted=False,
        memory_write_permitted=False,
    ),
    "inline_code": _fixture(
        response="Use `" + VALID_CONTINUITY + "` literally.",
        visible="Use `" + VALID_CONTINUITY + "` literally.",
        private_needles=[],
        continuity_state="literal_visible",
        memory_disposition="not_supplied",
        continuity_write_permitted=False,
        memory_write_permitted=False,
    ),
    "fenced_code": _fixture(
        response="```text\n" + VALID_CONTINUITY + "\n```",
        visible="```text\n" + VALID_CONTINUITY + "\n```",
        private_needles=[],
        continuity_state="literal_visible",
        memory_disposition="not_supplied",
        continuity_write_permitted=False,
        memory_write_permitted=False,
    ),
    "indented_code": _fixture(
        response="    " + VALID_CONTINUITY,
        visible="    " + VALID_CONTINUITY,
        private_needles=[],
        continuity_state="literal_visible",
        memory_disposition="not_supplied",
        continuity_write_permitted=False,
        memory_write_permitted=False,
    ),
    "blockquote": _fixture(
        response="> " + VALID_CONTINUITY,
        visible="> " + VALID_CONTINUITY,
        private_needles=[],
        continuity_state="literal_visible",
        memory_disposition="not_supplied",
        continuity_write_permitted=False,
        memory_write_permitted=False,
    ),
    "unknown_capability": _fixture(
        response=VISIBLE + "\n" + UNKNOWN_CONTINUITY,
        visible=VISIBLE + "\n" + UNKNOWN_CONTINUITY,
        private_needles=[],
        continuity_state="unknown_capability_literal_visible",
        memory_disposition="not_supplied",
        continuity_write_permitted=False,
        memory_write_permitted=False,
    ),
    "wrong_turn_capability": _fixture(
        response=_VALID_CONTINUITY_RESPONSE,
        visible=VISIBLE + "\n",
        private_needles=["continuity:" + VALID_CONTINUITY],
        continuity_state="rejected_wrong_turn_binding",
        memory_disposition="not_supplied",
        continuity_write_permitted=False,
        memory_write_permitted=False,
    ),
    "duplicate_continuity": _fixture(
        response=VISIBLE + "\n" + VALID_CONTINUITY + "\n" + VALID_CONTINUITY,
        visible=VISIBLE + "\n\n",
        private_needles=[
            "continuity:" + VALID_CONTINUITY,
            "continuity:" + VALID_CONTINUITY,
        ],
        continuity_state="rejected_duplicate_private_block",
        memory_disposition="not_supplied",
        continuity_write_permitted=False,
        memory_write_permitted=False,
    ),
    "out_of_order_memory_then_continuity": _fixture(
        response=VISIBLE + "\n" + VALID_MEMORY + "\n" + VALID_CONTINUITY,
        visible=VISIBLE + "\n\n",
        private_needles=[
            "memory:" + VALID_MEMORY,
            "continuity:" + VALID_CONTINUITY,
        ],
        continuity_state="rejected_out_of_order_private_block",
        memory_disposition="rejected_out_of_order_private_block",
        continuity_write_permitted=False,
        memory_write_permitted=False,
    ),
    "malformed_json": _fixture(
        response=VISIBLE
        + "\n"
        + CONTINUITY_OPEN
        + '{"capability":"'
        + KNOWN_CAPABILITY
        + '","schema_version":'
        + CONTINUITY_CLOSE,
        visible=VISIBLE + "\n",
        private_needles=[
            "continuity:"
            + CONTINUITY_OPEN
            + '{"capability":"'
            + KNOWN_CAPABILITY
            + '","schema_version":'
            + CONTINUITY_CLOSE
        ],
        continuity_state="rejected_malformed_known_capability",
        memory_disposition="not_supplied",
        continuity_write_permitted=False,
        memory_write_permitted=False,
    ),
    "oversized_candidate": _fixture(
        response=VISIBLE
        + "\n"
        + CONTINUITY_OPEN
        + '{"capability":"'
        + KNOWN_CAPABILITY
        + '","padding":"'
        + ("x" * MAX_CONTINUITY_CANDIDATE_BYTES)
        + '"}'
        + CONTINUITY_CLOSE,
        visible=VISIBLE + "\n",
        private_needles=[
            "continuity:"
            + CONTINUITY_OPEN
            + '{"capability":"'
            + KNOWN_CAPABILITY
            + '","padding":"'
            + ("x" * MAX_CONTINUITY_CANDIDATE_BYTES)
            + '"}'
            + CONTINUITY_CLOSE
        ],
        continuity_state="rejected_oversized_known_capability",
        memory_disposition="not_supplied",
        continuity_write_permitted=False,
        memory_write_permitted=False,
    ),
    "unterminated_known_capability_final_line": _fixture(
        response=VISIBLE
        + "\n"
        + CONTINUITY_OPEN
        + '{"capability":"'
        + KNOWN_CAPABILITY
        + '"',
        visible=VISIBLE + "\n",
        private_needles=[
            "continuity:"
            + CONTINUITY_OPEN
            + '{"capability":"'
            + KNOWN_CAPABILITY
            + '"'
        ],
        continuity_state="rejected_unterminated_known_capability",
        memory_disposition="not_supplied",
        continuity_write_permitted=False,
        memory_write_permitted=False,
    ),
    "terminal_whitespace_at_limit": _fixture(
        response=_VALID_CONTINUITY_RESPONSE + (" " * MAX_TERMINAL_WHITESPACE_BYTES),
        visible=VISIBLE + "\n",
        private_needles=[
            "continuity:"
            + VALID_CONTINUITY
            + (" " * MAX_TERMINAL_WHITESPACE_BYTES)
        ],
        continuity_state="accepted_known_capability",
        memory_disposition="not_supplied",
        continuity_write_permitted=True,
        memory_write_permitted=False,
    ),
    "terminal_whitespace_over_limit": _fixture(
        response=_VALID_CONTINUITY_RESPONSE
        + (" " * (MAX_TERMINAL_WHITESPACE_BYTES + 1)),
        visible=_VALID_CONTINUITY_RESPONSE
        + (" " * (MAX_TERMINAL_WHITESPACE_BYTES + 1)),
        private_needles=[],
        continuity_state="not_terminal_literal_visible",
        memory_disposition="not_supplied",
        continuity_write_permitted=False,
        memory_write_permitted=False,
    ),
    "valid_continuity_invalid_memory": _fixture(
        response=VISIBLE + "\n" + VALID_CONTINUITY + "\n" + INVALID_MEMORY,
        visible=VISIBLE + "\n\n",
        private_needles=[
            "continuity:" + VALID_CONTINUITY,
            "memory:" + INVALID_MEMORY,
        ],
        continuity_state="accepted_known_capability",
        memory_disposition="recognized_rejected_invalid_memory",
        continuity_write_permitted=True,
        memory_write_permitted=False,
    ),
    "invalid_continuity_valid_memory": _fixture(
        response=VISIBLE
        + "\n"
        + CONTINUITY_OPEN
        + '{"capability":"'
        + KNOWN_CAPABILITY
        + '"}'
        + CONTINUITY_CLOSE
        + "\n"
        + VALID_MEMORY,
        visible=VISIBLE + "\n\n",
        private_needles=[
            "continuity:"
            + CONTINUITY_OPEN
            + '{"capability":"'
            + KNOWN_CAPABILITY
            + '"}'
            + CONTINUITY_CLOSE,
            "memory:" + VALID_MEMORY,
        ],
        continuity_state="recognized_rejected_schema_invalid",
        memory_disposition="delegate_valid_candidate_to_existing_memory_owner",
        continuity_write_permitted=False,
        memory_write_permitted=True,
    ),
}

TERMINAL_FIXTURE_BUNDLE_SHA256 = hashlib.sha256(
    json.dumps(
        TERMINAL_PRIVATE_TAIL_FIXTURES,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
