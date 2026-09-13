import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

import provider_trace_vault_v0 as trace_vault


class ProviderTraceVaultV0Tests(unittest.TestCase):
    def make_vault(self, temp_dir: str) -> trace_vault.ProviderTraceVault:
        return trace_vault.ProviderTraceVault(Path(temp_dir) / "provider-traces")

    def begin(self, vault: trace_vault.ProviderTraceVault, body: bytes = b'{"prompt":"hello"}'):
        return vault.begin_attempt(
            body,
            operation_id="op_house_turn_123",
            request_id="request_456",
            provider_label="openai_compatible",
            model_label="house_model_v1",
            endpoint_family="chat_completions",
            attempt_number=1,
        )

    def test_success_preserves_exact_bytes_hashes_and_http_metadata(self):
        request_body = b'{"messages":[{"content":"Astel \xf0\x9f\x92\x9c"}]}\n'
        response_body = b'{"choices":[{"message":{"content":"Solen"}}]}\r\n'
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = self.make_vault(temp_dir)
            created = self.begin(vault, request_body)
            updated = vault.record_response(created.trace_id, response_body, http_status=200)
            vault.record_stage(
                created.trace_id,
                stage="provider_shape_validation",
                outcome="accepted",
                reason_label="valid_text_shape",
            )
            manifest = vault.read_manifest(created.trace_id)

            self.assertEqual(request_body, vault.read_request_body(created.trace_id))
            self.assertEqual(response_body, vault.read_response_body(created.trace_id))

        self.assertEqual(hashlib.sha256(request_body).hexdigest(), created.request_sha256)
        self.assertEqual(hashlib.sha256(response_body).hexdigest(), updated.response_sha256)
        self.assertEqual(len(request_body), manifest["request"]["byte_count"])
        self.assertEqual(len(response_body), manifest["response"]["byte_count"])
        self.assertEqual(200, manifest["http_status"])
        self.assertTrue(manifest["response_received"])
        self.assertEqual(
            ["request_capture", "response_capture", "provider_shape_validation"],
            [item["stage"] for item in manifest["stages"]],
        )

    def test_private_intimate_negative_and_contradictory_text_is_not_redacted(self):
        request_body = (
            "private intimate adult negative contradictory material remains ordinary trace bytes"
        ).encode("utf-8")
        response_body = (
            "intimate and contradictory provider text remains byte-exact inside private footing"
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = self.make_vault(temp_dir)
            receipt = self.begin(vault, request_body)
            vault.record_response(receipt.trace_id, response_body, http_status=200)

            self.assertEqual(request_body, vault.read_request_body(receipt.trace_id))
            self.assertEqual(response_body, vault.read_response_body(receipt.trace_id))

    def test_http_rejection_is_raw_free_metadata_with_exact_response_body(self):
        response_body = b'{"error":{"message":"provider rejected shape"}}'
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = self.make_vault(temp_dir)
            receipt = self.begin(vault)
            vault.record_response(receipt.trace_id, response_body, http_status=422)
            vault.record_stage(
                receipt.trace_id,
                stage="http_status_validation",
                outcome="rejected",
                reason_label="http_non_success",
            )
            manifest = vault.read_manifest(receipt.trace_id)

        self.assertEqual(422, manifest["http_status"])
        self.assertEqual("rejected", manifest["stages"][-1]["outcome"])
        self.assertEqual("http_non_success", manifest["stages"][-1]["reason_label"])
        self.assertNotIn("provider rejected shape", json.dumps(manifest))

    def test_transport_error_keeps_request_without_inventing_response(self):
        request_body = b"request that reached the transport boundary"
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = self.make_vault(temp_dir)
            receipt = self.begin(vault, request_body)
            updated = vault.record_transport_error(receipt.trace_id, reason_label="timeout")
            manifest = vault.read_manifest(receipt.trace_id)

            self.assertEqual(request_body, vault.read_request_body(receipt.trace_id))
            self.assertIsNone(vault.read_response_body(receipt.trace_id))
            self.assertFalse((vault.root / receipt.trace_id / "response.body").exists())

        self.assertFalse(updated.response_received)
        self.assertIsNone(manifest["http_status"])
        self.assertIsNone(manifest["response"])
        self.assertEqual("transport_error", manifest["stages"][-1]["outcome"])

    def test_stage_history_supports_all_outcomes_and_rejects_free_text_reasons(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = self.make_vault(temp_dir)
            receipt = self.begin(vault)
            vault.record_stage(receipt.trace_id, stage="json_parse", outcome="accepted")
            vault.record_stage(
                receipt.trace_id,
                stage="normalization",
                outcome="rejected",
                reason_label="missing_text",
            )
            vault.record_stage(
                receipt.trace_id,
                stage="transport",
                outcome="transport_error",
                reason_label="connection_reset",
            )
            with self.assertRaises(trace_vault.ProviderTraceVaultError):
                vault.record_stage(
                    receipt.trace_id,
                    stage="validation",
                    outcome="rejected",
                    reason_label="raw provider said: secret body",
                )
            manifest = vault.read_manifest(receipt.trace_id)

        self.assertEqual(
            ["accepted", "accepted", "rejected", "transport_error"],
            [item["outcome"] for item in manifest["stages"]],
        )

    def test_invalid_trace_ids_labels_types_and_statuses_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = self.make_vault(temp_dir)
            with self.assertRaises(trace_vault.ProviderTraceVaultError):
                vault.begin_attempt(
                    b"request",
                    operation_id="op_1",
                    request_id=None,
                    provider_label="provider",
                    model_label="model",
                    endpoint_family="chat",
                    attempt_number=1,
                    trace_id="../outside",
                )
            with self.assertRaises(trace_vault.ProviderTraceVaultError):
                vault.begin_attempt(
                    bytearray(b"not bytes"),
                    operation_id="op_1",
                    request_id=None,
                    provider_label="provider",
                    model_label="model",
                    endpoint_family="chat",
                    attempt_number=1,
                )
            with self.assertRaises(trace_vault.ProviderTraceVaultError):
                vault.begin_attempt(
                    b"request",
                    operation_id="op_1",
                    request_id=None,
                    provider_label="https://provider.example",
                    model_label="model",
                    endpoint_family="chat",
                    attempt_number=1,
                )
            slash_model = vault.begin_attempt(
                b"request",
                operation_id="op_2",
                request_id=None,
                provider_label="provider",
                model_label="vendor/model-v1",
                endpoint_family="chat",
                attempt_number=1,
            )
            self.assertEqual("vendor/model-v1", vault.read_manifest(slash_model.trace_id)["model_label"])
            with self.assertRaises(trace_vault.ProviderTraceVaultError):
                vault.begin_attempt(
                    b"request",
                    operation_id="op_3",
                    request_id=None,
                    provider_label="provider",
                    model_label="vendor/../model",
                    endpoint_family="chat",
                    attempt_number=1,
                )
            receipt = self.begin(vault)
            with self.assertRaises(trace_vault.ProviderTraceVaultError):
                vault.read_manifest("ptv1_" + "g" * 32)
            with self.assertRaises(trace_vault.ProviderTraceVaultError):
                vault.record_response(receipt.trace_id, b"bad status", http_status=700)

            self.assertFalse((Path(temp_dir) / "outside").exists())

    def test_manifest_has_only_raw_free_schema_fields(self):
        forbidden_keys = {
            "authorization",
            "headers",
            "api_key",
            "cookies",
            "environment",
            "env",
            "base_url",
            "request_body",
            "response_body",
        }

        def walk_keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key
                    yield from walk_keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from walk_keys(child)

        with tempfile.TemporaryDirectory() as temp_dir:
            vault = self.make_vault(temp_dir)
            receipt = self.begin(vault, b"private request content")
            vault.record_response(receipt.trace_id, b"private response content", http_status=200)
            manifest = vault.read_manifest(receipt.trace_id)
            serialized = json.dumps(manifest, sort_keys=True)

        self.assertTrue(forbidden_keys.isdisjoint(set(walk_keys(manifest))))
        self.assertNotIn("private request content", serialized)
        self.assertNotIn("private response content", serialized)
        self.assertNotIn("http://", serialized)
        self.assertNotIn("https://", serialized)

    def test_new_vault_instance_reopens_metadata_and_verified_raw_bodies(self):
        request_body = b"request persisted before send"
        response_body = b"response persisted before parse"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "provider-traces"
            first = trace_vault.ProviderTraceVault(root)
            receipt = self.begin(first, request_body)
            first.record_response(receipt.trace_id, response_body, http_status=201)

            reopened = trace_vault.ProviderTraceVault(root)
            manifest = reopened.read_manifest(receipt.trace_id)
            reopened_receipt = reopened.record_stage(
                receipt.trace_id,
                stage="final_text_validation",
                outcome="accepted",
            )

            self.assertEqual(request_body, reopened.read_request_body(receipt.trace_id))
            self.assertEqual(response_body, reopened.read_response_body(receipt.trace_id))

        self.assertEqual(trace_vault.SCHEMA, manifest["schema"])
        self.assertEqual(receipt.trace_id, reopened_receipt.trace_id)
        self.assertTrue(reopened_receipt.response_received)

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits are not available on this platform")
    def test_private_group_readable_modes_preserve_existing_root_setgid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "provider-traces"
            root.mkdir(mode=0o750)
            root.chmod(0o2750)
            vault = trace_vault.ProviderTraceVault(root)
            receipt = self.begin(vault)
            vault.record_response(receipt.trace_id, b"response", http_status=200)
            trace_dir = root / receipt.trace_id

            self.assertEqual(0o2750, stat.S_IMODE(root.stat().st_mode))
            self.assertEqual(0o2750, stat.S_IMODE(trace_dir.stat().st_mode))
            self.assertEqual(0, stat.S_IMODE(trace_dir.stat().st_mode) & 0o007)
            self.assertEqual(0o640, stat.S_IMODE((trace_dir / "request.body").stat().st_mode))
            self.assertEqual(0o640, stat.S_IMODE((trace_dir / "response.body").stat().st_mode))
            self.assertEqual(0o640, stat.S_IMODE((trace_dir / "manifest.json").stat().st_mode))


if __name__ == "__main__":
    unittest.main()
