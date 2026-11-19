"""Wiring guards for GitHub-only nationwide replay capture fallback.

These tests run without footage, credentials, network access, or a runner
dispatch. A green test proves YAML intent, not that a GitHub schedule fired.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / ".github/workflows/keirin-github-autonomous.yml"
CANARY = ROOT / ".github/workflows/keirin-personal-hourly-canary.yml"


class GitHubScheduleFallbackContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = MAIN.read_text(encoding="utf-8")
        cls.canary = CANARY.read_text(encoding="utf-8")

    def test_recording_workflow_is_reusable_only_with_explicit_mode(self):
        self.assertIn("  workflow_call:\n    inputs:\n      mode:", self.main)
        self.assertRegex(
            self.main,
            r"workflow_call:\s+inputs:\s+mode:\s+required: true\s+type: string",
        )
        self.assertIn("github.event_name == 'schedule' && inputs.mode == 'capture'", self.main)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.mode == 'capture'", self.main)

    def test_existing_hourly_canary_calls_same_capture_worker_only_on_schedule(self):
        self.assertIn("  actions: read", self.canary)
        self.assertIn("  fallback_scheduling_gate:", self.canary)
        self.assertIn("python -m scripts.keirin_schedule_fallback_gate", self.canary)
        self.assertIn("needs: fallback_scheduling_gate", self.canary)
        self.assertIn("needs.fallback_scheduling_gate.outputs.should_capture == 'true'", self.canary)
        self.assertIn(
            "uses: ./.github/workflows/keirin-github-autonomous.yml",
            self.canary,
        )
        self.assertRegex(
            self.canary, r"fallback_nationwide_capture:[\s\S]*?with:\s*mode: capture"
        )
        self.assertIn("secrets: inherit", self.canary)

    def test_shared_concurrency_prevents_parallel_recording_waves(self):
        self.assertIn("group: keirin-github-independent-main", self.main)
        self.assertIn("cancel-in-progress: false", self.main)
        self.assertIn("temporary-artifact-receipts.json", self.main)

    def test_no_private_storage_must_not_look_like_success(self):
        self.assertRegex(
            self.main,
            r'if \[ -z "\$ARCHIVE_BUCKET" \]; then\s+'
            r'echo "DURABLE_PRIVATE_STORAGE_NOT_CONFIGURED"[^\n]*\n\s+exit 1',
        )
        self.assertIn("keirin_github_private_s3_archive", self.main)
        self.assertIn("owner-durable-readback.json", self.main)


if __name__ == "__main__":
    unittest.main()
