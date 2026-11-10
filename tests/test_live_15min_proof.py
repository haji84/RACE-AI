"""Synthetic contract tests only. Never count these as genuine live forecasts."""
import copy
import unittest

from race_ai.live_15min_proof import (
    LiveProofError, audit_frozen_race, select_window, summarize
)

START = "2026-11-11T12:00:00+09:00"
CUTOFF = "2026-11-11T11:58:00+09:00"
PERSISTED = "2026-11-11T11:47:00+09:00"
PUBLISHED = "2026-11-11T11:30:00+09:00"
SOURCE_SHA = "a" * 64
RESULT_SHA = "b" * 64
ROSTER = ("model-A", "model-B")


def fixture():
    source = {"race_id": "20261111XX01", "official_cutoff_at": CUTOFF}
    models = {
        "model-A": {"model_id": "model-A", "prediction_sha256": "c"*64,
                    "ordered_top8": [[1, 2, 3], [1, 3, 2]]},
        "model-B": {"model_id": "model-B", "prediction_sha256": "d"*64,
                    "ordered_top8": [[2, 1, 3]]},
    }
    saved = {"source": source, "suite": {"models": models},
             "source_sha256": SOURCE_SHA, "persisted_at": PERSISTED}
    start = {"sport": "keirin", "race_id": source["race_id"],
             "source_sha256": SOURCE_SHA, "scheduled_start_at": START,
             "official_cutoff_at": CUTOFF, "schedule_published_at": PUBLISHED,
             "authority": "INDEPENDENTLY_VERIFIED_SOURCE"}
    result = {"race_id": source["race_id"], "status": "FINAL",
              "source_sha256": RESULT_SHA,
              "source_published_at": "2026-11-11T12:04:00+09:00",
              "winning_triples": [[1,2,3]]}
    return saved, start, result


class LiveWindowTest(unittest.TestCase):
    def test_time_window_exact_edges(self):
        _, schedule, _ = fixture()
        self.assertEqual(select_window(schedule, "2026-11-11T11:45:00+09:00"),
                         "IN_15_TO_10_MINUTE_PRE_RACE_WINDOW")
        self.assertEqual(select_window(schedule, "2026-11-11T11:50:00+09:00"),
                         "IN_15_TO_10_MINUTE_PRE_RACE_WINDOW")
        self.assertEqual(select_window(schedule, "2026-11-11T11:44:59+09:00"),
                         "WAIT_BEFORE_15_MINUTE_WINDOW")
        self.assertEqual(select_window(schedule, "2026-11-11T11:50:01+09:00"),
                         "HOLD_MISSED_10_MINUTE_DEADLINE")

    def test_missing_schedule_not_inferred_from_cutoff(self):
        _, schedule, _ = fixture()
        schedule.pop("scheduled_start_at")
        self.assertEqual(select_window(schedule, PERSISTED),
                         "HOLD_NO_VERIFIED_START_TIME")

    def test_cutoff_guard_and_delay(self):
        _, schedule, _ = fixture()
        schedule["official_cutoff_at"] = "2026-11-11T11:47:30+09:00"
        self.assertEqual(select_window(schedule, PERSISTED),
                         "HOLD_OFFICIAL_CUTOFF_MARGIN")
        schedule["official_cutoff_at"] = "2026-11-11T12:01:00+09:00"
        with self.assertRaisesRegex(LiveProofError, "CUTOFF_AFTER_START_INVALID"):
            select_window(schedule, PERSISTED)

    def test_schedule_revision_after_freeze_rejected(self):
        _, schedule, _ = fixture()
        schedule["schedule_published_at"] = "2026-11-11T11:49:00+09:00"
        self.assertEqual(select_window(schedule, PERSISTED),
                         "HOLD_SCHEDULE_PUBLISHED_AFTER_FREEZE")

    def test_requires_timezone(self):
        _, schedule, _ = fixture()
        with self.assertRaisesRegex(LiveProofError, "TIMEZONE_REQUIRED"):
            select_window(schedule, "2026-11-11T11:47:00")

    def test_three_sports_supported(self):
        _, schedule, _ = fixture()
        for sport in ("boat", "keirin", "autorace"):
            schedule["sport"] = sport
            self.assertEqual(select_window(schedule, PERSISTED),
                             "IN_15_TO_10_MINUTE_PRE_RACE_WINDOW")


