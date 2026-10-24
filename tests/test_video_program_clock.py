"""Source-declared clocks only: no physical-event or independently verified clock claim."""
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib
import json
import unittest


CLOSE = '2026-10-15T10:21:00+09:00'
CAPTURE = '2026-10-15T10:20:00+09:00'
ANCHOR = '2026-10-15T01:19:00.123Z'
UNSET = object()


def playlist(anchors=(ANCHOR, '2026-10-15T01:19:06.123Z'), durations=('6', '6'), discontinuity=False):
    lines = ['#EXTM3U', '#EXT-X-PLAYLIST-TYPE:VOD', '#EXT-X-MEDIA-SEQUENCE:17']
    for i, (anchor, duration) in enumerate(zip(anchors, durations)):
        if i and discontinuity:
            lines.append('#EXT-X-DISCONTINUITY')
        if anchor is not None:
            lines.append('#EXT-X-PROGRAM-DATE-TIME:' + anchor)
        lines.extend(['#EXTINF:' + duration + ',', 'https://synthetic.invalid/segment-' + str(i)])
    return ('\n'.join(lines) + '\n#EXT-X-ENDLIST\n').encode()


def segments(durations=(6.0, 6.0), discontinuity=False):
    return [dict(sequence=17+i, duration=value, discontinuity=bool(i and discontinuity))
            for i, value in enumerate(durations)]


