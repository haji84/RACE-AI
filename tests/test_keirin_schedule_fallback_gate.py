"""Pure fallback gate tests: no GitHub API, runners, or races are started."""
from datetime import datetime, timezone, timedelta
import unittest

from scripts.keirin_schedule_fallback_gate import decide_fallback


NOW = datetime(2026, 11, 9, 19, 10, tzinfo=timezone.utc)


def run(*, minutes_ago=15, event="schedule",
        status="completed", branch="main",
        path=".github/workflows/keirin-github-autonomous.yml"):
    return {
        "created_at": (NOW - timedelta(minutes=minutes_ago))
                      .isoformat().replace("+00:00", "Z"),
        "event": event,
        "status": status,
        "head_branch": branch,
        "path": path,
    }


class FallbackGateTests(unittest.TestCase):
    def test_recent_main_schedule_blocks_duplicate_wave(self):
        launch, reason = decide_fallback({"workflow_runs": [run()]}, now=NOW)
        self.assertFalse(launch)
        self.assertEqual(reason, "MAIN_SCHEDULE_RECENT")

    def test_no_primary_schedule_in_window_allows_one_backup(self):
        launch, reason = decide_fallback(
            {"workflow_runs": [run(minutes_ago=100)]}, now=NOW)
        self.assertTrue(launch)
        self.assertEqual(reason, "NO_RECENT_MAIN_SCHEDULE")

    def test_active_primary_blocks_even_after_nominal_hour(self):
        launch, reason = decide_fallback(
            {"workflow_runs": [run(minutes_ago=100, status="in_progress")]},
            now=NOW)
        self.assertFalse(launch)
        self.assertEqual(reason, "MAIN_SCHEDULE_ACTIVE")

    def test_unrelated_or_push_runs_never_suppress_backup(self):
        payload = {"workflow_runs": [
            run(event="push"),
            run(path=".github/workflows/boat-racer-daily.yml"),
            run(branch="feat/bad-untrusted-branch"),
        ]}
        launch, reason = decide_fallback(payload, now=NOW)
        self.assertTrue(launch)
        self.assertEqual(reason, "NO_RECENT_MAIN_SCHEDULE")

    def test_missing_or_wrong_schema_never_approves_recording(self):
        for payload in ({}, {"workflow_runs": None},
                        {"workflow_runs": [None]}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    decide_fallback(payload, now=NOW)


if __name__ == "__main__":
    unittest.main()
