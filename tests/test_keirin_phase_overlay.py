"""Offline six-stage forecast / verified-video scoring regressions.

All riders, SHA values, frames and official-looking results are invented.
No source network, private footage, production model, or live accuracy claim.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import copy
import json
import unittest

from race_ai.keirin_phase_overlay import (
    PHASE_SCHEMA, SCORE_SCHEMA, STAGES, UNKNOWN, PhaseError, digest,
    build_phase_forecast, checked_forecast, freeze_private_once,
    score_six_phases,
)

JST = timezone(timedelta(hours=9))
CUT = datetime(2030, 1, 15, 12, 0, tzinfo=JST)
NOW = CUT - timedelta(minutes=12)
RID = "203001151201"


def h(x):
    return sha256(x.encode("utf-8")).hexdigest()


def parts():
    return {
        "leader": 1,
        "top3": [1, 7, 2],
        "line_groups": [[1, 4], [7, 2], [3], [5, 6]],
        "second_wheel": 4,
        "attack": {"rider": 1, "kind": "NIGE", "success": True},
    }


def frozen():
    return build_phase_forecast(
        race_id=RID, model_id="multisport-race-trajectory-v1",
        parent_prediction_sha256=h("prior verified PR71 suite, fictional"),
        pre_race_input_sha256=h("before-cutoff private source packet"),
        parent_saved_at=(NOW - timedelta(seconds=30)).isoformat(),
        official_cutoff_at=CUT.isoformat(),
        stage_predictions={name: parts() for name, _ in STAGES},
        clock=lambda: NOW,
    )


def stage(name, time_s, *, scene="LIVE", data=None):
    fields = parts() if data is None else data
    return {
        "phase": name, "recording_sec": float(time_s),
        "scene": scene, "frame_sha256": [h(name + "-frame-a"),
                                        h(name + "-frame-b")],
        "review_refs": [name + "_frame_a", name + "_frame_b"],
        "measured": fields,
    }


TIMES = [10, 39, 68, 93, 125, 161]


def all_stages():
    return [stage(name, time) for (name, _), time in zip(STAGES, TIMES)]


def admitted(observations, *, synthetic=True, reviewed_at=None):
    scene_frames = []
    for s in observations:
        for frame, ref in zip(s["frame_sha256"], s["review_refs"]):
            scene_frames.append({
                "frame_sha256": frame, "review_ref": ref,
                "label": "RACING", "time_s": s["recording_sec"],
            })
    doc = {
        "schema": "RACE_AI_KEIRIN_CLIP_TRAINING_ADMISSION_V1",
        "race_id": RID,
        "recording_sha256": h("fictional private screen clip"),
        "source_url": "synthetic://no-media" if synthetic else
                      "https://www.winticket.jp/keirin/example",
        "source_kind": "SYNTHETIC_FIXTURE" if synthetic else "WINTICKET_PAST_REPLAY",
        "admitted_coverage": "NONE" if synthetic else "PARTIAL_HIGHLIGHTS",
        "training_eligible": not synthetic,
        "duration_s": 168.0,
        "reviewed_at": reviewed_at or (CUT + timedelta(hours=1)).isoformat(),
        "reviewed_scene_frames": scene_frames,
    }
    doc["admission_sha256"] = digest(doc)
    return doc


def result(order=None, *, published_at=None):
    return {
        "race_id": RID,
        "ordered_top3": [1, 7, 2] if order is None else order,
        "published_at": published_at or (CUT + timedelta(minutes=20)).isoformat(),
        "source_result_sha256": h("fictional official-result bytes"),
    }


def compare(observations=None, *, frozen_doc=None, permission=None,
            verified_frame=True, original=False, official=None, result_ok=False):
    observations = all_stages() if observations is None else observations
    permission = admitted(observations) if permission is None else permission
    return score_six_phases(
        frozen_doc or frozen(), permission, observations,
        visual_verifier=lambda o, a: verified_frame,
        frozen_original_verifier=(lambda o: original),
        rights_verifier=lambda admission, purpose: True,
        official_result=official,
        official_result_verifier=lambda o: result_ok,
    )


class BeforeCutoffSidecarTests(unittest.TestCase):
    def test_existing_model_and_sha_bound_six_stage_snapshot(self):
        row = frozen()
        self.assertEqual(row["schema"], PHASE_SCHEMA)
        self.assertEqual(list(row["stage_predictions"]), [x for x, _ in STAGES])
        self.assertEqual(sum(weight for _, weight in STAGES), 100)
        self.assertEqual(checked_forecast(row), row)

    def test_private_create_once_binds_exact_readback_and_never_overwrites(self):
        with TemporaryDirectory() as folder:
            target = Path(folder) / "real-private-sidecar.json"
            first = freeze_private_once(target, frozen())
            self.assertEqual(first, sha256(target.read_bytes()).hexdigest())
            before = target.read_bytes()
            with self.assertRaisesRegex(PhaseError, "PRIVATE_FREEZE_PATH_UNSAFE_OR_EXISTS"):
                freeze_private_once(target, frozen())
            self.assertEqual(before, target.read_bytes())

    def test_tampering_with_stage_or_parent_sha_is_rejected(self):
        for change in ("leader", "parent_prediction_sha256", "frozen_at"):
            row = copy.deepcopy(frozen())
            if change == "leader":
                row["stage_predictions"]["BELL"]["leader"] = 8
            elif change == "parent_prediction_sha256":
                row[change] = h("different original")
            else:
                row[change] = CUT.isoformat()
            with self.subTest(change=change), self.assertRaises(PhaseError):
                checked_forecast(row)

    def test_without_proven_pre_cutoff_parent_or_missing_stage_holds(self):
        base = frozen()
        with self.assertRaisesRegex(PhaseError, "MISSING_PRE_CUTOFF_PHASE_FREEZE"):
            build_phase_forecast(
                race_id=RID, model_id=base["model_id"],
                parent_prediction_sha256=base["parent_prediction_sha256"],
                pre_race_input_sha256=base["pre_race_input_sha256"],
                parent_saved_at=base["parent_saved_at"],
                official_cutoff_at=base["official_cutoff_at"],
                stage_predictions=base["stage_predictions"],
                clock=lambda: CUT + timedelta(minutes=1))
        with self.assertRaisesRegex(PhaseError, "ALL_SIX_STAGES_REQUIRED"):
            build_phase_forecast(
                race_id=RID, model_id=base["model_id"],
                parent_prediction_sha256=base["parent_prediction_sha256"],
                pre_race_input_sha256=base["pre_race_input_sha256"],
                parent_saved_at=base["parent_saved_at"],
                official_cutoff_at=base["official_cutoff_at"],
                stage_predictions={"BELL": parts()}, clock=lambda: NOW)

    def test_bad_vehicle_order_and_attack_are_never_auto_corrected(self):
        for field, bad in (("top3", [1, 1, 2]),
                           ("leader", 0),
                           ("attack", {"rider": 4, "kind": "NONE",
                                      "success": False}),
                           ("second_wheel", True)):
            row = copy.deepcopy(frozen())
            row["stage_predictions"]["BELL"][field] = bad
            row["phase_forecast_sha256"] = digest({
                k: v for k, v in row.items() if k != "phase_forecast_sha256"})
            with self.subTest(field=field), self.assertRaises(PhaseError):
                checked_forecast(row)


class PostRaceStageScoreTests(unittest.TestCase):
    def test_perfect_synthetic_is_100_of_100_but_not_formal(self):
        doc = compare(official=result(), result_ok=True, original=True)
        self.assertEqual(doc["schema"], SCORE_SCHEMA)
        self.assertEqual(doc["weight_total"], 100)
        self.assertEqual(doc["visual_observation_coverage_pct"], 100.0)
        self.assertEqual(doc["comparison_coverage_pct"], 100.0)
        self.assertEqual(doc["earned_points_out_of_100_possible"], 100.0)
        self.assertEqual(doc["accuracy_on_comparable_components_pct"], 100.0)
        self.assertFalse(doc["formal_evaluation_inputs_attested"])
        self.assertFalse(doc["automatic_model_promotion"])
        self.assertFalse(doc["official_accuracy_or_roi_updated"])

    def test_partial_visible_video_does_not_auto_penalize_undetected_phases(self):
        observations = [
            stage("FINAL_BACK", 93), stage("GOAL", 161)
        ]
        observations[0]["measured"]["leader"] = 7
        doc = compare(observations)
        self.assertEqual(doc["visual_observation_coverage_pct"], 45.0)
        self.assertEqual(doc["comparison_coverage_pct"], 45.0)
        self.assertEqual(doc["earned_points_out_of_100_possible"], 40.0)
        self.assertAlmostEqual(doc["accuracy_on_comparable_components_pct"], 88.889, places=3)
        self.assertEqual(doc["phases"][0]["status"], "UNKNOWN")
        self.assertEqual(doc["phases"][3]["component_outcomes"]["leader"], "MISS")
        self.assertEqual(doc["status"], "RESEARCH_SCORE_ONLY_NOT_FORMAL")

    def test_unknown_component_excluded_not_full_or_zero(self):
        obs = [stage("GOAL", 161)]
        obs[0]["measured"]["leader"] = UNKNOWN
        obs[0]["measured"]["top3"] = UNKNOWN
        doc = compare(obs)
        self.assertAlmostEqual(doc["comparison_coverage_pct"], 10.0)
        self.assertAlmostEqual(doc["earned_points_out_of_100_possible"], 10.0)
        self.assertEqual(doc["accuracy_on_comparable_components_pct"], 100.0)
        self.assertEqual(doc["visual_observation_coverage_pct"], 10.0)
        self.assertEqual(doc["phases"][-1]["component_outcomes"]["leader"], "UNKNOWN")

    def test_unverified_stage_is_unknown_even_if_json_claims_riders(self):
        doc = compare(verified_frame=False)
        self.assertEqual(doc["status"], "HOLD_NO_INDEPENDENTLY_COMPARABLE_PHASES")
        self.assertEqual(doc["visual_observation_coverage_pct"], 0)
        self.assertEqual(doc["comparison_coverage_pct"], 0)
        self.assertIsNone(doc["accuracy_on_comparable_components_pct"])

    def test_replay_scene_is_not_scored_or_double_counted(self):
        obs = [stage("GOAL", 161, scene="REPLAY")]
        doc = compare(obs)
        self.assertEqual(doc["comparison_coverage_pct"], 0)
        self.assertEqual(doc["phases"][-1]["status"], "UNKNOWN")

    def test_existing_admission_receipt_must_contain_all_scored_frames(self):
        obs = [stage("GOAL", 161)]
        permission = admitted(obs)
        permission["reviewed_scene_frames"].pop()
        permission["admission_sha256"] = digest({
            k: v for k, v in permission.items() if k != "admission_sha256"})
        with self.assertRaisesRegex(PhaseError, "PHASE_FRAME_NOT_IN_VIDEO_ADMISSION"):
            compare(obs, permission=permission)

    def test_original_video_and_result_identifiers_must_agree(self):
        obs = [stage("GOAL", 161)]
        a = admitted(obs)
        a["race_id"] = "203001151202"
        a["admission_sha256"] = digest({
            k: v for k, v in a.items() if k != "admission_sha256"})
        with self.assertRaisesRegex(PhaseError, "EXISTING_VIDEO_ADMISSION_REQUIRED"):
            compare(obs, permission=a)
        bad_result = result()
        bad_result["race_id"] = "203001151202"
        with self.assertRaisesRegex(PhaseError, "OFFICIAL_RESULT_SOURCE_REQUIRED"):
            compare(obs, official=bad_result, result_ok=True)

    def test_result_never_goes_into_pre_race_phase_inference(self):
        obs = [stage("GOAL", 161)]
        with self.assertRaisesRegex(PhaseError, "POST_CUTOFF_OFFICIAL_RESULT_REQUIRED"):
            compare(obs, official=result(
                published_at=(CUT - timedelta(seconds=1)).isoformat()),
                result_ok=True)
        doc = compare(obs, official=result(), result_ok=True)
        self.assertFalse(doc["source_outcome_used_as_pre_race_input"])
        self.assertFalse(doc["official_accuracy_or_roi_updated"])

    def test_video_goal_vs_official_result_conflict_is_hold(self):
        obs = [stage("GOAL", 161)]
        doc = compare(obs, official=result([1, 2, 7]),
                      result_ok=True, original=True)
        self.assertEqual(doc["status"], "HOLD_GOAL_VIDEO_OFFICIAL_RESULT_CONFLICT")
        self.assertFalse(doc["formal_evaluation_inputs_attested"])

    def test_research_only_when_chat_original_not_independently_attested(self):
        obs = [stage("GOAL", 161)]
        admitted_real = admitted(obs, synthetic=False)
        r = compare(obs, permission=admitted_real, original=False,
                    official=result(), result_ok=True)
        self.assertEqual(r["status"], "RESEARCH_SCORE_ONLY_NOT_FORMAL")
        self.assertFalse(r["formal_evaluation_inputs_attested"])
        self.assertFalse(r["model_parameters_updated"])

    def test_positive_attestors_prove_interface_not_live_video(self):
        # A simulated attestor handshake is still synthetic CI evidence.
        obs = [stage("GOAL", 161)]
        admitted_real = admitted(obs, synthetic=False)
        r = compare(obs, permission=admitted_real, original=True,
                    official=result(), result_ok=True)
        self.assertEqual(r["status"], "FORMAL_INPUT_ATTESTED_RESEARCH_SCORE")
        self.assertTrue(r["formal_evaluation_inputs_attested"])
        self.assertTrue(r["learning_candidate_only"])
        self.assertFalse(r["automatic_model_promotion"])

    def test_missing_rights_gate_causes_all_phases_unknown(self):
        obs = [stage("GOAL", 161)]
        a = admitted(obs, synthetic=False)
        out = score_six_phases(
            frozen(), a, obs, visual_verifier=lambda *args: True,
            rights_verifier=lambda *args: False,
            frozen_original_verifier=lambda *args: True,
            official_result=result(), official_result_verifier=lambda *args: True,
        )
        self.assertEqual(out["status"], "HOLD_NO_INDEPENDENTLY_COMPARABLE_PHASES")
        self.assertEqual(out["comparison_coverage_pct"], 0)
        self.assertFalse(out["formal_evaluation_inputs_attested"])

    def test_duplicate_frame_and_reverse_time_not_allowed(self):
        obs = all_stages()
        obs[1]["frame_sha256"][0] = obs[0]["frame_sha256"][0]
        a = admitted(obs)
        with self.assertRaisesRegex(PhaseError, "DUPLICATE_STAGE_FRAME"):
            compare(obs, permission=a)
        obs = [stage("GOAL", 161), stage("BELL", 39)]
        with self.assertRaisesRegex(PhaseError, "STAGES_NOT_IN_VIDEO_TIME_ORDER"):
            compare(obs)

    def test_all_unknown_projections_do_not_get_full_points(self):
        doc = copy.deepcopy(frozen())
        for k in doc["stage_predictions"]:
            doc["stage_predictions"][k] = {
                label: UNKNOWN for label in ("leader", "top3", "line_groups",
                                            "second_wheel", "attack")
            }
        doc["phase_forecast_sha256"] = digest({
            k: v for k, v in doc.items() if k != "phase_forecast_sha256"})
        result_doc = compare(frozen_doc=doc)
        self.assertEqual(result_doc["visual_observation_coverage_pct"], 100)
        self.assertEqual(result_doc["comparison_coverage_pct"], 0)
        self.assertIsNone(result_doc["accuracy_on_comparable_components_pct"])
        self.assertEqual(result_doc["status"], "HOLD_NO_INDEPENDENTLY_COMPARABLE_PHASES")


if __name__ == "__main__":
    unittest.main()
