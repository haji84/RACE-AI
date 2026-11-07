"""Actions-only reader of one consumed fixed-attempt recovery capsule.

No issuance or Git write exists here. Attempt one deliberately produces HOLD;
the owner publishes a create-only consumed capsule only after that whole attempt
succeeds. Only the same run's attempt two can dispatch the bounded normal UI.
"""
import argparse
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha1,sha256
import json
import os
from pathlib import Path
import re
import subprocess

from race_ai import all_existing_model_official_recovery as recovery
from race_ai.actions_contract import digest
from race_ai.boat_all_model_store import MAX_WIRE
from race_ai.boat_pdca_github_handoff import TRANSFER_REF
from race_ai.boat_pdca_state import state_key
from race_ai.boat_private_original_vault import _json as bounded_json
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts import all_existing_model_official_result_collect as collector
from scripts.boat_all_racers import _read,_write

REQUEST_PATH='audit/state/official-result-recovery-request.json'
PREFLIGHT_SCHEMA='RACE_AI_FIXED_RECOVERY_VERIFICATION_PREFLIGHT_V1'
FULL_CHECK_STEPS=('Python synthetic journal to viewer projection tests',
    'Verify isolated experimental video decoding and measurements')

def _api(path):
    recovery.need(type(path) is str and re.fullmatch(r'(?:actions/runs/[1-9][0-9]*(?:/attempts/[1-9][0-9]*(?:/jobs\?per_page=100)?)?|'
        r'git/ref/heads/state/boat-pdca-transfer|git/(?:commits|trees|blobs)/[a-f0-9]{40})',path),'GITHUB_ROUTE')
    response=subprocess.run(['gh','api','repos/haji84/RACE-AI/'+path],capture_output=True,timeout=50,check=False)
    recovery.need(response.returncode==0 and 0<len(response.stdout)<=52*1024*1024,'GITHUB_READ')
    return bounded_json(response.stdout,52*1024*1024)

def _capsule(request,env,*,fetch=None,request_sha256=None):
    """Read only a computed path at one immutable existing-ref commit."""
    fetch=fetch or _api;ref=fetch('git/ref/heads/'+TRANSFER_REF)
    recovery.need(type(ref) is dict and ref.get('ref')=='refs/heads/'+TRANSFER_REF and
        type(ref.get('object')) is dict and ref['object'].get('type')=='commit','EXISTING_TRANSFER_REF')
    commit=ref['object'].get('sha');recovery.need(type(commit) is str and re.fullmatch('[a-f0-9]{40}',commit),'TRANSFER_COMMIT')
    value=fetch('git/commits/'+commit);tree=value.get('tree',{}).get('sha')
    if request_sha256 is None:relative=recovery.capsule_path(request,env['head_sha'],env['run_id'])
    else:
        recovery.need(type(request_sha256) is str and re.fullmatch('[a-f0-9]{64}',request_sha256) and
            type(env['head_sha']) is str and re.fullmatch('[a-f0-9]{40}',env['head_sha']) and
            type(env['run_id']) is int and env['run_id']>0,'ORIGINAL_CAPSULE_PATH')
        relative='recovery/official-results/'+request_sha256+'/'+env['head_sha']+'/'+str(env['run_id'])+'/2.enc'
    parts=relative.split('/')
    for index,part in enumerate(parts):
        recovery.need(type(tree) is str and re.fullmatch('[a-f0-9]{40}',tree),'TRANSFER_TREE')
        listing=fetch('git/trees/'+tree)
        recovery.need(type(listing) is dict and listing.get('truncated') is False and
            type(listing.get('tree')) is list and len(listing['tree'])<=32768,'TRANSFER_TREE_BOUND')
        found=[item for item in listing['tree'] if type(item) is dict and item.get('path')==part]
        if not found:return None
        recovery.need(len(found)==1,'CAPSULE_PATH_CONFLICT');entry=found[0]
        if index<len(parts)-1:
            recovery.need(entry.get('type')=='tree' and entry.get('mode')=='040000','CAPSULE_PATH_TREE');tree=entry.get('sha')
        else:
            ident=entry.get('sha');recovery.need(entry.get('type')=='blob' and entry.get('mode')=='100644' and
                type(ident) is str and re.fullmatch('[a-f0-9]{40}',ident) and type(entry.get('size')) is int and
                0<entry['size']<=MAX_WIRE,'CAPSULE_BLOB_BOUND')
            blob=fetch('git/blobs/'+ident)
            recovery.need(type(blob) is dict and blob.get('sha')==ident and blob.get('encoding')=='base64' and
                blob.get('size')==entry['size'] and type(blob.get('content')) is str,'CAPSULE_BLOB')
            encoded=blob['content'].replace('\n','');raw=base64.b64decode(encoded,validate=True)
            recovery.need(len(raw)==entry['size'] and base64.b64encode(raw).decode()==encoded and
                sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==ident,'CAPSULE_IMMUTABLE_BYTES')
            return raw

