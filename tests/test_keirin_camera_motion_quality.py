"""Synthetic motion geometry gates, not human rider identities."""
from __future__ import annotations

from hashlib import sha256
import unittest

from race_ai.keirin_camera_motion_quality import (
    SCHEMA,MotionQualityError,assess_pair,summarize_motion,
)


def digest(frame):
    return sha256(frame.tobytes()).hexdigest()


class CameraFlowResearchTests(unittest.TestCase):
    def test_identical_source_frame_cannot_be_used_as_motion_proof(self):
        import numpy as np
        frame=np.zeros((292,515,3),dtype=np.uint8)
        d=digest(frame)
        out=assess_pair(frame,frame,previous_sha=d,current_sha=d)
        self.assertEqual(out["camera_transform_quality_state"],
                         "REPEATED_FRAME_NO_FLOW_PROOF")
        self.assertFalse(out["reliable_for_person_id_or_tactics"])

    def test_no_visual_features_remains_unassessable(self):
        import numpy as np
        f=np.zeros((292,515,3),dtype=np.uint8)
        g=np.full_like(f,130)
        out=assess_pair(f,g,previous_sha=digest(f),current_sha=digest(g))
        self.assertEqual(out["camera_transform_quality_state"],
                         "INSUFFICIENT_SOURCE_FEATURES")
        self.assertIsNone(out["global_affine_inlier_fraction"])

    def test_source_sha_and_frame_shape_must_match(self):
        import numpy as np
        f=np.zeros((292,515,3),dtype=np.uint8)
        g=np.ones_like(f)
        with self.assertRaisesRegex(
                MotionQualityError,"SOURCE_IMAGE_SHA_OR_BGR_INVALID"):
            assess_pair(f,g,previous_sha="f"*64,current_sha=digest(g))
        with self.assertRaisesRegex(
                MotionQualityError,"FLOW_FRAME_SHAPES_DIFFER"):
            s=np.ones((290,510,3),dtype=np.uint8)
            assess_pair(f,s,previous_sha=digest(f),current_sha=digest(s))

    def test_many_stable_feature_tracks_are_only_camera_geometry_candidate(self):
        import numpy as np
        import cv2
        f=np.zeros((292,515,3),dtype=np.uint8)
        rng=np.random.default_rng(1008)
        for x,y in zip(rng.integers(12,500,170),
                       rng.integers(12,280,170)):
            cv2.circle(f,(int(x),int(y)),2,(240,240,240),-1)
        matrix=np.float32([[1,0,4],[0,1,3]])
        g=cv2.warpAffine(f,matrix,(515,292))
        r=assess_pair(f,g,previous_sha=digest(f),current_sha=digest(g))
        self.assertGreaterEqual(r["tracked_features"],20)
        self.assertEqual(
            r["camera_transform_quality_state"],
            "BACKGROUND_FLOW_GEOMETRY_CANDIDATE_ONLY")
        self.assertFalse(r["reliable_for_person_id_or_tactics"])
        self.assertFalse(r["phase_scoring_admitted"])
        self.assertFalse(r["actual_rider_motion_or_number_verified"])

    def test_unreliable_flow_aggregate_is_not_actual_rider_miss(self):
        import numpy as np
        frame=np.zeros((292,515,3),dtype=np.uint8)
        f=digest(frame)
        r=assess_pair(frame,frame,previous_sha=f,current_sha=f)
        out=summarize_motion([r],expected_transitions=1)
        self.assertEqual(out["source_frame_pairs"],1)
        self.assertEqual(out["pairs_without_a_reliable_background_transform"],1)
        self.assertIsNone(out["qualified_rider_track_pairs"])
        self.assertIsNone(out["race_position_or_line_coverage_pct"])

    def test_impossible_transition_count_refused(self):
        with self.assertRaisesRegex(
                MotionQualityError,"MOTION_QUALITY_SOURCE_SET_INVALID"):
            summarize_motion([],expected_transitions=1)


if __name__=="__main__":
    unittest.main()
