"""Synthetic caller tests: no live source, credentials or network."""
import copy
from datetime import timedelta
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.test_name_binding_store import fixture
from tests.test_live_research_contract import NOW
from tests.test_race_cloud_store import Blob
from tests.test_exhibition_store import seed_baseline
from web.race_contract import canonical

caller=importlib.import_module('scripts.publish_name_binding')
store=importlib.import_module('api.name_binding_store')

class CallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.review=self.root/'review.json';self.review.write_text('{}')
        self.feed,self.race,self.baseline,self.request=fixture()
        self.feed.update(schedule_verified=True)
        self.feed['venues'][0]['status']='READY'
        self.feed['venues'] += [dict(status='NO_RACES',races=[]) for _ in range(23)]
        self.calls=[];self.envelope=None;self.report=None
        self.env=dict(RACE_AI_NAME_BINDING_PUBLISH_URL='https://race-ai-preview-test-qq1130034-1738.vercel.app/api/publish-name-binding',
            RACE_AI_NAME_BINDING_COMMIT_SHA='a'*40,GITHUB_RUN_ID='123456',GITHUB_RUN_ATTEMPT='1')
    def network(self,opener,request,*,limit):
        self.calls.append(request.full_url)
        if request.full_url.endswith('/today'):return copy.deepcopy(self.feed)
        if '/prediction?' in request.full_url:return copy.deepcopy(self.baseline)
        if request.get_method()=='POST':
            self.request=json.loads(request.data)
            client=Blob();seed_baseline(client,self.baseline)
            self.report=store.publish_name_binding(self.request,self.race,self.baseline,client=client,now=NOW,clock=lambda:NOW)
            self.envelope=store.read_name_binding(self.race,self.baseline,client=client,now=NOW,request_id='123456-1')
            return dict(self.report,commit_sha='a'*40)
        return copy.deepcopy(self.envelope)
    def collect(self,*args,**kwargs):
        kwargs['transport']('synthetic',timeout=10,max_bytes=1000000)
        return dict(status='COLLECTED',snapshot=copy.deepcopy(self.request['snapshot']))
    def run_case(self,network=None,collector=None,clock=None,monotonic=None):
        with patch.dict(caller.os.environ,self.env),patch.object(caller,'workflow_session',return_value=(object(),{})) as session,patch.object(caller,'get_json',side_effect=network or self.network),patch.object(caller,'utc_now',side_effect=clock or (lambda:NOW)),patch.object(caller,'collect_name_binding',side_effect=collector or self.collect),patch('race_ai.official_racelist_worker.fetch_racelist',return_value=None),patch.object(caller.time,'monotonic',side_effect=monotonic or (lambda:0)):
            result=caller.run(self.review,self.root/'out',race_id=self.race['race_id'],execute=True)
        self.assertLessEqual(session.call_count,1)
        return result
    def test_dry_run_has_no_io(self):
        with patch.object(caller,'workflow_session') as session:
            self.assertIsNone(caller.run('missing','missing',race_id='bad'));session.assert_not_called()
    def test_success_replays_full_envelope_and_all_backup_bytes(self):
        before=canonical(self.baseline);result=self.run_case()
        self.assertEqual(result['status'],'COMPLETED');self.assertEqual(result['official_source_requests'],1)
        self.assertEqual(result['reads_used'],4);self.assertEqual(result['posts_attempted'],1)
        self.assertEqual(canonical(self.baseline),before)
        self.assertEqual({p.name for p in (self.root/'out').iterdir()},caller.ALLOWED)
        for name,meta in result['backups'].items():
            raw=(self.root/'out'/name).read_bytes();self.assertEqual(meta,dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        self.assertEqual(json.loads((self.root/'out'/'receipt.json').read_bytes()),self.envelope)
    def test_absent_or_corrupt_baseline_never_collects(self):
        self.baseline=None
        with patch.object(caller,'collect_name_binding') as collect:
            result=self.run_case(collector=collect)
        self.assertEqual(result['status'],'STOPPED');self.assertEqual(result['official_source_requests'],0)
    def test_pinned_baseline_mismatch_never_collects(self):
        def network(opener,request,*,limit):
            value=self.network(opener,request,limit=limit)
            if '&request_id=' in request.full_url:value['request_id']='987-1'
            return value
        result=self.run_case(network=network)
        self.assertEqual(result['official_source_requests'],0);self.assertEqual(result['posts_attempted'],0)
    def test_source_rights_response_and_parse_failures_preserve_baseline(self):
        for code in ['SOURCE_RIGHTS_BLOCKED','SOURCE_UNAVAILABLE','SOURCE_INVALID']:
            with self.subTest(code=code):
                if (self.root/'out').exists():
                    for path in (self.root/'out').iterdir():path.unlink()
                    (self.root/'out').rmdir()
                result=self.run_case(collector=lambda *a,**k:dict(status=code))
                self.assertEqual(result['status'],'STOPPED');self.assertEqual(set(result['backups']),{'baseline.json'})
                self.assertEqual(result['failure_reason'],'NAME_BINDING_STOPPED')
    def test_commit_and_receipt_tampering_stop_with_partial_request(self):
        def network(opener,request,*,limit):
            value=self.network(opener,request,limit=limit)
            if request.get_method()=='POST':value['commit_sha']='b'*40
            return value
        result=self.run_case(network=network)
        self.assertEqual(result['status'],'STOPPED');self.assertNotIn('receipt.json',result['backups'])
        self.assertIn('request.json',result['backups'])
    def test_budget_prevents_oidc_and_leaves_safe_manifest(self):
        result=self.run_case(monotonic=iter([0,151]).__next__)
        self.assertEqual(result['status'],'TIME_LIMIT_REACHED');self.assertEqual(self.calls,[])
    def test_midnight_and_cutoff_stop_before_baseline_or_source(self):
        result=self.run_case(clock=lambda:NOW+timedelta(days=1))
        self.assertEqual(result['official_source_requests'],0);self.assertEqual(result['status'],'STOPPED')
    def test_file_size_and_exclusive_readback(self):
        with self.assertRaises(ValueError):caller.write_checked(self.root,'name-proof.json',{'large':'x'*64000})
        caller.write_checked(self.root,'baseline.json',{})
        with self.assertRaises(FileExistsError):caller.write_checked(self.root,'baseline.json',{})
    def test_original_baseline_archive_pin_can_differ_from_current_archive(self):
        self.race['program_source_sha256']='b'*64
        result=self.run_case()
        self.assertEqual(result['status'],'COMPLETED');self.assertEqual(self.request['snapshot']['b_program_sha256'],'a'*64)


    def test_failed_local_readback_preserves_present_normalized_file_digest(self):
        original=caller.write_checked
        def fail(folder,name,value):
            result=original(folder,name,value)
            if name=='name-proof.json':raise OSError('private detail')
            return result
        with patch.object(caller,'write_checked',side_effect=fail):result=self.run_case()
        self.assertEqual(result['status'],'STOPPED')
        self.assertIn('name-proof.json',result['backups'])
        self.assertNotIn('private',canonical(result).decode())
    def test_request_latency_crossing_cutoff_never_posts(self):
        clock=iter([NOW,NOW,NOW,NOW,NOW,caller.instant(self.race['closed_at'])]).__next__
        result=self.run_case(clock=clock)
        self.assertEqual(result['status'],'STOPPED');self.assertEqual(result['posts_attempted'],0)
    def test_unknown_post_outcome_is_not_retried(self):
        def network(opener,request,*,limit):
            if request.get_method()=='POST':raise RuntimeError('provider private detail')
            return self.network(opener,request,limit=limit)
        result=self.run_case(network=network)
        self.assertEqual(result['posts_attempted'],1);self.assertEqual(result['official_source_requests'],1)
        self.assertEqual(result['status'],'STOPPED');self.assertIn('request.json',result['backups'])
    def test_local_tampering_stops_before_post(self):
        original=caller.write_checked
        def tamper(folder,name,value):
            result=original(folder,name,value)
            if name=='request.json':(folder/'baseline.json').write_bytes(b'{}')
            return result
        with patch.object(caller,'write_checked',side_effect=tamper):result=self.run_case()
        self.assertEqual(result['posts_attempted'],0);self.assertEqual(result['status'],'STOPPED')
    def test_receipt_nonce_or_marker_tampering_is_rejected(self):
        def network(opener,request,*,limit):
            value=self.network(opener,request,limit=limit)
            if '/name-binding?' in request.full_url:value['finalization']['request_id']='999-1'
            return value
        result=self.run_case(network=network)
        self.assertEqual(result['status'],'STOPPED');self.assertNotIn('receipt.json',result['backups'])

    def test_source_budget_exhaustion_is_time_limit_without_get(self):
        def collector(*args,**kwargs):
            try:kwargs['transport']('synthetic')
            except TimeoutError:return dict(status='SOURCE_UNAVAILABLE')
        result=self.run_case(collector=collector,monotonic=iter([0,0,0,0,0,0,171]).__next__)
        self.assertEqual(result['status'],'TIME_LIMIT_REACHED')
        self.assertEqual(result['official_source_requests'],0)

    def test_reverse_runner_clock_stops_before_post(self):
        clock=iter([NOW,NOW,NOW,NOW,NOW-timedelta(seconds=10),NOW]).__next__
        result=self.run_case(clock=clock)
        self.assertEqual(result['posts_attempted'],0)
        self.assertEqual(result['status'],'STOPPED')
