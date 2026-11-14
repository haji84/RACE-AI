"""Offline tests; all inputs are fictional and never attest source rights."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import itertools
import math
import unittest

from race_ai.boat_multi_feature_models import (
    SCHEMA, MODEL_IDS, FeatureModelError, run_models, validate_snapshot,
    FEATURE_RANGES, CONDITIONS,
)
from race_ai.actions_contract import digest

BASE_TIME = "2030-04-01T10:00:00+09:00"
CUTOFF = "2030-04-01T10:59:00+09:00"
OBSERVED = "2030-04-01T10:40:00+09:00"


def fixture():
    # Per-entrant ratings differ deliberately; it is not copied from a
    # published racing table or a machine-learned real-world fitted dataset.
    entrants=[]
    for lane in range(1,7):
        f={
            "ability_rating":float([81,89,76,94,70,64][lane-1]),
            "recent_form_rating":float([69,80,88,67,75,72][lane-1]),
            "motor_rating":float([60,88,70,91,95,71][lane-1]),
            "course_suitability_rating":float([87,80,73,78,61,55][lane-1]),
            "exhibition_time_seconds":float([6.80,6.77,6.85,6.69,6.76,6.92][lane-1]),
            "exhibition_start_seconds":float([.17,.11,.20,.08,.14,.25][lane-1]),
            "start_consistency_rating":float([80,93,61,85,89,73][lane-1])
        }
        entrants.append({"lane":lane,"participant_id":str(4000+lane),"features":f,
                         "source_ref":"fictional-fixture-provider-"+str(lane),
                         "published_at":BASE_TIME,"captured_at":OBSERVED})
    return {
        "schema":SCHEMA,"scope":"SYNTHETIC_ONLY",
        "race_id":"boat:2030-04-01:synthetic:1",
        "venue":"synthetic-test-venue",
        "event_date_jst":"2030-04-01",
        "sales_cutoff_at":CUTOFF,
        "as_of":"2030-04-01T10:42:00+09:00",
        "entrants":entrants,
        "conditions":{
            "wind_speed_mps":4.0,
            "wave_height_cm":5.0,
            "wind_relative_to_course":0.65,
            "wet_surface_factor":0.0,
        },
        "conditions_source":"fictional-weather-source",
        "conditions_published_at":BASE_TIME,
        "conditions_captured_at":OBSERVED
    }


class MultiFeatureModelsTest(unittest.TestCase):
    def test_both_models_rank_all_120_candidates_and_distinct_identity(self):
        output=run_models(fixture())
        self.assertEqual(tuple(output),MODEL_IDS)
        for name,forecast in output.items():
            with self.subTest(model=name):
                self.assertEqual(len(forecast["candidates"]),120)
                self.assertEqual(len(forecast["ordered_top8"]),8)
                self.assertEqual(len({tuple(x["combination"]) for x in forecast["candidates"]}),120)
                self.assertAlmostEqual(sum(x["score"] for x in forecast["candidates"]),1,places=10)
                self.assertTrue(forecast["odds_independent"])
                self.assertEqual(forecast["model_status"],"RESEARCH_UNTRAINED_NOT_CALIBRATED")
                self.assertFalse(forecast["official_prediction"])
                self.assertIsNone(forecast["persistence_receipt"])
                self.assertIsNone(forecast["official_result"])
                self.assertEqual(forecast["purchase_decision"],"NO_BET")
                self.assertEqual(forecast["prediction_sha256"],digest({k:v for k,v in forecast.items() if k!="prediction_sha256"}))
        self.assertNotEqual(output[MODEL_IDS[0]]["candidates"],
                            output[MODEL_IDS[1]]["candidates"])

    def test_provenance_and_input_hash_separate_with_changed_weather(self):
        s=fixture()
        before=run_models(s)
        s["conditions"]["wave_height_cm"]=180.
        s["conditions"]["wind_speed_mps"]=27.
        after=run_models(s)
        self.assertNotEqual(before[MODEL_IDS[1]]["prediction_sha256"],
                            after[MODEL_IDS[1]]["prediction_sha256"])
        self.assertNotEqual(before[MODEL_IDS[1]]["scenario_weights"],
                            after[MODEL_IDS[1]]["scenario_weights"])

    def test_entrant_strength_change_affects_individual_prediction(self):
        s=fixture()
        baseline=run_models(s)
        s["entrants"][5]["features"]["ability_rating"]=99.
        revised=run_models(s)
        self.assertNotEqual(baseline[MODEL_IDS[0]]["prediction_sha256"],
                            revised[MODEL_IDS[0]]["prediction_sha256"])

    def test_unknown_features_and_outcome_odds_leak_are_rejected(self):
        for field in ("odds","popularity","actual_finish","winning_trifecta",
                      "market_implied_win_probability","result"):
            with self.subTest(field=field):
                s=fixture()
                s["entrants"][0]["features"][field]=0.95
                with self.assertRaisesRegex(FeatureModelError,"exact fields"):
                    run_models(s)
        s=fixture()
        s["conditions"]["payout_yen"]=200
        with self.assertRaisesRegex(FeatureModelError,"exact fields"):
            run_models(s)

    def test_missing_feature_fails_without_stealth_imputation(self):
        for field in FEATURE_RANGES:
            with self.subTest(field=field):
                s=fixture()
                s["entrants"][2]["features"][field]=None
                with self.assertRaisesRegex(FeatureModelError,"missing"):
                    run_models(s)

    def test_late_or_future_entry_is_rejected(self):
        s=fixture()
        s["entrants"][0]["captured_at"]="2030-04-01T11:01:00+09:00"
        with self.assertRaisesRegex(FeatureModelError,"after as_of"):
            run_models(s)
        s=fixture()
        s["conditions_captured_at"]="2030-04-01T10:43:00+09:00"
        with self.assertRaisesRegex(FeatureModelError,"after as_of"):
            run_models(s)

    def test_unverified_cutoff_and_stale_asof_are_rejected(self):
        s=fixture()
        s["as_of"]=CUTOFF
        with self.assertRaisesRegex(FeatureModelError,"before JST sales cutoff"):
            run_models(s)
        s=fixture()
        s["sales_cutoff_at"]="2030-04-02T10:59:00+09:00"
        with self.assertRaisesRegex(FeatureModelError,"JST sales cutoff"):
            run_models(s)

    def test_duplicate_or_false_entrant_identifiers_are_rejected(self):
        s=fixture()
        s["entrants"][1]["lane"]=1
        with self.assertRaisesRegex(FeatureModelError,"unique lanes"):
            run_models(s)
        s=fixture()
        s["entrants"][0]["participant_id"]="not-a-real-id"
        with self.assertRaisesRegex(FeatureModelError,"racer identity"):
            run_models(s)

    def test_negative_and_nonfinite_values_fail_closed(self):
        s=fixture()
        s["conditions"]["wind_speed_mps"]=float("nan")
        with self.assertRaisesRegex(FeatureModelError,"invalid or missing"):
            run_models(s)
        s=fixture()
        s["entrants"][0]["features"]["motor_rating"]=101.
        with self.assertRaisesRegex(FeatureModelError,"invalid or missing"):
            run_models(s)

    def test_source_rights_are_not_created_by_model_output(self):
        result=run_models(fixture())
        for item in result.values():
            self.assertNotIn("source_rights_granted",item)
            self.assertNotIn("external_receipt_verified",item)
            self.assertEqual(item["scope"],"SYNTHETIC_ONLY")
        research=fixture()
        research["scope"]="OPERATOR_SUPPLIED_RESEARCH"
        second=run_models(research)
        self.assertTrue(all(not r["official_prediction"] for r in second.values()))

    def test_feature_allowlist_has_no_market_columns(self):
        serialized=str(FEATURE_RANGES)+str(CONDITIONS)
        for field in ("market","odds","popularity","payout","finish"):
            self.assertNotIn(field,serialized)

if __name__=="__main__":
    unittest.main()