class ProgramClockTests(unittest.TestCase):
    def assess(self, raw=UNSET, metadata=UNSET, **kwargs):
        try:
            module = importlib.import_module('race_ai.video_program_clock')
        except ModuleNotFoundError:
            self.fail('source-declared program-clock quality assessor is missing')
        return module.assess_program_clock(playlist() if raw is UNSET else raw,
            segments() if metadata is UNSET else metadata, closed_at=kwargs.get('closed_at', CLOSE),
            captured_at=kwargs.get('captured_at', CAPTURE))

    def assert_rejected(self, value, reason):
        self.assertEqual(value['status'], reason)
        self.assertFalse(value['source_clock_consistent'])
        self.assertEqual(value['segment_boundaries'], [])
        self.assertIsNone(value['declared_clip_start_at'])
        self.assertIsNone(value['declared_clip_end_at'])
        self.assertFalse(value['physical_exhibition_time_verified'])
        self.assertFalse(value['independent_clock_verified'])
        self.assertFalse(value['prediction_eligible'])
        self.assertNotIn('https:', json.dumps(value, allow_nan=False))

    def test_explicit_anchors_normalized_and_full_playlist_hash_bound(self):
        raw = playlist()
        value = self.assess(raw)
        self.assertEqual(value['status'], 'SOURCE_DECLARED_CLOCK_CONSISTENT')
        self.assertTrue(value['source_clock_consistent'])
        self.assertEqual(value['declared_clip_start_at'], '2026-10-15T01:19:00.123000+00:00')
        self.assertEqual(value['declared_clip_end_at'], '2026-10-15T01:19:12.123000+00:00')
        self.assertEqual(value['playlist_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(value['explicit_anchor_count'], 2)
        self.assertEqual([v['sequence'] for v in value['segment_boundaries']], [17, 18])
        self.assertEqual(value['frame_time_mapping'], 'NOT_COMPUTED')
        self.assertFalse(value['physical_exhibition_time_verified'])
        self.assertFalse(value['independent_clock_verified'])
        self.assertFalse(value['prediction_eligible'])
        self.assertEqual(value['timing_scope'], 'SOURCE_DECLARED_SEGMENT_BOUNDARIES_ONLY')
        self.assertNotIn('https:', json.dumps(value, allow_nan=False))

    def test_timezone_equivalence_and_exact_decimal_duration(self):
        raw = playlist(('2026-10-15T10:19:00.123456+09:00', '2026-10-15T01:19:00.456789Z'),
                       ('0.333333', '0.666667'))
        value = self.assess(raw, segments((.333333, .666667)))
        self.assertTrue(value['source_clock_consistent'])
        self.assertEqual(value['declared_clip_end_at'], '2026-10-15T01:19:01.123456+00:00')

    def test_missing_or_partial_anchors_never_interpolate_a_verified_clock(self):
        for anchors in ((None, None), (ANCHOR, None), (None, ANCHOR)):
            with self.subTest(anchors=anchors):
                self.assert_rejected(self.assess(playlist(anchors)), 'UNVERIFIED_MISSING_SEGMENT_ANCHOR')

    def test_duplicate_or_unused_anchor_is_ambiguous(self):
        raw = playlist()
        for bad in (raw.replace(b'#EXTINF:6,', b'#EXT-X-PROGRAM-DATE-TIME:' + ANCHOR.encode() + b'\n#EXTINF:6,', 1),
                    raw.replace(b'#EXT-X-ENDLIST', b'#EXT-X-PROGRAM-DATE-TIME:' + ANCHOR.encode() + b'\n#EXT-X-ENDLIST')):
            self.assert_rejected(self.assess(bad), 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')

    def test_unknown_timezone_invalid_calendar_or_unbounded_precision_is_rejected(self):
        for anchor in ('2026-10-15T01:19:00', '2026-02-30T01:19:00Z', '2026-10-15 01:19:00Z',
                       '2026-10-15T01:19:00.1234567Z', '2026-10-15T01:19:00+99:00',
                       '2026-10-15T02:19:00.123+00:60', '2026-10-15T11:58:00.123+09:99',
                       '2026-10-15T15:20:00.123+14:01'):
            with self.subTest(anchor=anchor):
                self.assert_rejected(self.assess(playlist((anchor, ANCHOR))), 'UNVERIFIED_PROGRAM_CLOCK_VALUE')

    def test_malformed_known_tags_or_conflicting_playlist_type_are_not_ignored(self):
        for extra in (b'#EXT-X-PROGRAM-DATE-TIME', b'#EXT-X-PROGRAM-DATE-TIME :broken',
                      b'#EXT-X-DISCONTINUITY:false', b'#EXT-X-MEDIA-SEQUENCE', b'#EXTINF',
                      b'#EXT-X-PLAYLIST-TYPE:EVENT', b'#EXT-X-PLAYLIST-TYPE', b'#EXTM3U'):
            bad = playlist().replace(b'#EXT-X-ENDLIST', extra + b'\n#EXT-X-ENDLIST')
            self.assert_rejected(self.assess(bad), 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')

    def test_forward_rounding_gap_boundary_is_explicit_and_overlap_never_tolerated(self):
        value = self.assess(playlist((ANCHOR, '2026-10-15T01:19:06.124Z')))
        self.assertTrue(value['source_clock_consistent'])
        self.assertEqual(value['segment_boundaries'][1]['gap_before_seconds'], .001)
        for anchor in ('2026-10-15T01:19:06.124001Z', '2026-10-15T01:19:06.122999Z'):
            self.assert_rejected(self.assess(playlist((ANCHOR, anchor))), 'UNVERIFIED_PROGRAM_CLOCK_CONTINUITY')

    def test_complete_declared_clock_does_not_claim_decode_coverage(self):
        value = self.assess()
        self.assertEqual(value.get('coverage_scope'), 'WHOLE_PLAYLIST_METADATA_NOT_DECODE_COVERAGE')

    def test_gap_without_discontinuity_and_overlapping_segments_fail_closed(self):
        for anchor in ('2026-10-15T01:19:07.123Z', '2026-10-15T01:19:05.123Z'):
            self.assert_rejected(self.assess(playlist((ANCHOR, anchor))), 'UNVERIFIED_PROGRAM_CLOCK_CONTINUITY')
        self.assert_rejected(self.assess(playlist((ANCHOR, ANCHOR), discontinuity=True),
                                         segments(discontinuity=True)), 'UNVERIFIED_PROGRAM_CLOCK_CONTINUITY')

    def test_explicit_forward_discontinuity_is_retained_not_filled_with_fake_frames(self):
        value = self.assess(playlist((ANCHOR, '2026-10-15T01:19:10.123Z'), discontinuity=True),
                            segments(discontinuity=True))
        self.assertTrue(value['source_clock_consistent'])
        self.assertEqual(value['discontinuity_count'], 1)
        self.assertEqual(value['segment_boundaries'][1]['gap_before_seconds'], 4)
        self.assertEqual(value['frame_time_mapping'], 'NOT_COMPUTED')

    def test_future_end_of_segment_is_not_past_evidence(self):
        self.assert_rejected(self.assess(captured_at='2026-10-15T01:19:10Z'), 'UNVERIFIED_PROGRAM_CLOCK_FUTURE')

    def test_wrong_race_day_and_postcutoff_segment_are_not_exhibition_clock_proof(self):
        self.assert_rejected(self.assess(playlist(('2026-10-14T01:19:00Z', '2026-10-14T01:19:06Z'))),
                             'UNVERIFIED_PROGRAM_CLOCK_DAY')
        self.assert_rejected(self.assess(captured_at='2026-10-15T01:23:00Z', closed_at='2026-10-15T01:19:10Z'),
                             'UNVERIFIED_PROGRAM_CLOCK_CUTOFF')

    def test_cutoff_and_capture_context_are_aware_ordered_actual_clocks(self):
        for context in ({'captured_at': '2026-10-15T01:20:00'}, {'closed_at': 'garbage'},
                        {'captured_at': datetime(2026, 10, 15, 1, 20)}, {'captured_at': True}):
            self.assert_rejected(self.assess(**context), 'UNVERIFIED_PROGRAM_CLOCK_CONTEXT')
        # Later replay is allowed on the same actual race date, not backdated input eligibility.
        self.assertTrue(self.assess(captured_at='2026-10-15T01:23:00Z')['source_clock_consistent'])

    def test_parsed_segment_count_sequence_duration_and_discontinuity_must_match(self):
        variants = [segments()[:1], segments() + segments(), None, 'bad']
        for key, value in (('sequence', 99), ('duration', 5.9), ('discontinuity', True),
                           ('duration', True), ('sequence', True), ('extra', 'unexpected')):
            rows = deepcopy(segments()); rows[0][key] = value; variants.append(rows)
        for rows in variants:
            with self.subTest(rows=rows):
                self.assert_rejected(self.assess(metadata=rows), 'UNVERIFIED_PROGRAM_CLOCK_SEGMENTS')

    def test_malformed_playlist_durations_and_resource_bounds_never_escape(self):
        raw = playlist()
        bads = [b'', None, raw+b'x'*1048576, raw.replace(b'#EXTM3U', b'garbage'),
                raw.replace(b'#EXT-X-ENDLIST', b''), raw.replace(b'VOD', b'EVENT'),
                raw.replace(b'#EXTINF:6,', b'#EXTINF:nan,'), raw.replace(b'#EXTINF:6,', b'#EXTINF:0,'),
                raw.replace(b'#EXTINF:6,', b'#EXTINF:21,'), raw.replace(b'#EXTINF:6,', b'#EXTINF:1e0,'),
                raw.replace(b'#EXT-X-MEDIA-SEQUENCE:17', b'#EXT-X-MEDIA-SEQUENCE:17\n#EXT-X-MEDIA-SEQUENCE:17')]
        for bad in bads:
            with self.subTest(size=len(bad) if bad is not None else None):
                self.assert_rejected(self.assess(bad), 'UNVERIFIED_PROGRAM_CLOCK_STRUCTURE')


class ProgramClockDecodeIntegrationTests(unittest.TestCase):
    def analyze(self, **kwargs):
        from tests import test_exhibition_video_camera_integration as integration
        return integration.CameraDecodeIntegrationTests().analyze(**kwargs)

    def test_default_and_v2_do_not_gain_new_clock_claims(self):
        for options in ({}, {'camera_motion': True}):
            result = self.analyze(**options)
            self.assertNotIn('program_clock', result)
            self.assertEqual(result['timestamp_basis'], 'RELATIVE_SEGMENT_PTS_NOT_PHYSICAL_EXHIBITION_CLOCK')

    def test_v3_valid_declared_clock_links_child_hash_without_assigning_frame_or_physical_time(self):
        from tests.test_exhibition_video_decode import child
        vod = child().replace('#EXTINF:', '#EXT-X-PROGRAM-DATE-TIME:2026-10-15T01:19:00.123Z\n#EXTINF:')
        result = self.analyze(program_clock=True, camera_motion=True, playlist=vod)
        self.assertEqual(result['analysis_version'], 'transient-hls-color-candidates/v3')
        self.assertTrue(result['program_clock']['source_clock_consistent'])
        self.assertEqual(result['program_clock']['playlist_sha256'], result['child_sha256'])
        self.assertEqual(result['program_clock']['segment_count'], result['segments_in_playlist'])
        self.assertEqual(result['boat_identity'], 'UNVERIFIED')
        self.assertEqual(result['camera_calibration'], 'UNVERIFIED')
        self.assertFalse(result['prediction_eligible'])
        self.assertEqual(result['boat_features'], [])
        self.assertEqual(result['timestamp_basis'], 'RELATIVE_SEGMENT_PTS_NOT_PHYSICAL_EXHIBITION_CLOCK')
        self.assertNotIn('https:', json.dumps(result))

    def test_v3_clock_quality_failure_does_not_claim_media_not_decoded_or_invent_timestamps(self):
        result = self.analyze(program_clock=True)
        self.assertEqual(result['coverage'], 'COMPLETE_PLAYLIST')
        self.assertGreater(result['frames_decoded'], 0)
        self.assertEqual(result['program_clock']['status'], 'UNVERIFIED_MISSING_SEGMENT_ANCHOR')
        self.assertFalse(result['program_clock']['source_clock_consistent'])
        self.assertEqual(result['program_clock']['segment_boundaries'], [])

    def test_partial_decode_keeps_whole_manifest_clock_coverage_explicitly_separate(self):
        from tests.test_exhibition_video_decode import child
        one = child().replace('#EXTINF:', '#EXT-X-PROGRAM-DATE-TIME:2026-10-15T01:19:00Z\n#EXTINF:')
        uri = one.split('#EXTINF:', 1)[1].split('#EXT-X-ENDLIST')[0]
        vod = one.replace('#EXT-X-ENDLIST', '#EXT-X-PROGRAM-DATE-TIME:2026-10-15T01:19:02Z\n#EXTINF:'
                          + uri.replace('_17.ts', '_18.ts') + '#EXT-X-ENDLIST')
        result = self.analyze(program_clock=True, playlist=vod, segment_limit=1)
        self.assertEqual(result['coverage'], 'PARTIAL_PLAYLIST')
        self.assertEqual(result['segments_decoded'], 1)
        self.assertEqual(result['program_clock']['segment_count'], 2)
        self.assertEqual(result['program_clock']['coverage_scope'], 'WHOLE_PLAYLIST_METADATA_NOT_DECODE_COVERAGE')
        self.assertFalse(result['program_clock']['physical_exhibition_time_verified'])

    def test_v3_option_requires_bool_before_media_get_and_false_preserves_v1_bytes(self):
        from unittest.mock import patch
        from race_ai.exhibition_video_decode import analyze_exhibition
        from race_ai.core import SourceError
        from tests.test_exhibition_video_source import run, program, NOW
        for bad in (1, 'true', None):
            descriptor, lease = run()
            with self.subTest(value=bad), patch('race_ai.exhibition_video_decode.bounded_fetch') as fetch:
                with self.assertRaises(SourceError):
                    analyze_exhibition(descriptor, lease, program(), program_clock=bad,
                                       clock=lambda: datetime.fromisoformat(NOW))
                fetch.assert_not_called()
        self.assertEqual(self.analyze(), self.analyze(program_clock=False))
        self.assertEqual(self.analyze(camera_motion=True), self.analyze(camera_motion=True, program_clock=False))


if __name__ == '__main__':
    unittest.main()
