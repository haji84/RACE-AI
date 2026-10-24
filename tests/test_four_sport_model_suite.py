"""Run a same-race prospective model roster on fictional evidence only."""
import copy
import unittest

from test_comprehensive_four_sport_models import sample
from race_ai.four_sport_model_suite import run_suite, verify_suite, ALL_MODELS
from race_ai.comprehensive_four_sport_models import ModelInputError

SIZES={"boat":6,"keirin":7,"autorace":8,"horse":18}


class ModelSuiteTest(unittest.TestCase):
    def test_all_models_on_every_sport_exact_same_snapshot_and_cutoff(self):
        for sport,n in SIZES.items():
            with self.subTest(sport=sport):
                s=sample(sport,size=n)
                batch=run_suite(s)
                self.assertTrue(verify_suite(batch))
                self.assertEqual(batch["ranked_model_ids"],list(ALL_MODELS))
                self.assertEqual(batch["model_count"],4)
                self.assertEqual(batch["official_prediction"],False)
                self.assertIsNone(batch["external_timestamp_receipts"])
                for m in batch["models"].values():
                    self.assertEqual(m["snapshot_sha256"],batch["input_sha256"])
                    self.assertEqual(m["candidate_count"],n*(n-1)*(n-2))
                    self.assertEqual(len(m["ordered_top8"]),8)
                    self.assertEqual(m["cutoff_at"],batch["sales_cutoff_at"])

    def test_real_scope_has_no_implicit_permission(self):
        s=sample("keirin",scope="OPERATOR_SUPPLIED_RESEARCH")
        with self.assertRaisesRegex(ModelInputError,"rights not externally admitted"):
            run_suite(s)

    def test_mutation_of_one_model_cannot_pass_suite_integrity(self):
        batch=run_suite(sample("boat"))
        bad=copy.deepcopy(batch)
        bad["models"][ALL_MODELS[0]]["ordered_top8"][0]=[6,5,4]
        self.assertFalse(verify_suite(bad))
        missing=copy.deepcopy(batch)
        del missing["models"][ALL_MODELS[-1]]
        self.assertFalse(verify_suite(missing))

    def test_repeatable_same_features_and_weather_change(self):
        s=sample("horse",size=12)
        x=run_suite(s)
        self.assertEqual(x,run_suite(copy.deepcopy(s)))
        updated=copy.deepcopy(s)
        updated["environment"]["rain_mm_h"]["value"]=90
        updated["environment"]["surface_wetness"]["value"]=.9
        y=run_suite(updated)
        self.assertNotEqual(x["input_sha256"],y["input_sha256"])
        self.assertNotEqual(x["models"][ALL_MODELS[-1]]["scenario_weights"],
                            y["models"][ALL_MODELS[-1]]["scenario_weights"])


    def test_train_only_learned_model_is_optional_fifth_model(self):
        from test_four_sport_learning import fit_rows, dataset, future
        from race_ai.four_sport_learning import LEARNED_ID
        model=fit_rows(dataset("boat"),sport="boat")
        batch=run_suite(future("boat"),learned_model=model)
        self.assertTrue(verify_suite(batch))
        self.assertEqual(batch["model_count"],5)
        self.assertEqual(batch["ranked_model_ids"][-1],LEARNED_ID)
        self.assertTrue(batch["models"][LEARNED_ID]["trained"])
        self.assertFalse(batch["models"][LEARNED_ID]["calibrated"])
        self.assertIsNone(batch["external_timestamp_receipts"])
        assert batch["models"][LEARNED_ID]["official_prediction"] is False

    def test_wrong_sport_learned_model_rejected_instead_of_retrained(self):
        from test_four_sport_learning import fit_rows, dataset, future
        from race_ai.comprehensive_four_sport_models import ModelInputError
        model=fit_rows(dataset("boat"),sport="boat")
        with self.assertRaisesRegex(ModelInputError,"version/sport"):
            run_suite(future("horse"),learned_model=model)

    def test_no_results_odds_money_or_official_picks_produced(self):
        x=run_suite(sample("boat"))
        self.assertEqual(x["purchase_decision"],"NO_BET")
        self.assertIsNone(x["official_result"])
        for model in x["models"].values():
            self.assertNotIn("market_odds",model)
            self.assertNotIn("payout_yen",model)
            self.assertFalse(model["official_prediction"])
            self.assertIsNone(model["external_pre_cutoff_receipt"])


if __name__=="__main__":
    unittest.main()
