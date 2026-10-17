"""Separate current-day post-exhibition readers and scoped Preview writer."""
import copy
from datetime import timedelta
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from tests.test_exhibition_contract import fixture, NOW
from tests.test_exhibition_store import seed_baseline, seed_preview
from tests.test_race_cloud_store import Blob

ROOT=Path(__file__).resolve().parents[1]


def route(filename,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'web/api'/filename)
    module=importlib.util.module_from_spec(spec)
    with patch.object(sys,'path',[str(ROOT/'web')]+sys.path): spec.loader.exec_module(module)
    return module


class ClosingBlob(Blob):
    def __init__(self): super().__init__(); self.closed=0
    def close(self): self.closed+=1


class ExhibitionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.read=route('exhibition-prediction.py','exhibition_read_route')
            cls.publish=route('publish-exhibition-prediction.py','exhibition_publish_route')
        except (FileNotFoundError,ModuleNotFoundError): cls.read=cls.publish=None

    def setUp(self):
        self.assertIsNotNone(self.read,'separate exhibition API routes must exist')
        self.baseline,self.bundle,self.race=fixture(); self.client=ClosingBlob()
        seed_baseline(self.client,self.baseline); seed_preview(self.client,self.bundle)
        self.feed=dict(venues=[dict(races=[self.race])])
        self.request=dict(publication_review='user-confirmation-2026-10-15-official-facts',
                          race_id=self.race['race_id'],request_id='123457-1')
        env=patch.dict('os.environ',{'BLOB_READ_WRITE_TOKEN':'synthetic-secret','VERCEL_ENV':'preview','VERCEL_GIT_COMMIT_SHA':'a'*40})
        env.start(); self.addCleanup(env.stop)
        for module in [self.read,self.publish]:
            for target,value in [('utc_now',NOW),('load_feed',(200,self.feed)),('create_blob_client',self.client)]:
                patcher=patch.object(module,target,return_value=value); patcher.start(); self.addCleanup(patcher.stop)
        auth=patch.object(self.publish,'verify_github_oidc'); auth.start(); self.addCleanup(auth.stop)

    def handler(self,module,path='',headers=None,body=None):
        handler=object.__new__(module.handler); handler.path=path; handler.wfile=BytesIO(); handler.response_headers={}
        handler.send_response=lambda status:setattr(handler,'status',status)
        handler.send_header=lambda key,value:handler.response_headers.update({key:value})
        handler.end_headers=lambda:None
        raw=json.dumps(self.request).encode() if body is None else body
        handler.rfile=BytesIO(raw)
        handler.headers=headers or {'Authorization':'Bearer synthetic','X-Race-AI-Commit':'a'*40,
            'Content-Type':'application/json','Content-Length':str(len(raw))}
        return handler

    def published(self):
        handler=self.handler(self.publish); handler.do_POST()
        self.assertEqual(handler.status,200,handler.wfile.getvalue())
        return json.loads(handler.wfile.getvalue())

    def test_real_synthetic_publish_and_read_chain_preserves_baselines(self):
        baseline_bytes={k:v for k,v in self.client.data.items() if '/prediction' in k}
        metadata=self.published(); self.assertEqual(metadata['models'],1)
        self.assertEqual(metadata['commit_sha'],'a'*40)
        puts=len(self.client.puts)
        handler=self.handler(self.read,'/api/exhibition-prediction?race_id='+self.race['race_id']); handler.do_GET()
        self.assertEqual(handler.status,200)
        receipt=json.loads(handler.wfile.getvalue())
        self.assertEqual(receipt['snapshot']['snapshot_id'],metadata['snapshot_id'])
        self.assertEqual(receipt['cloud_saved_at'],metadata['cloud_saved_at'])
        self.assertEqual(len(self.client.puts),puts)
        self.assertEqual({k:v for k,v in self.client.data.items() if '/prediction' in k},baseline_bytes)
        self.assertEqual(self.client.closed,2)
        for name,value in [('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('X-Robots-Tag','noindex')]:
            self.assertEqual(handler.response_headers[name],value)
        self.assertEqual(int(handler.response_headers['Content-Length']),len(handler.wfile.getvalue()))

    def test_missing_receipt_is_404_and_get_creates_nothing(self):
        for request_id in [None,'999999-1']:
            with self.subTest(request_id=request_id):
                self.assertEqual(self.read.load_exhibition_prediction(self.race['race_id'],request_id),
                    (404,{'error':'EXHIBITION_PREDICTION_NOT_SAVED'}))
        self.assertEqual(self.client.puts,[])

    def test_strict_duplicate_extra_blank_and_client_asof_queries_rejected(self):
        for query in ['', '?race_id', '?race_id=', '?race_id=x&race_id=y', '?race_id=x&as_of=x',
                      '?race_id=x&request_id=', '?race_id=x&request_id=a&extra=x', '?request_id=x']:
            with self.subTest(query=query),patch.object(self.read,'load_exhibition_prediction') as load:
                handler=self.handler(self.read,'/api/exhibition-prediction'+query); handler.do_GET()
                self.assertEqual(handler.status,400); load.assert_not_called()

    def test_invalid_race_or_nonce_and_unapproved_day_cannot_read_private_store(self):
        for identifier in ['../escape','20261014-18-01','20261015-18-02']:
            with patch.object(self.read,'create_blob_client') as client:
                self.assertEqual(self.read.load_exhibition_prediction(identifier)[0],422); client.assert_not_called()
        with patch.object(self.read,'load_feed',return_value=(503,{})),patch.object(self.read,'create_blob_client') as client:
            self.assertEqual(self.read.load_exhibition_prediction(self.race['race_id'])[0],503); client.assert_not_called()

    def test_corrupt_post_and_storage_failures_are_sanitized_and_closed(self):
        self.published(); key=f"race-ai/post-exhibition/{self.race['race_id']}.json"; self.client.data[key]=b'{private-secret'
        self.assertEqual(self.read.load_exhibition_prediction(self.race['race_id']),
            (422,{'error':'EXHIBITION_PREDICTION_DATA_REJECTED'}))
        self.assertEqual(self.client.closed,2)
        with patch.object(self.client,'get',side_effect=OSError('private-secret')):
            self.assertEqual(self.read.load_exhibition_prediction(self.race['race_id']),
                (503,{'error':'EXHIBITION_PREDICTION_STORE_UNAVAILABLE'}))
        self.assertEqual(self.client.closed,3)

    def test_get_midnight_rejects_mixed_day(self):
        midnight=NOW.replace(hour=0,minute=0,second=0)+timedelta(days=1)
        with patch.object(self.read,'utc_now',side_effect=[NOW,NOW,midnight]):
            self.assertEqual(self.read.load_exhibition_prediction(self.race['race_id'])[0],422)
        self.assertEqual(self.client.closed,1)

    def test_read_pinned_request_after_latest_changes_returns_original_receipt(self):
        first=self.published()
        self.request['request_id']='123458-1'
        with patch.object(self.publish,'utc_now',return_value=NOW+timedelta(seconds=1)): self.published()
        status,receipt=self.read.load_exhibition_prediction(self.race['race_id'],first['request_id'])
        self.assertEqual(status,200); self.assertEqual(receipt['snapshot']['snapshot_id'],first['snapshot_id'])

    def test_production_missing_invalid_oidc_and_commit_never_load_feed(self):
        with patch.dict('os.environ',{'VERCEL_ENV':'production'}),patch.object(self.publish,'load_feed') as feed:
            handler=self.handler(self.publish); handler.do_POST(); self.assertEqual(handler.status,404); feed.assert_not_called()
        for mode in ['no_bearer','invalid_oidc','wrong_commit']:
            handler=self.handler(self.publish)
            if mode=='no_bearer': handler.headers['Authorization']=''
            if mode=='wrong_commit': handler.headers['X-Race-AI-Commit']='b'*40
            with patch.object(self.publish,'load_feed') as feed,patch.object(self.publish,'verify_github_oidc',
                side_effect=ValueError('bad') if mode=='invalid_oidc' else None):
                handler.do_POST(); self.assertEqual(handler.status,409 if mode=='wrong_commit' else 404); feed.assert_not_called()

    def test_injected_times_probabilities_invalid_nonce_and_duplicate_json_cannot_write(self):
        bodies=[json.dumps({**self.request,'as_of':NOW.isoformat()}).encode(),
                json.dumps({**self.request,'probabilities':[]}).encode(),
                json.dumps({**self.request,'request_id':'../escape'}).encode(),
                b'{"race_id":"x","race_id":"y"}',b'[]']
        for body in bodies:
            with self.subTest(body=body),patch.object(self.publish,'create_blob_client') as client:
                handler=self.handler(self.publish,body=body); handler.do_POST()
                self.assertEqual(handler.status,422); client.assert_not_called()
        self.assertEqual(self.client.puts,[])

    def test_oversized_and_truncated_body_rejected_before_feed_or_store(self):
        for size,body in [('8193',b'{}'),('99',b'{}')]:
            handler=self.handler(self.publish,body=body); handler.headers['Content-Length']=size
            with patch.object(self.publish,'load_feed') as feed:
                handler.do_POST(); self.assertIn(handler.status,[400,422]); feed.assert_not_called()

    def test_incomplete_evidence_has_fixed_reason_and_no_post_receipt(self):
        del self.client.data[f"race-ai/predictions/{self.race['race_id']}.json"]
        handler=self.handler(self.publish); handler.do_POST()
        self.assertEqual(handler.status,422)
        self.assertEqual(json.loads(handler.wfile.getvalue()),{'error':'EXHIBITION_PREDICTION_UNAVAILABLE','reason':'BASELINE_MISSING'})
        self.assertEqual(self.client.puts,[]); self.assertEqual(self.client.closed,1)

    def test_publish_store_failure_is_sanitized_and_client_is_closed(self):
        with patch.object(self.client,'get',side_effect=OSError('private-secret')):
            handler=self.handler(self.publish); handler.do_POST()
        self.assertEqual(handler.status,503)
        self.assertEqual(json.loads(handler.wfile.getvalue()),{'error':'EXHIBITION_PUBLICATION_FAILED'})
        self.assertEqual(self.client.closed,1)

    def test_publisher_get_is_method_rejection_with_security_headers(self):
        handler=self.handler(self.publish); handler.do_GET()
        self.assertEqual(handler.status,405)
        self.assertEqual(handler.response_headers['Cache-Control'],'no-store')
        self.assertEqual(handler.response_headers['X-Robots-Tag'],'noindex')
        self.assertEqual(self.client.puts,[])


if __name__=='__main__': unittest.main()
