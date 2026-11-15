"""Synthetic fresh-card Actions integration; no live source or owner key."""
from copy import deepcopy
from datetime import timedelta
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from hashlib import sha256
from race_ai.actions_contract import digest

from tests.test_official_future_source_packet import capture_fixture
from tests import test_all_existing_model_official_recovery as old
from tests.test_all_existing_model_official_probe16 import with_known_prior
from tests.test_all_existing_model_source_packet_freeze import KEY
from tests import test_all_existing_model_source_packet_baseline_v2 as baselines
from tests.test_official_issue_transport import FakeGitHub


def manifest_fixture():
    plan,index,files,terms=capture_fixture()
    pin=lambda n:dict(id=n,digest='sha256:'+str(n%10)*64,run_id=n+10,head_sha='a'*40)
    return dict(schema='RACE_AI_OFFICIAL_FUTURE_SOURCE_CAPTURE_INPUT_V1',execution_day='2030-01-15',
        cases=plan['cases'],terms_manifest=terms,maximum_requests=32,
        baseline_artifacts={sport:pin(900) for sport in ('autorace','keirin')},carrier_artifact=pin(700),
        prior_journal_artifacts=deepcopy(old.fixture()[0]['request']['manifest']['prior_journal_artifacts']))


class FutureSourceCaptureTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.all_existing_model_future_source_capture'))
        return importlib.import_module('race_ai.all_existing_model_future_source_capture')

    def test_manifest_exact_two_original_ui_choices_and_current_day(self):
        api=self.api();manifest=manifest_fixture();now=capture_fixture()[1]['completed_at']
        self.assertEqual(api.validate_manifest(manifest,now=now),manifest)
        for change in ('day','extra','budget','host','query','duplicate','missing','pin','unknown_case'):
            value=deepcopy(manifest)
            if change=='day':value['execution_day']='2030-01-14'
            elif change=='extra':value['unused']=True
            elif change=='budget':value['maximum_requests']=33
            elif change=='host':value['cases'][0]['ui_entry_url']='https://example.test/'
            elif change=='query':value['cases'][0]['ui_entry_url']+='?x=1'
            elif change=='duplicate':value['cases'][1]=deepcopy(value['cases'][0])
            elif change=='missing':value['cases'].pop()
            elif change=='pin':value['baseline_artifacts']['keirin']['id']=True
            else:value['cases'][0]['unregistered_case']=True
            with self.subTest(change=change),self.assertRaises(ValueError):api.validate_manifest(value,now=now)

    def test_history_authenticates_every_prior_and_keeps_fixed_unknown(self):
        api=self.api();data=with_known_prior();manifest=manifest_fixture()
        manifest['prior_journal_artifacts']=data['request']['manifest']['prior_journal_artifacts']
        result=api.authenticate_future_history(manifest,journal_archives=data['prior_journal_archives'],
            old_run=data['old_run'],prior_runs=data['prior_runs'],now=old.NOW,key=KEY)
        self.assertIsNone(result['old_source_requests_actual']);self.assertEqual(result['old_source_requests_upper_bound'],32)
        self.assertEqual(result['prior_journal_artifact_count'],2)
        for change in ('missing','denied','unknown','recent','active'):
            value=with_known_prior(change if change in ('denied','unknown') else None)
            if change=='missing':value['prior_journal_archives'].pop()
            if change=='recent':value['prior_runs'][0]['updated_at']=(old.NOW-timedelta(minutes=1)).isoformat()
            if change=='active':value['prior_runs'][0]['status']='in_progress'
            with self.subTest(change=change),self.assertRaises(ValueError):
                api.authenticate_future_history(manifest,journal_archives=value['prior_journal_archives'],
                    old_run=value['old_run'],prior_runs=value['prior_runs'],now=old.NOW,key=KEY)

    def test_node_transport_environment_has_no_owner_gh_or_arbitrary_secrets(self):
        from scripts import all_existing_model_future_source_capture as wrapper
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'browser';directory.mkdir(mode=0o700)
            index=directory/'capture-index.json';index.write_text('{}');index.chmod(0o600)
            with patch.dict(os.environ,{'PATH':'/usr/bin:/bin','RACE_AI_STATE_KEY':'private','GITHUB_TOKEN':'private','GH_TOKEN':'private',
                'ARBITRARY_PASSWORD':'private','NODE_OPTIONS':'--require=private','HTTPS_PROXY':'http://proxy.test:80',
                'NODE_EXTRA_CA_CERTS':'/tmp/ca.crt'},clear=True),patch.object(wrapper,'subprocess') as sub:
                sub.run.return_value.returncode=0;sub.run.return_value.stdout=b'{}';sub.run.return_value.stderr=b''
                wrapper.capture_browser({},directory)
            sent=sub.run.call_args.kwargs['env']
            self.assertEqual(sent['HTTPS_PROXY'],'http://proxy.test:80');self.assertEqual(sent['NODE_EXTRA_CA_CERTS'],'/tmp/ca.crt')
            self.assertFalse({'RACE_AI_STATE_KEY','GITHUB_TOKEN','GH_TOKEN','ARBITRARY_PASSWORD','NODE_OPTIONS'}&set(sent))

    def test_actions_scope_is_checked_before_any_owner_key_lookup(self):
        from scripts import all_existing_model_future_source_capture as wrapper
        with patch.dict(os.environ,{},clear=True),patch.object(wrapper.future,'environment') as entered:
            with self.assertRaises(ValueError):wrapper.environment()
        entered.assert_not_called()

    def test_nonzero_node_completion_cannot_promote_an_existing_index_to_known_success(self):
        from scripts import all_existing_model_future_source_capture as wrapper
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'browser';directory.mkdir(mode=0o700)
            (directory/'capture-index.json').write_text('{}')
            with patch.object(wrapper.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout=b'{}',stderr=b'')):
                with self.assertRaises(ValueError):wrapper.capture_browser({},directory)

    def test_same_source_original_index_and_journal_must_agree(self):
        from scripts import all_existing_model_future_source_capture as wrapper
        plan,index,files,terms=capture_fixture();now=wrapper.core.clock(index['completed_at'])
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);root.chmod(0o700);browser=root/'browser';browser.mkdir(mode=0o700)
            source=root/'source';source.mkdir(mode=0o700);env=dict(run_id=42,head_sha='a'*40)
            for name,raw in dict(files,**{'capture-index.json':wrapper.future.wire(index)}).items():
                path=browser/name;path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);path.write_bytes(raw);path.chmod(0o600)
            items,complete=wrapper.inventory(browser,source,env,key=KEY);self.assertTrue(complete)
            reservation=dict(schema=wrapper.core.JOURNAL,state='RESERVED',manifest=manifest_fixture(),
                manifest_sha256=digest(manifest_fixture()),workflow_run_id=42,code_sha='a'*40,
                epoch_started_at=plan['available_after'],plan_sha256=digest(plan),source_requests_actual=None,maximum_requests=32,history={})
            # manifest_fixture creates fresh randomized prior receipts; bind one unchanged instance.
            reservation['manifest_sha256']=digest(reservation['manifest'])
            journal=dict(reservation,state='CAPTURE_RETAINED',completed_at=now.isoformat(),capture_index=deepcopy(index),
                capture_inventory=items,raw_retention_complete=True,native_ready=False)
            journal['capture_index']['stop_reason']='OTHER_CHANGED_INDEX'
            wrapper._seal(source/'reservation.enc',reservation,env,KEY);wrapper._seal(source/'plan.enc',plan,env,KEY)
            wrapper._seal(source/'collection.enc',journal,env,KEY)
            raw=archive_directory(source);actual=dict(id=800,name='official-future-source-capture-42',expired=False,
                size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),created_at=now.isoformat(),
                expires_at=(now+timedelta(days=1)).isoformat(),workflow_run=dict(id=42,head_sha='a'*40,
                repository_id=1416489937,head_repository_id=1416489937))
            with self.assertRaises(ValueError):wrapper.source_archive(raw,actual,env,now=now,key=KEY)

    def test_future_window_checks_day_baseline_precision_and_margin(self):
        api=self.api();manifest=manifest_fixture();plan,index,files,terms=capture_fixture()
        now=api.clock(index['completed_at'])
        contexts={sport:dict(receipt=dict(created_at=(now-timedelta(minutes=2)).isoformat()),training=dict(models={
            sport+'/'+api.LEARNED_ID:dict(native_training=dict(created_at=(now-timedelta(minutes=3)).isoformat()))}))
            for sport in ('autorace','keirin')}
        out=api.prepare_capture(manifest,contexts,now=now)
        self.assertEqual(out['cases'],manifest['cases']);self.assertEqual(out['request_budget'],32)
        self.assertEqual(out['available_after'],(now-timedelta(minutes=2)+timedelta(seconds=1)).isoformat())
        for change in ('baseline','model','day','margin'):
            m=deepcopy(manifest);c=deepcopy(contexts);at=now
            if change=='baseline':c['autorace']['receipt']['created_at']=now.isoformat()
            elif change=='model':c['keirin']['training']['models']['keirin/'+api.LEARNED_ID]['native_training']['created_at']=now.isoformat()
            elif change=='day':at+=timedelta(days=1)
            else:m['cases'][0]['cutoff_at']=(now+timedelta(seconds=600)).isoformat()
            with self.subTest(change=change),self.assertRaises(ValueError):api.prepare_capture(m,c,now=at)


