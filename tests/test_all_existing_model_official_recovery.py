"""Fictional fixed-run recovery: no real key, provider, Git or Actions writes."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import importlib
import io
import base64
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from race_ai.actions_contract import digest
from race_ai.boat_all_model_store import seal_forecasts

KEY=bytes(range(32));HEAD='a'*40;OLD_HEAD='9b4bc37648fbfad421daa80bd2300cda5e97e9df'
NOW=datetime(2026,11,7,11,tzinfo=timezone.utc)

def fixture():
    def pin(n):return dict(id=n,digest='sha256:'+'d'*64,run_id=100+n,head_sha='c'*40)
    case=dict(sport='autorace',race_id='autorace:2026-11-07:isesaki:1',route=dict(kind='NORMAL_UI',ui_entry_url='https://autorace.jp/race_info/Live/isesaki',ui_venue_name=None))
    old_manifest=dict(schema='RACE_AI_OFFICIAL_RESULT_COLLECT_INPUT_V2',execution_day='2026-11-07',plan_path='audit/state/official-result-collection-plan-'+('f'*64)+'.enc',plan_sha256='f'*64,native_artifacts=[pin(n) for n in range(1,5)],checkpoint_artifacts=[pin(7),pin(8)],prior_journal_artifacts=[],allow_order_only=True)
    old_plan=dict(schema='RACE_AI_OFFICIAL_RESULT_COLLECTION_PLAN_V1',execution_day='2026-11-07',cases=[case],terms_manifest=dict(terms=[]),maximum_requests=32,result_wait_seconds=120)
    started=(NOW-timedelta(hours=2)).isoformat();finished=(NOW-timedelta(hours=2)+timedelta(seconds=8)).isoformat()
    body=dict(schema='RACE_AI_OFFICIAL_RESULT_COLLECTION_JOURNAL_V2',execution_day='2026-11-07',manifest_sha256=digest(old_manifest),maximum_requests=32,epoch_started_at=started,
        attempts=[dict(url='https://www.jra.go.jp/',started_at=started,finished_at=finished,state='SUCCESS',http_status=200) for _ in range(8)],captures=[],cases=[dict(sport=case['sport'],race_id=case['race_id'],state='HOLD_BROWSER_SOURCE_UNVERIFIED')],manifest=old_manifest,workflow_run_id=42349536138,code_sha=OLD_HEAD,collection_plan_sha256='f'*64,
        browser_attempt=dict(state='RESERVED',reserved_request_limit=24,started_at=finished))
    cipher=seal_forecasts(body,run_id='42349536138',round_no=900006,key=KEY);out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as zipped:zipped.writestr('collection.enc',cipher)
    raw=out.getvalue();old_pin=dict(id=13565712487,digest='sha256:'+sha256(raw).hexdigest(),run_id=42349536138,head_sha=OLD_HEAD)
    meta=dict(id=old_pin['id'],name='official-result-collection-journal-42349536138',expired=False,digest=old_pin['digest'],size_in_bytes=len(raw),created_at=finished,expires_at=(NOW+timedelta(days=2)).isoformat(),workflow_run=dict(id=42349536138,head_sha=OLD_HEAD,repository_id=1416489937,head_repository_id=1416489937))
    manifest=deepcopy(old_manifest);manifest.update(plan_sha256='e'*64,plan_path='audit/state/official-result-collection-plan-'+('e'*64)+'.enc',prior_journal_artifacts=[old_pin]);manifest['checkpoint_artifacts'].append(pin(9))
    plan=dict(deepcopy(old_plan),maximum_requests=8)
    request=dict(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V1',repository_id=1416489937,pull_request=71,mode='FIXED_ATTEMPT_TWO_SINGLE_NORMAL_UI_PROBE',probe_sport='autorace',old_journal_artifact_id=13565712487,manifest=manifest)
    def run(ident,head,attempt,updated):return dict(id=ident,head_sha=head,run_attempt=attempt,status='completed',conclusion='success',updated_at=updated,run_started_at=started,repository=dict(id=1416489937,full_name='haji84/RACE-AI'),head_repository=dict(id=1416489937,full_name='haji84/RACE-AI'),pull_requests=[dict(number=71)])
    oldrun=run(42349536138,OLD_HEAD,1,finished);first=run(77,HEAD,1,(NOW-timedelta(minutes=1)).isoformat())
    data=dict(request=request,target=dict(head_sha=HEAD,run_id=77,run_attempt=2),issued_at=NOW.isoformat(),not_before=NOW.isoformat(),expires_at=(NOW+timedelta(minutes=30)).isoformat(),old_journal_raw=raw,old_journal_metadata=meta,old_run=oldrun,first_attempt=first,old_plan=old_plan,new_plan=plan)
    return data,body,cipher

class FixedRecoveryTests(unittest.TestCase):
    def module(self):return importlib.import_module('race_ai.all_existing_model_official_recovery')
    def test_real_fixture_codec_and_fixed_attempt_two_validation_preserve_unknown(self):
        api=self.module();data,body,cipher=fixture();before=deepcopy(data)
        raw=api.issue_consume_capsule(data,KEY)
        current=deepcopy(data['first_attempt']);current.update(run_attempt=2,status='in_progress',conclusion=None)
        auth=api.validate_capsule(raw,request=data['request'],current_run=current,first_attempt=data['first_attempt'],old_run=data['old_run'],now=NOW,key=KEY)
        self.assertEqual(auth.audit()['old_source_requests_actual'],None);self.assertEqual(auth.audit()['old_source_requests_upper_bound'],32)
        self.assertEqual(auth.audit()['maximum_new_requests'],8);self.assertEqual(data,before)
        auth.validate_prior(data['request']['manifest'],data['request']['manifest']['prior_journal_artifacts'][0],body,cipher,data['old_journal_metadata'],NOW)
    def test_missing_success_wrong_run_attempt_head_expiry_or_request_cannot_authorize(self):
        api=self.module();data,_,_=fixture();raw=api.issue_consume_capsule(data,KEY)
        for change in ('attempt','run','head','first_failed','expired','request'):
            current=deepcopy(data['first_attempt']);current.update(run_attempt=2,status='in_progress',conclusion=None)
            first=deepcopy(data['first_attempt']);request=deepcopy(data['request']);now=NOW
            if change=='attempt':current['run_attempt']=3
            elif change=='run':current['id']=78
            elif change=='head':current['head_sha']='b'*40
            elif change=='first_failed':first['conclusion']='failure'
            elif change=='expired':now+=timedelta(hours=1)
            else:request['probe_sport']='keirin'
            with self.subTest(change=change),self.assertRaises(ValueError):api.validate_capsule(raw,request=request,current_run=current,first_attempt=first,old_run=data['old_run'],now=now,key=KEY)
    def test_review_never_overrides_denial_or_changes_native_terms_route_and_budget(self):
        api=self.module()
        for change in ('deny','route','terms','native','checkpoint_drop','budget','case','recent','old_active'):
            data,body,_=fixture()
            if change=='deny':body['browser_process_diagnostic']=dict(stdout_stopped_host=True)
            elif change=='route':data['new_plan']['cases'][0]['route']['ui_entry_url']+='x'
            elif change=='terms':data['new_plan']['terms_manifest']['changed']=True
            elif change=='native':data['request']['manifest']['native_artifacts'].pop()
            elif change=='checkpoint_drop':data['request']['manifest']['checkpoint_artifacts'].pop(0)
            elif change=='budget':data['new_plan']['maximum_requests']=16
            elif change=='case':data['new_plan']['cases']*=2
            elif change=='recent':data['old_run']['updated_at']=(NOW-timedelta(minutes=20)).isoformat()
            else:data['old_run']['status']='in_progress'
            if change=='deny':
                cipher=seal_forecasts(body,run_id='42349536138',round_no=900006,key=KEY);out=io.BytesIO()
                with zipfile.ZipFile(out,'w') as zipped:zipped.writestr('collection.enc',cipher)
                raw=out.getvalue();data['old_journal_raw']=raw;data['old_journal_metadata'].update(digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw));data['request']['manifest']['prior_journal_artifacts'][0]['digest']=data['old_journal_metadata']['digest']
            with self.subTest(change=change),self.assertRaises(ValueError):api.issue_consume_capsule(data,KEY)

    def test_actual_source_cache_can_only_narrow_to_exact_original_sport_entries(self):
        api=self.module();data,_,_=fixture()
        cache=[dict(metadata=dict(source_url='https://autorace.jp/cache.js'),raw_base64='YQ=='),
               dict(metadata=dict(source_url='https://keirin.jp/cache.js'),raw_base64='Yg==')]
        data['old_plan']['static_cache']=deepcopy(cache);data['new_plan']['static_cache']=cache[:1]
        api.issue_consume_capsule(data,KEY)
        data['new_plan']['static_cache'][0]['raw_base64']='Yw=='
        with self.assertRaises(ValueError):api.issue_consume_capsule(data,KEY)

    def test_default_guard_stays_strict_but_capability_admits_only_fixed_original(self):
        from scripts import all_existing_model_official_result_collect as c
        api=self.module();data,body,cipher=fixture();raw=api.issue_consume_capsule(data,KEY)
        current=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        auth=api.validate_capsule(raw,request=data['request'],current_run=current,first_attempt=data['first_attempt'],
            old_run=data['old_run'],now=NOW,key=KEY)
        with patch.object(c,'_journal_artifact',return_value=(body,cipher,data['old_journal_metadata'])):
            with self.assertRaisesRegex(ValueError,'UNCERTAIN_REQUIRES_OWNER_REVIEW'):
                c.prior_journals(data['request']['manifest'],now=NOW,key=KEY)
            result=c.prior_journals(data['request']['manifest'],now=NOW,key=KEY,recovery_authorization=auth)
            self.assertEqual(result['prior_journal_artifact_count'],1)
            denied=deepcopy(body);denied['browser_process_diagnostic']=dict(stdout_stopped_host=True)
            with patch.object(c,'_journal_artifact',return_value=(denied,cipher,data['old_journal_metadata'])):
                with self.assertRaisesRegex(ValueError,'KNOWN_DENIAL_NON_OVERRIDABLE'):
                    c.prior_journals(data['request']['manifest'],now=NOW,key=KEY,recovery_authorization=auth)
        with self.assertRaises(ValueError):auth.validate_prior(data['request']['manifest'],data['request']['manifest']['prior_journal_artifacts'][0],dict(body,maximum_requests=31),cipher,data['old_journal_metadata'],NOW)

    def test_attempt_one_and_local_wrapper_need_no_key_fetch_provider_or_artifact_names(self):
        from scripts import all_existing_model_official_result_recovery as wrapper
        for attempt in ('1','3'):
            output=io.StringIO()
            with patch.dict(os.environ,{'GITHUB_RUN_ATTEMPT':attempt},clear=True),patch.object(wrapper,'_api',side_effect=AssertionError('unexpected GH')), \
                patch.object(wrapper,'state_key',side_effect=AssertionError('unexpected owner key')),redirect_stdout(output):
                self.assertEqual(wrapper.main(['--out-dir','/nonexistent/private']),0)
            status=json.loads(output.getvalue());self.assertFalse(status['ready']);self.assertEqual(status['source_requests'],0)
            self.assertNotIn('artifact_name',status);self.assertNotIn('journal_artifact_name',status)
        with patch.dict(os.environ,{'GITHUB_RUN_ATTEMPT':'2'},clear=True),patch.object(wrapper,'state_key',side_effect=AssertionError('unexpected owner key')):
            with self.assertRaisesRegex(ValueError,'ACTIONS_ONLY'):wrapper._trusted_environment()

    def test_immutable_existing_ref_blob_and_missing_path_are_read_only(self):
        from scripts import all_existing_model_official_result_recovery as wrapper
        from hashlib import sha1
        data,_,_=fixture();raw=self.module().issue_consume_capsule(data,KEY)
        env=dict(head_sha=HEAD,run_id=77);parts=self.module().capsule_path(data['request'],HEAD,77).split('/')
        blob=sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest();calls=[]
        trees={format(i+1,'040x'):i for i in range(len(parts))}
        def fetch(route):
            calls.append(route)
            if route.startswith('git/ref/'):return dict(ref='refs/heads/state/boat-pdca-transfer',object=dict(type='commit',sha='f'*40))
            if route.startswith('git/commits/'):return dict(tree=dict(sha=format(1,'040x')))
            if route.startswith('git/trees/'):
                index=trees[route.rsplit('/',1)[1]];last=index==len(parts)-1
                return dict(truncated=False,tree=[dict(path=parts[index],type='blob' if last else 'tree',mode='100644' if last else '040000',
                    sha=blob if last else format(index+2,'040x'),**(dict(size=len(raw)) if last else {}))])
            if route.startswith('git/blobs/'):return dict(sha=blob,encoding='base64',size=len(raw),content=base64.b64encode(raw).decode())
            raise AssertionError(route)
        self.assertEqual(wrapper._capsule(data['request'],env,fetch=fetch),raw)
        self.assertTrue(all(path.startswith('git/') for path in calls))
        def absent(route):
            return dict(truncated=False,tree=[]) if route.startswith('git/trees/') else fetch(route)
        self.assertIsNone(wrapper._capsule(data['request'],env,fetch=absent))

    def test_one_fixed_attempt_cannot_consume_again_with_another_output_directory(self):
        from scripts import all_existing_model_official_result_recovery as wrapper
        data,_,_=fixture();api=self.module();raw=api.issue_consume_capsule(data,KEY)
        current=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        auth=api.validate_capsule(raw,request=data['request'],current_run=current,first_attempt=data['first_attempt'],old_run=data['old_run'],now=NOW,key=KEY)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);request=root/'request.json';request.write_text(json.dumps(data['request']))
            env=dict(run_id=77,head_sha=HEAD,temp=root);calls=[]
            def collect(output,env,manifest,*,recovery_authorization):
                recovery_authorization.validate_collector(manifest,data['new_plan'],env,NOW);calls.append(output)
                return dict(ready=False,state='NO_NEW_AUTHENTICATED_RESULTS',source_requests=0)
            with patch.dict(os.environ,{'GITHUB_RUN_ATTEMPT':'2','RACE_AI_STATE_KEY':base64.b64encode(KEY).decode()}), \
                patch.object(wrapper,'_trusted_environment',return_value=(env,current)),patch.object(wrapper,'_admit',return_value=auth), \
                patch.object(wrapper.collector,'utc_now',return_value=NOW),patch.object(wrapper.collector,'collect',side_effect=collect):
                for name in ('first','different'):
                    output=io.StringIO()
                    with redirect_stdout(output):wrapper.main(['--input',str(request),'--out-dir',str(root/name)])
                    self.assertNotIn('artifact_metadata',output.getvalue())
            self.assertEqual(len(calls),1)

    def test_expiry_during_native_admission_holds_before_browser_dispatch(self):
        from scripts import all_existing_model_official_result_collect as c
        data,old_body,cipher=fixture();api=self.module();wire=api.issue_consume_capsule(data,KEY)
        current=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        auth=api.validate_capsule(wire,request=data['request'],current_run=current,first_attempt=data['first_attempt'],old_run=data['old_run'],now=NOW,key=KEY)
        case=data['new_plan']['cases'][0];native=dict(snapshot=dict(race=dict(sport='autorace',race_id=case['race_id'],
            event_date_jst='2026-11-07',sales_cutoff_at=(NOW-timedelta(hours=1)).isoformat(),venue='isesaki')))
        actual_clock=[NOW];calls=[]
        def admission(*args,**kwargs):actual_clock[0]=NOW+timedelta(minutes=31);return [native]
        with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode()), \
            patch.object(c,'load_plan',return_value=data['new_plan']),patch.object(c,'_journal_artifact',return_value=(old_body,cipher,data['old_journal_metadata'])), \
            patch.object(c.freeze,'frozen_inputs',side_effect=admission),patch.object(c.results,'_frozen',return_value=({('autorace',case['race_id']):native},'a'*64)), \
            patch.object(c,'checkpoints',return_value={}):
            with self.assertRaisesRegex(ValueError,'COLLECTOR_BINDING'):
                c.collect(Path(temporary)/'out',dict(run_id=77,head_sha=HEAD),data['request']['manifest'],clock=lambda:actual_clock[0],
                    opener=lambda *_:calls.append('GET'),browser=lambda *_:calls.append('BROWSER'),recovery_authorization=auth)
        self.assertEqual(calls,[])

    def test_all_other_prior_run_receipts_are_required_terminal_and_freshly_equal(self):
        data,_,_=fixture();api=self.module()
        pin=dict(id=13562617631,digest='sha256:'+'b'*64,run_id=42343017180,head_sha='c'*40)
        data['request']['manifest']['prior_journal_artifacts'].insert(0,pin)
        with self.assertRaisesRegex(ValueError,'ALL_PRIOR_RUNS_TERMINAL'):api.issue_consume_capsule(data,KEY)
        other=deepcopy(data['old_run']);other.update(id=pin['run_id'],head_sha=pin['head_sha'])
        data['prior_runs']=[other];raw=api.issue_consume_capsule(data,KEY)
        current=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        options=dict(request=data['request'],current_run=current,first_attempt=data['first_attempt'],old_run=data['old_run'],now=NOW,key=KEY)
        with self.assertRaisesRegex(ValueError,'ALL_PRIOR_RUNS_TERMINAL'):api.validate_capsule(raw,**options)
        api.validate_capsule(raw,**options,prior_runs=[other])
        for changed in (dict(other,status='in_progress'),dict(other,updated_at=NOW.isoformat()),dict(other,run_attempt=2)):
            with self.assertRaises(ValueError):api.validate_capsule(raw,**options,prior_runs=[changed])

if __name__=='__main__':unittest.main()
