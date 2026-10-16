"""Synthetic LIVE schedule boundaries; these are not playback or CV tests."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import unittest

from race_ai.core import SourceError
from race_ai.exhibition_video_source import PLAYER, STADIUMS, SourceResponse
from race_ai.live_video_source import resolve_live_schedule
from web.race_contract import canonical

NOW = datetime.fromisoformat('2026-10-16T16:25:00+09:00')


def setting(stadium='24omura'):
    rows = {}
    for source in ('br', 'mix'):
        for kind in ('live', 'dvr'):
            rows[f'{source}_{kind}'] = dict(
                ref_id=f'lm-{source}-{stadium}-tokyo' + ('-20261016' if kind == 'dvr' else ''),
                type=kind, region='tokyo', source_type=source,
                start_at='2026-10-16T09:50:00+09:00', end_at='2026-10-17T01:59:59+09:00')
    return dict(rows, update_from='ライブスケジュール登録API', last_update='2026-10-16T07:00:42+09:00')


class Fetch:
    def __init__(self, value=None):
        self.value = setting() if value is None else value
        self.calls = []
        self.response = None

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response or SourceResponse(200, url, 'application/json', canonical(self.value))


def run(fetch=None, **kwargs):
    return resolve_live_schedule(kwargs.pop('venue', '24'), fetch=fetch or Fetch(),
                                 clock=kwargs.pop('clock', lambda: NOW), **kwargs)


class LiveVideoSourceTests(unittest.TestCase):
    def test_schedule_is_one_bounded_metadata_get_and_never_predictive(self):
        fetch = Fetch()
        result = run(fetch)
        self.assertEqual(len(fetch.calls), 1)
        url, options = fetch.calls[0]
        self.assertEqual(url, PLAYER + '/setting/live/24omura/setting.json')
        self.assertEqual(options['max_bytes'], 16384)
        self.assertEqual(options['timeout'], 10)
        self.assertIn('/player/live?service=boatcast&stadium=24omura&sourceType=mix&dvr=1', options['headers']['Referer'])
        self.assertEqual(result['schedule_status'], 'SCHEDULE_ACTIVE')
        self.assertEqual(result['channel_ref'], 'lm-mix-24omura-tokyo')
        self.assertEqual(result['race_binding_status'], 'UNVERIFIED')
        self.assertEqual(result['exhibition_detection_status'], 'UNVERIFIED')
        self.assertEqual(result['wall_clock_alignment_status'], 'UNVERIFIED')
        self.assertFalse(result['prediction_input_eligible'])
        self.assertEqual(result['boat_features'], [])
        self.assertEqual(result['model_validation_status'], 'UNVALIDATED')
        self.assertNotIn('race_id', result)
        self.assertEqual(result['source_sha256'], hashlib.sha256(canonical(setting())).hexdigest())
        self.assertEqual(result['snapshot_id'], hashlib.sha256(canonical({k: v for k, v in result.items() if k != 'snapshot_id'})).hexdigest())

    def test_all_pinned_venue_paths_with_synthetic_settings(self):
        for venue, stadium in STADIUMS.items():
            with self.subTest(venue=venue):
                fetch = Fetch(setting(stadium))
                result = run(fetch, venue=venue)
                self.assertEqual(result['stadium'], stadium)
                self.assertEqual(fetch.calls[0][0], f'{PLAYER}/setting/live/{stadium}/setting.json')
                self.assertFalse(result['prediction_input_eligible'])

    def test_invalid_venues_and_naive_clock_make_zero_gets(self):
        for venue in (24, True, '1', '25', '24omura', '../24', '２４', None):
            fetch = Fetch()
            with self.subTest(venue=venue), self.assertRaises(SourceError): run(fetch, venue=venue)
            self.assertFalse(fetch.calls)
        fetch = Fetch()
        with self.assertRaises(SourceError): run(fetch, clock=lambda: NOW.replace(tzinfo=None))
        self.assertFalse(fetch.calls)

    def test_unknown_fields_or_missing_rows_are_rejected(self):
        for mutate in (lambda d: d.update(token='do-not-retain'),
                       lambda d: d.pop('br_live'),
                       lambda d: d['mix_live'].update(url='https://example.invalid'),
                       lambda d: d['br_dvr'].pop('end_at')):
            value = setting(); mutate(value)
            with self.subTest(value=value), self.assertRaises(SourceError): run(Fetch(value))

    def test_other_venue_source_region_kind_and_dvr_date_are_rejected(self):
        changes = [('mix_live', 'ref_id', 'lm-mix-02toda-tokyo'),
                   ('mix_live', 'source_type', 'br'), ('mix_live', 'type', 'dvr'),
                   ('mix_live', 'region', 'osaka'), ('br_live', 'ref_id', 'https://example.invalid?t=x'),
                   ('mix_dvr', 'ref_id', 'lm-mix-24omura-tokyo-20261015')]
        for row, field, value in changes:
            data = setting(); data[row][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(SourceError): run(Fetch(data))

    def test_strict_current_day_and_schedule_intervals(self):
        for start, end in [('2026-10-15T09:50:00+09:00', '2026-10-16T01:59:59+09:00'),
                           ('2026-10-16T09:50:00', '2026-10-17T01:59:59+09:00'),
                           ('2026-10-16T09:50:00+09:00', '2026-10-16T09:50:00+09:00'),
                           ('2026-10-16T09:50:00+09:00', '2026-10-18T09:50:00+09:00')]:
            data = setting(); data['mix_live'].update(start_at=start, end_at=end)
            with self.subTest(start=start, end=end), self.assertRaises(SourceError): run(Fetch(data))

    def test_live_and_dvr_windows_must_agree(self):
        data = setting(); data['mix_dvr']['end_at'] = '2026-10-17T01:59:58+09:00'
        with self.assertRaises(SourceError): run(Fetch(data))

    def test_schedule_labels_do_not_claim_video_or_exhibition_availability(self):
        for at, status in [('2026-10-16T09:49:59+09:00', 'SCHEDULE_FUTURE'),
                           ('2026-10-16T09:50:00+09:00', 'SCHEDULE_ACTIVE'),
                           ('2026-10-17T01:59:59+09:00', None)]:
            clock = lambda: datetime.fromisoformat(at)
            if status is None:
                with self.assertRaises(SourceError): run(clock=clock)
            else:
                result = run(clock=clock)
                self.assertEqual(result['schedule_status'], status)
                self.assertFalse(result['prediction_input_eligible'])
        data = setting()
        for key in ('mix_live', 'mix_dvr'): data[key]['end_at'] = '2026-10-16T16:25:00+09:00'
        self.assertEqual(run(Fetch(data))['schedule_status'], 'SCHEDULE_ENDED')

    def test_future_update_or_bad_registration_text_rejected(self):
        for field, value in [('last_update', '2026-10-16T16:25:01+09:00'),
                             ('last_update', '2026-10-17T00:00:00+09:00'),
                             ('update_from', ''), ('update_from', 1)]:
            data = setting(); data[field] = value
            with self.subTest(field=field), self.assertRaises(SourceError): run(Fetch(data))

    def test_capture_clock_must_not_reverse_cross_day_or_exceed_budget(self):
        for end in (NOW - timedelta(microseconds=1), NOW + timedelta(seconds=11),
                    datetime.fromisoformat('2026-10-17T00:00:00+09:00')):
            ticks = iter((NOW, end))
            with self.subTest(end=end), self.assertRaises(SourceError): run(clock=lambda: next(ticks))

    def test_redirect_status_mime_empty_oversize_and_nonbyte_body_rejected(self):
        url = PLAYER + '/setting/live/24omura/setting.json'
        responses = [SourceResponse(200, url + '?x=1', 'application/json', canonical(setting())),
                     SourceResponse(302, url, 'application/json', canonical(setting())),
                     SourceResponse(200, url, 'text/html', canonical(setting())),
                     SourceResponse(True, url, 'application/json', canonical(setting())),
                     SourceResponse(200, url, 'application/json', b''),
                     SourceResponse(200, url, 'application/json', b' ' * 16385),
                     SourceResponse(200, url, 'application/json', '{}')]
        for response in responses:
            fetch = Fetch(); fetch.response = response
            with self.subTest(response=response), self.assertRaises(SourceError): run(fetch)
            self.assertEqual(len(fetch.calls), 1)

    def test_duplicate_nonfinite_invalid_utf8_json_and_deep_data_rejected(self):
        url = PLAYER + '/setting/live/24omura/setting.json'
        for body in (b'{"mix_live":{},"mix_live":{}}', b'{"x":NaN}', b'{"x":1e999}', b'\xff',
                     b'[]', b'[' * 2000 + b']' * 2000):
            fetch = Fetch(); fetch.response = SourceResponse(200, url, 'application/json', body)
            with self.subTest(body=body[:30]), self.assertRaises(SourceError): run(fetch)

    def test_transport_errors_are_sanitized_without_retry(self):
        calls = []
        def fetch(url, **kwargs):
            calls.append(url)
            raise RuntimeError('https://untrusted.invalid?token=DO_NOT_LEAK')
        with self.assertRaisesRegex(SourceError, '^LIVE_SETTING_UNAVAILABLE$'): run(fetch)
        self.assertEqual(len(calls), 1)


if __name__ == '__main__': unittest.main()
