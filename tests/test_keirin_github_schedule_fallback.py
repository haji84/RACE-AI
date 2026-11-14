"""Wiring guards for GitHub-only nationwide replay capture fallback.

These tests run without footage, credentials, network access, or a runner
dispatch. A green test proves YAML intent, not that a GitHub schedule fired.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import textwrap
import unittest
from tempfile import TemporaryDirectory

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

    def test_zero_clips_avoid_false_s3_failure_but_never_claim_archive(self):
        archive = self.main.split(
            '      - name: Owner-private S3 upload must fail visibly if configured and readback fails',1
        )[1].split('      - name: Report actual capture, source unknowns and durability separately',1)[0]
        self.assertIn('CAPTURE_REPORT_REQUIRED_BEFORE_ARCHIVE',archive)
        self.assertIn('INVALID_ENCRYPTED_VIDEO_COUNT',archive)
        self.assertIn('HOLD_NO_ENCRYPTED_VIDEO_TO_ARCHIVE',archive)
        zero = archive.index('if [ "$verified_clips" = "0" ]; then')
        storage = archive.index('if [ -z "$ARCHIVE_BUCKET" ]; then')
        self.assertLess(zero,storage)
        self.assertIn('exit 0',archive[zero:storage])
        self.assertIn('exit 1',archive[storage:])
        self.assertNotIn('DURABLE_CIPHERTEXT_READBACK_VERIFIED',archive[zero:storage])

    def _execute_existing_archive_shell_without_provider(self, count):
        # Execute the *actual workflow shell*, not a duplicated Python policy.
        # All branches here stop before pip/aws, so no network or secrets.
        from pathlib import Path
        archive = self.main.split(
            '      - name: Owner-private S3 upload must fail visibly if configured and readback fails',1
        )[1].split('      - name: Report actual capture, source unknowns and durability separately',1)[0]
        script = textwrap.dedent(archive.split('        run: |\n',1)[1])
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'keirin-daily-wave.json').write_text(
                json.dumps({'encrypted':count}),encoding='utf-8')
            summary=root/'summary.md'
            env={**os.environ, 'RUNNER_TEMP':tmp,
                 'GITHUB_STEP_SUMMARY':str(summary),'ARCHIVE_BUCKET':''}
            run=subprocess.run(['bash','-c',script],env=env,
                               capture_output=True,text=True,timeout=10)
            return run.returncode,summary.read_text() if summary.exists() else '',run.stderr

    def test_actual_zero_clip_shell_holds_without_false_s3_failure(self):
        code,summary,err=self._execute_existing_archive_shell_without_provider(0)
        self.assertEqual(code,0,err)
        self.assertIn('HOLD_NO_ENCRYPTED_VIDEO_TO_ARCHIVE',summary)
        self.assertNotIn('DURABLE_PRIVATE_STORAGE_NOT_CONFIGURED',summary)

    def test_actual_positive_clip_shell_requires_real_private_storage(self):
        code,summary,err=self._execute_existing_archive_shell_without_provider(1)
        self.assertNotEqual(code,0)
        self.assertIn('DURABLE_PRIVATE_STORAGE_NOT_CONFIGURED',summary)
        self.assertNotIn('HOLD_NO_ENCRYPTED_VIDEO_TO_ARCHIVE',summary)

    def test_actual_invalid_clip_report_must_fail_closed(self):
        code,summary,err=self._execute_existing_archive_shell_without_provider('1')
        self.assertNotEqual(code,0)
        self.assertIn('INVALID_ENCRYPTED_VIDEO_COUNT',err)
        self.assertNotIn('HOLD_NO_ENCRYPTED_VIDEO_TO_ARCHIVE',summary)

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