def archive_directory(directory):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.iterdir()):archive.writestr(path.name,path.read_bytes())
    return stream.getvalue()


class FreshNativeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.helper=baselines.SourcePacketBaselineV2Tests('runTest');self.helper.setUp();self.addCleanup(self.helper.doCleanups)
        isolated=patch.dict(os.environ,{k:v for k,v in os.environ.items() if k!='NODE_PATH'},clear=True)
        isolated.start();self.addCleanup(isolated.stop)
        self.directory=self.helper.root/'fresh';self.env=self.helper.env;self.now=self.helper.now
        self.env['run_attempt']=1

    def generated(self,*,failure=None):
        from scripts import all_existing_model_future_source_capture as wrapper
        api=wrapper.freeze;baseline,baseline_meta=self.helper.baseline(order=True)
        self.marker_transport=wrapper.once.FutureSourceMarkerTransport(FakeGitHub())
        carrier,carrier_meta=self.helper.carrier();manifest=manifest_fixture()
        manifest['baseline_artifacts']={s:deepcopy(self.helper.pin) for s in ('autorace','keirin')}
        manifest['carrier_artifact']=deepcopy(self.helper.carrier_pin)
        old_data,_,_=old.fixture();meta=deepcopy(old_data['old_journal_metadata']);meta['expires_at']=(self.now+timedelta(days=7)).isoformat()
        manifest['prior_journal_artifacts']=deepcopy(old_data['request']['manifest']['prior_journal_artifacts'])
        clock=[self.now-timedelta(seconds=80)]
        calls=[]
        def capture(plan,directory,**_):
            calls.append(plan);directory.mkdir(mode=0o700)
            p,index,files,terms=capture_fixture();index['available_after']=plan['available_after']
            if failure=='interrupted':
                files={'request-ledger-001.json':b'{"actual_request_count":1,"ledger":[]}'}
            for name,raw in files.items():
                target=directory/name;target.parent.mkdir(parents=True,mode=0o700,exist_ok=True);target.write_bytes(raw);target.chmod(0o600)
            clock[0]=self.now+timedelta(seconds=3)
            if failure=='interrupted':raise TimeoutError('PRIVATE MUST NEVER BE PRINTED')
            (directory/'capture-index.json').write_bytes(wrapper.future.wire(index))
            (directory/'capture-index.json').chmod(0o600)
            if failure=='indexed_interruption':raise TimeoutError('private fixture process timeout')
            if failure=='late':clock[0]=self.now+timedelta(hours=2)
            return index
        mapping={700:(carrier,carrier_meta),900:(baseline,baseline_meta),meta['id']:(old_data['old_journal_raw'],meta)}
        def gh(path):
            if path=='actions/runs/'+str(old_data['old_run']['id']):return wrapper.future.wire(old_data['old_run'])
            return mapping[int(path.split('/')[2])][0]
        with patch.object(wrapper,'utc_now',side_effect=lambda:clock[0]),patch.object(api,'utc_now',side_effect=lambda:clock[0]),\
            patch.object(wrapper.future,'metadata',side_effect=lambda i:mapping[i][1]),patch.object(wrapper.future,'gh',side_effect=gh),\
            patch.object(wrapper.collector,'load_plan',return_value=old_data['old_plan']),\
            patch.object(wrapper,'capture_browser',side_effect=capture):
            result=wrapper.generate(manifest,self.directory,self.env,marker_transport=self.marker_transport)
        return result,manifest,mapping,calls

    def test_real_mac_baseline_fixed_eleven_inputs_encrypted_source_and_dual_actual_readback(self):
        from scripts import all_existing_model_future_source_capture as wrapper
        from tests.test_all_existing_model_source_packet_freeze import packed
        result,manifest,mapping,calls=self.generated()
        self.assertTrue(result['ready'],result);self.assertEqual(result['source_requests'],4)
        self.assertEqual(result['captured_native_input_count'],11);self.assertEqual(result['baseline_attachment_count'],2)
        records=wrapper.freeze.local_records(self.directory/'native')
        _,original_index,original_files,terms=capture_fixture();original_index['available_after']=calls[0]['available_after']
        built=wrapper.builder.build_source_packet(calls[0],original_index,original_files,terms_manifest=terms,
            as_of=wrapper.core.clock(original_index['completed_at']))
        expected={r['cell_key']:r['native_payload'] for r in built['requests']}
        for record in records:
            for capsule in record['captured_native_inputs']:
                self.assertEqual(wrapper.core.clock(capsule['captured_as_of']),self.now)
                original=deepcopy(capsule['native_payload']);original.pop('learned_model',None);original.pop('baseline_attachment',None)
                self.assertEqual(original,expected[capsule['cell_key']])
        for path in (self.directory/'source').iterdir():self.assertEqual(path.suffix,'.enc')
        source=archive_directory(self.directory/'source');native=packed(self.directory/'native')
        def metadata(ident,raw,name):return dict(id=ident,name=name,digest='sha256:'+sha256(raw).hexdigest(),
            size_in_bytes=len(raw),expired=False,created_at=(self.now+timedelta(seconds=5)).isoformat(),
            expires_at=(self.now+timedelta(days=7)).isoformat(),workflow_run=dict(id=42,head_sha=self.env['head_sha'],
            repository_id=1416489937,head_repository_id=1416489937))
        mapping.update({801:(native,metadata(801,native,'all-existing-model-pairs-42-900003')),
            802:(source,metadata(802,source,'official-future-source-capture-42'))})
        with patch.object(wrapper,'utc_now',return_value=self.now+timedelta(seconds=6)),\
            patch.object(wrapper.freeze,'utc_now',return_value=self.now+timedelta(seconds=6)),\
            patch.object(wrapper.future,'metadata',side_effect=lambda i:mapping[i][1]),\
            patch.object(wrapper.future,'gh',side_effect=lambda p:mapping[int(p.split('/')[2])][0]):
            checked=wrapper.readback(801,802,self.directory,self.env,manifest,marker_transport=self.marker_transport)
        self.assertTrue(checked['independent_source_capture_receipt_verified'])
        self.assertTrue(checked['independent_baseline_artifact_receipts_verified'])
        self.assertEqual(checked['fixed_as_of'],built['fixed_as_of'])
        with self.assertRaises(ValueError):wrapper.generate(manifest,self.directory,self.env)

    def test_interrupted_capture_retains_encrypted_checkpoint_and_unknown_count_without_native_inputs(self):
        from race_ai.boat_all_model_store import open_forecasts
        result,manifest,mapping,calls=self.generated(failure='interrupted')
        self.assertFalse(result['ready']);self.assertIsNone(result['source_requests'])
        self.assertFalse((self.directory/'native').exists());self.assertEqual(len(calls),1)
        journal=open_forecasts((self.directory/'source'/'collection.enc').read_bytes(),key=KEY)
        self.assertTrue(journal['raw_retention_complete']);self.assertIsNone(journal['source_requests_actual'])
        self.assertEqual(journal['capture_inventory'][0]['file'],'request-ledger-001.json')
        self.assertNotIn('PRIVATE MUST NEVER BE PRINTED',json.dumps(result))

    def test_actual_capture_becoming_late_is_held_after_retaining_originals(self):
        result,manifest,mapping,calls=self.generated(failure='late')
        self.assertFalse(result['ready']);self.assertEqual(result['source_requests'],4)
        self.assertTrue((self.directory/'source'/'collection.enc').exists());self.assertFalse((self.directory/'native').exists())

    def test_process_failure_with_a_written_index_retains_raw_but_keeps_actual_count_unknown(self):
        from race_ai.boat_all_model_store import open_forecasts
        result,_,_,_=self.generated(failure='indexed_interruption')
        self.assertFalse(result['ready']);self.assertIsNone(result['source_requests'])
        self.assertFalse((self.directory/'native').exists())
        journal=open_forecasts((self.directory/'source'/'collection.enc').read_bytes(),key=KEY)
        self.assertIsNotNone(journal['capture_index']);self.assertIsNone(journal['source_requests_actual'])
        self.assertTrue(journal['raw_retention_complete'])


if __name__=='__main__':unittest.main()
