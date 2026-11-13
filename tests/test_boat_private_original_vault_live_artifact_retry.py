"""Test transient *GitHub* artifact availability; never race source GET."""
import unittest
from unittest.mock import patch
from scripts import boat_private_original_vault as cli


class LiveGithubArtifactRetryTests(unittest.TestCase):
    def test_recent_same_artifact_id_can_be_read_after_two_transient_denials(self):
        endpoint="actions/artifacts/14004326635"
        with patch.object(cli,"_gh_once",side_effect=[
                ValueError("VAULT_GITHUB_READ_DENIED_OR_UNAVAILABLE"),
                ValueError("VAULT_GITHUB_READ_DENIED_OR_UNAVAILABLE"),
                b"IMMUTABLE_SYNTHETIC_METADATA"]) as get, \
             patch.object(cli.time,"sleep") as pause:
            self.assertEqual(cli._gh(endpoint),b"IMMUTABLE_SYNTHETIC_METADATA")
        self.assertEqual(get.call_count,3)
        self.assertTrue(all(x.args == (endpoint,) for x in get.call_args_list))
        self.assertEqual([x.args[0] for x in pause.call_args_list],[2,4])

    def test_artifact_zip_permanent_denial_keeps_hold(self):
        endpoint="actions/artifacts/14004326635/zip"
        with patch.object(cli,"_gh_once",side_effect=ValueError(
                "VAULT_GITHUB_READ_DENIED_OR_UNAVAILABLE")) as get, \
             patch.object(cli.time,"sleep") as pause:
            with self.assertRaisesRegex(ValueError,"VAULT_GITHUB_READ_DENIED_OR_UNAVAILABLE"):
                cli._gh(endpoint)
        self.assertEqual(get.call_count,3)
        self.assertEqual(pause.call_count,2)

    def test_source_run_denial_is_not_retried(self):
        with patch.object(cli,"_gh_once",side_effect=ValueError(
                "VAULT_GITHUB_READ_DENIED_OR_UNAVAILABLE")) as get, \
             patch.object(cli.time,"sleep") as pause:
            with self.assertRaisesRegex(ValueError,"VAULT_GITHUB_READ_DENIED_OR_UNAVAILABLE"):
                cli._gh("actions/runs/43348227701")
        get.assert_called_once();pause.assert_not_called()

    def test_integrity_size_and_secret_failures_never_retry(self):
        endpoint="actions/artifacts/14004326635"
        for reason in ("VAULT_GITHUB_READ_BOUND_INVALID",
                       "VAULT_GITHUB_READ_TIMEOUT",
                       "VAULT_LIVE_ARTIFACT_DIGEST_INVALID"):
            with self.subTest(reason=reason),patch.object(cli,"_gh_once",
                    side_effect=ValueError(reason)) as get, \
                 patch.object(cli.time,"sleep") as pause:
                with self.assertRaisesRegex(ValueError,reason):
                    cli._gh(endpoint)
                get.assert_called_once();pause.assert_not_called()


if __name__=="__main__":
    unittest.main()
