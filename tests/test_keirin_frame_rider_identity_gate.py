"""Offline 2-frame candidate-to-rider validation against existing SHA receipts.

Fictional OCR/visual callbacks. No real footage, independently trained video
recognition, actual rider accuracy or formal outcome is established by CI.
"""
from __future__ import annotations

from copy import deepcopy
import unittest

from race_ai.keirin_frame_rider_identity_gate import (
    FrameIdentityError, SCHEMA, REPORT, bridge_reviewed_frames,
    bridge_from_existing_pr71_ledger,
)
from race_ai.keirin_phase_overlay import score_six_phases
from tests.test_keirin_phase_overlay import (
    frozen, admitted, stage, result, digest, UNKNOWN, RID,
)

ROSTER=[1,2,3,4,5,6,7]


def observations():
    return [stage("BELL",39)]


def packets():
    example=observations()[0]
    result=[]
    for t,frame,ref in zip((38,40),example["frame_sha256"],
                            example["review_refs"]):
        riders=[]
        for n,(car,pos) in enumerate(((1,1),(7,2),(2,3))):
            riders.append({
                "track_id":f"track-{car}",
                "car_number_candidate":car,
                "number_confidence":.97,
                "rank_candidate":pos,
                "rank_confidence":.96,
                "bbox_xywh_normalized":[.1+n*.12,.2,.08,.16],
                "recognition_kind":"OCR_CANDIDATE",
            })
        result.append({
            "schema":SCHEMA,"phase":"BELL",
            "frame_sha256":frame,"review_ref":ref,
            "recording_sec":t,"scene":"LIVE",
            "candidates":riders,
        })
    return result


def bridge(frames=None,*,video=None,roster=None,confirm=True,pixel=True,
           lines=False):
    frames=packets() if frames is None else frames
    a=admitted(observations(),synthetic=False) if video is None else video
    return bridge_reviewed_frames(
        frozen(),a,ROSTER if roster is None else roster,frames,
        roster_original_verifier=lambda f,r:confirm,
        pixel_source_verifier=lambda packet,admission,roster:pixel,
        line_relation_verifier=lambda first,second,admission:lines,
    )


def saved_suite():
    f=frozen()
    before="2030-01-15T09:00:00+09:00"
    return {
        "source":{
            "race_id":RID,"official_cutoff_at":f["official_cutoff_at"],
            "as_of":before,"starters":list(ROSTER),
        },
        "suite":{
            "race_id":RID,"as_of":before,
            "input_sha256":f["pre_race_input_sha256"],
            "models":{
                f["model_id"]:{
                    "model_id":f["model_id"],
                    "prediction_sha256":f["parent_prediction_sha256"],
                    "snapshot_sha256":f["pre_race_input_sha256"],
                },
            },
        },
    }


