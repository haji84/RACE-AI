"""Synthetic BGR frames only: auto-locator, single-review scoreboard and tracks.

No actual rider identity, official forecast/result, network or footage is
present in CI. The driver cannot use reviewed center labels to localize pixels.
"""
from __future__ import annotations

from hashlib import sha256
import copy
import unittest

from race_ai.keirin_visual_jersey_proposals import (
    JerseyProposalError, SCHEMA, TRACK_SCHEMA,
    detect_color_regions, match_single_review_after_detection,
    link_untrusted_color_blobs,
)


def frame():
    import numpy as np
    return np.zeros((292,515,3),dtype=np.uint8)


def squares(items):
    import cv2
    import numpy as np
    image=frame()
    colors={
        3:(0,0,220),4:(225,145,50),5:(0,220,230),
        6:(40,170,80),7:(0,130,220),1:(240,240,240)
    }
    for num,x,y in items:
        a,b=int(x*515/1024),int(y*292/584)
        cv2.rectangle(image,(a-8,b-6),(a+8,b+6),colors[num],-1)
    return image


def positive(frame,roster=None):
    return detect_color_regions(
        frame,roster=[1,2,3,4,5,6,7] if roster is None else roster,
        source_crop_sha256=sha256(frame.tobytes()).hexdigest())


def labeled(num,x,y):
    return {"car_number":num,"center_x_1024":x,"center_y_584":y}


class AutomaticJerseyBlobFixtureTests(unittest.TestCase):
    def test_three_synthetic_jerseys_are_auto_located_without_centers(self):
        image=squares([(3,280,260),(4,500,295),(5,750,340)])
        got=positive(image)
        self.assertEqual(got["schema"],SCHEMA)
        self.assertFalse(got["manually_supplied_centers_used_for_detection"])
        self.assertFalse(got["video_phase_or_race_order_inferred"])
        locs=got["proposals"]
        for car,x,y in [(3,280,260),(4,500,295),(5,750,340)]:
            near=[p for p in locs if p["car_color_candidate"]==car and
                  abs(p["center_x_1024"]-x)<=20 and
                  abs(p["center_y_584"]-y)<=20]
            self.assertTrue(near,car)
            self.assertFalse(near[0]["rider_number_confirmed"])

    def test_white_and_black_are_research_hold_not_false_proof(self):
        image=squares([(1,450,270),(3,650,270)])
        found=positive(image)
        self.assertTrue(any(p["car_color_candidate"]==3
                            for p in found["proposals"]))
        self.assertFalse(any(p["car_color_candidate"] in (1,2)
                             for p in found["proposals"]))
        self.assertEqual(found["uncalibrated_starters_excluded"],[1,2])
        self.assertTrue(found["untrusted_not_formal_rider_identity"])

    def test_header_and_bottom_reflections_not_scored_as_jerseys(self):
        image=squares([(3,330,60),(4,500,500)])
        report=positive(image)
        self.assertEqual(report["proposals"],[])

    def test_six_car_mode_does_not_require_seven_or_nine(self):
        image=squares([(6,440,290)])
        report=positive(image,roster=[1,2,3,4,5,6])
        self.assertEqual(report["roster_count"],6)
        self.assertEqual(report["proposals"][0]["car_color_candidate"],6)

    def test_absent_or_forged_existing_sha_must_stop(self):
        image=squares([(3,500,290)])
        with self.assertRaisesRegex(
            JerseyProposalError,"EXISTING_FRAME_SHA_MISMATCH"):
            detect_color_regions(image,roster=[1,2,3,4,5,6],
                                 source_crop_sha256="a"*64)
        with self.assertRaisesRegex(
            JerseyProposalError,"PRIVATE_RACE_STARTERS_REQUIRED"):
            positive(image,roster=[1,2,2,4,5,6])

    def test_pixel_array_has_to_be_actual_bgr(self):
        import numpy as np
        with self.assertRaisesRegex(
            JerseyProposalError,"REAL_BGR_SOURCE_CROP_REQUIRED"):
            detect_color_regions(np.zeros((20,20,3),dtype=np.uint8),
                                 roster=[1,2,3])

    def test_no_jpeg_bytes_or_raw_pixels_exported_by_detector(self):
        image=squares([(7,600,290)])
        out=positive(image)
        self.assertEqual(out["proposals"][0]["trust_tier"],
                         "UNTRUSTED_COLOR_BLOB_ONLY")
        self.assertNotIn("raw_pixels",str(out))
        self.assertNotIn("rider_name",str(out))


