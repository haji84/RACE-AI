"""Invented rider/video fixtures; these tests are not real accuracy evidence."""
from __future__ import annotations

from dataclasses import asdict, replace
import importlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


def module(name):
    try:
        return importlib.import_module("research.chatgpt_dt_r1." + name)
    except ModuleNotFoundError as exc:
        if exc.name != "research.chatgpt_dt_r1." + name:
            raise
        return None


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.o = module("observations")
        self.assertIsNotNone(self.o, "The observation processing module is not implemented")

    def source(self, kind="reviewed_video", available="2026-01-02T12:00:00Z"):
        return self.o.Provenance(kind=kind, source_url="https://example.test/synthetic-video",
            source_sha256="a" * 64, retrieved_at="2026-01-02T10:00:00Z",
            available_at=available, reviewer_id="synthetic-reviewer" if kind == "reviewed_video" else None,
            reviewed_at="2026-01-02T11:00:00Z" if kind == "reviewed_video" else None)

    def config(self):
        return self.o.VideoTimingConfig(fps=25.0, timebase_verified=True,
            timebase_id="synthetic-continuous-clock", playback_rate=1.0, max_gap_seconds=.3)

    def pair(self, center=10.0, **kw):
        defaults = dict(rider_id="invented-rider", track_id="synthetic-track", camera_id="cam-a",
                        shot_id="shot-1", identity_confidence=.98, point_kind="front_wheel_contact")
        defaults.update(kw)
        return [self.o.TrackSample(t_seconds=center-.1, x=-1, y=0, **defaults),
                self.o.TrackSample(t_seconds=center+.1, x=1, y=0, **defaults)]

    def gate(self, role="FINAL_HOME", **kw):
        args = dict(gate_id=role, role=role, line_start=(0, 1), line_end=(0, -1),
                    camera_id="cam-a", shot_id="shot-1", physical_line_id=role,
                    calibration_id="synthetic-line-review", lap_index=None)
        args.update(kw)
        return self.o.Gate(**args)

    def observation(self, race="synthetic-old-1", event="2026-01-01T10:00:00Z",
                    full=24., kind="official_record", available="2026-01-02T12:00:00Z"):
        return self.o.RiderTimingObservation(observation_id=race+kind, race_id=race,
            rider_id="invented-rider", venue_id="99", event_at=event,
            provenance=self.source(kind, available), timings={"full_last_lap_seconds":full,
                "agari_half_seconds":11.4}, uncertainties={}, identity_confidence=1.)

    def test_interpolates_gate_time_and_retains_conservative_uncertainty(self):
        result = self.o.extract_crossings(self.pair(), [self.gate()], self.config())
        self.assertEqual(len(result.crossings), 1)
        crossing = result.crossings[0]
        self.assertAlmostEqual(crossing.t_seconds, 10.)
        self.assertGreaterEqual(crossing.uncertainty_seconds, .12 - 1e-10)
        self.assertEqual(crossing.rider_id, "invented-rider")
        self.assertAlmostEqual(crossing.identity_confidence, .98)

    def test_refuses_cross_cut_occlusion_low_identity_unverified_clock_and_playback(self):
        variants = [([self.pair()[0], replace(self.pair()[1], shot_id="shot-2")], self.config()),
            ([self.pair()[0], replace(self.pair()[1], occluded=True)], self.config()),
            (self.pair(identity_confidence=.2), self.config()),
            (self.pair(), replace(self.config(), timebase_verified=False)),
            (self.pair(), replace(self.config(), playback_rate=.5)),
            ([self.pair()[0], replace(self.pair()[1], t_seconds=12.)], self.config())]
        for samples, config in variants:
            with self.subTest(samples=samples, config=config):
                result = self.o.extract_crossings(samples, [self.gate()], config)
                self.assertEqual(result.crossings, [])
                self.assertTrue(result.issues)

    def test_finite_gate_and_direction_do_not_count_extension_or_reverse_crossings(self):
        for samples in ([replace(s, y=5) for s in self.pair()], list(reversed(self.pair()))):
            if samples[0].t_seconds > samples[1].t_seconds:
                samples = [replace(samples[0], t_seconds=9.9), replace(samples[1], t_seconds=10.1)]
            self.assertEqual(self.o.extract_crossings(samples, [self.gate()], self.config()).crossings, [])

    def test_own_lap_start_is_required_and_agari_is_never_doubled(self):
        times = {"LAP_START":10., "FINAL_HOME":11., "FINAL_BACK":22.,
                 "FOURTH_CORNER":28., "AGARI_START":21.5, "GOAL":34.}
        crossings = []
        for role, at in times.items():
            kw = {"time_window":(at-.2, at+.2)}
            if role in {"LAP_START", "GOAL"}:
                kw.update(physical_line_id="finish", lap_index=0 if role == "LAP_START" else 1)
            if role == "AGARI_START":
                kw["remaining_laps"] = .5
            crossings += self.o.extract_crossings(self.pair(at), [self.gate(role, **kw)], self.config()).crossings
        row = self.o.build_lap_observation(crossings, observation_id="synthetic-video-1", race_id="synthetic-old-1",
            rider_id="invented-rider", venue_id="99", event_at="2026-01-01T10:00:00Z", provenance=self.source())
        self.assertEqual(row.timings, {"full_last_lap_seconds":24., "home_back_seconds":11.,
            "back_fourth_seconds":6., "fourth_goal_seconds":6., "agari_half_seconds":12.5})
        incomplete = self.o.build_lap_observation([c for c in crossings if c.role != "LAP_START"],
            observation_id="synthetic-video-2", race_id="synthetic-old-1", rider_id="invented-rider", venue_id="99",
            event_at="2026-01-01T10:00:00Z", provenance=self.source())
        self.assertIsNone(incomplete.timings["full_last_lap_seconds"])
        self.assertEqual(incomplete.timings["agari_half_seconds"], 12.5)
        wrong_rider = [replace(c, rider_id="another-invented-rider") if c.role == "LAP_START" else c for c in crossings]
        no_lap = self.o.build_lap_observation(wrong_rider, observation_id="synthetic-video-3", race_id="synthetic-old-1",
            rider_id="invented-rider", venue_id="99", event_at="2026-01-01T10:00:00Z", provenance=self.source())
        self.assertIsNone(no_lap.timings["full_last_lap_seconds"])

    def test_video_lap_cannot_be_relabelled_official_and_uncertain_intervals_stay_null(self):
        start = self.o.extract_crossings(self.pair(10.),
            [self.gate("LAP_START",physical_line_id="finish",lap_index=0)],self.config()).crossings[0]
        goal = self.o.extract_crossings(self.pair(10.05),
            [self.gate("GOAL",physical_line_id="finish",lap_index=1)],self.config()).crossings[0]
        metadata = dict(observation_id="short-uncertain",race_id="synthetic-old-1",rider_id="invented-rider",
                        venue_id="99",event_at="2026-01-01T10:00:00Z")
        with self.assertRaises(ValueError):
            self.o.build_lap_observation([start,goal],provenance=self.source("official_record"),**metadata)
        row = self.o.build_lap_observation([start,goal],provenance=self.source(),**metadata)
        self.assertIsNone(row.timings["full_last_lap_seconds"])
        with self.assertRaises(ValueError):
            replace(start,t_seconds=float("nan"))
        with self.assertRaises(ValueError):
            replace(self.config(),timebase_verified="true")

    def test_metre_speed_requires_valid_local_plane_and_screen_motion_is_labelled(self):
        samples = self.pair()
        uncalibrated = self.o.motion_features(samples, self.config())
        self.assertIsNone(uncalibrated["measured_speed_mean_m_s"])
        self.assertAlmostEqual(uncalibrated["screen_speed_mean_px_s"], 10.)
        calibration = self.o.LocalPlaneCalibration(calibration_id="synthetic-local-plane",
            camera_id="cam-a", shot_id="shot-1", homography=((2,0,0),(0,2,0),(0,0,1)),
            valid_polygon=((-2,-2),(2,-2),(2,2),(-2,2)), max_span_m=10.,
            position_error_m=.02, source=self.source("user_observation"))
        calibrated = self.o.motion_features(samples, self.config(), calibration)
        self.assertAlmostEqual(calibrated["measured_speed_mean_m_s"], 20.)
        self.assertGreater(calibrated["measured_speed_uncertainty_m_s"], 0.)
        outside = self.o.motion_features([replace(s, y=3) for s in samples], self.config(), calibration)
        self.assertIsNone(outside["measured_speed_mean_m_s"])
        with self.assertRaises(ValueError):
            replace(calibration, scope="whole_bank_flat_homography")

    def test_local_speed_acceleration_uses_contiguous_frames_and_rejects_singular_calibration(self):
        samples = [replace(self.pair()[0],t_seconds=10.,x=0.),
                   replace(self.pair()[0],t_seconds=10.1,x=1.),
                   replace(self.pair()[0],t_seconds=10.2,x=3.)]
        calibration = self.o.LocalPlaneCalibration(calibration_id="synthetic-local-plane",
            camera_id="cam-a",shot_id="shot-1",homography=((1,0,0),(0,1,0),(0,0,1)),
            valid_polygon=((-4,-4),(4,-4),(4,4),(-4,4)),max_span_m=12.,position_error_m=.01,
            source=self.source("user_observation"))
        result = self.o.motion_features(samples,self.config(),calibration)
        self.assertIn("measured_acceleration_mean_m_s2",result)
        self.assertAlmostEqual(result["measured_acceleration_mean_m_s2"],100.)
        self.assertAlmostEqual(result["screen_acceleration_mean_px_s2"],100.)
        broken = self.o.motion_features([samples[0],replace(samples[1],occluded=True),samples[2]],self.config(),calibration)
        self.assertIsNone(broken["measured_acceleration_mean_m_s2"])
        with self.assertRaises(ValueError):
            replace(calibration,homography=((0,0,0),(0,0,0),(0,0,1)))
        with self.assertRaises(ValueError):
            replace(calibration,valid_polygon=((0,0),(1,1),(2,2)))
        with self.assertRaises(ValueError):
            replace(calibration,source=None)

    def test_timing_book_excludes_target_future_and_late_sources(self):
        book = self.o.TimingBook([self.observation(), self.observation("synthetic-old-2", "2026-01-03T10:00:00Z", 26., available="2026-01-03T12:00:00Z"),
            self.observation("synthetic-late", "2026-01-04T10:00:00Z", 10., available="2026-01-06T12:00:00Z"),
            self.observation("synthetic-target", "2026-01-05T10:00:00Z", 8., available="2026-01-05T12:00:00Z")])
        f = book.features("invented-rider", "99", "2026-01-05T10:00:00Z", "2026-01-05T09:00:00Z")
        self.assertEqual(f["full_last_lap_seconds_count"], 2)
        self.assertEqual(f["full_last_lap_seconds_min"], 24.)
        self.assertEqual(f["full_last_lap_seconds_mean"], 25.)
        self.assertEqual(f["full_last_lap_seconds_recent"], 26.)
        self.assertEqual(f["full_last_lap_seconds_variance"], 1.)
        self.assertEqual(f["source_official_record_count"], 2)
        short = book.features("invented-rider", "99", "2026-01-05T10:00:00Z", "2026-01-05T09:00:00Z", window_days=3)
        self.assertEqual(short["full_last_lap_seconds_count"], 1)

    def test_duplicate_race_measurements_do_not_inflate_counts_or_mix_estimates(self):
        book = self.o.TimingBook([self.observation(), self.observation(kind="reviewed_video", full=23.),
                                  self.observation(kind="ai_estimate", full=15.)])
        f = book.features("invented-rider", "99", "2026-01-05T10:00:00Z", "2026-01-05T09:00:00Z")
        self.assertEqual(f["full_last_lap_seconds_count"], 1)
        self.assertEqual(f["full_last_lap_seconds_mean"], 24.)
        self.assertEqual(f["source_ai_estimate_count"], 1)
        self.assertEqual(f["estimated_full_last_lap_seconds_mean"], 15.)

    def test_recency_sorts_actual_instants_with_different_timezones(self):
        earlier = self.observation("earlier", "2026-01-02T10:00:00+09:00", 24.)
        later = self.observation("later", "2026-01-02T02:00:00Z", 26.)
        f = self.o.TimingBook([earlier,later]).features("invented-rider","99","2026-01-05T10:00:00Z","2026-01-05T09:00:00Z")
        self.assertEqual(f["full_last_lap_seconds_recent"],26.)

    def test_missing_values_stay_null_and_reviewed_source_cannot_be_self_labelled(self):
        empty = self.o.TimingBook([]).features("missing", "99", "2026-01-05T10:00:00Z", "2026-01-05T09:00:00Z")
        self.assertEqual(empty["agari_half_seconds_count"], 0)
        self.assertIsNone(empty["agari_half_seconds_mean"])
        with self.assertRaises(ValueError):
            replace(self.source(), reviewer_id=None)
        with self.assertRaises(ValueError):
            replace(self.observation(), timings={"full_last_lap_seconds":float("nan")})

    def test_retrospective_day_only_records_are_explicit_and_late_sources_flagged(self):
        row = replace(self.observation(), event_at=None, event_day="2026-01-01")
        book = self.o.TimingBook([row])
        with self.assertRaises(ValueError):
            book.features("invented-rider", "99", "2026-01-02", None)
        f = book.features("invented-rider", "99", "2026-01-02", "2026-01-08T12:00:00Z", scope="retrospective")
        self.assertEqual(f["retrospective_only"], 1)
        self.assertEqual(f["late_source_count"], 1)
        same_day = book.features("invented-rider", "99", "2026-01-01", "2026-01-08T12:00:00Z", scope="retrospective")
        self.assertEqual(same_day["full_last_lap_seconds_count"], 0)

    def test_context_features_support_identity_and_venue_aliases(self):
        record = {"day":"2026-01-05", "venue_code":"99", "riders":[{"identity_key":"invented-rider", "car":1}],
            "timing_observations":[asdict(self.observation())]}
        f = self.o.context_features(record, "2026-01-08T12:00:00Z", scope="retrospective")
        self.assertEqual(f["invented-rider"]["full_last_lap_seconds_mean"], 24.)

    def test_phase_adapter_preserves_user_estimate_and_tactical_unknown_denominators(self):
        phase = self.o.PhaseObservation(race_id="202601019901", phase="FINAL_HOME", order=(1,2,3),
            complete=True, provenance=self.source("user_observation"), receipt="synthetic-only")
        rows = self.o.to_pdca_observations([phase])
        self.assertEqual(rows[0]["source"], "user")
        self.assertEqual(rows[0]["aspect"], "FINAL_HOME")
        events = [self.o.TacticalOpportunity(opportunity_id=str(i), race_id="synthetic-old-1", rider_id="invented-rider",
            phase="FINAL_BACK", action="attack", outcome=outcome, provenance=self.source("user_observation"))
            for i,outcome in enumerate(("success","failure","unknown"))]
        summary = self.o.tactical_summary(events)
        self.assertEqual(summary["attack"], {"opportunities":3,"success":1,"failure":1,"unknown":1,"known_success_rate":.5})
        goal = replace(phase, phase="GOAL")
        self.assertEqual(self.o.to_pdca_observations([goal]), [])
        compared = self.o.compare_with_existing_pdca(race_id="202601019901",starters=[1,2,3],
            forecast={"race_id":"202601019901","scope":"conversation_reference","tickets":[[1,2,3]],
                      "flow":{"FINAL_HOME":[1,2,3]}},
            order={"race_id":"202601019901","winning_triples":[[1,2,3]]},phase_observations=[phase],
            verify_forecast=lambda row:False,verify_order=lambda row:True,verify_observation=lambda row:False)
        self.assertIsNone(compared["grade"])
        self.assertFalse(compared["placing"]["formal"])
        self.assertEqual(compared["reference_flow"]["aspects"]["FINAL_HOME"]["state"],"match")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "optional ffmpeg unavailable")
    def test_extracts_real_local_frames_with_original_timestamp_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp)/"synthetic.mp4"
            subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-f","lavfi","-i","color=c=red:s=32x32:r=10",
                "-t","0.6","-c:v","mpeg4",str(video)], check=True, capture_output=True)
            with self.assertRaises(PermissionError):
                self.o.extract_local_frames(video, Path(tmp)/"blocked", rights_confirmed=False)
            manifest = self.o.extract_local_frames(video, Path(tmp)/"frames", rights_confirmed=True, duration_seconds=.5, every_n_frames=1)
            self.assertGreaterEqual(len(manifest["frames"]), 4)
            self.assertEqual(manifest["source_sha256"], __import__("hashlib").sha256(video.read_bytes()).hexdigest())
            self.assertAlmostEqual(manifest["source_fps"], 10.)
            timestamps = [r["pts_seconds"] for r in manifest["frames"]]
            self.assertEqual(timestamps, sorted(timestamps))
            self.assertTrue(all((Path(tmp)/"frames"/r["file"]).is_file() for r in manifest["frames"]))
            seeked = self.o.extract_local_frames(video, Path(tmp)/"seeked", rights_confirmed=True,
                start_seconds=.2, duration_seconds=.3, every_n_frames=1)
            self.assertEqual([r["pts_seconds"] for r in seeked["frames"]], [.2,.3,.4])


