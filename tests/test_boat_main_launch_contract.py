"""Source-free guard for one MAIN BOAT production entry.

Only static workflow structure is tested. A passed contract cannot certify
a future forecast, official source permission, or an independent result match.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / ".github/workflows/boat-racer-daily.yml").read_text()
REGISTRATION = (ROOT / ".github/workflows/boat-nationwide-ab-one-shot.yml").read_text()


class CanonicalBoatLaunchContract(unittest.TestCase):
    def test_default_branch_is_registration_only(self):
        self.assertIn("  workflow_dispatch:", REGISTRATION)
        self.assertIn("existing-owner-p0-p1", REGISTRATION)
        self.assertIn("reject_default_branch_execution:", REGISTRATION)
        self.assertIn("github.ref == 'refs/heads/main'", REGISTRATION)
        self.assertIn("exit 1", REGISTRATION)
        self.assertNotIn("official_national:", REGISTRATION)
        self.assertNotIn("boat_all_model_cycle", REGISTRATION)

    def test_same_existing_main_schedule_has_exactly_one_launcher(self):
        self.assertEqual(MAIN.count("  canonical_owner_p0_p1_dispatch:"), 1)
        launch = MAIN.split("  canonical_owner_p0_p1_dispatch:\n", 1)[1].split(
            "  mirror_contract:\n", 1)[0]
        self.assertIn("github.event.schedule == '20 21 * * *'", launch)
        self.assertIn("refs/heads/main", launch)
        self.assertIn("boat-canonical-owner-dispatch-main", launch)
        self.assertIn("actions: write", launch)
        self.assertIn("contents: read", launch)
        self.assertIn("HOLD_BOAT_OWNER_FIXED_SOURCE_BOUNDARY", launch)
        self.assertIn("exit 78", launch)
        self.assertIn("RACE_AI_BOAT_OWNER_SOURCE_RELEASE_APPROVED", launch)
        self.assertIn("SKIP_EXISTING_SAME_DAY_OWNER_DISPATCH", launch)
        self.assertIn("workflow run boat-nationwide-ab-one-shot.yml", launch)
        self.assertIn("production_scope=existing-owner-p0-p1", launch)
        self.assertIn("BOAT_OWNER_DISPATCH_REQUESTED_NOT_FORECAST_PROVEN", launch)
        self.assertNotIn("RACE_AI_STATE_KEY", launch)
        self.assertNotIn("racer_intraday_refresh", launch)
        self.assertNotIn("boat_all_model_cycle", launch)

    def test_source_mirror_and_result_reader_accept_only_trusted_same_owner(self):
        header = MAIN.split("jobs:\n", 1)[0]
        self.assertIn("production/boat-p0-p1-20261111", header)
        mirror = MAIN.split("  source_mirror:\n", 1)[1].split("  daily:\n", 1)[0]
        daily = MAIN.split("  daily:\n", 1)[1]
        for section in (mirror, daily):
            self.assertIn("github.event.workflow_run.event == 'push'", section)
            self.assertIn("github.event.workflow_run.event == 'workflow_dispatch'", section)
            self.assertIn("github.event.workflow_run.conclusion == 'success'", section)
            self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", section)
            self.assertIn("github.event.workflow_run.head_branch == 'production/boat-p0-p1-20261111'", section)
        # The original mirrored result/PDCA job remains authoritative.
        self.assertIn("scripts.boat_source_control_mirror import main", mirror)
        self.assertIn("python -m scripts.racer_intraday_refresh", daily)
        self.assertIn("python -m scripts.verify_all_history_pdca_readback", daily)
        self.assertIn("ref: 761247bee0209e37b1af6b8885e92cad3e9260a5", daily)
        self.assertIn("ref: 7a432e5acc4d3495a0e82bd79726929e2f8085fe", daily)
        self.assertNotIn("python -m scripts.new_result_scorer", MAIN)

    def test_permissions_not_granted_to_existing_result_jobs(self):
        launch = MAIN.split("  canonical_owner_p0_p1_dispatch:\n", 1)[1].split(
            "  mirror_contract:\n", 1)[0]
        self.assertIn("actions: write", launch)
        for header in ("  mirror_contract:", "  source_mirror:", "  daily:"):
            block = MAIN.split(header + "\n", 1)[1]
            self.assertNotIn("actions: write", block.split("\n  ", 1)[0])
        # Prevent importing private branch-only code into public default.
        self.assertEqual(MAIN.count("workflow run boat-nationwide-ab-one-shot.yml"), 1)


if __name__ == "__main__":
    unittest.main()
