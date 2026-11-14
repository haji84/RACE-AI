"""Synthetic replay/prediction audit regression. NO real proprietary forecast input."""
import copy
from datetime import datetime,timezone
from hashlib import sha256
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from scripts.keirin_video_forecast_real_uplift_gate import (
    audit, probability_slate, METHODS,TRAIN_ROSTERS)

def sha(x):return sha256(x.encode()).hexdigest()

def source(as_of="2026-11-08T20:43:43+09:00"):
    perms=list(itertools.permutations(range(1,8),3))
    rows=[]
    for triple in perms:
        d={"combination":"-".join(map(str,triple))}
        for m in METHODS:d[m]=1./210
        rows.append(d)
    return {
        "schema":"MATS2R_RESEARCH_SCENARIO_PREDICTION_V1",
        "status":"research_only_uncalibrated_no_official_frozen_proof",
        "race":{
          "date_jst":"2026-11-08","venue":"松山","race_number":2,
          "as_of_jst":as_of,"sales_cutoff_jst":"20:55",
          "scheduled_start_jst":"21:00"},
        "participants":[
          {"n":1,"name":"中川飛隆"},{"n":2,"name":"福地晶"},
          {"n":3,"name":"小林和彦"},{"n":4,"name":"関根崇人"},
          {"n":5,"name":"吉田英二"},{"n":6,"name":"森佑樹"},
          {"n":7,"name":"藤原義浩"}],
        "all_210":rows,
        "methodology":{"model_family":"SYNTHETIC_UNIFORM_FIXTURE"}
    }

def receipt():
    return {
        "schema":"RACE_AI_REAL_SHORT_CLIP_SCENE_RESEARCH_V1",
        "train_races":list(TRAIN_ROSTERS),
        "classes":["GOAL","LINEUP","RACING","RESULT"],
        "labeled_rows":91,"sha_frozen_at":"2026-11-08T23:04:05+00:00",
        "independent_second_review_complete":False,
        "goal_scene_trained":True,
        "real_rider_attack_identity_labels_trained":False,
        "model_sha256":sha("fixture-scene-model")
    }

class ActualUpliftEligibilityTests(unittest.TestCase):
    def _evaluate(self,base,receipt):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/"base.json";b=Path(d)/"receipt.json"
            a.write_text(json.dumps(base));b.write_text(json.dumps(receipt))
            return audit(a,b)

    def test_actual_logic_refuses_to_claim_trifecta_uplift_from_scene_labels(self):
        result=self._evaluate(source(),receipt())
        self.assertFalse(result["baseline_mean"]["hit_at_8"] is None)
        self.assertEqual(result["video_model_210_probabilities_available"],False)
        self.assertEqual(result["real_eligible_ab_races"],0)
        self.assertEqual(result["same_riders_in_training_and_target"],[])
        self.assertTrue(result["training_model_after_target_as_of"])
        self.assertIsNone(result["uplift_top8_pct_points"])
        self.assertEqual(result["promotion_decision"],
            "FAIL_CLOSED_NO_VERIFIED_VIDEO_FORECAST_UPLIFT")
        self.assertIn("NO_FROZEN_VIDEO_BASED_210_PROBABILITY_DISTRIBUTION",
            result["failed_requirements"])
        self.assertTrue(result["research_other_scenarios_do_not_prove_video_uplift"])

    def test_210_full_slate_is_required(self):
        s=source();s["all_210"]=s["all_210"][:-1]
        with self.assertRaisesRegex(ValueError,"NOT_ALL_210_COMBINATIONS"):
            self._evaluate(s,receipt())

    def test_no_duplicate_or_missing_triple(self):
        s=source();s["all_210"][1]["combination"]=s["all_210"][0]["combination"]
        with self.assertRaisesRegex(ValueError,"BAD_OR_DUPLICATE_COMBINATION"):
            self._evaluate(s,receipt())

    def test_frozen_baseline_cannot_be_after_betting_cutoff(self):
        with self.assertRaisesRegex(ValueError,"FORECAST_AFTER_CUTOFF"):
            self._evaluate(source("2026-11-08T20:55:01+09:00"),receipt())

    def test_future_video_scene_model_not_prospectively_available(self):
        result=self._evaluate(source(),receipt())
        self.assertIn("VIDEO_MODEL_BUILT_AFTER_TARGET_FORECAST_AS_OF",
            result["failed_requirements"])
        self.assertEqual(result["verified_rider_tactics_labels_trained"],False)
        self.assertFalse(result["official_model_weights_modified"])

if __name__=="__main__":
    unittest.main()
