"""Offline synthetic-only retrospective blind video holdout regression."""
import copy
from datetime import datetime,timedelta,timezone
from hashlib import sha256 as hash_fn
import unittest

from race_ai.keirin_historical_holdout import (
    BLIND,TRUTH,HoldoutError,sha,validate_predictions,validate_truth,score,
    build_blind)

LABELS=("START","HOME_PASS","HOME_PASS","HOME_PASS","HOME_PASS",
        "GOAL","REPLAY_START","REPLAY_END","RESULT")
TIMES=(192,246,295,337,384,389,403,431,517)
STAMP="2026-11-09T00:20:00+09:00"
REVIEW="2026-11-09T00:25:00+09:00"

def h(s): return hash_fn(s.encode()).hexdigest()

def blank():
    base={"schema":BLIND,"race_id":"20261108-matsuyama-9R",
       "source":"WINTICKET_LIVE","recording_sha256":h("synthetic source"),
       "duration_s":625.0,"model_sha256":h("synthetic model"),
       "model_train_races":["20261106-another-1R","20261107-another-2R"],
       "model_dev_races":["20261108-matsuyama-1R"],
       "events":[
           {"id":f"p-{i}","time_s":float(time)+.3,
            "event":event,"frame_sha256":h(f"pred-{i}"),
            "confidence":.94}
           for i,(event,time) in enumerate(zip(LABELS,TIMES))],
       "frozen_at":STAMP,"video_input_labels_used":False,
       "forecast_modified":False}
    base["prediction_sha256"]=sha(base)
    return base

def labels():
    t={"schema":TRUTH,"race_id":"20261108-matsuyama-9R",
       "recording_sha256":h("synthetic source"),
       "duration_s":625.0,"review_type":"INDEPENDENT_FRAME_REVIEW",
       "reviewed_at":REVIEW,
       "events":[
          {"id":f"truth-{i}","time_s":float(time),
           "event":event,"frame_sha256":h(f"verified-frame-{i}"),
           "review_ref":f"independent-review-{i}"}
          for i,(event,time) in enumerate(zip(LABELS,TIMES))]
       }
    t["review_sha256"]=sha(t)
    return t

def sealed(obj, field): 
    obj[field]=sha({k:v for k,v in obj.items() if k!=field})
    return obj

CALLBACKS={"frozen_prediction_attestor":lambda prediction: True,
           "independent_review_attestor":lambda reviewed: True,
           "source_rights_attestor":lambda source,purpose: True}

