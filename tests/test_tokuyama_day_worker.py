import hashlib
import unittest
from datetime import date, datetime, timezone, timedelta
from unittest.mock import patch

from race_ai.core import SourceError
from race_ai.day_snapshot_publisher import validate
from race_ai.venue_source_rights import RightsRecord
from race_ai.tokuyama_day_worker import (
    FetchResponse, MAX_BYTES, TIMEOUT, SOURCE_SCOPE, NoRedirects,
    collect_tokuyama_day, endpoint, fetch_index,
)

DAY = date(2026, 10, 15)
NOW = datetime(2026, 10, 14, 16, tzinfo=timezone.utc)


def html(day=DAY):
    rows = []
    for number in range(1, 13):
        link = f'https://www.boatrace.jp/owpc/pc/race/racelist?hd={day:%Y%m%d}&amp;jcd=18&amp;rno={number}'
        rows.append(f'<tr><td><a href="{link}">{number}R</a></td>' +
                    ''.join(f'<td>選手{number}-{lane}</td>' for lane in range(1, 7)) + '</tr>')
    return ('<table>' + ''.join(rows) + '</table>').encode()


def rights(day=DAY, decision='allowed'):
    return [RightsRecord('18', 'facts_ingest', decision, endpoint(day),
                         NOW.isoformat(), 'test-only-permission-evidence', 'test reviewer')]


def details():
    return [dict(race_id=f'{DAY:%Y%m%d}-18-{number:02d}', lane=lane,
                 name=f'選手{number}-{lane}', racer_registration_id=str(4000 + number * 6 + lane),
                 motor_no=number * 6 + lane, verified_source=True,
                 source_url='https://www.boatrace.jp/owpc/pc/race/racelist',
                 captured_at=NOW.isoformat())
            for number in range(1, 13) for lane in range(1, 7)]


