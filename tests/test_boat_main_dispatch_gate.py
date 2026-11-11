"""Source-free acceptance for the canonical BOAT main launcher."""
import base64
from datetime import datetime, timezone
import unittest

from scripts.boat_main_dispatch_gate import (
    decide, RELEASE_REF, RELEASE_SHA, RELEASE_TOKEN, WORKFLOW,
    FIRST_FAILED_ID, FIRST_FAILED_SHA
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
                  "event":"workflow_dispatch",
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
        self.assertIn("github.event.schedule == '2-59/5 0-14 * * *'", launcher)
        self.assertIn("--owner-release-root boat-owner-release", launcher)
        self.assertIn("RACE_AI_STATE_KEY: ${{ secrets.RACE_AI_STATE_KEY }}", launcher)
        self.assertIn("group: boat-main-launcher-source-free", launcher)
        self.assertIn("actions: write", launcher)
        self.assertNotIn("racer_intraday_refresh",launcher)

    def test_overnight_active_owner_run_blocks_another_writer(self):
        previous={"name": WORKFLOW, "head_branch": RELEASE_REF,
                  "event":"workflow_dispatch",
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
        self.assertEqual(workflow.splitlines().count("  daily:"),1)
        self.assertEqual(workflow.splitlines().count("  source_mirror:"),1)

    def _previous_pre_source_run_and_proof(self):
        at="2026-11-11T09:13:07Z"
        row=dict(id=FIRST_FAILED_ID,name=WORKFLOW,
                 head_branch=RELEASE_REF,event="workflow_dispatch",
                 status="completed",conclusion="failure",created_at=at)
        skipped=(
            "Check all earlier same-day receipts before first P0",
            "Authenticate the requested grid before any bootstrap source GET",
            "Obtain first P0 from verified official B only if truly absent",
            "Save first P0 separately before reading results",
            "Execute new-day P0 families from the authenticated first receipt",
            "Freeze additional new-day P0 as owner ciphertext",
            "Wait without source requests for the authenticated exhibition window",
            "Initialize continuous source session and account for initial B GET",
            "Deadline-ordered five-model round 01",
        )
        steps=[{"name":f"Placeholder source-free prep {i}", "conclusion":"success"}
               for i in range(61)]
        steps.append({"name":"Test originals, pending results, tampering and unchanged models",
                      "conclusion":"failure"})
        steps.extend({"name":name,"conclusion":"skipped"} for name in skipped)
        proof=dict(run={**row,"head_sha":FIRST_FAILED_SHA},
            jobs={"total_count":1,"jobs":[{
                "name":"Existing frozen P0, exhibition P1, separate official results and PDCA",
                "conclusion":"failure","steps":steps}]},
            artifacts={"total_count":1,"artifacts":[{
                "name":"existing-cycle-source-42993305843"}]})
        return row,proof

    def test_one_attested_pre_source_failure_can_retry_without_any_original(self):
        row,proof=self._previous_pre_source_run_and_proof()
        ci=dict(name=WORKFLOW,head_branch=RELEASE_REF,event="pull_request",
                created_at="2026-11-11T09:17:51Z",status="completed",
                conclusion="success")
        value=decide(now=datetime(2026,11,11,9,30,tzinfo=timezone.utc),
                     release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                     history=history(ci,row),retry_proof=proof)
        self.assertEqual(value["status"],"READY_RETRY_AFTER_VERIFIED_PRE_SOURCE_FAILURE")
        self.assertTrue(value["dispatch_allowed"])
        self.assertEqual(value["official_source_requests"],0)
        self.assertFalse(value["future_real_forecast_proven"])

    def test_preplace_failure_proof_cannot_be_faked_or_reused(self):
        from copy import deepcopy
        row,proof=self._previous_pre_source_run_and_proof()
        now=datetime(2026,11,11,9,30,tzinfo=timezone.utc)
        def verdict(evidence,records=None):
            return decide(now=now,release=release(),owner_doc=source_doc(RELEASE_TOKEN),
                          history=history(*(records or [row])),retry_proof=evidence)
        for corrupt in (
            lambda p:p["artifacts"]["artifacts"].append({"name":"boat-p0-existing-fake"}),
            lambda p:p["artifacts"].update(total_count=5),
            lambda p:p["run"].update(head_sha="0"*40),
            lambda p:p["run"].update(conclusion="success"),
            lambda p:p["jobs"]["jobs"][0]["steps"][-1].update(conclusion="success"),
            lambda p:p["jobs"].update(total_count=10),
        ):
            tmp=deepcopy(proof)
            corrupt(tmp)
            self.assertFalse(verdict(tmp)["dispatch_allowed"])
        second={**row,"id":42994444444,"created_at":"2026-11-11T09:25:00Z",
                "conclusion":"failure"}
        self.assertEqual(verdict(proof,[second,row])["status"],
                         "HOLD_ALREADY_DISPATCHED_FOR_JST_DAY")
        self.assertFalse(verdict(None)["dispatch_allowed"])

    def test_unreturned_pagination_is_not_no_forecast(self):
        output=decide(now=NOW, release=release(),
            owner_doc=source_doc(RELEASE_TOKEN), history=history(total=101))
        self.assertEqual(output["status"], "HOLD_INCOMPLETE_RUN_HISTORY")
        self.assertFalse(output["dispatch_allowed"])


class AuthenticatedSameDayContinuationTests(unittest.TestCase):
    """No earlier source session is retried without AES-authenticated evidence."""

    @staticmethod
    def owner(ident, *, created="2026-11-11T00:02:00Z", conclusion="success",
              status="completed", sha=RELEASE_SHA):
        return dict(id=ident, name=WORKFLOW, head_branch=RELEASE_REF,
                    head_sha=sha, event="workflow_dispatch", created_at=created,
                    status=status, conclusion=conclusion)

    @staticmethod
    def proof(ident, *, day="2026-11-11", reason="BOUNDED_SESSION_END",
              total=90, base=0):
        return dict(status="AUTHENTICATED_EXISTING_OWNER_FINAL_CONTROL",
                    source_run_id=ident, source_sha=RELEASE_SHA,
                    day_jst=day, previous_stop_reason=reason, source_wait=None,
                    prepared_round=None, lifetime_requests=total,
                    day_start_lifetime_requests=base,
                    continuity_artifact_id=177, source_control_artifact_id=178)

    def judge(self, *runs, proof=None):
        from scripts.boat_main_dispatch_gate import decide
        return decide(now=NOW, release=release(), owner_doc=source_doc(RELEASE_TOKEN),
                      history=history(*runs), resume_proof=proof)

    def test_valid_immutable_checkpoint_allows_one_more_existing_owner_worker(self):
        current=self.owner(101)
        result=self.judge(current,proof=self.proof(101))
        self.assertTrue(result["dispatch_allowed"])
        self.assertEqual(result["status"],"READY_AUTHENTICATED_SAME_DAY_CONTINUATION")
        self.assertFalse(result["future_real_forecast_proven"])
        self.assertEqual(result["official_source_requests"],0)

    def test_multiple_completed_successors_use_only_latest_authentic_checkpoint(self):
        earlier=self.owner(101,created="2026-11-11T00:02:00Z")
        latest=self.owner(102,created="2026-11-11T00:04:00Z")
        self.assertTrue(self.judge(latest,earlier,proof=self.proof(102))["dispatch_allowed"])
        self.assertFalse(self.judge(latest,earlier,proof=self.proof(101))["dispatch_allowed"])

    def test_missing_or_inconsistent_proof_or_source_halt_never_restarts(self):
        from copy import deepcopy
        target=self.owner(101)
        for changed in (
            {"status": "NOT_ATTESTED"}, {"source_run_id": 102},
            {"source_sha": "a"*40}, {"day_jst": "2026-11-10"},
            {"previous_stop_reason": "DAY_HANDOFF"},
            {"previous_stop_reason": "SOURCE_VERIFICATION_REQUIRED"},
            {"previous_stop_reason": "SESSION_SOURCE_BUDGET_EXHAUSTED"},
            {"source_wait": {"state": "RATE_LIMIT_WAIT"}},
            {"prepared_round": 1}, {"lifetime_requests": 239},
            {"day_start_lifetime_requests": None}, {"day_start_lifetime_requests": -1},
            {"lifetime_requests": 100, "day_start_lifetime_requests": 101},
            {"continuity_artifact_id": 178},
        ):
            with self.subTest(changed=changed):
                evidence=deepcopy(self.proof(101));evidence.update(changed)
                self.assertFalse(self.judge(target,proof=evidence)["dispatch_allowed"])
        self.assertFalse(self.judge(target,proof=None)["dispatch_allowed"])

    def test_p1_budget_cannot_renew_by_restarting(self):
        target=self.owner(101)
        self.assertTrue(self.judge(target,proof=self.proof(101,total=195))["dispatch_allowed"])
        self.assertFalse(self.judge(target,proof=self.proof(101,total=196))["dispatch_allowed"])
        self.assertTrue(self.judge(target,proof=self.proof(101,total=300,base=110))["dispatch_allowed"])

    def test_active_duplicate_and_failed_worker_are_never_successors(self):
        target=self.owner(101)
        active=self.owner(102,created="2026-11-11T00:04:00Z",status="in_progress",
                          conclusion=None)
        self.assertEqual(self.judge(active,target,proof=self.proof(101))["status"],
                         "HOLD_ACTIVE_OWNER_WORKFLOW")
        failed=self.owner(102,created="2026-11-11T00:04:00Z",conclusion="failure")
        self.assertFalse(self.judge(failed,target,proof=self.proof(102))["dispatch_allowed"])



if __name__ == "__main__":
    unittest.main()