class BlindedHistoricalHoldoutTests(unittest.TestCase):
    def test_one_to_one_4_laps_goal_and_replay_accepts_independent_real_review(self):
        p,t=blank(),labels()
        out=score(p,t,**CALLBACKS)
        self.assertEqual(out["status"],"BLIND_HISTORICAL_HOLDOUT_PASSED")
        self.assertTrue(out["lap_pass_all_four_matched"])
        self.assertTrue(out["goal_matched"])
        self.assertTrue(out["replay_regions_matched"])
        self.assertEqual(out["replay_as_lap_false_positive_count"],0)
        self.assertEqual(out["metrics"]["HOME_PASS"]["true_positive"],4)
        self.assertEqual(out["metrics"]["HOME_PASS"]["false_positive"],0)
        self.assertEqual(out["metrics"]["GOAL"]["true_positive"],1)
        self.assertEqual(out["learning_policy"],"DO_NOT_TRAIN_ON_HELDOUT_RACE")

    def test_model_freeze_excludes_dev_race_before_truth_is_available(self):
        from race_ai.keirin_video_learning import MODEL_SCHEMA,digest
        model={"schema":MODEL_SCHEMA,"validation_status":"RESEARCH_HOLDOUT_PASSED",
               "train_races":["20261105-example-1R"],
               "dev_races":["20261108-matsuyama-9R"]}
        model["model_sha256"]=digest(model)
        p=blank()
        queue={"input":{
            "race_id":p["race_id"],"recording_sha256":p["recording_sha256"],
            "duration_s":p["duration_s"],"source":"WINTICKET_LIVE",
            "inference_model":model["model_sha256"],
            "observations":[{
                "id":row["id"],"recording_sec":row["time_s"],
                "event":row["event"],"frame_sha256":row["frame_sha256"],
                "confidence":row["confidence"]}
                for row in p["events"]]}}
        with self.assertRaisesRegex(HoldoutError,"HOLDOUT_NOT_INDEPENDENT"):
            build_blind(queue,model,frozen_at=STAMP)
        model["dev_races"]=[]
        model["model_sha256"]=digest({k:v for k,v in model.items()
                                      if k!="model_sha256"})
        queue["input"]["inference_model"]=model["model_sha256"]
        prediction=build_blind(queue,model,frozen_at=STAMP)
        self.assertEqual(prediction["prediction_sha256"],
                         sha({k:v for k,v in prediction.items()
                              if k!="prediction_sha256"}))
        self.assertFalse(prediction["video_input_labels_used"])
        self.assertNotIn("ordered_top3",prediction)

    def test_replay_home_pass_cannot_be_counted_as_new_lap(self):
        p,t=blank(),labels()
        insert={"id":"replay-duplicate","time_s":420.0,"event":"HOME_PASS",
                "frame_sha256":h("replayed footage"),"confidence":0.99}
        p["events"].insert(-2,insert)
        sealed(p,"prediction_sha256")
        out=score(p,t,**CALLBACKS)
        self.assertEqual(out["status"],"HISTORICAL_HOLDOUT_NOT_ACCEPTED")
        self.assertEqual(out["replay_as_lap_false_positive_count"],1)
        self.assertFalse(out["lap_pass_all_four_matched"])
        self.assertEqual(out["metrics"]["HOME_PASS"]["false_positive"],1)

    def test_missing_goals_and_replay_markers_fail(self):
        p,t=blank(),labels()
        p["events"]=[x for x in p["events"] if x["event"]!="GOAL"]
        sealed(p,"prediction_sha256")
        out=score(p,t,**CALLBACKS)
        self.assertFalse(out["goal_matched"])
        self.assertEqual(out["status"],"HISTORICAL_HOLDOUT_NOT_ACCEPTED")
        p=blank()
        p["events"]=[x for x in p["events"] if x["event"]!="REPLAY_END"]
        sealed(p,"prediction_sha256")
        out=score(p,t,**CALLBACKS)
        self.assertFalse(out["replay_regions_matched"])

    def test_development_9r_not_allowed_as_blind_holdout(self):
        p=blank()
        p["model_dev_races"].append("20261108-matsuyama-9R")
        sealed(p,"prediction_sha256")
        with self.assertRaisesRegex(HoldoutError,"TEST_RACE_ALREADY_USED_FOR_MODEL_TUNING"):
            validate_predictions(p)
        p=blank()
        p["model_train_races"].append("20261108-matsuyama-9R")
        sealed(p,"prediction_sha256")
        with self.assertRaisesRegex(HoldoutError,"TEST_RACE_IN_TRAINING_DATA"):
            validate_predictions(p)

    def test_tampering_prediction_or_labels_rejected(self):
        p,t=blank(),labels()
        p["events"][0]["time_s"]=10.
        with self.assertRaisesRegex(HoldoutError,"BLIND_DIGEST_MISMATCH"):
            validate_predictions(p)
        t["events"][0]["time_s"]=20.
        with self.assertRaisesRegex(HoldoutError,"TRUTH_DIGEST_MISMATCH"):
            validate_truth(t)

    def test_results_cannot_be_used_as_video_input(self):
        p=blank()
        p["actual_ordered_top3"]=[1,2,7]
        with self.assertRaisesRegex(HoldoutError,"INVALID_BLIND_SCHEMA"):
            validate_predictions(p)

    def test_untrusted_review_and_missing_witnesses(self):
        p,t=blank(),labels()
        with self.assertRaisesRegex(HoldoutError,"OUT_OF_BAND_WITNESSES_REQUIRED"):
            score(p,t)
        t["reviewed_at"]="2026-11-09T00:15:00+09:00"
        sealed(t,"review_sha256")
        with self.assertRaisesRegex(HoldoutError,
                "TRUTH_REVIEWED_BEFORE_BLIND_PREDICTION_FREEZE"):
            score(p,t,**CALLBACKS)
        t=labels()
        with self.assertRaisesRegex(HoldoutError,"UNVERIFIED_FREEZE_REVIEW_OR_RIGHTS"):
            score(p,t,**{**CALLBACKS,
                         "independent_review_attestor":lambda x:False})

    def test_synthetic_heldout_results_are_never_real_proof(self):
        p,t=blank(),labels()
        t["review_type"]="SYNTHETIC_FIXTURE"
        sealed(t,"review_sha256")
        out=score(p,t,**CALLBACKS)
        self.assertEqual(out["status"],"HISTORICAL_HOLDOUT_NOT_ACCEPTED")
        self.assertFalse(out["learning_policy"]!="DO_NOT_TRAIN_ON_HELDOUT_RACE")

    def test_false_replay_label_never_self_confirms(self):
        p,t=blank(),labels()
        t["events"]=[x for x in t["events"]
                     if x["event"] not in ("REPLAY_START","REPLAY_END")]
        sealed(t,"review_sha256")
        out=score(p,t,**CALLBACKS)
        self.assertFalse(out["replay_regions_matched"])
        self.assertEqual(out["status"],"HISTORICAL_HOLDOUT_NOT_ACCEPTED")

if __name__=="__main__":
    unittest.main()
