"""Fixture-only tests for partial-highlight research scene training.

These fabricated frames are never evidence that real WINTICKET training
permissions were granted or that real riders/laps were classified correctly.
"""
import copy
from hashlib import sha256
import unittest

from race_ai.keirin_video_clip_policy import (
    CLIP_SCHEMA, assess_clip, choose_preferred_clips, digest as clip_digest)
from race_ai.keirin_video_learning import FEATURE_SCHEMA, SceneLearningError
from race_ai.keirin_video_partial_learning import (
    PARTIAL_MODEL_SCHEMA, train_partial_scene_model,
    predict_visible_scene, extract_training_rows)

def h(s):return sha256(s.encode()).hexdigest()
CATS=("ATTACK","GOAL","REPLAY","RACING")

def source_bundle(race_num, *, full=False):
    race=f"202610{race_num+20}-yahiko-{race_num}R"
    video_sha=h(f"fabricated-test-video-{race_num}-{'full' if full else 'short'}")
    clip={
        "schema":CLIP_SCHEMA,"race_id":race,
        "source_url":"https://www.winticket.jp/keirin/yahiko/raceresult/2026103021/1/1",
        "source_kind":"WINTICKET_PAST_REPLAY",
        "recording_sha256":video_sha,
        "duration_s":90.0,
        "claimed_coverage":"FULL_FOUR_LAPS" if full else "PARTIAL_HIGHLIGHTS",
        "reviewed_at":"2026-11-09T02:00:00+09:00",
        "events":[]
    }
    frames=[]
    idx=0
    for label_idx,label in enumerate(CATS):
        for n in range(5):
            idx+=1
            key=h(f"fake-frame-{race_num}-{full}-{label_idx}-{n}")
            v=[0.0]*196
            v[label_idx]=10.
            v[8]=n*.008
            v[9]=race_num*.007
            clip["events"].append({
                "id":f"e-{idx}","time_s":idx*2.0,
                "label":label,"rider_id":"rider-001" if label=="ATTACK" else None,
                "action_key":f"action-{idx}",
                "frame_sha256":key,
                "scene":"REPLAY" if label=="REPLAY" else "LIVE",
                "review_ref":f"private-reviewed-test-frame-{idx}"
            })
            frames.append({"t":idx*2.0,"frame_sha256":key,
                           "phash64":f"{idx:016x}","vector":v})
    full_receipt=({"status":"FOUR_LAPS_VISUALLY_VERIFIED",
                   "race_id":race,"recording_sha256":video_sha} if full else None)
    admission=assess_clip(
        clip,independent_visual_verifier=lambda x:True,
        rights_verifier=lambda x,y:True,
        full_lap_audit=full_receipt,
        lap_audit_verifier=(lambda x,y:True) if full else None)
    feature_doc={
        "schema":FEATURE_SCHEMA,"race_id":race,"recording_sha256":video_sha,
        "feature_version":"HSV_GRID_EDGE_7x28_v1",
        "features":frames
    }
    return {"features":feature_doc,"admission":admission}

