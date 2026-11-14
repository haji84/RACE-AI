"""Proof that the NEW overlay consumes the EXISTING immutable PR102 admission.

This test constructs fictional screen-frame metadata. The actual PR102 module
is loaded from a SHA-pinned checkout. A successful test is NOT proof of footage,
provider rights, visual identification, predicted stages, or real-race scoring.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import importlib.util
import os
import unittest

from race_ai.keirin_phase_overlay import (
    STAGES, UNKNOWN, build_phase_forecast, score_six_phases,
)

RID = "203001151201"
JST = timezone(timedelta(hours=9))
CUTOFF = datetime(2030, 1, 15, 12, tzinfo=JST)
NOW = CUTOFF - timedelta(minutes=12)


def h(x):
    return sha256(x.encode()).hexdigest()


def event(name, stamp, label, rider=None):
    return {
        "id": name,
        "time_s": stamp,
        "label": label,
        "rider_id": rider,
        "action_key": "action_" + name,
        "frame_sha256": h("fictional-frame-" + name),
        "scene": "LIVE",
        "review_ref": "reviewed_" + name,
    }


def fixture_clip():
    return {
        "schema": "RACE_AI_KEIRIN_CLIP_REVIEW_V1",
        "race_id": RID,
        "source_url": "https://www.winticket.jp/keirin/aomori/raceresult/2030011512/1/1",
        "source_kind": "WINTICKET_PAST_REPLAY",
        "recording_sha256": h("fictional_clip_bytes_only"),
        "duration_s": 168,
        "claimed_coverage": "PARTIAL_HIGHLIGHTS",
        "reviewed_at": (CUTOFF + timedelta(hours=1)).isoformat(),
        "events": [
            event("bell_a", 38, "RACING"),
            event("bell_b", 40, "RACING"),
            event("bell_attack", 41, "ATTACK", "fictional-rider-1"),
        ],
    }


def parts():
    return {
        "leader": 1, "top3": [1, 7, 2],
        "line_groups": [[1, 4], [7, 2], [3], [5, 6]],
        "second_wheel": 4,
        "attack": {"rider": 1, "kind": "NIGE", "success": True},
    }


def forecast():
    return build_phase_forecast(
        race_id=RID,
        model_id="multisport-race-trajectory-v1",
        parent_prediction_sha256=h("fictional_parent_PR71_original"),
        pre_race_input_sha256=h("fictional_private_source"),
        parent_saved_at=(NOW - timedelta(minutes=1)).isoformat(),
        official_cutoff_at=CUTOFF.isoformat(),
        stage_predictions={
            phase: (parts() if phase == "BELL" else {
                name: UNKNOWN for name in (
                    "leader", "top3", "line_groups", "second_wheel", "attack")})
            for phase, _ in STAGES
        },
        clock=lambda: NOW,
    )


class ActualExistingPR102AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get("RACE_AI_PR102_PINNED_SOURCE_ROOT", "")
        if not root:
            raise RuntimeError("PR102_IMMUTABLE_CHECKOUT_REQUIRED")
        path = Path(root) / "race_ai" / "keirin_video_clip_policy.py"
        if not path.is_file():
            raise RuntimeError("PR102_EXISTING_CLIP_POLICY_NOT_FOUND")
        spec = importlib.util.spec_from_file_location(
            "_pinned_existing_pr102_video_clip_policy", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("PR102_MODULE_INVALID")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.clip_policy = module

    def test_existing_clip_admission_to_six_phase_scorer_end_to_end_offline(self):
        original = fixture_clip()
        admission = self.clip_policy.assess_clip(
            original, independent_visual_verifier=lambda x: True,
            rights_verifier=lambda source, purpose: True,
        )
        self.assertEqual(admission["admitted_coverage"], "PARTIAL_HIGHLIGHTS")
        self.assertTrue(admission["training_eligible"])
        self.assertFalse(admission["all_four_laps_verified"])
        obs = [{
            "phase": "BELL",
            "recording_sec": 39,
            "scene": "LIVE",
            "frame_sha256": [
                original["events"][0]["frame_sha256"],
                original["events"][1]["frame_sha256"],
            ],
            "review_refs": [
                original["events"][0]["review_ref"],
                original["events"][1]["review_ref"],
            ],
            "measured": parts(),
        }]
        scored = score_six_phases(
            forecast(), admission, obs,
            visual_verifier=lambda stage, video: True,
            rights_verifier=lambda video, purpose: True,
        )
        self.assertEqual(scored["comparison_coverage_pct"], 15.0)
        self.assertEqual(scored["visual_observation_coverage_pct"], 15.0)
        self.assertEqual(scored["earned_points_out_of_100_possible"], 15.0)
        self.assertEqual(scored["accuracy_on_comparable_components_pct"], 100.0)
        self.assertEqual(scored["status"], "RESEARCH_SCORE_ONLY_NOT_FORMAL")
        self.assertFalse(scored["independent_frozen_original_attested"])
        self.assertFalse(scored["independent_prospective_window_attested"])
        self.assertFalse(scored["model_parameters_updated"])
        self.assertFalse(scored["official_accuracy_or_roi_updated"])

    def test_clip_policy_denies_unverified_frame_rights_before_scoring(self):
        rejection = self.clip_policy.assess_clip(
            fixture_clip(),
            independent_visual_verifier=lambda x: False,
            rights_verifier=lambda source, purpose: True,
        )
        self.assertFalse(rejection["training_eligible"])
        self.assertEqual(rejection["admitted_coverage"], "NONE")
        self.assertEqual(rejection["reviewed_scene_frames"], [])
        scored = score_six_phases(
            forecast(), rejection, [],
            visual_verifier=lambda *args: True,
            rights_verifier=lambda *args: True,
        )
        self.assertEqual(scored["comparison_coverage_pct"], 0)
        self.assertEqual(scored["status"], "HOLD_NO_INDEPENDENTLY_COMPARABLE_PHASES")


if __name__ == "__main__":
    unittest.main()