class VenueTests(unittest.TestCase):
    def setUp(self):
        self.v = module("venues")
        self.assertIsNotNone(self.v, "The dated venue geometry module is not implemented")

    def record(self):
        return dict(venue_code="99", name="Invented test venue", circumference_m=400., straight_m=50., cant_deg=30.,
            effective_from="2026-01-01", effective_to=None, geometry_scope="dated", indoor=None,
            source_url="https://example.test/synthetic-geometry", source_sha256="b"*64,
            retrieved_at="2026-01-01T00:00:00Z")

    def test_geometry_dates_source_and_null_wind_axes_are_preserved(self):
        store = self.v.VenueStore.from_records([self.record()])
        f = store.features("99", "2026-01-03", "2026-01-02T00:00:00Z")
        self.assertEqual(f["venue_circumference_m"], 400.)
        self.assertIsNone(f["venue_indoor"])
        self.assertIsNone(f["venue_home_bearing_deg"])
        old = store.features("99", "2025-01-03", "2026-01-02T00:00:00Z")
        self.assertIsNone(old["venue_circumference_m"])
        late = store.features("99", "2026-01-03", "2025-12-31T00:00:00Z")
        self.assertIsNone(late["venue_circumference_m"])

    def test_current_geometry_requires_explicit_historical_assumption(self):
        r = dict(self.record(), effective_from=None, geometry_scope="current_unversioned")
        store = self.v.VenueStore.from_records([r])
        self.assertIsNone(store.features("99", "2025-11-20", "2026-01-02T00:00:00Z")["venue_straight_m"])
        f = store.features("99", "2025-11-20", "2026-01-02T00:00:00Z", allow_current_geometry_assumption=True)
        self.assertEqual(f["retrospective_current_geometry_assumption"], 1)
        self.assertEqual(f["venue_straight_m"], 50.)

    def test_rejects_nonphysical_or_unattributed_geometry(self):
        for changes in ({"source_sha256":""}, {"circumference_m":-1.}, {"cant_deg":100.},
                        {"straight_m":500.}, {"effective_to":"2025-01-01"}, {"indoor":"unknown"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.v.VenueStore.from_records([dict(self.record(), **changes)])

    def test_official_html_parser_extracts_only_geometry_and_keeps_source_hash(self):
        raw = ('PJ0701json = '+json.dumps({"data":{"jyoCode":"99", "jyoName":"Invented test venue"}})+';\n'+
            'PJ0703json = '+json.dumps({"data":{"jyoCode":"99", "syutyoImg":"/pc/static/img/sisetsu/bank400.gif",
                "tyokusen":"50.0m","kant":"30&deg;30&prime;0&Prime;", "tkant":"3&deg;0&prime;0&Prime;",
                "homeHukuin":"11.0m", "backHukuin":"10.0m", "centerHukuin":"8.0m", "maxAgariMei":"DO NOT COPY"}})+';').encode()
        r = self.v.parse_keirin_jp_geometry(raw, "https://www.keirin.jp/pc/jyoguide?jocd=99", "2026-01-01T00:00:00Z")
        self.assertEqual(r["cant_deg"], 30.5)
        self.assertEqual(r["circumference_m"], 400.)
        self.assertEqual(r["source_sha256"], __import__("hashlib").sha256(raw).hexdigest())
        self.assertNotIn("DO NOT COPY", json.dumps(r))
        self.assertIsNone(r["indoor"])
        self.assertIsNone(r["effective_from"])


if __name__ == "__main__":
    unittest.main()