class ArchivedProofTest(unittest.TestCase):
    def check(self, change=None, expected="PROVEN_TIME_WINDOW_MODEL_RESULT_MATCH",
              *, verified=True, official=True):
        saved, start, result = fixture()
        if change:
            change(saved, start, result)
        output = audit_frozen_race(
            saved, start_evidence=start, result=result,
            expected_models=ROSTER, independent_model_readback=verified,
            independently_authenticated_result=official)
        self.assertEqual(output["status"], expected)
        return output

    def test_frozen_full_staged_result_success_requires_both_receipts(self):
        result = self.check()
        self.assertEqual((result["hits"],result["misses"]),(1,1))
        self.assertEqual(summarize([result])["model_result_pairs_proven"],2)

    def test_no_frozen_ledger_readback(self):
        self.check(expected="HOLD_SEPARATE_RUNNER_READBACK_MISSING",
                   verified=False)

    def test_unverified_start_packet(self):
        self.check(lambda saved,start,result: start.update(
            authority="UNVERIFIED"),"HOLD_SCHEDULE_AUTHORITY_UNVERIFIED")

    def test_schedule_source_sha_mismatch(self):
        self.check(lambda saved,start,result: start.update(
            source_sha256="f"*64),"HOLD_SCHEDULE_OR_SOURCE_SHA_MISMATCH")

    def test_no_real_start_evidence(self):
        saved, _, result = fixture()
        report = audit_frozen_race(saved, start_evidence=None, result=result,
             expected_models=ROSTER, independent_model_readback=True)
        self.assertEqual(report["status"],"HOLD_NO_VERIFIED_START_TIME")

    def test_late_forecast_cannot_be_backdated(self):
        self.check(lambda saved,start,result: saved.update(
            persisted_at="2026-11-11T11:55:00+09:00"),
            "HOLD_MISSED_10_MINUTE_DEADLINE")

    def test_missing_model_not_ignored(self):
        self.check(lambda saved,start,result: saved["suite"]["models"].pop(
            "model-B"), "HOLD_MODEL_ROSTER_INCOMPLETE")

    def test_tampered_picks_cannot_be_graded(self):
        self.check(lambda saved,start,result: saved["suite"]["models"]["model-B"].update(
            ordered_top8=[[1,1,3]]), "HOLD_INVALID_MODEL_TICKETS_OR_SHA")

    def test_no_result_is_not_a_loss(self):
        saved, start, _ = fixture()
        report=audit_frozen_race(saved, start_evidence=start, expected_models=ROSTER,
            independent_model_readback=True)
        self.assertEqual(report["status"],"HOLD_RESULT_PENDING")

    def test_unauthenticated_official_result_cannot_win(self):
        self.check(expected="HOLD_OFFICIAL_RESULT_AUTHENTICATION_MISSING",
                   official=False)

    def test_published_before_start_is_not_final(self):
        self.check(lambda saved,start,result: result.update(
            source_published_at=PERSISTED),"HOLD_RESULT_NOT_AFTER_START")

    def test_cancelled_results_not_counted_as_losses(self):
        r=self.check(lambda saved,start,result: result.update(status="CANCELLED"),
                     "VOID_OFFICIAL_CANCELLATION")
        self.assertEqual((r["hits"],r["misses"]),(0,0))

    def test_summary_does_not_contain_private_tickets(self):
        r=self.check()
        summary=summarize([r,{"status":"HOLD_RESULT_PENDING","models":2}])
        self.assertEqual(summary["proven_races"],1)
        self.assertEqual(summary["model_result_pairs_proven"],2)
        self.assertEqual(summary["holds"],{"HOLD_RESULT_PENDING":1})
        self.assertNotIn("20261111XX01",str(summary))
        self.assertNotIn("[1, 2, 3]",str(summary))


if __name__=="__main__":
    unittest.main()
