"""Synthetic color rectangles only; no real rider identities or phase truth."""
from __future__ import annotations

from hashlib import sha256
from copy import deepcopy
import unittest

from race_ai.keirin_color_track_flow_guard import (
    color_scene_guarded_tracks, ColorSceneGateError,SCHEMA,ACCEPT,
)
from race_ai.keirin_camera_motion_quality import SCHEMA as MOTION_SCHEMA


def sha(s):return sha256(s.encode()).hexdigest()


def frame(t,car=4,xy=(400,275)):
    return {
        "sample_sec":t,
        "source_crop_sha256":sha(f"frozen-frame-{t}"),
        "proposals":[{
            "car_color_candidate":car,
            "center_x_1024":xy[0],
            "center_y_584":xy[1],
            "trust_tier":"UNTRUSTED_COLOR_BLOB_ONLY",
        }],
    }


def receipt(before,after,state):
    return {
        "previous_frame_sha256":before["source_crop_sha256"],
        "current_frame_sha256":after["source_crop_sha256"],
        "motion":{
            "schema":MOTION_SCHEMA,
            "gap_seconds":after["sample_sec"]-before["sample_sec"],
            "camera_transform_quality_state":state,
            "reliable_for_person_id_or_tactics":False,
            "phase_scoring_admitted":False,
        },
    }


class CameraCutGuardIsNotRiderAccuracy(unittest.TestCase):
    def test_good_geometry_allows_only_untrusted_color_continuity(self):
        rows=[frame(0),frame(2,xy=(407,275)),frame(4,xy=(410,275))]
        changes=[receipt(rows[i],rows[i+1],ACCEPT) for i in (0,1)]
        x=color_scene_guarded_tracks(rows,changes)
        self.assertEqual(x["schema"],SCHEMA)
        self.assertEqual(x["scene_guarded_untrusted_color_tracks_seen_twice"],1)
        self.assertEqual(x["baseline_untrusted_color_tracks_seen_twice"],1)
        self.assertEqual(x["background_geometry_candidate_transitions"],2)
        self.assertIsNone(x["confirmed_rider_track_accuracy_pct"])
        self.assertIsNone(x["confirmed_phase_accuracy_pct"])
        self.assertFalse(x["eligible_for_formal_PDCA_or_training"])

    def test_camera_quality_failure_breaks_same_color_mere_spatial_track(self):
        rows=[frame(0),frame(2,xy=(405,275)),frame(4,xy=(410,275))]
        changes=[
            receipt(rows[0],rows[1],"LOW_INLIER_GLOBAL_FLOW"),
            receipt(rows[1],rows[2],"INSUFFICIENT_TRACKED_FEATURES"),
        ]
        got=color_scene_guarded_tracks(rows,changes)
        self.assertEqual(got["untrusted_or_unverifiable_transitions"],2)
        self.assertEqual(got["research_scene_segments"],3)
        self.assertEqual(got["single_frame_segments"],3)
        self.assertEqual(got["baseline_untrusted_color_tracks_seen_twice"],1)
        self.assertEqual(got["scene_guarded_untrusted_color_tracks_seen_twice"],0)
        self.assertFalse(got["camera_ambiguous_transitions_are_linked"])

    def test_only_verified_middle_pair_forms_one_research_tracklet(self):
        rows=[frame(0),frame(2,xy=(405,275)),frame(4,xy=(410,275))]
        changes=[
            receipt(rows[0],rows[1],"LOW_INLIER_GLOBAL_FLOW"),
            receipt(rows[1],rows[2],ACCEPT),
        ]
        x=color_scene_guarded_tracks(rows,changes)
        self.assertEqual(x["research_scene_segments"],2)
        self.assertEqual(x["scene_guarded_untrusted_color_tracks_seen_twice"],1)
        self.assertEqual(x["single_frame_segments"],1)

    def test_adversarial_frame_sha_swap_rejected_before_any_track(self):
        rows=[frame(0),frame(2)]
        wrong=receipt(rows[0],rows[1],ACCEPT)
        wrong["previous_frame_sha256"]=sha("different")
        with self.assertRaisesRegex(
            ColorSceneGateError,"INVALID_SHA_BOUND_CAMERA_PAIR_RECEIPT"):
            color_scene_guarded_tracks(rows,[wrong])

    def test_motion_receipt_does_not_become_approval_via_boolean_flag(self):
        rows=[frame(0),frame(2)]
        wrong=receipt(rows[0],rows[1],ACCEPT)
        wrong["motion"]["reliable_for_person_id_or_tactics"]=True
        with self.assertRaisesRegex(
            ColorSceneGateError,"INVALID_SHA_BOUND_CAMERA_PAIR_RECEIPT"):
            color_scene_guarded_tracks(rows,[wrong])

    def test_missing_or_duplicate_frames_refused(self):
        a=frame(0);b=frame(2)
        with self.assertRaisesRegex(
            ColorSceneGateError,"ADJACENT_REAL_FRAME_AND_FLOW_RECEIPTS_REQUIRED"):
            color_scene_guarded_tracks([a,b],[])
        dup=deepcopy(b)
        dup["source_crop_sha256"]=a["source_crop_sha256"]
        with self.assertRaisesRegex(
            ColorSceneGateError,"INVALID_FROZEN_COLOR_FRAME_OR_SHA"):
            color_scene_guarded_tracks([a,dup],[receipt(a,dup,ACCEPT)])

    def test_no_fabricated_car_number_confidence_or_position(self):
        rows=[frame(0,car=4),frame(2,car=6)]
        result=color_scene_guarded_tracks(
            rows,[receipt(rows[0],rows[1],ACCEPT)])
        self.assertEqual(result["scene_guarded_untrusted_color_tracks_seen_twice"],0)
        self.assertFalse(result["existing_PR71_model_weights_modified"])
        self.assertIsNone(result["confirmed_rider_number_OCR_accuracy_pct"])
        self.assertEqual(result["verified_human_independent_reference_count"],0)


if __name__=="__main__":
    unittest.main()
