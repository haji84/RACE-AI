"""Strict result/P D C A tests, all synthetic and frozen before outcomes."""
from copy import deepcopy
import unittest
from race_ai.boat_ab_shadow import build_pair,MODEL_IDS,_digest
from race_ai.boat_ab_result_audit import score_pair

def fixture():
    source=dict(race_id="20301103-17-05",cutoff_at="2030-11-03T13:30:00+09:00",
                captured_at="2030-11-03T13:14:00+09:00",
                program_source_sha256="a"*64,beforeinfo_source_sha256="b"*64,
                boats=[dict(lane=n,racer_id=str(4200+n),national_win_rate=6+n*.05,
                            exhibition_time_seconds=6.7+n*.01,motor_two_place_rate_percent=30+n)
                       for n in range(1,7)])
    pair=build_pair(source,"2030-11-03T13:15:00+09:00")
    return dict(schema="RACE_AI_BOAT_LIVE_AB_RESEARCH_V1",
                status="REAL_TWO_MODEL_PAIR_GENERATED_UNVERIFIED_ARTIFACT",
                result_used=False,race_id=source["race_id"],cutoff_at=source["cutoff_at"],
                paired_forecast=pair)

class AuditTests(unittest.TestCase):
    def test_scores_saved_pair_without_changing_any_original_byte(self):
        old=fixture();frozen=deepcopy(old)
        a=score_pair(old,"1-2-3","2030-11-03T13:34:00+09:00","2030-11-03T13:16:00+09:00")
        self.assertEqual(old,frozen)
        self.assertEqual([m["model_id"] for m in a["models"]],list(MODEL_IDS))
        self.assertFalse(a["next_model_auto_promoted"])
        for m in a["models"]:
            self.assertEqual(m["hit_at_1"],int(m["top8"][0]=="1-2-3"))
            self.assertEqual(m["hit_at_8"],int("1-2-3" in m["top8"]))
            self.assertGreater(m["multiclass_brier"],0)
            self.assertGreater(m["log_loss"],0)

    def test_refuses_after_cutoff_forecast_and_preclose_result(self):
        for saved,observed in (
             ("2030-11-03T13:30:00+09:00","2030-11-03T13:34:00+09:00"),
             ("2030-11-03T13:16:00+09:00","2030-11-03T13:29:00+09:00")):
            with self.assertRaises(ValueError):
                score_pair(fixture(),"1-2-3",observed,saved)

    def test_github_artifact_timestamp_truncates_subsecond_without_expanding_cutoff(self):
        source=dict(race_id="20301103-17-05",cutoff_at="2030-11-03T13:30:00+09:00",
                    captured_at="2030-11-03T13:14:59.990000+09:00",
                    program_source_sha256="a"*64,beforeinfo_source_sha256="b"*64,
                    boats=[dict(lane=n,racer_id=str(4200+n),
                                national_win_rate=6+n*.05,
                                exhibition_time_seconds=6.7+n*.01,
                                motor_two_place_rate_percent=30+n)
                           for n in range(1,7)])
        old=dict(schema="RACE_AI_BOAT_LIVE_AB_RESEARCH_V1",
                 status="REAL_TWO_MODEL_PAIR_GENERATED_UNVERIFIED_ARTIFACT",
                 result_used=False,race_id=source["race_id"],cutoff_at=source["cutoff_at"],
                 paired_forecast=build_pair(source,"2030-11-03T13:15:00.181331+09:00"))
        # Same-second GitHub created_at can be displayed earlier than generation
        # at microsecond resolution; chronological validity still holds.
        score_pair(old,"1-2-3","2030-11-03T13:34:00+09:00",
                   "2030-11-03T13:15:00+09:00")
        for saved in ("2030-11-03T13:14:59+09:00",
                      "2030-11-03T13:30:00+09:00"):
            with self.assertRaises(ValueError):
                score_pair(old,"1-2-3","2030-11-03T13:34:00+09:00",saved)

    def test_rejects_replaced_model_and_altered_forecast(self):
        original=fixture()
        for fn in (
            lambda p:p["paired_forecast"]["models"][0]["full_120"][0].update(score=0.90),
            lambda p:p["paired_forecast"]["models"].pop(),
            lambda p:p["paired_forecast"].update(actual_result_at_forecast_time=[1,2,3])
        ):
            x=deepcopy(original);fn(x)
            with self.assertRaises(ValueError):
                score_pair(x,"1-2-3","2030-11-03T13:34:00+09:00","2030-11-03T13:16:00+09:00")

    def test_invalid_top_three_never_makes_false_score(self):
        for ticket in ("1-1-2","0-2-3","1-2-7","unconfirmed",""):
            with self.assertRaises(ValueError):
                score_pair(fixture(),ticket,"2030-11-03T13:34:00+09:00","2030-11-03T13:16:00+09:00")

if __name__=="__main__":unittest.main()