def _trusted_environment():
    # No local-key fallback: inspect trusted Actions scope before key lookup.
    recovery.need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')=='haji84/RACE-AI' and
        os.environ.get('GITHUB_REPOSITORY_ID')=='1416489937' and os.environ.get('GITHUB_EVENT_NAME')=='pull_request',
        'ACTIONS_ONLY')
    event=read_json_bytes(_read(Path(os.environ.get('GITHUB_EVENT_PATH','')),1024*1024))
    recovery.need(event.get('number')==71 and event.get('pull_request',{}).get('head',{}).get('repo',{}).get('full_name')=='haji84/RACE-AI',
        'PULL_REQUEST_EVENT')
    env=collector.future.environment();current=_api('actions/runs/'+str(env['run_id']))
    recovery.need(recovery.run_receipt(current)['run_attempt']==2 and
        current['head_sha']==env['head_sha'],'ACTUAL_ATTEMPT_TWO')
    return env,current

def _admit(request,env,current,now,key):
    raw=_capsule(request,env)
    if raw is None:return None
    first=_api('actions/runs/'+str(env['run_id'])+'/attempts/1')
    old=_api('actions/runs/'+str(recovery.OLD_RUN))
    prior_ids=sorted({pin['run_id'] for pin in request['manifest']['prior_journal_artifacts']}-{recovery.OLD_RUN})
    prior_runs=[_api('actions/runs/'+str(ident)) for ident in prior_ids]
    if request.get('schema')=='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V4':
        return _admit_probe16(raw,request,env,current,first,old,prior_runs,now,key)
    if recovery.is_continuation_request(request):
        return _admit_continuation(raw,request,env,current,first,old,prior_runs,now,key)
    auth=recovery.validate_capsule(raw,request=request,current_run=current,first_attempt=first,old_run=old,prior_runs=prior_runs,now=now,key=key)
    manifest=request['manifest'];pin=next(p for p in manifest['prior_journal_artifacts'] if p['id']==recovery.OLD_ARTIFACT)
    body,cipher,actual=collector._journal_artifact(pin,now=now,key=key)
    auth.validate_prior(manifest,pin,body,cipher,actual,now)
    old_plan=collector.load_plan(body['manifest'],key=key,now=recovery.clock(body['epoch_started_at']))
    plan=collector.load_plan(manifest,key=key,now=now)
    recovery.need(old_plan==auth._body['old_plan'] and plan==auth._body['new_plan'],'AUTHENTICATED_PLAN_BYTES')
    auth.validate_collector(manifest,plan,env,now)
    return auth

def _admit_probe16(raw,request,env,current,first,old,prior_runs,now,key):
    from race_ai import all_existing_model_official_probe16 as sixteen
    from race_ai import all_existing_model_official_continuation as continuation
    archives=[];total=len(raw);manifest=request['manifest']
    for pin in manifest['prior_journal_artifacts']:
        actual=collector.future.metadata(pin['id']);size=actual.get('size_in_bytes')
        recovery.need(type(size) is int and 0<size<=collector.results.MAX_ARCHIVE_BYTES and
            total+size<=256*1024*1024 and actual.get('id')==pin['id'] and actual.get('digest')==pin['digest'] and
            actual.get('expired') is False and recovery.clock(actual['created_at'])<=now<recovery.clock(actual['expires_at']),
            'SIXTEEN_PRIOR_METADATA')
        encoded=collector.future.gh('actions/artifacts/'+str(pin['id'])+'/zip');total+=len(encoded)
        continuation._pin_metadata(encoded,actual,pin,now);archives.append(dict(raw=encoded,metadata=actual))
    fixed=next(item for item in archives if item['metadata']['id']==recovery.OLD_ARTIFACT)
    pin=next(p for p in manifest['prior_journal_artifacts'] if p['id']==recovery.OLD_ARTIFACT)
    old_body,_=recovery._evidence(fixed['raw'],fixed['metadata'],pin,now,key)
    old_plan=collector.load_plan(old_body['manifest'],key=key,now=recovery.clock(old_body['epoch_started_at']))
    plan=collector.load_plan(manifest,key=key,now=now);stored=collector.open_forecasts(raw,key=key)['body']
    data=dict(request=request,target=stored['target'],issued_at=stored['issued_at'],not_before=stored['not_before'],
        expires_at=stored['expires_at'],old_run=old,prior_runs=prior_runs,first_attempt=first,
        old_plan=old_plan,new_plan=plan,old_journal_raw=fixed['raw'],old_journal_metadata=fixed['metadata'],
        prior_journal_archives=archives)
    auth=sixteen.validate_capsule(raw,data=data,current_run=current,now=now,key=key)
    auth.validate_collector(manifest,plan,env,now);return auth

