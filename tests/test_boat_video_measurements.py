"""Synthetic geometry checks; these do not validate tracking on race footage."""
from copy import deepcopy
import math
import unittest


def engine(test):
    try:
        from race_ai.boat_video_measurements import measure_tracks
    except ImportError:
        test.fail("pure boat-video measurement engine is missing")
    return measure_tracks


def track(points, times=None, **overrides):
    times = times if times is not None else [i * 0.1 for i in range(len(points))]
    out = {"lane": 1, "identity_status": "COLOR_CANDIDATE", "samples": [
        {"t": t, "x": p[0], "y": p[1], "scene": 0, "valid": True, "frame_index": i}
        for i, (t, p) in enumerate(zip(times, points))]}
    out.update(overrides)
    return out


def measurements(test, tracks, **kwargs):
    return engine(test)(tracks, coordinate_space="REFERENCE_IMAGE_PX", **kwargs)


def phase(out, name, lane=0):
    return out["lanes"][lane]["phases"][name]


def metric(result, name):
    return next(m for m in result["metrics"] if m["name"] == name)


GATE = {"a": [1, -2], "b": [1, 2], "normal": [1, 0]}
CALIBRATION = {"validation_status": "CALIBRATION_PROVIDED_UNVERIFIED",
               "source_sha256": "a" * 64, "reference_frame_sha256": "b" * 64,
               "ground_plane": True, "world_units": "m", "training_anchor_count": 4,
               "independent_check_count": 2, "max_check_error_m": 0.1,
               "per_frame_checks": [{"scene": 0, "frame_index": i, "max_check_error_m": 0.1}
                                    for i in range(11)]}


