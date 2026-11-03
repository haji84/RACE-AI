"""Multi-race A/B cohort synthetic tests; no actual result or cloud evidence."""
from copy import deepcopy
from datetime import date,datetime,timedelta
import unittest

from race_ai.boat_ab_shadow import build_pair
from race_ai.boat_ab_result_audit import score_pair
from race_ai.boat_ab_cohort import analyze, wilson


def fake_case(i=0, *, forecast=True):
    day=date(2030,11,3)+timedelta(days=i//20)
    venue=i%20+1
    date8=day.strftime("%Y%m%d")
    stamp=day.isoformat()
    race_id=f"{date8}-{venue:02d}-05"
    cutoff=f"{stamp}T13:30:00+09:00"
    captured=f"{stamp}T13:14:00+09:00"
    generated=f"{stamp}T13:15:00+09:00"
    saved=f"{stamp}T13:16:00+09:00"
    outcome=f"{stamp}T13:34:00+09:00"
    source=dict(race_id=race_id,cutoff_at=cutoff,captured_at=captured,
                program_source_sha256="a"*64,
                beforeinfo_source_sha256="b"*64,
                boats=[dict(lane=n,racer_id=str(4100+n),
                            national_win_rate=6+.03*n,
                            exhibition_time_seconds=6.75+.01*n,
                            motor_two_place_rate_percent=30+n*2)
                       for n in range(1,7)])
    original=dict(schema="RACE_AI_BOAT_LIVE_AB_RESEARCH_V1",
                  status="REAL_TWO_MODEL_PAIR_GENERATED_UNVERIFIED_ARTIFACT",
                  result_used=False,race_id=race_id,cutoff_at=cutoff)
    original["paired_forecast"]=build_pair(source,generated)
    ticket="1-2-3" if i%2==0 else "2-1-3"
    audit=score_pair(original,ticket,outcome,saved)
    receipt=dict(verified_download_and_sha256=True,
                 artifact_sha256="e"*64,
                 original_pair_json_sha256="f"*64,
                 server_created_at=saved,
                 pair_bundle_sha256=original["paired_forecast"]["bundle_sha256"])
    return dict(race_id=race_id,cutoff_at=cutoff,trifecta_offered=True,
                result_state="SETTLED",official_top3=ticket,
                official_source_sha256="c"*64,
                official_result_captured_at=outcome,
                payout_per_100_yen=900,
                paired_audit=audit if forecast else None,
                artifact_receipt=receipt if forecast else None)


class MultiRaceABTest(unittest.TestCase):
    def test_single_race_is_not_improvement_evidence(self):
        x=analyze([fake_case()])
        self.assertEqual(x["total_discovered"],1)
        self.assertEqual(x["paired_forecast_count"],1)
        self.assertEqual(x["officially_settled_eligible"],1)
        self.assertEqual(x["statement"],"INCONCLUSIVE_NOT_ENOUGH_PROSPECTIVE_EVIDENCE")
        self.assertFalse(x["model_auto_promoted"])
        self.assertEqual(len(x["models"]),2)
        for m in x["models"]:
            self.assertEqual(m["hypothetical_8x100_yen_spend"],800)
            self.assertIsNotNone(m["avg_multiclass_brier"])
            self.assertIsNotNone(m["avg_log_loss"])
            self.assertIsNotNone(m["mean_top8_model_mass"])

    def test_missing_predictions_are_not_deleted_from_all_race_denominator(self):
        x=analyze([fake_case(),fake_case(1,forecast=False)])
        self.assertEqual(x["officially_settled_eligible"],2)
        self.assertEqual(x["paired_forecast_count"],1)
        self.assertEqual(x["unforecast_or_unverified"],1)
        for m in x["models"]:
            self.assertAlmostEqual(m["hit_at_8_all"],m["hits_at_8"]/2)
            self.assertAlmostEqual(m["hit_at_8_matched"],m["hits_at_8"])

    def test_full_sample_never_autopromotes(self):
        # All numbers below are synthetic test doubles, never actual betting.
        cases=[fake_case(i) for i in range(100)]
        x=analyze(cases)
        self.assertEqual(x["total_discovered"],100)
        self.assertEqual(x["paired_forecast_count"],100)
        self.assertEqual(x["paired_days"],5)
        self.assertFalse(x["model_auto_promoted"])
        self.assertIsNotNone(x["paired_comparison"]["b_minus_a_hit_at8_bootstrap95"])
        self.assertIsNotNone(x["paired_comparison"]["b_minus_a_brier_bootstrap95"])
        self.assertIsNotNone(x["paired_comparison"]["b_minus_a_logloss_bootstrap95"])
        self.assertEqual(x["paired_comparison"]["paired_n"],100)
        self.assertEqual(x,analyze(list(reversed(cases))))

    def test_pending_cancelled_refunded_and_unoffered_not_scored(self):
        rows=[fake_case(i) for i in range(4)]
        for row,state in zip(rows,("PENDING","CANCELLED","REFUNDED","NO_TRIFECTA")):
            row.update(result_state=state,official_top3=None,
                       payout_per_100_yen=None,paired_audit=None,
                       artifact_receipt=None)
            if state=="NO_TRIFECTA":row["trifecta_offered"]=False
        x=analyze(rows)
        self.assertEqual(x["officially_settled_eligible"],0)
        self.assertEqual(x["paired_forecast_count"],0)
        self.assertEqual(x["state_counts"]["REFUNDED"],1)
        self.assertIsNone(x["models"][0]["hit_at_8_all"])

    def test_duplicate_or_tampered_source_never_becomes_real_win(self):
        a=fake_case()
        with self.assertRaisesRegex(ValueError,"duplicate"):
            analyze([a,a])
        variants=[
            ("wrong race result",lambda x:x.update(official_top3="3-4-5")),
            ("late artifact",lambda x:x["artifact_receipt"].update(server_created_at=x["cutoff_at"])),
            ("fake readback",lambda x:x["artifact_receipt"].update(verified_download_and_sha256=False)),
            ("altered model",lambda x:x["paired_audit"]["models"][0].update(hit_at_8=9)),
            ("wrong result instant",lambda x:x.update(official_result_captured_at="2030-11-03T12:00:00+09:00")),
            ("missing payout check",lambda x:x.update(payout_per_100_yen=-1)),
            ("forecast bundle swap",lambda x:x["artifact_receipt"].update(pair_bundle_sha256="3"*64)),
            ("forecaster result",lambda x:x["paired_audit"].update(official_top3="5-1-2")),
        ]
        for name,change in variants:
            case=deepcopy(a);change(case)
            with self.subTest(name=name),self.assertRaises(ValueError):
                analyze([case])

    def test_wilson_limits_and_empty(self):
        self.assertIsNone(wilson(0,0))
        self.assertEqual(wilson(1,1)[1],1)
        self.assertEqual(wilson(0,1)[0],0)
        self.assertLess(wilson(10,20)[0],.5)
        self.assertGreater(wilson(10,20)[1],.5)


if __name__ == "__main__":
    unittest.main()
