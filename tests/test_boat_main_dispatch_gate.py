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
            "ACTIVE_FULL_FIRST_TO_FIXED_ATTEMPT_TWO_BOUNDARY " + RELEASE_TOKEN,
            "CODE_ONLY_NO_SOURCE",
        ):
            value=self.decide(src=doc)
            self.assertFalse(value["dispatch_allowed"])
            self.assertEqual(value["status"], "HOLD_SOURCE_OWNER_FIXED_BOUNDARY_NOT_RELEASED")
            self.assertFalse(value["future_real_forecast_proven"])
            self.assertFalse(value["official_results_reconciled"])

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

    def test_unreturned_pagination_is_not_no_forecast(self):
        output=decide(now=NOW, release=release(),
            owner_doc=source_doc(RELEASE_TOKEN), history=history(total=101))
        self.assertEqual(output["status"], "HOLD_INCOMPLETE_RUN_HISTORY")
        self.assertFalse(output["dispatch_allowed"])


if __name__ == "__main__":
    unittest.main()
