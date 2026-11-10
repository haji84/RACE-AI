"""Explicit source configuration observability without inspecting secrets.

Never performs provider HTTP, creates license, or modifies production state.
"""
import json
import unittest

from scripts.keirin_cloud_pr71_state import (
    LICENSED_SOURCE_REQUIRED_KEYS, missing_source_configuration
)


class CloudLicensedSourceReadinessTests(unittest.TestCase):
    def test_missing_config_names_are_exact_known_safe_names(self):
        d = {key: "opaque-private-placeholder" for key in
             LICENSED_SOURCE_REQUIRED_KEYS}
        self.assertEqual(missing_source_configuration(d), [])
        missing = LICENSED_SOURCE_REQUIRED_KEYS[2]
        d[missing] = ""
        output = missing_source_configuration(d)
        self.assertEqual(output, [missing])
        self.assertNotIn("opaque-private-placeholder", json.dumps(output))

    def test_all_missing_names_are_visible_without_values(self):
        expected = list(LICENSED_SOURCE_REQUIRED_KEYS)
        self.assertEqual(missing_source_configuration({}), expected)
        self.assertTrue(all(k.startswith("RACE_AI_KEIRIN_") for k in expected))
        self.assertNotIn("RACE_AI_STATE_KEY", expected)
        self.assertNotIn("RACE_AI_KEIRIN_FEED_TOKEN", expected)

    def test_one_missing_config_does_not_forge_legal_entitlement(self):
        test_env = {k: "not-a-real-grant" for k in LICENSED_SOURCE_REQUIRED_KEYS}
        self.assertEqual(missing_source_configuration(test_env), [])
        # Complete CONFIG is only a connectivity precondition.
        # It cannot independently validate issuer, contract or licence scope.
        self.assertEqual(len(test_env), 4)


if __name__ == "__main__":
    unittest.main()
