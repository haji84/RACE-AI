"""Read-only route integration uses synthetic immutable Blob objects only."""
import copy
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from tests.test_name_bound_evaluation import fixture
from tests.test_exhibition_api import route, ClosingBlob
from tests import test_exhibition_api as api_helpers
from tests.test_exhibition_store import seed_baseline
from web import race_contract as facts


class ReadOnlyBlob(ClosingBlob):
    def __init__(self): super().__init__(); self.reads = []
    def get(self, key, **kwargs):
        self.reads.append(key)
        return super().get(key, **kwargs)
    def put(self, *args, **kwargs): raise AssertionError('evaluation must never write')


def seed(client, forecast, bundle):
    """Seed immutable versions, while unrelated latest pointers are malformed."""
    race_id = forecast['receipt']['snapshot']['race_id']
    seed_baseline(client,forecast['baseline'])
    for name in ('prediction','name-binding','name-bound-exhibition'):
        client.data[f'race-ai/{name}/{race_id}.json'] = b'{"unrelated_latest":"invalid"}'
    for namespace,envelope in (('name-binding',forecast['name_binding']),('name-bound',forecast)):
        receipt = envelope['receipt']; nonce = receipt['request_id']; snapshot = receipt['snapshot']
        client.data[f'race-ai/{namespace}-receipts/{race_id}/{nonce}.json'] = facts.canonical(receipt)
        client.data[f'race-ai/{namespace}-finalizations/{race_id}/{nonce}.json'] = facts.canonical(envelope['finalization'])
        versions = 'name-binding-versions' if namespace=='name-binding' else 'name-bound-predictions'
        client.data[f'race-ai/{versions}/{race_id}/{snapshot["snapshot_id"]}.json'] = facts.canonical(snapshot)
    client.data[f'race-ai/name-bound-inputs/{race_id}/{forecast["inputs"]["snapshot_id"]}.json'] = facts.canonical(forecast['inputs'])
    if bundle is not None:
        client.data[f'race-ai/races/{race_id}.json'] = facts.canonical({k:v for k,v in bundle.items() if k!='records'})
        for receipt in bundle['records']:
            snapshot = receipt['record']['snapshot_id']
            client.data[f'race-ai/observations/{race_id}/{snapshot}.json'] = facts.canonical(receipt['record'])
            client.data[f'race-ai/receipts/{race_id}/{snapshot}.json'] = facts.canonical(receipt)


