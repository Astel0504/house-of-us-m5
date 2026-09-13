import json
import unittest

import main_runtime_provider_adapter_v0 as adapter
import house_prompt_cache_production_v1 as prompt_cache_production


def base_request(**overrides):
    request = adapter.build_runtime_request(
        request_id="gw_test_001",
        session_id="session_test",
        user_text="Please answer through the fake adapter.",
        context_packet=overrides.pop("context_packet", None),
    )
    request.update(overrides)
    return request


def fake_env(**overrides):
    env = {
        "MAIN_MODEL_PROVIDER": "fake",
        "MAIN_MODEL_NAME": "fake-solen-runtime-v0",
        "MAIN_MODEL_FAKE_MODE": "success",
        "MAIN_MODEL_SUPPORTS_STREAMING": "false",
        "MAIN_MODEL_SUPPORTS_TOOLS": "false",
        "MAIN_MODEL_SUPPORTS_STRUCTURED_OUTPUT": "true",
    }
    env.update(overrides)
    return env


def mock_provider_env(**overrides):
    env = {
        "MAIN_MODEL_PROVIDER": "mock_provider",
        "MAIN_MODEL_NAME": "mock-provider-model-v0",
        "MAIN_MODEL_API_KEY": "TEST_ONLY_API_KEY",
        "MAIN_MODEL_MOCK_PROVIDER_MODE": "success",
        "MAIN_MODEL_SUPPORTS_STREAMING": "false",
        "MAIN_MODEL_SUPPORTS_TOOLS": "false",
        "MAIN_MODEL_SUPPORTS_STRUCTURED_OUTPUT": "true",
    }
    env.update(overrides)
    return env


def openai_compatible_env(**overrides):
    env = {
        "MAIN_MODEL_PROVIDER": "openai_compatible",
        "MAIN_MODEL_NAME": "gpt-5.1",
        "MAIN_MODEL_BASE_URL": "https://fixture.invalid/v1",
        "MAIN_MODEL_API_KEY": "TEST_ONLY_OPENAI_COMPATIBLE_API_KEY",
        "MAIN_MODEL_OPENAI_COMPATIBLE_MOCK_MODE": "success",
        "MAIN_MODEL_SUPPORTS_STREAMING": "false",
        "MAIN_MODEL_SUPPORTS_TOOLS": "false",
        "MAIN_MODEL_SUPPORTS_STRUCTURED_OUTPUT": "true",
    }
    env.update(overrides)
    return env


def openai_compatible_live_env(**overrides):
    env = openai_compatible_env(
        MAIN_MODEL_OPENAI_COMPATIBLE_TRANSPORT="live_http",
        MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="responses",
        HOUSE_ALLOW_MAIN_RUNTIME_LIVE_HTTP="true",
        MAIN_MODEL_TIMEOUT_SECONDS="5",
    )
    env.update(overrides)
    return env


def anthropic_compatible_live_env(**overrides):
    env = {
        "MAIN_MODEL_PROVIDER": "anthropic_compatible",
        "MAIN_MODEL_NAME": "claude-sonnet-4-6",
        "MAIN_MODEL_BASE_URL": "https://fixture.invalid/v1",
        "MAIN_MODEL_API_KEY": "TEST_ONLY_ANTHROPIC_COMPATIBLE_API_KEY",
        "HOUSE_ALLOW_MAIN_RUNTIME_LIVE_HTTP": "true",
        "MAIN_MODEL_TIMEOUT_SECONDS": "5",
        "MAIN_MODEL_SUPPORTS_STREAMING": "false",
        "MAIN_MODEL_SUPPORTS_TOOLS": "false",
        "MAIN_MODEL_SUPPORTS_STRUCTURED_OUTPUT": "true",
    }
    env.update(overrides)
    return env