class ExploratorySingleReviewMatchingTests(unittest.TestCase):
    def test_one_to_one_spatial_matches_not_using_review_number_for_detection(self):
        image=squares([(3,280,260),(4,500,290)])
        p=positive(image)["proposals"]
        reviewed=[labeled(3,280,260),labeled(4,500,290),
                  labeled(1,60,310)]
        report=match_single_review_after_detection(p,reviewed)
        self.assertEqual(report["manual_single_review_count"],3)
        self.assertEqual(report["single_review_spatial_matches"],2)
        self.assertEqual(report["single_review_spatially_matched_color_agreements"],2)
        self.assertEqual(report["single_review_joint_position_and_color_coverage_pct"],
                         66.667)
        self.assertIsNone(report["independent_detection_recall_pct"])
        self.assertIsNone(report["independent_identity_accuracy_pct"])

    def test_wrong_color_near_review_counts_miss_not_success(self):
        p=positive(squares([(3,400,290)]))["proposals"]
        report=match_single_review_after_detection(
            p,[labeled(4,400,290)])
        self.assertEqual(report["single_review_spatial_matches"],1)
        self.assertEqual(report["single_review_spatially_matched_color_agreements"],0)
        self.assertEqual(report["color_agreement_given_spatial_match_pct"],0)

    def test_unreviewed_candidates_are_not_falsely_called_false_positives(self):
        p=positive(squares([(3,320,290),(4,700,290)]))["proposals"]
        out=match_single_review_after_detection(p,[labeled(3,320,290)])
        self.assertTrue(out["unreviewed_objects_cannot_be_called_false_positives"])
        self.assertGreaterEqual(out["single_review_unmatched_proposals"],1)

    def test_empty_truth_or_predictions_do_not_claim_perfect_accuracy(self):
        a=match_single_review_after_detection([],[])
        self.assertIsNone(a["color_agreement_given_spatial_match_pct"])
        self.assertIsNone(a["single_review_position_candidate_coverage_pct"])
        b=match_single_review_after_detection([],[labeled(3,200,280)])
        self.assertIsNone(b["color_agreement_given_spatial_match_pct"])
        self.assertEqual(b["single_review_joint_position_and_color_coverage_pct"],0)

    def test_duplicate_proposal_cannot_match_two_reviewers(self):
        p=positive(squares([(3,320,290)]))["proposals"]
        out=match_single_review_after_detection(
            p,[labeled(3,320,290),labeled(3,333,290)])
        self.assertEqual(out["single_review_spatial_matches"],1)


class TemporalColorCandidateTests(unittest.TestCase):
    def test_untrusted_same_color_track_requires_two_distinct_frames(self):
        a=squares([(3,315,285)])
        b=squares([(3,325,285)])
        rows=[
            {"sample_sec":20,"source_crop_sha256":sha256(a.tobytes()).hexdigest(),
             "proposals":positive(a)["proposals"]},
            {"sample_sec":22,"source_crop_sha256":sha256(b.tobytes()).hexdigest(),
             "proposals":positive(b)["proposals"]},
        ]
        out=link_untrusted_color_blobs(rows)
        self.assertEqual(out["schema"],TRACK_SCHEMA)
        self.assertGreaterEqual(out["track_candidates_seen_in_at_least_two_frames"],1)
        self.assertFalse(out["actual_rider_identity_confirmed"])
        self.assertFalse(out["track_order_and_line_position_confirmed"])
        self.assertFalse(out["phase_scoring_admitted"])

    def test_frame_sha_reuse_is_rejected(self):
        image=squares([(3,330,285)])
        row={"sample_sec":20,
             "source_crop_sha256":sha256(image.tobytes()).hexdigest(),
             "proposals":positive(image)["proposals"]}
        changed=copy.deepcopy(row)
        changed["sample_sec"]=22
        with self.assertRaisesRegex(
            JerseyProposalError,"TRACK_FRAME_SHA_TIME_OR_COUNT_INVALID"):
            link_untrusted_color_blobs([row,changed])

    def test_color_class_change_never_claims_same_rider_track(self):
        a=squares([(3,300,280)])
        b=squares([(6,300,280)])
        rows=[
            {"sample_sec":20,"source_crop_sha256":sha256(a.tobytes()).hexdigest(),
             "proposals":positive(a)["proposals"]},
            {"sample_sec":22,"source_crop_sha256":sha256(b.tobytes()).hexdigest(),
             "proposals":positive(b)["proposals"]},
        ]
        out=link_untrusted_color_blobs(rows)
        self.assertEqual(out["track_candidates_seen_in_at_least_two_frames"],0)

    def test_forged_trusted_color_blob_is_rejected(self):
        a=squares([(3,300,290)])
        proposals=positive(a)["proposals"]
        proposals[0]["trust_tier"]="INDEPENDENT_RIDER_ID"
        with self.assertRaisesRegex(
            JerseyProposalError,"FORGED_TRUSTED_TRACK_PROPOSAL"):
            link_untrusted_color_blobs([{
                "sample_sec":10,
                "source_crop_sha256":sha256(a.tobytes()).hexdigest(),
                "proposals":proposals,
            }])


if __name__=="__main__":
    unittest.main()
