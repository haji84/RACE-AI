"""Actual MPEG-TS integration; image corrections never imply boat performance."""
from datetime import datetime
import json
import unittest
from unittest.mock import patch

from race_ai.core import SourceError
from race_ai.exhibition_video_source import SourceResponse
from tests.test_exhibition_video_source import run, program, NOW
from tests.test_exhibition_video_decode import synthetic_ts, master, child


class CameraDecodeIntegrationTests(unittest.TestCase):
    def analyze(self, *, playlist=None, encoded=None, **kwargs):
        from race_ai.exhibition_video_decode import analyze_exhibition
        descriptor, lease = run()
        raw = encoded or synthetic_ts()
        def fetch(url, **options):
            body, mime = (master().encode(), 'application/vnd.apple.mpegurl') if 'manifest.streaks.jp/' in url else (
                ((playlist or child()).encode(), 'application/x-mpegURL') if 'variants.streaks.jp/' in url else (raw, 'video/mp2t'))
            return SourceResponse(200, url, mime, body)
        return analyze_exhibition(descriptor, lease, program(), fetch=fetch,
                                  clock=lambda: datetime.fromisoformat(NOW), sample_interval=.5, **kwargs)

    def test_default_preserves_v1_without_camera_claims(self):
        result = self.analyze()
        self.assertEqual(result['analysis_version'], 'transient-hls-color-candidates/v1')
        self.assertNotIn('camera_motion', result)
        self.assertTrue(result['candidate_tracks'])
        self.assertNotIn('camera_corrected_dx_pixels', result['candidate_tracks'][0])

    def test_v2_flat_background_has_no_numeric_correction(self):
        result = self.analyze(camera_motion=True)
        self.assertEqual(result['analysis_version'], 'transient-hls-color-candidates/v2')
        self.assertGreater(result['camera_motion']['attempted_pairs'], 0)
        self.assertEqual(result['camera_motion']['accepted_pairs'], 0)
        self.assertTrue(result['candidate_tracks'])
        for track in result['candidate_tracks']:
            self.assertIsNone(track['camera_corrected_dx_pixels'])
            self.assertIsNone(track['camera_corrected_dy_pixels'])
        self.assertEqual(result['boat_features'], [])
        self.assertEqual(result['boat_identity'], 'UNVERIFIED')
        self.assertEqual(result['camera_calibration'], 'UNVERIFIED')
        self.assertFalse(result['prediction_eligible'])
        self.assertNotIn('https:', json.dumps(result))

    def test_v2_accepted_affine_and_both_frame_exclusions(self):
        import cv2
        import numpy as np
        from race_ai.video_camera_motion import estimate_camera_motion
        pixels = np.random.default_rng(7).integers(20, 235, (96, 160), dtype=np.uint8)
        pixels = cv2.GaussianBlur(pixels, (5, 5), .8)
        previous = np.repeat(pixels[:, :, None], 3, axis=2)
        matrix = cv2.getRotationMatrix2D((80, 48), 3, 1)
        matrix[0, 2] += 3
        current = cv2.warpAffine(previous, matrix, (160, 96))
        motion = estimate_camera_motion(previous, current)
        self.assertTrue(motion['accepted'], motion)
        with patch('race_ai.video_camera_motion.estimate_camera_motion', return_value=motion) as estimator:
            result = self.analyze(camera_motion=True)
        self.assertGreater(estimator.call_count, 0)
        for call in estimator.call_args_list:
            self.assertTrue(call.kwargs['previous_exclusions'])
            self.assertTrue(call.kwargs['current_exclusions'])
        self.assertEqual(result['camera_motion']['accepted_pairs'], estimator.call_count)
        track = max(result['candidate_tracks'], key=lambda t: t['samples'])
        self.assertEqual(track['camera_corrected_transitions'], track['samples'] - 1)
        self.assertIsInstance(track['camera_corrected_dx_pixels'], float)
        self.assertNotAlmostEqual(track['camera_corrected_dx_pixels'], track['dx_pixels'])
        self.assertNotEqual(track['camera_corrected_dy_pixels'], 0)
        self.assertFalse(result['prediction_eligible'])

    def test_v2_option_is_strict_before_media_fetch(self):
        from race_ai.exhibition_video_decode import analyze_exhibition
        for invalid in (1, 'true', None):
            descriptor, lease = run()
            with self.subTest(invalid=invalid), patch('race_ai.exhibition_video_decode.bounded_fetch') as fetch:
                with self.assertRaises(SourceError):
                    analyze_exhibition(descriptor, lease, program(), camera_motion=invalid,
                                       clock=lambda: datetime.fromisoformat(NOW))
                fetch.assert_not_called()

    def test_camera_detected_scene_change_resets_even_below_thumbnail_threshold(self):
        # Independent reviewer reproduced a scene change with thumbnail MAD31.59.
        # Its explicit camera rejection must reset associations even below35.
        with patch('race_ai.video_camera_motion.estimate_camera_motion',
                   return_value={'accepted': False, 'status': 'UNVERIFIED_SCENE_CHANGE'}):
            result = self.analyze(camera_motion=True)
        self.assertGreater(result['camera_motion']['attempted_pairs'], 0)
        self.assertEqual(result['candidate_tracks'], [])

    def test_segment_boundaries_reset_camera_pairs_and_associations(self):
        extended = child()
        segment = extended.split('#EXTINF:', 1)[1].split('#EXT-X-ENDLIST')[0]
        extended = extended.replace('#EXT-X-ENDLIST', '#EXTINF:' + segment.replace('_17.ts', '_18.ts') + '#EXT-X-ENDLIST')
        result = self.analyze(camera_motion=True, playlist=extended)
        self.assertEqual(result['segments_decoded'], 2)
        self.assertEqual(result['camera_motion']['attempted_pairs'], result['frames_sampled'] - 2)
        self.assertEqual({track['segment'] for track in result['candidate_tracks']}, {0, 1})

    def test_size_change_resets_even_when_new_frame_is_below_camera_minimum(self):
        import av
        import numpy as np
        from fractions import Fraction
        from types import SimpleNamespace
        frames = []
        for index, (width, height) in enumerate(((160, 96), (80, 48))):
            pixels = np.full((height, width, 3), [40, 60, 60], dtype=np.uint8)
            pixels[20:30, 10:30] = [0, 0, 255]
            frame = av.VideoFrame.from_ndarray(pixels, format='bgr24')
            frame.pts, frame.time_base = index, Fraction(1, 2)
            frames.append(frame)
        class Container:
            streams = SimpleNamespace(video=[object()])
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def decode(self, **kwargs): return iter(frames)
        with patch('av.open', return_value=Container()):
            result = self.analyze(camera_motion=True, encoded=b'SYNTHETIC_DECODER_INPUT')
        self.assertEqual(result['candidate_tracks'], [])
        self.assertEqual(result['camera_motion']['attempted_pairs'], 0)


if __name__ == '__main__':
    unittest.main()
