"""Review-gated one-time bootstrap cannot silently expand production permissions.

All tests are static. They never dispatch Actions, read secrets or fetch a race.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / ".github/workflows/keirin-pr71-one-shot-bootstrap.yml"
PRODUCER = ROOT / ".github/workflows/keirin-pr71-owner-autonomous.yml"


class OneShotBootstrapGuard(unittest.TestCase):
    def setUp(self):
        self.text = FLOW.read_text(encoding="utf-8")
        self.assertTrue(PRODUCER.is_file())
        self.pr, self.once = self.text.split("\n  one-time-dispatch:\n", 1)

    def test_one_shot_must_be_from_owner_main_exact_optin(self):
        body = self.once
        self.assertIn("github.event_name == 'push'", body)
        self.assertIn("github.repository == 'haji84/RACE-AI'", body)
        self.assertIn("github.ref == 'refs/heads/main'", body)
        self.assertIn("github.actor == 'haji84'", body)
        self.assertIn("one-shot-PR71-bootstrap-20261110", body)
        self.assertIn('"$remote_sha" != "$GITHUB_SHA"', body)
        self.assertIn("HOLD_MAIN_MOVED_BEFORE_DIAGNOSTIC", body)
        self.assertIn("HOLD_PR71_WORKFLOW_NOT_ACTIVE", body)
        self.assertNotIn("github.event_name == 'pull_request'", body)

    def test_sensitive_permissions_only_in_push_job(self):
        self.assertIn("permissions:\n  contents: read\n", self.text)
        self.assertNotIn("actions: write", self.pr)
        self.assertIn("actions: write", self.once)
        self.assertIn("GH_TOKEN:", self.once)
        self.assertIn("github.token", self.once)
        self.assertNotIn("secrets.RACE_AI_STATE_KEY", self.text)
        self.assertNotIn("secrets.RACE_AI_KEIRIN_", self.text)
        self.assertNotIn("self-hosted", self.text)
        self.assertNotIn("pull_request_target:", self.text)

    def test_single_existing_producer_and_no_recurring_dispatch(self):
        self.assertIn("on:\n  pull_request:", self.text)
        self.assertIn("  push:\n    branches: [main]", self.text)
        self.assertEqual(
            self.text.count("      - '.github/workflows/keirin-pr71-one-shot-bootstrap.yml'"), 2
        )
        self.assertNotIn("  schedule:\n", self.text)
        self.assertNotIn("  workflow_dispatch:\n", self.text)
        self.assertEqual(
            self.once.count("actions/workflows/keirin-pr71-owner-autonomous.yml/dispatches"), 1
        )
        self.assertIn("-f ref=main --silent", self.once)
        self.assertIn("gh api --method POST", self.once)
        self.assertNotIn("git push", self.text)

    def test_existing_production_security_gate_unchanged(self):
        current = PRODUCER.read_text(encoding="utf-8")
        self.assertIn("github.ref == 'refs/heads/main'", current)
        self.assertIn("github.event_name == 'schedule'", current)
        self.assertIn("github.event_name == 'workflow_dispatch'", current)
        self.assertIn("needs.github-hosted-pr71-cycle.outputs.committed == 'true'", current)
        self.assertNotIn("github.event_name == 'push' || github.event_name == 'workflow_dispatch'", current)


if __name__ == "__main__":
    unittest.main()