def _admit_continuation(raw,request,env,current,first,old,prior_runs,now,key):
    from race_ai import all_existing_model_official_continuation as continuation
    manifest=request['manifest'];probe_pin=next(p for p in manifest['prior_journal_artifacts'] if p['id']==request['probe_journal_artifact_id'])
    original=_capsule(None,dict(head_sha=probe_pin['head_sha'],run_id=probe_pin['run_id']),request_sha256=request['probe_request_sha256'])
    recovery.need(original is not None,'ORIGINAL_PROBE_CAPSULE_REQUIRED')
    groups={};total=len(raw)+len(original)
    for field in ('prior_journal_artifacts','native_artifacts','checkpoint_artifacts'):
        items=[]
        for pin in manifest[field]:
            actual=collector.future.metadata(pin['id']);size=actual.get('size_in_bytes')
            recovery.need(type(size) is int and 0<size<=collector.results.MAX_ARCHIVE_BYTES and
                total+size<=256*1024*1024 and actual.get('id')==pin['id'] and actual.get('digest')==pin['digest'] and
                actual.get('expired') is False and recovery.clock(actual['created_at'])<=now<recovery.clock(actual['expires_at']),
                'CONTINUATION_SOURCE_METADATA')
            body=collector.future.gh('actions/artifacts/'+str(pin['id'])+'/zip');total+=len(body)
            continuation._pin_metadata(body,actual,pin,now);items.append(dict(raw=body,metadata=actual))
        groups[field]=items
    stored=collector.open_forecasts(raw,key=key)['body']
    old_body,_=recovery._evidence(next(item['raw'] for item in groups['prior_journal_artifacts'] if item['metadata']['id']==recovery.OLD_ARTIFACT),
        next(item['metadata'] for item in groups['prior_journal_artifacts'] if item['metadata']['id']==recovery.OLD_ARTIFACT),
        next(p for p in manifest['prior_journal_artifacts'] if p['id']==recovery.OLD_ARTIFACT),now,key)
    old_plan=collector.load_plan(old_body['manifest'],key=key,now=recovery.clock(old_body['epoch_started_at']))
    new_plan=collector.load_plan(manifest,key=key,now=now)
    data=dict(request=request,target=stored['target'],issued_at=stored['issued_at'],not_before=stored['not_before'],
        expires_at=stored['expires_at'],old_run=old,prior_runs=prior_runs,first_attempt=first,
        probe_first_attempt=_api('actions/runs/'+str(probe_pin['run_id'])+'/attempts/1'),old_plan=old_plan,new_plan=new_plan,
        journal_archives=groups['prior_journal_artifacts'],native_archives=groups['native_artifacts'],
        checkpoint_archives=groups['checkpoint_artifacts'],probe_capsule_raw=original)
    auth=continuation.validate_capsule(raw,data=data,current_run=current,now=now,key=key)
    auth.validate_collector(manifest,new_plan,env,now);return auth