class MainRuntimeProviderAdapterTests(unittest.TestCase):
    def test_fake_provider_success(self):
        logs = []
        response = adapter.call_main_runtime(base_request(), env=fake_env(), safe_logs=logs)
        self.assertTrue(response["ok"])
        self.assertEqual(adapter.RESPONSE_SCHEMA_VERSION, response["schema_version"])
        self.assertEqual("fake", response["provider"]["provider"])
        self.assertIn("fake runtime", response["assistant_text"])
        self.assertEqual("none", response["policy_action"])
        self.assertEqual([], response["tool_requests"])
        self.assertEqual(1, len(logs))
        self.assertNotIn("Please answer", str(logs))

    def test_fake_provider_accepts_compact_context_packet(self):
        packet = {
            "schema_version": "context_packet_v0",
            "records": [{"record_id": "mem_1", "title": "Tiny synthetic record"}],
            "source_notes": [{"source": "synthetic"}],
            "policy_action": "none",
        }
        logs = []
        response = adapter.call_main_runtime(
            base_request(context_packet=packet),
            env=fake_env(),
            safe_logs=logs,
        )
        self.assertTrue(response["ok"])
        self.assertIn("Context packet present: yes", response["assistant_text"])
        self.assertIn("Context record count: 1", response["assistant_text"])
        self.assertEqual(1, logs[0]["context_record_count"])
        self.assertNotIn("Tiny synthetic record", str(logs))

    def test_fake_context_aware_mode_without_context(self):
        logs = []
        response = adapter.call_main_runtime(
            base_request(),
            env=fake_env(MAIN_MODEL_FAKE_MODE="context_aware_success"),
            safe_logs=logs,
        )

        self.assertTrue(response["ok"])
        self.assertIn("[fake runtime / context-aware]", response["assistant_text"])
        self.assertIn("No context packet was attached", response["assistant_text"])
        self.assertIn("metadata-only test response", response["assistant_text"])
        self.assertNotIn("Please answer", response["assistant_text"])
        self.assertFalse(logs[0]["context_present"])

    def test_fake_context_aware_mode_with_context_uses_metadata_only(self):
        packet = {
            "schema_version": "context_packet_v0",
            "records": [
                {
                    "record_id": "doc_1",
                    "source_type": "project_doc",
                    "source_name": "HOUSE_CURRENT_STATE_QUICK_REVIEW_2026-05-07.md",
                    "quote": "RAW_DOC_SNIPPET_DO_NOT_RENDER",
                },
                {
                    "record_id": "chat_1",
                    "source_type": "chat",
                    "source_name": "Synthetic restricted title should not render",
                    "quote": "RAW_CHAT_SNIPPET_DO_NOT_RENDER",
                },
            ],
            "conversation_recall": [
                {
                    "quote": "RAW_DOC_SNIPPET_DO_NOT_RENDER",
                    "evidence_ref": {"source_pointer": "project_doc://safe"},
                }
            ],
            "source_notes": ["source note text should not render"],
            "confidence_notes": ["confidence note text should not render"],
            "safety_notes": ["safety note text should not render"],
            "policy_action": "none",
        }
        request = base_request(context_packet=packet)
        request["metadata"]["recall_source_route"] = "current_state_docs"
        logs = []
        response = adapter.call_main_runtime(
            request,
            env=fake_env(MAIN_MODEL_FAKE_MODE="context_aware_success"),
            safe_logs=logs,
        )

        self.assertTrue(response["ok"])
        text = response["assistant_text"]
        self.assertIn("[fake runtime / context-aware]", text)
        self.assertIn("Context packet present: yes", text)
        self.assertIn("Records: 2", text)
        self.assertIn("Evidence refs: 1", text)
        self.assertIn("Source notes: 1", text)
        self.assertIn("Confidence notes: 1", text)
        self.assertNotIn("Safety notes:", text)
        self.assertIn("Source route: current_state_docs", text)
        self.assertIn("HOUSE_CURRENT_STATE_QUICK_REVIEW_2026-05-07.md", text)
        for forbidden in [
            "RAW_DOC_SNIPPET_DO_NOT_RENDER",
            "RAW_CHAT_SNIPPET_DO_NOT_RENDER",
            "Synthetic restricted title should not render",
            "source note text should not render",
            "confidence note text should not render",
            "safety note text should not render",
            "Please answer",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)
                self.assertNotIn(forbidden, str(logs))
        self.assertEqual(2, logs[0]["context_record_count"])
        self.assertEqual(1, logs[0]["context_evidence_ref_count"])
        self.assertEqual(1, logs[0]["context_safety_note_count"])

    def test_fake_context_aware_mode_ignores_retired_style_metadata(self):
        request = base_request()
        request["metadata"]["runtime_profile_packet_metadata"] = {
            "profile_packet_present": True,
            "schema_version": "runtime_profile_packet_v0",
            "active_setting_counts": {"astel": 0, "solen": 3, "house": 0},
            "active_solen_style_count": 9,
            "warning_count": 0,
            "policy_action": "none",
            "raw_solen_core_seed_text": "RAW_SOLEN_SEED_DO_NOT_RENDER",
            "full_profile_json": {"unsafe": "RAW_PROFILE_JSON_DO_NOT_RENDER"},
        }
        logs = []

        response = adapter.call_main_runtime(
            request,
            env=fake_env(MAIN_MODEL_FAKE_MODE="context_aware_success"),
            safe_logs=logs,
        )

        self.assertTrue(response["ok"])
        text = response["assistant_text"]
        self.assertIn("Profile packet present: yes", text)
        self.assertNotIn("style control", text.casefold())
        self.assertNotIn("Profile warnings:", text)
        self.assertIn("Profile policy action: none", text)
        self.assertNotIn("RAW_SOLEN_SEED_DO_NOT_RENDER", text)
        self.assertNotIn("RAW_PROFILE_JSON_DO_NOT_RENDER", text)
        self.assertNotIn("RAW_SOLEN_SEED_DO_NOT_RENDER", str(logs))
        self.assertNotIn("RAW_PROFILE_JSON_DO_NOT_RENDER", str(logs))
        self.assertTrue(logs[0]["profile_packet_present"])
        self.assertNotIn("active_solen_style_count", logs[0])
        self.assertEqual(0, logs[0]["profile_warning_count"])

    def test_fake_timeout_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=fake_env(MAIN_MODEL_FAKE_MODE="timeout"),
        )
        self.assertFalse(response["ok"])
        self.assertEqual("", response["assistant_text"])
        self.assertEqual("timeout", response["errors"][0]["error_class"])
        self.assertTrue(response["errors"][0]["retryable"])

    def test_fake_malformed_response_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=fake_env(MAIN_MODEL_FAKE_MODE="malformed_response"),
        )
        self.assertFalse(response["ok"])
        self.assertEqual("malformed_provider_response", response["errors"][0]["error_class"])
        self.assertEqual("", response["assistant_text"])

    def test_fake_provider_error_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=fake_env(MAIN_MODEL_FAKE_MODE="provider_error"),
        )
        self.assertFalse(response["ok"])
        self.assertEqual("provider_error", response["errors"][0]["error_class"])
        self.assertEqual("", response["assistant_text"])

    def test_mock_provider_success_normalizes_response_and_usage(self):
        logs = []
        response = adapter.call_main_runtime(
            base_request(),
            env=mock_provider_env(),
            safe_logs=logs,
        )

        self.assertTrue(response["ok"])
        self.assertEqual(adapter.RESPONSE_SCHEMA_VERSION, response["schema_version"])
        self.assertEqual("mock_provider", response["provider"]["provider"])
        self.assertEqual("mock-provider-model-v0", response["provider"]["model"])
        self.assertEqual("[mock provider] Provider-neutral mocked response reached the adapter.", response["assistant_text"])
        self.assertEqual("stop", response["finish_reason"])
        self.assertEqual(11, response["usage"]["input_tokens"])
        self.assertEqual(9, response["usage"]["output_tokens"])
        self.assertEqual(20, response["usage"]["total_tokens"])
        self.assertEqual(0, response["usage"]["estimated_cost"])
        self.assertEqual("USD", response["usage"]["currency"])
        self.assertEqual([], response["tool_requests"])
        self.assertEqual("none", response["policy_action"])
        self.assertEqual(1, len(logs))
        self.assertEqual("mock_provider", logs[0]["provider"])
        self.assertEqual(20, logs[0]["total_tokens"])
        self.assertNotIn("Please answer", str(logs))
        self.assertNotIn("TEST_ONLY_API_KEY", str(logs))

    def test_mock_provider_timeout_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=mock_provider_env(MAIN_MODEL_MOCK_PROVIDER_MODE="timeout"),
        )

        self.assertFalse(response["ok"])
        self.assertEqual("", response["assistant_text"])
        self.assertEqual("timeout", response["errors"][0]["error_class"])
        self.assertTrue(response["errors"][0]["retryable"])

    def test_mock_provider_malformed_response_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=mock_provider_env(MAIN_MODEL_MOCK_PROVIDER_MODE="malformed_response"),
        )

        self.assertFalse(response["ok"])
        self.assertEqual("", response["assistant_text"])
        self.assertEqual("malformed_provider_response", response["errors"][0]["error_class"])

    def test_mock_provider_rate_limit_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=mock_provider_env(MAIN_MODEL_MOCK_PROVIDER_MODE="rate_limit"),
        )

        self.assertFalse(response["ok"])
        self.assertEqual("", response["assistant_text"])
        self.assertEqual("rate_limit", response["errors"][0]["error_class"])
        self.assertTrue(response["errors"][0]["retryable"])

    def test_mock_provider_error_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=mock_provider_env(MAIN_MODEL_MOCK_PROVIDER_MODE="provider_error"),
        )

        self.assertFalse(response["ok"])
        self.assertEqual("", response["assistant_text"])
        self.assertEqual("provider_error", response["errors"][0]["error_class"])

    def test_mock_provider_missing_key_fails_closed_without_validation(self):
        logs = []
        response = adapter.call_main_runtime(
            base_request(),
            env={
                "MAIN_MODEL_PROVIDER": "mock_provider",
                "MAIN_MODEL_NAME": "mock-provider-model-v0",
            },
            safe_logs=logs,
        )

        self.assertFalse(response["ok"])
        self.assertEqual("", response["assistant_text"])
        self.assertEqual("missing_api_key", response["errors"][0]["error_class"])
        self.assertEqual("mock_provider", logs[0]["provider"])
        self.assertNotIn("secret", str(response))
        self.assertNotIn("Please answer", str(logs))

    def test_openai_compatible_mock_success_normalizes_responses_fixture(self):
        logs = []
        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_env(),
            safe_logs=logs,
        )

        self.assertTrue(response["ok"])
        self.assertEqual(adapter.RESPONSE_SCHEMA_VERSION, response["schema_version"])
        self.assertEqual("openai_compatible", response["provider"]["provider"])
        self.assertEqual("gpt-5.1", response["provider"]["model"])
        self.assertEqual("[openai-compatible mock] Responses-style fixture reached the adapter.", response["assistant_text"])
        self.assertEqual("stop", response["finish_reason"])
        self.assertEqual(17, response["usage"]["input_tokens"])
        self.assertEqual(12, response["usage"]["output_tokens"])
        self.assertEqual(29, response["usage"]["total_tokens"])
        self.assertEqual([], response["tool_requests"])
        self.assertEqual("none", response["policy_action"])
        self.assertEqual(1, len(logs))
        self.assertEqual("openai_compatible", logs[0]["provider"])
        self.assertEqual(29, logs[0]["total_tokens"])
        self.assertNotIn("TEST_ONLY_OPENAI_COMPATIBLE_API_KEY", str(logs))
        self.assertNotIn("Please answer", str(logs))

    def test_openai_compatible_mock_usage_absent_is_safe(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_env(MAIN_MODEL_OPENAI_COMPATIBLE_MOCK_MODE="usage_absent"),
        )

        self.assertTrue(response["ok"])
        self.assertIsNone(response["usage"]["input_tokens"])
        self.assertIsNone(response["usage"]["output_tokens"])
        self.assertIsNone(response["usage"]["total_tokens"])

    def test_responses_provider_instructions_omit_retired_style_and_warning_counts(self):
        request = base_request()
        request["metadata"]["runtime_profile_packet_metadata"] = {
            "profile_packet_present": True,
            "active_setting_counts": {"astel": 0, "solen": 3, "house": 0},
            "active_solen_style_count": 9,
            "warning_count": 2,
            "policy_action": "none",
        }
        config = adapter.load_main_model_config(openai_compatible_live_env())
        body = adapter.build_openai_compatible_responses_http_body(
            request,
            config,
            adapter.context_packet_stats(None),
        )

        self.assertIn("Runtime profile packet present: yes", body["instructions"])
        self.assertNotIn("style", body["instructions"].casefold())
        self.assertNotIn("Profile warning count", body["instructions"])
        self.assertNotIn("warning_count", body["instructions"])

    def test_openai_compatible_chat_completions_fixture_success_normalizes_text_and_usage(self):
        logs = []
        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_env(MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="chat_completions"),
            safe_logs=logs,
        )

        self.assertTrue(response["ok"])
        self.assertEqual("openai_compatible", response["provider"]["provider"])
        self.assertEqual("gpt-5.1", response["provider"]["model"])
        self.assertEqual(
            "[openai-compatible mock] Chat Completions fixture reached the adapter.",
            response["assistant_text"],
        )
        self.assertEqual("stop", response["finish_reason"])
        self.assertEqual(17, response["usage"]["input_tokens"])
        self.assertEqual(12, response["usage"]["output_tokens"])
        self.assertEqual(29, response["usage"]["total_tokens"])
        self.assertEqual([], response["tool_requests"])
        rendered_logs = str(logs)
        self.assertNotIn("TEST_ONLY_OPENAI_COMPATIBLE_API_KEY", rendered_logs)
        self.assertNotIn("Please answer", rendered_logs)
        self.assertNotIn("Chat Completions fixture reached the adapter", rendered_logs)

    def test_openai_compatible_chat_completions_fixture_provider_error_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_env(
                MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="chat_completions",
                MAIN_MODEL_OPENAI_COMPATIBLE_MOCK_MODE="provider_error",
            ),
        )

        self.assertFalse(response["ok"])
        self.assertEqual("provider_error", response["errors"][0]["error_class"])

    def test_openai_compatible_top_level_output_text_extraction_works(self):
        text, finish_reason, usage = adapter.normalize_openai_compatible_response(
            {
                "id": "resp_fixture_top_level_text",
                "object": "response",
                "status": "completed",
                "output_text": "adapter live synthetic test ok.",
                "finish_reason": "stop",
                "usage": {"input_tokens": 5, "output_tokens": 6, "total_tokens": 11},
            }
        )

        self.assertEqual("adapter live synthetic test ok.", text)
        self.assertEqual("stop", finish_reason)
        self.assertEqual(11, usage["total_tokens"])

    def test_openai_compatible_mock_missing_text_path_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_env(MAIN_MODEL_OPENAI_COMPATIBLE_MOCK_MODE="missing_text"),
        )

        self.assertFalse(response["ok"])
        self.assertEqual("", response["assistant_text"])
        self.assertEqual("missing_output_text", response["errors"][0]["error_class"])

    def test_openai_compatible_mock_malformed_response_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_env(MAIN_MODEL_OPENAI_COMPATIBLE_MOCK_MODE="malformed_response"),
        )

        self.assertFalse(response["ok"])
        self.assertEqual("", response["assistant_text"])
        self.assertEqual("malformed_provider_response", response["errors"][0]["error_class"])

    def test_openai_compatible_mock_unsupported_response_shape_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_env(MAIN_MODEL_OPENAI_COMPATIBLE_MOCK_MODE="unsupported_response_shape"),
        )

        self.assertFalse(response["ok"])
        self.assertEqual("", response["assistant_text"])
        self.assertEqual("unsupported_response_shape", response["errors"][0]["error_class"])

    def test_openai_compatible_mock_timeout_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_env(MAIN_MODEL_OPENAI_COMPATIBLE_MOCK_MODE="timeout"),
        )

        self.assertFalse(response["ok"])
        self.assertEqual("timeout", response["errors"][0]["error_class"])
        self.assertTrue(response["errors"][0]["retryable"])

    def test_openai_compatible_mock_rate_limit_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_env(MAIN_MODEL_OPENAI_COMPATIBLE_MOCK_MODE="rate_limit"),
        )

        self.assertFalse(response["ok"])
        self.assertEqual("rate_limit", response["errors"][0]["error_class"])
        self.assertTrue(response["errors"][0]["retryable"])

    def test_openai_compatible_mock_provider_error_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_env(MAIN_MODEL_OPENAI_COMPATIBLE_MOCK_MODE="provider_error"),
        )

        self.assertFalse(response["ok"])
        self.assertEqual("provider_error", response["errors"][0]["error_class"])
        self.assertTrue(response["errors"][0]["retryable"])

    def test_openai_compatible_mock_auth_error_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_env(MAIN_MODEL_OPENAI_COMPATIBLE_MOCK_MODE="auth_error"),
        )

        self.assertFalse(response["ok"])
        self.assertEqual("auth_error", response["errors"][0]["error_class"])
        self.assertFalse(response["errors"][0]["retryable"])

    def test_openai_compatible_live_http_missing_approval_fails_before_http_call(self):
        called = False

        def fake_transport(url, headers, body, timeout_seconds):
            nonlocal called
            called = True
            return 200, b"{}"

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(HOUSE_ALLOW_MAIN_RUNTIME_LIVE_HTTP="false"),
            http_transport=fake_transport,
        )

        self.assertFalse(response["ok"])
        self.assertFalse(called)
        self.assertEqual("live_http_disabled", response["errors"][0]["error_class"])
        self.assertNotIn("TEST_ONLY_OPENAI_COMPATIBLE_API_KEY", str(response))

    def test_openai_compatible_live_http_missing_key_fails_before_http_call(self):
        called = False

        def fake_transport(url, headers, body, timeout_seconds):
            nonlocal called
            called = True
            return 200, b"{}"

        env = openai_compatible_live_env()
        del env["MAIN_MODEL_API_KEY"]
        response = adapter.call_main_runtime(base_request(), env=env, http_transport=fake_transport)

        self.assertFalse(response["ok"])
        self.assertFalse(called)
        self.assertEqual("missing_api_key", response["errors"][0]["error_class"])

    def test_openai_compatible_live_http_missing_base_url_fails_before_http_call(self):
        called = False

        def fake_transport(url, headers, body, timeout_seconds):
            nonlocal called
            called = True
            return 200, b"{}"

        env = openai_compatible_live_env()
        del env["MAIN_MODEL_BASE_URL"]
        response = adapter.call_main_runtime(base_request(), env=env, http_transport=fake_transport)

        self.assertFalse(response["ok"])
        self.assertFalse(called)
        self.assertEqual("missing_base_url", response["errors"][0]["error_class"])

    def test_openai_compatible_live_http_missing_model_fails_before_http_call(self):
        called = False

        def fake_transport(url, headers, body, timeout_seconds):
            nonlocal called
            called = True
            return 200, b"{}"

        env = openai_compatible_live_env()
        del env["MAIN_MODEL_NAME"]
        response = adapter.call_main_runtime(base_request(), env=env, http_transport=fake_transport)

        self.assertFalse(response["ok"])
        self.assertFalse(called)
        self.assertEqual("missing_model", response["errors"][0]["error_class"])

    def test_openai_compatible_live_http_unsupported_endpoint_fails_closed(self):
        called = False

        def fake_transport(url, headers, body, timeout_seconds):
            nonlocal called
            called = True
            return 200, b"{}"

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="gemini_native"),
            http_transport=fake_transport,
        )

        self.assertFalse(response["ok"])
        self.assertFalse(called)
        self.assertEqual("unsupported_endpoint_family", response["errors"][0]["error_class"])

    def test_openai_compatible_live_http_unsupported_tool_mode_fails_closed(self):
        called = False

        def fake_transport(url, headers, body, timeout_seconds):
            nonlocal called
            called = True
            return 200, b"{}"

        request = base_request()
        request["tool_policy"]["mode"] = "auto"
        response = adapter.call_main_runtime(
            request,
            env=openai_compatible_live_env(),
            http_transport=fake_transport,
        )

        self.assertFalse(response["ok"])
        self.assertFalse(called)
        self.assertEqual("unsupported_tool_mode", response["errors"][0]["error_class"])

    def test_openai_compatible_live_http_success_normalizes_response_and_usage(self):
        seen = {}

        def fake_transport(url, headers, body, timeout_seconds):
            seen["url"] = url
            seen["headers"] = dict(headers)
            seen["body"] = json.loads(body.decode("utf-8"))
            seen["timeout_seconds"] = timeout_seconds
            return 200, json.dumps(
                {
                    "id": "resp_live_test_001",
                    "object": "response",
                    "status": "completed",
                    "model": "gpt-5.1",
                    "output": [
                        {
                            "type": "message",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "adapter live HTTP synthetic test ok.",
                                }
                            ],
                        }
                    ],
                    "finish_reason": "stop",
                    "usage": {"input_tokens": 7, "output_tokens": 8, "total_tokens": 15},
                }
            ).encode("utf-8")

        logs = []
        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            safe_logs=logs,
            http_transport=fake_transport,
        )

        self.assertTrue(response["ok"])
        self.assertEqual("adapter live HTTP synthetic test ok.", response["assistant_text"])
        self.assertEqual(15, response["usage"]["total_tokens"])
        self.assertTrue(response["provider_calls_made"])
        self.assertEqual("https://fixture.invalid/v1/responses", seen["url"])
        self.assertEqual("gpt-5.1", seen["body"]["model"])
        self.assertFalse(seen["body"]["stream"])
        self.assertFalse(seen["body"]["store"])
        self.assertEqual("none", response["policy_action"])
        rendered_logs = str(logs)
        self.assertNotIn("TEST_ONLY_OPENAI_COMPATIBLE_API_KEY", rendered_logs)
        self.assertNotIn("Bearer", rendered_logs)
        self.assertNotIn("https://fixture.invalid", rendered_logs)
        self.assertNotIn("Please answer", rendered_logs)
        self.assertNotIn("adapter live HTTP synthetic test ok", rendered_logs)

    def test_openai_compatible_chat_completions_live_http_builds_minimal_request_and_extracts_message_content(self):
        seen = {}

        def fake_transport(url, headers, body, timeout_seconds):
            seen["url"] = url
            seen["headers"] = dict(headers)
            seen["body"] = json.loads(body.decode("utf-8"))
            return 200, json.dumps(
                {
                    "id": "chatcmpl_live_test_001",
                    "object": "chat.completion",
                    "model": "gpt-5.1",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "chat completions minimal ok."},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 8, "total_tokens": 15},
                }
            ).encode("utf-8")

        logs = []
        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="chat_completions"),
            safe_logs=logs,
            http_transport=fake_transport,
        )

        self.assertTrue(response["ok"])
        self.assertEqual("chat completions minimal ok.", response["assistant_text"])
        self.assertEqual("https://fixture.invalid/v1/chat/completions", seen["url"])
        self.assertEqual(
            {
                "model": "gpt-5.1",
                "messages": [{"role": "user", "content": "Please answer through the fake adapter."}],
                "stream": False,
            },
            seen["body"],
        )
        self.assertNotIn("tools", seen["body"])
        self.assertNotIn("temperature", seen["body"])
        self.assertNotIn("top_p", seen["body"])
        self.assertNotIn("max_tokens", seen["body"])
        self.assertNotIn("store", seen["body"])
        self.assertNotIn("system", str(seen["body"]).lower())
        self.assertEqual(7, response["usage"]["input_tokens"])
        self.assertEqual(8, response["usage"]["output_tokens"])
        self.assertEqual(15, response["usage"]["total_tokens"])
        rendered_logs = str(logs)
        self.assertNotIn("TEST_ONLY_OPENAI_COMPATIBLE_API_KEY", rendered_logs)
        self.assertNotIn("Bearer", rendered_logs)
        self.assertNotIn("https://fixture.invalid", rendered_logs)
        self.assertNotIn("Please answer", rendered_logs)
        self.assertNotIn("chat completions minimal ok", rendered_logs)

    def test_openrouter_qualified_model_is_applied_only_at_transport_boundary(self):
        sections = [
            {
                "section_id": "instruction_law",
                "section_class": "instruction_law",
                "exactness": "exact",
                "update_frequency": "immutable_versioned",
                "rendered_text": "Answer naturally.",
            },
            {
                "section_id": "current_input",
                "section_class": "current_input",
                "exactness": "exact",
                "update_frequency": "per_turn",
                "rendered_text": "A synthetic current turn.",
            },
        ]
        assembly = prompt_cache_production.assemble_production_prompt(
            legacy_user_text="legacy",
            section_outputs=sections,
            envelope={},
            env={prompt_cache_production.FEATURE_SWITCH_NAME: "on"},
            model="openai/gpt-5.5",
            route="openai_compatible_chat_completions",
            tools_requested=False,
        )
        request = base_request(
            chat_projection=assembly.chat_projection,
            metadata={
                "prompt_cache": {
                    "effective_mode": "stable_prefix",
                    "prefix_sha256": "a" * 64,
                }
            },
        )
        config = adapter.load_main_model_config(
            openai_compatible_live_env(
                MAIN_MODEL_NAME="openai/gpt-5.5",
                MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="chat_completions",
            )
        )

        body = adapter.build_openai_compatible_chat_completions_http_body(
            request,
            config,
            {},
        )

        self.assertEqual("openai/gpt-5.5", body["model"])
        self.assertEqual("gpt-5.5", assembly.chat_projection.model)
        self.assertEqual("24h", body["prompt_cache_retention"])
        self.assertEqual("house-pc-v1-" + ("a" * 40), body["prompt_cache_key"])

    def test_provider_body_final_text_invariant_survives_supported_message_shapes(self):
        final_text = "final provider text invariant survives below envelope"
        request = adapter.build_runtime_request(
            request_id="gw_final_text_invariant",
            session_id="session_final_text_invariant",
            user_text=final_text,
        )
        responses_config = adapter.load_main_model_config(openai_compatible_live_env())
        chat_config = adapter.load_main_model_config(
            openai_compatible_live_env(MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="chat_completions")
        )
        anthropic_config = adapter.load_main_model_config(anthropic_compatible_live_env())

        responses_body = adapter.build_openai_compatible_responses_http_body(request, responses_config, {})
        chat_body = adapter.build_openai_compatible_chat_completions_http_body(request, chat_config, {})
        anthropic_body = adapter.build_anthropic_compatible_messages_http_body(request, anthropic_config, {})

        self.assertEqual(final_text, request["user_message"]["text"])
        self.assertEqual(final_text, responses_body["input"][0]["content"][0]["text"])
        self.assertEqual(final_text, chat_body["messages"][0]["content"])
        self.assertEqual(final_text, anthropic_body["messages"][0]["content"])
        for body in (responses_body, chat_body, anthropic_body):
            serialized = json.dumps(body, sort_keys=True)
            self.assertNotIn("context_packet", serialized)
            self.assertNotIn("provider_request_body", serialized)
            self.assertNotIn("provider_response_body", serialized)
            self.assertNotIn("vector", serialized)
            self.assertNotIn("embedding", serialized)

    def test_stable_prefix_cache_controls_are_independently_reversible(self):
        request = adapter.build_runtime_request(
            request_id="gw_cache_retention",
            session_id="session_cache_retention",
            user_text="Synthetic stable-prefix request.",
            metadata={
                "prompt_cache": {
                    "effective_mode": "stable_prefix",
                    "prefix_sha256": "a" * 64,
                }
            },
        )
        enabled_config = adapter.load_main_model_config(
            openai_compatible_live_env(
                MAIN_MODEL_NAME="gpt-5.5",
                MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="chat_completions",
            )
        )
        disabled_config = adapter.load_main_model_config(
            openai_compatible_live_env(
                MAIN_MODEL_NAME="gpt-5.5",
                MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="chat_completions",
                HOUSE_PROMPT_CACHE_RETENTION_POLICY="off",
            )
        )
        key_disabled_config = adapter.load_main_model_config(
            openai_compatible_live_env(
                MAIN_MODEL_NAME="gpt-5.5",
                MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="chat_completions",
                HOUSE_PROMPT_CACHE_KEY_POLICY="off",
            )
        )
        unknown_config = adapter.load_main_model_config(
            openai_compatible_live_env(
                MAIN_MODEL_NAME="gpt-4o",
                MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="chat_completions",
            )
        )

        enabled = adapter.build_openai_compatible_chat_completions_http_body(
            request,
            enabled_config,
            {},
        )
        disabled = adapter.build_openai_compatible_chat_completions_http_body(
            request,
            disabled_config,
            {},
        )
        key_disabled = (
            adapter.build_openai_compatible_chat_completions_http_body(
                request,
                key_disabled_config,
                {},
            )
        )
        unknown = adapter.build_openai_compatible_chat_completions_http_body(
            request,
            unknown_config,
            {},
        )

        self.assertEqual("24h", enabled["prompt_cache_retention"])
        self.assertEqual(
            "house-pc-v1-" + ("a" * 40),
            enabled["prompt_cache_key"],
        )
        self.assertNotIn("prompt_cache_retention", disabled)
        self.assertIn("prompt_cache_key", disabled)
        self.assertEqual("24h", key_disabled["prompt_cache_retention"])
        self.assertNotIn("prompt_cache_key", key_disabled)
        self.assertNotIn("prompt_cache_retention", unknown)
        self.assertIn("prompt_cache_key", unknown)

    def test_prompt_cache_key_requires_valid_existing_prefix_identity(self):
        config = adapter.load_main_model_config(
            openai_compatible_live_env(
                MAIN_MODEL_NAME="gpt-5.5",
                MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="chat_completions",
            )
        )
        for digest in ("", "A" * 64, "a" * 63):
            with self.subTest(digest=digest):
                request = adapter.build_runtime_request(
                    request_id="gw_cache_key_identity",
                    session_id="session_cache_key_identity",
                    user_text="Synthetic stable-prefix request.",
                    metadata={
                        "prompt_cache": {
                            "effective_mode": "stable_prefix",
                            "prefix_sha256": digest,
                        }
                    },
                )
                body = (
                    adapter.build_openai_compatible_chat_completions_http_body(
                        request,
                        config,
                        {},
                    )
                )
                self.assertNotIn("prompt_cache_key", body)

    def test_openai_compatible_chat_completions_live_http_extracts_content_list(self):
        def fake_transport(url, headers, body, timeout_seconds):
            return 200, json.dumps(
                {
                    "id": "chatcmpl_content_list",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": [{"type": "text", "text": "chat content list ok."}],
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
            ).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="chat_completions"),
            http_transport=fake_transport,
        )

        self.assertTrue(response["ok"])
        self.assertEqual("chat content list ok.", response["assistant_text"])

    def test_openai_compatible_chat_completions_live_http_extracts_choice_text(self):
        def fake_transport(url, headers, body, timeout_seconds):
            return 200, json.dumps(
                {
                    "id": "chatcmpl_choice_text",
                    "object": "chat.completion",
                    "choices": [{"text": "chat choice text ok.", "finish_reason": "stop"}],
                }
            ).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="chat_completions"),
            http_transport=fake_transport,
        )

        self.assertTrue(response["ok"])
        self.assertEqual("chat choice text ok.", response["assistant_text"])

    def test_openai_compatible_chat_completions_live_http_extracts_nested_data_envelope(self):
        def fake_transport(url, headers, body, timeout_seconds):
            return 200, json.dumps(
                {
                    "data": {
                        "id": "chatcmpl_nested",
                        "object": "chat.completion",
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "nested chat envelope ok."},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                }
            ).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(MAIN_MODEL_OPENAI_COMPATIBLE_ENDPOINT="chat_completions"),
            http_transport=fake_transport,
        )

        self.assertTrue(response["ok"])
        self.assertEqual("nested chat envelope ok.", response["assistant_text"])

    def test_anthropic_compatible_live_http_builds_messages_request_and_extracts_text(self):
        seen = {}

        def fake_transport(url, headers, body, timeout_seconds):
            seen["url"] = url
            seen["headers"] = dict(headers)
            seen["body"] = json.loads(body.decode("utf-8"))
            return 200, json.dumps(
                {
                    "id": "msg_live_test_001",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "anthropic messages ok."}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 7, "output_tokens": 8},
                }
            ).encode("utf-8")

        logs = []
        response = adapter.call_main_runtime(
            base_request(),
            env=anthropic_compatible_live_env(),
            safe_logs=logs,
            http_transport=fake_transport,
        )

        self.assertTrue(response["ok"])
        self.assertEqual("anthropic messages ok.", response["assistant_text"])
        self.assertEqual("https://fixture.invalid/v1/messages", seen["url"])
        self.assertEqual("TEST_ONLY_ANTHROPIC_COMPATIBLE_API_KEY", seen["headers"]["x-api-key"])
        self.assertEqual("2023-06-01", seen["headers"]["anthropic-version"])
        self.assertEqual(
            {
                "model": "claude-sonnet-4-6",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": "Please answer through the fake adapter."}],
                "stream": False,
            },
            seen["body"],
        )
        self.assertEqual(7, response["usage"]["input_tokens"])
        self.assertEqual(8, response["usage"]["output_tokens"])
        self.assertEqual(15, response["usage"]["total_tokens"])
        rendered_logs = str(logs)
        self.assertNotIn("TEST_ONLY_ANTHROPIC_COMPATIBLE_API_KEY", rendered_logs)
        self.assertNotIn("x-api-key", rendered_logs)
        self.assertNotIn("https://fixture.invalid", rendered_logs)
        self.assertNotIn("Please answer", rendered_logs)
        self.assertNotIn("anthropic messages ok", rendered_logs)

    def test_anthropic_compatible_live_http_fails_closed_on_provider_status(self):
        def fake_transport(url, headers, body, timeout_seconds):
            return 500, json.dumps({"error": {"type": "overloaded_error"}}).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=anthropic_compatible_live_env(),
            http_transport=fake_transport,
        )

        self.assertFalse(response["ok"])
        self.assertEqual("provider_5xx", response["errors"][0]["error_class"])
        self.assertTrue(response["provider_calls_made"])

    def test_openai_compatible_live_http_accepts_output_content_type_text(self):
        def fake_transport(url, headers, body, timeout_seconds):
            return 200, json.dumps(
                {
                    "id": "resp_text_content",
                    "object": "response",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "text", "text": "text content shape ok."}],
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
                }
            ).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            http_transport=fake_transport,
        )

        self.assertTrue(response["ok"])
        self.assertEqual("text content shape ok.", response["assistant_text"])
        self.assertEqual(14, response["usage"]["total_tokens"])

    def test_openai_compatible_live_http_accepts_chat_like_choices_message_content(self):
        logs = []

        def fake_transport(url, headers, body, timeout_seconds):
            return 200, json.dumps(
                {
                    "id": "chatcmpl_text_content",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "chat-like text shape ok."},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"input_tokens": 11, "output_tokens": 5, "total_tokens": 16},
                }
            ).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            safe_logs=logs,
            http_transport=fake_transport,
        )

        self.assertTrue(response["ok"])
        self.assertEqual("chat-like text shape ok.", response["assistant_text"])
        self.assertEqual("stop", response["finish_reason"])
        self.assertEqual(16, response["usage"]["total_tokens"])
        rendered_logs = str(logs)
        self.assertNotIn("chat-like text shape ok", rendered_logs)
        self.assertNotIn("TEST_ONLY_OPENAI_COMPATIBLE_API_KEY", rendered_logs)

    def test_openai_compatible_live_http_accepts_choices_text(self):
        def fake_transport(url, headers, body, timeout_seconds):
            return 200, json.dumps(
                {
                    "id": "cmpl_text",
                    "object": "chat.completion",
                    "choices": [{"text": "choice text shape ok.", "finish_reason": "length"}],
                }
            ).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            http_transport=fake_transport,
        )

        self.assertTrue(response["ok"])
        self.assertEqual("choice text shape ok.", response["assistant_text"])
        self.assertEqual("length", response["finish_reason"])

    def test_openai_compatible_live_http_accepts_text_from_nested_data_envelope(self):
        def fake_transport(url, headers, body, timeout_seconds):
            return 200, json.dumps(
                {
                    "data": {
                        "id": "resp_nested",
                        "object": "response",
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": "nested envelope ok."}],
                            }
                        ],
                    }
                }
            ).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            http_transport=fake_transport,
        )

        self.assertTrue(response["ok"])
        self.assertEqual("nested envelope ok.", response["assistant_text"])

    def test_openai_compatible_live_http_uses_text_from_incomplete_max_token_response(self):
        def fake_transport(url, headers, body, timeout_seconds):
            return 200, json.dumps(
                {
                    "id": "resp_incomplete",
                    "object": "response",
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "partial text is usable."}],
                        }
                    ],
                    "usage": {"input_tokens": 122, "output_tokens": 120, "total_tokens": 242},
                }
            ).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            http_transport=fake_transport,
        )

        self.assertTrue(response["ok"])
        self.assertEqual("partial text is usable.", response["assistant_text"])
        self.assertEqual("incomplete", response["finish_reason"])
        self.assertEqual(242, response["usage"]["total_tokens"])

    def test_openai_compatible_live_http_malformed_json_fails_closed(self):
        def fake_transport(url, headers, body, timeout_seconds):
            return 200, b"{not-json"

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            http_transport=fake_transport,
        )

        self.assertFalse(response["ok"])
        self.assertEqual("malformed_json", response["errors"][0]["error_class"])

    def test_openai_compatible_live_http_missing_output_text_fails_closed(self):
        def fake_transport(url, headers, body, timeout_seconds):
            return 200, json.dumps(
                {"id": "resp_missing", "object": "response", "status": "completed", "output": []}
            ).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            http_transport=fake_transport,
        )

        self.assertFalse(response["ok"])
        self.assertEqual("missing_output_text", response["errors"][0]["error_class"])

    def test_openai_compatible_live_http_200_without_text_does_not_become_provider_error(self):
        def fake_transport(url, headers, body, timeout_seconds):
            return 200, json.dumps(
                {"id": "resp_no_text", "object": "response", "status": "incomplete", "output": []}
            ).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            http_transport=fake_transport,
        )

        self.assertFalse(response["ok"])
        self.assertIn(
            response["errors"][0]["error_class"],
            {"missing_output_text", "unsupported_response_shape"},
        )
        self.assertNotEqual("provider_error", response["errors"][0]["error_class"])

    def test_openai_compatible_live_http_non_2xx_auth_rate_limit_timeout_fail_closed(self):
        cases = [
            ("auth_error", 401, lambda url, headers, body, timeout_seconds: (401, b'{"error":"auth"}')),
            ("rate_limit", 429, lambda url, headers, body, timeout_seconds: (429, b'{"error":"rate"}')),
            ("provider_4xx", 400, lambda url, headers, body, timeout_seconds: (400, b'{"error":{"code":"bad_request"}}')),
            ("provider_5xx", 500, lambda url, headers, body, timeout_seconds: (500, b'{"error":"server"}')),
            ("provider_non_2xx", 302, lambda url, headers, body, timeout_seconds: (302, b'{"error":{"type":"redirected"}}')),
        ]
        for expected, expected_status_code, fake_transport in cases:
            with self.subTest(expected=expected):
                response = adapter.call_main_runtime(
                    base_request(),
                    env=openai_compatible_live_env(),
                    http_transport=fake_transport,
                )
                self.assertFalse(response["ok"])
                self.assertEqual(expected, response["errors"][0]["error_class"])
                self.assertEqual(expected_status_code, response["errors"][0]["http_status_code"])

        def timeout_transport(url, headers, body, timeout_seconds):
            raise TimeoutError("timeout")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            http_transport=timeout_transport,
        )

        self.assertFalse(response["ok"])
        self.assertEqual("timeout", response["errors"][0]["error_class"])

    def test_openai_compatible_live_http_403_classifies_as_auth_error(self):
        def fake_transport(url, headers, body, timeout_seconds):
            return 403, b'{"error":{"code":"forbidden"}}'

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            http_transport=fake_transport,
        )

        self.assertFalse(response["ok"])
        self.assertEqual("auth_error", response["errors"][0]["error_class"])

    def test_openai_compatible_live_http_unsupported_shape_fails_closed(self):
        def fake_transport(url, headers, body, timeout_seconds):
            return 200, json.dumps({"id": "chat_1", "object": "chat.completion", "choices": []}).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            http_transport=fake_transport,
        )

        self.assertFalse(response["ok"])
        self.assertEqual("unsupported_response_shape", response["errors"][0]["error_class"])

    def test_openai_compatible_live_http_safe_provider_error_code_is_captured(self):
        logs = []

        def fake_transport(url, headers, body, timeout_seconds):
            return 400, json.dumps({"error": {"code": "invalid_request"}}).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            safe_logs=logs,
            http_transport=fake_transport,
        )

        self.assertFalse(response["ok"])
        self.assertEqual("provider_4xx", response["errors"][0]["error_class"])
        self.assertEqual("invalid_request", response["errors"][0]["provider_error_code_safe"])
        self.assertEqual(400, response["errors"][0]["http_status_code"])
        self.assertEqual("invalid_request", logs[0]["provider_error_code_safe"])
        self.assertEqual(400, logs[0]["http_status_code"])
        rendered = str(response) + str(logs)
        self.assertNotIn("TEST_ONLY_OPENAI_COMPATIBLE_API_KEY", rendered)
        self.assertNotIn("Bearer", rendered)
        self.assertNotIn("https://fixture.invalid", rendered)

    def test_openai_compatible_live_http_unsafe_provider_error_code_is_withheld(self):
        logs = []

        def fake_transport(url, headers, body, timeout_seconds):
            return 400, json.dumps(
                {
                    "error": {
                        "code": "https://fixture.invalid/v1 Please answer token-like",
                        "message": "Please answer through the fake adapter.",
                    }
                }
            ).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            safe_logs=logs,
            http_transport=fake_transport,
        )

        self.assertFalse(response["ok"])
        self.assertEqual("provider_4xx", response["errors"][0]["error_class"])
        self.assertEqual(400, response["errors"][0]["http_status_code"])
        self.assertNotIn("provider_error_code_safe", response["errors"][0])
        rendered = str(response) + str(logs)
        self.assertNotIn("https://fixture.invalid", rendered)
        self.assertNotIn("Please answer", rendered)
        self.assertNotIn("token-like", rendered)

    def test_openai_compatible_live_http_provider_tool_request_fails_closed(self):
        def fake_transport(url, headers, body, timeout_seconds):
            return 200, json.dumps(
                {
                    "id": "resp_tool",
                    "object": "response",
                    "status": "completed",
                    "output": [{"type": "function_call", "name": "tool"}],
                }
            ).encode("utf-8")

        response = adapter.call_main_runtime(
            base_request(),
            env=openai_compatible_live_env(),
            http_transport=fake_transport,
        )

        self.assertFalse(response["ok"])
        self.assertEqual("provider_tool_request", response["errors"][0]["error_class"])

    def test_openai_compatible_missing_key_fails_closed_without_validation(self):
        logs = []
        response = adapter.call_main_runtime(
            base_request(),
            env={
                "MAIN_MODEL_PROVIDER": "openai_compatible",
                "MAIN_MODEL_NAME": "gpt-5.1",
                "MAIN_MODEL_BASE_URL": "https://fixture.invalid/v1",
            },
            safe_logs=logs,
        )

        self.assertFalse(response["ok"])
        self.assertEqual("", response["assistant_text"])
        self.assertEqual("missing_api_key", response["errors"][0]["error_class"])
        self.assertEqual("openai_compatible", logs[0]["provider"])
        self.assertNotIn("Please answer", str(logs))

    def test_openai_compatible_missing_base_url_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env={
                "MAIN_MODEL_PROVIDER": "openai_compatible",
                "MAIN_MODEL_NAME": "gpt-5.1",
                "MAIN_MODEL_API_KEY": "TEST_ONLY_OPENAI_COMPATIBLE_API_KEY",
            },
        )

        self.assertFalse(response["ok"])
        self.assertEqual("missing_base_url", response["errors"][0]["error_class"])
        self.assertNotIn("TEST_ONLY_OPENAI_COMPATIBLE_API_KEY", str(response))

    def test_openai_compatible_logs_omit_secrets_prompts_and_fixture_bodies(self):
        packet = {
            "schema_version": "context_packet_v0",
            "records": [
                {
                    "record_id": "doc_1",
                    "source_type": "project_doc",
                    "source_name": "HOUSE_CURRENT_STATE_QUICK_REVIEW_2026-05-07.md",
                    "quote": "RAW_DOC_SNIPPET_DO_NOT_LOG",
                }
            ],
            "source_notes": ["RAW_SOURCE_NOTE_DO_NOT_LOG"],
            "policy_action": "none",
        }
        logs = []
        response = adapter.call_main_runtime(
            base_request(context_packet=packet),
            env=openai_compatible_env(MAIN_MODEL_API_KEY="TEST_ONLY_OPENAI_COMPATIBLE_API_KEY"),
            safe_logs=logs,
        )

        self.assertTrue(response["ok"])
        rendered_logs = str(logs)
        for forbidden in [
            "TEST_ONLY_OPENAI_COMPATIBLE_API_KEY",
            "Please answer",
            "RAW_DOC_SNIPPET_DO_NOT_LOG",
            "RAW_SOURCE_NOTE_DO_NOT_LOG",
            "openai_compatible_responses_request_fixture_v0",
            "resp_fixture_001",
            "Responses-style fixture reached the adapter",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered_logs)

    def test_mock_provider_logs_omit_prompt_context_and_provider_bodies(self):
        packet = {
            "schema_version": "context_packet_v0",
            "records": [
                {
                    "record_id": "doc_1",
                    "source_type": "project_doc",
                    "source_name": "HOUSE_CURRENT_STATE_QUICK_REVIEW_2026-05-07.md",
                    "quote": "RAW_DOC_SNIPPET_DO_NOT_LOG",
                }
            ],
            "conversation_recall": [
                {
                    "quote": "RAW_DOC_SNIPPET_DO_NOT_LOG",
                    "evidence_ref": {"source_pointer": "project_doc://safe"},
                }
            ],
            "source_notes": ["RAW_SOURCE_NOTE_DO_NOT_LOG"],
            "policy_action": "none",
        }
        logs = []
        response = adapter.call_main_runtime(
            base_request(context_packet=packet),
            env=mock_provider_env(MAIN_MODEL_API_KEY="TEST_ONLY_PROVIDER_API_KEY"),
            safe_logs=logs,
        )

        self.assertTrue(response["ok"])
        self.assertNotIn("RAW_DOC_SNIPPET_DO_NOT_LOG", response["assistant_text"])
        rendered_logs = str(logs)
        for forbidden in [
            "TEST_ONLY_PROVIDER_API_KEY",
            "Please answer",
            "RAW_DOC_SNIPPET_DO_NOT_LOG",
            "RAW_SOURCE_NOTE_DO_NOT_LOG",
            "mock_provider_request_v0",
            "mock_provider_response_v0",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered_logs)

    def test_missing_key_fails_for_real_provider_mode(self):
        response = adapter.call_main_runtime(
            base_request(),
            env={"MAIN_MODEL_PROVIDER": "openai", "MAIN_MODEL_NAME": "example-model"},
        )
        self.assertFalse(response["ok"])
        self.assertEqual("missing_api_key", response["errors"][0]["error_class"])

    def test_disabled_provider_fails_clearly(self):
        response = adapter.call_main_runtime(
            base_request(),
            env={"MAIN_MODEL_PROVIDER": "disabled"},
        )
        self.assertFalse(response["ok"])
        self.assertEqual("provider_disabled", response["errors"][0]["error_class"])

    def test_unsupported_provider_label_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(),
            env={"MAIN_MODEL_PROVIDER": "unknown_provider", "MAIN_MODEL_NAME": "example-model"},
        )
        self.assertFalse(response["ok"])
        self.assertEqual("unsupported_provider", response["errors"][0]["error_class"])

    def test_non_fixture_real_provider_with_key_is_not_implemented_and_makes_no_call(self):
        response = adapter.call_main_runtime(
            base_request(),
            env={
                "MAIN_MODEL_PROVIDER": "openai",
                "MAIN_MODEL_NAME": "example-model",
                "MAIN_MODEL_API_KEY": "TEST_ONLY_API_KEY",
            },
        )
        self.assertFalse(response["ok"])
        self.assertEqual("real_provider_not_implemented", response["errors"][0]["error_class"])
        self.assertNotIn("TEST_ONLY_API_KEY", str(response))

    def test_context_packet_too_large_fails_before_provider(self):
        packet = {
            "schema_version": "context_packet_v0",
            "records": [{"record_id": "mem_big", "summary": "x" * 1000}],
        }
        response = adapter.call_main_runtime(
            base_request(context_packet=packet),
            env=fake_env(MAIN_MODEL_MAX_INPUT_TOKENS="10"),
        )
        self.assertFalse(response["ok"])
        self.assertEqual("context_packet_too_large", response["errors"][0]["error_class"])

    def test_unsupported_tools_fail_before_provider(self):
        request = base_request()
        request["tool_policy"]["mode"] = "native"
        response = adapter.call_main_runtime(request, env=fake_env())
        self.assertFalse(response["ok"])
        self.assertEqual("unsupported_tools", response["errors"][0]["error_class"])

    def test_invalid_request_schema_fails_closed(self):
        request = base_request()
        request["schema_version"] = "wrong"
        response = adapter.call_main_runtime(request, env=fake_env())
        self.assertFalse(response["ok"])
        self.assertEqual("invalid_schema_version", response["errors"][0]["error_class"])

    def test_invalid_context_packet_schema_fails_closed(self):
        response = adapter.call_main_runtime(
            base_request(context_packet={"schema_version": "wrong"}),
            env=fake_env(),
        )
        self.assertFalse(response["ok"])
        self.assertEqual("invalid_context_packet", response["errors"][0]["error_class"])

    def test_safe_config_summary_omits_secret_values(self):
        summary = adapter.get_safe_config_summary(
            {
                "MAIN_MODEL_PROVIDER": "openai",
                "MAIN_MODEL_NAME": "example-model",
                "MAIN_MODEL_API_KEY": "TEST_ONLY_API_KEY",
            }
        )
        self.assertTrue(summary["api_key_configured"])
        self.assertNotIn("TEST_ONLY_API_KEY", str(summary))


if __name__ == "__main__":
    unittest.main()