class NameBoundEvaluationApiTests(unittest.TestCase):
    handler = api_helpers.ExhibitionApiTests.handler

    @classmethod
    def setUpClass(cls):
        try: cls.api = route('name-bound-evaluation.py','name_bound_evaluation_route')
        except (FileNotFoundError,ModuleNotFoundError): cls.api = None

    def setUp(self):
        self.assertIsNotNone(self.api, 'separate read-only name-bound evaluation route required')
        self.race,self.forecast,self.bundle,self.now = fixture()
        self.client = ReadOnlyBlob(); seed(self.client,self.forecast,self.bundle)
        self.request = {}
        self.query = '/api/name-bound-evaluation?race_id='+self.race['race_id']+'&forecast_request_id=123499-1'
        for patcher in (patch.dict('os.environ',{'BLOB_READ_WRITE_TOKEN':'synthetic-secret'}),
                patch.object(self.api,'utc_now',return_value=self.now),
                patch.object(self.api,'load_feed',return_value=(200,dict(venues=[dict(races=[self.race])]))),
                patch.object(self.api,'create_blob_client',return_value=self.client)):
            patcher.start(); self.addCleanup(patcher.stop)

    def test_real_pinned_forecast_and_projected_result_read_ignore_all_other_latest(self):
        before = copy.deepcopy((self.race,self.forecast,self.bundle,self.client.data))
        original_read = self.api.read_current_race
        captured = []
        def read(projected, **kwargs):
            self.assertIsNot(projected,self.race)
            self.assertEqual(projected['boats'][0]['name'],'松田 大志郎')
            captured.append(projected)
            return original_read(projected,**kwargs)
        with patch.object(self.api,'read_current_race',side_effect=read):
            h = self.handler(self.api,self.query); h.do_GET()
        self.assertEqual(h.status,200,h.wfile.getvalue())
        report = json.loads(h.wfile.getvalue())
        self.assertEqual(report['status'],'EVALUATED')
        self.assertEqual(report['forecast_proof']['request_id'],'123499-1')
        self.assertEqual((self.race,self.forecast,self.bundle,self.client.data),before)
        self.assertEqual(len(captured),1)
        for key in self.client.reads:
            self.assertNotIn(key,[f'race-ai/{n}/{self.race["race_id"]}.json' for n in ('prediction','name-binding','name-bound-exhibition')])
        self.assertEqual(self.client.closed,1)
        self.assertEqual(self.client.puts,[])
        self.assertEqual(h.wfile.getvalue(),facts.canonical(report))
        for name,value in [('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('X-Robots-Tag','noindex')]:
            self.assertEqual(h.response_headers[name],value)
        self.assertEqual(int(h.response_headers['Content-Length']),len(h.wfile.getvalue()))
        self.assertFalse(hasattr(self.api.handler,'do_POST'))

    def test_exact_two_queries_reject_duplicates_extra_blank_bad_nonce_and_asof(self):
        invalid = ['', '?race_id=x', '?race_id=x&forecast_request_id=', '?race_id=x&forecast_request_id=../escape',
            '?race_id=x&forecast_request_id=123499-1&as_of=x', '?race_id=x&race_id=y',
            self.query.split('/api/name-bound-evaluation')[1]+'&forecast_request_id=123500-1',
            '?race_id=20261014-18-01&forecast_request_id=123499-1', '?race_id', '?'+('x'*500)]
        with patch.object(self.api,'load_name_bound_evaluation') as load:
            for query in invalid:
                with self.subTest(query=query):
                    h=self.handler(self.api,'/api/name-bound-evaluation'+query); h.do_GET(); self.assertEqual(h.status,400)
        load.assert_not_called()

    def test_exact_nonce_missing_is_404_without_result_read(self):
        with patch.object(self.api,'read_current_race') as read:
            status,data=self.api.load_name_bound_evaluation(self.race['race_id'],'123500-1')
        self.assertEqual((status,data),(404,{'error':'NAME_BOUND_PREDICTION_NOT_SAVED'}))
        read.assert_not_called(); self.assertEqual(self.client.closed,1)

    def test_missing_result_returns_informative_empty_state(self):
        del self.client.data[f'race-ai/races/{self.race["race_id"]}.json']
        status,report=self.api.load_name_bound_evaluation(self.race['race_id'],'123499-1')
        self.assertEqual((status,report['status'],report['models']),(200,'RESULT_NOT_OBTAINED',[]))

    def test_errors_are_sanitized_and_always_close_client(self):
        for error,status,code in [(ValueError('secret'),422,'NAME_BOUND_EVALUATION_DATA_REJECTED'),
                (OSError('secret'),503,'NAME_BOUND_EVALUATION_STORE_UNAVAILABLE')]:
            self.client.closed=0
            with self.subTest(error=error),patch.object(self.api,'read_name_bound_exhibition',side_effect=error):
                self.assertEqual(self.api.load_name_bound_evaluation(self.race['race_id'],'123499-1'),(status,{'error':code}))
            self.assertEqual(self.client.closed,1)
        with patch.object(self.api,'load_feed',return_value=(503,{})),patch.object(self.api,'create_blob_client') as create:
            self.assertEqual(self.api.load_name_bound_evaluation(self.race['race_id'],'123499-1'),(503,{'error':'DAY_PROGRAM_UNAVAILABLE'}))
        create.assert_not_called()

    def test_fresh_postread_clock_and_midnight_crossing(self):
        final=self.now+timedelta(microseconds=1)
        with patch.object(self.api,'utc_now',side_effect=[self.now,self.now,self.now,self.now,final]):
            status,report=self.api.load_name_bound_evaluation(self.race['race_id'],'123499-1')
        self.assertEqual(status,200); self.assertEqual(report['as_of'],facts.stamp(final))
        midnight=self.now.astimezone(facts.JST).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
        with patch.object(self.api,'utc_now',side_effect=[self.now,self.now,self.now,self.now,midnight]):
            self.assertEqual(self.api.load_name_bound_evaluation(self.race['race_id'],'123499-1'),(422,{'error':'NAME_BOUND_EVALUATION_DATA_REJECTED'}))


if __name__ == '__main__': unittest.main()
