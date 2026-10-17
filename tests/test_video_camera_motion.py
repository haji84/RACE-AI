"""Synthetic image-space camera estimates: no real video or boat identity."""
from copy import deepcopy
import importlib
import json
import math
import os
import unittest
from unittest.mock import patch


class CameraMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import cv2
            import numpy as np
        except (ImportError, OSError):
            if os.environ.get('RACE_AI_REQUIRE_VIDEO_RUNTIME') == '1':
                raise AssertionError('required camera-motion runtime unavailable') from None
            raise unittest.SkipTest('optional video runtime unavailable') from None
        cls.cv2, cls.np = cv2, np

    def module(self):
        try:
            return importlib.import_module('race_ai.video_camera_motion')
        except ModuleNotFoundError:
            self.fail('bounded camera-motion contract is not implemented')

    def texture(self, seed=7):
        pixels = self.np.random.default_rng(seed).integers(20, 235, (240, 320), dtype=self.np.uint8)
        pixels = self.cv2.GaussianBlur(pixels, (5, 5), .8)
        return self.np.repeat(pixels[:, :, None], 3, axis=2)

    def pair(self, angle=0):
        background = self.texture()
        radians = math.radians(angle)
        cosine, sine = math.cos(radians), math.sin(radians)
        matrix = self.np.array([[cosine, -sine, 5.0], [sine, cosine, -3.0]], dtype=float)
        current = self.cv2.warpAffine(background, matrix, (320, 240))
        previous = background.copy()
        foreground = self.texture(11)[50:130, 100:180]
        previous[70:150, 110:190] = foreground
        current[95:175, 150:230] = foreground
        return previous, current, matrix

    def estimate(self, angle=0):
        previous, current, expected = self.pair(angle)
        result = self.module().estimate_camera_motion(previous, current,
            previous_exclusions=[(110, 70, 80, 80)], current_exclusions=[(150, 95, 80, 80)])
        return result, expected

    def assert_unverified(self, result, status=None):
        self.assertFalse(result['accepted'])
        self.assertTrue(result['status'].startswith('UNVERIFIED_'))
        if status:
            self.assertEqual(result['status'], status)
        self.assertIsNone(result['affine_previous_to_current'])
        self.assertEqual(result['boat_identity'], 'UNVERIFIED')
        self.assertEqual(result['world_calibration'], 'UNVERIFIED')
        self.assertFalse(result['prediction_eligible'])
        json.dumps(result, allow_nan=False)

    def test_known_translation_ignores_independently_moving_excluded_foreground(self):
        result, expected = self.estimate()
        self.assertTrue(result['accepted'], result)
        self.np.testing.assert_allclose(result['affine_previous_to_current'], expected, atol=.15)
        self.assertGreaterEqual(result['inlier_count'], 20)
        self.assertGreaterEqual(result['inlier_ratio'], .75)
        self.assertGreaterEqual(result['spatial_coverage'], .20)
        self.assertLessEqual(result['reprojection_rmse_pixels'], 1.0)
        self.assertEqual(result['metric_units'], 'CAMERA_ESTIMATED_PIXELS')
        self.assertEqual(result['boat_identity'], 'UNVERIFIED')
        self.assertEqual(result['world_calibration'], 'UNVERIFIED')
        self.assertFalse(result['prediction_eligible'])
        self.assertLess(len(json.dumps(result, allow_nan=False)), 2000)

    def test_known_rotation_corrects_point_using_full_affine_not_translation_only(self):
        result, expected = self.estimate(angle=3)
        self.assertTrue(result['accepted'], result)
        self.np.testing.assert_allclose(result['affine_previous_to_current'], expected, atol=.20)
        source = (80.0, 180.0)
        destination = expected @ self.np.array([*source, 1.0]) + [4.0, -2.0]
        residual = self.module().candidate_point_residual(result, source, tuple(destination))
        self.assertTrue(residual['accepted'], residual)
        self.assertAlmostEqual(residual['residual_dx_pixels'], 4, delta=.15)
        self.assertAlmostEqual(residual['residual_dy_pixels'], -2, delta=.15)
        self.assertAlmostEqual(residual['residual_distance_pixels'], math.sqrt(20), delta=.2)
        self.assertEqual(residual['metric_units'], 'CAMERA_ESTIMATED_PIXELS')
        self.assertFalse(residual['prediction_eligible'])

    def test_zoomed_exclusion_overlap_is_normalized_in_current_frame(self):
        previous = self.texture()
        expected = self.np.array([[1.05, 0., -8.], [0., 1.05, -6.]])
        current = self.cv2.warpAffine(previous, expected, (320, 240))
        result = self.module().estimate_camera_motion(previous, current,
                                                     previous_exclusions=[(0, 0, 100, 100)])
        self.assertTrue(result['accepted'], result)
        self.assertLessEqual(result['background_overlap_ratio'], 1)
        residual = self.module().candidate_point_residual(result, (100, 100), (100, 100))
        self.assertTrue(residual['accepted'], residual)
        self.assertAlmostEqual(residual['residual_dx_pixels'], 3, delta=.15)
        self.assertAlmostEqual(residual['residual_dy_pixels'], 1, delta=.15)

    def test_flat_frames_do_not_substitute_zero_motion(self):
        frame = self.np.zeros((240, 320, 3), dtype=self.np.uint8)
        result = self.module().estimate_camera_motion(frame, frame)
        self.assert_unverified(result, 'UNVERIFIED_INSUFFICIENT_FEATURES')
        residual = self.module().candidate_point_residual(result, (20, 20), (25, 25))
        self.assertFalse(residual['accepted'])
        self.assertIsNone(residual['residual_dx_pixels'])

    def test_invalid_shape_dtype_size_and_missing_frames_fail_closed(self):
        frame = self.texture()
        bads = [None, [], frame[:, :, 0], frame[:, :, :2], frame.astype(float),
                self.np.full((240, 320, 3), self.np.nan), frame[:32],
                self.np.zeros((721, 1280, 3), dtype=self.np.uint8)]
        for bad in bads:
            with self.subTest(shape=getattr(bad, 'shape', None)):
                self.assert_unverified(self.module().estimate_camera_motion(bad, frame),
                                       'UNVERIFIED_INVALID_FRAME')
        self.assert_unverified(self.module().estimate_camera_motion(frame, frame[:-1]),
                               'UNVERIFIED_SIZE_CHANGE')

    def test_local_texture_and_fully_excluded_background_lack_spatial_support(self):
        frame = self.np.zeros((240, 320, 3), dtype=self.np.uint8)
        frame[80:160, 120:200] = self.texture()[80:160, 120:200]
        self.assert_unverified(self.module().estimate_camera_motion(frame, frame),
                               'UNVERIFIED_SPATIAL_SUPPORT')
        frame = self.texture()
        self.assert_unverified(self.module().estimate_camera_motion(frame, frame,
                               previous_exclusions=[(0, 0, 320, 240)]),
                               'UNVERIFIED_INSUFFICIENT_FEATURES')
        self.assert_unverified(self.module().estimate_camera_motion(frame, frame,
                               current_exclusions=[(0, 0, 320, 240)]),
                               'UNVERIFIED_INSUFFICIENT_TRACKS')

    def test_scene_cut_has_no_camera_transform(self):
        previous = self.texture()
        current = self.texture(17)
        self.assert_unverified(self.module().estimate_camera_motion(previous, current))
        dark = previous // 3
        bright = current // 3 + 170
        self.assert_unverified(self.module().estimate_camera_motion(dark, bright),
                               'UNVERIFIED_SCENE_CHANGE')

    def test_invalid_or_excessive_exclusion_regions_are_not_silently_ignored(self):
        frame = self.texture()
        bads = [[(-1, 20, 30, 30)], [(20, 20, 0, 30)], [(300, 20, 30, 30)],
                [(20, 20, self.np.nan, 30)], [(20, 20, 30)], [(20, 20, 30, 30)] * 65,
                None, 'arbitrary']
        for bad in bads:
            with self.subTest(exclusions=bad):
                self.assert_unverified(self.module().estimate_camera_motion(frame, frame,
                                       current_exclusions=bad), 'UNVERIFIED_INVALID_EXCLUSIONS')

    def test_inlier_gate_rejects_small_reported_consensus(self):
        frame = self.texture()
        def small_consensus(source, destination, **kwargs):
            mask = self.np.zeros((len(source), 1), dtype=self.np.uint8)
            mask[:8] = 1
            return self.np.array([[1., 0., 0.], [0., 1., 0.]]), mask
        with patch.object(self.cv2, 'estimateAffinePartial2D', side_effect=small_consensus):
            result = self.module().estimate_camera_motion(frame, frame)
        self.assert_unverified(result, 'UNVERIFIED_INSUFFICIENT_INLIERS')
        self.assertEqual(result['inlier_count'], 8)

    def test_inconsistent_background_flow_has_no_dominant_camera_consensus(self):
        previous = self.texture()
        left = self.cv2.warpAffine(previous, self.np.array([[1., 0., 4.], [0., 1., 0.]]), (320, 240))
        right = self.cv2.warpAffine(previous, self.np.array([[1., 0., -4.], [0., 1., 0.]]), (320, 240))
        current = left.copy(); current[:, 160:] = right[:, 160:]
        self.assert_unverified(self.module().estimate_camera_motion(previous, current),
                               'UNVERIFIED_INSUFFICIENT_INLIERS')

    def test_reported_inliers_do_not_bypass_reprojection_gate(self):
        frame = self.texture()
        with patch.object(self.cv2, 'estimateAffinePartial2D',
                side_effect=lambda source, destination, **kwargs:
                (self.np.array([[1., 0., 1.1], [0., 1., 0.]]),
                 self.np.ones((len(source), 1), dtype=self.np.uint8))):
            result = self.module().estimate_camera_motion(frame, frame)
        self.assert_unverified(result, 'UNVERIFIED_REPROJECTION_ERROR')

    def test_nonfinite_or_unreasonable_affine_outputs_are_rejected(self):
        frame = self.texture()
        matrices = [[[self.np.nan, 0., 0.], [0., 1., 0.]],
                    [[1., 0., self.np.inf], [0., 1., 0.]],
                    [[1., 0., 500.], [0., 1., 0.]],
                    [[1.3, 0., 0.], [0., 1.3, 0.]],
                    [[1., .3, 0.], [0., 1., 0.]],
                    [[-1., 0., 0.], [0., 1., 0.]], [[1., 0.], [0., 1.]]]
        for matrix in matrices:
            with self.subTest(matrix=matrix):
                with patch.object(self.cv2, 'estimateAffinePartial2D',
                        side_effect=lambda source, destination, **kwargs:
                        (self.np.array(matrix), self.np.ones((len(source), 1), dtype=self.np.uint8))):
                    result = self.module().estimate_camera_motion(frame, frame)
                self.assert_unverified(result, 'UNVERIFIED_INVALID_TRANSFORM')

    def test_residual_helper_rejects_tampered_acceptance_matrix_and_points(self):
        valid, _ = self.estimate()
        self.assertTrue(valid['accepted'], valid)
        tampered = []
        for key, value in [('status', 'UNVERIFIED_SCENE_CHANGE'), ('accepted', False),
                           ('affine_previous_to_current', [[1, 0], [0, 1]]),
                           ('affine_previous_to_current', [[1, 0, float('nan')], [0, 1, 0]]),
                           ('affine_previous_to_current', [[1, 0, 500], [0, 1, 0]]),
                           ('inlier_count', 2), ('inlier_ratio', .1), ('spatial_coverage', .01),
                           ('reprojection_rmse_pixels', 99), ('photometric_mean_error', float('nan')),
                           ('prediction_eligible', True), ('prediction_eligible', 0),
                           ('world_calibration', 'VERIFIED')]:
            value_result = deepcopy(valid); value_result[key] = value; tampered.append(value_result)
        tampered.extend([None, {}, 'ACCEPTED'])
        for result in tampered:
            with self.subTest(result=result):
                residual = self.module().candidate_point_residual(result, (20, 20), (25, 25))
                self.assertFalse(residual['accepted'])
                self.assertIsNone(residual['residual_distance_pixels'])
                json.dumps(residual, allow_nan=False)
        for point in [(float('nan'), 20), (-1, 20), (320, 20), (20,), (True, 20), (10**400, 20)]:
            with self.subTest(point=point):
                residual = self.module().candidate_point_residual(valid, point, (25, 25))
                self.assertFalse(residual['accepted'])
                self.assertIsNone(residual['residual_dx_pixels'])


if __name__ == '__main__':
    unittest.main()
