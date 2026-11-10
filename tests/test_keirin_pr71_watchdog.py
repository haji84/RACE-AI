"""No-network regression for recurring PR71 main-only schedule fallback."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from scripts.keirin_pr71_watchdog import inspect_workflow_runs, WatchdogError

ROOT = Path(__file__).resolve().parents[1]
WATCHDOG = ROOT / ".github/workflows/keirin-pr71-watchdog.yml"
PRODUCER = ROOT / ".github/workflows/keirin-pr71-owner-autonomous.yml"
FIXED = datetime(2026, 11, 10, 4, 0, tzinfo=timezone.utc)


def run(*, minutes_ago=10, event="schedule", status="completed",
        branch="main", run_id=1):
    return {
        "id": run_id,
        "event": event,
        "head_branch": branch,
        "status": status,
        "created_at": (FIXED-timedelta(minutes=minutes_ago)).isoformat(),
    }


def result(*rows, total=None):
    return inspect_workflow_runs({
        "total_count": len(rows) if total is None else total,
        "workflow_runs": list(rows),
    }, now=FIXED)


class WatchdogDecisionTests(unittest.TestCase):
    def test_empty_schedule_and_dispatch_runs_trigger_one_backup(self):
        report = result()
        self.assertEqual(report["decision"], "DISPATCH_MISSING_TRUSTED_PRODUCER")
        self.assertEqual(report["active_main_producer_runs"], 0)
        self.assertFalse(report["real_forecast_claimed"])

    def test_unobserved_five_minute_ticks_are_not_successes(self):
        record = result()
        audit = record["source_free_schedule_audit"]
        self.assertEqual(audit["lookback_minutes"], 35)
        self.assertEqual(audit["grace_minutes"], 3)
        self.assertEqual(audit["nominal_five_minute_ticks"], 6)
        self.assertEqual(audit["schedule_runs_observed"], 0)
        self.assertEqual(audit["nominal_ticks_without_observed_event"], 6)
        self.assertTrue(audit["history_page_complete"])
        self.assertFalse(audit["scheduler_root_cause_proven"])
        self.assertFalse(audit["actual_start_or_forecast_proven"])

    def test_scheduled_and_manually_triggered_runs_not_conflated(self):
        record = result(
            run(minutes_ago=10, event="schedule", run_id=1),
            run(minutes_ago=20, event="workflow_dispatch", run_id=2),
        )
        audit = record["source_free_schedule_audit"]
        self.assertEqual(audit["schedule_runs_observed"], 1)
        self.assertEqual(audit["manual_dispatch_runs_observed"], 1)
        self.assertEqual(audit["nominal_ticks_without_observed_event"], 5)

    def test_incomplete_github_history_never_claims_missing_ticks(self):
        record = result(run(minutes_ago=10), total=55)
        audit = record["source_free_schedule_audit"]
        self.assertFalse(audit["history_page_complete"])
        self.assertIsNone(audit["nominal_ticks_without_observed_event"])

    def test_recent_main_primary_schedule_skips_backup(self):
        self.assertEqual(
            result(run(minutes_ago=10))["decision"],
            "SKIP_RECENT_TRUSTED_PRODUCER"
        )

    def test_missed_5min_windows_dispatch_even_before_old_26min_threshold(self):
        self.assertEqual(result(run(minutes_ago=13))["decision"],
                         "DISPATCH_MISSING_TRUSTED_PRODUCER")
        self.assertEqual(result(run(minutes_ago=26))["decision"],
                         "DISPATCH_MISSING_TRUSTED_PRODUCER")

    def test_recent_main_workflow_dispatch_also_skips_backup(self):
        self.assertEqual(
            result(run(minutes_ago=5, event="workflow_dispatch"))["decision"],
            "SKIP_RECENT_TRUSTED_PRODUCER"
        )

    def test_active_producer_is_not_started_again_even_if_old(self):
        self.assertEqual(
            result(run(minutes_ago=120, status="in_progress"))["decision"],
            "HOLD_ACTIVE_TRUSTED_PRODUCER"
        )

    def test_old_completed_run_is_not_current_coverage(self):
        self.assertEqual(
            result(run(minutes_ago=27))["decision"],
            "DISPATCH_MISSING_TRUSTED_PRODUCER"
        )

    def test_pull_request_and_push_ci_never_count_as_real_cycle(self):
        r = result(
            run(minutes_ago=1, event="push", run_id=1),
            run(minutes_ago=2, event="pull_request", run_id=2),
            run(minutes_ago=7, branch="other", run_id=3),
        )
        self.assertEqual(r["decision"], "DISPATCH_MISSING_TRUSTED_PRODUCER")
        self.assertEqual(r["trusted_main_producer_runs_examined"], 0)

    def test_invalid_remote_metadata_fails_closed(self):
        with self.assertRaises(WatchdogError):
            inspect_workflow_runs({"total_count": 1, "workflow_runs": []}, now=FIXED)
        with self.assertRaises(WatchdogError):
            result(run(minutes_ago=-5))
        with self.assertRaises(WatchdogError):
            result({"id": 1, "event": "schedule", "head_branch": "main",
                    "created_at": "not-a-timestamp", "status": "completed"})
        with self.assertRaises(WatchdogError):
            result({"id": 1, "event": "schedule", "head_branch": "main",
                    "created_at": FIXED.isoformat(), "status": "unknown"})


class WatchdogAccessBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.workflow = WATCHDOG.read_text(encoding="utf-8")
        self.producer = PRODUCER.read_text(encoding="utf-8")
        self.public_job, self.privileged = self.workflow.split(
            "\n  trusted-fallback:\n", 1)

    def test_expected_schedules_and_trusted_completion_only(self):
        text = self.workflow
        self.assertIn("25,55 * * * *", text)
        self.assertIn("workflow_run:", text)
        self.assertIn("KEIRIN hourly personal research canary", text)
        for check in (
            "github.event.workflow_run.event == 'schedule'",
            "github.event.workflow_run.conclusion == 'success'",
            "github.event.workflow_run.head_branch == 'main'",
            "github.event.workflow_run.head_repository.full_name == 'haji84/RACE-AI'",
            "github.ref == 'refs/heads/main'",
            "github.repository == 'haji84/RACE-AI'",
        ):
            self.assertIn(check, text)

    def test_single_dispatch_never_runs_from_untrusted_pr(self):
        self.assertIn("github.event_name == 'pull_request'", self.public_job)
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertNotIn("actions: write", self.public_job)
        self.assertIn("actions: write", self.privileged)
        self.assertIn("github.event_name == 'push'", self.privileged)
        self.assertNotIn("github.event_name == 'pull_request'", self.privileged)
        self.assertNotIn("pull_request_target:", self.workflow)
        self.assertEqual(
            self.privileged.count("actions/workflows/keirin-pr71-owner-autonomous.yml/dispatches"),
            1)
        self.assertIn("group: keirin-pr71-monitored-watchdog-main", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)
        self.assertIn("DISPATCH_MISSING_TRUSTED_PRODUCER", self.privileged)
        self.assertIn("HOLD_PR71_WORKFLOW_NOT_ACTIVE", self.privileged)
        self.assertIn("HOLD_MAIN_MOVED_NO_PRODUCER_DISPATCH", self.privileged)
        self.assertEqual(self.privileged.count("if: steps.main-preflight.outputs.eligible == 'true'"), 2)

    def test_no_secret_access_vendor_network_or_new_predictor(self):
        self.assertNotIn("secrets.", self.workflow)
        self.assertNotIn("self-hosted", self.workflow)
        self.assertNotIn("curl ", self.workflow)
        self.assertNotIn("winticket.jp", self.workflow)
        self.assertNotIn("keirin.jp", self.workflow)
        self.assertNotIn("RACE_AI_STATE_KEY", self.workflow)
        self.assertNotIn("model_weights", self.workflow)
        self.assertIn("gh api", self.workflow)

    def test_existing_main_producer_safety_unchanged(self):
        self.assertIn("3,33 * * * *", self.producer)
        self.assertIn("8,13,18,23,28,38,43,48,53,58 * * * *", self.producer)
        self.assertIn("needs: config_readiness", self.producer)
        self.assertIn("github.ref == 'refs/heads/main'", self.producer)
        self.assertIn("github.event_name == 'schedule'", self.producer)
        self.assertIn("github.event_name == 'workflow_dispatch'", self.producer)
        self.assertIn("needs.github-hosted-pr71-cycle.outputs.committed == 'true'", self.producer)


if __name__ == "__main__":
    unittest.main()
