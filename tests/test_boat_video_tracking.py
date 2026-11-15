"""Real decoding of synthetic media; no field validation or boat-ID evidence."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


def extractor(test):
    try:
        from race_ai.boat_video_tracking import extract_tracks
    except ImportError:
        test.fail("local video tracking engine is missing")
    return extract_tracks


CV_AVAILABLE = importlib.util.find_spec("cv2") is not None
MEDIA_AVAILABLE = CV_AVAILABLE and shutil.which("ffprobe") and shutil.which("ffmpeg")


@unittest.skipUnless(MEDIA_AVAILABLE, "video tracking fixtures need optional OpenCV plus ffmpeg/ffprobe")
class SyntheticDecodedTrackingTests(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np
        self.cv2, self.np = cv2, np
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def clip(self, *, pan=False, cut=False, occlusion=False, collision=False, stationary=False):
        """32 displayed frames: world boat moves 3 px/frame; camera 0 or 2 px/frame."""
        cv2, np = self.cv2, self.np
        rng = np.random.default_rng(71)
        noise = rng.integers(45, 165, (192, 448), dtype=np.uint8)
        background = cv2.cvtColor(cv2.GaussianBlur(noise, (3, 3), 0), cv2.COLOR_GRAY2BGR)
        alternate = cv2.cvtColor(rng.integers(65, 145, (192, 448), dtype=np.uint8), cv2.COLOR_GRAY2BGR)
        path = self.root / (f"fixture-{len(list(self.root.iterdir()))}.avi")
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 192))
        self.assertTrue(writer.isOpened())
        for i in range(32):
            camera = 2*i if pan else 0
            base = alternate if cut and i >= 16 else background
            frame = base[:, camera:camera+320].copy()
            world_x = 65 if stationary else 65 + 3*i
            x = world_x - camera
            if not (occlusion and 12 <= i <= 15):
                cv2.rectangle(frame, (x-8, 92), (x+8, 104), (0, 0, 245), -1)
            if collision and 12 <= i <= 15:
                cv2.rectangle(frame, (x-7, 92), (x+9, 104), (245, 0, 0), -1)
            # A colored scoreboard must not become a tracked moving boat.
            cv2.rectangle(frame, (240, 3), (280, 18), (0, 0, 245), -1)
            writer.write(frame)
        writer.release()
        return path

    def run_clip(self, path, **options):
        return extractor(self)(path, options={"sampling_fps": 10, **options})

    def test_real_decode_tracks_known_motion_using_pts_and_marks_unvalidated(self):
        path = self.clip()
        out = self.run_clip(path)
        self.assertEqual(out["schema_version"], "RACE_AI_BOAT_VIDEO_TRACKS_V1")
        self.assertEqual(out["media_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual((out["width"], out["height"]), (320, 192))
        self.assertEqual(out["timeline_source"], "MEDIA_PTS")
        self.assertEqual(out["coordinate_space"], "REFERENCE_IMAGE_PX")
        self.assertFalse(out["model_eligible"])
        self.assertEqual(out["validation_status"], "UNVALIDATED")
        red = out["tracks"][2]
        self.assertEqual(red["identity_status"], "COLOR_CANDIDATE")
        valid = [p for p in red["samples"] if p["valid"]]
        self.assertGreaterEqual(len(valid), 26)
        for p in valid:
            self.assertAlmostEqual(p["t"], p["frame_index"] / 10, places=6)
            self.assertAlmostEqual(p["x"], 65 + 3*p["frame_index"], delta=1.5)
            self.assertAlmostEqual(p["y"], 98, delta=1.5)
            self.assertGreaterEqual(p["position_error"], 0)
        self.assertTrue(out["quality"]["camera_estimates"])
        self.assertIn("COLOR_DOES_NOT_VERIFY_BOAT_IDENTITY", out["quality"]["flags"])

    def test_accelerating_camera_pan_does_not_become_boat_speed_trend(self):
        # Encode a distinct clip with accelerating camera x=floor(i*i/16).
        cv2, np = self.cv2, self.np
        background = cv2.cvtColor(np.random.default_rng(99).integers(45, 165, (192, 448), dtype=np.uint8), cv2.COLOR_GRAY2BGR)
        path = self.root / "accelerating-pan.avi"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 192))
        for i in range(32):
            camera = i*i//16
            frame = background[:, camera:camera+320].copy()
            cv2.rectangle(frame, (65+3*i-camera-8, 92), (65+3*i-camera+8, 104), (0, 0, 245), -1)
            writer.write(frame)
        writer.release()
        out = self.run_clip(path)
        valid = [p for p in out["tracks"][2]["samples"] if p["valid"]]
        self.assertGreaterEqual(len(valid), 24)
        self.assertLess(max(abs(p["x"] - (65+3*p["frame_index"])) for p in valid), 2.0)
        early = (valid[8]["x"]-valid[1]["x"])/(valid[8]["t"]-valid[1]["t"])
        late = (valid[-1]["x"]-valid[-8]["x"])/(valid[-1]["t"]-valid[-8]["t"])
        self.assertAlmostEqual(early, 30, delta=2)
        self.assertAlmostEqual(late, 30, delta=2)
        self.assertAlmostEqual(late-early, 0, delta=3)

    def test_projective_camera_motion_cannot_create_stationary_object_performance(self):
        cv2, np = self.cv2, self.np
        background = np.random.default_rng(73).integers(60, 195, (192, 320), dtype=np.uint8)
        background = cv2.cvtColor(cv2.GaussianBlur(background, (3, 3), 0), cv2.COLOR_GRAY2BGR)
        cv2.rectangle(background, (40, 140), (50, 150), (245, 0, 0), -1)
        path = self.root / "stationary-projective.avi"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 192))
        for i in range(32):
            homography = np.array([[1, 0, 0], [0, 1, 0], [0.00003*i, 0, 1]], dtype=float)
            writer.write(cv2.warpPerspective(background, homography, (320, 192), borderMode=cv2.BORDER_REFLECT))
        writer.release()
        out = self.run_clip(path)
        self.assertFalse(any(p["valid"] for p in out["tracks"][3]["samples"]),
                         "stationary color under projective camera motion must remain missing")
        from race_ai.boat_video_measurements import measure_tracks
        measured = measure_tracks(out["tracks"], coordinate_space="REFERENCE_IMAGE_PX")
        self.assertTrue(all(p["status"] == "MISSING" for p in measured["lanes"][3]["phases"].values()))

    def test_independent_motion_remains_measurable_during_projective_camera_motion(self):
        cv2, np = self.cv2, self.np
        background = np.random.default_rng(73).integers(60, 195, (192, 320), dtype=np.uint8)
        background = cv2.cvtColor(cv2.GaussianBlur(background, (3, 3), 0), cv2.COLOR_GRAY2BGR)
        path = self.root / "moving-projective.avi"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 192))
        for i in range(32):
            frame = background.copy()
            cv2.rectangle(frame, (65+3*i-8, 92), (65+3*i+8, 104), (245, 0, 0), -1)
            homography = np.array([[1, 0, 0], [0, 1, 0], [0.00003*i, 0, 1]], dtype=float)
            writer.write(cv2.warpPerspective(frame, homography, (320, 192), borderMode=cv2.BORDER_REFLECT))
        writer.release()
        out = self.run_clip(path)
        valid = [p for p in out["tracks"][3]["samples"] if p["valid"]]
        self.assertGreaterEqual(len(valid), 26)
        for point in valid:
            self.assertAlmostEqual(point["x"], 65+3*point["frame_index"], delta=1.5)
            self.assertAlmostEqual(point["y"], 98, delta=1.5)

    def test_multiple_same_color_components_cannot_hide_overlap_with_another_color(self):
        cv2, np = self.cv2, self.np
        background = cv2.cvtColor(np.random.default_rng(41).integers(50, 150, (192, 320), dtype=np.uint8), cv2.COLOR_GRAY2BGR)
        path = self.root / "ambiguous-red-overlaps-blue.avi"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 192))
        for i in range(16):
            frame, x = background.copy(), 70+3*i
            cv2.rectangle(frame, (x-13, 90), (x-3, 102), (0, 0, 245), -1)
            cv2.rectangle(frame, (x, 90), (x+10, 102), (245, 0, 0), -1)
            cv2.rectangle(frame, (220-3*i, 135), (230-3*i, 147), (0, 0, 245), -1)
            writer.write(frame)
        writer.release()
        out = self.run_clip(path)
        for lane in (3, 4):
            self.assertFalse(any(p["valid"] for p in out["tracks"][lane-1]["samples"]))

    def test_display_duration_uses_relative_pts_even_with_large_container_offset(self):
        source, target = self.clip(), self.root / "offset.mkv"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-vf", "setpts=PTS+130/TB",
                        "-fps_mode", "passthrough", "-c:v", "ffv1", str(target)], check=True)
        out = self.run_clip(target)
        self.assertAlmostEqual(out["media_pts_origin_seconds"], 130, places=6)
        self.assertAlmostEqual(out["tracks"][2]["samples"][-1]["t"], 3.1, places=6)
        self.assertGreaterEqual(out["duration_seconds"], 3.1-1e-6)
        self.assertLessEqual(out["duration_seconds"], 3.2+1e-6)

    def test_codec_dimension_changes_reject_even_when_ffmpeg_would_autoscale(self):
        parts = []
        for size in ("160x96", "640x384"):
            path = self.root / f"{size}.h264"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=10:duration=1",
                            "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", "-tune", "zerolatency",
                            "-f", "h264", str(path)], check=True)
            parts.append(path.read_bytes())
        elementary = self.root / "changing.h264"
        elementary.write_bytes(b"".join(parts))
        target = self.root / "dynamic.mkv"
        subprocess.run(["ffmpeg", "-v", "error", "-r", "10", "-i", str(elementary), "-c:v", "copy", str(target)], check=True)
        for limits in ({}, {"max_dimension": 200, "max_pixels": 20000}):
            with self.subTest(limits=limits), self.assertRaisesRegex(ValueError, "dimension|resource|probe"):
                self.run_clip(target, **limits)

    def test_cut_and_occlusion_are_missing_and_tracks_never_join_across_them(self):
        for kwargs in ({"cut": True}, {"occlusion": True}, {"collision": True}):
            with self.subTest(kwargs=kwargs):
                out = self.run_clip(self.clip(**kwargs))
                red = out["tracks"][2]["samples"]
                window = red[12:17] if not kwargs.get("cut") else red[16:18]
                self.assertTrue(any(not p["valid"] for p in window))
                before = [p for p in red[:12] if p["valid"]][-1]
                after = [p for p in red[18:] if p["valid"]][0]
                self.assertNotEqual(before["scene"], after["scene"])
                for p in window:
                    if not p["valid"]:
                        self.assertIsNone(p["x"])
                        self.assertIsNone(p["y"])
                if kwargs.get("collision"):
                    self.assertFalse(any(p["valid"] for p in out["tracks"][3]["samples"][12:16]))

    def test_stationary_color_overlay_and_achromatic_colors_do_not_create_tracks(self):
        out = self.run_clip(self.clip(stationary=True))
        for lane in (1, 2, 3):
            self.assertFalse(any(p["valid"] for p in out["tracks"][lane-1]["samples"]))
        self.assertIn("ACHROMATIC_LANES_UNRESOLVED", out["quality"]["flags"])

    def test_stationary_world_object_during_camera_pan_is_not_independent_motion(self):
        out = self.run_clip(self.clip(stationary=True, pan=True))
        self.assertFalse(any(p["valid"] for p in out["tracks"][2]["samples"]))

    def test_textureless_background_cannot_fall_back_to_identity_camera_transform(self):
        cv2, np = self.cv2, self.np
        path = self.root / "no-camera-support.avi"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 192))
        for i in range(16):
            frame = np.full((192, 320, 3), 100, np.uint8)
            cv2.rectangle(frame, (60+3*i, 92), (76+3*i, 104), (0, 0, 245), -1)
            writer.write(frame)
        writer.release()
        out = self.run_clip(path)
        self.assertFalse(any(p["valid"] for p in out["tracks"][2]["samples"]))
        self.assertTrue(all(c["status"] != "ACCEPTED" for c in out["quality"]["camera_estimates"]))

    def test_two_moving_components_of_same_color_remain_ambiguous(self):
        cv2, np = self.cv2, self.np
        background = cv2.cvtColor(np.random.default_rng(41).integers(50, 150, (192, 320), dtype=np.uint8), cv2.COLOR_GRAY2BGR)
        path = self.root / "ambiguous-red.avi"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 192))
        for i in range(16):
            frame = background.copy()
            for x, y in ((60+3*i, 90), (200-3*i, 140)):
                cv2.rectangle(frame, (x, y), (x+16, y+12), (0, 0, 245), -1)
            writer.write(frame)
        writer.release()
        out = self.run_clip(path)
        samples = out["tracks"][2]["samples"]
        self.assertFalse(any(p["valid"] for p in samples))
        self.assertIn("AMBIGUOUS_COLOR_CANDIDATES", {p.get("reason") for p in samples})

    def test_resource_limits_reject_the_whole_media_without_truncating(self):
        path = self.clip()
        for options in ({"max_decoded_frames": 10}, {"max_duration_seconds": 1}, {"max_bytes": 64}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "resource limit"):
                self.run_clip(path, **options)

    def test_variable_display_pts_are_preserved_and_missing_or_repeated_pts_rejected(self):
        source = self.clip()
        target = self.root / "vfr.mkv"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-vf", "setpts='if(lt(N,16),N,16+(N-16)*2)/(10*TB)'", "-fps_mode", "vfr", "-c:v", "ffv1", str(target)], check=True)
        # EBML signature also covers Matroska, which is accepted only as local WebM/Matroska media.
        out = self.run_clip(target)
        samples = out["tracks"][2]["samples"]
        self.assertAlmostEqual(samples[16]["t"], 1.6, places=6)
        self.assertAlmostEqual(samples[17]["t"], 1.8, places=6)
        self.assertAlmostEqual(samples[-1]["t"], 4.6, places=6)
        from race_ai import boat_video_tracking
        original = boat_video_tracking._probe_frames
        for issue in ("missing", "duplicate"):
            def bad_pts(*args, **kwargs):
                frames = original(*args, **kwargs)
                frames[2]["pts_time"] = None if issue == "missing" else frames[1]["pts_time"]
                return frames
            with patch.object(boat_video_tracking, "_probe_frames", side_effect=bad_pts):
                with self.assertRaisesRegex(ValueError, "PTS"):
                    self.run_clip(source)


class LocalMediaBoundaryTests(unittest.TestCase):
    def test_urls_playlists_symlinks_and_nonregular_inputs_are_rejected_before_decoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            playlist = base / "movie.mp4"
            playlist.write_text("#EXTM3U\nhttps://example.invalid/remote.ts\n")
            link = base / "linked.mp4"
            link.symlink_to(playlist)
            for path in ("https://example.invalid/a.mp4", "file:///tmp/a.mp4", playlist, link, base):
                with self.subTest(path=str(path)), self.assertRaises(ValueError):
                    extractor(self)(path)

    def test_bad_options_fail_explicitly_before_media_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"bad.mp4"
            path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\0"*32)
            for options in ({"sampling_fps": True}, {"water_roi": [0, 0, 2, 1]},
                            {"min_area": -1}, {"sampling_fps": float("nan")}, {"surprise": 1}):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    extractor(self)(path, options=options)
