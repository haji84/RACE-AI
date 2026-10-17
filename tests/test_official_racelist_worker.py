import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from race_ai.official_racelist_worker import collect_official_racelist, source_scope, fetch_racelist
from race_ai.official_racelist_adapter import endpoint
from race_ai.tokuyama_day_worker import FetchResponse
from race_ai.venue_source_rights import RightsRecord
from tests.test_official_racelist_adapter import DAY, fixture

NOW = datetime(2026, 10, 14, 22, tzinfo=timezone.utc)


def rights(url=None, decision='allowed'):
    return [RightsRecord('18', 'facts_ingest', decision, url or source_scope('18'),
                         NOW.isoformat(), 'synthetic-review-reference', 'test reviewer')]


class OfficialWorkerTests(unittest.TestCase):
    def collect(self, records=None, body=None, response=None, now=NOW):
        self.calls = []
        def transport(url, *, timeout, max_bytes):
            self.calls.append(url)
            return response or FetchResponse((fixture() if body is None else body).encode(), url, 200, 'text/html;charset=UTF-8')
        return collect_official_racelist(DAY, '18', 1, rights=rights() if records is None else records,
                                         now=now, transport=transport)

    def test_index_permission_does_not_authorize_common_site_detail(self):
        for records in ([], rights(decision='unknown'), rights(decision='denied'), rights() * 2,
                        rights('https://www.boatrace-tokuyama.jp/modules/raceinfo/?page=index_raceindex'),
                        rights(endpoint(DAY, '18', 2))):
            with self.subTest(records=records):
                self.assertEqual(self.collect(records)['status'], 'SOURCE_RIGHTS_BLOCKED')
                self.assertEqual(self.calls, [])

    def test_approved_exact_or_venue_scope_produces_unpublished_evidence(self):
        for records in (rights(), rights(endpoint(DAY, '18', 1))):
            result = self.collect(records)
            self.assertEqual(result['status'], 'OFFICIAL_BODY_IDENTITY_VERIFIED')
            self.assertEqual(len(result['detail']['boats']), 6)
            self.assertFalse(result['redistribution_authorized'])
            self.assertEqual(len(self.calls), 1)

    def test_wrong_day_invalid_body_and_wrong_response_fail_closed(self):
        self.assertEqual(self.collect(body=fixture(DAY.replace(day=14)))['status'], 'SOURCE_INVALID')
        self.assertEqual(self.collect(body='<p>データがありません。</p>')['status'], 'SOURCE_INVALID')
        self.assertEqual(self.collect(now=NOW.replace(tzinfo=None))['status'], 'DAY_INVALID')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.collect(response=FetchResponse(b'x', 'https://evil.example/', 200, 'text/html'))['status'], 'SOURCE_INVALID')

    def test_future_review_cannot_authorize_fetch(self):
        record = RightsRecord('18', 'facts_ingest', 'allowed', source_scope('18'),
                             '2026-10-16T00:00:00+09:00', 'test evidence', 'reviewer')
        self.assertEqual(self.collect([record])['status'], 'SOURCE_RIGHTS_BLOCKED')
        self.assertEqual(self.calls, [])

    def test_transport_endpoint_and_bounds_are_fixed(self):
        with patch('race_ai.official_racelist_worker.request.build_opener') as opener:
            for url in ('https://evil.example/', endpoint(DAY, '18', 1) + '&extra=x'):
                with self.assertRaises(ValueError):
                    fetch_racelist(url)
            opener.assert_not_called()
