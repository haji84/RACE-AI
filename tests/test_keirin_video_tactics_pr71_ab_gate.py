"""All data synthetic: tests real PR71-A evidence gate and video-B research freeze."""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import copy
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_video_tactics_pr71_ab_gate import (
  ABGateError,build_ab,digest,freeze_once)

def h(s):return sha256(s.encode()).hexdigest()
JST=timezone(timedelta(hours=9))

def original():
    a={
        "model_id":"multisport-factor-interaction-v1",
        "model_version":"0.1.0-UNTRAINED",
        "race_id":"202611097403",
        "sport":"keirin",
        "as_of":"2026-11-09T10:00:00+09:00",
        "cutoff_at":"2026-11-09T11:58:00+09:00",
        "trained":False,
        "official_prediction":False,
        "odds_independent":True,
        "snapshot_sha256":h("pre-race-authorized-input"),
        "candidate_count":210,
        "candidates":[{"combination":list(x),"score":1/210}
           for x in itertools.permutations(range(1,8),3)],
    }
    a["prediction_sha256"]=digest(a)
    return a

def past():
    return [{
      "historical_race_id":"20261030-yahiko-3R",
      "rider_name":"坂上忠克",
      "action":"SASHI",
      "reviewed_at":"2026-11-09T09:15:00+09:00",
      "source_video_sha256":h("private historical decoded WebM"),
      "frame_sha256":[h("original t+82"),h("original t+86")],
      "owner_scoped_rights":True,
      "visible_positive_only":True,
      "review_level":"SINGLE_WITH_RESULT_CROSSCHECK",
    }]

def starters():
    return [{"number":i,"rider_name":("坂上忠克" if i==3 else
             f"synthetic-other-rider-{i}")} for i in range(1,8)]

def run(a=None,events=None,t="2026-11-09T10:01:00+09:00",attest=True):
    return build_ab(original() if a is None else a,
             starters(),past() if events is None else events,
             clock=t,
             attest_existing_a=lambda item:attest,
             attest_video=lambda item:attest)

class RealOriginalAndVideoPriorABTests(unittest.TestCase):
    def test_same_real_original_210_triple_a_b_and_fixed_small_change(self):
        record=run()
        self.assertTrue(record["forecast_orig_A_untouched"])
        self.assertEqual(len(record["A"]["candidates"]),210)
        self.assertEqual(len(record["B"]["candidates"]),210)
        self.assertEqual(record["video_B_coefficients_learned"],False)
        self.assertEqual(record["existing_A_model_id"],
           "multisport-factor-interaction-v1")
        self.assertEqual(record["retained_rider_positive_events"][3]["action"],"SASHI")
        self.assertAlmostEqual(sum(x["score"] for x in record["B"]["candidates"]),1,places=10)
        self.assertGreater(next(x["score"] for x in record["B"]["candidates"]
             if x["combination"]==[3,1,2]),1/210)
        self.assertFalse(record["independent_holdout_proof"])
        self.assertFalse(record["outcomes_or_odds_used"])

    def test_fails_closed_without_actual_A_proof(self):
        with self.assertRaisesRegex(ABGateError,"EXISTING_A_ORIGINAL_NOT_INDEPENDENTLY_ATTESTED"):
            run(attest=False)
        a=original();a["model_id"]="invented-model"
        with self.assertRaisesRegex(ABGateError,"EXISTING_PR71_A_REQUIRED"):
            run(a=a)
        a=original();a["candidate_count"]=8
        with self.assertRaisesRegex(ABGateError,"A_FORECAST_DIGEST_CHANGED"):
            run(a=a)
        a=original();a["candidates"]=a["candidates"][:8]
        a["candidate_count"]=8;a["prediction_sha256"]=digest({
            k:v for k,v in a.items() if k!="prediction_sha256"})
        with self.assertRaisesRegex(ABGateError,"PR71_A_210_DISTRIBUTION_MISSING"):
            run(a=a)

    def test_source_result_no_future_leak(self):
        with self.assertRaisesRegex(ABGateError,"A_AFTER_CUTOFF"):
            run(t="2026-11-09T11:58:01+09:00")
        e=past();e[0]["reviewed_at"]="2026-11-09T12:00:00+09:00"
        with self.assertRaisesRegex(ABGateError,"FUTURE_VIDEO_REVIEW_LEAK"):
            run(events=e)
        e=past();e[0]["historical_race_id"]="202611097403"
        with self.assertRaisesRegex(ABGateError,"SAME_RACE_VIDEO_LEAK"):
            run(events=e)

    def test_unknown_rider_is_not_a_negative_video_event(self):
        e=past();e[0]["rider_name"]="rider-not-entered"
        with self.assertRaisesRegex(ABGateError,"NO_MATCHING_PREVIOUS_RIDER_ACTION"):
            run(events=e)

    def test_original_A_and_video_B_cannot_be_overwritten(self):
        report=run()
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"ab.json"
            digest1=freeze_once(p,report)
            self.assertEqual(digest1,sha256(p.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ABGateError,"AB_ALREADY_FROZEN"):
                freeze_once(p,run())
            self.assertEqual(digest1,sha256(p.read_bytes()).hexdigest())

    def test_missing_clip_sha_or_negative_permission_never_trains(self):
        e=past();e[0]["frame_sha256"]=[h("single frame")]
        with self.assertRaisesRegex(ABGateError,"ORIGINAL_VIDEO_FRAME_EVIDENCE_REQUIRED"):
            run(events=e)
        e=past();e[0]["owner_scoped_rights"]=False
        with self.assertRaisesRegex(ABGateError,"RIGHTS_OR_UNOBSERVED_NEGATIVE_RISK"):
            run(events=e)

if __name__=="__main__":unittest.main()
