"""Source-free BGR tests for A/B HSV agreement, never rider ground truth."""
from __future__ import annotations

from hashlib import sha256
import unittest

from race_ai.keirin_color_ab_stability import (
    ABStabilityError, conservative_blobs, compare_a_b_regions, summarize_a_b,
)
from race_ai.keirin_visual_jersey_proposals import detect_color_regions


def snapshot(colors=()):
    import cv2
    import numpy as np
    frame=np.zeros((292,515,3),dtype=np.uint8)
    palette={3:(0,0,220),4:(225,145,50),5:(0,220,230),
             6:(40,170,80),7:(0,110,220)}
    for num,x,y in colors:
        xx=int(x*515/1024);yy=int(y*292/584)
        cv2.rectangle(frame,(xx-9,yy-7),(xx+9,yy+7),
                      palette[num],-1)
    return frame


def sha_frame(frame):
    return sha256(frame.tobytes()).hexdigest()


def flatten_A(frame):
    r=detect_color_regions(frame,roster=list(range(1,8)),
                           source_crop_sha256=sha_frame(frame))
    return [{
       "bbox_xywh":[x/1024,y/584,w/1024,h/584],
       "car_color_candidate":p["car_color_candidate"],
       "identification_source":"COLOR_ONLY",
    } for p in r["proposals"]
      for x,y,w,h in [p["bbox_xywh_1024x584"]]]


class ColorABUntrustedFixtureTests(unittest.TestCase):
    def test_two_hsv_rules_find_overlapping_blue_yellow_green(self):
        image=snapshot([(4,380,260),(5,570,290),(6,730,325)])
        a=flatten_A(image)
        b=conservative_blobs(image,expected_frame_sha256=sha_frame(image))
        scored=compare_a_b_regions(a,b)
        self.assertGreaterEqual(scored["a_b_spatial_and_color_consistent_blobs"],3)
        self.assertTrue(scored["not_confirmed_riders"])
        self.assertLessEqual(
            scored["a_b_spatial_and_color_consistent_blobs"],
            min(len(a),len(b)))

    def test_same_location_different_car_color_is_not_a_correct_match(self):
        a=[{"bbox_xywh":[.30,.4,.04,.04],
            "car_color_candidate":4,"identification_source":"COLOR_ONLY"}]
        b=[{"color":3,"center_x":.32*1024,
            "center_y":.42*584}]
        r=compare_a_b_regions(a,b)
        self.assertEqual(r["a_b_spatially_paired_color_blobs"],1)
        self.assertEqual(r["a_b_spatial_and_color_consistent_blobs"],0)
        self.assertEqual(r["a_b_disagreed_color_within_spatial_pairs"],1)

    def test_duplicate_B_regions_cannot_match_single_A_twice(self):
        a=[{"bbox_xywh":[.30,.4,.04,.04],
            "car_color_candidate":4,"identification_source":"COLOR_ONLY"}]
        b=[{"color":4,"center_x":.32*1024,"center_y":.42*584},
           {"color":4,"center_x":.321*1024,"center_y":.42*584}]
        result=compare_a_b_regions(a,b)
        self.assertEqual(result["a_b_spatially_paired_color_blobs"],1)

    def test_no_ground_truth_means_no_precision_accuracy_or_PDCA(self):
        s=summarize_a_b([{
            "a_frozen_blob_count":2,"b_stricter_blob_count":1,
            "a_b_spatially_paired_color_blobs":1,
            "a_b_spatial_and_color_consistent_blobs":1,
        }],race_id="202611098402",frozen_sha="a"*64,
           exact_frame_sha_count=1)
        self.assertEqual(s["A_blob_color_confirmation_by_B_pct"],50)
        self.assertEqual(s["B_blob_color_confirmation_by_A_pct"],100)
        self.assertIsNone(s["actual_rider_car_number_accuracy_pct"])
        self.assertIsNone(s["independent_person_detection_recall_pct"])
        self.assertFalse(s["production_PDCA_or_model_training_authorized"])
        self.assertEqual(s["independent_person_ground_truth_reviewers"],0)

    def test_empty_blobs_are_unknown_not_one_hundred_percent(self):
        output=summarize_a_b([{
            "a_frozen_blob_count":0,"b_stricter_blob_count":0,
            "a_b_spatially_paired_color_blobs":0,
            "a_b_spatial_and_color_consistent_blobs":0,
        }],race_id="202611098402",frozen_sha="f"*64,
           exact_frame_sha_count=1)
        self.assertIsNone(output["A_blob_color_confirmation_by_B_pct"])
        self.assertIsNone(output["B_blob_color_confirmation_by_A_pct"])

    def test_bad_frame_sha_and_invalid_boxes_refused(self):
        frame=snapshot([(4,500,280)])
        with self.assertRaisesRegex(ABStabilityError,
                                    "A_B_REAL_SOURCE_FRAME_SHA_MISMATCH"):
            conservative_blobs(frame,expected_frame_sha256="f"*64)
        with self.assertRaisesRegex(ABStabilityError,
                                    "FROZEN_A_BOX_UNTRUSTED"):
            compare_a_b_regions([
               {"bbox_xywh":[.96,.5,.05,.1],
                "car_color_candidate":4,"identification_source":"COLOR_ONLY"}
            ],[])
        with self.assertRaisesRegex(ABStabilityError,
                                    "A_B_MATCH_COUNT_IMPOSSIBLE"):
            summarize_a_b([{
             "a_frozen_blob_count":1,"b_stricter_blob_count":1,
             "a_b_spatially_paired_color_blobs":2,
             "a_b_spatial_and_color_consistent_blobs":2,
            }],race_id="202611098402",frozen_sha="f"*64,
               exact_frame_sha_count=1)


if __name__=="__main__":
    unittest.main()
