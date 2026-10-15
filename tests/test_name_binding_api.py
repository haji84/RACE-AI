"""Protected name proof APIs use exact immutable baseline nonces."""
import json
import unittest
from web.race_contract import canonical
from unittest.mock import patch
from tests.test_exhibition_api import route,ClosingBlob
from tests import test_exhibition_api as api_helpers
from tests.test_exhibition_store import seed_baseline
from tests.test_name_binding_store import fixture,NOW

class NameBindingApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.reader=route('name-binding.py','name_binding_read_route')
            cls.writer=route('publish-name-binding.py','name_binding_write_route')
        except (FileNotFoundError,ModuleNotFoundError):cls.reader=cls.writer=None
    def setUp(self):
        self.assertIsNotNone(self.reader,'protected name-binding routes required')
        self.feed,self.race,self.base,self.request=fixture();self.client=ClosingBlob();seed_baseline(self.client,self.base)
        env=patch.dict('os.environ',{'BLOB_READ_WRITE_TOKEN':'synthetic','VERCEL_ENV':'preview','VERCEL_GIT_COMMIT_SHA':'a'*40});env.start();self.addCleanup(env.stop)
        for module in [self.reader,self.writer]:
            for key,value in [('utc_now',NOW),('load_feed',(200,self.feed)),('create_blob_client',self.client)]:
                p=patch.object(module,key,return_value=value);p.start();self.addCleanup(p.stop)
        p=patch.object(self.writer,'verify_github_oidc');p.start();self.addCleanup(p.stop)
    handler=api_helpers.ExhibitionApiTests.handler
    def publish(self):
        handler=self.handler(self.writer);handler.do_POST();self.assertEqual(handler.status,200,handler.wfile.getvalue())
        return json.loads(handler.wfile.getvalue())
    def test_publish_full_envelope_and_pinned_baseline_survives_latest_corruption(self):
        meta=self.publish();self.assertEqual(meta['commit_sha'],'a'*40)
        self.client.data[f"race-ai/predictions/{self.race['race_id']}.json"]=b'corrupt'
        h=self.handler(self.reader,'/api/name-binding?race_id='+self.race['race_id']+'&request_id='+self.request['request_id']);h.do_GET()
        self.assertEqual(h.status,200,h.wfile.getvalue());value=json.loads(h.wfile.getvalue())
        self.assertEqual(set(value),{'receipt','finalization'});self.assertEqual(value['receipt']['baseline_request_id'],self.base['request_id'])
        self.assertEqual(h.wfile.getvalue(),canonical(value))
        self.assertEqual(len(self.client.puts),4)
        self.assertEqual(h.response_headers['Cache-Control'],'no-store')
    def test_strict_query_and_oversize_query_reject(self):
        for query in ['', '?race_id=', '?race_id=x&race_id=y','?race_id=x&request_id=','?race_id=x&extra=y','?race_id='+'x'*2000]:
            h=self.handler(self.reader,'/api/name-binding'+query);h.do_GET();self.assertEqual(h.status,400)
    def test_preview_oidc_and_exact_commit_guards(self):
        with patch.dict('os.environ',{'VERCEL_ENV':'production'}):
            h=self.handler(self.writer);h.do_POST();self.assertEqual(h.status,404)
        with patch.object(self.writer,'verify_github_oidc',side_effect=ValueError('secret')):
            h=self.handler(self.writer);h.do_POST();self.assertEqual(h.status,404);self.assertNotIn(b'secret',h.wfile.getvalue())
        with patch.dict('os.environ',{'VERCEL_GIT_COMMIT_SHA':'b'*40}):
            h=self.handler(self.writer);h.do_POST();self.assertEqual(h.status,409)
        self.assertEqual(self.client.puts,[])
    def test_extra_fields_missing_baseline_and_immutable_baseline_loss_reject(self):
        for extra in [{'cloud_saved_at':NOW.isoformat()},{'baseline_request_id':'999-1'},{'probabilities':[]}]:
            h=self.handler(self.writer,body=json.dumps({**self.request,**extra}).encode());h.do_POST();self.assertEqual(h.status,422)
        self.assertEqual(self.client.puts,[])
        self.publish();del self.client.data[f"race-ai/prediction-versions/{self.race['race_id']}/{self.base['snapshot']['snapshot_id']}.json"]
        self.assertEqual(self.reader.load_name_binding(self.race['race_id'],self.request['request_id'])[0],422)
    def test_missing_or_orphan_receipt_is_never_success(self):
        self.assertEqual(self.reader.load_name_binding(self.race['race_id'])[0],404)
        self.publish();del self.client.data[f"race-ai/name-binding-finalizations/{self.race['race_id']}/{self.request['request_id']}.json"]
        self.assertEqual(self.reader.load_name_binding(self.race['race_id'],self.request['request_id'])[0],422)

if __name__=='__main__':unittest.main()
