"""Offline private auto-localization runner: fake video, real OpenCV pixels.

No source network, historical real footage, rights proof, or actual racer
identity in CI. The single-review label is evaluation-only after inference.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import unittest

from scripts.keirin_historical_auto_color_eval_private import run
from race_ai.keirin_historical_rider_color_eval import HistoricalColorError

RID="203001151201"


class AutoPrivateSourceContract(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np
        self.cv2=cv2
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        os.chmod(self.base,0o700)
        self.frames=self.base/"private_saved.json"
        self.labels=self.base/"private_single_review.json"
        self.video=self.base/(RID+".webm")
        self.video.write_bytes(b"FAKE TEST FIXTURE VIDEO WITHOUT RIGHTS")
        os.chmod(self.video,0o600)
        self.full=np.zeros((720,1280,3),dtype=np.uint8)
        # The only jersey is synthetic blue in the pixel array. Manual label
        # position is separate from detector input; no background graphics.
        x0,y0=int(1280*.299),int(720*.303)
        self.cv2.rectangle(self.full,(x0+248,y0+138),
                           (x0+264,y0+150),(225,145,50),-1)
        crop=self.full[int(720*.303):int(720*.709),
                       int(1280*.299):int(1280*.701)]
        self.source_sha=sha256(self.video.read_bytes()).hexdigest()
        self.frame_sha=sha256(crop.tobytes()).hexdigest()
        self.source={
            "sources":[{
                "race_id":RID,"source_sha256":self.source_sha,
                "frame_count":1,
                "frames":[{"second":0,"source_frame_sha256":self.frame_sha}],
            }],
            "raw_pixels_exported":False,
        }
        self.review={
            "schema":"RACE_AI_KEIRIN_PRIVATE_SINGLE_REVIEWED_JERSEY_CROPS_V1",
            "review_level":"SINGLE_VISUAL_REVIEW_NOT_INDEPENDENT",
            "races":[{
                "race_id":RID,"source_sha256":self.source_sha,
                "starters":[1,2,3,4,5,6],
                "labels":[{
                    "second":0,"frame_sha256":self.frame_sha,
                    "car_number":4,
                    "center_x_1024":512,"center_y_584":288,
                }],
            }],
        }
        self.save()

    def save(self):
        self.frames.write_text(json.dumps(self.source))
        self.labels.write_text(json.dumps(self.review))

    def check(self):
        frame=self.full
        class FakeCapture:
            def __init__(self,path):self.path=path
            def isOpened(self):return True
            def set(self,*args):return True
            def read(self):return True,frame.copy()
            def release(self):pass
        with patch.object(self.cv2,"VideoCapture",side_effect=FakeCapture):
            return run(
                decrypted_private_dir=self.base,
                saved_frame_features=self.frames,
                manual_review=self.labels,
            )

    def test_actual_cv2_bgr_detection_gets_no_manual_center(self):
        r=self.check()
        self.assertEqual(r["source_frame_hashes_matched"],1)
        self.assertEqual(r["source_frame_hashes_expected"],1)
        self.assertEqual(r["single_review_jerseys"],1)
        self.assertEqual(r["spatial_matches_within_40px"],1)
        self.assertEqual(r["spatial_matches_with_matching_car_color"],1)
        self.assertFalse(r["manual_center_supplied_to_detector"])
        self.assertFalse(r["formal_results_or_training_enabled"])
        self.assertIsNone(r["independent_car_id_accuracy_pct"])
        self.assertIsNone(r["actual_digit_ocr_accuracy_pct"])
        self.assertIsNone(r["formal_phase_accuracy_pct"])
        self.assertFalse(r["public_report_contains_no_pixel_data_or_exact_boxes"] is False)
        self.assertNotIn("center_x_1024",json.dumps(r))

    def test_modify_cipher_source_fails_before_any_scoring(self):
        self.video.write_bytes(b"CHANGED AFTER PRIVATE CAPTURE")
        with self.assertRaisesRegex(HistoricalColorError,
                                    "REPLAY_SOURCE_VIDEO_SHA_MISMATCH"):
            self.check()

    def test_modify_previous_frame_SHA_fails_before_any_scoring(self):
        self.source["sources"][0]["frames"][0]["source_frame_sha256"]="f"*64
        self.review["races"][0]["labels"][0]["frame_sha256"]="f"*64
        self.save()
        with self.assertRaisesRegex(HistoricalColorError,
                                    "REPLAY_SAVED_FRAME_SHA_MISMATCH"):
            self.check()

    def test_retroactive_label_for_different_frame_is_rejected(self):
        self.review["races"][0]["labels"][0]["frame_sha256"]="f"*64
        self.save()
        with self.assertRaisesRegex(HistoricalColorError,
                                    "SINGLE_REVIEW_FRAME_SHA_NOT_AUTHENTICATED"):
            self.check()

    def test_unknown_video_path_never_opened(self):
        self.source["sources"][0]["race_id"]="../rogue"
        self.review["races"][0]["race_id"]="../rogue"
        self.save()
        with self.assertRaisesRegex(HistoricalColorError,"UNTRUSTED_VIDEO_PATH"):
            self.check()

    def test_world_readable_media_folder_denied(self):
        os.chmod(self.base,0o755)
        with self.assertRaisesRegex(
            HistoricalColorError,"SOURCE_VIDEO_DIRECTORY_MUST_BE_OWNER_PRIVATE"):
            self.check()


if __name__=="__main__":
    unittest.main()
