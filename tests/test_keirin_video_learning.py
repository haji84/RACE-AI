"""All training inputs synthetic. Never pretend one actual 9R is enough to train."""
import copy
import hashlib
import math
from pathlib import Path
from unittest.mock import patch
import tempfile
import subprocess
import unittest

from race_ai.keirin_video_learning import (
    CLASSES,FEATURE_SCHEMA,SceneLearningError,train_reviewed_classifier,
    validated_rows, predict_scene,sample_private_video,
    bind_reviewed_labels_to_frames)
from race_ai.keirin_video_inference import to_review_queue

def sha(x):return hashlib.sha256(x.encode()).hexdigest()

def vec(label,race_idx=0,index=0):
    x=[.0]*196
    k=CLASSES.index(label)
    x[k]=7.0
    x[7]=race_idx*.02
    x[8]=index*.001
    return x

def docs(num_races=3):
    out=[]
    for r in range(num_races):
        samples=[]
        for label in CLASSES:
            for i in range(5):
                samples.append({
                    "frame_sha256":sha(f"synthetic-{r}-{label}-{i}"),
                    "label":label,"vector":vec(label,r,i),
                    "reviewed":True,"review_ref":f"synthetic-review-{r}-{label}-{i}"})
        out.append({
            "schema":"RACE_AI_KEIRIN_REVIEWED_SCENES_V1",
            "race_id":f"synthetic-2026110{r+1}-matsuyama-{r+1}R",
            "recording_sha256":sha(f"synthetic-recording-{r}"),
            "samples":samples})
    return out

