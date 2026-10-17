"""Full synthetic source/baseline/original-model publication and backup replay."""
import copy
from datetime import timedelta
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
from contextlib import redirect_stdout
from io import StringIO

from tests.test_collect_original_exhibition import load_script,inputs,ROOT
from tests.test_original_prediction_contract import fixture,NOW,sha
from tests.test_exhibition_store import seed_baseline,seed_preview
from tests.test_race_cloud_store import Blob
from web.race_contract import canonical


class OriginalPublisherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:cls.c=load_script('publish_original_exhibition_prediction')
        except FileNotFoundError:cls.c=None
        with patch.object(sys,'path',[str(ROOT/'web')]+sys.path):
            cls.source=importlib.import_module('api.original_exhibition_store')
            cls.post=importlib.import_module('api.original_prediction_store')
            cls.baseline_store=importlib.import_module('api.prediction_store')
            cls.race_store=importlib.import_module('api.race_store')

    def setUp(self):
        self.assertIsNotNone(self.c,'full original publisher required')
        self.baseline,self.bundle,self.original,self.race=fixture();self.feed,_,_=inputs()
        source=self.baseline['snapshot']['program_source']
        self.feed['sources']=[dict(source_url=source['source_url'],source_sha256=source['source_sha256'],first_observed_at=source['captured_at'])]
        self.client=Blob();seed_baseline(self.client,self.baseline);seed_preview(self.client,self.bundle)
        self.calls=[];self.commit='a'*40;self.nonce='323456-1';self.mode=None
        env=patch.dict('os.environ',{'RACE_AI_ORIGINAL_PUBLISH_URL':'https://race-ai-preview-test-qq1130034-1738.vercel.app/api/publish-original-exhibition',
            'RACE_AI_ORIGINAL_COMMIT_SHA':self.commit,'GITHUB_RUN_ID':'323456','GITHUB_RUN_ATTEMPT':'1'})
        env.start();self.addCleanup(env.stop)

    def http(self,opener,request,limit):
        self.calls.append(request);url=urlsplit(request.full_url);path=url.path;query=parse_qs(url.query)
        body=json.loads(request.data) if request.data else None
        if path=='/api/today':return self.feed
        if path=='/api/race':return self.race_store.read_current_race(self.race,client=self.client,now=NOW)
        if path=='/api/publish-original-exhibition':
            result=self.source.publish_original_exhibition(body,self.race,client=self.client,now=NOW,clock=lambda:NOW)
            result['commit_sha']=self.commit
            if self.mode=='source_sha':result['sha256']='b'*64
            return result
        if path=='/api/original-exhibition':return self.source.read_original_exhibition(self.race,client=self.client,now=NOW,request_id=query.get('request_id',[None])[0])
        if path=='/api/prediction':
            result=self.baseline_store.read_prediction(self.race,client=self.client,now=NOW,request_id=query.get('request_id',[None])[0])
            if result is None:raise RuntimeError('DAY_PUBLISH_HTTP_404')
            return result
        if path=='/api/publish-prediction':
            result=self.baseline_store.publish_prediction(body,self.feed,self.race,client=self.client,now=NOW,clock=lambda:NOW)
            return {**result,'commit_sha':self.commit}
        if path=='/api/publish-exhibition-prediction':
            self.assertEqual(body['variant'],'original-v1');body.pop('variant')
            result=self.post.publish_original_prediction(body,self.race,client=self.client,now=NOW,clock=lambda:NOW)
            result['commit_sha']=self.commit
            if self.mode=='post_sha':result['sha256']='b'*64
            return result
        if path=='/api/exhibition-prediction':
            self.assertEqual(query['variant'],['original-v1'])
            result=self.post.read_original_prediction(self.race,client=self.client,now=NOW,request_id=query['request_id'][0])
            if self.mode=='probability':result['snapshot']['model']['triples'][0]['probability']=.5
            return result
        raise AssertionError('Unexpected endpoint '+path)

    def run_publish(self,folder,clock=None):
        root=Path(folder);packet=dict(schema_version=1,race_id=self.race['race_id'],observation=self.original['observation'],runner_saved_at=self.original['runner_saved_at'])
        (root/'original.json').write_bytes(canonical(packet));(root/'race.json').write_bytes(canonical(self.bundle))
        with patch.object(self.c,'workflow_session',return_value=(object(),{'Authorization':'Bearer secret-not-backed-up'})),patch.object(self.c,'get_json',side_effect=self.http),redirect_stdout(StringIO()):
            return self.c.run(root/'original.json',root/'race.json',root/'output',execute=True,clock=clock or (lambda:NOW))

    def test_existing_baseline_preserved_full_model_replay_and_all_backups_hashed(self):
        old={k:v for k,v in self.client.data.items() if '/prediction' in k}
        with tempfile.TemporaryDirectory() as folder:
            manifest=self.run_publish(folder);output=Path(folder)/'output'
            self.assertEqual(manifest['result'],'ORIGINAL_EXHIBITION_PREDICTION_VERIFIED')
            self.assertEqual(manifest['official_source_requests'],0)
            for name,proof in manifest['backups'].items():
                raw=(output/name).read_bytes();self.assertEqual(sha(json.loads(raw)),proof['sha256']);self.assertEqual(len(raw),proof['bytes'])
                self.assertNotIn(b'secret-not-backed-up',raw)
            self.assertTrue({'race.json','original-request.json','original.json','baseline.json','post-request.json','post.json'}<=set(manifest['backups']))
        self.assertEqual({k:v for k,v in self.client.data.items() if '/prediction' in k},old)
        self.assertFalse(any(urlsplit(r.full_url).path=='/api/publish-prediction' for r in self.calls))

    def test_missing_baseline_is_created_with_own_nonce_and_full_server_receipt_verified(self):
        del self.client.data[self.baseline_store.manifest_key(self.race['race_id'])]
        with tempfile.TemporaryDirectory() as folder:
            manifest=self.run_publish(folder)
            baseline=json.loads((Path(folder)/'output/baseline.json').read_bytes())
            self.assertEqual(baseline['request_id'],self.nonce)
            self.assertIn('baseline-request.json',manifest['backups'])
        self.assertEqual(sum(urlsplit(r.full_url).path=='/api/publish-prediction' for r in self.calls),1)

    def test_partial_original_is_backed_up_and_never_calls_post_or_baseline_writer(self):
        observation=self.original['observation'];boat=observation['boats'][0];boat['original_times']['turn_s']=None
        boat['missing_reasons']['turn_s']='SOURCE_NOT_PUBLISHED';observation['status']='PARTIAL'
        observation['snapshot_id']=sha({k:v for k,v in observation.items() if k!='snapshot_id'})
        with tempfile.TemporaryDirectory() as folder:
            manifest=self.run_publish(folder)
            self.assertEqual(manifest['result'],'ORIGINAL_EXHIBITION_PARTIAL_VERIFIED')
            self.assertIn('original.json',manifest['backups']);self.assertNotIn('post.json',manifest['backups'])
        self.assertFalse(any(urlsplit(r.full_url).path in ['/api/publish-prediction','/api/publish-exhibition-prediction'] for r in self.calls))

    def test_source_or_model_fullhash_and_tampered_probability_fail(self):
        for mode in ['source_sha','post_sha','probability']:
            self.mode=mode
            with tempfile.TemporaryDirectory() as folder,self.subTest(mode=mode),self.assertRaises(ValueError):self.run_publish(folder)

    def test_margin_expiry_during_latency_cannot_post_source(self):
        ticks=iter([NOW+timedelta(minutes=1),NOW+timedelta(hours=2)])
        with tempfile.TemporaryDirectory() as folder,self.assertRaises(ValueError):self.run_publish(folder,clock=lambda:next(ticks))
        self.assertFalse(any(r.data for r in self.calls))

    def test_wrong_target_and_duplicate_input_fields_fail_before_session_or_writes(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(self.c,'workflow_session') as session:
            packet=Path(folder)/'bad.json';packet.write_bytes(b'{"schema_version":1,"schema_version":1}')
            with self.assertRaises(ValueError):self.c.run(packet,Path('absent'),Path(folder)/'out',execute=True)
            session.assert_not_called()
        with patch.dict('os.environ',{'RACE_AI_ORIGINAL_PUBLISH_URL':'https://attacker.example/api/publish-original-exhibition'}):
            with tempfile.TemporaryDirectory() as folder,patch.object(self.c,'workflow_session') as session,self.assertRaises(ValueError):self.run_publish(folder)
            session.assert_not_called()

    def test_dryrun_reads_nothing_and_contacts_nothing(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(self.c,'workflow_session') as session,redirect_stdout(StringIO()):
            result=self.c.run(Path('missing'),Path('missing'),Path(folder)/'out')
            self.assertEqual(result['network_requests'],0);self.assertFalse((Path(folder)/'out').exists());session.assert_not_called()


if __name__=='__main__':unittest.main()