class ExistingRiderCandidateGateTests(unittest.TestCase):
    def test_two_verified_frames_bind_candidate_numbers_and_ranks(self):
        out=bridge()
        self.assertEqual(out["schema"],REPORT)
        self.assertEqual(len(out["phase_observations"]),1)
        self.assertEqual(out["candidate_frames_received"],2)
        record=out["phase_observations"][0]
        self.assertEqual(record["phase"],"BELL")
        self.assertEqual(record["measured"]["leader"],1)
        self.assertEqual(record["measured"]["top3"],[1,7,2])
        self.assertEqual(record["measured"]["line_groups"],UNKNOWN)
        self.assertEqual(record["measured"]["second_wheel"],UNKNOWN)
        self.assertEqual(record["measured"]["attack"],UNKNOWN)
        self.assertFalse(out["real_rider_recognition_accuracy_established"])
        self.assertTrue(out["research_only_not_formal_evidence"])

    def test_existing_phase_scorer_considers_only_observed_two_fields(self):
        a=admitted(observations(),synthetic=False)
        frame=bridge(video=a)["phase_observations"]
        scored=score_six_phases(
            frozen(),a,frame,
            visual_verifier=lambda *args:True,
            frozen_original_verifier=lambda f:False,
            rights_verifier=lambda *args:True,
            official_result=result(),official_result_verifier=lambda o:False,
        )
        # BELL = 15 points. Leader 25% + top3 35% = 9/100.
        self.assertEqual(scored["visual_observation_coverage_pct"],9.0)
        self.assertEqual(scored["comparison_coverage_pct"],9.0)
        self.assertEqual(scored["earned_points_out_of_100_possible"],9.0)
        self.assertEqual(scored["accuracy_on_comparable_components_pct"],100.0)
        self.assertEqual(scored["status"],"RESEARCH_SCORE_ONLY_NOT_FORMAL")
        self.assertFalse(scored["automatic_model_promotion"])

    def test_existing_pr71_saved_roster_and_digests_are_reused(self):
        a=admitted(observations(),synthetic=False)
        f=frozen()
        report=bridge_from_existing_pr71_ledger(
            f,a,saved_suite(),packets(),
            ledger_readback_verifier=lambda saved,row:True,
            pixel_source_verifier=lambda packet,admission,roster:True)
        self.assertTrue(report["roster_verifier_accepted"])
        self.assertEqual(report["phase_observations"][0]["measured"]["leader"],1)
        self.assertFalse(report["attack_or_success_verified"])

    def test_unverified_saved_pr71_db_cannot_attest_rider_identity(self):
        a=admitted(observations(),synthetic=False)
        denied=bridge_from_existing_pr71_ledger(
            frozen(),a,saved_suite(),packets(),
            ledger_readback_verifier=lambda *_:False,
            pixel_source_verifier=lambda *_:True)
        self.assertFalse(denied["roster_verifier_accepted"])
        self.assertEqual(denied["phase_observations"],[])

    def test_modified_existing_model_source_sha_cannot_match_phase(self):
        saved=saved_suite()
        k=frozen()["model_id"]
        saved["suite"]["models"][k]["prediction_sha256"]="b"*64
        with self.assertRaisesRegex(FrameIdentityError,
                                    "PR71_PHASE_PARENT_OR_RACE_MISMATCH"):
            bridge_from_existing_pr71_ledger(
                frozen(),admitted(observations(),synthetic=False),
                saved,packets(),ledger_readback_verifier=lambda *args:True,
                pixel_source_verifier=lambda *args:True)

    def test_independent_two_frame_line_joins_can_score_real_line_mismatch(self):
        p=packets()
        for row in p:
            for n,car in enumerate((3,4,5,6),start=4):
                row["candidates"].append({
                    "track_id":f"track-{car}",
                    "car_number_candidate":car,
                    "number_confidence":.97,
                    "rank_candidate":n,
                    "rank_confidence":.96,
                    "bbox_xywh_normalized":[.1+(n-1)*.12,.2,.08,.16],
                    "recognition_kind":"OCR_CANDIDATE",
                })
            row["line_groups_candidate"]=[[1,7],[2],[3,4],[5,6]]
        a=admitted(observations(),synthetic=False)
        without=bridge(frames=p,video=a)
        self.assertEqual(without["phase_observations"][0]["measured"]["line_groups"],
                         UNKNOWN)
        self.assertFalse(without["line_or_second_wheel_verified"])
        with_lines=bridge(frames=p,video=a,lines=True)
        measured=with_lines["phase_observations"][0]["measured"]
        self.assertEqual(measured["line_groups"],[[1,7],[2],[3,4],[5,6]])
        self.assertEqual(measured["second_wheel"],7)
        self.assertTrue(with_lines["line_or_second_wheel_verified"])
        self.assertEqual(measured["attack"],UNKNOWN)
        scored=score_six_phases(
            frozen(),a,with_lines["phase_observations"],
            visual_verifier=lambda *args:True,
            rights_verifier=lambda *args:True,
        )
        # BELL leader+top3 agree (9 pts); line and second-wheel do not (4.5 pts).
        self.assertEqual(scored["comparison_coverage_pct"],13.5)
        self.assertEqual(scored["earned_points_out_of_100_possible"],9.0)
        self.assertEqual(scored["phases"][1]["component_outcomes"]["line_groups"],
                         "MISS")
        self.assertEqual(scored["phases"][1]["component_outcomes"]["second_wheel"],
                         "MISS")
        self.assertFalse(scored["formal_evaluation_inputs_attested"])

    def test_partial_visible_line_scores_second_wheel_not_full_line_groups(self):
        p=packets()
        for row in p:
            row["line_groups_candidate"]=[[1,7],[2]]
        a=admitted(observations(),synthetic=False)
        f=bridge(frames=p,video=a,lines=True)
        seen=f["phase_observations"][0]["measured"]
        self.assertEqual(seen["line_groups"],UNKNOWN)
        self.assertEqual(seen["second_wheel"],7)
        self.assertEqual(f["stage_status"][1]["reason"],
                         "PARTIAL_LINE_SECOND_WHEEL_ONLY")
        scored=score_six_phases(
            frozen(),a,f["phase_observations"],
            visual_verifier=lambda *args:True,
            rights_verifier=lambda *args:True)
        self.assertEqual(scored["comparison_coverage_pct"],11.25)
        self.assertEqual(scored["earned_points_out_of_100_possible"],9.0)
        self.assertEqual(scored["phases"][1]["component_outcomes"]["line_groups"],
                         "UNKNOWN")
        self.assertEqual(scored["phases"][1]["component_outcomes"]["second_wheel"],
                         "MISS")
        self.assertFalse(scored["formal_evaluation_inputs_attested"])

    def test_disagreement_or_missing_independent_line_attestor_means_unknown(self):
        p=packets()
        p[0]["line_groups_candidate"]=[[1,7],[2]]
        p[1]["line_groups_candidate"]=[[1],[7,2]]
        out=bridge(frames=p,lines=True)
        self.assertEqual(out["phase_observations"][0]["measured"]["line_groups"],
                         UNKNOWN)
        self.assertFalse(out["line_or_second_wheel_verified"])
        p[1]["line_groups_candidate"]=[[1,7],[2]]
        out=bridge(frames=p,lines=False)
        self.assertEqual(out["phase_observations"][0]["measured"]["line_groups"],
                         UNKNOWN)

    def test_line_cannot_contain_unseen_car_or_duplicate_member(self):
        p=packets()
        p[0]["line_groups_candidate"]=[[1,4],[7,2]]
        with self.assertRaisesRegex(
                FrameIdentityError,"LINE_MEMBER_MISSING_FROM_FRAME_OR_DUPLICATED"):
            bridge(frames=p,lines=True)
        p=packets()
        p[0]["line_groups_candidate"]=[[1,7],[1,2]]
        with self.assertRaisesRegex(
                FrameIdentityError,"LINE_MEMBER_MISSING_FROM_FRAME_OR_DUPLICATED"):
            bridge(frames=p,lines=True)

    def test_empty_or_unreviewed_frames_make_all_stages_unknown(self):
        for row in ([],packets()[:1]):
            out=bridge(frames=row)
            self.assertEqual(out["phase_observations"],[])
            self.assertEqual(len(out["stage_status"]),6)
            self.assertTrue(all(v["state"]=="UNKNOWN" for v in out["stage_status"]))
        out=bridge(pixel=False)
        self.assertEqual(out["phase_observations"],[])
        out=bridge(confirm=False)
        self.assertEqual(out["phase_observations"],[])

    def test_synthetic_clip_not_treated_as_independent_real_rider_labels(self):
        a=admitted(observations(),synthetic=True)
        out=bridge(video=a)
        self.assertEqual(out["phase_observations"],[])

    def test_six_car_video_review_is_supported_but_not_pr71_model_promotion(self):
        p=packets()
        for row in p:
            for item in row["candidates"]:
                if item["car_number_candidate"]==7:
                    item["car_number_candidate"]=6
                    item["track_id"]="track-6"
        r=bridge(frames=p,roster=[1,2,3,4,5,6])
        self.assertEqual(r["registered_starter_count"],6)
        self.assertEqual(r["phase_observations"][0]["measured"]["top3"],
                         [1,6,2])
        self.assertFalse(r["same_race_training_or_forecast_modified"])

    def test_color_blob_without_verified_number_never_promotes_phase_score(self):
        p=packets()
        for row in p:
            for item in row["candidates"]:
                item["recognition_kind"]="UNTRUSTED_COLOR_BLOB"
        r=bridge(frames=p,pixel=True,confirm=True,lines=True)
        self.assertEqual(r["phase_observations"],[])
        self.assertFalse(r["real_rider_recognition_accuracy_established"])
        self.assertEqual(r["stage_status"][1]["state"],"UNKNOWN")

    def test_low_ocr_confidence_stays_unknown(self):
        p=packets()
        for row in p:
            for item in row["candidates"]:
                item["number_confidence"]=.7
        out=bridge(frames=p)
        self.assertEqual(out["phase_observations"],[])
        self.assertEqual(out["stage_status"][1]["reason"],
                         "NO_TWO_FRAME_POSITION_CONSENSUS")

    def test_position_change_between_two_frames_is_not_a_false_unchanged_rank(self):
        p=packets()
        p[1]["candidates"][0]["rank_candidate"]=2
        p[1]["candidates"][1]["rank_candidate"]=1
        out=bridge(frames=p)
        self.assertEqual(out["phase_observations"],[])

    def test_replayed_frame_cannot_vote_as_live(self):
        p=packets()
        p[1]["scene"]="REPLAY"
        out=bridge(frames=p)
        self.assertEqual(out["phase_observations"],[])

    def test_unknown_roster_car_or_duplicate_position_fail_closed(self):
        p=packets()
        p[0]["candidates"][0]["car_number_candidate"]=8
        with self.assertRaisesRegex(FrameIdentityError,
                                    "CAR_NOT_IN_AUTHENTICATED_ROSTER_OR_DUPLICATE"):
            bridge(frames=p)
        p=packets()
        p[0]["candidates"][0]["rank_candidate"]=2
        with self.assertRaisesRegex(FrameIdentityError,
                                    "DUPLICATE_RACE_POSITION_IN_FRAME"):
            bridge(frames=p)

    def test_unreviewed_frame_sha_and_reference_do_not_get_scores(self):
        p=packets()
        p[0]["frame_sha256"]="d"*64
        with self.assertRaisesRegex(FrameIdentityError,
                                    "FRAME_NOT_IN_EXISTING_VIDEO_REVIEW"):
            bridge(frames=p)
        p=packets()
        p[0]["review_ref"]="invented-review-01"
        with self.assertRaisesRegex(FrameIdentityError,
                                    "FRAME_NOT_IN_EXISTING_VIDEO_REVIEW"):
            bridge(frames=p)

    def test_bad_crop_bounds_and_duplicate_frame_cannot_score(self):
        p=packets()
        p[0]["candidates"][0]["bbox_xywh_normalized"]=[.99,.2,.4,.1]
        with self.assertRaisesRegex(FrameIdentityError,
                                    "RIDER_BOUNDING_BOX_INVALID"):
            bridge(frames=p)
        p=packets()
        p[1]["frame_sha256"]=p[0]["frame_sha256"]
        p[1]["review_ref"]=p[0]["review_ref"]
        with self.assertRaisesRegex(FrameIdentityError,
                                    "FRAME_REUSED_ACROSS_PHASES"):
            bridge(frames=p)

    def test_wrong_roster_confirmation_does_not_bypass_independent_proof(self):
        with self.assertRaisesRegex(FrameIdentityError,
                                    "EXISTING_PR71_ROSTER_REQUIRED"):
            bridge(roster=[1,2])
        out=bridge(confirm=False)
        self.assertFalse(out["roster_verifier_accepted"])
        self.assertEqual(out["phase_observations"],[])


if __name__=="__main__":
    unittest.main()
