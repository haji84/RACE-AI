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
        self.assertFalse(metadata["model_eligible"])
        self.assertFalse(metadata["identity_validated"])
        self.assertNotIn("/workspace/", json.dumps(metadata))

    def test_injected_component_cannot_claim_pinned_model_metadata(self):
        class Injected:
            def __call__(self, crop):
                return []

            def metadata(self):
                return {"engine": "OPENCV_DNN_CPU", "model_sha256": "a"*64}

        metadata = self.wrapper(Injected()).metadata()
        self.assertEqual(metadata["engine"], "INJECTED_TILED_DETECTOR")
        self.assertNotIn("model_sha256", metadata)

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
