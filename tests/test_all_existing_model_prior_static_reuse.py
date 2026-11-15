"""Synthetic original journal codec/receipts; no provider or owner key."""
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai.boat_all_model_store import open_forecasts,seal_forecasts
from tests import test_all_existing_model_official_result_collect as fixtures

KEY=fixtures.KEY

def captured_browser(clock,seen):
    def browser(plan,directory):
        seen.append(deepcopy(plan));directory.mkdir(mode=0o700);start=clock.now();responses=[];ledger=[]
        targets=[('document','https://autorace.jp/race_info/Live/isesaki','text/html',b'<html>synthetic</html>'),
            *[('stylesheet','https://autorace.jp/content/assets/css/'+name,'text/css',('synthetic-style-'+name).encode())
              for name in ('app.css?20300115','style.css?20300115','video-js.css')],
            *[('xhr','https://autorace.jp'+path,'application/json',b'null') for path in
              ('/race_info/important_notice','/race_info/XML/Hold/Today','/data/notice/all-01.json','/data/notice/info-01.json')]]
        cache={entry['metadata']['source_url']:entry for entry in plan.get('static_cache',[])}
        for kind,url,mime,raw in targets:
            if kind in ('script','stylesheet') and url in cache:
                original=cache[url]['metadata'];ledger.append(dict(event='STATIC_CACHE_REPLAY',url=url,method='GET',resource_type=kind,
                    source_sha256=original['source_sha256'],original_captured_at=original['response_received_at'],at=start.isoformat()));continue
            n=len(responses)+1;began=start+timedelta(seconds=n);finished=began+timedelta(milliseconds=200)
            metadata=dict(source_url=url,final_url=url,status=200,byte_count=len(raw),source_sha256=sha256(raw).hexdigest(),
                fetched_at=began.isoformat(),response_received_at=finished.isoformat(),headers={'content-type':mime,'date':'authored fixture'},
                method='GET',http_method='GET',resource_type=kind,ui_capture_kind='NORMAL_BROWSER_UI')
            entry=dict(sequence=n,url=url,method='GET',resource_type=kind,request_started_at=began.isoformat(),status=200,
                headers_received_at=(began+timedelta(milliseconds=100)).isoformat(),body_captured_at=finished.isoformat(),
                response_received_at=finished.isoformat(),byte_count=len(raw),source_sha256=sha256(raw).hexdigest(),content_type=mime,
                body_file=f'response-{n:03d}.body',metadata_file=f'response-{n:03d}.metadata.json')
            for name,body in ((entry['body_file'],raw),(entry['metadata_file'],json.dumps(metadata).encode())):
                path=directory/name;path.write_bytes(body);path.chmod(0o600)
            responses.append(entry);ledger.append(deepcopy(entry))
        clock.value=start+timedelta(seconds=len(responses)+1)
        index=dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_CAPTURE_V1',started_at=start.isoformat(),completed_at=clock.now().isoformat(),
            actual_request_count=len(responses),maximum_requests=plan['request_budget'],minimum_spacing_ms=825,maximum_elapsed_ms=85000,
            request_timeout_ms=12000,stop_reason='REQUEST_LIMIT' if len(responses)==plan['request_budget'] else 'FINISHED',stopped_host=False,
            normal_ui_only=True,manual_api_requests=0,formal_learning_or_pdca_claim=False,responses=responses,ledger=ledger,
            cases=[dict(sport='autorace',race_id=plan['cases'][0]['race_id'],state='HOLD_UI_OR_SOURCE_UNAVAILABLE',responses=[],reason='UI_OPERATION_REJECTED')])
        path=directory/'capture-index.json';path.write_text(json.dumps(index));path.chmod(0o600);return index
    return browser

class PriorStaticReuseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.BrowserCollectorIntegrationTests('runTest');self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.fixture=self.base.fixture;f=self.fixture;self.api=f.api;self.seen=[]
        self.plan=f.plan_for([f.case],maximum_requests=8)
        raw=b'/* authored existing script */';url='https://autorace.jp/content/assets/js/app.js'
        self.original_script=dict(raw_base64=base64.b64encode(raw).decode(),metadata=dict(source_url=url,final_url=url,status=200,
            byte_count=len(raw),source_sha256=sha256(raw).hexdigest(),headers={'Content-Type':'application/javascript'},
            fetched_at=(f.clock.now()-timedelta(hours=1)).isoformat(),response_received_at=(f.clock.now()-timedelta(minutes=59)).isoformat(),
            http_method='GET',resource_type='script'))
        self.plan['static_cache']=[deepcopy(self.original_script)];self.manifest=f.sealed(self.plan)
        self.manifest.update(schema=self.api.SCHEMA_V2,prior_journal_artifacts=[],allow_order_only=True)
        self.browser=captured_browser(f.clock,self.seen)
        with patch.object(self.api,'ROOT',f.repo),patch.object(self.api.freeze,'frozen_inputs',return_value=[f.native]):
            status=self.api.collect(f.root/'first',f.env,self.manifest,clock=f.clock.now,sleeper=f.clock.sleep,browser=self.browser)
        self.assertEqual(status['source_requests'],8);self.assertFalse(status['ready']);self.assertEqual(self.seen[0]['request_budget'],8)
        self.body=open_forecasts((f.root/'first.collection.enc').read_bytes(),key=KEY)
        self.assertEqual(self.body['browser_attempt']['state'],'COMPLETE');self.assertEqual(self.body['captures'],[])
        f.clock.value+=timedelta(seconds=3601);self.pin,self.actual,self.raw=self.pack(self.body)
        self.next_manifest=dict(self.manifest,prior_journal_artifacts=[self.pin]);self.seen.clear()
    def pack(self,body):
        cipher=seal_forecasts(body,run_id='42',round_no=900006,key=KEY);stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('collection.enc',cipher)
        raw=stream.getvalue();pin=dict(id=990,digest='sha256:'+sha256(raw).hexdigest(),run_id=42,head_sha=fixtures.HEAD)
        saved=self.api.stamp(body['browser_attempt']['completed_at'])+timedelta(seconds=1)
        actual=dict(id=990,name='official-result-collection-journal-42',expired=False,digest=pin['digest'],size_in_bytes=len(raw),
            created_at=saved.isoformat(),expires_at=(self.fixture.clock.now()+timedelta(days=7)).isoformat(),workflow_run=dict(id=42,
                head_sha=fixtures.HEAD,repository_id=1416489937,head_repository_id=1416489937))
        return pin,actual,raw
    def prior(self,manifest=None,output=None):
        with patch.object(self.api.future,'metadata',return_value=self.actual),patch.object(self.api.future,'gh',return_value=self.raw):
            return self.api.prior_journals(self.next_manifest if manifest is None else manifest,now=self.fixture.clock.now(),key=KEY,
                private_static_cache_out=output)
    def test_complete_hold_private_cache_is_authenticated_without_public_raw_or_relabeling_outcome(self):
        output={};before=digest(self.body);public=self.prior(output=output)
        self.assertEqual(len(output['entries']),3);self.assertEqual(digest(self.body),before)
        self.assertEqual(public['prior_journal_artifact_count'],1)
        for key in ('entries','raw_base64','source_url','static_cache'):self.assertNotIn(key,json.dumps(public))
        self.assertEqual(output['lineage']['source_journals'],[self.pin])
        self.assertEqual(output['lineage']['cache_entry_count'],3)
        self.assertEqual(self.body['browser_attempt']['actual_request_count'],8)
        self.assertEqual(self.body['cases'][0]['state'],'HOLD_UI_OR_SOURCE_UNAVAILABLE')
    def test_runtime_only_merge_saves_three_dispatches_and_preserves_signed_plan_native_and_clocks(self):
        f=self.fixture;before_plan=deepcopy(self.plan);before_native=digest(f.native)
        cipher=(f.repo/self.manifest['plan_path']).read_bytes()
        with patch.object(self.api,'ROOT',f.repo),patch.object(self.api.freeze,'frozen_inputs',return_value=[f.native]), \
             patch.object(self.api.future,'metadata',return_value=self.actual),patch.object(self.api.future,'gh',return_value=self.raw):
            status=self.api.collect(f.root/'next',dict(f.env,run_id=43,head_sha='c'*40),self.next_manifest,
                clock=f.clock.now,sleeper=f.clock.sleep,browser=self.browser)
        self.assertEqual(status['source_requests'],5);self.assertEqual(status['source_requests_upper_bound'],8)
        self.assertFalse(status['ready']);self.assertEqual(len(self.seen[0]['static_cache']),4)
        self.assertEqual(self.plan,before_plan);self.assertEqual(digest(f.native),before_native)
        self.assertEqual((f.repo/self.manifest['plan_path']).read_bytes(),cipher)
        journal=open_forecasts((f.root/'next.collection.enc').read_bytes(),key=KEY)
        self.assertEqual(journal['prior_static_cache']['cache_entry_count'],3)
        self.assertEqual(journal['prior_static_cache']['source_journals'],[self.pin])
        self.assertNotIn('raw_base64',json.dumps(journal['prior_static_cache']))
        original={e['source_sha256']:e['raw_base64'] for e in self.body['browser_quarantine']['files']}
        for entry in self.seen[0]['static_cache']:
            if entry['metadata']['resource_type']=='script':
                self.assertEqual(entry,self.original_script);continue
            self.assertEqual(entry['raw_base64'],original[entry['metadata']['source_sha256']])
            self.assertLess(self.api.stamp(entry['metadata']['response_received_at']),self.api.stamp(journal['epoch_started_at']))
        for value in ('synthetic-style','raw_base64','source_url'):self.assertNotIn(value,json.dumps(status))
        self.api._journal_origin((f.root/'next.collection.enc').read_bytes(),key=KEY,run_id=43,head_sha='c'*40,now=f.clock.now())
    def test_denied_unknown_expired_or_bad_cipher_never_populates_private_cache(self):
        original=(self.pin,self.actual,self.raw)
        for kind in ('denied','unknown','expired','cipher'):
            output={};body=deepcopy(self.body)
            if kind=='denied':body['browser_index']['ledger'][0]['status']=403
            if kind=='unknown':body['browser_attempt']['state']='RESERVED'
            self.pin,self.actual,self.raw=self.pack(body)
            if kind=='expired':self.actual['expired']=True
            if kind=='cipher':self.raw=self.raw[:-1]+bytes([self.raw[-1]^1])
            manifest=dict(self.next_manifest,prior_journal_artifacts=[self.pin])
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.prior(manifest,output)
            self.assertEqual(output,{});self.assertEqual(self.seen,[])
        self.pin,self.actual,self.raw=original

    def test_default_public_prior_path_never_extracts_raw_static_bytes(self):
        from race_ai import all_existing_model_prior_static_cache as cache
        with patch.object(self.api.future,'metadata',return_value=self.actual),patch.object(self.api.future,'gh',return_value=self.raw), \
                patch.object(cache,'extract_static_cache',side_effect=AssertionError('private path must be opt-in')):
            public=self.api.prior_journals(self.next_manifest,now=self.fixture.clock.now(),key=KEY)
        self.assertEqual(set(public),{'prior_journal_artifact_count','prior_journal_receipts_sha256',
            'prior_journal_guard_scope','minimum_epoch_interval_seconds'})
        output={};self.assertEqual(public,self.prior(output=output));self.assertEqual(len(output['entries']),3)

    def test_a_later_bad_prior_leaves_private_output_empty_before_any_extraction(self):
        from race_ai import all_existing_model_prior_static_cache as cache
        first_pin,first_meta,first_raw=self.pin,self.actual,self.raw
        for kind in ('denied','unknown','recent'):
            second=deepcopy(self.body)
            if kind=='denied':second['browser_index']['ledger'][0]['status']=429
            elif kind=='unknown':second['browser_attempt']['state']='RESERVED'
            second_pin,second_meta,second_raw=self.pack(second)
            second_pin=dict(second_pin,id=991);second_meta=dict(second_meta,id=991)
            if kind=='recent':
                second={k:v for k,v in second.items() if not k.startswith('browser_')}
                second['epoch_started_at']=(self.fixture.clock.now()-timedelta(seconds=30)).isoformat()
                second['attempts']=[];second['captures']=[]
                cipher=seal_forecasts(second,run_id='42',round_no=900006,key=KEY);stream=io.BytesIO()
                with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('collection.enc',cipher)
                second_raw=stream.getvalue();second_pin=dict(second_pin,digest='sha256:'+sha256(second_raw).hexdigest())
                second_meta=dict(second_meta,digest=second_pin['digest'],size_in_bytes=len(second_raw),created_at=self.fixture.clock.now().isoformat())
            manifest=dict(self.next_manifest,prior_journal_artifacts=[first_pin,second_pin]);output={}
            def metadata(ident):return first_meta if ident==990 else second_meta
            def wire(route):return first_raw if '/990/' in route else second_raw
            with self.subTest(kind=kind),patch.object(self.api.future,'metadata',side_effect=metadata), \
                    patch.object(self.api.future,'gh',side_effect=wire), \
                    patch.object(cache,'extract_static_cache',side_effect=AssertionError('all guards must finish first')):
                with self.assertRaises(ValueError):self.api.prior_journals(manifest,now=self.fixture.clock.now(),key=KEY,private_static_cache_out=output)
            self.assertEqual(output,{});self.assertEqual(self.seen,[])

if __name__=='__main__':unittest.main()
