"""Synthetic all-venues ledger must never turn missing B into a scored forecast."""
import unittest
from race_ai.boat_post_exhibition_ab_coverage import count_schedule,SCHEMA

DAY="20300401"


def schedule():
    return [dict(race_id=f"{DAY}-{venue:02d}-{n:02d}",
                 cutoff_at=(f"2030-04-01T10:30:00+09:00"
                            if venue == 1 and n == 1 else
                            f"2030-04-01T09:30:00+09:00"
                            if venue == 1 and n == 2 else
                            f"2030-04-01T17:00:00+09:00"))
            for venue in range(1,12) for n in range(1,13)]


def study(pairs=None,holds=None):
    pairs=pairs or []
    holds=holds or []
    return dict(schema="RACE_AI_POST_EXHIBITION_AB_ENCRYPTED_ROUND_V1",
                pairs=pairs,holds=holds,
                attempted=len(pairs)+len(holds),
                candidate_pairs=len(pairs),held_races=len(holds))


class AllRaceCoverage(unittest.TestCase):
    def test_132_venues_not_132_forecasts(self):
        result=count_schedule(schedule(),study(),
                              now="2030-04-01T10:00:00+09:00")
        self.assertEqual(result["schema"],SCHEMA)
        self.assertEqual(result["venues"],11)
        self.assertEqual(result["scheduled_races"],132)
        self.assertEqual(result["b_physically_saved_before_cutoff"],0)
        self.assertEqual(sum(r["scheduled"] for r in result["venue_counts"].values()),132)
        self.assertEqual(result["status_counts"]["WAIT_POST_EXHIBITION_P1"],131)
        self.assertEqual(result["status_counts"]["HOLD_CUTOFF_PASSED_NO_B"],1)

    def test_a_real_preclose_receipt_only_marks_one_research_B(self):
        rid=DAY+"-01-01"
        pair={"race_id":rid,"generated_at":"2030-04-01T10:02:00+09:00"}
        hold={"race_id":DAY+"-01-02","status":"HOLD_TACTICS"}
        result=count_schedule(schedule(),study([pair],[hold]),
                             now="2030-04-01T10:10:00+09:00",
                             artifact_saved_at="2030-04-01T10:05:00+09:00")
        self.assertEqual(result["b_physically_saved_before_cutoff"],1)
        self.assertEqual(result["status_counts"]["HOLD_B_RESEARCH_FEATURES_OR_ORIGINAL"],1)
        self.assertEqual(result["status_counts"]["WAIT_POST_EXHIBITION_P1"],130)
        self.assertEqual(result["venue_counts"]["01"]["scheduled"],12)
        self.assertEqual(result["source_provider_requests"],0)
        before=count_schedule(schedule(),study([pair],[hold]),
                              now="2030-04-01T10:03:00+09:00")
        self.assertEqual(before["b_prepared_not_yet_saved"],1)

    def test_late_encrypted_original_is_never_counted(self):
        pair={"race_id":DAY+"-01-01",
              "generated_at":"2030-04-01T10:02:00+09:00"}
        result=count_schedule(schedule(),study([pair]),
                             now="2030-04-01T10:31:00+09:00",
                             artifact_saved_at="2030-04-01T10:31:00+09:00")
        self.assertEqual(result["b_physically_saved_before_cutoff"],0)
        self.assertEqual(result["status_counts"]["HOLD_B_PHYSICAL_SAVE_TOO_LATE"],1)

    def test_forged_dupe_outside_scope_or_day_rejected(self):
        with self.assertRaisesRegex(ValueError,"DUPLICATE"):
            count_schedule(schedule()+schedule()[:1],study(),
                           now="2030-04-01T10:00:00+09:00")
        with self.assertRaisesRegex(ValueError,"SCHEDULE_RESEARCH_MISMATCH"):
            count_schedule(schedule(),study([{"race_id":DAY+"-12-01",
                                               "generated_at":"2030-04-01T10:00:00+09:00"}]),
                           now="2030-04-01T10:00:00+09:00")
        bad=schedule()
        bad[0]["cutoff_at"]="2030-04-02T10:30:00+09:00"
        with self.assertRaisesRegex(ValueError,"CUTOFF_DAY"):
            count_schedule(bad,study(),now="2030-04-01T10:00:00+09:00")


if __name__=="__main__":
    unittest.main()
