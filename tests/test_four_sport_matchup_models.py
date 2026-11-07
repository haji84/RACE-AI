"""Fictional four-sport alternatives with strict temporal and rights boundaries."""
import copy
import itertools
import math
import unittest

from test_comprehensive_four_sport_models import sample
from race_ai.four_sport_matchup_models import MODEL_IDS, predict
from race_ai.comprehensive_four_sport_models import ModelInputError, digest

FIELDS={"boat":6,"keirin":9,"autorace":8,"horse":18}


class ConditionalMatchupTest(unittest.TestCase):
    def test_all_four_sport_universes_are_complete_and_normalized(self):
        for sport,n in FIELDS.items():
            with self.subTest(sport=sport):
                models=predict(sample(sport,size=n))
                self.assertEqual(tuple(models),MODEL_IDS)
                for model in models.values():
                    self.assertEqual(model["candidate_count"],n*(n-1)*(n-2))
                    self.assertEqual(len(model["ordered_top8"]),8)
                    self.assertEqual(len({tuple(r["combination"]) for r in model["candidates"]}),
                                     n*(n-1)*(n-2))
                    self.assertAlmostEqual(math.fsum(r["score"] for r in model["candidates"]),1.0,places=10)
                    self.assertTrue(model["odds_independent"])
                    self.assertFalse(model["trained"])
                    self.assertFalse(model["calibrated"])
                    self.assertFalse(model["official_prediction"])
                    self.assertIsNone(model["external_pre_cutoff_receipt"])
                    self.assertIsNone(model["official_result"])
                    self.assertEqual(model["purchase_decision"],"NO_BET")
                    self.assertEqual(model["prediction_sha256"],
                        digest({k:v for k,v in model.items() if k!="prediction_sha256"}))

    def test_two_new_models_are_independent_distributions(self):
        for sport in ("boat","keirin","horse"):
            with self.subTest(sport=sport):
                models=predict(sample(sport))
                a,b=(models[x] for x in MODEL_IDS)
                self.assertNotEqual(a["candidates"],b["candidates"])
                self.assertAlmostEqual(math.fsum(b["scenario_weights"].values()),1,places=10)

    def test_keirin_same_line_followers_affect_ordered_positions(self):
        together=sample("keirin",size=9)
        apart=copy.deepcopy(together)
        for p in apart["participants"]:p["group_id"]=None
        a=predict(together)[MODEL_IDS[0]]
        b=predict(apart)[MODEL_IDS[0]]
        self.assertNotEqual(a["prediction_sha256"],b["prediction_sha256"])
        self.assertNotEqual(a["candidates"],b["candidates"])

    def test_horse_front_runner_and_closer_interaction(self):
        one=sample("horse",size=12)
        two=copy.deepcopy(one)
        for p in two["participants"]:p["style"]="allround"
        self.assertNotEqual(predict(one)[MODEL_IDS[0]]["candidates"],
                            predict(two)[MODEL_IDS[0]]["candidates"])

    def test_weather_changes_trajectory_distribution(self):
        calm=sample("autorace")
        rain=copy.deepcopy(calm)
        rain["environment"]["rain_mm_h"]["value"]=90
        rain["environment"]["surface_wetness"]["value"]=1
        rain["environment"]["wet_track_factor"]["value"]=1
        a=predict(calm)[MODEL_IDS[1]]
        b=predict(rain)[MODEL_IDS[1]]
        self.assertNotEqual(a["scenario_weights"],b["scenario_weights"])
        self.assertNotEqual(a["candidates"],b["candidates"])

    def test_all_optional_feature_inventory_is_honestly_reported_missing(self):
        m=predict(sample("horse",size=18))[MODEL_IDS[0]]
        self.assertIn("paddock_observation",m["missing_optional_by_participant"][1])
        self.assertIn("workout_form",m["missing_optional_by_participant"][1])

    def test_result_or_market_columns_cannot_become_feature(self):
        for forbidden in ("odds","payout_yen","actual_finish","current_race_winner"):
            with self.subTest(forbidden=forbidden):
                s=sample("boat")
                s["participants"][0]["features"][forbidden]={
                    "value":.9,"published_at":"2030-01-15T08:00:00+09:00"
                }
                with self.assertRaises(ModelInputError):
                    predict(s)

    def test_late_exhibition_or_weather_fails_closed(self):
        for target in ("participant","weather"):
            with self.subTest(target=target):
                s=sample("boat")
                if target=="participant":
                    s["participants"][0]["features"]["motor_form"]["captured_at"]="2030-01-15T11:00:00+09:00"
                else:
                    s["environment"]["wind_mps"]["captured_at"]="2030-01-15T11:00:00+09:00"
                with self.assertRaisesRegex(ModelInputError,"after as_of"):
                    predict(s)

    def test_missing_mandatory_feature_fails(self):
        s=sample("horse")
        del s["participants"][3]["features"]["speed_figure"]
        with self.assertRaisesRegex(ModelInputError,"required features missing"):
            predict(s)

    def test_real_scope_without_external_rights_is_rejected(self):
        s=sample("boat",scope="OPERATOR_SUPPLIED_RESEARCH")
        with self.assertRaisesRegex(ModelInputError,"rights not externally admitted"):
            predict(s)

    def test_repeated_inference_deterministic(self):
        s=sample("boat")
        self.assertEqual(predict(s),predict(copy.deepcopy(s)))

    def test_distinct_from_existing_factor_model(self):
        from race_ai.comprehensive_four_sport_models import predict as old_predict
        s=sample("keirin")
        self.assertNotEqual(old_predict(s)["multisport-factor-interaction-v1"]["candidates"],
                            predict(s)[MODEL_IDS[0]]["candidates"])


if __name__ == "__main__":
    unittest.main()
