"""Invented matrices and locally generated moving pixels, never real race images."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np

from race_ai.keirin_daily_video_research import (
 FEATURE_SCHEMA,MODEL_SCHEMA,ResearchInputError,digest,frame_features,
 read_private_video,make_review_queue,fit_private_representation
)

def synthetic_doc(i,cohort):
    frames=[]
    for t in range(24):
        vector=[0.0]*196
        vector[(t%6)+i]=float((t%6+1)*0.1)
        vector[50]=i/10
        frames.append({
          "capture_second":t*2,
          "frame_sha256":hashlib.sha256(f"{i}.{t}".encode()).hexdigest(),
          "p_hash64":f"{t:016x}",
          "motion_scene_change_score":float((t%6)/10),
          "features":vector,
          "action_identity_verified":False,
          "tactical_label":"UNKNOWN_UNREVIEWED"})
    d={
      "schema":FEATURE_SCHEMA,"race_id":f"20261109-{i}",
      "cohort":cohort,
      "browser_video_sha256":hashlib.sha256(f"synthetic source {i}".encode()).hexdigest(),
      "source_bytes":25000,
      "browser_recording_duration_s":80.0,
      "sampling_seconds":2,"frames":frames,
      "real_source":True,"video_visible_event_labels_are_unknown":True,
      "all_four_laps_claimed":False,"official_prediction_modified":False,
    }
    d["feature_sha256"]=digest(d)
    return d

class DailyVideoResearchTests(unittest.TestCase):
    def test_196_feature_extract_from_synthetic_frame(self):
        frame=np.zeros((720,1280,3),dtype=np.uint8)
        frame[200:540,400:880,1]=155
        f=frame_features(frame)
        self.assertEqual(len(f["vector"]),196)
        self.assertEqual(len(f["crop_sha256"]),64)
        self.assertEqual(len(f["p_hash64"]),16)
        self.assertTrue(np.all(np.isfinite(f["vector"])))
    def test_preview_queue_never_fabricates_rider_or_winning_tactic(self):
        doc=synthetic_doc(1,"TRAIN_CANDIDATE")
        queue=make_review_queue([doc],peak_count=3)
        self.assertEqual(queue["candidate_count"],3)
        self.assertTrue(all(x["tactical_label"]=="UNKNOWN_UNREVIEWED"
                  and x["rider_id"] is None and not x["learnable_yet"]
                  for x in queue["candidates"]))
    def test_two_training_races_and_independent_holdout_fits_visual_only(self):
        docs=[synthetic_doc(1,"TRAIN_CANDIDATE"),
              synthetic_doc(2,"TRAIN_CANDIDATE"),
              synthetic_doc(3,"UNSEEN_VIDEO_HOLDOUT")]
        model=fit_private_representation(docs,n_clusters=3)
        self.assertEqual(model["status"],
            "RESEARCH_SELF_SUPERVISED_MODEL_FITTED_NOT_PREDICTIVE_PROOF")
        self.assertEqual(model["train_frames"],48)
        self.assertEqual(model["holdout_frames"],24)
        self.assertFalse(model["improvement_proven"])
        self.assertEqual(model["real_trifecta_A_B_forecasts_compared"],0)
        self.assertFalse(model["production_model_weights_updated"])
        self.assertEqual(model["model_sha256"],digest({
                  k:v for k,v in model.items() if k!="model_sha256"}))
    def test_insufficient_holdout_returns_no_model(self):
        docs=[synthetic_doc(1,"TRAIN_CANDIDATE"),
              synthetic_doc(2,"TRAIN_CANDIDATE")]
        model=fit_private_representation(docs)
        self.assertEqual(model["status"],
                         "TRAIN_OR_HOLDOUT_EVIDENCE_INSUFFICIENT")
        self.assertIsNone(model["empirical_forecast_improvement"])
    def test_source_sha_and_cohort_integrity_rejects_tampering(self):
        docs=[synthetic_doc(1,"TRAIN_CANDIDATE"),
              synthetic_doc(2,"TRAIN_CANDIDATE"),
              synthetic_doc(3,"UNSEEN_VIDEO_HOLDOUT")]
        docs[0]["cohort"]="UNSEEN_VIDEO_HOLDOUT"
        with self.assertRaisesRegex(ResearchInputError,
                                     "FEATURE_SOURCE_INTEGRITY_FAILURE"):
            fit_private_representation(docs)
        docs[0]=synthetic_doc(1,"TRAIN_CANDIDATE")
        docs[1]["browser_video_sha256"]=docs[0]["browser_video_sha256"]
        docs[1]["feature_sha256"]=digest({
               k:v for k,v in docs[1].items() if k!="feature_sha256"})
        with self.assertRaisesRegex(ResearchInputError,
                 "DUPLICATE_SOURCE_VIDEO_ACROSS_RACES"):
            fit_private_representation(docs)

    def test_fake_local_movie_is_not_claimed_as_a_real_competition(self):
        # Only locally drawn moving pixels, never video from WINTICKET.
        import cv2
        with tempfile.TemporaryDirectory() as t:
            file=Path(t)/"synthetic.avi"
            writer=cv2.VideoWriter(str(file),cv2.VideoWriter_fourcc(*"MJPG"),
                10.0,(320,180))
            self.assertTrue(writer.isOpened())
            for n in range(330):
                frame=np.full((180,320,3),n%195,dtype=np.uint8)
                cv2.rectangle(frame,(n%100,35),(n%100+70,100),
                              (65,180,20),-1)
                writer.write(frame)
            writer.release()
            doc=read_private_video(file,race_id="SYNTHETIC_RACE_ONLY",
                     cohort="TRAIN_CANDIDATE",every_s=2)
            self.assertEqual(doc["schema"],FEATURE_SCHEMA)
            self.assertFalse(doc["all_four_laps_claimed"])
            self.assertTrue(doc["video_visible_event_labels_are_unknown"])
            self.assertGreaterEqual(len(doc["frames"]),12)
if __name__=="__main__":unittest.main()
