"""Synthetic-only temporal evidence gate for partial historic keirin clip PDCA."""
import copy
from hashlib import sha256
import unittest

from race_ai.keirin_video_clip_policy import CLIP_SCHEMA,assess_clip
from race_ai.keirin_video_postrace_pdca import (
    create_partial_postrace_learning_candidate, EvidenceError)

def h(v):return sha256(v.encode()).hexdigest()

def reviewed_short_clip():
    doc={
        "schema":CLIP_SCHEMA,"race_id":"20261030-yahiko-1R",
        "source_url":"https://www.winticket.jp/keirin/yahiko/raceresult/2026103021/1/1",
        "source_kind":"WINTICKET_PAST_REPLAY",
        "recording_sha256":h("fabricated-private-clip"),
        "duration_s":80.164,"claimed_coverage":"PARTIAL_HIGHLIGHTS",
        "reviewed_at":"2026-11-09T02:30:00+09:00",
        "events":[
            {"id":"attack","time_s":15.,"label":"ATTACK",
             "rider_id":"rider-01","action_key":"attack-a",
             "frame_sha256":h("attack-frame"),"scene":"LIVE",
             "review_ref":"independent-attack-frame"},
            {"id":"attack-replay","time_s":34.,"label":"ATTACK",
             "rider_id":"rider-01","action_key":"attack-a",
             "frame_sha256":h("attack-replay-frame"),"scene":"REPLAY",
             "review_ref":"independent-replay-frame"},
            {"id":"goal","time_s":74.,"label":"GOAL",
             "rider_id":None,"action_key":"goal-scene",
             "frame_sha256":h("goal-frame"),"scene":"LIVE",
             "review_ref":"independent-goal-frame"},
        ]}
    return assess_clip(doc,independent_visual_verifier=lambda x:True,
                       rights_verifier=lambda source,purpose:True)

def pre():
    return {"race_id":"20261030-yahiko-1R",
            "original_sha256":h("frozen-real-pre-cutoff-original-fixture"),
            "saved_at":"2026-10-30T15:00:00+09:00",
            "official_cutoff_at":"2026-10-30T16:00:00+09:00"}

def result():
    return {"race_id":"20261030-yahiko-1R",
            "published_at":"2026-10-30T17:00:00+09:00",
            "ordered_top3":[3,2,4]}

def witnesses():
    return {
      "trusted_admission_verifier":lambda x:True,
      "frozen_receipt_verifier":lambda x:True,
      "official_result_verifier":lambda x:True,
      "rights_checker":lambda source,purpose:True,
    }

class PartialPostraceLearningTests(unittest.TestCase):
    def test_short_replay_can_supply_later_positive_attack_and_goal(self):
        item=create_partial_postrace_learning_candidate(
            reviewed_short_clip(),pre(),result(),**witnesses())
        self.assertEqual(item["admitted_coverage"],"PARTIAL_HIGHLIGHTS")
        self.assertFalse(item["four_laps_proven"])
        self.assertEqual(item["unobserved_rider_actions"],"UNKNOWN_NOT_NEGATIVE")
        self.assertEqual(item["unobserved_laps"],"UNKNOWN_NOT_ZERO")
        self.assertEqual(len(item["verified_actions_positive_only"]),1)
        self.assertEqual(item["verified_actions_positive_only"][0]["observed_action"],"ATTACK")
        self.assertEqual(len(item["verified_finish_scenes"]),1)
        self.assertEqual(item["verified_finish_scenes"][0]["label"],"GOAL")
        self.assertFalse(item["probabilities_or_accuracy_improved"])
        self.assertEqual(item["training_status"],"PRIVATE_RESEARCH_CANDIDATE_NOT_FITTED")

    def test_missing_real_independent_witnesses_rejected(self):
        with self.assertRaisesRegex(EvidenceError,"INDEPENDENT_ATTESTORS_REQUIRED"):
            create_partial_postrace_learning_candidate(
                reviewed_short_clip(),pre(),result())
        with self.assertRaisesRegex(EvidenceError,"PARTIAL_FRAME_OR_RIGHTS_NOT_ATTESTED"):
            create_partial_postrace_learning_candidate(
                reviewed_short_clip(),pre(),result(),
                **{**witnesses(),"rights_checker":lambda x,y:False})

    def test_immutability_and_result_timeline_required(self):
        old=pre()
        old["saved_at"]="2026-10-30T16:30:00+09:00"
        with self.assertRaisesRegex(EvidenceError,"FORECAST_VIDEO_OR_RESULT_TIME_LEAK"):
            create_partial_postrace_learning_candidate(
                reviewed_short_clip(),old,result(),**witnesses())
        o=result()
        o["race_id"]="other-race"
        with self.assertRaisesRegex(EvidenceError,"RACE_ID_MISMATCH"):
            create_partial_postrace_learning_candidate(
                reviewed_short_clip(),pre(),o,**witnesses())

    def test_forged_admission_digest_rejected(self):
        a=reviewed_short_clip()
        a["admitted_coverage"]="FULL_FOUR_LAPS"
        with self.assertRaisesRegex(EvidenceError,"INVALID_PARTIAL_ADMISSION_PROOF"):
            create_partial_postrace_learning_candidate(
                a,pre(),result(),**witnesses())

    def test_no_video_label_false_negatives(self):
        a=reviewed_short_clip()
        out=create_partial_postrace_learning_candidate(a,pre(),result(),
                                                         **witnesses())
        self.assertNotIn("did_not_attack",str(out))
        self.assertNotIn("zero_laps",str(out))
        self.assertFalse(out["no_same_race_pre_cutoff_features"] is False)

if __name__=="__main__":
    unittest.main()
