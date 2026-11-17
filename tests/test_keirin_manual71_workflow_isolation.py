"""Static, source-free assertions: main opt-in only; existing production untouched."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / ".github/workflows/keirin-pr71-owner-autonomous.yml"


def job_block(source, name):
    pattern = re.compile(rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-zA-Z][a-zA-Z0-9-]*:\n|\Z)")
    m=pattern.search(source)
    if not m:
        raise AssertionError(f"MISSING_JOB_{name}")
    return m.group(1)


class WorkflowIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wf=FILE.read_text(encoding="utf-8")

    def test_manual_opt_in_is_off_by_default(self):
        pre=self.wf.split("  push:",1)[0]
        self.assertIn("  workflow_dispatch:\n    inputs:\n      manual71_pilot:",pre)
        self.assertRegex(pre, r"manual71_pilot:[\s\S]*?type: boolean[\s\S]*?default: false")

    def test_main_owner_job_requires_explicit_dispatch(self):
        job=job_block(self.wf,"manual71-owner-one-race-preflight")
        self.assertIn("github.repository == 'haji84/RACE-AI'",job)
        self.assertIn("github.ref == 'refs/heads/main'",job)
        self.assertIn("github.event_name == 'workflow_dispatch'",job)
        self.assertIn("inputs.manual71_pilot == true",job)
        self.assertIn("contents: read",job)
        self.assertNotIn("contents: write",job)
        self.assertIn("secrets.RACE_AI_KEIRIN_PRIVATE_RSA_PEM",job)
        self.assertIn("scripts.keirin_manual71_matsuyama7_preflight",job)
        self.assertIn("ref: c52ff0216435b97a0209c43bbe5d0de589445736",job)
        self.assertNotIn("actions/upload-artifact",job)
        self.assertNotIn("gh api",job)
        self.assertNotIn("keirin_cloud_pr71_state",job)

    def test_other_model_jobs_cannot_launch_with_manual_intake_opt_in(self):
        for job_name in ("public-preflight","config_readiness",
                         "github-hosted-pr71-cycle"):
            job=job_block(self.wf,job_name)
            first_lines=job.split("    runs-on:",1)[0]
            self.assertIn("!(github.event_name == 'workflow_dispatch' && inputs.manual71_pilot == true)",first_lines)

    def test_existing_schedule_and_worker_remain(self):
        self.assertIn("cron: '3,33 * * * *'",self.wf)
        self.assertIn("cron: '8,13,18,23,28,38,43,48,53,58 * * * *'",self.wf)
        producer=job_block(self.wf,"github-hosted-pr71-cycle")
        self.assertIn("scripts/keirin_cloud_pr71_state.py",producer)
        self.assertIn("needs: config_readiness",producer)
        self.assertIn("contents: write",producer)
        private_reader=job_block(self.wf,"independent-cloud-readback")
        self.assertIn("needs: github-hosted-pr71-cycle",private_reader)
        self.assertIn("contents: read",private_reader)
        self.assertIn("steps",private_reader)

    def test_pr_ci_has_no_secret_for_RSA_or_approved_provider(self):
        ci=job_block(self.wf,"synthetic-ci")
        self.assertIn("tests.test_keirin_manual71_matsuyama7_preflight",ci)
        self.assertIn("tests.test_keirin_manual71_owner_intake_cli",ci)
        self.assertNotIn("secrets.RACE_AI_KEIRIN_PRIVATE_RSA_PEM",ci)
        self.assertNotIn("secrets.RACE_AI_STATE_KEY",ci)
        self.assertNotIn("workflow_dispatch",ci.split("    runs-on:",1)[0])


if __name__ == "__main__":
    unittest.main()
