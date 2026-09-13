from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import house_prompt_cache_production_v1 as production
import house_provider_chat_serialization_v0 as chat_serialization
import living_footing_packet_v0 as living_footing
import main_runtime_provider_adapter_v0 as runtime_adapter


def section(
    section_id: str,
    text: str,
    *,
    section_class: str = "standing_live_state",
    frequency: str = "per_turn",
    exactness: str = "derived",
) -> dict[str, str]:
    return {
        "section_id": section_id,
        "section_class": section_class,
        "exactness": exactness,
        "update_frequency": frequency,
        "rendered_text": text,
    }


def base_sections(
    *,
    current: str = "Current Astel message:\nSynthetic hello.",
    stable_profile: str = "Solen identity:\nSynthetic stable profile.",
    dynamic: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    return [
        section(
            "context_footing_law",
            "Context footing:\nSynthetic source labels remain descriptive.",
            section_class="standing_quiet_relationship_footing",
            frequency="immutable_versioned",
            exactness="exact",
        ),
        section(
            "solen_identity",
            stable_profile,
            section_class="standing_quiet_relationship_footing",
            frequency="slowly_changing",
        ),
        *(dynamic or []),
        section(
            "current_input",
            current,
            section_class="current_input",
            exactness="exact",
        ),
        section(
            "response_format_law",
            "Response instruction:\nStay natural and use readable short paragraphs.",
            section_class="response_format_law",
            frequency="immutable_versioned",
            exactness="exact",
        ),
    ]


def assemble(
    sections: list[dict[str, str]],
    *,
    envelope: dict | None = None,
    switch: str = "on",
    legacy: str = "legacy flattened text",
    model: str = "gpt-5.5",
):
    return production.assemble_production_prompt(
        legacy_user_text=legacy,
        section_outputs=sections,
        envelope=envelope or {},
        env={production.FEATURE_SWITCH_NAME: switch},
        model=model,
        route="openai_compatible_chat_completions",
        tools_requested=False,
    )


def projection_payloads(result) -> tuple[dict, dict | None, dict]:
    messages = result.chat_projection.messages
    developer = json.loads(messages[0].content.split("\n", 1)[1])
    stable = (
        json.loads(messages[1].content.split("\n", 1)[1])
        if len(messages) == 3
        else None
    )
    current = json.loads(messages[-1].content.split("\n", 1)[1])
    return developer, stable, current


class HousePromptCacheProductionV1Tests(unittest.TestCase):
    def test_new_session_uses_stable_prefix_without_recent_context(self):
        result = assemble(base_sections())

        self.assertTrue(result.stable_prefix_used)
        _developer, stable, current = projection_payloads(result)
        self.assertIn("Synthetic stable profile.", stable["context_data"][0])
        self.assertEqual([], current["dynamic_context"])
        self.assertIn("Synthetic hello.", current["current_input"])

    def test_openrouter_qualified_model_identifier_keeps_stable_prefix(self):
        baseline = assemble(base_sections(), model="gpt-5.5")
        result = assemble(base_sections(), model="openai/gpt-5.5")

        self.assertTrue(result.stable_prefix_used)
        self.assertEqual(
            "openaigpt-5.5",
            result.request_observability["model"],
        )
        self.assertEqual(
            baseline.request_observability["prefix_sha256"],
            result.request_observability["prefix_sha256"],
        )

    def test_openrouter_qualified_model_requests_extended_retention(self):
        result = assemble(base_sections(), model="openai/gpt-5.5")

        self.assertEqual(
            "requested_extended_24h",
            result.request_observability["retention_policy_state"],
        )
        self.assertEqual(
            "24h",
            result.request_observability["retention_requested_value"],
        )

    def test_continuing_session_keeps_complete_recent_exchange(self):
        recent = (
            "Recent visible exchange:\n"
            "Astel: complete first turn.\n"
            "Solen: complete first reply."
        )
        result = assemble(
            base_sections(
                dynamic=[
                    section(
                        "recent_visible_exchange",
                        recent,
                        section_class="recent_exact_current_session",
                        frequency="append_only",
                        exactness="exact",
                    )
                ]
            )
        )

        _developer, _stable, current = projection_payloads(result)
        self.assertIn(recent, current["dynamic_context"])
        self.assertNotIn("partial", current["dynamic_context"][0])

    def test_same_stable_prefix_with_changed_current_message(self):
        first = assemble(base_sections(current="Current Astel message:\nFirst tail."))
        second = assemble(base_sections(current="Current Astel message:\nSecond tail."))

        self.assertEqual(
            first.request_observability["prefix_sha256"],
            second.request_observability["prefix_sha256"],
        )
        self.assertNotEqual(
            first.chat_projection.messages[-1].content,
            second.chat_projection.messages[-1].content,
        )

    def test_memory_recall_present_or_absent_does_not_change_prefix(self):
        absent = assemble(base_sections())
        present = assemble(
            base_sections(
                dynamic=[
                    section(
                        "vault_recall",
                        "Vault recall:\nSynthetic source-backed memory.",
                        section_class="vault_memory_recall",
                    )
                ]
            )
        )

        self.assertEqual(
            absent.request_observability["prefix_sha256"],
            present.request_observability["prefix_sha256"],
        )
        self.assertNotEqual(
            absent.request_observability["semantic_section_sha256"],
            present.request_observability["semantic_section_sha256"],
        )

    def test_source_file_image_and_helper_context_remain_dynamic(self):
        values = [
            section(
                "read_mode_source_context",
                "Source context:\nSynthetic file summary.",
                section_class="timeline_source_attachment",
            ),
            section(
                "read_mode_exact_text",
                "Exact text:\nSynthetic image description.",
                section_class="timeline_source_attachment",
                exactness="exact",
            ),
            section(
                "turn_context",
                "Turn context:\nSynthetic helper output.",
                section_class="timeline_source_attachment",
            ),
        ]
        result = assemble(base_sections(dynamic=values))

        _developer, _stable, current = projection_payloads(result)
        rendered = "\n".join(current["dynamic_context"])
        self.assertIn("Synthetic file summary.", rendered)
        self.assertIn("Synthetic image description.", rendered)
        self.assertIn("Synthetic helper output.", rendered)

    def test_dynamic_order_is_memory_then_older_then_recent_then_attachments(self):
        result = assemble(
            base_sections(
                dynamic=[
                    section("read_mode_source_context", "source"),
                    section("recent_visible_exchange", "recent"),
                    section("read_mode_exact_text", "attachment"),
                    section("thread_summary", "older"),
                    section("vault_recall", "memory"),
                ]
            )
        )

        _developer, _stable, current = projection_payloads(result)
        self.assertEqual(
            ["memory", "older", "recent", "source", "attachment"],
            current["dynamic_context"],
        )

    def test_long_recent_thread_is_not_clipped_by_production_owner(self):
        long_recent = "Recent visible exchange:\n" + ("complete pair text " * 900)
        result = assemble(
            base_sections(
                dynamic=[
                    section(
                        "recent_visible_exchange",
                        long_recent,
                        frequency="append_only",
                    )
                ]
            )
        )

        _developer, _stable, current = projection_payloads(result)
        self.assertEqual(long_recent, current["dynamic_context"][0])

    def test_living_footing_profile_splits_losslessly_from_dynamic_room(self):
        packet = {
            "room_surface": "a synthetic House",
            "profile_footing_items": [
                {
                    "text": "Synthetic standing profile.",
                    "source_class": "profile_footing",
                    "render_mode": "detail",
                }
            ],
            "core_memory_footing_items": [],
            "active_situation_memory_items": [],
            "current_room_footing": [
                {
                    "text": "Synthetic current room state.",
                    "source_class": "current_room_state",
                    "render_mode": "detail",
                }
            ],
            "recent_pattern_footing": [],
            "active_task": {},
            "active_recall_target": {},
        }
        rendered = living_footing.render_living_footing_provider_section(packet)
        result = assemble(
            base_sections(
                stable_profile="Solen identity:\nAdditional stable profile.",
                dynamic=[section("living_footing", rendered)],
            ),
            envelope={"living_footing": {"packet": packet}},
        )

        _developer, stable, current = projection_payloads(result)
        self.assertIn("Synthetic standing profile.", "\n".join(stable["context_data"]))
        self.assertIn(
            "Synthetic current room state.",
            "\n".join(current["dynamic_context"]),
        )
        self.assertEqual(
            "lossless_selected_section_partition",
            result.request_observability["semantic_equivalence"],
        )

    def test_living_footing_split_preserves_selected_renderer_cap(self):
        packet = {
            "room_surface": "a synthetic House",
            "profile_footing_items": [
                {
                    "text": "Synthetic standing profile.",
                    "source_class": "profile_footing",
                    "render_mode": "detail",
                }
            ],
            "core_memory_footing_items": [],
            "active_situation_memory_items": [],
            "current_room_footing": [
                {
                    "text": f"Synthetic current room line {index} " + ("detail " * 24),
                    "source_class": "current_room_state",
                    "render_mode": "detail",
                }
                for index in range(16)
            ],
            "recent_pattern_footing": [],
            "active_task": {},
            "active_recall_target": {},
        }
        rendered = living_footing.render_living_footing_provider_section(
            packet,
            max_chars=1600,
        )
        self.assertLessEqual(len(rendered), 1600)
        self.assertTrue(rendered.endswith("detail..."))

        result = assemble(
            base_sections(dynamic=[section("living_footing", rendered)]),
            envelope={"living_footing": {"packet": packet}},
        )

        self.assertTrue(result.stable_prefix_used)
        _developer, stable, current = projection_payloads(result)
        self.assertIn(
            "Synthetic standing profile.",
            "\n".join(stable["context_data"]),
        )
        projected_living = [
            *stable["context_data"],
            *current["dynamic_context"],
        ]
        stable_living = next(
            item for item in projected_living if "Synthetic standing profile." in item
        )
        dynamic_living = next(
            item for item in projected_living if "Synthetic current room line" in item
        )
        self.assertEqual(
            rendered,
            production._merge_living_renders(stable_living, dynamic_living),
        )

    def test_dynamic_item_before_profile_keeps_living_section_exact_and_dynamic(self):
        packet = {
            "room_surface": "a synthetic House",
            "profile_footing_items": [
                {
                    "text": "Synthetic per-turn reality state.",
                    "source_class": "reality_context",
                    "render_mode": "detail",
                },
                {
                    "text": "Synthetic standing profile.",
                    "source_class": "profile_footing",
                    "render_mode": "detail",
                },
            ],
            "core_memory_footing_items": [],
            "active_situation_memory_items": [],
            "current_room_footing": [],
            "recent_pattern_footing": [],
            "active_task": {},
            "active_recall_target": {},
        }
        rendered = living_footing.render_living_footing_provider_section(packet)

        result = assemble(
            base_sections(dynamic=[section("living_footing", rendered)]),
            envelope={"living_footing": {"packet": packet}},
        )

        self.assertTrue(result.stable_prefix_used)
        _developer, stable, current = projection_payloads(result)
        self.assertNotIn(
            "Synthetic standing profile.",
            "\n".join(stable["context_data"]),
        )
        self.assertIn(rendered, current["dynamic_context"])
        self.assertEqual(
            0,
            result.request_observability["local_assembly_fallback_count"],
        )
        self.assertEqual(
            "lossless_selected_section_partition",
            result.request_observability["semantic_equivalence"],
        )

    def test_stable_prefix_bytes_remain_identical_when_dynamic_tail_changes(self):
        first = assemble(
            base_sections(dynamic=[section("vault_recall", "memory A")])
        )
        second = assemble(
            base_sections(dynamic=[section("vault_recall", "memory B")])
        )

        first_stable = [
            (message.role, message.content)
            for message in first.chat_projection.messages[:-1]
        ]
        second_stable = [
            (message.role, message.content)
            for message in second.chat_projection.messages[:-1]
        ]
        self.assertEqual(first_stable, second_stable)
        self.assertEqual(
            first.request_observability["prefix_version"],
            second.request_observability["prefix_version"],
        )

    def test_stable_card_change_invalidates_prefix_version(self):
        first = assemble(base_sections(stable_profile="Solen identity:\nProfile A."))
        second = assemble(base_sections(stable_profile="Solen identity:\nProfile B."))

        self.assertNotEqual(
            first.request_observability["prefix_version"],
            second.request_observability["prefix_version"],
        )
        self.assertNotEqual(
            first.request_observability["prefix_sha256"],
            second.request_observability["prefix_sha256"],
        )

    def test_voice_and_context_sections_are_each_projected_once(self):
        sections = base_sections(
            dynamic=[
                section("vault_recall", "Synthetic memory fact."),
                section("thread_summary", "Synthetic older context."),
                section("recent_visible_exchange", "Synthetic recent turns."),
            ]
        )
        result = assemble(sections)

        developer, stable, current = projection_payloads(result)
        projected_sections = [
            *developer["instruction_law"],
            *(stable["context_data"] if stable else []),
            *current["dynamic_context"],
            current["current_input"],
        ]
        for value in sections:
            self.assertEqual(
                1,
                projected_sections.count(value["rendered_text"]),
                value["section_id"],
            )

    def test_assembly_failure_falls_back_without_losing_legacy_turn(self):
        with patch.object(
            chat_serialization,
            "build_no_live_chat_projection",
            side_effect=ValueError("synthetic local failure"),
        ):
            result = assemble(base_sections(), legacy="exact legacy turn")

        self.assertFalse(result.stable_prefix_used)
        self.assertEqual("exact legacy turn", result.legacy_user_text)
        self.assertEqual(
            "local_assembly_failed",
            result.request_observability["local_assembly_fallback_state"],
        )
        self.assertEqual(
            1,
            result.request_observability["local_assembly_fallback_count"],
        )

    def test_feature_switch_off_reproduces_previous_legacy_text(self):
        result = assemble(
            base_sections(),
            switch="off",
            legacy="byte-identical legacy text",
        )

        self.assertFalse(result.stable_prefix_used)
        self.assertEqual("byte-identical legacy text", result.legacy_user_text)
        self.assertEqual("legacy", result.request_observability["effective_mode"])
        self.assertEqual(
            "switch_off",
            result.request_observability["local_assembly_fallback_state"],
        )

    def test_local_default_is_on_and_explicit_off_remains_available(self):
        self.assertEqual(
            ("default_on", True),
            production.configured_feature_mode({}),
        )
        self.assertEqual(
            ("explicit_off", False),
            production.configured_feature_mode(
                {production.FEATURE_SWITCH_NAME: "off"}
            ),
        )

    def test_stable_prefix_requests_extended_retention_by_default(self):
        result = assemble(base_sections())
        observation = result.request_observability

        self.assertEqual("default_on", observation["retention_configured_mode"])
        self.assertEqual(
            "requested_extended_24h",
            observation["retention_policy_state"],
        )
        self.assertEqual(
            "prompt_cache_retention",
            observation["retention_request_field"],
        )
        self.assertEqual("24h", observation["retention_requested_value"])

    def test_retention_switch_off_preserves_stable_prefix_assembly(self):
        result = production.assemble_production_prompt(
            legacy_user_text="legacy",
            section_outputs=base_sections(),
            envelope={},
            env={
                production.FEATURE_SWITCH_NAME: "on",
                "HOUSE_PROMPT_CACHE_RETENTION_POLICY": "off",
            },
            model="gpt-5.5",
            route="openai_compatible_chat_completions",
            tools_requested=False,
        )

        self.assertTrue(result.stable_prefix_used)
        self.assertEqual(
            "explicit_off",
            result.request_observability["retention_configured_mode"],
        )
        self.assertEqual(
            "switch_off",
            result.request_observability["retention_policy_state"],
        )
        self.assertEqual(
            "",
            result.request_observability["retention_request_field"],
        )

    def test_feature_switch_on_uses_attested_projection(self):
        result = assemble(base_sections())

        body = chat_serialization.endpoint_request_from_chat_projection(
            result.chat_projection
        )
        self.assertEqual(["model", "messages", "stream"], list(body))
        self.assertEqual("gpt-5.5", body["model"])
        self.assertFalse(body["stream"])

    def test_tools_request_uses_attested_projection(self):
        result = production.assemble_production_prompt(
            legacy_user_text="legacy",
            section_outputs=base_sections(),
            envelope={},
            env={production.FEATURE_SWITCH_NAME: "on"},
            model="gpt-5.5",
            route="openai_compatible_chat_completions",
            tools_requested=True,
        )

        self.assertTrue(result.stable_prefix_used)
        self.assertEqual("legacy", result.legacy_user_text)
        self.assertEqual("stable_prefix", result.request_observability["effective_mode"])
        self.assertEqual(
            "none",
            result.request_observability["local_assembly_fallback_state"],
        )

    def test_cache_usage_positive_zero_and_unavailable_never_fail(self):
        assembly = assemble(base_sections())
        cases = (
            (
                {
                    "prompt_tokens": 100,
                    "completion_tokens": 12,
                    "total_tokens": 112,
                    "prompt_tokens_details": {"cached_tokens": 80},
                },
                "reported_positive",
                80,
            ),
            (
                {
                    "prompt_tokens": 100,
                    "completion_tokens": 12,
                    "total_tokens": 112,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
                "reported_zero",
                0,
            ),
            (
                {
                    "prompt_tokens": 100,
                    "completion_tokens": 12,
                    "total_tokens": 112,
                },
                "unavailable",
                None,
            ),
        )
        for usage, expected_state, expected_cached in cases:
            with self.subTest(expected_state):
                observation = production.finalize_adapter_observability(
                    assembly,
                    {
                        "ok": True,
                        "provider": {"model": "gpt-5.5"},
                        "usage": usage,
                    },
                )
                self.assertEqual(expected_state, observation["cache_state"])
                self.assertEqual(
                    expected_cached,
                    observation["cached_input_tokens"],
                )
                self.assertEqual("success", observation["request_outcome"])

    def test_raw_private_text_never_enters_observability(self):
        sentinel = "PRIVATE_BODY_SENTINEL_8f14e45f"
        result = assemble(
            base_sections(
                dynamic=[section("vault_recall", f"Vault recall:\n{sentinel}")]
            ),
            legacy=f"legacy {sentinel}",
        )
        observation = production.finalize_adapter_observability(
            result,
            {
                "ok": True,
                "provider": {"model": "gpt-5.5"},
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
            },
        )

        self.assertNotIn(sentinel, json.dumps(observation, sort_keys=True))
        self.assertEqual(
            set(production._OBSERVABILITY_FIELDS),
            set(observation),
        )

    def test_provider_agent_cache_surface_replaces_pre_wrapper_only_state(self):
        assembly = assemble(base_sections())
        observation = production.finalize_adapter_observability(
            assembly,
            {
                "ok": True,
                "provider": {"model": "gpt-5.5"},
                "usage": {
                    "prompt_tokens": 1200,
                    "completion_tokens": 20,
                    "total_tokens": 1220,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
                "provider_agent": {
                    "prompt_cache_request_observability": {
                        "schema_version": (
                            "house_provider_agent_"
                            "prompt_cache_request_observability_v1"
                        ),
                        "provider_prefix_identity_state": (
                            "provider_agent_initial_surface"
                        ),
                        "provider_prefix_sha256": "a" * 64,
                        "provider_prefix_utf8_bytes": 5518,
                        "provider_stable_message_count": 3,
                        "provider_tool_definition_count": 6,
                        "provider_retention_field": (
                            "prompt_cache_retention"
                        ),
                        "provider_retention_value": "24h",
                        "provider_prompt_cache_key_present": False,
                        "raw_provider_content_present": False,
                    }
                },
            },
        )

        self.assertEqual(
            "provider_agent_initial_surface",
            observation["provider_prefix_identity_state"],
        )
        self.assertEqual("a" * 64, observation["provider_prefix_sha256"])
        self.assertEqual(5518, observation["provider_prefix_utf8_bytes"])
        self.assertEqual(3, observation["provider_stable_message_count"])
        self.assertEqual(6, observation["provider_tool_definition_count"])
        self.assertEqual(
            "prompt_cache_retention",
            observation["provider_retention_field"],
        )
        self.assertEqual("24h", observation["provider_retention_value"])
        self.assertFalse(
            observation["provider_prompt_cache_key_present"]
        )


class MainRuntimePromptCacheProjectionTests(unittest.TestCase):
    def test_adapter_uses_attested_projection_with_existing_request_fields(self):
        assembly = assemble(base_sections())
        request = runtime_adapter.build_runtime_request(
            request_id="synthetic-cache-request",
            session_id="synthetic-cache-session",
            user_text="legacy fallback text",
            response_mode={
                "streaming": False,
                "structured": False,
                "max_output_tokens": None,
            },
            chat_projection=assembly.chat_projection,
        )
        config = runtime_adapter.load_main_model_config(
            {
                "MAIN_MODEL_PROVIDER": "openai_compatible",
                "MAIN_MODEL_NAME": "gpt-5.5",
                "MAIN_MODEL_API_KEY": "synthetic-key",
                "MAIN_MODEL_BASE_URL": "https://synthetic.invalid",
                "MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT": "chat_completions",
                "MAIN_MODEL_OPENAI_COMPATIBLE_TRANSPORT": "live_http",
                "HOUSE_ALLOW_MAIN_RUNTIME_LIVE_HTTP": "1",
            }
        )

        body = runtime_adapter.build_openai_compatible_chat_completions_http_body(
            request,
            config,
            {},
        )
        expected = chat_serialization.endpoint_request_from_chat_projection(
            assembly.chat_projection
        )
        self.assertEqual(expected, body)
        self.assertEqual({"model", "messages", "stream"}, set(body))

    def test_effective_stable_projection_adds_reversible_cache_controls(self):
        assembly = assemble(base_sections())
        request = runtime_adapter.build_runtime_request(
            request_id="synthetic-cache-request",
            session_id="synthetic-cache-session",
            user_text="legacy fallback text",
            metadata={"prompt_cache": dict(assembly.request_observability)},
            chat_projection=assembly.chat_projection,
        )
        config = runtime_adapter.load_main_model_config(
            {
                "MAIN_MODEL_PROVIDER": "openai_compatible",
                "MAIN_MODEL_NAME": "gpt-5.5",
                "MAIN_MODEL_API_KEY": "synthetic-key",
                "MAIN_MODEL_BASE_URL": "https://synthetic.invalid",
                "MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT": "chat_completions",
                "MAIN_MODEL_OPENAI_COMPATIBLE_TRANSPORT": "live_http",
                "HOUSE_ALLOW_MAIN_RUNTIME_LIVE_HTTP": "1",
            }
        )

        body = runtime_adapter.build_openai_compatible_chat_completions_http_body(
            request,
            config,
            {},
        )

        self.assertEqual("24h", body["prompt_cache_retention"])
        self.assertEqual(
            "house-pc-v1-" + assembly.request_observability[
                "prefix_sha256"
            ][:40],
            body["prompt_cache_key"],
        )

    def test_adapter_preflight_projection_mismatch_calls_transport_zero_times(self):
        assembly = assemble(base_sections())
        request = runtime_adapter.build_runtime_request(
            request_id="synthetic-cache-request",
            session_id="synthetic-cache-session",
            user_text="legacy fallback text",
            chat_projection=assembly.chat_projection,
        )
        calls = []

        def transport(*args):
            calls.append(args)
            raise AssertionError("transport must not run")

        response = runtime_adapter.call_main_runtime(
            request,
            env={
                "MAIN_MODEL_PROVIDER": "openai_compatible",
                "MAIN_MODEL_NAME": "different-model",
                "MAIN_MODEL_API_KEY": "synthetic-key",
                "MAIN_MODEL_BASE_URL": "https://synthetic.invalid",
                "MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT": "chat_completions",
                "MAIN_MODEL_OPENAI_COMPATIBLE_TRANSPORT": "live_http",
                "HOUSE_ALLOW_MAIN_RUNTIME_LIVE_HTTP": "1",
            },
            safe_logs=[],
            http_transport=transport,
        )

        self.assertFalse(response["ok"])
        self.assertEqual([], calls)
        self.assertIn(
            "chat_projection_model_mismatch",
            [error["error_class"] for error in response["errors"]],
        )

    def test_switch_off_body_matches_previous_single_user_message(self):
        request = runtime_adapter.build_runtime_request(
            request_id="synthetic-cache-request",
            session_id="synthetic-cache-session",
            user_text="exact legacy flattened text",
        )
        config = runtime_adapter.load_main_model_config(
            {
                "MAIN_MODEL_PROVIDER": "openai_compatible",
                "MAIN_MODEL_NAME": "gpt-5.5",
                "MAIN_MODEL_API_KEY": "synthetic-key",
                "MAIN_MODEL_BASE_URL": "https://synthetic.invalid",
                "MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT": "chat_completions",
                "MAIN_MODEL_OPENAI_COMPATIBLE_TRANSPORT": "live_http",
                "HOUSE_ALLOW_MAIN_RUNTIME_LIVE_HTTP": "1",
            }
        )

        body = runtime_adapter.build_openai_compatible_chat_completions_http_body(
            request,
            config,
            {},
        )
        self.assertEqual(
            {
                "model": "gpt-5.5",
                "messages": [
                    {"role": "user", "content": "exact legacy flattened text"}
                ],
                "stream": False,
            },
            body,
        )
        self.assertNotIn("chat_projection", request)


if __name__ == "__main__":
    unittest.main()