class LearningTests(unittest.TestCase):
    def test_must_have_multiple_independent_reviewed_races(self):
        with self.assertRaisesRegex(SceneLearningError,
                                     "NOT_ENOUGH_DISTINCT_VERIFIED_RACES"):
            train_reviewed_classifier(docs(1))
        bad=docs()
        bad[0]["samples"][0]["reviewed"]=False
        with self.assertRaisesRegex(SceneLearningError,"TRAINING_LABEL_NOT_HUMAN_REVIEWED"):
            train_reviewed_classifier(bad)

    def test_review_labels_must_match_real_feature_hashes(self):
        recording=sha("video-1")
        h=sha("frame-1")
        feature={"schema":FEATURE_SCHEMA,"race_id":"race-A",
                 "recording_sha256":recording,
                 "feature_version":"HSV_GRID_EDGE_7x28_v1",
                 "features":[{"frame_sha256":h,"vector":vec("START")}]}
        review={"schema":"RACE_AI_KEIRIN_FRAME_REVIEW_V1",
                "race_id":"race-A","recording_sha256":recording,
                "feature_version":"HSV_GRID_EDGE_7x28_v1",
                "labels":[{"frame_sha256":h,"label":"START",
                           "reviewed":True,"review_ref":"private-review-1"}]}
        bound=bind_reviewed_labels_to_frames(feature,review)
        self.assertEqual(bound["samples"][0]["vector"],vec("START"))
        altered=copy.deepcopy(review)
        altered["labels"][0]["frame_sha256"]=sha("other image")
        with self.assertRaisesRegex(SceneLearningError,"LABEL_NOT_IN_SAME_VERIFIED_VIDEO"):
            bind_reviewed_labels_to_frames(feature,altered)
        wrong_clip=copy.deepcopy(review)
        wrong_clip["recording_sha256"]=sha("different recording")
        with self.assertRaisesRegex(SceneLearningError,"FEATURE_REVIEW_SOURCE_CONFLICT"):
            bind_reviewed_labels_to_frames(feature,wrong_clip)

    def test_train_with_heldout_race_and_predict(self):
        model=train_reviewed_classifier(docs())
        self.assertEqual(model["validation_status"],"RESEARCH_HOLDOUT_PASSED")
        self.assertEqual(len(model["heldout_races"]),1)
        self.assertEqual(len(model["train_races"]),2)
        self.assertEqual(model["holdout_macro_f1"],1.0)
        pred=predict_scene(model,{"vector":vec("HOME_PASS",5),
            "frame_sha256":sha("test"),"t":25})
        self.assertEqual(pred["label"],"HOME_PASS")
        self.assertTrue(pred["score_not_calibrated"])
        self.assertGreater(pred["score"],0.85)
        self.assertIn("REPLAY",pred["class_scores"])
        broken=copy.deepcopy(model)
        broken["weights"][0][0]=999
        with self.assertRaisesRegex(SceneLearningError,"MODEL_SHA_MISMATCH"):
            predict_scene(broken,{"vector":vec("START"),
                "frame_sha256":sha("bad"),"t":1})

    def test_holdout_must_not_share_source_or_image(self):
        duplicate=docs()
        duplicate[-1]["recording_sha256"]=duplicate[0]["recording_sha256"]
        with self.assertRaisesRegex(SceneLearningError,"RECORDING_CONTENT_LEAKAGE"):
            train_reviewed_classifier(duplicate)
        shared_frame=docs()
        shared_frame[-1]["samples"][0]["frame_sha256"]=shared_frame[0]["samples"][0]["frame_sha256"]
        with self.assertRaisesRegex(SceneLearningError,"FRAME_CONTENT_LEAKAGE"):
            train_reviewed_classifier(shared_frame)

    def test_scene_predictions_only_suggest_lap_evidence(self):
        model=train_reviewed_classifier(docs())
        blocks=[
            ("START",2),("RACING",15),("HOME_PASS",2),
            ("RACING",15),("HOME_PASS",2),("RACING",15),
            ("HOME_PASS",2),("RACING",15),("HOME_PASS",2),
            ("RACING",5),("GOAL",2),("REPLAY",4),("RESULT",3)
        ]
        features=[]
        t=0
        for label,count in blocks:
            for j in range(count):
                features.append({
                    "t":t,"frame_sha256":sha(f"{t}-synthetic"),
                    "phash64":f"{(t*0x9e3779b97f4a7c15)&((1<<64)-1):016x}",
                    "vector":vec(label,2,j)})
                t+=1
        feature_doc={"schema":FEATURE_SCHEMA,
            "race_id":"20261108-matsuyama-9R",
            "recording_sha256":sha("synthetic_video"),
            "duration_s":250.0,"sampling_seconds":1,
            "feature_version":"HSV_GRID_EDGE_7x28_v1",
            "features":features}
        out=to_review_queue(feature_doc,model,source="SYNTHETIC_FIXTURE")
        cannot_self=copy.deepcopy(feature_doc)
        cannot_self["race_id"]=model["train_races"][0]
        with self.assertRaisesRegex(SceneLearningError,"TRAINING_RACE_CANNOT_SELF_VERIFY_LAPS"):
            to_review_queue(cannot_self,model,source="SYNTHETIC_FIXTURE")
        self.assertEqual(out["audit"]["status"],"FOUR_LAPS_UNVERIFIED")
        self.assertTrue(out["private_review_required"])
        self.assertFalse(out["model_may_self_certify_four_laps"])
        self.assertEqual(out["audit"]["candidate_count"],4)

    def test_synthetic_ffmpeg_video_feature_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"test.webm"
            subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
              "-f","lavfi","-i","testsrc2=size=320x180:rate=8",
              "-t","22","-an","-c:v","libvpx",str(p)],
              check=True,timeout=30)
            snapshot=sample_private_video(p,race_id="synthetic-fixture-01",
                                         every_s=2)
            self.assertEqual(snapshot["schema"],FEATURE_SCHEMA)
            self.assertTrue(len(snapshot["features"])>=9)
            self.assertEqual(len(snapshot["features"][0]["vector"]),196)
            self.assertFalse(snapshot["raw_video_exported"])
            self.assertFalse(snapshot["source_outcomes_used"])

if __name__=="__main__":unittest.main()
