"""Fictional evidence exercises research admission, never field validation."""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import importlib
from pathlib import Path
import tempfile
import unittest

from race_ai.actions_contract import digest
from race_ai.boat_video_evaluation import analyze_video
from race_ai.boat_video_measurements import measure_tracks
from tests.test_boat_video_evaluation import job, reseal, roster, RACE, CUTOFF, START, END


AS_OF = "2030-04-01T11:55:00+09:00"
CREATED = "2030-04-01T11:54:00+09:00"
FEATURES = ("turn_sampled_radius", "exit_speed_trend", "runup_speed_trend", "straight_mean_speed")
PHASES = ("turn", "exit", "runup", "straight")


def module(test):
    try:
        return importlib.import_module("race_ai.boat_video_model_context")
    except ModuleNotFoundError:
        test.fail("existing-model video research admission interface is missing")


def seal_evidence(value):
    value = deepcopy(value)
    value.pop("evidence_sha256", None)
    value["evidence_sha256"] = digest(value)
    return value


def fixture():
    """Use actual measurement/report code with injected fictional decoded points."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fictional.bin"
        path.write_bytes(b"fictional decoder input; not actual exhibition footage")
        media_sha = sha256(path.read_bytes()).hexdigest()
        tracks = []
        for lane in range(1, 7):
            scale = float(lane)
            points = [(0, 0), (1, 0), (2, 1), (2, 2), (1, 3),
                      (0, 0), (1, 0), (4, 0), (9, 0), (16, 0),
                      (-16, 0), (-9, 0), (-4, 0), (-1, 0), (1, 0),
                      (0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]
            samples = [{"t": i / 10, "frame_index": i, "scene": 0, "valid": True,
                        "x": x * scale, "y": y * scale + lane * 10., "position_error": .0001}
                       for i, (x, y) in enumerate(points)]
            tracks.append({"lane": lane, "identity_status": "NUMBER_COLOR_AGREEMENT", "samples": samples})
        tracking = {"schema_version": "RACE_AI_BOAT_VIDEO_TRACKS_V1", "media_sha256": media_sha,
                    "width": 640, "height": 480, "duration_seconds": 2., "timeline_source": "MEDIA_PTS",
                    "coordinate_space": "REFERENCE_IMAGE_PX", "model_eligible": False,
                    "validation_status": "UNVALIDATED", "tracks": tracks, "quality": {"flags": []}}
        specification = job(media_sha)
        specification["phase_windows"] = {str(lane): {"turn": [0., .4], "exit": [.5, .9],
            "runup": [1., 1.3], "straight": [1.5, 1.9]} for lane in range(1, 7)}
        specification["start_gate"] = {"a": [0., 0.], "b": [0., 100.], "normal": [1., 0.]}
        clock = iter(datetime.fromisoformat(v) for v in (START, END))
        report = analyze_video(path, specification, clock=lambda: next(clock),
                               extractor=lambda path, *, options=None: deepcopy(tracking))
    identities = [{"lane": lane, "registration_number": str(4200 + lane), "number": lane,
                   "reviewer_kind": "AGENT", "reviewer_id": "fictional-agent",
                   "method": "INDEPENDENT_HULL_NUMBER_READ", "track_sha256": digest(tracks[lane - 1]),
                   "frames": [{"frame_index": i, "frame_sha256": sha256(str(i).encode()).hexdigest()}
                              for i in (0, 5, 10, 15)]} for lane in range(1, 7)]
    comparisons = {}
    for phase, start, end in (("turn", 0, 4), ("exit", 5, 9), ("runup", 10, 13), ("straight", 15, 19)):
        comparisons[phase] = {"comparison_id": "fictional-common-" + phase, "scene": 0,
            "frame_indices": list(range(start, end + 1)), "camera_evidence_sha256": "a" * 64,
            "calibration_evidence_sha256": "b" * 64, "clock_evidence_sha256": "c" * 64,
            "uncertainty_by_lane": {str(n): .01 for n in range(1, 7)}}
    evidence = seal_evidence({"schema_version": "RACE_AI_BOAT_VIDEO_COMPARISON_EVIDENCE_V1",
        "report_sha256": report["report_sha256"], "media_sha256": media_sha, "race_id": RACE,
        "cutoff_at": CUTOFF, "roster": roster(), "created_at": CREATED,
        "identities": identities, "comparisons": comparisons, "heldout_evidence_sha256": None})
    return report, evidence


class VideoModelContextTests(unittest.TestCase):
    def prepare(self, report, evidence, **overrides):
        arguments = dict(race_id=RACE, cutoff_at=CUTOFF, roster=roster(), as_of=AS_OF)
        arguments.update(overrides)
        return module(self).prepare_video_context(report, evidence, **arguments)

    def test_raw_typed_cells_are_comparable_without_becoming_strength_or_human_validation(self):
        report, evidence = fixture()
        before = deepcopy((report, evidence))
        out = self.prepare(report, evidence)
        self.assertTrue(out["eligible_for_research"])
        self.assertEqual(len(out["participants"]), 6)
        straight = out["participants"][0]["feature_cells"]["straight_mean_speed"]
        self.assertAlmostEqual(straight["value"], 10.)
        self.assertEqual(straight["unit"], "px/s")
        self.assertEqual(straight["comparison_id"], "fictional-common-straight")
        self.assertNotIn("normalized_value", straight)
        self.assertEqual(set(out["default_coefficients"].values()), {0.})
        self.assertEqual(out["learned_direction"], "UNTRAINED")
        self.assertEqual(out["raw_report_validation_status"], "UNVALIDATED")
        self.assertEqual(out.get("analysis_completed_at"), END)
        self.assertEqual(out.get("evidence_created_at"), CREATED)
        self.assertEqual(out.get("source_captured_at"), report["source"]["captured_at"])
        self.assertEqual(out.get("media_duration_seconds"), 2.)
        self.assertFalse(out["prediction_eligible"])
        self.assertFalse(out["independent_human_heldout_verified"])
        self.assertIn("INDEPENDENT_HUMAN_HELDOUT_VALIDATION_MISSING", out["validation_gaps"])
        self.assertEqual(out["identity_reviewer_kinds"], ["AGENT"])
        self.assertEqual((report, evidence), before)

    def test_missing_number_evidence_yields_24_explicit_missing_cells(self):
        report, _ = fixture()
        out = self.prepare(report, None)
        self.assertFalse(out["eligible_for_research"])
        for participant in out["participants"]:
            self.assertEqual(set(participant["feature_cells"]), set(FEATURES))
            for cell in participant["feature_cells"].values():
                self.assertIsNone(cell["value"])
                self.assertEqual(cell["missing_reason"], "INDEPENDENT_NUMBER_EVIDENCE_MISSING")

    def test_seal_or_media_or_target_identity_mismatch_is_rejected(self):
        report, evidence = fixture()
        cases = []
        bad = deepcopy(report); bad["analysis_completed_at"] = AS_OF; cases.append((bad, evidence, {}))
        for key, value in (("media_sha256", "f" * 64), ("report_sha256", "f" * 64),
                           ("race_id", "20300401-02-01")):
            bad = deepcopy(evidence); bad[key] = value; cases.append((report, seal_evidence(bad), {}))
        cases.append((report, evidence, {"cutoff_at": "2030-04-01T12:01:00+09:00"}))
        bad_roster = roster(); bad_roster[0]["registration_number"] = "9999"
        cases.append((report, evidence, {"roster": bad_roster}))
        for raw, proof, target in cases:
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.prepare(raw, proof, **target)

    def test_all_six_number_reads_and_bound_tracks_are_required(self):
        report, evidence = fixture()
        for mutate in (lambda x: x["identities"].pop(),
                       lambda x: x["identities"][0].update(number=2),
                       lambda x: x["identities"][0].update(method="COLOR_ONLY"),
                       lambda x: x["identities"][0].update(track_sha256="f" * 64)):
            bad = deepcopy(evidence); mutate(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.prepare(report, seal_evidence(bad))

    def test_report_metric_reseal_cannot_replace_measurement_math(self):
        report, evidence = fixture()
        bad = deepcopy(report)
        metric = next(m for m in bad["measurements"]["lanes"][0]["phases"]["straight"]["metrics"]
                      if m["name"] == "mean_interval_speed")
        metric["value"] = 1000.
        bad = reseal(bad)
        evidence["report_sha256"] = bad["report_sha256"]
        with self.assertRaises(ValueError):
            self.prepare(bad, seal_evidence(evidence))

    def test_comparison_needs_common_frames_and_scene_and_number_observation_in_each_phase(self):
        report, evidence = fixture()
        for mutate in (lambda x: x["comparisons"]["straight"].update(scene=1),
                       lambda x: x["comparisons"]["straight"].update(frame_indices=[15, 16, 17]),
                       lambda x: x["identities"][5]["frames"].pop()):
            bad = deepcopy(evidence); mutate(bad)
            out = self.prepare(report, seal_evidence(bad))
            self.assertTrue(out["eligible_for_research"])
            for participant in out["participants"]:
                cell = participant["feature_cells"]["straight_mean_speed"]
                self.assertIsNone(cell["value"])
                self.assertIn(cell["missing_reason"], {"COMMON_FRAME_CONTEXT_MISMATCH", "PHASE_NUMBER_EVIDENCE_MISSING",
                                                       "NON_COMMON_PHASE_WINDOW"})

    def test_missing_calibration_or_clock_is_explicit_without_identity_transform_fallback(self):
        report, evidence = fixture()
        for field, reason in (("camera_evidence_sha256", "CAMERA_COMPENSATION_UNVERIFIED"),
                              ("calibration_evidence_sha256", "COMPARISON_CALIBRATION_UNVERIFIED"),
                              ("clock_evidence_sha256", "COMMON_CLOCK_UNVERIFIED")):
            bad = deepcopy(evidence); bad["comparisons"]["straight"][field] = None
            out = self.prepare(report, seal_evidence(bad))
            self.assertEqual(out["participants"][0]["feature_cells"]["straight_mean_speed"]["missing_reason"], reason)

    def test_trend_uncertainty_exceeding_signal_is_missing_not_zero_or_boost(self):
        report, evidence = fixture()
        for phase, feature in (("exit", "exit_speed_trend"), ("runup", "runup_speed_trend")):
            bad = deepcopy(evidence)
            bad["comparisons"][phase]["uncertainty_by_lane"] = {str(n): 100000. for n in range(1, 7)}
            out = self.prepare(report, seal_evidence(bad))
            for participant in out["participants"]:
                cell = participant["feature_cells"][feature]
                self.assertIsNone(cell["value"])
                self.assertEqual(cell["missing_reason"], "MEASUREMENT_UNCERTAINTY_EXCEEDS_SIGNAL")

    def test_late_or_future_or_synthetic_evidence_never_becomes_live_research_input(self):
        report, evidence = fixture()
        out = self.prepare(report, evidence, as_of=CUTOFF)
        self.assertFalse(out["eligible_for_research"])
        self.assertIn("POST_CUTOFF_ONLY", out["missing_reasons"])
        bad = deepcopy(evidence); bad["created_at"] = "2030-04-01T11:59:00+09:00"
        out = self.prepare(report, seal_evidence(bad))
        self.assertFalse(out["eligible_for_research"])
        self.assertIn("EVIDENCE_NOT_AVAILABLE_AS_OF", out["missing_reasons"])
        bad_report = deepcopy(report)
        bad_report["source"].update(kind="SYNTHETIC_TEST", identity_status="SYNTHETIC")
        bad_report["dataset_status"] = "SYNTHETIC_ONLY"
        bad_report = reseal(bad_report)
        bad = deepcopy(evidence); bad["report_sha256"] = bad_report["report_sha256"]
        out = self.prepare(bad_report, seal_evidence(bad))
        self.assertFalse(out["eligible_for_research"])
        self.assertIn("SYNTHETIC_ONLY", out["missing_reasons"])

    def test_human_enum_or_heldout_reference_does_not_authenticate_a_human(self):
        report, evidence = fixture()
        for row in evidence["identities"]:
            row.update(reviewer_kind="HUMAN_MANUAL", reviewer_id="fictional-person")
        evidence["heldout_evidence_sha256"] = "d" * 64
        out = self.prepare(report, seal_evidence(evidence))
        self.assertFalse(out["independent_human_heldout_verified"])
        self.assertEqual(out["heldout_evidence_status"], "REFERENCE_SUPPLIED_NOT_AUTHENTICATED")
        self.assertIn("INDEPENDENT_HUMAN_HELDOUT_AUTHENTICATION_MISSING", out["validation_gaps"])
        self.assertEqual(out["identity_reviewer_kinds"], ["HUMAN_MANUAL"])

    def validate(self, context, **overrides):
        engine = module(self)
        self.assertTrue(hasattr(engine, "validate_video_context"), "strict sealed context reader is missing")
        arguments = dict(race_id=RACE, cutoff_at=CUTOFF, roster=roster(), as_of=AS_OF)
        arguments.update(overrides)
        return engine.validate_video_context(context, **arguments)

    def test_sealed_context_reader_checks_target_and_returns_detached_unchanged_cells(self):
        report, evidence = fixture()
        context = self.prepare(report, evidence)
        restored = self.validate(context)
        self.assertEqual(restored, context)
        restored["participants"][0]["feature_cells"]["straight_mean_speed"]["value"] = 999.
        self.assertAlmostEqual(context["participants"][0]["feature_cells"]["straight_mean_speed"]["value"], 10.)
        for arguments in ({"race_id": "20300401-02-01"},
                          {"cutoff_at": "2030-04-01T12:01:00+09:00"},
                          {"as_of": CREATED}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.validate(context, **arguments)

    def test_resealed_context_cannot_promote_units_signs_metadata_or_comparison_membership(self):
        report, evidence = fixture()
        context = self.prepare(report, evidence)
        mutations = (
            lambda x: x.update(raw_report_validation_status="VALIDATED"),
            lambda x: x.update(prediction_eligible=True),
            lambda x: x.update(independent_human_heldout_verified=True),
            lambda x: x.update(default_coefficients=dict.fromkeys(FEATURES, 1.)),
            lambda x: x["participants"][0]["feature_cells"]["straight_mean_speed"].update(unit="m/s"),
            lambda x: x["participants"][0]["feature_cells"]["straight_mean_speed"].update(comparison_id="foreign"),
            lambda x: x["participants"][0]["feature_cells"]["straight_mean_speed"].update(value=True),
            lambda x: x["participants"][0]["feature_cells"]["straight_mean_speed"].update(strength=10.),
            lambda x: x.update(analysis_completed_at="2030-04-01T11:59:00+09:00"),
            lambda x: x.update(evidence_created_at="2030-04-01T11:59:00+09:00"),
        )
        for index, mutate in enumerate(mutations):
            bad = deepcopy(context); mutate(bad); bad.pop("context_sha256")
            bad["context_sha256"] = digest(bad)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.validate(bad)

    def test_context_reader_rejects_negative_speed_radius_and_previous_day_source(self):
        report, evidence = fixture()
        context = self.prepare(report, evidence)
        for feature in ("turn_sampled_radius", "straight_mean_speed"):
            bad = deepcopy(context)
            bad["participants"][0]["feature_cells"][feature]["value"] = -100.
            bad.pop("context_sha256"); bad["context_sha256"] = digest(bad)
            with self.subTest(feature=feature), self.assertRaises(ValueError):
                self.validate(bad)
        bad = deepcopy(context)
        bad["source_captured_at"] = "2030-03-31T11:40:00+09:00"
        bad.pop("context_sha256"); bad["context_sha256"] = digest(bad)
        with self.assertRaises(ValueError):
            self.validate(bad)

    def test_reader_rejects_resealed_phase_windows_outside_media_or_different_between_lanes(self):
        report, evidence = fixture()
        context = self.prepare(report, evidence)
        for interval in ((99., 100.), (1.6, 1.9)):
            bad = deepcopy(context)
            bad["participants"][0]["feature_cells"]["straight_mean_speed"].update(t_start=interval[0], t_end=interval[1])
            bad.pop("context_sha256"); bad["context_sha256"] = digest(bad)
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                self.validate(bad)

    def test_preparation_records_common_source_pts_and_refuses_different_full_phase_windows(self):
        report, evidence = fixture()
        context = self.prepare(report, evidence)
        common = context["comparisons"]["straight"]
        self.assertEqual(common.get("source_pts_seconds"), [1.5, 1.6, 1.7, 1.8, 1.9])
        self.assertEqual((common.get("t_start"), common.get("t_end")), (1.5, 1.9))
        bad = deepcopy(report)
        bad["analysis_parameters"]["phase_windows"]["1"]["straight"] = [1.6, 1.9]
        parameters = bad["analysis_parameters"]
        bad["measurements"] = measure_tracks(bad["tracking"]["tracks"], coordinate_space="REFERENCE_IMAGE_PX",
            phase_windows=parameters["phase_windows"], start_gate=parameters["start_gate"])
        bad = reseal(bad)
        evidence["report_sha256"] = bad["report_sha256"]
        out = self.prepare(bad, seal_evidence(evidence))
        for participant in out["participants"]:
            cell = participant["feature_cells"]["straight_mean_speed"]
            self.assertIsNone(cell["value"])
            self.assertEqual(cell["missing_reason"], "NON_COMMON_PHASE_WINDOW")

    def test_number_evidence_binds_available_decoded_frame_hashes_without_promoting_report(self):
        report, evidence = fixture()
        for track in report["tracking"]["tracks"]:
            for sample in track["samples"]:
                sample["frame_sha256"] = sha256(("decoded-" + str(sample["frame_index"])).encode()).hexdigest()
        report = reseal(report)
        evidence["report_sha256"] = report["report_sha256"]
        for identity, track in zip(evidence["identities"], report["tracking"]["tracks"]):
            identity["track_sha256"] = digest(track)
            for frame in identity["frames"]:
                frame["frame_sha256"] = sha256(("decoded-" + str(frame["frame_index"])).encode()).hexdigest()
        out = self.prepare(report, seal_evidence(evidence))
        self.assertTrue(out["eligible_for_research"])
        self.assertEqual(out["raw_report_validation_status"], "UNVALIDATED")
        self.assertFalse(out["independent_human_heldout_verified"])
        for actual_sha in ("f" * 64, "malformed-frame-digest"):
            bad = deepcopy(report)
            bad["tracking"]["tracks"][0]["samples"][0]["frame_sha256"] = actual_sha
            bad = reseal(bad)
            proof = deepcopy(evidence)
            proof["report_sha256"] = bad["report_sha256"]
            proof["identities"][0]["track_sha256"] = digest(bad["tracking"]["tracks"][0])
            with self.subTest(actual_sha=actual_sha), self.assertRaises(ValueError):
                self.prepare(bad, seal_evidence(proof))


if __name__ == "__main__":
    unittest.main()
