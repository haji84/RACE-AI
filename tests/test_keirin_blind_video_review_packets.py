"""Private blind-review packet constraints using fictional frames only."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import unittest

from race_ai.keirin_blind_rider_holdout_gate import (
    HoldoutGateError,checked_review,make_proposals,
)
from scripts.keirin_blind_video_review_packets import generate

RID="203001151201"


class PrivatelySealedSourcePacketsTests(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np
        self.cv2=cv2
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        os.chmod(self.base,0o700)
        self.media=self.base/"fictional.webm"
        self.media.write_bytes(b"synthetic-video-no-real-pixels")
        os.chmod(self.media,0o600)
        self.out=self.base/"review"
        self.out.mkdir(mode=0o700)
        self.frames={}
        for ts,color in ((0,(20,110,200)),(2,(80,200,110))):
            frame=np.zeros((720,1280,3),dtype=np.uint8)
            self.cv2.rectangle(frame,(610,310),(640,338),color,-1)
            self.frames[ts]=frame
        rows=[]
        for ts,frame in self.frames.items():
            H,W=frame.shape[:2]
            crop=frame[int(H*.303):int(H*.709),
                       int(W*.299):int(W*.701)]
            rows.append({"recording_sec":ts,
                         "frame_sha256":sha256(crop.tobytes()).hexdigest(),
                         "proposals":[{"bbox_xywh":[.4,.3,.08,.1],
                                       "car_color_candidate":6,
                                       "identification_source":"COLOR_ONLY"}]})
        self.pred=make_proposals(
            race_id=RID,recording_sha256=sha256(self.media.read_bytes()).hexdigest(),
            model_code_sha256="a"*64,model_train_race_ids=[],
            frames=rows,frozen_at="2030-01-15T09:00:00+09:00",
            target_kind="JERSEY_COLOR_REGION")
        self.pred_file=self.base/"proposals.json"
        self.pred_file.write_text(json.dumps(self.pred))
        os.chmod(self.pred_file,0o600)

    def run_packet(self,*,reviewers=("reviewer_alpha","reviewer_beta"),
                   selected_seconds=None):
        frames=self.frames
        class Capture:
            def __init__(self,_):
                self.sec=0
            def isOpened(self):return True
            def set(self,attribute,t):
                self.sec=round(t/1000)
            def read(self):
                return True,frames[self.sec].copy()
            def release(self):pass
        with patch.object(self.cv2,"VideoCapture",side_effect=Capture):
            return generate(frozen_proposal=self.pred_file,
                    source_video=self.media,private_output=self.out,
                    reviewer_ids=reviewers,selected_seconds=selected_seconds)

    def test_two_private_reviewers_get_unlabeled_frames_not_predictions(self):
        result=self.run_packet()
        self.assertEqual(result["separate_packets_created"],2)
        self.assertEqual(result["images_per_reviewer"],2)
        self.assertFalse(result["candidate_color_boxes_exposed_to_reviewers"])
        self.assertFalse(result["second_independent_review_completed"])
        for reviewer in ("reviewer_alpha","reviewer_beta"):
            directory=self.out/("blind_"+reviewer)
            self.assertEqual(directory.stat().st_mode&0o077,0)
            pics=list(directory.glob("source_*.png"))
            self.assertEqual(len(pics),2)
            self.assertTrue(all(p.stat().st_mode&0o077==0 for p in pics))
            template=json.loads((directory/"review_UNFINISHED.json").read_text())
            self.assertIsNone(template["reviewed_at"])
            self.assertFalse(template["independent_source_frame_read"])
            self.assertTrue(all(not x["annotations"] for x in template["frames"]))
            self.assertNotIn("bbox_xywh",json.dumps(template))
            with self.assertRaises(HoldoutGateError):
                checked_review(template,self.pred)
            packet=json.loads((directory/"manifest.json").read_text())
            self.assertTrue(packet["does_not_contain_model_predictions_or_rider_labels"])

    def test_public_reviewer_directory_is_rejected(self):
        os.chmod(self.out,0o755)
        with self.assertRaisesRegex(
            HoldoutGateError,"PRIVATE_REVIEW_DIRECTORY_REQUIRED"):
            self.run_packet()

    def test_wrong_source_video_sha_is_rejected_without_reading_pixels(self):
        self.media.write_bytes(b"changed fake media")
        with self.assertRaisesRegex(HoldoutGateError,
                                    "SOURCE_PRIVATE_VIDEO_SHA_MISMATCH"):
            self.run_packet()
        self.assertEqual(list(self.out.iterdir()),[])

    def test_same_reviewer_twice_rejected(self):
        with self.assertRaisesRegex(HoldoutGateError,
                                    "TWO_DISTINCT_REVIEWER_IDS_REQUIRED"):
            self.run_packet(reviewers=("reviewer_dup","reviewer_dup"))

    def test_subset_selection_cannot_certify_holdout_recall(self):
        with self.assertRaisesRegex(
            HoldoutGateError,"PARTIAL_REVIEW_CANNOT_CERTIFY_COMPLETE_HOLDOUT"):
            self.run_packet(selected_seconds=[0])

    def test_wrong_frame_sha_stops_packet_generation(self):
        d=json.loads(self.pred_file.read_text())
        d["frames"][0]["frame_sha256"]="f"*64
        from race_ai.keirin_blind_rider_holdout_gate import digest
        d["proposal_sha256"]=digest({
            k:v for k,v in d.items() if k!="proposal_sha256"})
        self.pred_file.write_text(json.dumps(d))
        with self.assertRaisesRegex(
            HoldoutGateError,"PRIVATE_FRAME_SHA_REPLAY_MISMATCH"):
            self.run_packet()
        self.assertEqual(list(self.out.iterdir()),[])


if __name__=="__main__":
    unittest.main()