class PartialShortReplayLearningTests(unittest.TestCase):
    def setUp(self):
        self.bundles=[source_bundle(i) for i in range(1,4)]

    def test_both_partial_and_full_are_eligible_but_full_is_preferred(self):
        good=self.bundles[0]
        full=source_bundle(1,full=True)
        self.assertTrue(good["admission"]["training_eligible"])
        self.assertFalse(good["admission"]["all_four_laps_verified"])
        self.assertTrue(full["admission"]["all_four_laps_verified"])
        selected=choose_preferred_clips([good["admission"],full["admission"]])
        self.assertEqual(selected["full_count"],1)
        self.assertEqual(selected["partial_count"],0)
        data,chosen=extract_training_rows(
            self.bundles+[full],
            trusted_admission_verifier=lambda x:True)
        self.assertEqual(len(chosen),3)
        self.assertIn(full["admission"]["recording_sha256"],
                      {row["source_recording_sha256"] for row in data})
        self.assertNotIn(good["admission"]["recording_sha256"],
                         {row["source_recording_sha256"] for row in data})

    def test_three_reviewed_short_clips_train_with_one_race_held_out(self):
        model=train_partial_scene_model(
            self.bundles,trusted_admission_verifier=lambda x:True)
        self.assertEqual(model["schema"],PARTIAL_MODEL_SCHEMA)
        self.assertEqual(model["full_video_sources"],0)
        self.assertEqual(model["partial_video_sources"],3)
        self.assertEqual(model["validation_status"],"RESEARCH_SCENE_HOLDOUT_PASSED")
        self.assertEqual(model["holdout_macro_f1"],1.0)
        self.assertFalse(model["four_laps_certified"])
        self.assertTrue(model["never_treats_unseen_attack_as_negative"])
        self.assertEqual(len(model["heldout_races"]),1)
        src=self.bundles[0]["features"]["features"][0]
        pred=predict_visible_scene(model,src,race_id="20261104-yahiko-4R")
        self.assertEqual(pred["label"],"ATTACK")
        self.assertFalse(pred["rider_identity_proven"])
        self.assertFalse(pred["event_is_reviewed"])
        self.assertFalse(pred["four_laps_proven"])

    def test_no_rights_witness_or_review_ref_blocks_actual_training(self):
        with self.assertRaisesRegex(SceneLearningError,
                                    "INDEPENDENT_ADMISSION_ATTESTOR_REQUIRED"):
            train_partial_scene_model(
                self.bundles,trusted_admission_verifier=None)
        with self.assertRaisesRegex(SceneLearningError,
                                    "OWNER_RIGHTS_AND_REVIEW_ATTESTATION_MISSING"):
            train_partial_scene_model(
                self.bundles,trusted_admission_verifier=lambda x:False)
        tampered=copy.deepcopy(self.bundles)
        tampered[0]["admission"]["training_eligible"]=False
        with self.assertRaisesRegex(Exception,"INVALID_ADMISSION_INTEGRITY"):
            train_partial_scene_model(
                tampered,trusted_admission_verifier=lambda x:True)

    def test_no_video_frames_or_mismatched_sha_is_rejected(self):
        corrupt=copy.deepcopy(self.bundles)
        corrupt[0]["features"]["recording_sha256"]=h("different source")
        with self.assertRaisesRegex(SceneLearningError,"VIDEO_AND_FRAME_PROVENANCE_MISMATCH"):
            train_partial_scene_model(
                corrupt,trusted_admission_verifier=lambda x:True)
        missing=copy.deepcopy(self.bundles)
        missing[0]["features"]["features"].pop()
        with self.assertRaisesRegex(SceneLearningError,"REVIEWED_FRAME_NOT_IN_VIDEO"):
            train_partial_scene_model(
                missing,trusted_admission_verifier=lambda x:True)

    def test_other_race_can_not_reuse_recording_sha_or_frames(self):
        repeated=copy.deepcopy(self.bundles)
        repeated[1]["admission"]["recording_sha256"]=repeated[0]["admission"]["recording_sha256"]
        repeated[1]["admission"]["admission_sha256"]=clip_digest({
            k:v for k,v in repeated[1]["admission"].items()
            if k!="admission_sha256"})
        repeated[1]["features"]["recording_sha256"]=repeated[1]["admission"]["recording_sha256"]
        with self.assertRaisesRegex(SceneLearningError,"CROSS_RACE_DUPLICATE_RECORDING"):
            train_partial_scene_model(
                repeated,trusted_admission_verifier=lambda x:True)

    def test_training_race_does_not_certify_itself(self):
        model=train_partial_scene_model(
            self.bundles,trusted_admission_verifier=lambda x:True)
        frame=self.bundles[0]["features"]["features"][0]
        for known in model["train_races"]+model["heldout_races"]:
            with self.assertRaisesRegex(SceneLearningError,"SCENE_TEST_RACE_CONTAMINATED"):
                predict_visible_scene(model,frame,race_id=known)

    def test_single_clip_is_not_enough_for_proven_model(self):
        with self.assertRaisesRegex(SceneLearningError,"NOT_ENOUGH_REAL_REVIEWED_RACES"):
            train_partial_scene_model(
                self.bundles[:1],trusted_admission_verifier=lambda x:True)

if __name__=="__main__":unittest.main()
