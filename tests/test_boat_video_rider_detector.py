"""Person part geometry and provenance; no six-boat accuracy claim."""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec('cv2'), 'optional video dependencies')
class RiderDetectorTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        from race_ai import boat_video_rider_detector as module
        self.np, self.m = np, module

    def head(self, *, person=.8, boat=.2, obj=.8, index=0):
        x = self.np.zeros((1, 8400, 85), self.np.float32)
        x[0, index, :4] = [4., 4., 1., 1.]
        x[0, index, 4] = obj
        x[0, index, 5] = person
        x[0, index, 13] = boat
        return x

    def decode(self, x):
        return self.m.decode_yolox_person_regions(x, width=640, height=640)

    def test_person_head_uses_class_zero_not_boat(self):
        from race_ai.boat_video_identity import decode_yolox_regions
        head = self.head()
        self.assertEqual(decode_yolox_regions(head, width=640, height=640), [])
        result = self.decode(head)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]['score'], .64, places=6)
        self.assertEqual(len(result[0]['box']), 4)

    def test_boat_winner_is_never_relabelled_person(self):
        self.assertEqual(self.decode(self.head(person=.8, boat=.9)), [])

    def test_objectness_product_and_inclusive_fixed_threshold(self):
        self.assertEqual(self.decode(self.head(person=.8, obj=.6)), [])
        self.assertEqual(len(self.decode(self.head(person=1., obj=.5))), 1)

    def test_raw_argmax_tie_preserves_class_zero_order(self):
        self.assertEqual(len(self.decode(self.head(person=.8, boat=.8))), 1)

    def test_distinct_candidates_are_not_forced_to_six(self):
        head = self.head(index=0)
        for index in (20, 40):
            head[0, index] = head[0, 0]
        self.assertEqual(len(self.decode(head)), 3)

    def test_tensor_invalid_values_rejected(self):
        for bad in (float('nan'), float('inf'), -1., 1.1):
            with self.subTest(bad=bad):
                head = self.head()
                head[0, 0, 5] = bad
                with self.assertRaises(ValueError):
                    self.decode(head)

    def test_selected_unsafe_geometry_rejected(self):
        head = self.head()
        head[0, 0, 2] = 33.
        with self.assertRaises(ValueError):
            self.decode(head)

    def test_input_head_not_mutated(self):
        head = self.head()
        before = head.tobytes()
        self.decode(head)
        self.assertEqual(head.tobytes(), before)

    def test_exact_pinned_model_required_without_downloading(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'not-a-model.onnx'
            path.write_bytes(b'not a pinned model')
            with self.assertRaises(ValueError):
                self.m.PinnedRiderPartDetector(model_path=str(path))

    def injected(self, *, tiled=False):
        detector = object.__new__(self.m.PinnedRiderPartDetector)
        detector._tiled = tiled
        class Local:
            def metadata(self):
                return {'engine': 'TEST_NATIVE_DEPENDENCY', 'class_scope': 'GENERIC_COCO_BOAT_CANDIDATE',
                        'model_sha256': 'c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063'}
        detector._model = Local()
        return detector

    def test_envelope_uses_actual_bgr_hash_and_part_type(self):
        detector = self.injected()
        frame = self.np.zeros((90, 120, 3), self.np.uint8)
        with patch.object(detector, '_infer', return_value=[{'box': [2., 3., 10., 11.], 'score': .8}]):
            result = detector(frame)
        self.assertEqual(result['schema_version'], 'RACE_AI_RIDER_PART_DETECTIONS_V1')
        self.assertEqual(result['frame_sha256'], hashlib.sha256(frame.tobytes()).hexdigest())
        self.assertEqual(result['coordinate_space'], 'IMAGE_PX')
        self.assertEqual(result['semantic_type'], 'RIDER_PART_TYPED')
        self.assertEqual(result['detections'], [{'box': [2., 3., 10., 11.], 'score': .8,
                                               'semantic_type': 'RIDER_PART_TYPED', 'coco_class_id': 0}])
        self.assertFalse(result['model_eligible'])
        self.assertFalse(result['identity_validated'])
        self.assertEqual(result['engine']['class_scope'], 'GENERIC_COCO_PERSON_PART_CANDIDATE')
        self.assertNotIn('number', result['detections'][0])

    def test_fixed_native_tiles_full_frame_and_empty_result(self):
        detector = self.injected(tiled=True)
        frame = self.np.zeros((1080, 1920, 3), self.np.uint8)
        with patch.object(detector, '_infer', return_value=[]) as infer:
            result = detector(frame)
        self.assertEqual(infer.call_count, 7)
        self.assertEqual(result['detections'], [])
        self.assertEqual(result['engine']['tiling']['max_candidates'], 12)

    def test_source_image_isolated_from_inference_dependency(self):
        detector = self.injected()
        frame = self.np.zeros((90, 120, 3), self.np.uint8)
        def infer(crop):
            crop[:] = 255
            return []
        with patch.object(detector, '_infer', side_effect=infer):
            detector(frame)
        self.assertFalse(frame.any())

    def test_tiling_flag_requires_bool(self):
        for flag in (0, 1, 'yes', None):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                self.m.PinnedRiderPartDetector(model_path='/not-opened', tiled=flag)


if __name__ == '__main__':
    unittest.main()
