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
from race_ai.source_retry_policy import SourceWait, plan_http_wait


NOW = datetime(2030, 4, 1, 3, 35, tzinfo=timezone.utc)


class FixedClock(datetime):
    current = NOW

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz is not None else cls.current.replace(tzinfo=None)


def schedule_snapshot(count=7):
    return dict(official_day_source=dict(captured_at=NOW.isoformat(),source_sha256='a'*64,
                url='https://www.boatrace.jp/owpc/pc/race/index?hd=20300401'),
        verified_active_venues=['01'],
        official_race_registry=[dict(race_id=f'20300401-01-{n:02d}',
            cutoff_at=(NOW+timedelta(minutes=13,seconds=n)).astimezone(pilot.JST).isoformat(),
            schedule_captured_at=NOW.isoformat(),source_sha256='b'*64) for n in range(1,count+1)])


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
    def setUp(self):
        FixedClock.current=NOW

    def test_verified_pending_schedule_reserves_gets_for_later_p1_races(self):
        snapshot=schedule_snapshot(3)
        chosen=[]
        class ReadyGuard:
            def remaining(self):return 5
        def candidate(day,row,**options):
            chosen.append((row['race_id'],options['reserved_next_gets']))
            return dict(race_id=row['race_id'],state='AB_GENERATED_NOT_YET_EXTERNAL_FROZEN'), \
                   dict(race_id=row['race_id']),None,None,None
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(pilot,'OUTPUT',Path(folder)), \
             patch.object(pilot,'datetime',FixedClock), \
             patch.object(pilot,'SOURCE_GUARD',ReadyGuard()), \
             patch.object(pilot,'make_pair',side_effect=candidate), \
             patch.object(pilot,'load_original_race_ids',return_value=frozenset()), \
             patch.object(pilot,'MODEL_INPUT_SINK',None), \
             patch.object(pilot,'ISSUED_MODELS',None), \
             patch.dict('os.environ',{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true',
                                      'RACE_AI_EVENT_DAY':'2030-04-01'}):
            result=pilot.run(schedule_snapshot=snapshot)
        self.assertEqual(len(result['candidate_attempts']),3)
        self.assertEqual([n for _,n in chosen],[4,2,0])
        self.assertEqual(result['paired_forecast_count'],3)

    def test_optional_forecast_gets_require_proved_residual_budget(self):
        class Budget:
            def __init__(self,left):self.left=left
            def remaining(self):return self.left
        for left,reserve,expected in ((240,310,False),(240,4,True),
                                      (4,4,False),(5,4,True),(0,0,False)):
            with self.subTest(left=left,reserve=reserve),patch.object(pilot,'SOURCE_GUARD',Budget(left)):
                self.assertEqual(pilot._optional_source_allowed(reserve),expected)
        with patch.object(pilot,'SOURCE_GUARD',None):
            self.assertTrue(pilot._optional_source_allowed(100))
        with self.assertRaisesRegex(ValueError,'OPTIONAL_SOURCE_RESERVATION_INVALID'):
            pilot._optional_source_allowed(-1)

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
            guard = repeated_cycle.SourceGuard(path, clock=lambda: now)
            for _ in range(46):
                guard.charge('forecast')
            transport = Transport()
            def reject(req, *, timeout):
                transport.urls.append(req.full_url)
                raise HTTPError(req.full_url, 429, 'fictional response', {'Retry-After':'1200'}, None)
            with patch.object(pilot, 'requests_used', 46), \
                 patch.object(pilot, 'SOURCE_GUARD', guard), \
                 patch.object(pilot, 'datetime', FixedClock), \
                 patch.object(pilot.request, 'build_opener') as opener:
                opener.return_value.open.side_effect = reject
                with self.assertRaises(SourceWait) as waiting:
                    pilot.get('https://www.boatrace.jp/fictional/blocked')
                self.assertEqual(waiting.exception.retry_at,(NOW+timedelta(minutes=20)).isoformat())
                with self.assertRaisesRegex(SourceWait, 'HTTP_RATE_LIMIT'):
                    pilot.get('https://www.boatrace.jp/fictional/no-retry')
                self.assertEqual(pilot.requests_used, 47)
            self.assertEqual(len(transport.urls), 1)
            self.assertEqual(repeated_cycle.load(path)['requests_used'], 47)

    def test_preview_404_wait_does_not_pause_other_race_origin(self):
        class PendingTransport(Transport):
            def open(self,req,*,timeout):
                self.urls.append(req.full_url)
                if 'beforeinfo' in req.full_url:
                    raise HTTPError(req.full_url,404,'not yet',{},None)
                return Response(req.full_url)
        transport=PendingTransport()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'session.json'
            repeated_cycle.start(path,day='2030-04-01',run_id=99,now=NOW)
            guard=repeated_cycle.SourceGuard(path,clock=lambda:NOW)
            with patch.object(pilot,'SOURCE_GUARD',guard),patch.object(pilot,'requests_used',0), \
                 patch.object(pilot,'datetime',FixedClock),patch.object(pilot.time,'sleep'), \
                 patch.object(pilot.request,'build_opener',return_value=transport):
                with self.assertRaises(SourceWait) as waiting:
                    pilot.get('https://www.boatrace.jp/fictional/beforeinfo',not_yet_published=True)
                self.assertEqual(waiting.exception.state,'WAITING_PUBLICATION')
                body,_,_=pilot.get('https://www.boatrace.jp/fictional/other-race')
                self.assertEqual(body,b'fictional official body')
            self.assertEqual(repeated_cycle.load(path)['requests_used'],2)
            self.assertIsNone(repeated_cycle.load(path).get('source_wait'))

    def test_day_schedule_and_second_candidate_are_not_dropped_by_old_count(self):
        now = datetime(2030, 4, 1, 3, 35, tzinfo=timezone.utc)
        class FixedClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)
        day = now.astimezone(pilot.JST).date()
        prefix = day.strftime('%Y%m%d')
        schedule = {n: (now + timedelta(minutes=12+n)).astimezone(pilot.JST) for n in (1, 2)}
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

    def test_all_due_candidates_survive_incomplete_earlier_races(self):
        snapshot=schedule_snapshot()
        def candidate(day,row):
            rid=row['race_id']
            if rid.endswith(('01','02')):
                return {'race_id':rid,'state':'EXHIBITION_NOT_FULLY_PUBLISHED'},None,None,None,None
            return {'race_id':rid,'state':'AB_GENERATED_NOT_YET_EXTERNAL_FROZEN'}, {'race_id':rid},None,None,None
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(pilot,'OUTPUT',Path(folder)),patch.object(pilot,'datetime',FixedClock), \
             patch.object(pilot,'make_pair',side_effect=candidate), \
             patch.object(pilot,'load_original_race_ids',return_value=frozenset()), \
             patch.dict('os.environ',{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true','RACE_AI_EVENT_DAY':'2030-04-01'}):
            result=pilot.run(schedule_snapshot=snapshot)
        self.assertEqual(result['paired_forecast_count'],5)
        self.assertEqual(len(result['candidate_attempts']),7)
        self.assertEqual(result['deadline_targets']['due_races'],7)
        self.assertEqual(len(result['candidate_source_waits']),2)
        self.assertFalse(result['external_artifact_preclose_verified'])

    def test_pending_race_wait_skips_only_that_race_then_rechecks_at_t10(self):
        snapshot=schedule_snapshot(2)
        pending=plan_http_wait(200,{},NOW,not_yet_published=True)
        pending.update(race_id='20300401-01-01',cutoff_at=snapshot['official_race_registry'][0]['cutoff_at'])
        snapshot['candidate_source_waits']=[pending]
        def candidate(day,row):
            return {'race_id':row['race_id'],'state':'AB_GENERATED_NOT_YET_EXTERNAL_FROZEN'}, {'race_id':row['race_id']},None,None,None
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(pilot,'OUTPUT',Path(folder)),patch.object(pilot,'datetime',FixedClock), \
             patch.object(pilot,'make_pair',side_effect=candidate), \
             patch.object(pilot,'load_original_race_ids',return_value=frozenset()), \
             patch.dict('os.environ',{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true','RACE_AI_EVENT_DAY':'2030-04-01'}):
            result=pilot.run(schedule_snapshot=snapshot)
        self.assertEqual([p['race_id'] for p in result['paired_forecasts']],['20300401-01-02'])
        self.assertEqual(result['next_check_at'],pending['retry_at'])
        self.assertEqual(result['candidate_source_waits'][0]['race_id'],'20300401-01-01')

    def test_server_retry_after_is_global_wait_without_trying_another_candidate(self):
        snapshot=schedule_snapshot(2)
        retry=(NOW+timedelta(minutes=20)).isoformat()
        def waiting(day,row):
            raise SourceWait('HTTP_RATE_LIMIT',retry,state='RATE_LIMIT_WAIT')
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(pilot,'OUTPUT',Path(folder)),patch.object(pilot,'datetime',FixedClock), \
             patch.object(pilot,'make_pair',side_effect=waiting), \
             patch.object(pilot,'load_original_race_ids',return_value=frozenset()), \
             patch.dict('os.environ',{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true','RACE_AI_EVENT_DAY':'2030-04-01'}):
            result=pilot.run(schedule_snapshot=snapshot)
        self.assertEqual(len(result['candidate_attempts']),1)
        self.assertEqual(result['reason'],'HTTP_RATE_LIMIT')
        self.assertEqual(result['source_wait']['state'],'RATE_LIMIT_WAIT')
        self.assertEqual(result['next_check_at'],retry)
        self.assertEqual(result['paired_forecast_count'],0)

    def test_pinned_event_day_handoff_aborts_before_source(self):
        transport=Transport()
        with patch.object(pilot,'datetime',FixedClock), \
             patch.object(pilot.request,'build_opener',return_value=transport), \
             patch.dict('os.environ',{'RACE_AI_EVENT_DAY':'2030-03-31'}):
            with self.assertRaisesRegex(ValueError,'DAY_HANDOFF'):
                pilot.get('https://www.boatrace.jp/fictional/not-requested')
        self.assertEqual(transport.urls,[])

    def test_publication_retry_reaches_t10_once_then_stays_in_future(self):
        row=dict(race_id='20300401-01-01',cutoff_at='2030-04-01T12:48:00+09:00')
        delayed=plan_http_wait(200,{},NOW,attempt=2,not_yet_published=True)
        first=pilot._publication_wait(row,NOW,delayed)
        self.assertEqual(datetime.fromisoformat(first['retry_at']),
                         datetime(2030,4,1,3,38,tzinfo=timezone.utc))
        final=NOW+timedelta(minutes=3)
        second=pilot._publication_wait(row,final)
        self.assertEqual(datetime.fromisoformat(second['retry_at']),
                         datetime(2030,4,1,3,41,tzinfo=timezone.utc))

    def test_inflight_429_retains_server_wait_across_midnight(self):
        FixedClock.current=datetime(2030,4,1,14,59,59,tzinfo=timezone.utc)
        class MidnightTransport(Transport):
            def open(self,req,*,timeout):
                self.urls.append(req.full_url)
                FixedClock.current=datetime(2030,4,1,15,0,1,tzinfo=timezone.utc)
                raise HTTPError(req.full_url,429,'wait',{'Retry-After':'3600'},None)
        transport=MidnightTransport()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'session.json'
            repeated_cycle.start(path,day='2030-04-01',run_id=99,now=FixedClock.current)
            guard=repeated_cycle.SourceGuard(path,clock=lambda:FixedClock.current)
            with patch.object(pilot,'datetime',FixedClock),patch.object(pilot,'SOURCE_GUARD',guard), \
                 patch.object(pilot,'requests_used',0), \
                 patch.object(pilot.request,'build_opener',return_value=transport), \
                 patch.dict('os.environ',{'RACE_AI_EVENT_DAY':'2030-04-01'}):
                with self.assertRaises(SourceWait) as waiting:
                    pilot.get('https://www.boatrace.jp/fictional/inflight')
                self.assertEqual(waiting.exception.reason,'HTTP_RATE_LIMIT')
            saved=repeated_cycle.load(path)
            self.assertEqual(saved['requests_used'],1)
            self.assertEqual(saved['source_wait']['retry_at'],'2030-04-01T16:00:01+00:00')

    def test_publication_response_after_day_rollover_returns_handoff_artifact(self):
        snapshot=schedule_snapshot(1)
        def midnight(day,row):
            FixedClock.current=NOW+timedelta(days=1)
            raise pilot._PublicationWait(plan_http_wait(404,{},FixedClock.current,not_yet_published=True))
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(pilot,'OUTPUT',Path(folder)),patch.object(pilot,'datetime',FixedClock), \
             patch.object(pilot,'make_pair',side_effect=midnight), \
             patch.object(pilot,'load_original_race_ids',return_value=frozenset()), \
             patch.dict('os.environ',{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true','RACE_AI_EVENT_DAY':'2030-04-01'}):
            result=pilot.run(schedule_snapshot=snapshot)
        self.assertEqual(result['reason'],'DAY_HANDOFF')
        self.assertEqual(result['paired_forecast_count'],0)
        self.assertIsNone(result['next_check_at'])

    def test_worker_handoff_preserves_generated_pairs_without_requesting_later_races(self):
        def candidate(day,row):
            if row['race_id'].endswith('02'):raise ValueError('WORKER_HANDOFF')
            return {'race_id':row['race_id'],'state':'AB_GENERATED_NOT_YET_EXTERNAL_FROZEN'}, {'race_id':row['race_id']},None,None,None
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(pilot,'OUTPUT',Path(folder)),patch.object(pilot,'datetime',FixedClock), \
             patch.object(pilot,'make_pair',side_effect=candidate), \
             patch.object(pilot,'load_original_race_ids',return_value=frozenset()), \
             patch.dict('os.environ',{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true','RACE_AI_EVENT_DAY':'2030-04-01'}):
            result=pilot.run(schedule_snapshot=schedule_snapshot(3))
        self.assertEqual(result['reason'],'WORKER_HANDOFF')
        self.assertEqual(result['paired_forecast_count'],1)
        self.assertEqual(len(result['candidate_attempts']),2)
        self.assertEqual(result['candidate_attempts'][-1]['state'],'WORKER_HANDOFF')
        self.assertIsNone(result['next_check_at'])

    def test_worker_handoff_before_discovery_is_control_not_source_rejection(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(pilot,'OUTPUT',Path(folder)),patch.object(pilot,'datetime',FixedClock), \
             patch.object(pilot,'official_schedule',side_effect=ValueError('WORKER_HANDOFF')), \
             patch.dict('os.environ',{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true','RACE_AI_EVENT_DAY':'2030-04-01'}):
            result=pilot.run()
        self.assertEqual(result['reason'],'WORKER_HANDOFF')
        self.assertEqual(result['source_request_count'],0)
