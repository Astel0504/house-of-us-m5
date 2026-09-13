import unittest

import house_prompt_cache_key_policy_v1 as policy


class PromptCacheKeyPolicyTests(unittest.TestCase):
    def decision(
        self,
        *,
        provider: str = "openai_compatible",
        endpoint: str = "chat_completions",
        stable: bool = True,
        digest: str = "a" * 64,
        mode: str = "default_on",
        enabled: bool = True,
    ):
        return policy.decide_cache_key(
            provider=provider,
            endpoint_family=endpoint,
            stable_prefix_effective=stable,
            prefix_sha256=digest,
            configured_mode=mode,
            enabled=enabled,
        )

    def test_default_and_explicit_switch_modes(self):
        self.assertEqual(("default_on", True), policy.configured_feature_mode({}))
        self.assertEqual(
            ("explicit_on", True),
            policy.configured_feature_mode(
                {policy.FEATURE_SWITCH_NAME: "enabled"}
            ),
        )
        self.assertEqual(
            ("explicit_off", False),
            policy.configured_feature_mode(
                {policy.FEATURE_SWITCH_NAME: "off"}
            ),
        )
        self.assertEqual(
            ("invalid_off", False),
            policy.configured_feature_mode(
                {policy.FEATURE_SWITCH_NAME: "surprising"}
            ),
        )

    def test_valid_stable_prefix_requests_namespaced_hash_only_key(self):
        decision = self.decision()

        self.assertTrue(decision.requested)
        self.assertEqual(
            "requested_stable_prefix_key",
            decision.policy_state,
        )
        self.assertEqual(
            {
                "prompt_cache_key": (
                    "house-pc-v1-" + ("a" * policy.KEY_DIGEST_CHARS)
                )
            },
            decision.request_fields,
        )
        self.assertNotIn("a" * 64, repr(decision))
        self.assertEqual(
            {
                "cache_key_feature_switch": policy.FEATURE_SWITCH_NAME,
                "cache_key_configured_mode": "default_on",
                "cache_key_policy_state": "requested_stable_prefix_key",
                "cache_key_requested": True,
            },
            decision.safe_observability(),
        )

    def test_switch_off_omits_key(self):
        decision = self.decision(mode="explicit_off", enabled=False)

        self.assertFalse(decision.requested)
        self.assertEqual("switch_off", decision.policy_state)
        self.assertEqual({}, decision.request_fields)

    def test_inactive_prefix_omits_key(self):
        decision = self.decision(stable=False)

        self.assertFalse(decision.requested)
        self.assertEqual("stable_prefix_inactive", decision.policy_state)

    def test_invalid_or_missing_prefix_identity_omits_key(self):
        for digest in ("", "a" * 63, "A" * 64, "g" * 64, None):
            with self.subTest(digest=digest):
                decision = self.decision(digest=digest)
                self.assertFalse(decision.requested)
                self.assertEqual(
                    "prefix_identity_unavailable",
                    decision.policy_state,
                )

    def test_unsupported_provider_or_endpoint_omits_key(self):
        unsupported_provider = self.decision(provider="anthropic_compatible")
        unsupported_endpoint = self.decision(endpoint="responses")

        self.assertEqual(
            "unsupported_provider",
            unsupported_provider.policy_state,
        )
        self.assertEqual(
            "unsupported_endpoint",
            unsupported_endpoint.policy_state,
        )
        self.assertEqual({}, unsupported_provider.request_fields)
        self.assertEqual({}, unsupported_endpoint.request_fields)

    def test_distinct_prefix_hashes_produce_distinct_keys(self):
        first = self.decision(digest="a" * 64)
        second = self.decision(digest="b" * 64)

        self.assertNotEqual(first.request_fields, second.request_fields)


if __name__ == "__main__":
    unittest.main()
