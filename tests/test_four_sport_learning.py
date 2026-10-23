"""Chronological learning tests. All entrants and results are fictional fixtures."""
import copy
import datetime
import json
import unittest

from test_comprehensive_four_sport_models import sample, obs
from race_ai.comprehensive_four_sport_models import (
    ModelInputError, SYNTHETIC, RESEARCH, digest
)
from race_ai.four_sport_learning import (
    LEARNED_ID, fit_chronological, forecast, vector_schema
)

def dataset(sport="boat",size=None):
    rows=[]
    for i in range(12):
        day=f"2030-01-{i+1:02d}"
        old=sample(sport,size=size)
        s=json.loads(json.dumps(old).replace("2030-01-15",day))
        # Distinct outcomes, no market or other-race future observations.
        n=len(s["participants"])
        top=[1+((i+1)%n),1+((i+2)%n),1+((i+3)%n)]
        if len(set(top))!=3:raise AssertionError("fixture labels must be unique")
        result={"race_id":s["race"]["race_id"],"status":"settled",
                "ordered_top3":top,
                "published_at":day+"T11:00:00+09:00",
                "captured_at":day+"T11:05:00+09:00",
                "source_ref":"synthetic://official-fixture",
                "source_rights_ref":"synthetic-result-v1"}
        rows.append({"snapshot":s,"result":result})
    return rows

def fit_rows(rows,sport="boat",**opts):
    return fit_chronological(rows,sport=sport,
        train_end_at="2030-01-07T23:59:00+09:00",
        validation_end_at="2030-01-10T23:59:00+09:00",
        test_end_at="2030-01-15T23:59:00+09:00",
        epochs=12,learning_rate=.025,**opts)

def future(sport="boat",size=None):
    s=sample(sport,size=size)
    s["race"]["as_of"]="2030-01-15T09:10:00+09:00"
    return s

class ChronologicalLearningTests(unittest.TestCase):
    def test_can_fit_and_predict_all_sports_without_market_input(self):
        for sport,n in (("boat",6),("keirin",9),("autorace",8),("horse",18)):
            with self.subTest(sport=sport):
                model=fit_rows(dataset(sport,size=n),sport=sport)
                self.assertEqual(model["model_id"],LEARNED_ID)
                self.assertEqual(model["trained_examples"],7)
                self.assertEqual(model["validation_diagnostics"]["n"],3)
                self.assertEqual(model["holdout_diagnostics"]["n"],2)
                self.assertFalse(model["calibrated"])
                self.assertFalse(model["official_model_approved"])
                self.assertFalse(model["trained_on_licensed_real_data"])
                output=forecast(future(sport,size=n),model)
                self.assertEqual(output["candidate_count"],n*(n-1)*(n-2))
                self.assertEqual(len(output["ordered_top8"]),8)
                self.assertEqual(output["purchase_decision"],"NO_BET")
                self.assertFalse(output["official_prediction"])
                self.assertTrue(output["trained"])
                self.assertFalse(output["calibrated"])
                self.assertEqual(len(set(tuple(c["combination"]) for c in output["candidates"])),
                                 n*(n-1)*(n-2))

    def test_future_test_labels_cannot_change_fitted_weights(self):
        rows=dataset()
        reference=fit_rows(rows)
        manipulated=copy.deepcopy(rows)
        for item in manipulated[10:]:
            item["result"]["ordered_top3"]=[6,5,4]
        version=fit_rows(manipulated)
        self.assertEqual(reference["weights"],version["weights"])
        self.assertEqual(reference["trained_examples"],version["trained_examples"])
        self.assertEqual(reference["train_example_ids"],version["train_example_ids"])
        self.assertEqual(reference["validation_diagnostics"],version["validation_diagnostics"])

    def test_validation_labels_cannot_change_fitted_weights(self):
        rows=dataset()
        reference=fit_rows(rows)
        altered=copy.deepcopy(rows)
        for item in altered[7:10]:
            item["result"]["ordered_top3"]=[6,5,4]
        comparison=fit_rows(altered)
        self.assertEqual(reference["weights"],comparison["weights"])

    def test_training_results_after_train_boundary_are_rejected(self):
        rows=dataset()
        rows[0]["result"]["published_at"]="2030-01-08T12:00:00+09:00"
        rows[0]["result"]["captured_at"]="2030-01-08T12:01:00+09:00"
        with self.assertRaisesRegex(ModelInputError,"result unavailable"):
            fit_rows(rows)

    def test_future_or_past_time_cannot_backfill_model_forecast(self):
        m=fit_rows(dataset())
        old=sample("boat")
        old["race"]["as_of"]="2030-01-07T09:10:00+09:00"
        old["race"]["event_date_jst"]="2030-01-07"
        old["race"]["sales_cutoff_at"]="2030-01-07T10:00:00+09:00"
        with self.assertRaisesRegex(ModelInputError,"prediction must follow training"):
            forecast(old,m)

    def test_weights_tamper_and_model_sport_conflict_rejected(self):
        m=fit_rows(dataset())
        m["weights"][0]+=2
        with self.assertRaisesRegex(ModelInputError,"integrity"):
            forecast(future(),m)
        m=fit_rows(dataset())
        with self.assertRaisesRegex(ModelInputError,"version/sport"):
            forecast(future("horse"),m)

    def test_market_and_result_leak_guard_remains_active_in_training(self):
        rows=dataset()
        rows[0]["snapshot"]["participants"][0]["features"]["current_race_finish"]=obs(.95)
        with self.assertRaisesRegex(ModelInputError,"prohibited participant"):
            fit_rows(rows)
        rows=dataset()
        rows[0]["snapshot"]["participants"][0]["features"]["market_odds"]=obs(.95)
        with self.assertRaisesRegex(ModelInputError,"market/result leak"):
            fit_rows(rows)

    def test_real_permission_requires_both_input_and_result_gate(self):
        rows=dataset()
        for r in rows:r["snapshot"]["scope"]=RESEARCH
        with self.assertRaisesRegex(ModelInputError,"not externally admitted"):
            fit_rows(rows)
        with self.assertRaisesRegex(ModelInputError,"result label source not independently admitted"):
            fit_rows(rows,allow_source=lambda *_:True)
        admitted=fit_rows(rows,allow_source=lambda *_:True,
                          allow_result=lambda *_:True)
        self.assertEqual(admitted["trained_on_licensed_real_data"],"REQUIRES_EXTERNAL_AUDIT")
        self.assertFalse(admitted["official_model_approved"])

    def test_chronological_windows_must_not_overlap(self):
        with self.assertRaisesRegex(ModelInputError,"overlap"):
            fit_chronological(dataset(),sport="boat",
               train_end_at="2030-01-10T12:00:00+09:00",
               validation_end_at="2030-01-07T12:00:00+09:00",
               test_end_at="2030-01-15T12:00:00+09:00")

    def test_minimum_samples_and_duplicate_race_rejected(self):
        with self.assertRaisesRegex(ModelInputError,"at least six"):
            fit_rows(dataset()[:6])
        rows=dataset()
        rows[1]=copy.deepcopy(rows[0])
        with self.assertRaisesRegex(ModelInputError,"duplicate racing identity"):
            fit_rows(rows)

    def test_optional_missingness_is_explicit_in_learned_result(self):
        model=fit_rows(dataset("horse"),sport="horse")
        out=forecast(future("horse"),model)
        self.assertIn("paddock_observation",out["missing_optional_by_participant"][1])
        self.assertEqual(len(vector_schema("horse")),len(model["weights"]))

if __name__=="__main__":
    unittest.main()
