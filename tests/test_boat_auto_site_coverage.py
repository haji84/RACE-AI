"""Synthetic zero-GET tests for BOAT daily sealed forecast/result coverage."""
import unittest
from scripts.boat_auto_site_coverage import summarize


def cohort():
    rows=[]
    for i in range(2):
        rows.append(dict(
            sport="boat", event_date_jst="2026-11-13",
            race_id=f"20261113-01-0{i+1}",
            prediction={"model_id":"boat-factor", "stage":"P0"},
            comparison_predictions=[{"model_id":"boat-start","stage":"P0"}]))
    return dict(dataset_status="REAL_REPORTED",records=rows)


def score(*,eligible=2,held=0,pending=0):
    groups=[]
    for model in ("boat-factor","boat-start"):
        groups.append(dict(model_id=model,stage="P0",forecasts=2,
                           eligible=eligible,hits=1 if eligible else 0,
                           misses=eligible-(1 if eligible else 0),void=0,
                           pending=pending,held=held))
    return dict(schema="RACE_AI_RETAINED_MODEL_PDCA_AUDIT_V1",
                source="AES_AUTHENTICATED_SAVED_VIEW_ONLY",
                no_provider_requests=True,rewrote_predictions=False,
                actual_purchases=False,model_groups=groups,
                total_forecasts=4,total_scored=2*eligible,
                unresolved=2*(held+pending))


class AutoSiteCoverageTests(unittest.TestCase):
    def test_all_original_models_are_fully_scored(self):
        view=cohort();s=score()
        states={r["race_id"]:"final" for r in view["records"]}
        report=summarize(view,s,states,day="2026-11-13")
        self.assertEqual(report["status"],"COMPLETE")
        self.assertEqual(report["saved_races"],2)
        self.assertEqual(report["model_scored_forecasts"],4)
        self.assertEqual(report["model_held_forecasts"],0)
        self.assertEqual(report["official_provider_gets"],0)
        self.assertEqual(report["original_forecast_rewrites"],0)
        self.assertNotIn(view["records"][0]["race_id"],str(report))

    def test_new_day_unsettled_race_is_hold_not_false_miss(self):
        view=cohort()
        states={view["records"][0]["race_id"]:"final",
                view["records"][1]["race_id"]:"unsupported"}
        report=summarize(view,score(eligible=1,held=1),states,day="2026-11-13")
        self.assertEqual(report["status"],"HOLD")
        self.assertEqual(report["model_scored_forecasts"],2)
        self.assertEqual(report["model_held_forecasts"],2)
        self.assertEqual(report["reference_or_unsupported_races"],1)

    def test_missing_is_pending_not_historical_false_loss(self):
        view=cohort()
        states={view["records"][0]["race_id"]:"final",
                view["records"][1]["race_id"]:"missing"}
        report=summarize(view,score(eligible=1,pending=1),states,day="2026-11-13")
        self.assertEqual(report["status"],"HOLD")
        self.assertEqual(report["pending_result_races"],1)
        self.assertEqual(report["model_pending_forecasts"],2)

    def test_unverified_source_or_wrong_model_counts_fail_closed(self):
        view=cohort()
        states={r["race_id"]:"final" for r in view["records"]}
        bad=score();bad["no_provider_requests"]=False
        with self.assertRaisesRegex(ValueError,"NATIVE_SCORER_REQUIRED"):
            summarize(view,bad,states,day="2026-11-13")
        bad=score();bad["total_scored"]=5
        with self.assertRaisesRegex(ValueError,"NATIVE_MODEL_TOTALS_CONFLICT"):
            summarize(view,bad,states,day="2026-11-13")
        bad=score();bad["actual_purchases"]=True
        with self.assertRaisesRegex(ValueError,"NATIVE_SCORER_REQUIRED"):
            summarize(view,bad,states,day="2026-11-13")

    def test_duplicate_or_missing_race_refuses(self):
        view=cohort()
        states={r["race_id"]:"final" for r in view["records"]}
        view["records"][1]["race_id"]=view["records"][0]["race_id"]
        with self.assertRaisesRegex(ValueError,"RACE_COHORT_INVALID"):
            summarize(view,score(),states,day="2026-11-13")


if __name__=="__main__":
    unittest.main()
