"""Synthetic owner Actions/ZIP/AES PDCA entry, no network or real key."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
import importlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from race_ai.boat_venue_learning import read_candidate
from tests import test_all_existing_model_order_only_pdca as fixture


class OrderOnlyPDCACliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.training=fixture.training()
    def setUp(self):
        self.source=fixture.OrderOnlyPrivatePDCATests('runTest');self.source.training=self.training;self.source.setUp()
        self.addCleanup(self.source.doCleanups);self.root=self.source.root;self.out=self.root/'entry'
        self.now=fixture.EVALUATED_AT;self.transport=[]
        self.event=self.root/'event.json';self.event.write_text(json.dumps(dict(number=71,pull_request=dict(number=71,
            head=dict(sha=fixture.PDCA_HEAD,repo=dict(id=1416489937,full_name='haji84/RACE-AI')),
            base=dict(repo=dict(id=1416489937,full_name='haji84/RACE-AI'))))))
        environment=patch.dict(os.environ,dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',
            GITHUB_REPOSITORY_ID='1416489937',GITHUB_RUN_ID='111',RUNNER_TEMP=str(self.root),
            GITHUB_EVENT_NAME='pull_request',GITHUB_REF='refs/pull/71/merge',GITHUB_EVENT_PATH=str(self.event)))
        environment.start();self.addCleanup(environment.stop)
        deny=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('provider forbidden'))
        deny.start();self.addCleanup(deny.stop)
        self.manifest=dict(schema='RACE_AI_ORDER_ONLY_PDCA_INPUT_V1',future_artifact=self.pin(self.source.native_meta),
            result_artifact=self.pin(self.source.result_meta),additional_native_artifacts=[])
        self.path=self.root/'input.json';self.path.write_text(json.dumps(self.manifest))
        self.actual={800:self.source.native_meta,900:self.source.result_meta}
        self.archives={800:self.source.native_raw,900:self.source.result_raw}
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.all_existing_model_order_only_pdca'),
            'explicit Actions ORDER_ONLY PDCA entry absent')
        return importlib.import_module('scripts.all_existing_model_order_only_pdca')
    @staticmethod
    def pin(meta):
        return dict(id=meta['id'],digest=meta['digest'],run_id=meta['workflow_run']['id'],head_sha=meta['workflow_run']['head_sha'])
    def gh(self,path):
        self.transport.append(path)
        if path=='actions/runs/111':
            return json.dumps(dict(id=111,head_sha=fixture.PDCA_HEAD,repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
                head_repository=dict(id=1416489937,full_name='haji84/RACE-AI'))).encode()
        fields=path.split('/');ident=int(fields[2]);return self.archives[ident] if len(fields)==4 else json.dumps(self.actual[ident]).encode()
    def main(self,extra=()):
        api=self.module();stdout=io.StringIO();github=self.root/'github-output'
        with patch.object(api.future,'gh',side_effect=self.gh),patch.object(api,'utc_now',side_effect=lambda:self.now), \
                patch.dict(os.environ,GITHUB_OUTPUT=str(github)),redirect_stdout(stdout):
            code=api.main(['--input',str(self.path),'--out-dir',str(self.out),*extra])
        return code,json.loads(stdout.getvalue())
    def test_real_synthetic_archives_score_and_actual_pdca_zip_readback(self):
        code,status=self.main();self.assertEqual(code,0);self.assertTrue(status['ready'])
        self.assertEqual(status['paired_forecasts'],2);self.assertEqual(status['source_requests'],0)
        self.assertEqual(status['artifact_name'],'all-existing-model-order-only-pdca-111-900009')
        self.assertFalse(status['independent_pdca_artifact_receipt_verified']);self.assertFalse(status['monetary_evaluation_available'])
        parts=list(self.out.iterdir());self.assertEqual(len(parts),2)
        for part in parts:
            self.assertEqual({p.name for p in part.iterdir()},{'learning.json','learning.enc','summary.json'})
            self.assertEqual(part.stat().st_mode&0o777,0o700)
            self.assertTrue(all(p.stat().st_mode&0o777==0o600 for p in part.iterdir()))
            self.assertEqual(read_candidate(part)['observation']['status'],'rank_confirmed')
        for private in ('scoreboard','ordered_top3','source_ref','raw_base64','roster','coefficients'):
            self.assertNotIn(private,json.dumps(status))
        raw=fixture.archive(self.out);self.actual[1000]=fixture.metadata(raw,1000,status['artifact_name'],111,fixture.PDCA_HEAD,self.now+timedelta(seconds=2))
        self.archives[1000]=raw;self.now+=timedelta(seconds=3)
        _,checked=self.main(['--readback-artifact','1000'])
        self.assertTrue(checked['ready']);self.assertTrue(checked['independent_pdca_artifact_receipt_verified'])
        self.assertEqual(checked['paired_forecasts'],2);self.assertEqual(checked['source_requests'],0)
        self.assertTrue((self.root/'entry.generation.json').exists());self.assertTrue((self.root/'entry.status.json').exists())
        self.assertIn('ready=true',(self.root/'github-output').read_text())
    def test_no_key_or_non_pr71_context_holds_before_any_github_read(self):
        for changes in (dict(RACE_AI_STATE_KEY=''),dict(GITHUB_REF='refs/pull/72/merge'),dict(GITHUB_EVENT_NAME='workflow_dispatch'),
                dict(GITHUB_REPOSITORY='someone/fork')):
            self.transport=[]
            with patch.dict(os.environ,changes):
                _,status=self.main()
            self.assertFalse(status['ready']);self.assertEqual(self.transport,[]);self.assertFalse(self.out.exists())
    def test_invalid_local_pr_head_or_fork_is_rejected_before_github(self):
        original=json.loads(self.event.read_text())
        for kind in ('head','fork','number'):
            event=deepcopy(original)
            if kind=='head':event['pull_request']['head']['sha']='not-a-head'
            elif kind=='fork':event['pull_request']['head']['repo']['id']=999
            else:event['pull_request']['number']=72
            self.event.write_text(json.dumps(event));self.transport=[]
            _,held=self.main();self.assertFalse(held['ready']);self.assertEqual(self.transport,[])
    def test_strict_manifest_and_metadata_fail_before_zip_or_output(self):
        api=self.module()
        for change in ({'extra':1},{'future_artifact':dict(self.manifest['future_artifact'],id=True)},
                {'additional_native_artifacts':[self.manifest['future_artifact']]},
                {'additional_native_artifacts':[dict(self.manifest['future_artifact'],id=i+10000) for i in range(17)]}):
            self.path.write_text(json.dumps(dict(self.manifest,**change)));self.transport=[]
            _,status=self.main();self.assertFalse(status['ready']);self.assertFalse(self.out.exists())
            self.assertFalse(any(p.endswith('/zip') for p in self.transport))
        self.path.write_text(json.dumps(self.manifest))
        for change in ({'expired':True},{'name':'all-existing-model-pairs-100-1'},
                {'workflow_run':dict(self.source.native_meta['workflow_run'],repository_id=1)},
                {'digest':'sha256:'+'f'*64},{'size_in_bytes':64*1024*1024+1}):
            self.actual[800]=dict(self.source.native_meta,**change);self.transport=[]
            _,status=self.main();self.assertFalse(status['ready']);self.assertFalse(self.out.exists())
            self.assertFalse(any(p.endswith('/zip') for p in self.transport))

    def test_additional_native_is_authenticated_and_bound_without_extra_forecasts(self):
        raw,meta=self.source.native_archive(self.source.requests,'extra',801,2)
        self.actual[801]=meta;self.archives[801]=raw;self.manifest['additional_native_artifacts']=[self.pin(meta)]
        self.path.write_text(json.dumps(self.manifest));_,status=self.main()
        self.assertTrue(status['ready']);self.assertEqual(status['paired_forecasts'],2)
        self.assertEqual(status['additional_native_artifact_count'],1)
        payload=read_candidate(next(self.out.iterdir()))
        self.assertEqual(payload['additional_native_admissions'][0]['artifact_id'],801)
        self.manifest['additional_native_artifacts']=[];self.path.write_text(json.dumps(self.manifest));self.transport=[]
        _,held=self.main(['--readback-artifact','1000'])
        self.assertFalse(held['ready']);self.assertFalse(any('/1000' in p for p in self.transport))

    def test_advertised_aggregate_bound_is_checked_before_any_zip_download(self):
        self.actual[800]=dict(self.actual[800],size_in_bytes=64*1024*1024)
        self.actual[900]=dict(self.actual[900],size_in_bytes=64*1024*1024)
        for ident in (10000,10001,10002):
            meta=dict(self.source.native_meta,id=ident,size_in_bytes=64*1024*1024)
            self.actual[ident]=meta;self.manifest['additional_native_artifacts'].append(self.pin(meta))
        self.path.write_text(json.dumps(self.manifest));_,status=self.main()
        self.assertFalse(status['ready']);self.assertFalse(self.out.exists())
        self.assertFalse(any(p.endswith('/zip') for p in self.transport))

    def test_source_only_inputs_hold_without_fake_forecasts_or_loss_and_cannot_reset(self):
        requests=[dict(r,cell_key=r['cell_key'].split('/',1)[0]+'/'+fixture.ALL_MODELS[1]) for r in self.source.requests]
        raw,meta=self.source.native_archive(requests,'input-only',803,4)
        self.actual[803]=meta;self.archives[803]=raw;self.manifest['future_artifact']=self.pin(meta)
        self.path.write_text(json.dumps(self.manifest));_,status=self.main()
        self.assertFalse(status['ready']);self.assertEqual(status['partition_count'],0)
        self.assertEqual(status['paired_forecasts'],0);self.assertEqual(list(self.out.iterdir()),[])
        self.assertFalse((self.root/'entry.generation.json').exists());self.transport=[]
        _,held=self.main();self.assertFalse(held['ready'])
        self.assertFalse(any(p.endswith('/zip') for p in self.transport))

    def test_cash_pending_and_special_results_stay_outside_order_only(self):
        import base64
        from race_ai.manual_official_capture import official_rights_ref
        from race_ai.autorace_official_result_adapter import parse_result as auto_parse
        from race_ai.keirin_official_result_adapter import parse_result as keirin_parse
        from tests import test_autorace_official_result_adapter as auto
        from tests import test_keirin_official_result_adapter as keirin
        for kind in ('pending','special'):
            data=auto.fixture();a=auto.wire(data['result']);am=data['metadata']
            result,b,bm,_=keirin.fixture(unit=False)
            if kind=='pending':result['tyakujyunDispFlg']=False
            else:result['tyakujyunItemSubData'][1]['tyaku']='1'
            b=keirin.rebuild(result,bm)
            self.source.captures=[dict(raw_base64=base64.b64encode(a).decode(),metadata=am),
                dict(raw_base64=base64.b64encode(b).decode(),metadata=bm)]
            self.source.labels=[auto_parse(a,am,frozen_native_payload=self.source.requests[0]['native_payload'],now=self.now,
                source_rights_ref=official_rights_ref('autorace')),
                keirin_parse(b,bm,frozen_native_payload=self.source.requests[1]['native_payload'],now=self.now,
                source_rights_ref=official_rights_ref('keirin'),allow_order_only=True)]
            raw,meta=self.source.result_archive();self.actual[900]=meta;self.archives[900]=raw
            self.manifest['result_artifact']=self.pin(meta);self.path.write_text(json.dumps(self.manifest))
            self.out=self.root/('outside-'+kind)
            _,status=self.main();self.assertFalse(status['ready']);self.assertEqual(status['paired_forecasts'],0)
            self.assertEqual(status['outside_order_only_result_state_counts'],dict(settled=1,**{kind:1}))
            for folder in self.out.iterdir():
                payload=read_candidate(folder);self.assertIsNone(payload['observation'])
                self.assertEqual(payload['score'],dict(state='NO_ORDER_ONLY_TEACHER',paired=False))

    def test_source_digest_failure_holds_without_output_and_does_not_leak_stderr(self):
        self.archives[800]=self.archives[800]+b'changed'
        _,status=self.main();self.assertFalse(status['ready']);self.assertFalse(self.out.exists())
        api=self.module();stdout=io.StringIO()
        with patch.object(api.future,'gh',side_effect=RuntimeError('https://fixture.invalid?sig=PRIVATE_SAS_AND_KEY')),redirect_stdout(stdout):
            api.main(['--input',str(self.path),'--out-dir',str(self.root/'other')])
        self.assertNotIn('PRIVATE_SAS_AND_KEY',stdout.getvalue());self.assertNotIn('fixture.invalid',stdout.getvalue())
        self.assertFalse(json.loads(stdout.getvalue())['ready'])

    def test_existing_output_never_rewrites_prediction_or_score_bytes(self):
        _,status=self.main();self.assertTrue(status['ready'])
        before={str(p.relative_to(self.out)):p.read_bytes() for p in self.out.rglob('*') if p.is_file()}
        generation=(self.root/'entry.generation.json').read_bytes();self.transport=[]
        _,held=self.main();self.assertFalse(held['ready'])
        self.assertEqual(before,{str(p.relative_to(self.out)):p.read_bytes() for p in self.out.rglob('*') if p.is_file()})
        self.assertEqual(generation,(self.root/'entry.generation.json').read_bytes())
        self.assertFalse(any(p.endswith('/zip') for p in self.transport))

    def test_actual_pdca_identity_digest_and_reencrypted_originals_cannot_pass_readback(self):
        import zipfile
        from race_ai.boat_venue_learning import seal_candidate
        _,status=self.main();self.assertTrue(status['ready']);original=fixture.archive(self.out)
        actual=fixture.metadata(original,1000,status['artifact_name'],111,fixture.PDCA_HEAD,self.now+timedelta(seconds=2))
        self.archives[1000]=original;self.now+=timedelta(seconds=3)
        for change in ({'expired':True},{'digest':'sha256:'+'f'*64},
                {'workflow_run':dict(actual['workflow_run'],head_sha='f'*40)},
                {'name':'all-existing-model-order-only-pdca-111-1'}):
            self.actual[1000]=dict(actual,**change);_,held=self.main(['--readback-artifact','1000'])
            self.assertFalse(held['ready']);self.assertFalse(held['independent_pdca_artifact_receipt_verified'])
        part=next(self.out.iterdir());replacement=self.root/'reencrypted';seal_candidate(read_candidate(part),replacement)
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as zipped:
            for p in sorted(self.out.rglob('*')):
                if p.is_file():zipped.writestr(str(p.relative_to(self.out)),
                    (replacement/p.name).read_bytes() if p.parent==part else p.read_bytes())
        changed=output.getvalue();self.archives[1000]=changed
        self.actual[1000]=fixture.metadata(changed,1000,status['artifact_name'],111,fixture.PDCA_HEAD,self.now-timedelta(seconds=1))
        _,held=self.main(['--readback-artifact','1000']);self.assertFalse(held['ready'])
        self.assertEqual(held['error_code'],'ALL_MODEL_ORDER_ONLY_PDCA_CLI_ACTUAL_ORIGINAL_READBACK')
        self.archives[1000]=original;self.actual[1000]=actual
        _,checked=self.main(['--readback-artifact','1000']);self.assertTrue(checked['ready'])

if __name__=='__main__':unittest.main()
