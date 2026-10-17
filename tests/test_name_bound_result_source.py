"""Only transport and measured clocks are controlled; parser/store are real."""
import copy
from datetime import timedelta
import importlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import URLError

from tests.test_name_bound_evaluation import fixture
from tests.test_official_race_updates import page, results
from race_ai import official_observation_store as memory
from race_ai.tokuyama_day_worker import FetchResponse
from web import race_contract as facts

ROOT=Path(__file__).resolve().parents[1]


class NameBoundResultSourceTests(unittest.TestCase):
    def setUp(self):
        try:self.c=importlib.import_module('race_ai.name_bound_result_source')
        except ModuleNotFoundError:self.c=None
        self.assertIsNotNone(self.c,'one-source result worker required')
        self.race,self.forecast,_,self.now=fixture();self.calls=[]
        self.review=json.loads((ROOT/'config/operator-official-facts.json').read_text(encoding='utf-8'))
        self.review['reviewed_at']=facts.stamp(self.now-timedelta(hours=1))

    def collect(self, *, body=None, clocks=None, saved_at=None, failure=None, response=None, **kw):
        ticks=iter(clocks) if clocks is not None else None
        raw=page('raceresult',(results() if body is None else body).replace('選手1','松田 大志郎'))
        def transport(url,**options):
            self.calls.append((url,options))
            if failure:raise failure
            return response if response is not None else FetchResponse(raw,url,200,'text/html; charset=utf-8')
        with patch.object(memory,'utc_now',return_value=self.now if saved_at is None else saved_at):
            return self.c.collect_name_bound_result(self.race,self.forecast,
                parents_read_at=kw.pop('parents_read_at',facts._time(self.race['closed_at'])),facts_review=kw.pop('facts_review',self.review),
                execute=kw.pop('execute',True),transport=transport,clock=(lambda:next(ticks)) if ticks is not None else (lambda:self.now),**kw)

    def test_dryrun_never_reads_clock_or_calls_transport_even_with_invalid_input(self):
        def forbidden():raise AssertionError('dryrun read clock')
        self.assertEqual(self.c.collect_name_bound_result(None,None,parents_read_at=None,facts_review=None,
            execute=False,transport=forbidden,clock=forbidden),dict(status='DRY_RUN',official_source_requests=0))
        self.assertEqual(self.calls,[])

    def test_one_exact_get_captures_after_response_and_preserves_actual_memory_clock(self):
        old=copy.deepcopy((self.race,self.forecast));start=self.now
        times=[start+timedelta(milliseconds=n*100) for n in range(5)]
        result=self.collect(clocks=times,saved_at=start+timedelta(milliseconds=250))
        self.assertEqual((result['status'],result['official_source_requests']),('COLLECTED',1))
        self.assertEqual(self.calls,[(facts._endpoint(self.race['race_id'],'raceresult'),dict(timeout=10,max_bytes=1000000))])
        packet=result['snapshot'];record=packet['result_record']
        self.assertEqual(record['captured_at'],facts.stamp(times[2]))
        self.assertEqual(record['saved_at'],facts.stamp(start+timedelta(milliseconds=250)))
        self.assertEqual(packet['generated_at'],facts.stamp(times[4]))
        self.assertEqual((self.race,self.forecast),old)
        self.assertEqual(record['data']['results'][0]['name'],'松田 大志郎')
        self.assertEqual(record['data']['payouts'][0]['payout_per_100_yen'],610)
        self.assertNotIn('<html',repr(result));self.assertNotIn('<table',repr(result))

    def test_rights_parent_and_input_fail_before_transport(self):
        for kw,status in [(dict(facts_review={}),'RIGHTS_BLOCKED'),
                (dict(facts_review={**self.review,'evidence_reference':'other'}),'RIGHTS_BLOCKED'),
                (dict(parents_read_at=self.now+timedelta(seconds=1)),'INPUT_INVALID'),
                (dict(parents_read_at=facts._time(self.race['closed_at'])-timedelta(microseconds=1)),'INPUT_INVALID'),
                (dict(parents_read_at=self.now.replace(tzinfo=None)),'INPUT_INVALID'),
                (dict(clocks=[self.now+timedelta(days=1)]),'DAY_INVALID'),
                (dict(clocks=[facts._time(self.race['closed_at'])-timedelta(microseconds=1)]),'CUTOFF_NOT_REACHED')]:
            self.calls=[]
            with self.subTest(kw=kw):self.assertEqual(self.collect(**kw),dict(status=status,official_source_requests=0));self.assertEqual(self.calls,[])
        self.forecast['name_binding']['finalization']['receipt_sha256']='0'*64
        self.assertEqual(self.collect(),dict(status='INPUT_INVALID',official_source_requests=0));self.assertEqual(self.calls,[])

    def test_exact_close_is_allowed_and_clock_is_rechecked_before_get(self):
        close=facts._time(self.race['closed_at'])
        self.now=close
        self.assertEqual(self.collect()['status'],'COLLECTED')
        self.calls=[]
        self.assertEqual(self.collect(clocks=[close,close-timedelta(microseconds=1)]),dict(status='SOURCE_INVALID',official_source_requests=0))
        self.assertEqual(self.calls,[])

    def test_pending_empty_postponed_and_cancelled_stop_after_one_without_packet(self):
        for body in ('<p>結果はまだありません。</p>','<p>データがありません。</p>',
                '<span class="heading1_mainLabel">レース延期</span>','<span class="heading1_mainLabel">レース中止</span>'):
            self.calls=[]
            with self.subTest(body=body):
                self.assertEqual(self.collect(body=body),dict(status='RESULT_PENDING',official_source_requests=1));self.assertEqual(len(self.calls),1)

    def test_transport_exceptions_count_attempt_and_never_leak_error_or_retry(self):
        for failure,status in [(URLError('PRIVATE'),'SOURCE_UNAVAILABLE'),(TimeoutError('PRIVATE'),'SOURCE_UNAVAILABLE'),
                (ValueError('PRIVATE'),'SOURCE_INVALID'),(TypeError('PRIVATE'),'SOURCE_INVALID')]:
            self.calls=[]
            with self.subTest(failure=failure):self.assertEqual(self.collect(failure=failure),dict(status=status,official_source_requests=1));self.assertEqual(len(self.calls),1)

    def test_response_url_mime_bytes_status_size_and_body_identity_fail_closed(self):
        url=facts._endpoint(self.race['race_id'],'raceresult')
        raw=page('raceresult',results().replace('選手1','松田 大志郎'))
        responses=[FetchResponse(raw,url+'#redirect',200,'text/html'),FetchResponse(raw,url,200,'application/json'),
            FetchResponse(raw,url,True,'text/html'),FetchResponse(raw,url,302,'text/html'),FetchResponse('',url,200,'text/html'),
            FetchResponse(b'',url,200,'text/html'),FetchResponse(b'x'*1000001,url,200,'text/html'),
            FetchResponse(raw.replace(b'4001',b'4999'),url,200,'text/html'),
            FetchResponse(raw.replace('松田 大志郎'.encode(),'松田大志'.encode()),url,200,'text/html'),
            FetchResponse(raw.replace(b'20261015',b'20261014'),url,200,'text/html')]
        for response in responses:
            self.calls=[]
            with self.subTest(response_status=response.status):self.assertEqual(self.collect(response=response),dict(status='SOURCE_INVALID',official_source_requests=1));self.assertEqual(len(self.calls),1)

    def test_day_rollback_unaware_and_memory_clock_do_not_get_repaired(self):
        for ticks,status in [([self.now,self.now,self.now-timedelta(seconds=1)],'SOURCE_INVALID'),
                ([self.now,self.now,self.now+timedelta(days=1)],'DAY_INVALID'),
                ([self.now.replace(tzinfo=None)],'DAY_INVALID'),
                ([self.now,self.now,self.now.replace(tzinfo=None)],'SOURCE_INVALID')]:
            self.calls=[]
            with self.subTest(ticks=ticks):self.assertEqual(self.collect(clocks=ticks),dict(status=status,official_source_requests=0 if len(ticks)==1 else 1))
        for saved_at in (self.now-timedelta(microseconds=1),self.now+timedelta(seconds=1),self.now+timedelta(days=1),self.now.replace(tzinfo=None)):
            self.calls=[]
            with self.subTest(saved_at=saved_at):self.assertEqual(self.collect(saved_at=saved_at),dict(status='SOURCE_INVALID',official_source_requests=1))


if __name__=='__main__':unittest.main()
