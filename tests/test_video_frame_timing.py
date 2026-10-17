"""Exact decoded PTS quality, independently of source/physical clocks and boat metrics."""
from fractions import Fraction
import importlib
import json
import unittest
from unittest.mock import patch


class FrameTimingTests(unittest.TestCase):
    def assessor(self, duration=2):
        try:
            module = importlib.import_module('race_ai.video_frame_timing')
        except ModuleNotFoundError:
            self.fail('streaming decoded-frame timing assessor is missing')
        return module.FrameTimingQuality(duration)

    def assess(self, points, duration=2):
        item = self.assessor(duration)
        for pts, base in points:
            item.observe(pts, base)
        return item.finish()

    def assert_unusable(self, result, status):
        self.assertEqual(result['status'], status)
        self.assertFalse(result['relative_pts_consistent'])
        for key in ('first_pts', 'last_pts', 'time_base', 'relative_span', 'minimum_interval', 'maximum_interval',
                    'pts_sha256'):
            self.assertIsNone(result[key])
        self.assertFalse(result['physical_exhibition_time_verified'])
        self.assertFalse(result['independent_clock_verified'])
        self.assertFalse(result['source_frame_completeness_verified'])
        self.assertFalse(result['prediction_eligible'])
        self.assertEqual(result['wall_clock_mapping'], 'NOT_COMPUTED_FIRST_MEDIA_SAMPLE_ALIGNMENT_UNVERIFIED')

    def test_exact_rational_intervals_and_relative_span_without_wall_time(self):
        result = self.assess([(9000, Fraction(1, 90000)), (12003, Fraction(1, 90000)), (15006, Fraction(1, 90000))])
        self.assertEqual(result['status'], 'RELATIVE_PTS_CONSISTENT')
        self.assertTrue(result['relative_pts_consistent'])
        self.assertEqual(result['frames_observed'], 3)
        self.assertEqual(result['time_base'], [1, 90000])
        self.assertEqual(result['relative_span'], [1001, 15000])
        self.assertEqual(result['minimum_interval'], [1001, 30000])
        self.assertEqual(result['maximum_interval'], [1001, 30000])
        self.assertEqual(result['wall_clock_mapping'], 'NOT_COMPUTED_FIRST_MEDIA_SAMPLE_ALIGNMENT_UNVERIFIED')
        self.assertFalse(result['source_frame_completeness_verified'])
        self.assertFalse(result['prediction_eligible'])

    def test_pts_origin_is_segment_local_and_large_mpeg_pts_stays_exact(self):
        origin = (1 << 33) - 6000
        result = self.assess([(origin, Fraction(1, 90000)), (origin + 3003, Fraction(1, 90000))])
        self.assertEqual(result['relative_span'], [1001, 30000])
        self.assertEqual(result['first_pts'], origin)

    def test_gap_is_measured_without_inventing_missing_frames_or_constant_fps(self):
        result = self.assess([(0, Fraction(1, 10)), (1, Fraction(1, 10)), (11, Fraction(1, 10))])
        self.assertTrue(result['relative_pts_consistent'])
        self.assertEqual(result['minimum_interval'], [1, 10])
        self.assertEqual(result['maximum_interval'], [1, 1])
        self.assertNotIn('missing_frames', result)
        self.assertFalse(result['source_frame_completeness_verified'])

    def test_missing_bool_float_negative_or_unbounded_pts_rejects_full_segment(self):
        for bad in (None, True, 1.0, -1, 1 << 63, 'secret'):
            with self.subTest(value=bad):
                result = self.assess([(0, Fraction(1, 30)), (bad, Fraction(1, 30)), (2, Fraction(1, 30))])
                self.assert_unusable(result, 'UNVERIFIED_FRAME_PTS_VALUE')
                self.assertEqual(result['frames_observed'], 3)
                self.assertNotIn('secret', json.dumps(result))

    def test_missing_float_invalid_or_unbounded_timebase_is_rejected(self):
        for bad in (None, True, .1, 1, Fraction(0), Fraction(-1, 30), Fraction(2), Fraction(1, 10**9 + 1)):
            with self.subTest(value=bad):
                self.assert_unusable(self.assess([(0, bad), (1, Fraction(1, 30))]), 'UNVERIFIED_FRAME_TIME_BASE')

    def test_changed_timebase_duplicate_and_backwards_pts_never_retain_valid_prefix(self):
        for points, code in (([(0, Fraction(1, 30)), (1, Fraction(1, 60))], 'UNVERIFIED_FRAME_TIME_BASE_CHANGED'),
                             ([(0, Fraction(1, 30)), (0, Fraction(1, 30))], 'UNVERIFIED_FRAME_PTS_DUPLICATE'),
                             ([(2, Fraction(1, 30)), (1, Fraction(1, 30))], 'UNVERIFIED_FRAME_PTS_REVERSED')):
            with self.subTest(code=code):
                self.assert_unusable(self.assess(points), code)

    def test_segment_end_is_exclusive_and_failure_does_not_silently_tolerate_one_second(self):
        for pts in (20, 21):
            self.assert_unusable(self.assess([(0, Fraction(1, 10)), (pts, Fraction(1, 10))]),
                                 'UNVERIFIED_FRAME_OUTSIDE_DECLARED_SEGMENT')
        self.assertTrue(self.assess([(0, Fraction(1, 10)), (19, Fraction(1, 10))])['relative_pts_consistent'])

    def test_zero_one_frame_and_invalid_duration_remain_unusable(self):
        for points in ([], [(0, Fraction(1, 30))]):
            self.assert_unusable(self.assess(points), 'UNVERIFIED_INSUFFICIENT_FRAME_TIMES')
        for duration in (True, 0, -1, 21, 10**1000, float('nan'), float('inf'), '2'):
            with self.subTest(duration=duration):
                self.assert_unusable(self.assess([(0, Fraction(1, 30)), (1, Fraction(1, 30))], duration),
                                     'UNVERIFIED_FRAME_SEGMENT_DURATION')

    def test_streaming_bound_digest_and_result_copies(self):
        import hashlib
        item = self.assessor()
        for pts in (0, 1, 2):
            item.observe(pts, Fraction(1, 30))
        first = item.finish()
        self.assertEqual(first['pts_sha256'], hashlib.sha256(b'0/1/30\n1/1/30\n2/1/30\n').hexdigest())
        first['time_base'][0] = 99
        self.assertEqual(item.finish()['time_base'], [1, 30])
        for pts in range(3, 20001):
            item.observe(pts, Fraction(1, 1000000))
        self.assert_unusable(item.finish(), 'UNVERIFIED_FRAME_COUNT_BOUND')


