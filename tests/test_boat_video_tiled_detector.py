"""Fixed native-tile geometry contracts, not real-footage identity accuracy."""
import importlib.util
import json
import unittest
from unittest.mock import patch


CV_AVAILABLE = importlib.util.find_spec("cv2") is not None


@unittest.skipUnless(CV_AVAILABLE, "optional video dependencies are unavailable")
class TiledBoatDetectorTests(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np
        from race_ai import boat_video_identity
        self.cv2, self.np, self.module = cv2, np, boat_video_identity

    def wrapper(self, detector):
        self.assertTrue(hasattr(self.module, "TiledBoatDetector"),
                        "fixed optional local tiled inference is unavailable")
        return self.module.TiledBoatDetector(detector=detector)

    def crop_proposals(self, entries, *, detector_kind=None):
        """Exercise the public wrapper with independently tagged source pixels."""
        frame = self.np.zeros((1080, 1920, 3), self.np.uint8)
        origins = [(0, 0), (624, 0), (1088, 0), (0, 248), (624, 248), (1088, 248)]
        for tag, (x, y) in enumerate(origins, 1):
            frame[y, x, 0] = tag

        def detector(crop):
            source = "full" if crop.shape == frame.shape else origins[int(crop[0, 0, 0])-1]
            return entries.get(source, [])

        if detector_kind is None:
            return self.wrapper(detector)(frame)
        # Replace only local DNN inference; keep the real pinned-type policy.
        pinned = object.__new__(self.module.PinnedBoatDetector)
        pinned.kind, pinned.cv_version = detector_kind, self.cv2.__version__
        with patch.object(self.module.PinnedBoatDetector, "__call__",
                          new=lambda _self, crop: detector(crop)):
            return self.wrapper(pinned)(frame)

    def test_source_clipped_matching_stitches_observed_tile_fragments(self):
        # Frozen detector proposals reproduce the seam duplicate without media,
        # model loading, OCR, or any claim that these boxes certify identities.
        rows = self.crop_proposals({
            (624, 0): [{"box": [366.7656080927608, 616.3553329106319,
                                168.47820039467865, 53.287742210199895],
                        "score": .719760537147522}],
            (1088, 0): [{"box": [1.140808684555998, 609.587965337044,
                                 83.74512785488703, 59.77178470371973],
                         "score": .5904800891876221}],
            (1088, 248): [{"box": [1.1051888827545384, 368.9280687879102,
                                   83.34431631484372, 51.30782993821765],
                           "score": .5985432863235474}],
        })
        self.assertEqual(len(rows), 1)
        for actual, expected in zip(rows[0]["box"],
                                    [990.7656080927608, 616.3553329106319,
                                     168.47820039467865, 53.287742210199895]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(rows[0]["score"], .719760537147522)

    def test_source_clipped_matching_handles_all_internal_tile_sides(self):
        cases = [
            ((0, 0), [500, 400, 200, 40], (624, 0), [.5, 400, 70, 40],
             [500., 400., 200., 40.]),
            ((624, 0), [126, 400, 200, 40], (0, 0), [751.5, 400, 80, 40],
             [750., 400., 200., 40.]),
            ((0, 0), [400, 150, 100, 160], (0, 248), [400, .5, 100, 60],
             [400., 150., 100., 160.]),
            ((0, 248), [400, 502, 100, 200], (0, 0), [400, 751.5, 100, 80],
             [400., 750., 100., 200.]),
        ]
        for parent_source, parent_box, child_source, child_box, expected in cases:
            with self.subTest(parent_source=parent_source, child_source=child_source):
                rows = self.crop_proposals({
                    parent_source: [{"box": parent_box, "score": .95}],
                    child_source: [{"box": child_box, "score": .9}],
                })
                self.assertEqual(rows, [{"box": expected, "score": .95}])

    def test_interior_child_matching_clipped_parent_is_preserved(self):
        rows = self.crop_proposals({
            "full": [{"box": [500, 400, 300, 40], "score": .95}],
            (624, 0): [{"box": [56, 400, 100, 40], "score": .9}],
        })
        self.assertEqual(rows, [{"box": [500., 400., 300., 40.], "score": .95},
                                {"box": [680., 400., 100., 40.], "score": .9}])

    def test_child_must_touch_the_same_internal_edge_crossed_by_parent(self):
        rows = self.crop_proposals({
            "full": [{"box": [500, 248, 300, 200], "score": .95}],
            (624, 248): [{"box": [56, .5, 100, 200], "score": .9}],
        })
        self.assertEqual(rows, [{"box": [500., 248., 300., 200.], "score": .95},
                                {"box": [680., 248.5, 100., 200.], "score": .9}])

    def test_one_model_input_pixel_native_margin_has_an_inclusive_boundary(self):
        # An 832px source mapped to the injected default 640px input has a
        # 1.3 native-pixel precision margin, independently of any footage.
        for gap, expected_count in ((1.299999, 1), (1.3, 1), (1.300001, 2), (8., 2)):
            with self.subTest(gap=gap):
                rows = self.crop_proposals({
                    "full": [{"box": [500, 400, 300, 40], "score": .95}],
                    (624, 0): [{"box": [gap, 400, 100, 40], "score": .9}],
                })
                self.assertEqual(len(rows), expected_count)
                self.assertEqual(rows[0], {"box": [500., 400., 300., 40.], "score": .95})
                if expected_count == 2:
                    self.assertEqual(rows[1], {"box": [624+gap, 400., 100., 40.], "score": .9})

    def test_pinned_preprocessing_resolution_controls_native_precision_margin(self):
        for kind, expected_count in (("yolox", 2), ("nanodet", 1)):
            with self.subTest(kind=kind):
                rows = self.crop_proposals({
                    "full": [{"box": [500, 400, 300, 40], "score": .95}],
                    (624, 0): [{"box": [1.5, 400, 100, 40], "score": .9}],
                }, detector_kind=kind)
                self.assertEqual(len(rows), expected_count)

    def test_higher_confidence_partial_candidate_is_preserved(self):
        rows = self.crop_proposals({
            (0, 0): [{"box": [500, 400, 200, 40], "score": .9}],
            (624, 0): [{"box": [.5, 400, 70, 40], "score": .95}],
        })
        self.assertEqual(rows, [{"box": [624.5, 400., 70., 40.], "score": .95},
                                {"box": [500., 400., 200., 40.], "score": .9}])

    def test_overlapping_candidates_from_same_source_are_preserved(self):
        rows = self.crop_proposals({
            (624, 0): [{"box": [0, 400, 200, 40], "score": .95},
                       {"box": [8, 400, 70, 40], "score": .9}],
        })
        self.assertEqual(rows, [{"box": [624., 400., 200., 40.], "score": .95},
                                {"box": [632., 400., 70., 40.], "score": .9}])

    def test_overlap_without_source_boundary_crossing_is_preserved(self):
        rows = self.crop_proposals({
            "full": [{"box": [1050, 500, 200, 40], "score": .95}],
            (624, 0): [{"box": [476, 500, 70, 40], "score": .9}],
        })
        self.assertEqual(rows, [{"box": [1050., 500., 200., 40.], "score": .95},
                                {"box": [1100., 500., 70., 40.], "score": .9}])

    def test_two_incomplete_views_cannot_stitch_without_containing_source(self):
        rows = self.crop_proposals({
            (0, 0): [{"box": [500, 400, 320, 40], "score": .95}],
            (624, 0): [{"box": [1, 400, 275, 40], "score": .9}],
        })
        self.assertEqual(rows, [{"box": [500., 400., 320., 40.], "score": .95},
                                {"box": [625., 400., 275., 40.], "score": .9}])

    def test_source_clipped_match_below_existing_iou_limit_is_preserved(self):
        rows = self.crop_proposals({
            (0, 0): [{"box": [500, 400, 200, 40], "score": .95}],
            (624, 0): [{"box": [.5, 420, 70, 40], "score": .9}],
        })
        self.assertEqual(rows, [{"box": [500., 400., 200., 40.], "score": .95},
                                {"box": [624.5, 420., 70., 40.], "score": .9}])

    def test_larger_candidate_cannot_be_discarded_as_a_clipped_child(self):
        rows = self.crop_proposals({
            (0, 0): [{"box": [580, 400, 120, 40], "score": .95}],
            (624, 0): [{"box": [1, 400, 145, 40], "score": .9}],
        })
        self.assertEqual(rows, [{"box": [580., 400., 120., 40.], "score": .95},
                                {"box": [625., 400., 145., 40.], "score": .9}])

    def test_lone_internal_boundary_candidate_is_preserved(self):
        rows = self.crop_proposals({
            (624, 0): [{"box": [.5, 400, 70, 40], "score": .9}],
        })
        self.assertEqual(rows, [{"box": [624.5, 400., 70., 40.], "score": .9}])

    def test_outer_frame_edge_and_full_frame_candidates_are_preserved(self):
        rows = self.crop_proposals({
            (0, 0): [{"box": [0, 400, 200, 40], "score": .95}],
            "full": [{"box": [0, 400, 70, 40], "score": .9}],
        })
        self.assertEqual(rows, [{"box": [0., 400., 200., 40.], "score": .95},
                                {"box": [0., 400., 70., 40.], "score": .9}])

    def test_crop_pixels_bind_offsets_to_original_coordinates(self):
        frame = self.np.zeros((1080, 1920, 3), self.np.uint8)
        frame[248, 624] = [5, 5, 5]

        def detector(crop):
            if crop.shape == (832, 832, 3) and int(crop[0, 0, 0]) == 5:
                return [{"box": [20, 30, 50, 40], "score": .95}]
            return []

        self.assertEqual(self.wrapper(detector)(frame),
                         [{"box": [644., 278., 50., 40.], "score": .95}])

    def test_global_nms_removes_full_frame_and_overlapping_tile_duplicates(self):
        frame = self.np.zeros((1080, 1920, 3), self.np.uint8)
        # The top-left pixel independently records each crop's original origin.
        frame[:, :, 0] = self.np.arange(1920, dtype=self.np.uint16) % 256
        frame[:, :, 1] = self.np.arange(1920, dtype=self.np.uint16) // 256
        frame[:, :, 2] = (self.np.arange(1080, dtype=self.np.uint16) % 256)[:, None]

        def detector(crop):
            x = int(crop[0, 0, 0]) + 256 * int(crop[0, 0, 1])
            y = int(crop[0, 0, 2])
            if x <= 700 and y <= 400 and 800 <= x+crop.shape[1] and 440 <= y+crop.shape[0]:
                return [{"box": [700-x, 400-y, 100, 40], "score": .96}]
            return []

        self.assertEqual(self.wrapper(detector)(frame),
                         [{"box": [700., 400., 100., 40.], "score": .96}])

    def test_edge_aligned_tiles_cover_last_original_pixel(self):
        frame = self.np.zeros((1080, 1920, 3), self.np.uint8)
        frame[248, 1088] = [7, 7, 7]

        def detector(crop):
            if crop.shape == (832, 832, 3) and int(crop[0, 0, 0]) == 7:
                return [{"box": [800, 800, 32, 32], "score": .91}]
            return []

        self.assertEqual(self.wrapper(detector)(frame),
                         [{"box": [1888., 1048., 32., 32.], "score": .91}])

    def test_small_frame_is_evaluated_once_without_artificial_padding(self):
        shapes = []

        def detector(crop):
            shapes.append(crop.shape)
            return [{"box": [20, 30, 50, 40], "score": .9}]

        result = self.wrapper(detector)(self.np.zeros((100, 200, 3), self.np.uint8))
        self.assertEqual(shapes, [(100, 200, 3)])
        self.assertEqual(result, [{"box": [20., 30., 50., 40.], "score": .9}])

    def test_source_pixels_are_not_mutated_by_injected_model(self):
        frame = self.np.full((1080, 1920, 3), 70, self.np.uint8)
        before = frame.copy()

        def detector(crop):
            crop[:] = 0
            return []

        self.assertEqual(self.wrapper(detector)(frame), [])
        self.np.testing.assert_array_equal(frame, before)

    def test_invalid_crop_geometry_cannot_escape_original_frame(self):
        def detector(crop):
            if crop.shape == (832, 832, 3):
                return [{"box": [800, 800, 40, 40], "score": .99}]
            return []

        with self.assertRaisesRegex(ValueError, "inside the frame"):
            self.wrapper(detector)(self.np.zeros((1080, 1920, 3), self.np.uint8))

    def test_fixed_inference_budget_and_existing_candidate_cap_are_retained(self):
        shapes = []

        def detector(crop):
            shapes.append(crop.shape)
            return [{"box": [n*60, 50, 20, 20], "score": .99-n*.001}
                    for n in range(12)]

        rows = self.wrapper(detector)(self.np.zeros((1080, 1920, 3), self.np.uint8))
        self.assertEqual(len(shapes), 7)
        self.assertLessEqual(len(rows), 12)
        for row in rows:
            x, y, w, h = row["box"]
            self.assertTrue(0 <= x < x+w <= 1920 and 0 <= y < y+h <= 1080)

    def test_invalid_pixels_are_rejected_before_model_inference(self):
        def detector(crop):
            self.fail("invalid pixels must not reach the local model")

        with self.assertRaises(ValueError):
            self.wrapper(detector)(self.np.zeros((100, 200, 3), self.np.float32))

    def test_pinned_asset_provenance_and_fixed_policy_survive_provider_metadata(self):
        pinned = object.__new__(self.module.PinnedBoatDetector)
        pinned.kind, pinned.cv_version = "yolox", self.cv2.__version__
        wrapper = self.wrapper(pinned)
        provider = self.module.BoatIdentityProvider(detector=wrapper, number_reader=lambda crop: [])
        metadata = provider.metadata()
        self.assertEqual(metadata["detector"]["engine"], "OPENCV_DNN_CPU")
        self.assertEqual(metadata["detector"]["model_sha256"], self.module.MODEL_SPECS["yolox"]["sha256"])
        policy = metadata["detector"]["tiling"]
        self.assertEqual((policy["tile_size"], policy["stride"], policy["max_inference_calls"]),
                         (832, 624, 7))
        self.assertEqual(policy.get("boundary_duplicate_policy"),
                         "SAME_INTERNAL_EDGE_ONE_INPUT_PIXEL_AND_CLIPPED_IOU")
        self.assertEqual(policy.get("boundary_precision_input_side"), 640)
        self.assertEqual(policy.get("boundary_precision_input_pixels"), 1)
        self.assertEqual(policy.get("boundary_precision_native_rule"),
                         "MAX_SOURCE_SIDE_DIVIDED_BY_INPUT_SIDE")
        self.assertEqual(policy.get("boundary_precision_basis"), "PINNED_MODEL_PREPROCESSING")
        self.assertFalse(metadata["model_eligible"])
        self.assertFalse(metadata["identity_validated"])
        self.assertNotIn("/workspace/", json.dumps(metadata))

    def test_injected_component_cannot_claim_pinned_model_metadata(self):
        class Injected:
            kind = "nanodet"

            def __call__(self, crop):
                return []

            def metadata(self):
                return {"engine": "OPENCV_DNN_CPU", "model_sha256": "a"*64}

        metadata = self.wrapper(Injected()).metadata()
        self.assertEqual(metadata["engine"], "INJECTED_TILED_DETECTOR")
        self.assertNotIn("model_sha256", metadata)
        self.assertEqual(metadata["tiling"].get("boundary_precision_input_side"), 640)
        self.assertEqual(metadata["tiling"].get("boundary_precision_basis"), "INJECTED_DEFAULT_640_POLICY")

    def test_factory_defaults_stay_untiled_and_explicit_option_loads_no_extra_asset(self):
        detector = lambda crop: []
        reader = lambda crop: []
        with patch.object(self.module, "PinnedBoatDetector", return_value=detector), \
                patch.object(self.module, "LocalTesseractNumberReader", return_value=reader):
            baseline = self.module.create_local_identity_provider(
                model_path="local", tesseract_path="local", tessdata_path="local")
            tiled = self.module.create_local_identity_provider(
                model_path="local", tesseract_path="local", tessdata_path="local", tiled_hulls=True)
        self.assertIs(baseline.detector, detector)
        self.assertIsInstance(tiled.detector, self.module.TiledBoatDetector)
        self.assertIs(tiled.detector.detector, detector)
        self.assertIs(tiled.number_reader, reader)

    def test_configured_extractor_does_not_load_models_before_use(self):
        with patch.object(self.module, "PinnedBoatDetector", side_effect=AssertionError("unexpected model load")):
            extractor = self.module.make_local_identity_extractor(
                model_path="local", tesseract_path="local", tessdata_path="local", tiled_hulls=True)
        self.assertTrue(callable(extractor))


if __name__ == "__main__":
    unittest.main()