class WorkerTests(unittest.TestCase):
    def collect(self, *, body=None, records=None, detail_rows=None, response=None, now=NOW):
        self.calls = []
        def transport(url, *, timeout, max_bytes):
            self.calls.append((url, timeout, max_bytes))
            return response or FetchResponse(body if body is not None else html(), url, 200, 'text/html; charset=UTF-8')
        return collect_tokuyama_day(DAY, rights=rights() if records is None else records,
                                    now=now, transport=transport, details=detail_rows)

    def test_unknown_denied_and_duplicate_rights_stop_before_fetch(self):
        for records in ([], rights(decision='unknown'), rights(decision='denied'), rights() * 2):
            with self.subTest(records=records):
                result = self.collect(records=records)
                self.assertEqual(result['status'], 'SOURCE_RIGHTS_BLOCKED')
                self.assertEqual(self.calls, [])
                self.assertNotIn('snapshot', result)

    def test_approval_for_another_source_does_not_authorize_request(self):
        r = rights()
        r[0] = RightsRecord('18', 'facts_ingest', 'allowed', 'https://other.example/',
                            NOW.isoformat(), 'test evidence', 'reviewer')
        self.assertEqual(self.collect(records=r)['status'], 'SOURCE_RIGHTS_BLOCKED')
        self.assertEqual(self.calls, [])

    def test_configured_index_scope_can_cover_each_day_without_daily_permission_edit(self):
        r = rights()
        r[0] = RightsRecord('18', 'facts_ingest', 'allowed', SOURCE_SCOPE,
                            NOW.isoformat(), 'test source scope evidence', 'reviewer')
        self.assertEqual(self.collect(records=r)['status'], 'PARTIAL_INDEX_DETAILS_REQUIRED')

    def test_clock_mismatch_and_naive_clock_stop_before_fetch(self):
        for clock in (NOW.replace(day=16), NOW.replace(tzinfo=None)):
            self.assertEqual(self.collect(now=clock)['status'], 'DAY_INVALID')
            self.assertEqual(self.calls, [])

    def test_index_only_is_partial_and_has_computed_provenance(self):
        result = self.collect()
        self.assertEqual(result['status'], 'PARTIAL_INDEX_DETAILS_REQUIRED')
        self.assertEqual(result['race_count'], 12)
        self.assertEqual(result['source_sha256'], hashlib.sha256(html()).hexdigest())
        self.assertEqual(self.calls, [(endpoint(DAY), TIMEOUT, MAX_BYTES)])
        self.assertNotIn('snapshot', result)
        self.assertNotIn('entries', result)
        self.assertFalse(result['redistribution_authorized'])

    def test_yesterday_body_at_today_url_is_not_accepted(self):
        result = self.collect(body=html(date(2026, 10, 14)))
        self.assertEqual(result['status'], 'SOURCE_DATE_UNVERIFIED')
        self.assertNotIn('snapshot', result)

    def test_absent_date_links_are_unverified(self):
        self.assertEqual(self.collect(body=html().replace(b'racelist?', b'unknown?'))['status'],
                         'SOURCE_DATE_UNVERIFIED')

    def test_detached_current_day_navigation_cannot_date_previous_day_table(self):
        stale = html(date(2026, 10, 14)).replace(b'racelist?', b'unknown?')
        detached = b'<nav>' + b''.join(
            f'<a href="https://www.boatrace.jp/owpc/pc/race/racelist?hd={DAY:%Y%m%d}&amp;jcd=18&amp;rno={n}">today {n}</a>'.encode()
            for n in range(1, 13)) + b'</nav>'
        result = self.collect(body=stale + detached)
        self.assertEqual(result['status'], 'SOURCE_DATE_UNVERIFIED')
        self.assertNotIn('partial_index', result)
        self.assertNotIn('snapshot', result)

    def test_current_date_link_in_lane_cell_cannot_date_race_header(self):
        body = html().replace(b'racelist?', b'unknown?')
        for n in range(1, 13):
            name = f'選手{n}-1'.encode()
            body = body.replace(name,
                f'<a href="https://www.boatrace.jp/owpc/pc/race/racelist?hd={DAY:%Y%m%d}&amp;jcd=18&amp;rno={n}">'.encode()
                + name + b'</a>')
        self.assertEqual(self.collect(body=body)['status'], 'SOURCE_DATE_UNVERIFIED')

    def test_race_header_link_number_must_match_its_row(self):
        # All twelve identities exist, but two first-cell links label the wrong rows.
        body = html().replace(b'rno=1"', b'rno=swap"').replace(b'rno=2"', b'rno=1"').replace(b'rno=swap"', b'rno=2"')
        self.assertEqual(self.collect(body=body)['status'], 'SOURCE_DATE_UNVERIFIED')

    def test_incomplete_day_is_rejected(self):
        body = html().replace(b'>12R</a>', b'>not a race</a>')
        self.assertEqual(self.collect(body=body)['status'], 'SOURCE_INVALID')

    def test_response_status_origin_type_and_size_fail_closed(self):
        for response in (
            FetchResponse(html(), endpoint(DAY), 503, 'text/html'),
            FetchResponse(html(), 'https://evil.example/', 200, 'text/html'),
            FetchResponse(html(), endpoint(DAY), 200, 'application/json'),
            FetchResponse(b'x' * (MAX_BYTES + 1), endpoint(DAY), 200, 'text/html'),
            FetchResponse(b'\xff', endpoint(DAY), 200, 'text/html'),
            FetchResponse(html(), endpoint(DAY), 200, None),
        ):
            with self.subTest(response=response.url):
                self.assertEqual(self.collect(response=response)['status'], 'SOURCE_INVALID')

    def test_transport_timeout_is_an_explicit_unavailable_state(self):
        def transport(*args, **kwargs):
            raise TimeoutError('secret-like internal detail')
        result = collect_tokuyama_day(DAY, rights=rights(), now=NOW, transport=transport)
        self.assertEqual(result['status'], 'SOURCE_UNAVAILABLE')
        self.assertNotIn('secret-like', str(result))

    def test_verified_details_form_candidate_but_do_not_grant_publication(self):
        result = self.collect(detail_rows=details())
        self.assertEqual(result['status'], 'NORMALIZED_REQUIRES_PUBLICATION_APPROVAL')
        snapshot = result['snapshot']
        self.assertEqual(snapshot['races'], 12)
        self.assertEqual(snapshot['complete_six_boat_races'], 12)
        self.assertFalse(snapshot['redistribution_authorized'])
        with self.assertRaisesRegex(ValueError, 'redistribution'):
            validate(snapshot, today=DAY, approval={})
        approval = dict(redistribution_authorized=True, source_url=endpoint(DAY),
                        evidence_reference='synthetic publication review', reviewed_by='reviewer')
        self.assertEqual(validate(snapshot, today=DAY, approval=approval)['races'], 12)

    def test_conflicting_or_stale_detail_is_rejected(self):
        for field, value in (('name', '別選手'), ('captured_at', '2026-10-14T01:00:00+00:00')):
            rows = details()
            rows[0][field] = value
            self.assertEqual(self.collect(detail_rows=rows)['status'], 'DETAILS_INVALID')

    def test_duplicate_racer_or_motor_in_one_race_is_rejected(self):
        for field in ('racer_registration_id', 'motor_no'):
            rows = details()
            rows[1][field] = rows[0][field]
            self.assertEqual(self.collect(detail_rows=rows)['status'], 'DETAILS_INVALID')

    def test_live_clock_records_observation_after_fetch_and_rejects_midnight_crossing(self):
        def transport(url, **kwargs):
            return FetchResponse(html(), url, 200, 'text/html')
        for after, expected in ((NOW + timedelta(minutes=1), 'PARTIAL_INDEX_DETAILS_REQUIRED'),
                                (NOW + timedelta(days=1), 'DAY_INVALID')):
            with patch('race_ai.tokuyama_day_worker.datetime', wraps=datetime) as clock:
                clock.now.side_effect = [NOW, after]
                result = collect_tokuyama_day(DAY, rights=rights(), transport=transport)
            self.assertEqual(result['status'], expected)
            if expected == 'PARTIAL_INDEX_DETAILS_REQUIRED':
                self.assertEqual(result['first_observed_at'], after.isoformat())


