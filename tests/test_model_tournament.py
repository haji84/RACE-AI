"""Pure synthetic tests of existing model tournament, not actual performance."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_comprehensive_four_sport_models import sample
from race_ai.four_sport_model_suite import run_suite, ALL_MODELS
from race_ai.model_tournament import evaluate, run
from race_ai.verified_bulk_backtest import BadRecord


def case(sport="boat", *, cohort="A", status="SETTLED", payout=2000):
    snapshot = sample(sport, size={"boat":6,"keirin":7,
                                   "autorace":8,"horse":9}[sport])
    suite = run_suite(snapshot)
    ticket = suite["models"][ALL_MODELS[0]]["candidates"][0]["combination"]
    event = {
        "race_id":suite["race_id"], "status":status,
        "observed_at":"2030-01-15T11:05:00+09:00",
        "winning_combinations":(
            [] if status != "SETTLED" else
            [{"combination":ticket,"payout_per_100_yen":payout}]),
        "refunded_numbers":[],
        "source_grade":"unverified",
        "source_url":"https://example.test/fictional",
        "revision":1,
    }
    return {"cohort":cohort, "suite":suite, "result":event}


def schedule(cases):
    return [{"cohort":c["cohort"],"race_id":c["suite"]["race_id"]}
            for c in cases]


class ModelTournamentTests(unittest.TestCase):
    def test_four_sports_four_models_four_plans_all_share_one_realistic_cohort(self):
        for sport in ("boat","keirin","autorace","horse"):
            with self.subTest(sport=sport):
                x=case(sport)
                before=copy.deepcopy(x)
                r=evaluate([x],schedule([x]))
                self.assertEqual(x,before)
                self.assertEqual(r["records"],1)
                self.assertFalse(r["research_only"] is False)
                self.assertFalse(r["external_prediction_receipt_verified"])
                self.assertIsNone(r["official_hit_rate"])
                self.assertEqual(set(r["scorecards"]["A"]),set(ALL_MODELS))
                for mid in ALL_MODELS:
                    plans=r["scorecards"]["A"][mid]
                    self.assertEqual(len(plans),4)
                    self.assertEqual(plans["fixed_8"]["records"],1)
                    self.assertEqual(plans["fixed_12"]["stake_yen"],1200)
                    self.assertEqual(plans["confidence_shortlist_1_to_8"]["scorable"],1)
                self.assertEqual(r["cohort_comparisons"]["A"]["paired_scored_races"],1)
                self.assertEqual(r["cohort_comparisons"]["A"]["selection_state"],
                                 "INSUFFICIENT_PAIRED_EVIDENCE")

    def test_unverified_and_special_outcomes_are_not_losses(self):
        x=case()
        x["result"]=None
        report=evaluate([x],schedule([x]))
        v=report["scorecards"]["A"][ALL_MODELS[0]]["fixed_8"]
        self.assertEqual(v["scorable"],0)
        self.assertEqual(v["pending"],1)
        self.assertIsNone(v["hit_rate"])
        x["result"]=case(status="SPECIAL")["result"]
        report=evaluate([x],schedule([x]))
        self.assertEqual(report["scorecards"]["A"][ALL_MODELS[0]]
                         ["fixed_8"]["scorable"],0)

    def test_full_refund_separate_from_accuracy(self):
        x=case()
        x["result"]["status"]="CANCELLED"
        x["result"]["winning_combinations"]=[]
        report=evaluate([x],schedule([x]))
        v=report["scorecards"]["A"][ALL_MODELS[0]]["fixed_8"]
        self.assertEqual((v["gross_yen"] if "gross_yen" in v else
                          v["stake_yen"],v["received_yen"]),(800,800))
        self.assertEqual(v["full_refunds"],1)
        self.assertEqual(v["scorable"],0)
        self.assertEqual(v["roi"],1)
        self.assertEqual(report["cohort_comparisons"]["A"]["paired_scored_races"],0)

    def test_manshu_denominator_is_actual_high_payout_race_not_all_races(self):
        x=case(payout=12000)
        r=evaluate([x],schedule([x]))
        v=r["scorecards"]["A"][ALL_MODELS[0]]["fixed_8"]
        self.assertEqual(v["manshu_races"],1)
        self.assertEqual(v["manshu_hits"],1)
        self.assertEqual(v["manshu_capture_rate"],1)
        x["result"]["winning_combinations"]=[{
            "combination":[6,5,4],"payout_per_100_yen":15000}]
        r=evaluate([x],schedule([x]))
        self.assertEqual(r["scorecards"]["A"][ALL_MODELS[0]]
                         ["fixed_8"]["manshu_races"],1)

    def test_missing_forecast_in_schedule_is_not_silently_dropped(self):
        x=case()
        expected=schedule([x])+[{"cohort":"A","race_id":"boat:2030-01-15:fictional-venue:2"}]
        r=evaluate([x],expected,minimum_paired=1,minimum_days=1)
        self.assertEqual(len(r["missing_forecast_keys"]),1)
        self.assertEqual(r["cohort_comparisons"]["A"]["selection_state"],
                         "INSUFFICIENT_PAIRED_EVIDENCE")
        self.assertFalse(r["cohort_comparisons"]["A"]["coverage_in_expected_schedule"])

    def test_different_asof_cohorts_remain_separate(self):
        x=case()
        y=copy.deepcopy(x);y["cohort"]="B"
        r=evaluate([x,y],schedule([x,y]))
        self.assertEqual(r["records"],2)
        self.assertEqual(set(r["scorecards"]),{"A","B"})
        self.assertEqual(set(r["cohort_comparisons"]),{"A","B"})

    def test_forged_or_mutated_forecast_cannot_be_compared(self):
        x=case()
        x["suite"]["models"][ALL_MODELS[0]]["ordered_top8"][0]=[6,5,4]
        with self.assertRaises(BadRecord):
            evaluate([x],schedule([x]))

    def test_cross_race_results_and_duplicate_forecasts_refused(self):
        x=case()
        bad=copy.deepcopy(x);bad["result"]["race_id"]="boat:2030-01-15:fictional-venue:2"
        with self.assertRaises(BadRecord):
            evaluate([bad],schedule([bad]))
        with self.assertRaises(BadRecord):
            evaluate([x,copy.deepcopy(x)],schedule([x]))

    def test_result_must_be_observed_after_cutoff(self):
        x=case()
        x["result"]["observed_at"]="2030-01-15T09:30:00+09:00"
        with self.assertRaises(ValueError):
            evaluate([x],schedule([x]))

    def test_cli_exports_csv_and_json_without_overwrite(self):
        x=case()
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            forecasts=d/"suites.jsonl"
            scheduled=d/"schedule.jsonl"
            forecasts.write_text(json.dumps(x,ensure_ascii=False)+"\n",encoding="utf8")
            scheduled.write_text(json.dumps(schedule([x])[0])+"\n",encoding="utf8")
            result=run(forecasts,scheduled,d/"out")
            self.assertEqual(result["records"],1)
            self.assertTrue((d/"out"/"per_model_per_race.csv").is_file())
            self.assertEqual(len((d/"out"/"per_model_per_race.csv").read_text(
                             encoding="utf-8-sig").splitlines()),17)
            with self.assertRaises(BadRecord):
                run(forecasts,scheduled,d/"out")

if __name__=="__main__":
    unittest.main()
