"""Synthetic-only independent-review admission tests. No person/video truth.

Fake callbacks are explicit and cannot be used as real independent attestations.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest

from race_ai.keirin_blind_rider_holdout_gate import (
    AUDIT_SCHEMA, PREDICTION_SCHEMA, REVIEW_SCHEMA,
    HoldoutGateError, UNKNOWN, make_proposals, checked_proposal,
    freeze_private_once, checked_review, digest, audit,
)

T="2030-01-15T09:00:00+09:00"
RACE="203001151201"
SOURCE="a"*64
MODEL="b"*64


def proposal_rows():
    return [
        {"bbox_xywh":[.10,.25,.10,.12],"car_color_candidate":4,
         "identification_source":"COLOR_ONLY"},
        {"bbox_xywh":[.50,.25,.10,.12],"car_color_candidate":6,
         "identification_source":"COLOR_ONLY"},
    ]


def get_prediction(rows=None, *, target="JERSEY_COLOR_REGION"):
    return make_proposals(
        race_id=RACE, recording_sha256=SOURCE,
        model_code_sha256=MODEL,
        model_train_race_ids=["202911141201"],
        frames=[{"frame_sha256":"1"*64,"recording_sec":21,
                 "proposals":proposal_rows() if rows is None else rows}],
        frozen_at=T,target_kind=target)


def label(car,xywh,*,kind="COLOR_ONLY",rank=UNKNOWN,line=UNKNOWN):
    return {"bbox_xywh":xywh,"car_number":car,"number_evidence":kind,
            "race_position":rank,"line_role":line}


def review(pred, who, *, labels=None, exhaustive=True):
    doc={
        "schema":REVIEW_SCHEMA,
        "race_id":pred["race_id"],"recording_sha256":pred["recording_sha256"],
        "proposal_sha256":pred["proposal_sha256"],
        "reviewer_id":who,
        "reviewed_at":"2030-01-15T10:00:00+09:00",
        "target_kind":pred["target_kind"],
        "independent_source_frame_read":True,
        "frames":[{"frame_sha256":"1"*64,
                   "exhaustive_visible_targets":exhaustive,
                   "annotations":(
                      [label(4,[.10,.25,.10,.12]),
                       label(6,[.50,.25,.10,.12])]
                      if labels is None else labels)}],
    }
    doc["review_sha256"]=digest(doc)
    return doc


def accepted(*,prediction=None,a=None,b=None,video=True,frozen=True,
             lineage=True,reviewed=True):
    p=get_prediction() if prediction is None else prediction
    return audit(
        p,
        review(p,"blind_A_01") if a is None else a,
        review(p,"blind_B_02") if b is None else b,
        original_video_verifier=lambda _:video,
        freeze_receipt_verifier=lambda _:frozen,
        holdout_lineage_verifier=lambda _:lineage,
        reviewer_receipt_verifier=lambda *_:reviewed,
    )


class IndependentHeldoutRiderAuditTests(unittest.TestCase):
    def test_two_independent_complete_annotations_can_score_prec_recall(self):
        out=accepted()
        self.assertEqual(out["schema"],AUDIT_SCHEMA)
        self.assertEqual(out["status"],"TWO_REVIEW_JERSEY_COLOR_REGION_DETECTION_ADMITTED")
        self.assertEqual(out["true_positive_region_boxes"],2)
        self.assertEqual(out["false_positive_region_boxes"],0)
        self.assertEqual(out["false_negative_region_boxes"],0)
        self.assertEqual(out["independent_region_detection_f1_pct"],100)
        self.assertIsNone(out["digit_OCR_accuracy_pct"])
        self.assertIsNone(out["confirmed_rider_person_ID_accuracy_pct"])
        self.assertIsNone(out["rank_accuracy_pct"])
        self.assertEqual(out["independently_verified_six_phase_count"],0)
        self.assertFalse(out["training_or_model_weights_modified"])

    def test_false_positives_and_false_negatives_are_separate(self):
        p=get_prediction()
        truth=[label(4,[.10,.25,.10,.12]),
               label(7,[.80,.25,.10,.12])]
        out=accepted(prediction=p,a=review(p,"review_001",labels=truth),
                     b=review(p,"review_002",labels=truth))
        self.assertEqual(out["true_positive_region_boxes"],1)
        self.assertEqual(out["false_positive_region_boxes"],1)
        self.assertEqual(out["false_negative_region_boxes"],1)
        self.assertEqual(out["independent_region_detection_precision_pct"],50)
        self.assertEqual(out["independent_region_detection_recall_pct"],50)
        self.assertEqual(out["independent_region_detection_f1_pct"],50)

    def test_without_two_real_reviews_all_metrics_null(self):
        p=get_prediction()
        out=audit(p,None,None,
                  original_video_verifier=lambda *_:True,
                  freeze_receipt_verifier=lambda *_:True,
                  holdout_lineage_verifier=lambda *_:True,
                  reviewer_receipt_verifier=lambda *_:True)
        self.assertIn("TWO_INDEPENDENT_REVIEWS_NOT_AVAILABLE",out["hold_reasons"])
        self.assertIsNone(out["independent_region_detection_recall_pct"])
        self.assertIsNone(out["false_positive_region_boxes"])
        self.assertEqual(out["untrusted_candidate_regions"],2)
        self.assertEqual(out["status"],"HOLD_INDEPENDENT_GROUND_TRUTH_UNVERIFIED")

    def test_a_self_claim_of_independent_reviewer_not_sufficient(self):
        p=get_prediction()
        out=accepted(prediction=p,
                     a=review(p,"same_reviewer"),
                     b=review(p,"same_reviewer"))
        self.assertIn("REVIEWERS_NOT_INDEPENDENT",out["hold_reasons"])
        self.assertIsNone(out["independent_region_detection_precision_pct"])

    def test_training_lineage_and_original_witness_are_independent(self):
        for name in ("video","frozen","lineage","reviewed"):
            kw={name:False}
            with self.subTest(block=name):
                out=accepted(**kw)
                self.assertEqual(out["status"],
                                 "HOLD_INDEPENDENT_GROUND_TRUTH_UNVERIFIED")
                self.assertIsNone(out["independent_region_detection_recall_pct"])

    def test_partial_ground_truth_does_not_manufacture_fp_or_accuracy(self):
        p=get_prediction()
        out=accepted(prediction=p,
                     a=review(p,"blind_A_01",exhaustive=False))
        self.assertIn("NON_EXHAUSTIVE_REVIEW",out["hold_reasons"])
        self.assertIsNone(out["true_positive_region_boxes"])

    def test_independent_review_disagreement_blocks_whole_frame(self):
        p=get_prediction()
        other=[label(4,[.10,.25,.10,.12]),
               label(7,[.50,.25,.10,.12])]
        out=accepted(prediction=p,
                     b=review(p,"blind_B_02",labels=other))
        self.assertIn("INDEPENDENT_REVIEW_DISAGREEMENT",out["hold_reasons"])
        self.assertIsNone(out["false_negative_region_boxes"])

    def test_iou_disagreement_blocks_before_truth_cherry_picking(self):
        p=get_prediction()
        shifted=[label(4,[.75,.25,.10,.12]),
                 label(6,[.50,.25,.10,.12])]
        out=accepted(prediction=p,b=review(p,"blind_B_02",labels=shifted))
        self.assertIn("INDEPENDENT_REVIEW_DISAGREEMENT",out["hold_reasons"])
        self.assertIsNone(out["independent_region_detection_f1_pct"])

    def test_missing_or_reordered_review_frame_is_rejected(self):
        p=get_prediction()
        row=review(p,"blind_A_01")
        row["frames"][0]["frame_sha256"]="d"*64
        row["review_sha256"]=digest({
            k:v for k,v in row.items() if k!="review_sha256"})
        with self.assertRaisesRegex(HoldoutGateError,"REVIEW_FRAME_SET_NOT_COMPLETE"):
            checked_review(row,p)

    def test_changed_source_and_saved_sha_fail_closed(self):
        p=get_prediction()
        p["frames"][0]["frame_sha256"]="3"*64
        with self.assertRaisesRegex(HoldoutGateError,"UNTRUSTED_PREDICTION_TAMPERED"):
            checked_proposal(p)
        p=get_prediction()
        r=review(p,"blind_A_01")
        r["proposal_sha256"]="e"*64
        r["review_sha256"]=digest({
            k:v for k,v in r.items() if k!="review_sha256"})
        with self.assertRaisesRegex(HoldoutGateError,"REVIEW_ID_TIME_OR_SOURCE_MISMATCH"):
            checked_review(r,p)

    def test_before_freeze_review_is_rejected(self):
        p=get_prediction()
        r=review(p,"blind_A_01")
        r["reviewed_at"]="2030-01-15T08:00:00+09:00"
        r["review_sha256"]=digest({
            k:v for k,v in r.items() if k!="review_sha256"})
        with self.assertRaisesRegex(HoldoutGateError,"REVIEW_ID_TIME_OR_SOURCE_MISMATCH"):
            checked_review(r,p)

    def test_train_race_in_holdout_refused(self):
        with self.assertRaisesRegex(HoldoutGateError,"TRAIN_OR_HOLDOUT_RACE_LEAK"):
            make_proposals(
                race_id=RACE,recording_sha256=SOURCE,
                model_code_sha256=MODEL,model_train_race_ids=[RACE],
                frames=get_prediction()["frames"],frozen_at=T,
                target_kind="JERSEY_COLOR_REGION")

    def test_malformed_frames_and_reviews_fail_closed_with_a_typed_hold(self):
        p=get_prediction()
        p["frames"]=[None]
        with self.assertRaisesRegex(
            HoldoutGateError,"FRAMES_MISSING_OR_REUSED"):
            checked_proposal(p)
        p=get_prediction()
        q=review(p,"blind_A_01")
        q["frames"]=[None]
        with self.assertRaisesRegex(
            HoldoutGateError,"REVIEW_FRAME_SET_NOT_COMPLETE"):
            checked_review(q,p)

    def test_private_freeze_create_once_with_exact_SHA(self):
        p=get_prediction()
        with TemporaryDirectory() as tmp:
            os.chmod(tmp,0o700)
            path=Path(tmp)/"proposals.json"
            ref=freeze_private_once(path,p)
            self.assertEqual(ref,sha256(path.read_bytes()).hexdigest())
            self.assertEqual(path.stat().st_mode&0o077,0)
            with self.assertRaisesRegex(
                HoldoutGateError,"PRIVATE_PREDICTION_FREEZE_PATH_UNSAFE"):
                freeze_private_once(path,p)
            os.chmod(tmp,0o755)
            with self.assertRaisesRegex(
                HoldoutGateError,"PRIVATE_PREDICTION_FREEZE_PATH_UNSAFE"):
                freeze_private_once(Path(tmp)/"public.json",p)

    def test_jpeg_color_only_can_never_claim_ocr_identity_or_phase(self):
        p=get_prediction()
        q=accepted(prediction=p)
        self.assertEqual(q["jersey_color_match_among_iou_matched_pct"],100)
        self.assertIsNone(q["digit_OCR_accuracy_pct"])
        self.assertIsNone(q["line_role_accuracy_pct"])
        self.assertEqual(q["independently_verified_six_phase_count"],0)

    def test_unknown_color_does_not_fake_high_precision(self):
        p=get_prediction(rows=[{"bbox_xywh":[.10,.25,.10,.12],
                                "car_color_candidate":UNKNOWN,
                                "identification_source":"COLOR_ONLY"}])
        a=review(p,"blind_A_01",labels=[label(UNKNOWN,[.10,.25,.10,.12],
                                           kind="UNKNOWN")])
        b=review(p,"blind_B_02",labels=[label(UNKNOWN,[.10,.25,.10,.12],
                                           kind="UNKNOWN")])
        out=accepted(prediction=p,a=a,b=b)
        self.assertEqual(out["independent_region_detection_recall_pct"],100)
        self.assertIsNone(out["jersey_color_match_among_iou_matched_pct"])
        self.assertIsNone(out["digit_OCR_accuracy_pct"])

if __name__=="__main__":
    unittest.main()
