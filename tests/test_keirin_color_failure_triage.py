"""No real people/frames: strict HSV dropout vs region geometry diagnostics."""
import copy
from hashlib import sha256
import unittest

from race_ai.keirin_color_failure_triage import (
    ABStabilityError, diagnose_frame, summarize_diagnosis, SCHEMA,
)
from race_ai.keirin_visual_jersey_proposals import detect_color_regions


def sample(hsv_color):
    import numpy as np
    import cv2
    img=np.zeros((292,515,3),dtype=np.uint8)
    bgr=cv2.cvtColor(
        np.uint8([[hsv_color]]),cv2.COLOR_HSV2BGR)[0,0].tolist()
    cv2.rectangle(img,(225,120),(249,144),bgr,-1)
    digest=sha256(img.tobytes()).hexdigest()
    a=detect_color_regions(img,roster=list(range(1,8)),
                           source_crop_sha256=digest)["proposals"]
    frozen=[{
        "bbox_xywh":[x/1024,y/584,w/1024,h/584],
        "car_color_candidate":p["car_color_candidate"],
        "identification_source":"COLOR_ONLY",
    }for p in a for x,y,w,h in [p["bbox_xywh_1024x584"]]]
    return img,digest,frozen


class ResearchFailureTriageTests(unittest.TestCase):
    def test_narrow_B_drops_broad_A_while_correctly_labelled_unknown(self):
        img,h,a=sample([88,70,150])  # blue at broad HSV edge
        self.assertGreater(len(a),0)
        report=diagnose_frame(img,a,expected_sha256=h,second=14)
        self.assertEqual(report["schema"],SCHEMA)
        self.assertEqual(report["B_stricter_color_regions"],0)
        self.assertEqual(report["A_regions_no_spatial_partner"],len(a))
        self.assertEqual(
            report["A_only_strict_pixel_categories"][
                "ABSENT_STRICT_HSV_PIXEL_IN_FROZEN_A_BOX"],len(a))
        self.assertFalse(report["actual_rider_position_or_number_confirmed"])
        self.assertFalse(report["training_or_phase_scoring_eligible"])

    def test_concordant_color_region_has_no_A_only_dropouts(self):
        img,h,a=sample([100,110,160])
        report=diagnose_frame(img,a,expected_sha256=h,second=32)
        self.assertGreater(report["same_color_pairs"],0)
        self.assertEqual(report["A_regions_no_spatial_partner"],0)
        self.assertEqual(sum(report["A_only_strict_pixel_categories"].values()),0)

    def test_no_detected_color_on_black_frame_is_not_person_accuracy(self):
        import numpy as np
        img=np.zeros((292,515,3),np.uint8)
        h=sha256(img.tobytes()).hexdigest()
        report=diagnose_frame(img,[],expected_sha256=h,second=82)
        self.assertEqual(report["same_color_pairs"],0)
        out=summarize_diagnosis(
            [report],race_id="202611098402",expected_frame_count=1,
            expected_A_count=0,expected_B_count=0,
            expected_spatial_count=0,expected_color_count=0)
        self.assertIsNone(out["actual_rider_detection_recall_pct"])
        self.assertIsNone(out["real_rider_identity_accuracy_pct"])
        self.assertFalse(out["model_learning_or_formal_PDCA_updated"])

    def test_invalid_or_modified_source_pixels_rejected(self):
        img,h,a=sample([100,110,160])
        with self.assertRaisesRegex(ABStabilityError,
                                    "SOURCE_FRAME_SHA_MISMATCH"):
            diagnose_frame(img,a,expected_sha256="f"*64,second=1)
        invalid=copy.deepcopy(a)
        invalid[0]["bbox_xywh"]=[0.99,0.7,0.1,0.1]
        with self.assertRaisesRegex(ABStabilityError,
                                    "TRIAGE_FROZEN_BBOX_INVALID"):
            diagnose_frame(img,invalid,expected_sha256=h,second=1)

    def test_no_changes_to_frozen_A_baseline_allowed(self):
        img,h,a=sample([100,110,160])
        r=diagnose_frame(img,a,expected_sha256=h,second=2)
        kwargs=dict(race_id="202611098402",expected_frame_count=1,
                    expected_A_count=r["A_frozen_color_regions"],
                    expected_B_count=r["B_stricter_color_regions"],
                    expected_spatial_count=r["spatially_paired_regions"],
                    expected_color_count=r["same_color_pairs"])
        s=summarize_diagnosis([r],**kwargs)
        self.assertEqual(s["A_only_without_spatial_pair"],0)
        self.assertEqual(s["research_priority_seconds"],[2])
        with self.assertRaisesRegex(ABStabilityError,
                                    "A_B_FROZEN_BASELINE_DRIFT_REJECTED"):
            summarize_diagnosis([r],**{**kwargs,
                "expected_color_count":kwargs["expected_color_count"]+1})

    def test_duplicate_frame_sha_is_not_a_valid_2frame_source(self):
        img,h,a=sample([88,70,150])
        r=diagnose_frame(img,a,expected_sha256=h,second=2)
        r2={**r,"second":4}
        with self.assertRaisesRegex(ABStabilityError,
                                    "DUPLICATE_OR_REORDERED_RESEARCH_FRAMES"):
            summarize_diagnosis([r,r2],race_id="202611098402",
                expected_frame_count=2,
                expected_A_count=2*len(a),expected_B_count=0,
                expected_spatial_count=0,expected_color_count=0)


if __name__=="__main__":
    unittest.main()