class BoatVideoMeasurementTests(unittest.TestCase):
    def test_sampled_circle_reports_conditional_radius_and_media_time(self):
        # Chord length / heading change approaches radius; finite sampling is explicit.
        points = [(10 * math.cos(i * math.pi / 40), 10 * math.sin(i * math.pi / 40))
                  for i in range(21)]
        out = measurements(self, [track(points)], phase_windows={"1": {"turn": [0, 2]}})
        turn = phase(out, "turn")
        self.assertEqual(turn["status"], "MEASURED")
        self.assertEqual(turn["window_source"], "CONFIGURED")
        self.assertEqual(metric(turn, "window_duration")["value"], 2)
        self.assertAlmostEqual(metric(turn, "sampled_heading_change")["value"], 85.5, places=7)
        self.assertAlmostEqual(metric(turn, "equivalent_sampled_radius")["value"], 10.5236105, places=6)
        self.assertEqual(metric(turn, "equivalent_sampled_radius")["unit"], "px")
        self.assertIn("sampled", turn["measurement_scope"].lower())
        self.assertEqual(out["schema_version"], "RACE_AI_BOAT_VIDEO_MEASUREMENTS_V1")
        self.assertFalse(out["model_eligible"])
        self.assertEqual(out["validation_status"], "UNVALIDATED")
        self.assertEqual(out["time_basis"], "MEDIA_TIMELINE_SECONDS")

    def test_irregular_pts_give_interval_speed_trend_not_frame_rate_acceleration(self):
        # x = 2t + 3t², hence interval speed is exactly 2 + 6*midpoint.
        times = [0, 0.07, 0.2, 0.39, 0.6, 0.83, 1]
        item = track([(2 * t + 3 * t * t, 0) for t in times], times)
        out = measurements(self, [item], phase_windows={"1": {"exit": [0, 1]}})
        result = phase(out, "exit")
        self.assertEqual(result["status"], "MEASURED")
        self.assertAlmostEqual(metric(result, "sampled_speed_trend")["value"], 6, places=10)
        self.assertEqual(metric(result, "sampled_speed_trend")["unit"], "px/s^2")
        self.assertAlmostEqual(metric(result, "first_interval_speed")["value"], 2.21)
        self.assertAlmostEqual(metric(result, "last_interval_speed")["value"], 7.49)
        self.assertAlmostEqual(metric(result, "interval_speed_change")["value"], 5.28)
        self.assertLess(metric(result, "speed_trend_residual_rms")["value"], 1e-12)
        self.assertEqual(result["instantaneous_acceleration"], "NOT_ESTIMATED")

    def test_all_configured_phases_measure_and_runup_uses_gate(self):
        points = [(i * 0.1, 0) for i in range(11)]
        windows = {"1": {"turn": [0, 1], "exit": [0, 1],
                          "runup": [0, 1], "straight": [0, 1]}}
        out = measurements(self, [track(points)], phase_windows=windows, start_gate=GATE)
        self.assertEqual(phase(out, "turn")["status"], "MISSING")  # a line is not a turn
        for name in ("exit", "runup", "straight"):
            self.assertEqual(phase(out, name)["status"], "MEASURED", name)
        self.assertAlmostEqual(metric(phase(out, "straight"), "mean_interval_speed")["value"], 1)
        self.assertEqual(metric(phase(out, "straight"), "max_lateral_deviation")["value"], 0)
        self.assertEqual(phase(out, "runup")["gate_crossing_t"], 1)

    def test_configured_runup_cannot_invent_a_start_reference(self):
        out = measurements(self, [track([(i, 0) for i in range(6)])],
                           phase_windows={"1": {"runup": [0, 0.5]}})
        self.assertEqual(phase(out, "runup")["reason"], "START_REFERENCE_REQUIRED")
        self.assertEqual(phase(out, "runup")["metrics"], [])

    def test_auto_straight_does_not_label_pre_turn_samples_runup(self):
        out = measurements(self, [track([(i, 0) for i in range(20)])])
        self.assertEqual(phase(out, "straight")["status"], "MEASURED")
        self.assertEqual(phase(out, "turn")["status"], "MISSING")
        self.assertEqual(phase(out, "exit")["status"], "MISSING")
        self.assertEqual(phase(out, "runup")["reason"], "START_REFERENCE_REQUIRED")

    def test_auto_turn_and_following_exit_are_observed_candidates(self):
        arc = [(10 * math.cos(i * math.pi / 20), 10 * math.sin(i * math.pi / 20))
               for i in range(11)]
        points = arc + [(-i, 10) for i in range(1, 15)]
        out = measurements(self, [track(points)])
        turn, exit_phase = phase(out, "turn"), phase(out, "exit")
        self.assertEqual(turn["status"], "MEASURED")
        self.assertGreaterEqual(metric(turn, "sampled_heading_change")["value"], 45)
        self.assertEqual(turn["window_source"], "AUTOMATIC_CANDIDATE")
        self.assertEqual(exit_phase["status"], "MEASURED")
        self.assertGreaterEqual(exit_phase["t_start"], turn["t_end"])

    def test_long_gentle_arc_is_not_an_automatic_straight(self):
        points = [(100 * math.cos(math.radians(i)), 100 * math.sin(math.radians(i)))
                  for i in range(181)]
        result = phase(measurements(self, [track(points)]), "straight")
        self.assertEqual(result["status"], "MISSING")
        self.assertEqual(result["metrics"], [])

    def test_sustained_turn_detection_does_not_depend_on_degrees_per_sample(self):
        for step in (1, 2.5, 9):
            points = [(100 * math.cos(math.radians(i * step)),
                       100 * math.sin(math.radians(i * step)))
                      for i in range(int(90 / step) + 1)]
            result = phase(measurements(self, [track(points)]), "turn")
            self.assertEqual(result["status"], "MEASURED", step)
            self.assertGreaterEqual(metric(result, "sampled_heading_change")["value"], 45)

    def test_automatic_exit_requires_stable_heading_after_a_turn(self):
        points = [(10 * math.cos(i * math.pi / 20), 10 * math.sin(i * math.pi / 20))
                  for i in range(11)]
        # A broad bend with a direction reversal follows the initial turn.
        for offset in (0, -2, -4, -6, -8, -10, -8, -6, -4, -2, 0):
            theta = math.radians(180 + offset)
            points.append((points[-1][0] + math.cos(theta), points[-1][1] + math.sin(theta)))
        out = measurements(self, [track(points)])
        self.assertEqual(phase(out, "turn")["status"], "MEASURED")
        self.assertEqual(phase(out, "exit")["status"], "MISSING")
        self.assertEqual(phase(out, "exit")["reason"], "POST_TURN_HEADING_NOT_STABLE")
        self.assertEqual(phase(out, "exit")["metrics"], [])

    def test_sub_position_error_jitter_does_not_create_turn_exit_or_straight(self):
        points = [(0.1 * math.cos(math.radians(i * 15)),
                   0.1 * math.sin(math.radians(i * 15))) for i in range(9)]
        points += [(-0.05 - 0.01 * i, 0.0866) for i in range(1, 11)]
        item = track(points)
        for row in item["samples"]:
            row["position_error"] = 1
        out = measurements(self, [item])
        for name in ("turn", "exit", "straight"):
            self.assertEqual(phase(out, name)["status"], "MISSING", name)
            self.assertEqual(phase(out, name)["metrics"], [])
        self.assertEqual(phase(out, "turn")["reason"], "POSITION_DISPLACEMENT_UNRESOLVED")

    def test_resolved_straight_motion_does_not_make_an_unresolved_prior_turn_an_exit(self):
        points = [(0.1 * math.cos(math.radians(i * 15)),
                   0.1 * math.sin(math.radians(i * 15))) for i in range(9)]
        points += [(-0.05 - 10 * i, 0.0866) for i in range(1, 11)]
        item = track(points)
        for row in item["samples"]:
            row["position_error"] = 1
        out = measurements(self, [item])
        self.assertEqual(phase(out, "turn")["reason"], "POSITION_DISPLACEMENT_UNRESOLVED")
        self.assertEqual(phase(out, "exit")["reason"], "TURN_PHASE_NOT_RESOLVED")
        self.assertEqual(phase(out, "exit")["metrics"], [])

    def test_configured_rates_do_not_present_sub_error_displacements_as_resolved(self):
        item = track([(i * 0.01, 0) for i in range(11)])
        for row in item["samples"]:
            row["position_error"] = 1
        out = measurements(self, [item], phase_windows={"1": {"exit": [0, 1]}})
        self.assertEqual(phase(out, "exit")["reason"], "POSITION_DISPLACEMENT_UNRESOLVED")
        self.assertEqual(phase(out, "exit")["metrics"], [])

    def test_runup_requires_a_crossing_of_the_gate_segment_in_the_known_direction(self):
        for points in ([(i * 0.1, 5) for i in range(11)],
                       [(1 - i * 0.1, 0) for i in range(11)]):
            out = measurements(self, [track(points)], start_gate=GATE)
            self.assertEqual(phase(out, "runup")["reason"], "START_GATE_CROSSING_NOT_OBSERVED")
        out = measurements(self, [track([(i * 0.1, 0) for i in range(11)])], start_gate=GATE)
        self.assertEqual(phase(out, "runup")["status"], "MEASURED")
        self.assertLessEqual(phase(out, "runup")["t_end"], phase(out, "runup")["gate_crossing_t"])

    def test_stationary_and_empty_tracks_have_missing_measurements_not_fake_zero_rates(self):
        for item in (track([(2, 3)] * 8), track([])):
            out = measurements(self, [item], phase_windows={"1": {
                "turn": [0, 0.7], "exit": [0, 0.7], "straight": [0, 0.7]}})
            for result in out["lanes"][0]["phases"].values():
                self.assertEqual(result["status"], "MISSING")
                self.assertEqual(result["metrics"], [])

    def test_configured_windows_do_not_bridge_cuts_gaps_or_occlusions(self):
        base = track([(i, 0) for i in range(6)])
        cases = []
        cut = deepcopy(base)
        cut["samples"][3]["scene"] = 1
        cases.append((cut, "CAMERA_SCENE_CHANGE"))
        gap = deepcopy(base)
        for sample in gap["samples"][3:]:
            sample["t"] += 0.5
        cases.append((gap, "SAMPLE_GAP"))
        occluded = deepcopy(base)
        occluded["samples"][2]["valid"] = False
        cases.append((occluded, "OCCLUDED_OR_INVALID_SAMPLE"))
        for item, reason in cases:
            end = item["samples"][-1]["t"]
            result = phase(measurements(self, [item], phase_windows={"1": {"straight": [0, end]}}), "straight")
            self.assertEqual(result["reason"], reason)
            self.assertEqual(result["metrics"], [])

    def test_invalid_null_sample_is_retained_as_configured_window_break(self):
        item = track([(i * 0.1, 0) for i in range(11)])
        item["samples"][5].update(valid=False, x=None, y=None, position_error=None)
        out = measurements(self, [item], phase_windows={"1": {"straight": [0, 1]}})
        result = phase(out, "straight")
        self.assertEqual(result["status"], "MISSING")
        self.assertEqual(result["reason"], "OCCLUDED_OR_INVALID_SAMPLE")
        self.assertEqual(result["sample_count"], 11)
        self.assertEqual(result["metrics"], [])

    def test_auto_windows_do_not_bridge_a_null_coordinate_occlusion(self):
        item = track([(i * 0.1, 0) for i in range(11)])
        item["samples"][5].update(valid=False, x=None, y=None, position_error=None)
        straight = phase(measurements(self, [item]), "straight")
        self.assertEqual(straight["status"], "MEASURED")
        self.assertEqual(straight["sample_count"], 5)
        self.assertEqual(straight["t_start"], 0)
        self.assertAlmostEqual(straight["t_end"], 0.4)

    def test_null_occlusion_cannot_supply_an_unobserved_gate_crossing(self):
        item = track([(i * 0.1, 0) for i in range(11)])
        item["samples"][9].update(valid=False, x=None, y=None, position_error=None)
        out = measurements(self, [item], start_gate=GATE)
        self.assertEqual(phase(out, "runup")["reason"], "START_GATE_CROSSING_NOT_OBSERVED")

    def test_null_measurements_are_rejected_for_valid_samples(self):
        for key in ("x", "y", "position_error"):
            item = track([(i, 0) for i in range(6)])
            item["samples"][2][key] = None
            with self.assertRaises(ValueError, msg=key):
                measurements(self, [item])
        for key in ("t", "frame_index", "scene"):
            item = track([(i, 0) for i in range(6)])
            item["samples"][2].update(valid=False, x=None, y=None, position_error=None)
            item["samples"][2][key] = None
            with self.assertRaises(ValueError, msg=key):
                measurements(self, [item])
        for key in ("x", "y", "position_error"):
            item = track([(i, 0) for i in range(6)])
            item["samples"][2].update(valid=False, x=None, y=None, position_error=None)
            item["samples"][2][key] = float("nan")
            with self.assertRaises(ValueError, msg=key):
                measurements(self, [item])

    def test_auto_windows_stay_inside_one_contiguous_scene(self):
        item = track([(i, 0) for i in range(20)])
        for sample in item["samples"][10:]:
            sample["scene"] = 1
        straight = phase(measurements(self, [item]), "straight")
        self.assertEqual(straight["status"], "MEASURED")
        self.assertLessEqual(straight["t_end"] - straight["t_start"], 0.9 + 1e-12)
        self.assertEqual(straight["scene"], 0)

    def test_unresolved_identity_never_gets_labelled_verified_or_measured(self):
        item = track([(i, 0) for i in range(6)], identity_status="UNKNOWN")
        out = measurements(self, [item], phase_windows={"1": {"straight": [0, 0.5]}})
        self.assertEqual(out["lanes"][0]["identity_status"], "UNRESOLVED")
        for result in out["lanes"][0]["phases"].values():
            self.assertEqual(result["reason"], "IDENTITY_UNRESOLVED")
            self.assertEqual(result["metrics"], [])

    def test_metres_require_explicit_verified_calibration_and_keep_world_units(self):
        item = track([(i * 0.1, 0) for i in range(11)])
        for evidence in (None, {}, {"verified": True}, dict(CALIBRATION, ground_plane=False),
                         dict(CALIBRATION, independent_check_count=True),
                         dict(CALIBRATION, max_check_error_m=0.26),
                         dict(CALIBRATION, reference_frame_sha256="")):
            with self.assertRaises(ValueError):
                engine(self)([item], coordinate_space="WATER_PLANE_METRES", calibration_evidence=evidence)
        out = engine(self)([item], coordinate_space="WATER_PLANE_METRES", calibration_evidence=CALIBRATION,
                           phase_windows={"1": {"straight": [0, 1]}})
        self.assertEqual(metric(phase(out, "straight"), "mean_interval_speed")["unit"], "m/s")
        self.assertEqual(out["validation_status"], "UNVALIDATED")
        self.assertEqual(out["calibration_status"], "CONDITIONAL_ON_SUPPLIED_CALIBRATION")
        incomplete = dict(CALIBRATION, per_frame_checks=CALIBRATION["per_frame_checks"][:-1])
        incomplete_out = engine(self)([item], coordinate_space="WATER_PLANE_METRES",
                                      calibration_evidence=incomplete,
                                      phase_windows={"1": {"straight": [0, 1]}})
        self.assertEqual(phase(incomplete_out, "straight")["reason"], "CALIBRATION_FRAME_CHECK_MISSING")
        self.assertEqual(phase(incomplete_out, "straight")["metrics"], [])

    def test_position_error_is_reported_as_supplied_not_certified(self):
        item = track([(i * 0.1, 0) for i in range(11)])
        for sample in item["samples"]:
            sample["position_error"] = 0.01
        result = phase(measurements(self, [item], phase_windows={"1": {"exit": [0, 1]}}), "exit")
        self.assertAlmostEqual(metric(result, "max_supplied_interval_speed_error")["value"], 0.2)
        self.assertEqual(result["uncertainty_scope"], "SUPPLIED_POSITION_ERROR_ONLY_UNCERTIFIED")
        self.assertGreaterEqual(metric(result, "sampled_speed_trend_error_bound")["value"], 0)

    def test_partial_uncertainty_is_not_presented_as_a_complete_bound(self):
        item = track([(i, 0) for i in range(6)])
        item["samples"][0]["position_error"] = 0.1
        result = phase(measurements(self, [item], phase_windows={"1": {"exit": [0, 0.5]}}), "exit")
        self.assertEqual(result["uncertainty_scope"], "INCOMPLETE_POSITION_ERROR_NOT_BOUNDED")
        self.assertNotIn("sampled_speed_trend_error_bound", [m["name"] for m in result["metrics"]])

    def test_nonfinite_boolean_duplicate_or_unordered_samples_are_rejected(self):
        base = track([(i, 0) for i in range(6)])
        mutations = [("x", float("nan")), ("y", float("inf")), ("x", True),
                     ("t", True), ("t", -1), ("t", 0), ("frame_index", 0),
                     ("scene", True), ("valid", 1), ("position_error", -0.01)]
        for key, value in mutations:
            item = deepcopy(base)
            item["samples"][1][key] = value
            with self.assertRaises(ValueError, msg=(key, value)):
                measurements(self, [item])
        for kwargs in ({"max_gap_seconds": 0}, {"max_gap_seconds": True},
                       {"max_gap_seconds": float("inf")}):
            with self.assertRaises(ValueError):
                measurements(self, [base], **kwargs)
        for bad in ([base, base], [dict(base, lane=True)], [dict(base, lane=7)]):
            with self.assertRaises(ValueError):
                measurements(self, bad)

    def test_four_distinct_configured_windows_report_observed_geometry(self):
        arc = [(10 * math.cos(i * math.pi / 20), 10 * math.sin(i * math.pi / 20))
               for i in range(11)]
        points = arc + [(-i, 10) for i in range(1, 31)]
        gate = {"a": [-20, 8], "b": [-20, 12], "normal": [-1, 0]}
        out = measurements(self, [track(points)], start_gate=gate, phase_windows={"1": {
            "turn": [0, 1], "exit": [1.1, 1.8], "runup": [2, 3], "straight": [3.1, 4]}})
        for name in ("turn", "exit", "runup", "straight"):
            self.assertEqual(phase(out, name)["status"], "MEASURED", name)
            self.assertFalse(phase(out, name)["identity_validated"])
        self.assertAlmostEqual(metric(phase(out, "exit"), "sampled_speed_trend")["value"], 0)
        self.assertAlmostEqual(metric(phase(out, "straight"), "mean_interval_speed")["value"], 10)

    def test_calibration_cannot_understate_its_supplied_per_frame_maximum_error(self):
        evidence = deepcopy(CALIBRATION)
        evidence["per_frame_checks"][0]["max_check_error_m"] = 0.2
        with self.assertRaises(ValueError):
            engine(self)([track([(i, 0) for i in range(11)])],
                         coordinate_space="WATER_PLANE_METRES", calibration_evidence=evidence)

    def test_extreme_integer_coordinates_are_rejected_as_nonfinite_without_overflow_error(self):
        item = track([(0, 0), (1, 0), (2, 0)])
        item["samples"][1]["x"] = 10 ** 1000
        with self.assertRaises(ValueError):
            measurements(self, [item])

    def test_phase_windows_and_gate_are_validated_without_interpolation(self):
        item = track([(i, 0) for i in range(6)])
        for windows in ({"1": {"straight": [0.5, 0]}}, {"1": {"straigth": [0, 0.5]}},
                        {"1": {"straight": [0, float("inf")]}}):
            with self.assertRaises(ValueError):
                measurements(self, [item], phase_windows=windows)
        for gate in ({"a": [1, 0], "b": [1, 0], "normal": [1, 0]},
                     {"a": [1, 0], "b": [1, 1], "normal": [0, 1]}):
            with self.assertRaises(ValueError):
                measurements(self, [item], start_gate=gate)
        result = phase(measurements(self, [item], phase_windows={"1": {"straight": [0, 2]}}), "straight")
        self.assertEqual(result["reason"], "INSUFFICIENT_WINDOW_COVERAGE")


if __name__ == "__main__":
    unittest.main()
