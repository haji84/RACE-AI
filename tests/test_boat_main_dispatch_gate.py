"""Source-free acceptance for the canonical BOAT main launcher."""
import base64
from datetime import datetime, timezone
import unittest

from scripts.boat_main_dispatch_gate import (
    decide, RELEASE_REF, RELEASE_SHA, RELEASE_TOKEN, WORKFLOW
)

NOW = datetime(2026, 11, 11, 0, 10, tzinfo=timezone.utc)


def release(sha=RELEASE_SHA):
    return {"ref": "refs/heads/" + RELEASE_REF, "object": {"sha": sha}}


def source_doc(text):
    return {"encoding": "base64", "content": base64.b64encode(
        text.encode("utf8")).decode("ascii")}


def history(*runs, total=None):
    return {"workflow_runs": list(runs), "total_count": len(runs) if total is None else total}


class BoatOwnerLauncherGateTests(unittest.TestCase):
    def decide(self, *, sha=RELEASE_SHA, src=RELEASE_TOKEN, runs=None):
        return decide(now=NOW, release=release(sha),
                      owner_doc=source_doc(src),
                      history=history(*(runs or [])))

    def test_no_source_owner_release_keeps_existing_fixed_boundary(self):
        for doc in (
            RELEASE_TOKEN + " ACTIVE_FULL_FIRST_TO_FIXED_ATTEMPT_TWO_BOUNDARY",
            "CODE_ONLY_NO_SOURCE",
        ):
            value=self.decide(src=doc)
            self.assertFalse(value["dispatch_allowed"])
            self.assertEqual(value["status"], "HOLD_SOURCE_OWNER_FIXED_BOUNDARY_NOT_RELEASED")
            self.assertFalse(value["future_real_forecast_proven"])
            self.assertFalse(value["official_results_reconciled"])

    def test_newer_formal_release_does_not_delete_historical_holds(self):
        result=self.decide(src="ACTIVE_FULL_FIRST_TO_FIXED_ATTEMPT_TWO_BOUNDARY\\n"
                               + RELEASE_TOKEN)
        self.assertTrue(result["dispatch_allowed"])
        self.assertEqual(result["status"], "READY_EXISTING_OWNER_WORKFLOW_ONLY")

    def test_release_sha_must_be_exact_not_mutable_branch_alias(self):
        value=self.decide(sha="0"*40)
        self.assertEqual(value["status"], "HOLD_RELEASE_SHA_MISMATCH")
        self.assertFalse(value["dispatch_allowed"])

    def test_positive_owner_release_and_new_day_allows_existing_workflow(self):
        value=self.decide()
        self.assertEqual(value["status"], "READY_EXISTING_OWNER_WORKFLOW_ONLY")
        self.assertTrue(value["dispatch_allowed"])
        self.assertEqual(value["official_source_requests"], 0)

    def test_duplicate_same_day_owner_run_never_issued_twice(self):
        existing={"name": WORKFLOW, "head_branch": RELEASE_REF,
                  "created_at": "2026-11-11T00:01:00Z", "status": "completed"}
        result=self.decide(runs=[existing])
        self.assertEqual(result["status"], "HOLD_ALREADY_DISPATCHED_FOR_JST_DAY")

    def test_yesterday_does_not_block_new_day(self):
        existing={"name": WORKFLOW,"head_branch":RELEASE_REF,
                  "created_at":"2026-11-10T05:00:00Z"}
        self.assertTrue(self.decide(runs=[existing])["dispatch_allowed"])

    def test_existing_boat_result_polling_times_are_unchanged(self):
        from pathlib import Path
        source=(Path(__file__).resolve().parents[1]/
                ".github/workflows/boat-racer-daily.yml").read_text()
        self.assertIn("cron: '2-59/5 0-14 * * *'", source)
        self.assertIn("cron: '2-59/5 22-23 * * *'", source)
        self.assertIn("cron: '20 21 * * *'", source)
        self.assertNotIn("cron: '2-59/5 0-14,22-23 * * *'", source)
        # 15 hours + 2 hours. Identical minute values in each hour:
        minute_set=set(range(2,60,5))
        self.assertEqual(len(minute_set),12)
        self.assertEqual(len(minute_set)*(15+2),204)
        launcher=source.split("  owner_p0_p1_dispatch:\n",1)[1]
        self.assertIn("github.event.schedule == '2-59/5 22-23 * * *'", launcher)
        self.assertNotIn("github.event.schedule == '2-59/5 0-14 * * *'", launcher)
        self.assertIn("group: boat-main-launcher-source-free", launcher)
        self.assertIn("actions: write", launcher)
        self.assertNotIn("racer_intraday_refresh",launcher)

    def test_overnight_active_owner_run_blocks_another_writer(self):
        previous={"name": WORKFLOW, "head_branch": RELEASE_REF,
                  "created_at": "2026-11-10T23:01:00Z",
                  "status": "in_progress"}
        # Previous in JST? 23:01 UTC is already next JST date.
        previous["created_at"] = "2026-11-10T14:55:00Z"
        value=self.decide(runs=[previous])
        self.assertEqual(value["status"], "HOLD_ACTIVE_OWNER_WORKFLOW")
        self.assertFalse(value["dispatch_allowed"])

    def test_ordered_hundred_old_runs_cover_current_day_despite_pagination(self):
        from datetime import timedelta
        from scripts.boat_main_dispatch_gate import decide
        last=datetime(2026,11,10,14,0,tzinfo=timezone.utc)
        rows=[{"name":WORKFLOW,"head_branch":RELEASE_REF,
               "created_at":(last-timedelta(days=i)).isoformat(),
               "status":"completed"} for i in range(100)]
        result=decide(now=NOW,release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                      history=history(*rows,total=101))
        self.assertEqual(result["status"],"READY_EXISTING_OWNER_WORKFLOW_ONLY")
        self.assertTrue(result["dispatch_allowed"])

    def test_pagination_with_recent_unseen_run_stays_hold(self):
        from datetime import timedelta
        from scripts.boat_main_dispatch_gate import decide
        newest=NOW-timedelta(minutes=3)
        rows=[{"name":WORKFLOW,"head_branch":RELEASE_REF,
               "created_at":(newest-timedelta(seconds=5*i)).isoformat(),
               "status":"completed"} for i in range(100)]
        result=decide(now=NOW,release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                      history=history(*rows,total=101))
        self.assertEqual(result["status"],"HOLD_INCOMPLETE_RUN_HISTORY")
        self.assertFalse(result["dispatch_allowed"])

    def test_out_of_order_run_metadata_never_proves_history_complete(self):
        from scripts.boat_main_dispatch_gate import decide
        rows=[{"name":WORKFLOW,"head_branch":RELEASE_REF,
               "created_at":at,"status":"completed"} for at in (
                 "2026-11-10T02:00:00Z","2026-11-10T03:00:00Z")]
        result=decide(now=NOW,release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                      history=history(*rows))
        self.assertEqual(result["status"],"HOLD_INCOMPLETE_RUN_HISTORY")

    def test_one_shot_owner_push_reuses_existing_main_workflow(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        workflow=(root/".github/workflows/boat-racer-daily.yml").read_text()
        self.assertIn("docs/evidence/owner-pdca-main-trigger.txt", workflow)
        launcher=workflow.split("  owner_p0_p1_dispatch:\n",1)[1]
        self.assertIn("github.event_name == 'push'", launcher)
        self.assertIn("boat-owner-release: single-real-session-20261111", launcher)
        self.assertIn("github.ref == 'refs/heads/main'", launcher)
        self.assertIn("steps.owner_gate.outputs.ready == 'true'", launcher)
        self.assertIn("--ref production/boat-p0-p1-20261111", launcher)
        self.assertIn("production_scope=existing-owner-p0-p1", launcher)
        self.assertIn("group: boat-main-launcher-source-free", launcher)
        self.assertIn("cancel-in-progress: false", launcher)
        self.assertIn("actions: write", launcher)
        self.assertNotIn("racer_intraday_refresh", launcher)
        self.assertNotIn("scripts.boat_pdca_github", launcher)
        # Existing collector and main result scorer remain separate jobs.
        self.assertEqual(workflow.count("  daily:"),1)
        self.assertEqual(workflow.count("  source_mirror:"),1)

    def test_unreturned_pagination_is_not_no_forecast(self):
        output=decide(now=NOW, release=release(),
            owner_doc=source_doc(RELEASE_TOKEN), history=history(total=101))
        self.assertEqual(output["status"], "HOLD_INCOMPLETE_RUN_HISTORY")
        self.assertFalse(output["dispatch_allowed"])


if __name__ == "__main__":
    unittest.main()
