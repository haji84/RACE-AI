"""Result routes exercise real contracts and storage through bounded fake I/O."""
import copy
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from tests.test_exhibition_api import route, ClosingBlob
from tests import test_exhibition_api as api_helpers
from tests.test_name_bound_result_store import store_fixture
from web import race_contract as facts


class NameBoundResultApiTests(unittest.TestCase):
    handler = api_helpers.ExhibitionApiTests.handler

    def setUp(self):
        try:
            self.reader = route('name-bound-result.py','nb_result_read')
            self.writer = route('publish-name-bound-result.py','nb_result_write')
        except (FileNotFoundError,ModuleNotFoundError): self.reader=self.writer=None
        self.assertIsNotNone(self.reader,'separate result routes required')
        self.race,self.forecast,self.request,self.client,self.now=store_fixture(ClosingBlob())
        p=patch.dict('os.environ',{'BLOB_READ_WRITE_TOKEN':'synthetic-secret','VERCEL_ENV':'preview','VERCEL_GIT_COMMIT_SHA':'a'*40})
        p.start();self.addCleanup(p.stop)
        for module in (self.reader,self.writer):
            for target,value in [('utc_now',self.now),('load_feed',(200,dict(venues=[dict(races=[self.race])]))),('create_blob_client',self.client)]:
                p=patch.object(module,target,return_value=value);p.start();self.addCleanup(p.stop)
        p=patch.object(self.writer,'verify_github_oidc');p.start();self.addCleanup(p.stop)
        self.query='/api/name-bound-result?race_id='+self.race['race_id']+'&forecast_request_id=123499-1'

    def publish(self):
        h=self.handler(self.writer);h.do_POST();self.assertEqual(h.status,200,h.wfile.getvalue())
        return json.loads(h.wfile.getvalue())

    def test_publish_pinned_and_latest_get_return_full_canonical_envelope(self):
        original=copy.deepcopy(self.client.data);meta=self.publish();puts=len(self.client.puts)
        for query in (self.query,self.query+'&request_id=123500-1'):
            h=self.handler(self.reader,query);h.do_GET();self.assertEqual(h.status,200,h.wfile.getvalue())
            envelope=json.loads(h.wfile.getvalue());self.assertEqual(set(envelope),{'receipt','finalization'})
            self.assertEqual(h.wfile.getvalue(),facts.canonical(envelope))
            self.assertEqual(envelope['receipt']['snapshot'],self.request['snapshot'])
            self.assertEqual(envelope['receipt']['forecast_request_id'],'123499-1')
            self.assertEqual(meta['commit_sha'],'a'*40)
            for name,value in [('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('X-Robots-Tag','noindex')]:
                self.assertEqual(h.response_headers[name],value)
            self.assertEqual(int(h.response_headers['Content-Length']),len(h.wfile.getvalue()))
        self.assertEqual(self.client.closed,3);self.assertEqual(len(self.client.puts),puts)
        for key,raw in original.items():self.assertEqual(self.client.data[key],raw)
        self.assertFalse(hasattr(self.reader.handler,'do_POST'))

    def test_missing_label_and_own_forecast_are_distinct_fixed_404(self):
        for request_id in (None,'123500-1'):
            self.assertEqual(self.reader.load_name_bound_result(self.race['race_id'],'123499-1',request_id),
                (404,{'error':'NAME_BOUND_RESULT_NOT_SAVED'}))
        self.assertEqual(self.reader.load_name_bound_result(self.race['race_id'],'123498-1'),
            (404,{'error':'NAME_BOUND_PREDICTION_NOT_SAVED'}))
        self.assertEqual(self.client.puts,[]);self.assertEqual(self.client.closed,3)

    def test_duplicate_blank_extra_bad_nonce_overlong_and_max_three_queries_reject_before_load(self):
        invalid=['','?race_id','?race_id=x','?race_id=x&forecast_request_id=',
            '?race_id=x&forecast_request_id=../escape',self.query.split('?',1)[1]+'&request_id=',
            '?race_id=20261014-18-01&forecast_request_id=123499-1',
            self.query.split('?',1)[1]+'&request_id=123500-1&extra=x',
            self.query.split('?',1)[1]+'&forecast_request_id=123498-1',
            self.query.split('?',1)[1]+'&request_id=123500-1&request_id=123501-1','?'+('x'*300)]
        with patch.object(self.reader,'load_name_bound_result') as load:
            for query in invalid:
                if query and not query.startswith('?'):query='?'+query
                with self.subTest(query=query):
                    h=self.handler(self.reader,'/api/name-bound-result'+query);h.do_GET();self.assertEqual(h.status,400)
        load.assert_not_called()

    def test_preview_oidc_bearer_and_commit_gates_never_touch_program_or_blob(self):
        cases=[('production',404),('bearer',404),('oidc',404),('commit',409),('invalid_commit',409)]
        for mode,status in cases:
            h=self.handler(self.writer)
            env={'VERCEL_ENV':'production'} if mode=='production' else {}
            if mode=='bearer':h.headers['Authorization']=''
            if mode=='commit':h.headers['X-Race-AI-Commit']='b'*40
            if mode=='invalid_commit':env['VERCEL_GIT_COMMIT_SHA']='z'*40;h.headers['X-Race-AI-Commit']='z'*40
            with patch.dict('os.environ',env),patch.object(self.writer,'verify_github_oidc',side_effect=ValueError('private-secret') if mode=='oidc' else None),patch.object(self.writer,'load_feed') as feed:
                h.do_POST();self.assertEqual(h.status,status);feed.assert_not_called()
                self.assertNotIn(b'private-secret',h.wfile.getvalue())
        self.assertEqual(self.client.puts,[])

    def test_strict_json_fields_duplicates_types_constants_utf8_and_bound_never_write(self):
        invalid=[b'[]',b'null',b'{"race_id":"x","race_id":"y"}',b'{"x":NaN}',b'\xff',
            b'{"x":"\\ud800"}']
        for field,value in [('request_id',True),('forecast_request_id','../escape'),('publication_review','bad'),
                ('runner_saved_at',True),('snapshot',[]),('cloud_saved_at','x')]:
            invalid.append(json.dumps({**self.request,field:value}).encode())
        for raw in invalid:
            with self.subTest(raw=raw[:80]):
                h=self.handler(self.writer,body=raw);h.do_POST();self.assertEqual(h.status,422,h.wfile.getvalue())
        self.assertEqual(self.client.puts,[])

    def test_content_type_length_and_truncation_reject_before_program(self):
        for field,value,status in [('Content-Length','0',400),('Content-Length','256001',400),
                ('Content-Length','-1',400),('Content-Length','nope',422),('Content-Length','99',422),
                ('Content-Type','text/plain',400)]:
            h=self.handler(self.writer,body=b'{}');h.headers[field]=value
            with patch.object(self.writer,'load_feed') as feed:
                h.do_POST();self.assertEqual(h.status,status);feed.assert_not_called()
        self.assertEqual(self.client.puts,[])

    def test_bad_forecast_or_separate_label_is_422_and_transport_failure_503(self):
        self.publish();key=f'race-ai/name-bound-result-latest/{self.race["race_id"]}/123499-1.json'
        self.client.data[key]=b'null'
        self.assertEqual(self.reader.load_name_bound_result(self.race['race_id'],'123499-1'),
            (422,{'error':'NAME_BOUND_RESULT_DATA_REJECTED'}))
        with patch.object(self.client,'get',side_effect=OSError('private-secret')):
            self.assertEqual(self.reader.load_name_bound_result(self.race['race_id'],'123499-1'),
                (503,{'error':'NAME_BOUND_RESULT_STORE_UNAVAILABLE'}))
            h=self.handler(self.writer);h.do_POST();self.assertEqual((h.status,json.loads(h.wfile.getvalue())),
                (503,{'error':'NAME_BOUND_RESULT_PUBLICATION_FAILED'}))
        self.assertEqual(self.client.closed,4)

    def test_program_and_parent_unavailable_fail_closed_and_client_closes(self):
        for module in (self.reader,self.writer):
            with patch.object(module,'load_feed',return_value=(503,{})),patch.object(module,'create_blob_client') as create:
                if module is self.reader:status,data=module.load_name_bound_result(self.race['race_id'],'123499-1')
                else:
                    h=self.handler(module);h.do_POST();status,data=h.status,json.loads(h.wfile.getvalue())
                self.assertEqual((status,data),(503,{'error':'DAY_PROGRAM_UNAVAILABLE'}));create.assert_not_called()
        del self.client.data[f'race-ai/name-bound-receipts/{self.race["race_id"]}/123499-1.json']
        h=self.handler(self.writer);h.do_POST();self.assertEqual(h.status,422)
        self.assertEqual(self.client.closed,1);self.assertEqual(self.client.puts,[])

    def test_postread_midnight_and_preclose_present_label_reject(self):
        self.publish()
        midnight=self.now.astimezone(facts.JST).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
        with patch.object(self.reader,'utc_now',side_effect=[self.now,self.now,self.now,midnight]):
            self.assertEqual(self.reader.load_name_bound_result(self.race['race_id'],'123499-1'),
                (422,{'error':'NAME_BOUND_RESULT_DATA_REJECTED'}))
        with patch.object(self.reader,'utc_now',return_value=facts._time(self.race['closed_at'])-timedelta(seconds=1)):
            self.assertEqual(self.reader.load_name_bound_result(self.race['race_id'],'123499-1')[0],422)

    def test_final_get_clock_rollback_revalidates_complete_label(self):
        self.publish()
        preclose=facts._time(self.race['closed_at'])-timedelta(microseconds=1)
        for final in (preclose,self.now-timedelta(microseconds=1)):
            with self.subTest(final=final),patch.object(self.reader,'utc_now',side_effect=[self.now,self.now,self.now,final]):
                self.assertEqual(self.reader.load_name_bound_result(self.race['race_id'],'123499-1'),
                    (422,{'error':'NAME_BOUND_RESULT_DATA_REJECTED'}))

    def test_post_midnight_after_store_cannot_return_success_and_get_requires_post(self):
        midnight=self.now.astimezone(facts.JST).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
        with patch.object(self.writer,'publish_name_bound_result',return_value={}),patch.object(self.writer,'utc_now',side_effect=[self.now,self.now,midnight]):
            h=self.handler(self.writer);h.do_POST();self.assertEqual(h.status,422)
        h=self.handler(self.writer);h.do_GET();self.assertEqual(h.status,405)
        self.assertEqual(h.response_headers['Cache-Control'],'no-store')

    def test_publisher_feed_and_final_response_clock_rollback_reject(self):
        earlier=self.now-timedelta(microseconds=1)
        for clocks in ([self.now,earlier,self.now],[self.now,self.now,earlier]):
            with self.subTest(clocks=clocks),patch.object(self.writer,'publish_name_bound_result',return_value={}),patch.object(self.writer,'utc_now',side_effect=clocks):
                h=self.handler(self.writer);h.do_POST()
                self.assertEqual((h.status,json.loads(h.wfile.getvalue())),
                    (422,{'error':'NAME_BOUND_RESULT_PUBLICATION_REJECTED'}))


if __name__=='__main__':unittest.main()
