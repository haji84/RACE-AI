"""Fictional BGR shapes and mocked OCR; not actual numbered riders."""
from __future__ import annotations
from hashlib import sha256
import copy
import unittest
import cv2,numpy as np
from race_ai.keirin_visual_jersey_proposals import detect_color_regions
from race_ai.keirin_shape_digit_candidate_research import (
    ShapeDigitResearchError,analyze_shape_digit_frame,summarize_shape_digit,
    UNKNOWN,SCHEMA,
)


def frame(blue=True):
    img=np.full((292,515,3),150,np.uint8)
    if blue:cv2.rectangle(img,(181,120),(203,138),(225,145,50),-1)
    return img

def input_a(image):
    sig=sha256(image.tobytes()).hexdigest()
    r=detect_color_regions(image,roster=[1,2,3,4,5,6,7],
                           source_crop_sha256=sig)
    return [{
        "bbox_xywh":[x/1024,y/584,w/1024,h/584],
        "car_color_candidate":p["car_color_candidate"],
        "identification_source":"COLOR_ONLY",
    } for p in r["proposals"]
      for x,y,w,h in [p["bbox_xywh_1024x584"]]]

def run(image,reader,second=16):
    return analyze_shape_digit_frame(
        image,input_a(image),
        expected_sha256=sha256(image.tobytes()).hexdigest(),
        second=second,ocr_reader=reader)


class NoHumanTruthFromImageHeuristics(unittest.TestCase):
    def test_two_preprocessing_views_and_wheel_context_are_only_hypotheses(self):
        img=frame()
        res=run(img,lambda _:dict(digit=4,confidence=98.0))
        self.assertEqual(res["schema"],SCHEMA)
        self.assertGreater(res["frozen_A_candidate_count"],0)
        self.assertEqual(
            res["counts"].get("TWO_PREPROCESSINGS_SAME_DIGIT_UNTRUSTED",0),
            res["counts"].get("OCR_GEOMETRY_ELIGIBLE",0))
        self.assertFalse(res["actual_person_detected_or_identified"])
        self.assertFalse(res["official_phase_scoring_or_training_authorized"])
        self.assertIsNone(res["true_car_number_OCR_accuracy_pct"])

    def test_unknown_ocr_holds_without_deleting_color_evidence(self):
        r=run(frame(),lambda _:dict(digit=UNKNOWN,confidence=None))
        self.assertEqual(r["counts"].get("NO_VERIFIED_DIGIT",0),
                         r["frozen_A_candidate_count"])
        self.assertEqual(r["counts"].get("UNTRUSTED_DIGIT_AND_COLOR_CONSISTENT",0),0)

    def test_color_number_disagreement_must_hold(self):
        r=run(frame(),lambda _:dict(digit=7,confidence=88))
        self.assertGreaterEqual(
            r["counts"].get("UNTRUSTED_DIGIT_AND_COLOR_CONFLICT_HOLD",0),1)
        self.assertEqual(r["counts"].get("UNTRUSTED_THREE_SIGNAL_AGREEMENT",0),0)

    def test_backend_failure_cannot_elevate_to_known_car(self):
        def fail(_):raise RuntimeError("MOCK_FAILURE")
        r=run(frame(),fail)
        self.assertGreaterEqual(r["counts"].get("OCR_BACKEND_REJECTED",0),1)
        self.assertEqual(r["counts"].get("NO_VERIFIED_DIGIT",0),
                         r["frozen_A_candidate_count"])

    def test_missing_or_false_frame_SHA_rejected(self):
        img=frame()
        with self.assertRaisesRegex(
            ShapeDigitResearchError,"SOURCE_FRAME_BGR_SHA_REQUIRED"):
            analyze_shape_digit_frame(
                img,input_a(img),expected_sha256="f"*64,second=16,
                ocr_reader=lambda _:dict(digit=UNKNOWN,confidence=None))

    def test_coverage_aggregate_has_no_accuracy_without_truth(self):
        a=run(frame(),lambda _:dict(digit=UNKNOWN,confidence=None),second=16)
        b=run(frame(False),lambda _:dict(digit=UNKNOWN,confidence=None),second=32)
        s=summarize_shape_digit(
            [a,b],race_id="203011091201",
            expected_frame_count=2,
            expected_A_candidates=a["frozen_A_candidate_count"]+
                                  b["frozen_A_candidate_count"])
        self.assertEqual(s["source_sha_verified_frames"],2)
        self.assertIsNone(s["actual_bib_digit_accuracy_pct"])
        self.assertFalse(s["eligible_for_PDCA_or_training"])
        self.assertEqual(s["independent_human_labels"],0)

    def test_identical_frame_sha_reuse_refused(self):
        a=run(frame(),lambda _:dict(digit=UNKNOWN,confidence=None),second=16)
        b=copy.deepcopy(a);b["second"]=32
        with self.assertRaisesRegex(
            ShapeDigitResearchError,"SOURCE_BOUND_UNIQUE_FRAME_SEQUENCE_REQUIRED"):
            summarize_shape_digit(
                [a,b],race_id="203011091201",
                expected_frame_count=2,
                expected_A_candidates=2*a["frozen_A_candidate_count"])


if __name__=="__main__":
    unittest.main()
