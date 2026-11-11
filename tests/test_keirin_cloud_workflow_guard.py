"""Cloud-only GitHub workflow safety, not a source grant or prediction test."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
FLOW=ROOT/".github/workflows/keirin-pr71-owner-autonomous.yml"
STATE=ROOT/"scripts/keirin_cloud_pr71_state.py"


class CloudGuardTests(unittest.TestCase):
    def test_public_repo_keeps_github_hosted_only(self):
        y=FLOW.read_text(encoding="utf-8")
        self.assertIn("name: KEIRIN PR71 GitHub-only forecast and PDCA",y)
        self.assertIn("runs-on: ubuntu-24.04",y)
        self.assertNotIn("self-hosted",y)
        self.assertNotIn("runs-on: [",y)
        self.assertNotIn("keirin-owner-private",y)
        self.assertNotIn("OWNER_RUNTIME_ENABLED",y)
        self.assertNotIn("github.event.repository.private == true",y)
        self.assertIn("schedule:",y)
        self.assertIn("3,33 * * * *",y)
        self.assertIn("8,13,18,23,28,38,43,48,53,58 * * * *",y)
        self.assertIn("needs: config_readiness",y)
        self.assertIn("cancel-in-progress: false",y)

    def test_secret_write_job_never_runs_on_pr(self):
        y=FLOW.read_text(encoding="utf-8")
        cloud=y.split("\n  github-hosted-pr71-cycle:\n",1)[1].split(
            "\n  independent-cloud-readback:\n",1)[0]
        self.assertIn("github.ref == 'refs/heads/main'",cloud)
        self.assertIn("github.event_name == 'schedule'",cloud)
        self.assertIn("github.event_name == 'workflow_dispatch'",cloud)
        self.assertNotIn("github.event_name == 'pull_request'",cloud)
        self.assertIn("contents: write",cloud)
        self.assertIn("secrets.RACE_AI_STATE_KEY",cloud)
        self.assertNotIn("actions/upload-artifact",cloud)
        self.assertNotIn("git push --force",cloud)
        self.assertIn("source-root",cloud)
        source_sha="9b875cf9c1d48f8bd31e95fd407a24cf3dcdb330"
        self.assertIn(source_sha,cloud)
        self.assertEqual(y.count(source_sha),4)
        self.assertNotIn("97464792c2af28b39f9ffbe668019fb1482d5a8c",y)
        self.assertIn("result_rows_appended",cloud)
        self.assertIn("result_rows_held",cloud)
        self.assertIn("official_result_independently_authenticated",cloud)
        self.assertIn("RACE_AI_OWNER_AUTO_SOURCE_PROFILE: owner-approved-winticket-keirinjp-20261109",cloud)

    def test_hosted_synthetic_ci_runs_pinned_result_source_regressions(self):
        content=FLOW.read_text(encoding="utf-8")
        synthetic=content.split("\n  synthetic-ci:\n",1)[1].split(
            "\n  public-preflight:\n",1)[0]
        self.assertIn("tests.test_keirin_licensed_result_stage",synthetic)
        self.assertIn("tests.test_keirin_license_api_ingest",synthetic)
        self.assertIn("test_keirin_cloud_pr71_state.py",synthetic)
        self.assertIn("test_keirin_cloud_owner_source_cycle.py",synthetic)
        self.assertIn("tests.test_keirin_prior_private_stage",synthetic)
        self.assertNotIn("secrets.RACE_AI_STATE_KEY",synthetic)
        smoke=synthetic.split("      - name: Main-only owner-approved real source connection",1)[1]
        self.assertIn("if: github.event_name == 'push' && github.ref == 'refs/heads/main'",smoke)
        self.assertIn("trap 'rm -rf",smoke)
        self.assertNotIn("actions/upload-artifact",smoke)

    def test_independent_reader_is_separate_ubuntu_job_and_read_only(self):
        y=FLOW.read_text(encoding="utf-8")
        independent=y.split("\n  independent-cloud-readback:\n",1)[1]
        self.assertIn("needs: github-hosted-pr71-cycle",independent)
        self.assertIn("outputs.committed == 'true'",independent)
        self.assertIn("runs-on: ubuntu-24.04",independent)
        self.assertIn("contents: read",independent)
        self.assertNotIn("contents: write",independent)
        self.assertIn("verify --repo",independent)

    def test_original_codec_and_git_state_reused_with_production_separation(self):
        s=STATE.read_text(encoding="utf-8")
        self.assertIn("from scripts.keirin_github_git_archive import",s)
        self.assertIn("from scripts.keirin_github_sqlite_snapshot import",s)
        self.assertIn("state/keirin/pr71-production/v1",s)
        self.assertIn("FourModelRankLedger",s)
        self.assertIn("stage_existing_owner_pre_races",s)
        self.assertIn("apply_existing_frozen_results",s)
        self.assertIn("result_rows_appended",s)
        self.assertIn("official_result_independently_authenticated",s)
        self.assertIn("STATE_BRANCH",s)
        self.assertIn("RACE_AI_STATE_KEY",s)
        self.assertIn("RACE_AI_EXPECTED_CIPHER_SHA256",s)
        self.assertNotIn("def predict_new_model",s)
        self.assertNotIn("syntheticKey",s)
        self.assertIn("git(tree,\"push\",\"origin\"",s)
        self.assertNotIn("force=True",s)

if __name__=="__main__":
    unittest.main()
