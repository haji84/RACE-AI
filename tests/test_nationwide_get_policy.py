"""Count fictional source requests without stopping at the former 45-GET cap."""
import hashlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import race_ai

ROOT = Path(__file__).resolve().parents[1]
PIN = str(ROOT / 'pr64-reference/race_ai')
if PIN not in race_ai.__path__:
    race_ai.__path__.append(PIN)
from scripts import boat_nationwide_ab_pilot as pilot
from race_ai import repeated_cycle


class Response(io.BytesIO):
    status = 200
    headers = {'content-type': 'text/html; charset=utf-8'}

    def __init__(self, url):
        super().__init__(b'fictional official body')
        self.url = url

    def geturl(self):
        return self.url


class Transport:
    def __init__(self):
        self.urls = []

    def open(self, req, *, timeout):
        self.urls.append(req.full_url)
        return Response(req.full_url)


class NationwideGetPolicyTests(unittest.TestCase):
    def test_sixty_real_get_calls_keep_count_and_response_past_former_cap(self):
        transport = Transport()
        with patch.object(pilot, 'requests_used', 0), \
             patch.object(pilot, 'SOURCE_GUARD', None), \
             patch.object(pilot.request, 'build_opener', return_value=transport), \
             patch.object(pilot.time, 'sleep'):
            for no in range(60):
                body, captured, digest = pilot.get(f'https://www.boatrace.jp/fictional/{no}')
                self.assertEqual(body, b'fictional official body')
                self.assertIsNotNone(captured.utcoffset())
                self.assertEqual(digest, hashlib.sha256(b'fictional official body').hexdigest())
            self.assertEqual(pilot.requests_used, 60)
            self.assertEqual(len(transport.urls), 60)

    def test_source_429_still_latches_guard_past_former_cap(self):
        now = datetime(2030, 4, 1, 3, 35, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'session.json'
            repeated_cycle.start(path, day='2030-04-01', run_id=99, now=now)
            guard = repeated_cycle.SourceGuard(path)
            for _ in range(46):
                guard.charge('forecast')
            transport = Transport()
            def reject(req, *, timeout):
                transport.urls.append(req.full_url)
                raise HTTPError(req.full_url, 429, 'fictional response', {}, None)
            with patch.object(pilot, 'requests_used', 46), \
                 patch.object(pilot, 'SOURCE_GUARD', guard), \
                 patch.object(pilot.request, 'build_opener') as opener:
                opener.return_value.open.side_effect = reject
                with self.assertRaises(HTTPError):
                    pilot.get('https://www.boatrace.jp/fictional/blocked')
                with self.assertRaisesRegex(ValueError, 'SOURCE_HTTP_429'):
                    pilot.get('https://www.boatrace.jp/fictional/no-retry')
                self.assertEqual(pilot.requests_used, 47)
            self.assertEqual(len(transport.urls), 1)
            self.assertEqual(repeated_cycle.load(path)['requests_used'], 47)

    def test_day_schedule_and_second_candidate_are_not_dropped_by_old_count(self):
        now = datetime(2030, 4, 1, 3, 35, tzinfo=timezone.utc)
        class FixedClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)
        day = now.astimezone(pilot.JST).date()
        prefix = day.strftime('%Y%m%d')
        schedule = {n: (now + timedelta(minutes=14+n)).astimezone(pilot.JST) for n in (1, 2)}
        def discovery(_day):
            pilot.requests_used = 46
            return {'active_venues': ['01']}, now, 'a'*64, 'https://www.boatrace.jp/fictional/index'
        def unavailable(_day, row):
            return {'race_id': row['race_id'], 'state': 'EXHIBITION_NOT_FULLY_PUBLISHED'}, None, None, None, None
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(pilot, 'OUTPUT', Path(folder)), \
             patch.object(pilot, 'datetime', FixedClock), \
             patch.object(pilot, 'official_schedule', side_effect=discovery), \
             patch.object(pilot, 'get', return_value=(b'fictional schedule', now, 'b'*64)), \
             patch.object(pilot, 'parse_official_racelist', return_value={'status': 'OFFICIAL_BODY_IDENTITY_VERIFIED'}), \
             patch.object(pilot, 'schedule_times', return_value=schedule), \
             patch.object(pilot, 'load_original_race_ids', return_value=frozenset()), \
             patch.object(pilot, 'make_pair', side_effect=unavailable), \
             patch.dict('os.environ', {'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED': 'true'}):
            result = pilot.run()
            self.assertEqual(result['reason'], 'NO_COMPLETE_EXHIBITION_IN_ORDERED_CANDIDATES')
            self.assertEqual(len(result['official_race_registry']), 2)
            self.assertEqual([x['race_id'] for x in result['candidate_attempts']],
                             [prefix+'-01-01', prefix+'-01-02'])
            self.assertEqual(result['source_request_count'], 46)
            self.assertIsNone(result['source_request_cap'])
            saved = json.loads((Path(folder)/'national.json').read_text())
            self.assertIsNone(saved['source_request_cap'])
