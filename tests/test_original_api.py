"""Scoped original facts APIs and opt-in post variant, with synthetic storage."""
from datetime import timedelta
from pathlib import Path
import json
import unittest
from unittest.mock import patch

from tests import test_exhibition_api as helpers
from tests.test_original_prediction_contract import fixture,NOW
from tests.test_exhibition_store import seed_baseline,seed_preview


class OriginalApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.source_read=helpers.route('original-exhibition.py','original_source_read')
            cls.source_write=helpers.route('publish-original-exhibition.py','original_source_write')
            cls.post_read=helpers.route('exhibition-prediction.py','original_post_read')
            cls.post_write=helpers.route('publish-exhibition-prediction.py','original_post_write')
        except (FileNotFoundError,ModuleNotFoundError):cls.source_read=None

    def setUp(self):
        self.assertIsNotNone(self.source_read,'original API routes required')
        base,bundle,original,self.race=fixture();self.client=helpers.ClosingBlob()
        seed_baseline(self.client,base);seed_preview(self.client,bundle)
        self.feed=dict(venues=[dict(races=[self.race])])
        self.request=dict(publication_review='user-confirmation-2026-10-15-exhibition-private-analysis',race_id=self.race['race_id'],
            request_id='223456-1',observation=original['observation'],runner_saved_at=original['runner_saved_at'])
        env=patch.dict('os.environ',{'BLOB_READ_WRITE_TOKEN':'synthetic-secret','VERCEL_ENV':'preview','VERCEL_GIT_COMMIT_SHA':'a'*40})
        env.start();self.addCleanup(env.stop)
        for module in [self.source_read,self.source_write,self.post_read,self.post_write]:
            for target,value in [('utc_now',NOW),('load_feed',(200,self.feed)),('create_blob_client',self.client)]:
                p=patch.object(module,target,return_value=value);p.start();self.addCleanup(p.stop)
        for module in [self.source_write,self.post_write]:
            p=patch.object(module,'verify_github_oidc');p.start();self.addCleanup(p.stop)

    handler=helpers.ExhibitionApiTests.handler

    def publish(self):
        handler=self.handler(self.source_write);handler.do_POST()
        self.assertEqual(handler.status,200,handler.wfile.getvalue())
        return json.loads(handler.wfile.getvalue())

    def test_actual_source_publish_and_read_are_bounded_secure_and_readonly(self):
        meta=self.publish();puts=len(self.client.puts)
        handler=self.handler(self.source_read,'/api/original-exhibition?race_id='+self.race['race_id']);handler.do_GET()
        self.assertEqual(handler.status,200);receipt=json.loads(handler.wfile.getvalue())
        self.assertEqual(receipt['observation']['snapshot_id'],meta['snapshot_id'])
        self.assertEqual(receipt['runner_saved_at'],self.request['runner_saved_at'])
        self.assertEqual(len(self.client.puts),puts);self.assertEqual(self.client.closed,2)
        for name,value in [('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('X-Robots-Tag','noindex')]:
            self.assertEqual(handler.response_headers[name],value)

    def test_original_variant_dispatch_and_default_display_namespace_are_separate(self):
        self.publish()
        self.request=dict(publication_review='user-confirmation-2026-10-15-official-facts',race_id=self.race['race_id'],request_id='323456-1',variant='original-v1')
        handler=self.handler(self.post_write);handler.do_POST();self.assertEqual(handler.status,200,handler.wfile.getvalue())
        meta=json.loads(handler.wfile.getvalue());self.assertEqual(meta['variant'],'original-v1')
        reader=self.handler(self.post_read,'/api/exhibition-prediction?race_id='+self.race['race_id']+'&variant=original-v1');reader.do_GET()
        self.assertEqual(reader.status,200);self.assertEqual(json.loads(reader.wfile.getvalue())['snapshot']['variant'],'original-v1')
        self.assertEqual(self.post_read.load_exhibition_prediction(self.race['race_id'])[0],404)
        self.request.pop('variant');self.request['request_id']='323457-1'
        handler=self.handler(self.post_write);handler.do_POST();self.assertEqual(handler.status,200)
        self.assertNotIn('variant',json.loads(handler.wfile.getvalue()))
        self.assertNotIn('variant',self.post_read.load_exhibition_prediction(self.race['race_id'])[1]['snapshot'])

    def test_unknown_blank_duplicate_variant_and_source_queries_are_rejected(self):
        for suffix in ['&variant=unknown','&variant=','&variant=original-v1&variant=original-v1']:
            handler=self.handler(self.post_read,'/api/exhibition-prediction?race_id='+self.race['race_id']+suffix);handler.do_GET()
            self.assertEqual(handler.status,400)
        for query in ['', '?race_id=', '?race_id=x&race_id=y', '?race_id=x&as_of=x']:
            handler=self.handler(self.source_read,'/api/original-exhibition'+query);handler.do_GET();self.assertEqual(handler.status,400)
        for variant in ['unknown','',None]:
            request=dict(publication_review='user-confirmation-2026-10-15-official-facts',race_id=self.race['race_id'],request_id='323456-1',variant=variant)
            handler=self.handler(self.post_write,body=json.dumps(request).encode());handler.do_POST();self.assertEqual(handler.status,422)
        self.assertEqual(self.client.puts,[])

    def test_source_publisher_injection_review_and_auth_fail_before_client(self):
        for extra in [{'probabilities':[]},{'cloud_saved_at':NOW.isoformat()},{'publication_review':'unknown'}]:
            with patch.object(self.source_write,'create_blob_client') as client:
                handler=self.handler(self.source_write,body=json.dumps({**self.request,**extra}).encode());handler.do_POST()
                self.assertEqual(handler.status,422);client.assert_not_called()
        with patch.dict('os.environ',{'VERCEL_ENV':'production'}),patch.object(self.source_write,'load_feed') as feed:
            handler=self.handler(self.source_write);handler.do_POST();self.assertEqual(handler.status,404);feed.assert_not_called()
        with patch.object(self.source_write,'verify_github_oidc',side_effect=ValueError('invalid')):
            handler=self.handler(self.source_write);handler.do_POST();self.assertEqual(handler.status,404)

    def test_missing_and_corrupt_store_or_failure_are_sanitized_and_closed(self):
        self.assertEqual(self.source_read.load_original_exhibition(self.race['race_id'])[0],404)
        self.publish();self.client.data[f"race-ai/original-exhibition/{self.race['race_id']}.json"]=b'{private secret'
        self.assertEqual(self.source_read.load_original_exhibition(self.race['race_id'])[0],422)
        with patch.object(self.client,'get',side_effect=OSError('private-secret')):
            self.assertEqual(self.source_read.load_original_exhibition(self.race['race_id']),
                (503,{'error':'ORIGINAL_EXHIBITION_STORE_UNAVAILABLE'}))
        self.assertEqual(self.client.closed,4)

    def test_source_clock_midnight_and_body_size_limits_fail_closed(self):
        tomorrow=NOW+timedelta(days=1)
        with patch.object(self.source_read,'utc_now',side_effect=[NOW,NOW,tomorrow]):
            self.assertEqual(self.source_read.load_original_exhibition(self.race['race_id'])[0],422)
        handler=self.handler(self.source_write);handler.headers['Content-Length']='256001'
        with patch.object(self.source_write,'load_feed') as feed:
            handler.do_POST();self.assertEqual(handler.status,400);feed.assert_not_called()

    def test_original_missing_post_variant_is_informative_and_never_mints_receipt(self):
        request=dict(publication_review='user-confirmation-2026-10-15-official-facts',race_id=self.race['race_id'],request_id='323456-1',variant='original-v1')
        handler=self.handler(self.post_write,body=json.dumps(request).encode());handler.do_POST()
        self.assertEqual(handler.status,422)
        self.assertEqual(json.loads(handler.wfile.getvalue())['reason'],'ORIGINAL_NOT_OBTAINED')
        self.assertEqual(self.client.puts,[])


if __name__=='__main__':unittest.main()
