"""Controlled original-pixel motion only; no OCR or real-field accuracy claim."""
from copy import deepcopy
from hashlib import sha256
import importlib
import importlib.util
import unittest
from unittest.mock import patch

try:
    flow_module = importlib.import_module('race_ai.boat_video_marker_flow')
except ModuleNotFoundError:
    flow_module = None

CV = importlib.util.find_spec('cv2') is not None and importlib.util.find_spec('numpy') is not None


@unittest.skipUnless(CV, 'optional OpenCV image dependencies unavailable')
class MarkerPixelFollowerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(flow_module, 'original-pixel marker follower is missing')
        import cv2
        import numpy as np
        self.cv, self.np = cv2, np
        self.cv.setNumThreads(1)
        self.frame = np.zeros((160, 240, 3), np.uint8)
        rng = np.random.default_rng(9281)
        self.frame[50:90, 70:120] = rng.integers(0, 256, (40, 50, 3), dtype=np.uint8)
        self.seed = dict(key='opaque-marker-A', box=[70, 50, 50, 40])

    def moved(self, dx, dy, *, frame=None):
        image = self.frame if frame is None else frame
        matrix = self.np.float32([[1, 0, dx], [0, 1, dy]])
        return self.cv.warpAffine(image, matrix, (image.shape[1], image.shape[0]))

    def call(self, follower, image, index, seeds=(), *, t=None, scene=0):
        return follower.update(image, list(seeds), t=index / 20 if t is None else t,
                               frame_index=index, scene=scene)

    def establish(self):
        follower = flow_module.MarkerPixelFollower()
        first = self.call(follower, self.frame, 0, [self.seed])
        self.assertEqual(first['tracked'][0]['status'], 'SEEDED')
        return follower, first

    def test_actual_translation_uses_pixels_and_has_no_number_or_world_claim(self):
        follower, seeded = self.establish()
        for index in range(1, 6):
            image = self.moved(index * 2, index)
            result = self.call(follower, image, index)
            self.assertEqual(result['schema_version'], 'RACE_AI_BOAT_MARKER_PIXEL_FLOW_V1')
            self.assertEqual(result['coordinate_space'], 'IMAGE_PX')
            self.assertEqual(result['frame_sha256'], sha256(image.tobytes()).hexdigest())
            self.assertFalse(result['model_eligible'])
            self.assertFalse(result['metric_positions_inferred'])
            self.assertEqual(result['lost_keys'], [])
            track = result['tracked'][0]
            self.assertEqual(track['key'], 'opaque-marker-A')
            self.assertEqual(track['status'], 'TRACKED')
            self.assertGreaterEqual(track['point_count'], 4)
            self.assertAlmostEqual(track['box'][0], 70 + index * 2, delta=.25)
            self.assertAlmostEqual(track['box'][1], 50 + index, delta=.25)
            self.assertAlmostEqual(track['median_displacement_px'][0], 2, delta=.2)
            self.assertAlmostEqual(track['median_displacement_px'][1], 1, delta=.2)
            self.assertLessEqual(track['median_forward_backward_error_px'], 1)
            self.assertLessEqual(track['displacement_dispersion_px'], 2)
            self.assertAlmostEqual(track['affine_area_ratio'], 1, delta=.05)
            self.assertNotIn('number', track)
            self.assertNotIn('world_position', track)
            self.assertNotIn('confidence', track)
        self.assertEqual(seeded['tracked'][0]['previous_frame_sha256'], None)

    def test_blank_seed_has_no_points_and_does_not_create_track(self):
        follower = flow_module.MarkerPixelFollower()
        result = self.call(follower, self.np.zeros_like(self.frame), 0, [self.seed])
        self.assertEqual(result['tracked'], [])
        self.assertEqual(result['lost_keys'], ['opaque-marker-A'])
        self.assertEqual(result['loss_reasons']['opaque-marker-A'], 'INSUFFICIENT_TEXTURE')

    def test_four_spread_actual_feature_points_are_required(self):
        for count in (1, 2, 3, 4):
            with self.subTest(count=count):
                image = self.np.zeros_like(self.frame)
                for x, y in [(78, 58), (110, 58), (78, 82), (110, 82)][:count]:
                    image[y, x] = 255
                follower = flow_module.MarkerPixelFollower()
                result = self.call(follower, image, 0, [self.seed])
                if count < 4:
                    self.assertEqual(result['tracked'], [])
                else:
                    self.assertEqual(result['tracked'][0]['point_count'], 4)
                    tracked = self.call(follower, self.moved(2, 1, frame=image), 1)
                    self.assertEqual(tracked['tracked'][0]['point_count'], 4)
                    self.assertAlmostEqual(tracked['tracked'][0]['box'][0], 72, delta=.25)

    def test_clustered_texture_cannot_support_an_entire_marker_box(self):
        image = self.np.zeros_like(self.frame)
        image[52:58, 72:78] = self.frame[50:56, 70:76]
        follower = flow_module.MarkerPixelFollower()
        result = self.call(follower, image, 0, [self.seed])
        self.assertEqual(result['tracked'], [])
        self.assertEqual(result['loss_reasons']['opaque-marker-A'], 'INSUFFICIENT_TEXTURE')

    def test_significant_partial_occlusion_fails_closed_instead_of_coasting(self):
        follower, _ = self.establish()
        image = self.moved(2, 1)
        image[51:91, 72:92] = 0
        result = self.call(follower, image, 1)
        self.assertEqual(result['tracked'], [])
        self.assertEqual(result['lost_keys'], ['opaque-marker-A'])

    def test_disappearance_is_lost_and_reappearance_does_not_predict_or_reacquire(self):
        follower, _ = self.establish()
        absent = self.call(follower, self.np.zeros_like(self.frame), 1)
        self.assertEqual(absent['tracked'], [])
        self.assertEqual(absent['lost_keys'], ['opaque-marker-A'])
        reappeared = self.call(follower, self.moved(4, 2), 2)
        self.assertEqual(reappeared['tracked'], [])
        seeded = self.call(follower, self.moved(6, 3), 3,
                           [dict(key=self.seed['key'], box=[76, 53, 50, 40])])
        self.assertEqual(seeded['tracked'][0]['status'], 'SEEDED')

    def test_scene_shape_and_half_second_gap_reset_without_prediction(self):
        for kind in ('scene', 'shape', 'gap'):
            with self.subTest(kind=kind):
                follower, _ = self.establish()
                image = self.frame[:150] if kind == 'shape' else self.moved(2, 1)
                result = self.call(follower, image, 1, t=.5 if kind == 'gap' else .05,
                                   scene=1 if kind == 'scene' else 0)
                self.assertEqual(result['tracked'], [])
                self.assertEqual(result['lost_keys'], ['opaque-marker-A'])
                self.assertIn(result['loss_reasons']['opaque-marker-A'],
                              ('SCENE_CHANGE', 'FRAME_SIZE_CHANGE', 'TIME_GAP'))

    def test_decimal_half_second_boundary_is_exact(self):
        follower = flow_module.MarkerPixelFollower()
        self.call(follower, self.frame, 0, [self.seed], t=.2)
        result = self.call(follower, self.moved(1, 0), 1, t=.7)
        self.assertEqual(result['tracked'], [])
        self.assertEqual(result['loss_reasons']['opaque-marker-A'], 'TIME_GAP')

    def test_valid_explicit_reseed_reports_new_seed_not_inferred_continuity(self):
        follower, _ = self.establish()
        image = self.moved(5, 3)
        new = dict(key=self.seed['key'], box=[75, 53, 50, 40])
        result = self.call(follower, image, 1, [new])
        row = result['tracked'][0]
        self.assertEqual(row['status'], 'SEEDED')
        self.assertIsNone(row['previous_frame_sha256'])
        self.assertIsNone(row['median_displacement_px'])
        self.assertTrue(row['explicit_seed'])

    def test_textureless_reseed_drops_old_track_instead_of_silently_following(self):
        follower, _ = self.establish()
        result = self.call(follower, self.moved(2, 1), 1,
                           [dict(key=self.seed['key'], box=[10, 10, 30, 30])])
        self.assertEqual(result['tracked'], [])
        self.assertEqual(result['lost_keys'], ['opaque-marker-A'])

    def test_border_escape_is_lost_without_clipping_box(self):
        image = self.np.zeros_like(self.frame)
        image[50:90, 188:238] = self.frame[50:90, 70:120]
        follower = flow_module.MarkerPixelFollower()
        self.call(follower, image, 0, [dict(key='edge', box=[188, 50, 50, 40])])
        result = self.call(follower, self.moved(4, 0, frame=image), 1)
        self.assertEqual(result['tracked'], [])
        self.assertEqual(result['lost_keys'], ['edge'])

    def test_incoherent_pixel_deformation_and_scale_change_are_not_translation(self):
        for kind in ('random', 'scale'):
            with self.subTest(kind=kind):
                follower, _ = self.establish()
                if kind == 'random':
                    image = self.np.random.default_rng(455).integers(0, 256, self.frame.shape, dtype=self.np.uint8)
                else:
                    matrix = self.cv.getRotationMatrix2D((95, 70), 0, 1.8)
                    image = self.cv.warpAffine(self.frame, matrix, (240, 160))
                result = self.call(follower, image, 1)
                self.assertEqual(result['tracked'], [])
                self.assertEqual(result['lost_keys'], ['opaque-marker-A'])

    def test_two_keys_follow_separate_actual_pixel_displacements(self):
        image = self.frame.copy()
        image[105:135, 155:195] = self.np.random.default_rng(716).integers(0, 256, (30, 40, 3), dtype=self.np.uint8)
        follower = flow_module.MarkerPixelFollower()
        self.call(follower, image, 0, [self.seed, dict(key='other', box=[155, 105, 40, 30])])
        next_image = self.np.zeros_like(image)
        next_image[51:91, 72:122] = image[50:90, 70:120]
        next_image[103:133, 152:192] = image[105:135, 155:195]
        result = self.call(follower, next_image, 1)
        rows = {r['key']: r for r in result['tracked']}
        self.assertEqual(set(rows), {'opaque-marker-A', 'other'})
        self.assertAlmostEqual(rows['opaque-marker-A']['box'][0], 72, delta=.25)
        self.assertAlmostEqual(rows['other']['box'][0], 152, delta=.25)

    def test_identical_pixels_are_measured_zero_displacement_not_numeric_evidence(self):
        follower, _ = self.establish()
        result = self.call(follower, self.frame.copy(), 1)
        self.assertEqual(result['tracked'][0]['status'], 'TRACKED')
        self.assertEqual(result['tracked'][0]['median_displacement_px'], [0., 0.])
        self.assertNotIn('observations', result['tracked'][0])

    def test_inputs_and_outputs_cannot_rewrite_internal_points_or_boxes(self):
        follower = flow_module.MarkerPixelFollower()
        original = self.frame.copy()
        seed = deepcopy(self.seed)
        result = self.call(follower, original, 0, [seed])
        seed['box'][0] = 0
        result['tracked'][0]['box'][0] = 0
        original[:] = 0
        row = self.call(follower, self.moved(2, 1), 1)['tracked'][0]
        self.assertAlmostEqual(row['box'][0], 72, delta=.25)

    def test_invalid_update_is_atomic_and_can_be_retried_at_same_frame(self):
        bad_arguments = [
            {'seeds': [dict(key='a', box=[1, 1, 5, 5]), dict(key='a', box=[2, 2, 5, 5])]},
            {'seeds': [dict(key='a', box=[-1, 0, 5, 5])]},
            {'seeds': [dict(key='a', box=[0, 0, 500, 5])]},
            {'seeds': [dict(key='a', box=[0, 0, float('nan'), 5])]},
            {'seeds': [dict(key='', box=[0, 0, 5, 5])]},
            {'seeds': [dict(key=1, box=[0, 0, 5, 5])]},
            {'seeds': [dict(key='a', box=[0, 0, 5, 5], number=1)]},
            {'t': float('nan')}, {'t': 0}, {'t': True},
            {'frame_index': 0}, {'frame_index': True}, {'scene': -1},
            {'frame': self.frame.astype(self.np.float32)}, {'frame': self.frame[:, :, 0]},
        ]
        for override in bad_arguments:
            with self.subTest(override=str(override.keys())):
                follower, _ = self.establish()
                kwargs = dict(frame=self.moved(2, 1), seeds=[], t=.05, frame_index=1, scene=0)
                kwargs.update(override)
                with self.assertRaises(ValueError):
                    follower.update(**kwargs)
                result = self.call(follower, self.moved(2, 1), 1)
                self.assertEqual(result['tracked'][0]['status'], 'TRACKED')

    def test_parameters_reject_invalid_or_weakened_gap(self):
        for value in (0, -.1, .51, True, float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                flow_module.MarkerPixelFollower(max_gap_seconds=value)

    def test_pixel_copy_failure_does_not_publish_partial_track_state(self):
        follower, _ = self.establish()
        image = self.moved(2, 1)
        class UncopyableGray(self.np.ndarray):
            def copy(self, *args, **kwargs):
                raise MemoryError('controlled grayscale allocation failure')
        gray = self.cv.cvtColor(image, self.cv.COLOR_BGR2GRAY).view(UncopyableGray)
        old_tracks, old_gray = follower._tracks, follower._gray
        with patch.object(self.cv, 'cvtColor', return_value=gray), self.assertRaises(MemoryError):
            self.call(follower, image, 1)
        self.assertIs(follower._tracks, old_tracks)
        self.assertIs(follower._gray, old_gray)
        self.assertEqual(follower._time, 0.)
        result = self.call(follower, image, 1)
        self.assertAlmostEqual(result['tracked'][0]['box'][0], 72, delta=.25)

    def test_live_state_bound_is_aggregate_and_rejection_is_atomic(self):
        follower = flow_module.MarkerPixelFollower()
        seeds = [dict(key='key-%04d' % i, box=list(self.seed['box'])) for i in range(1000)]
        self.call(follower, self.frame, 0, seeds)
        with self.assertRaises(ValueError):
            self.call(follower, self.moved(2, 1), 1, [dict(key='extra', box=list(self.seed['box']))])
        self.assertEqual(len(follower._tracks), 1000)
        self.assertEqual(follower._time, 0.)
        # A caller-declared cut clears the old physical state, so its sole new
        # seed does not count against 1000 already discarded old keys.
        result = self.call(follower, self.frame, 1, [dict(key='extra', box=list(self.seed['box']))], scene=1)
        self.assertEqual([r['key'] for r in result['tracked']], ['extra'])


if __name__ == '__main__':
    unittest.main()
