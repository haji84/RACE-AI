import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import json
from tests import test_name_bound_store as store_helpers
from tests.test_exhibition_api import route,ClosingBlob
from tests import test_exhibition_api as api_helpers
from web.race_contract import canonical

class ApiTests(unittest.TestCase):
    handler=api_helpers.ExhibitionApiTests.handler
    def setUp(self):
        self.reader=route('name-bound-exhibition.py','nb_read')
        self.writer=route('publish-name-bound-exhibition.py','nb_write')
        helper=store_helpers.StoreTests();helper.setUp()
        self.race,self.request=helper.race,helper.request
        self.client=ClosingBlob();self.client.data=helper.client.data
        env=patch.dict('os.environ',{'BLOB_READ_WRITE_TOKEN':'synthetic','VERCEL_ENV':'preview','VERCEL_GIT_COMMIT_SHA':'a'*40});env.start();self.addCleanup(env.stop)
        from tests.test_name_bound_prediction import NOW
        for module in (self.reader,self.writer):
            for key,value in [('utc_now',NOW),('load_feed',(200,dict(venues=[dict(races=[self.race])]))),('create_blob_client',self.client)]:
                p=patch.object(module,key,return_value=value);p.start();self.addCleanup(p.stop)
        p=patch.object(self.writer,'verify_github_oidc');p.start();self.addCleanup(p.stop)

    def test_real_publish_and_canonical_pinned_read(self):
        h=self.handler(self.writer);h.do_POST();self.assertEqual(h.status,200,h.wfile.getvalue())
        self.assertEqual(json.loads(h.wfile.getvalue())['commit_sha'],'a'*40)
        h=self.handler(self.reader,'/api/name-bound-exhibition?race_id='+self.race['race_id']+'&request_id='+self.request['request_id']);h.do_GET()
        self.assertEqual(h.status,200,h.wfile.getvalue());value=json.loads(h.wfile.getvalue())
        self.assertEqual(h.wfile.getvalue(),canonical(value));self.assertNotIn('commit_sha',value['receipt'])

    def test_query_auth_commit_and_safe_errors(self):
        for query in ('','?race_id=','?race_id=x&race_id=y','?race_id=x&extra=y','?race_id=x&request_id=','?race_id='+'x'*2000,'?race_id=20261014-18-01'):
            h=self.handler(self.reader,'/api/name-bound-exhibition'+query);h.do_GET();self.assertEqual(h.status,400)
        with patch.dict('os.environ',{'VERCEL_ENV':'production'}):
            h=self.handler(self.writer);h.do_POST();self.assertEqual(h.status,404)
        with patch.object(self.writer,'verify_github_oidc',side_effect=ValueError('secret')):
            h=self.handler(self.writer);h.do_POST();self.assertEqual(h.status,404);self.assertNotIn(b'secret',h.wfile.getvalue())
        with patch.dict('os.environ',{'VERCEL_GIT_COMMIT_SHA':'b'*40}):
            h=self.handler(self.writer);h.do_POST();self.assertEqual(h.status,409)
        with patch.dict('os.environ',{'VERCEL_GIT_COMMIT_SHA':'z'*40}):
            h=self.handler(self.writer);h.headers['X-Race-AI-Commit']='z'*40;h.do_POST();self.assertEqual(h.status,409)
        for extra in ({'generated_at':'x'},{'cloud_saved_at':'x'},{'media_review':'bad'}):
            h=self.handler(self.writer,body=json.dumps({**self.request,**extra}).encode());h.do_POST();self.assertEqual(h.status,422)
        self.assertEqual(self.client.puts,[])
    def test_separate_read_and_publish_routes_load(self):
        root=Path(__file__).resolve().parents[1]
        with patch.object(sys,'path',[str(root/'web')]+sys.path):
            for filename in ('name-bound-exhibition.py','publish-name-bound-exhibition.py'):
                path=root/'web'/'api'/filename
                self.assertTrue(path.exists(),'separate route required')
                spec=importlib.util.spec_from_file_location(filename,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                self.assertTrue(hasattr(module,'handler'))

if __name__=='__main__':unittest.main()
