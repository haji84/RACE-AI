"""No real rider truth: synthetic bike circles and broadcast-style color bars.

Tests assert that wheel-like shape context can raise a research hypothesis,
but never changes the original A or promotes a candidate to verified person,
car number, line, six-phase scoring, PDCA or learning.
"""
from __future__ import annotations

from hashlib import sha256
import unittest

from race_ai.keirin_bicycle_shape_context import (
    analyze_frame, summarize_shape_context, BicycleContextError,
)
from race_ai.keirin_visual_jersey_proposals import detect_color_regions


def make_frame(*,bike=False,banner=False):
    import cv2
    import numpy as np

    img=np.full((292,515,3),160,dtype=np.uint8)
    if banner:
        cv2.rectangle(img,(175,111),(211,122),(0,220,230),-1)
    else:
        # Blue region is intentionally not a labeled rider. It merely sits
        # above two round contours arranged like small bicycle wheels.
        cv2.rectangle(img,(182,123),(206,137),(225,145,50),-1)
        if bike:
            for center in ((178,190),(220,190)):
                cv2.circle(img,center,20,(5,5,5),2)
    return img


def existing_a(img):
    h=sha256(img.tobytes()).hexdigest()
    detected=detect_color_regions(
        img,roster=[1,2,3,4,5,6,7],source_crop_sha256=h)
    return [{
       "bbox_xywh":[x/1024,y/584,w/1024,ht/584],
       "car_color_candidate":p["car_color_candidate"],
       "identification_source":"COLOR_ONLY",
    } for p in detected["proposals"]
      for x,y,w,ht in [p["bbox_xywh_1024x584"]]]


def assess(img,t=14):
    return analyze_frame(
        img,existing_a(img),expected_sha256=sha256(img.tobytes()).hexdigest(),
        second=t)


class ActualColorInputButSyntheticGeometryOnly(unittest.TestCase):
    def test_clear_toy_two_wheels_raise_shape_context_not_identity(self):
        img=make_frame(bike=True)
        r=assess(img)
        self.assertEqual(r["schema"],
                         "RACE_AI_KEIRIN_BICYCLE_SHAPE_CONTEXT_RESEARCH_V1")
        self.assertGreaterEqual(r["counts"]["A_CANDIDATES"],1)
        self.assertGreaterEqual(r["counts"]["WEAK_WHEEL_PAIR_CONTEXT"],1)
        self.assertEqual(r["automatically_removed_candidate_count"],0)
        self.assertTrue(r["circle_pairs_not_independently_verified_wheels"])
        self.assertIsNone(r["person_detection_accuracy_pct"])
        self.assertFalse(r["eligible_for_formal_phase_scoring"])
        self.assertTrue(all(not x["recognized_athlete"]
                            for x in r["private_candidate_hypotheses_not_ground_truth"]))

    def test_missing_circle_does_not_delete_color_candidate(self):
        x=assess(make_frame())
        self.assertGreaterEqual(x["counts"]["A_CANDIDATES"],1)
        self.assertEqual(x["counts"]["WEAK_WHEEL_PAIR_CONTEXT"],0)
        self.assertEqual(x["automatically_removed_candidate_count"],0)
        self.assertTrue(x["missing_wheels_do_not_erase_riders"])

    def test_flat_upper_banner_is_background_risk_not_false_positive(self):
        x=assess(make_frame(banner=True),t=32)
        self.assertGreaterEqual(x["counts"]["A_CANDIDATES"],1)
        self.assertGreaterEqual(
            x["counts"]["BROAD_IMAGE_BACKGROUND_RISK_FLAG"],1)
        self.assertTrue(any(
            c["research_background_risk_flag"]
            for c in x["private_candidate_hypotheses_not_ground_truth"]))
        self.assertEqual(x["automatically_removed_candidate_count"],0)
        self.assertIsNone(x["car_number_OCR_accuracy_pct"])

    def test_wrong_frame_bytes_or_forged_boxes_rejected_before_scoring(self):
        img=make_frame(bike=True)
        a=existing_a(img)
        with self.assertRaisesRegex(BicycleContextError,
                                    "SOURCE_BOUND_BGR_SHA_REQUIRED"):
            analyze_frame(img,a,expected_sha256="f"*64,second=14)
        with self.assertRaisesRegex(BicycleContextError,
                                    "EXISTING_A_NORMALIZED_BBOX_INVALID"):
            analyze_frame(img,[
               {**a[0],"bbox_xywh":[.96,.3,.1,.08]}
            ],expected_sha256=sha256(img.tobytes()).hexdigest(),second=14)

    def test_research_sums_require_original_frozen_baseline(self):
        img=make_frame(bike=True)
        r=assess(img)
        c=r["counts"]
        ok=summarize_shape_context(
            [r],expected_frame_count=1,
            expected_a_count=c["A_CANDIDATES"],
            expected_b_count=c["B_CANDIDATES"],
            expected_spatial_count=c["A_B_SPATIAL_PAIRS"],
            expected_color_count=c["A_B_SAME_COLOR_PAIRS"])
        self.assertIsNone(ok["rider_detection_recall_pct"])
        self.assertFalse(ok["formal_PDCA_and_training_updated"])
        self.assertEqual(ok["removed_existing_A_regions"],0)
        self.assertIn("14",ok["priority_source_seconds"])
        with self.assertRaisesRegex(BicycleContextError,
                                    "FROZEN_A_B_COUNTS_CHANGED"):
            summarize_shape_context(
                [r],expected_frame_count=1,
                expected_a_count=c["A_CANDIDATES"]+1,
                expected_b_count=c["B_CANDIDATES"],
                expected_spatial_count=c["A_B_SPATIAL_PAIRS"],
                expected_color_count=c["A_B_SAME_COLOR_PAIRS"])

    def test_no_ground_truth_labels_are_emitted_as_real_accuracy(self):
        rows=[assess(make_frame(bike=True),14),
              assess(make_frame(),32)]
        counts=lambda k:sum(row["counts"].get(k,0) for row in rows)
        # The repeated identical img would have same SHA; these differ.
        result=summarize_shape_context(
            rows,expected_frame_count=2,
            expected_a_count=counts("A_CANDIDATES"),
            expected_b_count=counts("B_CANDIDATES"),
            expected_spatial_count=counts("A_B_SPATIAL_PAIRS"),
            expected_color_count=counts("A_B_SAME_COLOR_PAIRS"))
        self.assertEqual(result["verified_source_frames"],2)
        self.assertIsNone(result["car_number_accuracy_pct"])
        self.assertIsNone(result["six_phase_accuracy_pct"])
        self.assertTrue(result["original_prediction_model_unchanged"])
        self.assertFalse(result["formal_PDCA_and_training_updated"])


if __name__=="__main__":
    unittest.main()
