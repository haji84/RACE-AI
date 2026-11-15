"""Offline end-to-end private replay runner contract with fictional frame bytes.

Uses OpenCV operations on an in-memory fake video stream; the file itself
contains invented placeholder bytes. No WINTICKET access or real rider labels.
"""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import copy
import json
import os
import unittest

from scripts.keirin_historical_color_eval_offline import run
from race_ai.keirin_historical_rider_color_eval import HistoricalColorError

RID="203001151201"


class PrivateRunnerRegression(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np
        self.cv2=cv2
        self.root=TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.base=Path(self.root.name)
        os.chmod(self.base,0o700)
        self.source=self.base/"frames.json"
        self.manual=self.base/"review.json"
        self.video=self.base/(RID+".webm")
        self.video.write_bytes(b"FAKE VIDEO: NO REAL MEDIA OR RIGHTS")
        os.chmod(self.video,0o600)
        self.frame=np.zeros((240,320,3),dtype=np.uint8)
        self.frame[:]=[255,110,20]  # BGR blue
        crop=self.frame[int(240*.303):int(240*.709),
                        int(320*.299):int(320*.701)]
        self.sha=sha256(self.video.read_bytes()).hexdigest()
        self.frame_sha=sha256(crop.tobytes()).hexdigest()
        self.saved={"sources":[{"race_id":RID,
             "source_sha256":self.sha,"frame_count":1,
             "frames":[{"second":0,"source_frame_sha256":self.frame_sha}]}]}
        self.review={
            "schema":"RACE_AI_KEIRIN_PRIVATE_SINGLE_REVIEWED_JERSEY_CROPS_V1",
            "review_level":"SINGLE_VISUAL_REVIEW_NOT_INDEPENDENT",
            "races":[{"race_id":RID,"source_sha256":self.sha,
                      "starters":[1,2,3,4,5,6],
                      "labels":[{"second":0,"frame_sha256":self.frame_sha,
                                 "car_number":4,
                                 "center_x_1024":512,"center_y_584":292}]}],
        }
        self.save()

    def save(self):
        self.source.write_text(json.dumps(self.saved))
        self.manual.write_text(json.dumps(self.review))

    def check(self):
        frames=self.frame
        class MockCapture:
            def __init__(self,path):
                self.path=path
            def isOpened(self):
                return True
            def set(self,*args):
                return True
            def read(self):
                return True,frames.copy()
            def release(self):
                pass
        with patch.object(self.cv2,"VideoCapture",side_effect=MockCapture):
            return run(decrypted_private_dir=self.base,
                       saved_frame_features=self.source,
                       manual_review=self.manual)

    def test_blue_rider_six_car_private_one_review_stays_non_formal(self):
        r=self.check()
        self.assertEqual(r["exact_saved_frame_sha_matches"],1)
        self.assertEqual(r["original_saved_frame_count"],1)
        self.assertEqual(r["manually_localized_jersey_crops"],1)
        self.assertEqual(r["color_car_candidates_decided"],1)
        self.assertEqual(r["color_car_candidates_matching_single_review"],1)
        self.assertEqual(r["conditional_single_review_color_match_pct"],100)
        self.assertIsNone(r["position_accuracy_pct"])
        self.assertIsNone(r["complete_automatic_car_detection_accuracy_pct"])
        self.assertEqual(r["verified_six_phase_count"],0)
        self.assertFalse(r["eligible_for_official_accuracy_or_training"])

    def test_changed_video_sha_fails_before_any_grading(self):
        self.video.write_bytes(b"TAMPERED FAKE MEDIA")
        with self.assertRaisesRegex(HistoricalColorError,
                                    "DECRYPTED_VIDEO_BYTES_SHA_MISMATCH"):
            self.check()

    def test_changed_frame_sha_fails_before_any_grading(self):
        self.saved["sources"][0]["frames"][0]["source_frame_sha256"]="d"*64
        self.review["races"][0]["labels"][0]["frame_sha256"]="d"*64
        self.save()
        with self.assertRaisesRegex(HistoricalColorError,
                                    "SAVED_SOURCE_FRAME_SHA_MISMATCH"):
            self.check()

    def test_private_roster_unexpected_extra_rider_and_forged_location_fail(self):
        self.review["races"][0]["starters"]=[1,2]
        self.save()
        with self.assertRaisesRegex(HistoricalColorError,
                                    "PRIVATE_ROSTER_INVALID"):
            self.check()
        self.review["races"][0]["starters"]=[1,2,3,4,5,6]
        self.review["races"][0]["labels"][0]["frame_sha256"]="d"*64
        self.save()
        with self.assertRaisesRegex(HistoricalColorError,
                                    "MANUAL_FRAME_CROP_REFERENCE_INVALID"):
            self.check()


if __name__=="__main__":
    unittest.main()