class TransportTests(unittest.TestCase):
    def test_redirect_handler_never_follows_other_or_same_host(self):
        for target in (endpoint(DAY), 'https://evil.example/'):
            with self.assertRaises(SourceError):
                NoRedirects().redirect_request(None, None, 302, '', {}, target)

    def test_bad_endpoint_is_rejected_before_opener(self):
        with patch('race_ai.tokuyama_day_worker.request.build_opener') as opener:
            with self.assertRaises(SourceError):
                fetch_index('https://evil.example/')
            opener.assert_not_called()

    def test_one_fetch_reads_only_limit_plus_one_with_fixed_timeout(self):
        # A fake response is unavoidable here: the boundary under test is HTTP I/O.
        class Response:
            status = 200
            headers = {'Content-Type': 'text/html; charset=UTF-8'}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def geturl(self): return endpoint(DAY)
            def read(self, count):
                self.read_count = count
                return b'x' * count
        response = Response()
        with patch('race_ai.tokuyama_day_worker.request.build_opener') as opener:
            opener.return_value.open.return_value = response
            result = fetch_index(endpoint(DAY))
            self.assertEqual(response.read_count, MAX_BYTES + 1)
            self.assertEqual(len(result.body), MAX_BYTES + 1)
            self.assertEqual(opener.return_value.open.call_count, 1)
            self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'], TIMEOUT)


class DetailCollectionBridgeTests(unittest.TestCase):
    def test_detail_scope_required_and_normalized_metadata_is_joined(self):
        from race_ai.official_racelist_worker import source_scope
        from tests.test_official_racelist_adapter import fixture
        calls = []
        def index_transport(url, **bounds):
            return FetchResponse(html(), url, 200, 'text/html')
        def detail_transport(url, **bounds):
            from urllib.parse import parse_qs, urlsplit
            number = int(parse_qs(urlsplit(url).query)['rno'][0])
            calls.append(number)
            body = fixture(number=number)
            for lane in range(1, 7):
                body = body.replace(f'選手 {lane}', f'選手{number}-{lane}')
            return FetchResponse(body.encode(), url, 200, 'text/html')
        blocked = collect_tokuyama_day(DAY, rights=rights(), now=NOW,
            transport=index_transport, detail_rights=[], detail_transport=detail_transport)
        self.assertEqual(blocked['status'], 'DETAIL_SOURCE_RIGHTS_BLOCKED')
        self.assertEqual(calls, [])
        detail_rights = [RightsRecord('18', 'facts_ingest', 'allowed', source_scope('18'),
            NOW.isoformat(), 'synthetic detail scope approval', 'test reviewer')]
        result = collect_tokuyama_day(DAY, rights=rights(), now=NOW, transport=index_transport,
            detail_rights=detail_rights, detail_transport=detail_transport)
        self.assertEqual(result['status'], 'NORMALIZED_REQUIRES_PUBLICATION_APPROVAL')
        self.assertEqual(calls, list(range(1, 13)))
        snapshot = result['snapshot']
        self.assertEqual(len(snapshot['sources']), 13)
        self.assertEqual(snapshot['venues'][0]['races'][0]['closed_at'], '2026-10-15T08:03:00+09:00')
        first = snapshot['venues'][0]['races'][0]['boats'][0]
        self.assertEqual(first['boat_no'], 21)
        self.assertEqual(first['average_st'], 0.17)
        self.assertFalse(snapshot['redistribution_authorized'])
        approval = dict(redistribution_authorized=True, source_url=endpoint(DAY),
                        evidence_reference='synthetic index permission', reviewed_by='reviewer')
        with self.assertRaisesRegex(ValueError, 'source approval'):
            validate(snapshot, today=DAY, approval=approval)
        approval['source_approvals'] = [dict(redistribution_authorized=True,
            source_url=s['source_url'], evidence_reference='synthetic detail permission', reviewed_by='reviewer')
            for s in snapshot['sources'][1:]]
        self.assertEqual(validate(snapshot, today=DAY, approval=approval)['races'], 12)


if __name__ == '__main__':
    unittest.main()
