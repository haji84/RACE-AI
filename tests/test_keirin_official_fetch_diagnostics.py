"""Synthetic official JSON fetch failures, never live provider calls."""
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from race_ai import keirin_github_provider_stop as stop
from race_ai import keirin_official_public_source as official
from scripts import keirin_official_day_pipeline as pipeline


class OfficialFetchDiagnostics(unittest.TestCase):
    now = datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    detail = official._url('JSJ012', encp='private_fixture_token_123456789')

    def make(self, fetch):
        result = pipeline.official_fetcher('/synthetic', lambda:self.now, fetch=fetch)
        self.assertTrue(callable(getattr(result, 'safe_diagnostics', None)),
                        'OFFICIAL_FETCH_SAFE_DIAGNOSTICS_REQUIRED')
        return result

    def test_all_json_request_types_get_fixed_secret_free_purposes(self):
        get = self.make(lambda _:b'{"resultCd":0}')
        for kind, purpose in (('JSJ057', 'OFFICIAL_JSON_CALENDAR'),
                ('JSJ017', 'OFFICIAL_JSON_DAY_LIST'), ('JSJ018', 'OFFICIAL_JSON_RESULT_SUMMARY'),
                ('JSJ001', 'OFFICIAL_JSON_HEADER'), ('JSJ012', 'OFFICIAL_JSON_DETAIL')):
            url = official._url(kind, **({'kday':'20261121'} if kind == 'JSJ057' else
                                       {'encp':'private_fixture_token_123456789'}))
            get(url)
            row = get.safe_diagnostics()[-1]
            self.assertEqual(row['purpose'], purpose)
            self.assertEqual((row['source_host'], row['source_path'], row['method']),
                             ('keirin.jp', '/pc/json', 'GET'))
            self.assertEqual(row['http_status'], 200)
            self.assertNotIn('encp', json.dumps(row))
            self.assertNotIn('private_fixture_token', json.dumps(row))

    def test_denial_details_exist_before_persistent_stop_and_no_retry(self):
        for status in (401, 403, 407, 429):
            for mode in ('typed', 'http', 'internal'):
                with self.subTest(status=status, mode=mode):
                    calls = []
                    def failed(url):
                        calls.append(url)
                        if mode == 'http':
                            raise HTTPError(url, status, 'private HTTP reason', {}, None)
                        if mode == 'internal':
                            raise official.OfficialSourceError(f'OFFICIAL_HTTP_{status}')
                        raise official.OfficialProviderStop(status)
                    get = self.make(failed)
                    def persist(**kwargs):
                        row = get.safe_diagnostics()[-1]
                        self.assertEqual(row['http_status'], status)
                        self.assertEqual(row['purpose'], 'OFFICIAL_JSON_DETAIL')
                        self.assertEqual(row['reason'], 'HTTP_DENIED')
                        self.assertEqual(kwargs['code'], stop.DENIED)
                    with patch.object(stop, 'record_denial', side_effect=persist) as saved:
                        for _ in range(2):
                            with self.assertRaises(official.OfficialProviderStop):
                                get(self.detail)
                        self.assertEqual(len(calls), 1)
                        saved.assert_called_once()

    def test_transport_and_http_failure_are_not_relabelled_as_provider_denial(self):
        cases = [(TimeoutError('Cookie=private'), None, 'TRANSPORT_FAILED'),
                 (HTTPError(self.detail, 503, 'private', {}, None), 503, 'HTTP_ERROR'),
                 (official.OfficialSourceError('OFFICIAL_HTTP_500'), 500, 'HTTP_ERROR')]
        for error, status, reason in cases:
            with self.subTest(error=type(error).__name__, status=status):
                def failed(_):
                    raise error
                get = self.make(failed)
                with patch.object(stop, 'record_denial') as saved:
                    with self.assertRaises(official.OfficialSourceError) as raised:
                        get(self.detail)
                    self.assertNotIsInstance(raised.exception, official.OfficialProviderStop)
                    self.assertNotEqual(saved.call_args.kwargs['code'], stop.DENIED)
                row = get.safe_diagnostics()[-1]
                self.assertEqual(row['reason'], reason)
                self.assertEqual(row['http_status'], status)
                self.assertNotIn('Cookie', json.dumps(row))
                self.assertNotIn('private', json.dumps(row))

    def test_higher_level_parser_failure_has_last_response_type_and_200(self):
        get = self.make(lambda _:b'invented malformed JSON')
        get(self.detail)
        get.record_validation_failure()
        row = get.safe_diagnostics()[-1]
        self.assertEqual(row['purpose'], 'OFFICIAL_JSON_DETAIL')
        self.assertEqual(row['stage'], 'PARSE_RESULT')
        self.assertEqual(row['reason'], 'SOURCE_VALIDATION_FAILED')
        self.assertEqual(row['http_status'], 200)
        get.record_validation_failure()
        self.assertEqual(len(get.safe_diagnostics()), 2)

    def test_bounded_copied_history_does_not_mutate_internal_rows(self):
        get = self.make(lambda _:b'{"resultCd":0}')
        for i in range(40):
            get(official._url('JSJ012', encp=f'fixture_token_{i:020}'))
        rows = get.safe_diagnostics()
        self.assertEqual(len(rows), 32)
        rows[0]['source_host'] = 'malicious.invalid'
        self.assertEqual(get.safe_diagnostics()[0]['source_host'], 'keirin.jp')


if __name__ == '__main__':
    unittest.main()