class FrameTimingDecodeIntegrationTests(unittest.TestCase):
    def analyze(self, **kwargs):
        from tests.test_exhibition_video_camera_integration import CameraDecodeIntegrationTests
        return CameraDecodeIntegrationTests().analyze(**kwargs)

    def test_v4_observes_all_decoded_frames_not_only_sparse_samples(self):
        result = self.analyze(frame_timing=True, program_clock=True, camera_motion=True)
        self.assertEqual(result['analysis_version'], 'transient-hls-color-candidates/v4')
        timing = result['frame_timing']
        self.assertEqual(timing['frames_observed'], result['frames_decoded'])
        self.assertGreater(timing['frames_observed'], result['frames_sampled'])
        self.assertEqual(timing['segments_assessed'], result['segments_decoded'])
        self.assertEqual(timing['segments'][0]['sequence'], 17)
        self.assertTrue(timing['segments'][0]['relative_pts_consistent'])
        self.assertEqual(timing['playlist_sha256'], result['child_sha256'])
        self.assertEqual(timing['coverage_scope'], 'COMPLETE_DECODED_PLAYLIST')
        self.assertFalse(timing['independent_clock_verified'])
        self.assertFalse(timing['physical_exhibition_time_verified'])
        self.assertFalse(timing['prediction_eligible'])
        self.assertEqual(result['program_clock']['frame_time_mapping'], 'NOT_COMPUTED')
        self.assertEqual(result['boat_features'], [])
        self.assertFalse(result['prediction_eligible'])
        self.assertNotIn('https:', json.dumps(result))

    def test_omitted_or_false_option_preserves_all_existing_versions(self):
        for options in ({}, {'camera_motion': True}, {'program_clock': True},
                        {'program_clock': True, 'camera_motion': True}):
            with self.subTest(options=options):
                self.assertEqual(self.analyze(**options), self.analyze(**options, frame_timing=False))

    def test_option_is_strict_before_media_get_and_partial_segments_are_not_complete(self):
        from race_ai.exhibition_video_decode import analyze_exhibition
        from race_ai.core import SourceError
        from tests.test_exhibition_video_source import run, program, NOW
        from datetime import datetime
        for bad in (None, 1, 'true'):
            descriptor, lease = run()
            with self.subTest(bad=bad), patch('race_ai.exhibition_video_decode.bounded_fetch') as fetch:
                with self.assertRaises(SourceError):
                    analyze_exhibition(descriptor, lease, program(), frame_timing=bad,
                                       clock=lambda: datetime.fromisoformat(NOW))
                fetch.assert_not_called()
        from tests.test_exhibition_video_decode import child
        vod = child()
        segment = vod.split('#EXTINF:', 1)[1].split('#EXT-X-ENDLIST')[0]
        vod = vod.replace('#EXT-X-ENDLIST', '#EXTINF:' + segment.replace('_17.ts', '_18.ts') + '#EXT-X-ENDLIST')
        result = self.analyze(frame_timing=True, playlist=vod, segment_limit=1)
        self.assertEqual(result['frame_timing']['coverage_scope'], 'PARTIAL_DECODED_PLAYLIST')
        self.assertEqual(result['frame_timing']['segments_assessed'], 1)
        self.assertEqual(result['segments_in_playlist'], 2)

    def test_segment_reset_and_declared_discontinuity_never_create_cross_segment_intervals(self):
        from tests.test_exhibition_video_decode import child
        vod = child()
        segment = vod.split('#EXTINF:', 1)[1].split('#EXT-X-ENDLIST')[0]
        vod = vod.replace('#EXT-X-ENDLIST', '#EXT-X-DISCONTINUITY\n#EXTINF:'
                          + segment.replace('_17.ts', '_18.ts') + '#EXT-X-ENDLIST')
        result = self.analyze(frame_timing=True, playlist=vod)
        rows = result['frame_timing']['segments']
        self.assertEqual([r['sequence'] for r in rows], [17, 18])
        self.assertEqual([r['discontinuity_before'] for r in rows], [False, True])
        self.assertEqual(rows[0]['first_pts'], rows[1]['first_pts'])
        self.assertTrue(all(r['relative_pts_consistent'] for r in rows))
        self.assertNotIn('cross_segment_interval', result['frame_timing'])


if __name__ == '__main__':
    unittest.main()