def _full_first_attempt(first,document,env):
    """Witness both expensive checks, not merely a successful workflow label."""
    receipt=recovery.run_receipt(first)
    recovery.need(receipt['id']==env['run_id'] and receipt['head_sha']==env['head_sha'] and
        receipt['run_attempt']==1 and receipt['status']=='completed' and receipt['conclusion']=='success',
        'FULL_FIRST_ATTEMPT_REQUIRED')
    recovery.need(type(document) is dict and type(document.get('total_count')) is int and
        type(document.get('jobs')) is list and 1<=document['total_count']==len(document['jobs'])<=100,
        'FIRST_JOBS_COMPLETE')
    jobs=document['jobs'];seen=set()
    for job in jobs:
        recovery.need(type(job) is dict and type(job.get('id')) is int and job['id']>0 and job['id'] not in seen and
            job.get('run_id')==env['run_id'] and type(job.get('run_attempt')) is int and job['run_attempt']==1 and
            job.get('head_sha')==env['head_sha'],'FIRST_JOB_BINDING')
        seen.add(job['id'])
    viewers=[job for job in jobs if job.get('name')=='Viewer audit contract']
    recovery.need(len(viewers)==1 and viewers[0].get('status')=='completed' and
        viewers[0].get('conclusion')=='success','FULL_VIEWER_JOB_REQUIRED')
    job=viewers[0];steps=job.get('steps');checked=[]
    recovery.need(type(steps) is list and 2<=len(steps)<=128,'FULL_FIRST_STEPS_REQUIRED')
    for name in FULL_CHECK_STEPS:
        matches=[step for step in steps if type(step) is dict and step.get('name')==name]
        recovery.need(len(matches)==1 and matches[0].get('status')=='completed' and
            matches[0].get('conclusion')=='success' and type(matches[0].get('number')) is int,
            'FULL_FIRST_STEPS_REQUIRED')
        step=matches[0]
        recovery.need(recovery.clock(step['started_at'])<=recovery.clock(step['completed_at'])<=
            recovery.clock(receipt['updated_at'])+timedelta(seconds=1),'FIRST_STEP_CLOCK')
        checked.append({key:step[key] for key in ('name','number','status','conclusion','started_at','completed_at')})
    proof=dict(schema='RACE_AI_SAME_HEAD_PRIOR_FULL_VERIFICATION_V1',first_attempt=receipt,
        first_jobs_sha256=digest(document),viewer_job_id=job['id'],verified_steps=checked)
    return dict(verified_first_attempt=1,verified_first_run_id=env['run_id'],verified_first_head_sha=env['head_sha'],
        prior_full_jobs_sha256=digest(document),prior_full_verification_sha256=digest(proof))


def preflight(input_path):
    """Read existing authority only; no marker, issuance or source dispatch."""
    status=dict(schema=PREFLIGHT_SCHEMA,state='FULL_VERIFICATION_REQUIRED',ready=False,
        reuse_prior_verification=False,source_requests=0,full_verification_executed_in_this_attempt=False,
        plaintext_published=False,production_promoted=False,actual_purchases=False)
    try:
        recovery.need(os.environ.get('GITHUB_RUN_ATTEMPT')=='2','FIXED_ATTEMPT_TWO_ONLY')
        env,current=_trusted_environment();now=collector.utc_now();key=state_key('production')
        request=recovery.validate_request(read_json_bytes(_read(Path(input_path),32768)),now)
        auth=_admit(request,env,current,now,key);recovery.need(auth is not None,'CONSUMED_CAPSULE_ABSENT')
        first=_api('actions/runs/'+str(env['run_id'])+'/attempts/1')
        recovery.need(recovery.run_receipt(first)==auth._body['first_attempt'],'FIRST_ATTEMPT_AUTHORIZATION_BINDING')
        document=_api('actions/runs/'+str(env['run_id'])+'/attempts/1/jobs?per_page=100')
        proof=_full_first_attempt(first,document,env)
        # GitHub/source-plan reads may take time. Re-sample physical time;
        # the later provider step still performs its own fresh admission.
        plan=collector.load_plan(request['manifest'],key=key,now=collector.utc_now())
        fresh=collector.utc_now()
        auth.validate_collector(request['manifest'],plan,env,fresh)
        audit=auth.audit();remaining=(recovery.clock(audit['expires_at'])-fresh).total_seconds()
        recovery.need(remaining>=180,'PREFLIGHT_REMAINING_WINDOW')
        status.update(proof,state='PRIOR_SAME_HEAD_FULL_VERIFICATION_REUSED',reuse_prior_verification=True,
            recovery_authorization_sha256=audit['authorization_sha256'],recovery_request_sha256=audit['request_sha256'],
            remaining_authorization_seconds=int(remaining),reused_verification_steps=list(FULL_CHECK_STEPS))
    except Exception as exc:
        status.update(**collector.future.safe_diagnostic(exc))
    return status


