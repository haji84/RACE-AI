"""Synthetic identity/association contracts; these do not validate real footage."""
import importlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


CV_AVAILABLE = importlib.util.find_spec("cv2") is not None


@unittest.skipUnless(CV_AVAILABLE, "optional video dependencies are unavailable")
class BoatIdentityTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        self.np = np
        self.frame = np.full((180, 640, 3), 100, np.uint8)
        try:
            self.module = importlib.import_module("race_ai.boat_video_identity")
        except ImportError:
            self.fail("the local six-boat identity provider is missing")

    def detection(self, x, *, y=70, width=30, height=24):
        return {"box": [x, y, width, height], "score": .95}

    def provider(self, numbers, **options):
        self.numbers = list(numbers)
        def read(crop):
            number = self.numbers.pop(0)
            if number is None:
                return []
            return [{"text": str(number), "score": .98, "box": [8, 6, 10, 12]}]
        return self.module.BoatIdentityProvider(detector=lambda frame: [],
                                               number_reader=read, **options)

    def identify(self, provider, detections, frame_index, **options):
        return provider.identify(self.frame, detections, t=frame_index / 10,
                                 frame_index=frame_index, scene=options.pop("scene", 0), **options)

    def test_six_numbered_hulls_include_achromatic_boats_after_three_observations(self):
        # All hull pixels are deliberately identical grey, including lanes 1/2.
        provider = self.provider(list(range(1, 7)) * 3)
        for frame in range(3):
            rows = [self.detection(20 + n * 80 + frame * 2) for n in range(6)]
            output = self.identify(provider, rows, frame)
            self.assertEqual(len(output["exclusion_boxes"]), 6)
            if frame < 2:
                self.assertEqual(output["regions"], [])
        self.assertEqual({row["lane"] for row in output["regions"]}, set(range(1, 7)))
        self.assertEqual(len({row["track_id"] for row in output["regions"]}), 6)
        for row in output["regions"]:
            self.assertEqual(row["identity_status"], "NUMBER_TEMPORAL_CANDIDATE")
            self.assertEqual(row["number_evidence"]["observations"], 3)
        self.assertIs(output["model_eligible"], False)
        self.assertIs(output["identity_validated"], False)
        json.dumps(output, allow_nan=False)

    def test_camera_translation_preserves_track_and_number_evidence(self):
        provider = self.provider([1] * 4)
        for frame in range(3):
            output = self.identify(provider, [self.detection(30)], frame)
        old_id = output["regions"][0]["track_id"]
        transform = [[1, 0, 180], [0, 1, 0], [0, 0, 1]]
        output = self.identify(provider, [self.detection(210)], 3,
                               previous_to_current=transform)
        self.assertEqual(output["regions"][0]["track_id"], old_id)
        self.assertEqual(output["regions"][0]["number_evidence"]["observations"], 4)

    def test_number_evidence_preserves_identity_when_hulls_cross_positions(self):
        provider = self.provider([1, 2] * 4)
        for frame in range(3):
            output = self.identify(provider, [self.detection(100), self.detection(150)], frame)
        ids = {row["lane"]: row["track_id"] for row in output["regions"]}
        output = self.identify(provider, [self.detection(150), self.detection(100)], 3)
        self.assertEqual({row["lane"]: row["track_id"] for row in output["regions"]}, ids)
        self.assertEqual({row["lane"]: row["box"][0] for row in output["regions"]}, {1: 150, 2: 100})

    def test_missing_detection_and_time_gap_require_fresh_evidence(self):
        for missing_frame in (True, False):
            with self.subTest(missing_frame=missing_frame):
                provider = self.provider([1] * 4)
                for frame in range(3):
                    output = self.identify(provider, [self.detection(50)], frame)
                self.assertEqual(len(output["regions"]), 1)
                if missing_frame:
                    self.assertEqual(self.identify(provider, [], 3)["regions"], [])
                output = self.identify(provider, [self.detection(50)], 4 if missing_frame else 9)
                self.assertEqual(output["regions"], [])

    def test_scene_change_cannot_inherit_a_number(self):
        provider = self.provider([2] * 4)
        for frame in range(3):
            self.identify(provider, [self.detection(80)], frame)
        self.assertEqual(self.identify(provider, [self.detection(80)], 3, scene=1)["regions"], [])

    def test_conflicting_number_never_keeps_previous_identity(self):
        provider = self.provider([1, 1, 1, 3])
        for frame in range(3):
            self.identify(provider, [self.detection(80)], frame)
        self.assertEqual(self.identify(provider, [self.detection(80)], 3)["regions"], [])

    def test_conflicting_digit_cannot_redirect_identity_to_a_nearby_unread_hull(self):
        provider = self.provider([1, 1, 1, 2, None, 1])
        for frame in range(3):
            self.identify(provider, [self.detection(100)], frame)
        output = self.identify(provider, [self.detection(100), self.detection(135)], 3)
        self.assertEqual(output["regions"], [])
        self.assertIn("CONFLICTING_NUMBER_OBSERVATIONS", output["quality_flags"])
        self.assertEqual(self.identify(provider, [self.detection(100)], 4)["regions"], [])

    def test_duplicate_numbers_are_missing_on_both_hulls(self):
        provider = self.provider([1, 1] * 4)
        for frame in range(4):
            output = self.identify(provider, [self.detection(40), self.detection(180)], frame)
            self.assertEqual(output["regions"], [])
        self.assertIn("DUPLICATE_NUMBER_OBSERVATIONS", output["quality_flags"])

    def test_duplicate_number_cannot_redirect_identity_to_an_unread_third_hull(self):
        provider = self.provider([1, 1, 1, 1, 1, None])
        for frame in range(3):
            self.identify(provider, [self.detection(100)], frame)
        output = self.identify(provider, [self.detection(100), self.detection(200), self.detection(135)], 3)
        self.assertEqual(output["regions"], [])

    def test_occluded_track_cannot_redirect_to_an_unread_nearby_hull(self):
        provider = self.provider([1, 1, 1, None])
        for frame in range(3):
            self.identify(provider, [self.detection(100)], frame)
        output = self.identify(provider, [self.detection(100), self.detection(104), self.detection(135)], 3)
        self.assertEqual(output["regions"], [])

    def test_ambiguous_digit_crop_cannot_redirect_identity_to_a_nearby_unread_hull(self):
        single = [{"text": "1", "score": .98, "box": [2, 6, 8, 12]}]
        ambiguous = single + [{"text": "2", "score": .98, "box": [18, 6, 8, 12]}]
        readings = iter([single, single, single, ambiguous, [], single])
        provider = self.module.BoatIdentityProvider(detector=lambda frame: [],
            number_reader=lambda crop: next(readings))
        for frame in range(3):
            output = self.identify(provider, [self.detection(100)], frame)
        self.assertEqual(output["regions"][0]["track_id"], "T000001")
        output = self.identify(provider, [self.detection(100), self.detection(135)], 3)
        self.assertIn("AMBIGUOUS_NUMBER_MARKS", output["quality_flags"])
        self.assertEqual(len(output["exclusion_boxes"]), 2)
        self.assertEqual(output["regions"], [])
        # The interrupted old identity must also require new evidence afterward.
        self.assertEqual(self.identify(provider, [self.detection(100)], 4)["regions"], [])

    def test_merged_hulls_do_not_coast_and_need_reidentification(self):
        provider = self.provider([1, 2] * 3 + [1, 2])
        for frame in range(3):
            self.identify(provider, [self.detection(60), self.detection(160)], frame)
        output = self.identify(provider, [self.detection(100), self.detection(104)], 3)
        self.assertEqual(output["regions"], [])
        self.assertEqual(len(output["exclusion_boxes"]), 2)
        self.assertIn("OVERLAPPING_HULL_CANDIDATES", output["quality_flags"])

    def test_equally_plausible_associations_cannot_inherit_numbers(self):
        provider = self.provider([1, 2] * 3 + [None, None])
        for frame in range(3):
            self.identify(provider, [self.detection(80, y=50), self.detection(140, y=50)], frame)
        output = self.identify(provider, [self.detection(110, y=25), self.detection(110, y=75)], 3)
        self.assertEqual(output["regions"], [])
        self.assertIn("AMBIGUOUS_TEMPORAL_ASSOCIATION", output["quality_flags"])

    def test_static_overlay_is_excluded_from_identity_but_retained_for_camera_mask(self):
        provider = self.provider([], exclusions=[[10, 10, 100, 35]])
        row = self.detection(20, y=15)
        for frame in range(3):
            output = self.identify(provider, [row], frame)
            self.assertEqual(output["regions"], [])
            self.assertEqual(output["exclusion_boxes"], [row["box"]])
        self.assertIn("OVERLAY_INTERSECTION", output["quality_flags"])

    def test_invalid_digit_geometry_and_nonexact_digit_cannot_assign_hull(self):
        readings = [
            [{"text": "1", "score": .99, "box": [25, 5, 10, 10]}],
            [{"text": "12", "score": .99, "box": [2, 5, 10, 10]}],
            [{"text": "1", "score": .4, "box": [2, 5, 10, 10]}],
            [{"text": "1", "score": .99, "box": [-1, 5, 10, 10]}],
        ]
        for reading in readings:
            provider = self.module.BoatIdentityProvider(detector=lambda frame: [],
                                                       number_reader=lambda crop: reading)
            for frame in range(3):
                self.assertEqual(self.identify(provider, [self.detection(70)], frame)["regions"], [])

    def test_invalid_frame_detection_clock_and_homography_fail_closed(self):
        provider = self.provider([1] * 10)
        self.identify(provider, [self.detection(70)], 0)
        for kwargs in ({"t": 0, "frame_index": 1, "scene": 0},
                       {"t": .1, "frame_index": 0, "scene": 0},
                       {"t": .1, "frame_index": 1, "scene": 0,
                        "previous_to_current": [[1, 0, 0], [0, math.nan, 0], [0, 0, 1]]}):
            with self.assertRaises(ValueError):
                provider.identify(self.frame, [], **kwargs)
        with self.assertRaises(ValueError):
            self.identify(provider, [{"box": [620, 70, 30, 24], "score": .95}], 1)
        with self.assertRaises(ValueError):
            provider.detect(self.frame.astype(self.np.float32))
        with self.assertRaises(ValueError):
            self.identify(provider, [{"box": [10 ** 1000, 70, 30, 24], "score": .95}], 1)

    def test_detector_receives_copy_and_metadata_has_no_paths_or_verified_claims(self):
        def detector(frame):
            frame[:] = 0
            return [self.detection(50)]
        provider = self.module.BoatIdentityProvider(detector=detector, number_reader=lambda crop: [])
        self.assertEqual(provider.detect(self.frame), [self.detection(50)])
        self.assertTrue((self.frame == 100).all())
        metadata = provider.metadata()
        self.assertIs(metadata["model_eligible"], False)
        self.assertEqual(metadata["field_validation"], "NOT_ESTABLISHED")
        self.assertNotIn("/workspace", json.dumps(metadata))

    def test_factory_requires_existing_local_assets_and_never_downloads(self):
        with self.assertRaises(ValueError):
            self.module.create_local_identity_provider(model_path="/no/model.onnx",
                tesseract_path="/no/tesseract", tessdata_path="/no/tessdata")

    def test_media_extractor_creates_fresh_provider_for_each_clip(self):
        make_extractor = getattr(self.module, "make_local_identity_extractor", None)
        self.assertTrue(callable(make_extractor), "the per-media identity extractor factory is missing")
        made = []
        def build_provider(**configuration):
            provider = self.provider([1, 1, 1])
            made.append(provider)
            return provider

        def decode_media(path, *, options=None, identity_provider):
            # Exercise actual temporal state at the production extractor boundary.
            for frame in range(3):
                observation = self.identify(identity_provider, [self.detection(80)], frame)
            return {"media": path, "track_id": observation["regions"][0]["track_id"],
                    "options": options}

        with patch.object(self.module, "create_local_identity_provider", side_effect=build_provider):
            extract = make_extractor(model_path="/private/assets/detector.onnx",
                                     tesseract_path="/private/bin/tesseract",
                                     tessdata_path="/private/assets/tessdata")
            self.assertEqual(made, [], "configuring intake must not load model assets")
            with patch("race_ai.boat_video_tracking.extract_tracks", side_effect=decode_media):
                first = extract("first.avi", options={"sampling_fps": 5})
                second = extract("second.avi")
        self.assertEqual(len(made), 2)
        self.assertIsNot(made[0], made[1])
        self.assertEqual((first["track_id"], second["track_id"]), ("T000001", "T000001"))
        self.assertEqual(first["options"], {"sampling_fps": 5})
        self.assertIsNone(second["options"])
        self.assertNotIn("/private/", json.dumps([first, second]))

    def test_ocr_reader_falls_back_for_an_isolated_digit_and_remaps_geometry(self):
        header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        digit = "5\t1\t1\t1\t1\t1\t24\t18\t30\t36\t98\t2\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "tesseract"
            executable.write_bytes(b"test executable boundary")
            executable.chmod(0o700)
            (root / "eng.traineddata").write_bytes(b"test language boundary")
            replies = [subprocess.CompletedProcess([], 0, b"tesseract 5.5.0\n", b""),
                       subprocess.CompletedProcess([], 0, header.encode(), b""),
                       subprocess.CompletedProcess([], 0, (header+digit).encode(), b"")]
            # Mock only the external process; production TSV/geometry parsing is real.
            with patch.object(self.module.subprocess, "run", side_effect=replies):
                reader = self.module.LocalTesseractNumberReader(tesseract_path=executable, tessdata_path=root)
                rows = reader(self.frame[70:94, 50:80].copy())
            self.assertEqual(rows, [{"text": "2", "score": .98, "box": [8., 6., 10., 12.]}])
            self.assertNotIn(directory, json.dumps(reader.metadata()))

    def test_yolox_decoder_uses_boat_class_and_reverses_integer_resize(self):
        output = self.np.zeros((1, 8400, 85), self.np.float32)
        # First stride-8 cell predicts center(100,200), dimensions(80,40).
        output[0, 0, :4] = [12.5, 25, math.log(10), math.log(5)]
        output[0, 0, 4] = 1
        output[0, 0, 13] = .95
        rows = self.module.decode_yolox_regions(output, width=640, height=360)
        self.assertEqual(len(rows), 1)
        for actual, expected in zip(rows[0]["box"], [60, 180, 80, 40]):
            self.assertAlmostEqual(actual, expected, places=4)
        output[0, 0, 13] = 0
        output[0, 0, 5] = .99  # Person is never a hull candidate.
        self.assertEqual(self.module.decode_yolox_regions(output, width=640, height=360), [])

    def test_nanodet_decoder_pairs_heads_by_shape(self):
        outputs = []
        for side in (52, 26, 13):
            scores = self.np.zeros((1, side * side, 80), self.np.float32)
            distances = self.np.zeros((1, side * side, 32), self.np.float32)
            if side == 52:
                scores[0, 20 * side + 20, 8] = .95
            outputs += [distances, scores]
        rows = self.module.decode_nanodet_regions(outputs[::-1], width=416, height=416)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["box"], [135.5, 135.5, 56., 56.])


if __name__ == "__main__":
    unittest.main()
