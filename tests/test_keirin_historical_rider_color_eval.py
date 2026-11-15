"""No video or real rider labels in this CI: purely synthetic HSV and rows.

This regression keeps unknowns from becoming perfect/wrong predictions. The
real historical media run is a separate owner-private one-review experiment.
"""
import copy
import unittest
from hashlib import sha256

from race_ai.keirin_historical_rider_color_eval import (
    UNKNOWN, SCHEMA, REPORT_SCHEMA, HistoricalColorError,
    classify_hsv_patch, aggregate_historical_color_scores, sha_json,
)


def h(s):
    return sha256(s.encode()).hexdigest()


def patch(hue,sat,value,n=256):
    return [[hue,sat,value] for _ in range(n)]


def record(race,second,car,guess):
    return dict(race_id=race,sample_second=second,frame_sha256=h(
        race+":"+str(second)),reviewed_car_number=car,
        candidate_car_number=guess)


class PrivateHistoricalColorCandidateTests(unittest.TestCase):
    def test_jersey_palette_has_white_black_red_blue_yellow_green_orange(self):
        inputs={
            1:(0,4,230),
            2:(0,10,40),
            3:(176,120,180),
            4:(100,120,190),
            5:(25,150,210),
            6:(69,120,210),
            7:(11,140,210),
        }
        for color,hsv in inputs.items():
            with self.subTest(car=color):
                r=classify_hsv_patch(patch(*hsv),
                                     allowed_car_numbers=[1,2,3,4,5,6,7])
                self.assertEqual(r["candidate_car_number"],color)
                self.assertEqual(r["schema"],SCHEMA)
                self.assertFalse(r["probability_calibrated"])
                self.assertFalse(r["automatic_rider_detection"])
                self.assertFalse(r["position_or_line_verified"])

    def test_unknown_color_abstains_without_forced_nearest_car(self):
        ambiguous=patch(35,20,120)
        x=classify_hsv_patch(ambiguous,allowed_car_numbers=[1,2,3,4,5,6,7])
        self.assertEqual(x["candidate_car_number"],UNKNOWN)
        self.assertTrue(x["abstained"])
        self.assertEqual(x["color_evidence_fraction"],0)

    def test_margin_rejects_equally_plausible_colors(self):
        pixels=patch(25,110,220,128)+patch(69,110,220,128)
        report=classify_hsv_patch(
            pixels,allowed_car_numbers=[1,2,3,4,5,6,7])
        self.assertEqual(report["candidate_car_number"],UNKNOWN)
        self.assertLess(report["margin_fraction"],.05)

    def test_six_rider_video_supported_without_7_9_model_assumption(self):
        decision=classify_hsv_patch(
            patch(100,120,190),allowed_car_numbers=[1,2,3,4,5,6])
        self.assertEqual(decision["candidate_car_number"],4)

    def test_no_roster_no_image_no_pseudo_probability(self):
        for x in ([],[1,2],[1,2,3,3],[0,1,2],list(range(1,11))):
            with self.subTest(roster=x), self.assertRaises(HistoricalColorError):
                classify_hsv_patch(patch(100,100,200),allowed_car_numbers=x)
        with self.assertRaisesRegex(HistoricalColorError,"INVALID_HSV_VALUE"):
            classify_hsv_patch([[200,60,100]],
                               allowed_car_numbers=[1,2,3,4,5,6,7])

    def test_count_unverified_crop_coverage_separately_from_accuracy(self):
        a,b,c="202611091201","202611091202","202611091203"
        records=[record(a,48,1,1),record(a,48,2,1),
                 record(b,64,2,UNKNOWN),record(b,64,4,4),
                 record(c,78,7,7),record(c,78,3,UNKNOWN)]
        # Two errors/abstentions never become a false 100pt stage result.
        out=aggregate_historical_color_scores(
            records,race_ids=[a,b,c],sample_frames_expected=153,
            complete_frame_sha_matches=153)
        self.assertEqual(out["schema"],REPORT_SCHEMA)
        self.assertEqual(out["manually_localized_jersey_crops"],6)
        self.assertEqual(out["color_car_candidates_decided"],4)
        self.assertEqual(out["color_car_candidates_matching_single_review"],3)
        self.assertEqual(out["conditional_single_review_color_match_pct"],75)
        self.assertEqual(out["candidate_decision_coverage_pct"],66.667)
        self.assertEqual(out["exact_saved_frame_sha_matches"],153)
        self.assertIsNone(out["complete_automatic_car_detection_accuracy_pct"])
        self.assertIsNone(out["position_accuracy_pct"])
        self.assertIsNone(out["line_accuracy_pct"])
        self.assertIsNone(out["phase_weighted_accuracy_pct"])
        self.assertEqual(out["six_phase_gates_requiring_true_phase_annotations"],18)
        self.assertEqual(out["verified_six_phase_count"],0)
        self.assertFalse(out["eligible_for_official_accuracy_or_training"])
        self.assertFalse(out["existing_PR71_model_weights_modified"])
        self.assertEqual(out["report_sha256"],sha_json({
            k:v for k,v in out.items() if k!="report_sha256"
        }))

    def test_unscored_no_decisions_is_null_not_zero_or_perfect(self):
        rid="202611091201"
        report=aggregate_historical_color_scores(
            [record(rid,48,6,UNKNOWN)],race_ids=[rid],
            sample_frames_expected=54,complete_frame_sha_matches=54)
        self.assertIsNone(report["conditional_single_review_color_match_pct"])
        self.assertEqual(report["candidate_decision_coverage_pct"],0)
        self.assertEqual(report["races"][0]["matches_with_single_review"],0)

    def test_bad_sha_forged_identity_and_duplicates_rejected(self):
        rid="202611091203"
        d=record(rid,78,7,7)
        for rows in ([d,d], [{**d,"frame_sha256":"X"*64}],
                     [{**d,"race_id":"202611091202"}]):
            with self.subTest(rows=rows),self.assertRaises(HistoricalColorError):
                aggregate_historical_color_scores(
                    rows,race_ids=[rid],sample_frames_expected=50,
                    complete_frame_sha_matches=50)

    def test_partial_video_readback_is_not_100pct(self):
        rid="202611091203"
        report=aggregate_historical_color_scores(
            [record(rid,78,7,7)],race_ids=[rid],
            sample_frames_expected=50,complete_frame_sha_matches=48)
        self.assertEqual(report["saved_frame_readback_coverage_pct"],96)
        self.assertFalse(report["eligible_for_official_accuracy_or_training"])


if __name__=="__main__":
    unittest.main()