def _preflight_main(input_path):
    status=preflight(input_path)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('reuse_prior_verification='+str(status['reuse_prior_verification']).lower()+'\n')
            if status['reuse_prior_verification']:
                output.write('prior_full_verification_sha256='+status['prior_full_verification_sha256']+'\n')
    print(json.dumps(status,sort_keys=True));return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',default=REQUEST_PATH)
    parser.add_argument('--out-dir',required=True);parser.add_argument('--readback-artifact',type=int)
    parser.add_argument('--readback-journal-artifact',type=int);parser.add_argument('--preflight',action='store_true')
    args=parser.parse_args(argv)
    if args.preflight:return _preflight_main(args.input)
    status=dict(schema=collector.STATUS,state='HOLD_FIXED_RECOVERY_NOT_ISSUED',ready=False,source_requests=0,
        plaintext_published=False,production_promoted=False,actual_purchases=False)
    root=None;manifest=None;authorized=False
    try:
        # Attempt one can pass complete CI without any owner key or source access.
        recovery.need(os.environ.get('GITHUB_RUN_ATTEMPT')=='2','FIXED_ATTEMPT_TWO_ONLY')
        env,current=_trusted_environment();now=collector.utc_now();key=state_key('production')
        request=recovery.validate_request(read_json_bytes(_read(Path(args.input),32768)),now)
        auth=_admit(request,env,current,now,key)
        recovery.need(auth is not None,'CONSUMED_CAPSULE_ABSENT')
        root=collector.future.output_path(args.out_dir,env);manifest=request['manifest'];authorized=True
        status.update(workflow_run_id=env['run_id'],expected_head_sha=env['head_sha'],
            artifact_name=f'all-existing-official-results-{env["run_id"]}-{collector.ROUND}',
            journal_artifact_name='official-result-collection-journal-'+str(env['run_id']),
            recovery_authorization_sha256=auth.audit()['authorization_sha256'],recovery_request_sha256=auth.audit()['request_sha256'],
            old_source_requests_actual=None,old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN',
            maximum_new_requests=auth.audit()['maximum_new_requests'])
        if args.readback_artifact is None and args.readback_journal_artifact is None:
            # A second call within this fixed runner cannot dispatch again.
            marker=env['temp']/('official-recovery-consumed-'+auth.audit()['request_sha256']+'-'+env['head_sha']+'-'+str(env['run_id'])+'-2.json')
            _write(marker,collector.future.wire(auth.audit()))
            status.update(collector.collect(root,env,manifest,recovery_authorization=auth))
        elif args.readback_artifact is not None:
            status.update(collector.readback(args.readback_artifact,root,env,manifest))
        else:
            old_status=root.with_name(root.name+'.status.json')
            recovery.need(old_status.exists(),'LOCAL_RECOVERY_STATUS_REQUIRED')
            status.update(read_json_bytes(_read(old_status,128*1024)))
        if args.readback_journal_artifact is not None:
            status.update(collector.readback_journal(args.readback_journal_artifact,root,env,manifest))
        if args.readback_artifact is not None or args.readback_journal_artifact is not None:
            local=collector.open_forecasts(_read(root.with_name(root.name+'.collection.enc'),MAX_WIRE),key=key)
            recovery.need(local.get('recovery_authorization')==auth.audit(),'LOCAL_RECOVERY_JOURNAL_BINDING')
    except Exception as exc:
        status.update(state='HOLD_FIXED_OFFICIAL_RESULT_RECOVERY',ready=False,**collector.future.safe_diagnostic(exc))
        if authorized and root is not None and manifest is not None:
            path=root.with_name(root.name+'.collection.enc')
            if path.exists():
                try:status.update(collector._status(collector.open_forecasts(_read(path,MAX_WIRE),key=state_key('production')),manifest,
                    state='HOLD_FIXED_OFFICIAL_RESULT_RECOVERY'))
                except Exception:status['source_requests']=None
    if authorized and root is not None:
        try:
            if args.readback_artifact is None and args.readback_journal_artifact is None and status['ready']:
                _write(root.with_name(root.name+'.generation.json'),collector.future.wire(status))
            path=root.with_name(root.name+'.status.json');collector.save(path,collector.future.wire(status),replace=path.exists())
        except Exception as exc:status.update(state='HOLD_FIXED_OFFICIAL_RESULT_RECOVERY',ready=False,**collector.future.safe_diagnostic(exc))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('ready='+str(status['ready']).lower()+'\n')
            if authorized:
                output.write('requested=true\n')
                for field in ('artifact_name','journal_artifact_name'):output.write(field+'='+status[field]+'\n')
    print(json.dumps(status,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
