"""Authored continuation evidence only; no owner data/key, provider or Git I/O."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from functools import lru_cache
from hashlib import sha256
import base64
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from race_ai.actions_contract import digest
from race_ai.boat_all_model_store import seal_forecasts,open_forecasts
from tests import test_all_existing_model_official_recovery as probe
PLAN_BYTES={}

def zipped(cipher,name):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr(name,cipher)
    return out.getvalue()

def metadata(raw,ident,name,run,head,saved):
    return dict(id=ident,name=name,expired=False,size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),
        created_at=saved.isoformat(),expires_at=(saved+timedelta(days=7)).isoformat(),workflow_run=dict(id=run,
        head_sha=head,repository_id=1416489937,head_repository_id=1416489937))

def pin(meta):return dict(id=meta['id'],digest=meta['digest'],run_id=meta['workflow_run']['id'],head_sha=meta['workflow_run']['head_sha'])

@lru_cache(maxsize=1)
def complete_fixture():
    """Actual authored fit/native/normal-UI/RESULT/AES pipeline, never a source GET."""
    from race_ai import all_existing_model_official_recovery as authority
    from scripts import all_existing_model_official_result_collect as collector
    from tests import test_all_existing_model_order_only_pdca as pairs
    from tests import test_all_existing_model_official_result_collect as collect_fixtures
    pairs.OrderOnlyPrivatePDCATests.setUpClass()
    inputs=pairs.OrderOnlyPrivatePDCATests(methodName='runTest');inputs.setUp()
    browser=collect_fixtures.BrowserCollectorIntegrationTests(methodName='runTest');browser.setUp();f=browser.fixture
    try:
        natives=[]
        for number in range(4):
            actual=deepcopy(inputs.native_meta);actual['id']=800+number
            natives.append(dict(raw=inputs.native_raw,metadata=actual))
        f.native=deepcopy(inputs.requests[0]['native_payload']);f.day='2030-01-15'
        f.case=dict(sport='autorace',race_id=f.native['snapshot']['race']['race_id'],route=dict(kind='NORMAL_UI',
            ui_entry_url='https://autorace.jp/race_info/Live/isesaki',ui_venue_name=None,place_code=3))
        old_plan=f.plan_for([f.case]);old_manifest=f.sealed(old_plan)
        old_manifest.update(schema=collector.SCHEMA_V2,native_artifacts=[pin(a['metadata']) for a in natives],prior_journal_artifacts=[])
        data,old_body,_=probe.fixture();old_start=datetime(2030,1,15,2,tzinfo=timezone.utc);old_finish=old_start+timedelta(seconds=8)
        old_body.update(execution_day=f.day,manifest=old_manifest,manifest_sha256=digest(old_manifest),collection_plan_sha256=old_manifest['plan_sha256'],
            epoch_started_at=old_start.isoformat(),cases=[dict(sport='autorace',race_id=f.case['race_id'],state='HOLD_BROWSER_SOURCE_UNVERIFIED')])
        for attempt in old_body['attempts']:attempt.update(started_at=old_start.isoformat(),finished_at=old_finish.isoformat())
        old_body['browser_attempt']['started_at']=old_finish.isoformat()
        old_cipher=seal_forecasts(old_body,run_id=str(authority.OLD_RUN),round_no=900006,key=probe.KEY)
        old_raw=zipped(old_cipher,'collection.enc');old_meta=metadata(old_raw,authority.OLD_ARTIFACT,
            'official-result-collection-journal-'+str(authority.OLD_RUN),authority.OLD_RUN,authority.OLD_HEAD,old_finish)
        one_plan=dict(deepcopy(old_plan),maximum_requests=8);one_manifest=f.sealed(one_plan)
        one_manifest.update(schema=collector.SCHEMA_V2,native_artifacts=old_manifest['native_artifacts'],
            prior_journal_artifacts=[pin(old_meta)],allow_order_only=True)
        first_request=deepcopy(data['request']);first_request.update(manifest=one_manifest)
        start=datetime(2030,1,15,3,0,10,tzinfo=timezone.utc)
        def run(ident,head,attempt,updated):
            return dict(id=ident,head_sha=head,run_attempt=attempt,status='completed',conclusion='success',updated_at=updated.isoformat(),
                run_started_at=(updated-timedelta(minutes=10)).isoformat(),repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
                head_repository=dict(id=1416489937,full_name='haji84/RACE-AI'),pull_requests=[dict(number=71)])
        old_run=run(authority.OLD_RUN,authority.OLD_HEAD,1,old_finish)
        first_probe=run(77,probe.HEAD,1,start-timedelta(seconds=1))
        capsule_data=dict(request=first_request,target=dict(run_id=77,head_sha=probe.HEAD,run_attempt=2),issued_at=start.isoformat(),
            not_before=start.isoformat(),expires_at=(start+timedelta(hours=1)).isoformat(),old_journal_raw=old_raw,
            old_journal_metadata=old_meta,old_run=old_run,first_attempt=first_probe,old_plan=old_plan,new_plan=one_plan)
        capsule=authority.issue_consume_capsule(capsule_data,probe.KEY)
        active=deepcopy(first_probe);active.update(run_attempt=2,status='in_progress',conclusion=None)
        auth=authority.validate_capsule(capsule,request=first_request,current_run=active,first_attempt=first_probe,old_run=old_run,now=start,key=probe.KEY)
        f.clock.value=start;output=f.root/'probe-output';env=dict(f.env,run_id=77,head_sha=probe.HEAD)
        with patch.object(collector,'ROOT',f.repo),patch.object(collector.freeze,'frozen_inputs',return_value=[r['native_payload'] for r in inputs.requests]), \
            patch.object(collector,'_journal_artifact',return_value=(old_body,old_cipher,old_meta)):
            status=collector.collect(output,env,one_manifest,clock=f.clock.now,sleeper=f.clock.sleep,browser=browser.browser,recovery_authorization=auth)
        if status['ready'] is not True:raise AssertionError('authored normal UI probe failed')
        end=f.clock.now();journal_raw=zipped(output.with_name(output.name+'.collection.enc').read_bytes(),'collection.enc')
        journal_meta=metadata(journal_raw,90001,'official-result-collection-journal-77',77,probe.HEAD,end+timedelta(seconds=2))
        result_raw=zipped((output/'results.enc').read_bytes(),'results.enc')
        result_meta=metadata(result_raw,90002,'all-existing-official-results-77-'+str(collector.ROUND),77,probe.HEAD,end+timedelta(seconds=2))
        new_plan=dict(deepcopy(old_plan),maximum_requests=32);manifest=f.sealed(new_plan)
        manifest.update(schema=collector.SCHEMA_V2,native_artifacts=old_manifest['native_artifacts'],
            prior_journal_artifacts=[pin(old_meta),pin(journal_meta)],checkpoint_artifacts=[pin(result_meta)],allow_order_only=True)
        now=end+timedelta(hours=1,seconds=10);target_head='e'*40
        request=dict(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V2',repository_id=1416489937,pull_request=71,
            mode='FIXED_ATTEMPT_TWO_AFTER_VERIFIED_SAME_HOST_PROBE',probe_sport='autorace',old_journal_artifact_id=authority.OLD_ARTIFACT,
            manifest=manifest,probe_journal_artifact_id=90001,probe_result_artifact_id=90002,probe_request_sha256=digest(first_request))
        data=dict(request=request,target=dict(run_id=88,head_sha=target_head,run_attempt=2),issued_at=now.isoformat(),not_before=now.isoformat(),
            expires_at=(now+timedelta(minutes=30)).isoformat(),old_run=old_run,prior_runs=[run(77,probe.HEAD,2,end+timedelta(seconds=3))],
            first_attempt=run(88,target_head,1,now-timedelta(seconds=1)),probe_first_attempt=first_probe,old_plan=old_plan,new_plan=new_plan,
            journal_archives=[dict(raw=old_raw,metadata=old_meta),dict(raw=journal_raw,metadata=journal_meta)],native_archives=natives,
            checkpoint_archives=[dict(raw=result_raw,metadata=result_meta)],probe_capsule_raw=capsule)
        PLAN_BYTES.update({str(path.relative_to(f.repo)):path.read_bytes() for path in f.repo.rglob('*.enc')})
        return data,now
    finally:browser.doCleanups();inputs.doCleanups()

class ContinuationContractTests(unittest.TestCase):
    def module(self):return importlib.import_module('race_ai.all_existing_model_official_continuation')
    def test_continuation_request_requires_explicit_probe_and_bound_checkpoint_and_journal(self):
        api=self.module();data,_,_=probe.fixture();request=deepcopy(data['request'])
        request.update(schema=api.REQUEST,mode=api.MODE,probe_request_sha256='a'*64,
            probe_journal_artifact_id=90001,probe_result_artifact_id=90002)
        request['manifest']['prior_journal_artifacts'].append(dict(id=90001,digest='sha256:'+'b'*64,run_id=77,head_sha='a'*40))
        request['manifest']['checkpoint_artifacts'].append(dict(id=90002,digest='sha256:'+'c'*64,run_id=77,head_sha='a'*40))
        self.assertEqual(api.validate_request(request,probe.NOW),request)
        for change in ('no_journal','no_result','different_producer','unknown_mode','extra'):
            value=deepcopy(request)
            if change=='no_journal':value['manifest']['prior_journal_artifacts'].pop()
            elif change=='no_result':value['manifest']['checkpoint_artifacts'].pop()
            elif change=='different_producer':value['manifest']['checkpoint_artifacts'][-1]['run_id']=78
            elif change=='unknown_mode':value['mode']='ALLOW_ALL'
            else:value['approved']=True
            with self.subTest(change=change),self.assertRaises(ValueError):api.validate_request(value,probe.NOW)
    def test_same_host_original_plan_subset_is_bounded_and_keeps_terms_cache_and_pins(self):
        api=self.module();data,_,_=probe.fixture();original=data['old_plan'];new=data['new_plan']
        new['maximum_requests']=32
        api.validate_plan('autorace',original,new)
        for kind in ('budget','case_count','host','route','terms','invented_case','cache'):
            value=deepcopy(new)
            if kind=='budget':value['maximum_requests']=33
            elif kind=='case_count':value['cases']*=9
            elif kind=='host':value['cases'][0]['sport']='keirin'
            elif kind=='route':value['cases'][0]['route']['ui_entry_url']+='x'
            elif kind=='terms':value['terms_manifest']['changed']=True
            elif kind=='invented_case':value['cases'][0]['race_id']+='x'
            else:value['static_cache']=[dict(raw_base64='YQ==',metadata=dict(source_url='https://autorace.jp/new.js'))]
            with self.subTest(kind=kind),self.assertRaises(ValueError):api.validate_plan('autorace',original,value)

class AuthenticatedContinuationTests(unittest.TestCase):
    def fixture(self):data,now=complete_fixture();return deepcopy(data),now
    def test_full_original_capsule_native_complete_journal_and_raw_result_replay_then_new_mac(self):
        from race_ai import all_existing_model_official_continuation as api
        data,now=self.fixture();before=deepcopy(data);raw=api.issue_consume_capsule(data,probe.KEY)
        actual=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        auth=api.validate_capsule(raw,data=data,current_run=actual,now=now,key=probe.KEY)
        audit=auth.audit();self.assertIsNone(audit['old_source_requests_actual']);self.assertEqual(audit['old_source_requests_upper_bound'],32)
        self.assertEqual(audit['verified_probe_requests'],2);self.assertEqual(audit['maximum_new_requests'],32)
        self.assertEqual(data,before)
    def test_missing_raw_authority_native_journal_or_result_evidence_never_authorizes(self):
        from race_ai import all_existing_model_official_continuation as api
        for kind in ('authority','native','journal','result','json_authority','wrong_probe_request'):
            data,_=self.fixture()
            if kind=='authority':data['probe_capsule_raw']=b'no-original'
            elif kind=='native':data['native_archives'].pop()
            elif kind=='journal':data['journal_archives'].pop()
            elif kind=='result':data['checkpoint_archives'].pop()
            elif kind=='json_authority':data['probe_capsule_raw']={'approved':True}
            else:data['request']['probe_request_sha256']='0'*64
            with self.subTest(kind=kind),self.assertRaises((ValueError,TypeError)):api.issue_consume_capsule(data,probe.KEY)

    def mutate_journal(self,data,transform):
        from scripts import all_existing_model_official_result_collect as collector
        item=next(i for i in data['journal_archives'] if i['metadata']['id']==90001)
        body=open_forecasts(collector._journal_cipher(item['raw']),key=probe.KEY);transform(body)
        item['raw']=zipped(seal_forecasts(body,run_id='77',round_no=900006,key=probe.KEY),'collection.enc')
        item['metadata'].update(digest='sha256:'+sha256(item['raw']).hexdigest(),size_in_bytes=len(item['raw']))
        next(p for p in data['request']['manifest']['prior_journal_artifacts'] if p['id']==90001)['digest']=item['metadata']['digest']

    def test_missing_wire_outcome_interruption_counts_denial_and_raw_quarantine_refuse(self):
        from race_ai import all_existing_model_official_continuation as api
        for kind in ('missing_status','interrupted','count','deny','quarantine','authority_projection'):
            data,_=self.fixture()
            def change(body):
                if kind=='missing_status':body['browser_index']['ledger'][0].pop('status')
                elif kind=='interrupted':body['browser_attempt']['state']='INTERRUPTED'
                elif kind=='count':body['browser_attempt']['actual_request_count']=3
                elif kind=='deny':body['browser_process_diagnostic']=dict(stdout_stopped_host=True)
                elif kind=='quarantine':body['browser_quarantine']['complete']=False
                else:body['recovery_authorization']['authorization_sha256']='0'*64
            self.mutate_journal(data,change)
            with self.subTest(kind=kind),self.assertRaises(ValueError):api.issue_consume_capsule(data,probe.KEY)

    def test_same_normal_label_with_different_supplemental_dom_is_not_the_probe_result(self):
        from race_ai import all_existing_model_official_continuation as api
        from race_ai import all_existing_model_official_results as result_reader
        data,_=self.fixture();item=data['checkpoint_archives'][0]
        payload=open_forecasts(result_reader._cipher(item['raw']),key=probe.KEY)
        dom=payload['captures'][0]['metadata']['auto_result_context']['rendered_dom_capture']
        raw=base64.b64decode(dom['raw_base64'])+b' ';dom['raw_base64']=base64.b64encode(raw).decode()
        dom['metadata'].update(byte_count=len(raw),source_sha256=sha256(raw).hexdigest())
        item['raw']=zipped(seal_forecasts(payload,run_id='77',round_no=900005,key=probe.KEY),'results.enc')
        item['metadata'].update(digest='sha256:'+sha256(item['raw']).hexdigest(),size_in_bytes=len(item['raw']))
        data['request']['manifest']['checkpoint_artifacts'][0]['digest']=item['metadata']['digest']
        with self.assertRaisesRegex(ValueError,'ACTUAL_NORMAL_PROBE_TEACHER_JOIN'):api.issue_consume_capsule(data,probe.KEY)

    def test_later_authenticated_pending_revision_does_not_reuse_earlier_normal_probe(self):
        from race_ai import all_existing_model_official_continuation as api
        from race_ai import all_existing_model_official_results as result_reader
        from race_ai.autorace_official_result_adapter import parse_result
        from race_ai.manual_official_capture import official_rights_ref
        from tests import test_autorace_official_result_adapter as sources
        data,_=self.fixture();payload=open_forecasts(result_reader._cipher(data['checkpoint_archives'][0]['raw']),key=probe.KEY)
        capture=payload['captures'][0];wire=json.loads(base64.b64decode(capture['raw_base64']));wire['body']['raceResult']=[]
        raw=json.dumps(wire,separators=(',',':')).encode();capture['raw_base64']=base64.b64encode(raw).decode()
        actual=capture['metadata'];actual.update(byte_count=len(raw),source_sha256=sha256(raw).hexdigest())
        for key in ('fetched_at','response_received_at'):actual[key]=(datetime.fromisoformat(actual[key])+timedelta(seconds=1)).isoformat()
        generated=datetime.fromisoformat(payload['generated_at'])+timedelta(seconds=1)
        label=parse_result(raw,actual,frozen_native_payload=sources.fixture()['frozen'],now=generated,
            source_rights_ref=official_rights_ref('autorace'),allow_order_only=True)
        self.assertEqual(label['status'],'pending')
        payload.update(observations=[label],run_id=78,code_sha='b'*40,generated_at=generated.isoformat())
        encoded=zipped(seal_forecasts(payload,run_id='78',round_no=900005,key=probe.KEY),'results.enc')
        meta=metadata(encoded,90003,'all-existing-official-results-78-900005',78,'b'*40,generated+timedelta(seconds=2))
        data['checkpoint_archives'].append(dict(raw=encoded,metadata=meta));data['request']['manifest']['checkpoint_artifacts'].append(pin(meta))
        with self.assertRaisesRegex(ValueError,'ACTUAL_NORMAL_PROBE_TEACHER_JOIN'):api.issue_consume_capsule(data,probe.KEY)

    def test_explicit_native_reader_key_cannot_fall_back_to_a_different_environment_key(self):
        from race_ai import all_existing_model_official_continuation as api
        data,_=self.fixture();wrong=base64.b64encode(bytes(reversed(range(32)))).decode()
        with patch.dict(os.environ,RACE_AI_STATE_KEY=wrong):
            api.issue_consume_capsule(data,probe.KEY)
            self.assertEqual(os.environ['RACE_AI_STATE_KEY'],wrong)
            with self.assertRaises(ValueError):api.issue_consume_capsule(data,bytes(reversed(range(32))))

    def test_runtime_wrapper_reauthenticates_actual_shaped_transport_and_preserves_old_unknown(self):
        from race_ai import all_existing_model_official_continuation as api
        from scripts import all_existing_model_official_result_recovery as wrapper
        from scripts import all_existing_model_official_result_collect as collector
        data,now=self.fixture();raw=api.issue_consume_capsule(data,probe.KEY)
        current=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        archives={i['metadata']['id']:i for group in ('native_archives','journal_archives','checkpoint_archives') for i in data[group]}
        def get(route):
            if route=='actions/runs/88/attempts/1':return data['first_attempt']
            if route=='actions/runs/77/attempts/1':return data['probe_first_attempt']
            if route=='actions/runs/77':return data['prior_runs'][0]
            if route=='actions/runs/'+str(probe.fixture()[0]['old_run']['id']):return data['old_run']
            raise AssertionError(route)
        def capsule(request,env,**kwargs):return data['probe_capsule_raw'] if request is None else raw
        def source_read(route):return archives[int(route.split('/')[2])]['raw']
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);repo=root/'repo';repo.mkdir(mode=0o700)
            for relative,body in PLAN_BYTES.items():
                path=repo/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body);path.chmod(0o600)
            env=dict(run_id=88,head_sha=data['target']['head_sha'],temp=root)
            with patch.object(wrapper,'_capsule',side_effect=capsule),patch.object(wrapper,'_api',side_effect=get), \
                patch.object(collector.future,'metadata',side_effect=lambda ident:deepcopy(archives[ident]['metadata'])), \
                patch.object(collector.future,'gh',side_effect=source_read),patch.object(collector,'ROOT',repo), \
                patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(probe.KEY).decode()):
                auth=wrapper._admit(data['request'],env,current,now,probe.KEY)
                prior=collector.prior_journals(data['request']['manifest'],now=now,key=probe.KEY,recovery_authorization=auth)
                self.assertEqual(prior['prior_journal_artifact_count'],2)
                result=collector.collect(root/'continued',env,data['request']['manifest'],clock=lambda:now,
                    opener=lambda *_:self.fail('unexpected provider GET'),browser=lambda *_:self.fail('unexpected provider browser'),
                    recovery_authorization=auth)
            self.assertFalse(result['ready']);self.assertEqual(result['source_requests'],0)
            self.assertEqual(result['confirmed_case_count'],1)
            journal=open_forecasts((root/'continued.collection.enc').read_bytes(),key=probe.KEY)
            audit=journal['recovery_authorization'];self.assertIsNone(audit['old_source_requests_actual'])
            self.assertEqual(audit['old_source_requests_upper_bound'],32);self.assertEqual(audit['maximum_new_requests'],32)

    def test_new_authority_needs_new_attempt_two_and_cannot_extend_clock_or_source_expiry(self):
        from race_ai import all_existing_model_official_continuation as api
        data,now=self.fixture();raw=api.issue_consume_capsule(data,probe.KEY)
        actual=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        for kind in ('attempt','head','completed','expires','prior_rerun','native_expired'):
            supplied=deepcopy(data);current=deepcopy(actual);at=now
            if kind=='attempt':current['run_attempt']=3
            elif kind=='head':current['head_sha']='0'*40
            elif kind=='completed':current.update(status='completed',conclusion='success')
            elif kind=='expires':at=datetime.fromisoformat(data['expires_at'])
            elif kind=='prior_rerun':supplied['prior_runs'][0]['run_attempt']=3
            else:supplied['native_archives'][0]['metadata']['expired']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                api.validate_capsule(raw,data=supplied,current_run=current,now=at,key=probe.KEY)
        with self.assertRaises(ValueError):api.validate_capsule(data['probe_capsule_raw'],data=data,current_run=actual,now=now,key=probe.KEY)

if __name__=='__main__':unittest.main()
