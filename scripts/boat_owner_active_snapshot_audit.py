"""Independent, count-only AES audit of a frozen active owner's saved rounds.

This is never final control, a recovery proof, or permission to start a worker.
Only existing GitHub receipts are read; original bytes and counters stay intact.
"""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from hashlib import sha1
import base64
import json
import re

OWNER_SHA='eff296f6d54ad4be297d93e32f1ee0d4592ad9e3'
BRANCH='production/boat-p0-p1-20261111'
JOB='Existing frozen P0, exhibition P1, separate official results and PDCA'
SCHEMA='RACE_AI_ACTIVE_OWNER_RECEIPT_SNAPSHOT_V1'


def need(ok,reason):
    if not ok:raise ValueError('OWNER_ACTIVE_AUDIT_'+reason)


def _time(value):
    from scripts.boat_exact_all_model_zip_readback import moment
    return moment(value)


def _jobs(get,run,now):
    rows=[];total=None
    for page in range(1,12):
        suffix='' if page==1 else f'&page={page}'
        value=json.loads(get(f'actions/runs/{run["id"]}/jobs?per_page=100'+suffix))
        count=value.get('total_count');part=value.get('jobs')
        need(type(count) is int and 0<count<=1024 and type(part) is list and len(part)<=100
             and (total is None or total==count),'JOBS_INCOMPLETE_OR_CHANGED')
        total=count;rows.extend(part)
        if len(rows)>=total:break
        need(len(part)==100,'JOBS_INCOMPLETE_OR_CHANGED')
    need(len(rows)==total and len({r['id'] for r in rows})==len(rows),'JOBS_INCOMPLETE_OR_CHANGED')
    matches=[r for r in rows if r.get('name')==JOB]
    need(len(matches)==1,'OWNER_JOB_MISSING_OR_DUPLICATE');job=matches[0]
    need(type(job.get('id')) is int and job['id']>0 and job.get('run_id')==run['id'] and job.get('head_sha')==OWNER_SHA and
         type(job.get('run_attempt')) is int and job['run_attempt']==1,'OWNER_JOB_IDENTITY')
    steps=job.get('steps');need(type(steps) is list,'OWNER_STEPS_MISSING')
    rounds={}
    for step in steps:
        match=re.fullmatch(r'Deadline-ordered five-model round ([0-9]{2})',str(step.get('name')))
        if not match:continue
        number=int(match[1]);need(1<=number<=24 and number not in rounds,'ROUND_STEP_DUPLICATE')
        rounds[number]=step
    selected=[]
    for number,step in sorted(rounds.items()):
        if step.get('status')=='completed' and step.get('conclusion')=='success':
            need(number==len(selected)+1 and _time(run['created_at'])<=_time(step['started_at'])<=
                 _time(step['completed_at'])<=now,'ROUND_COMPLETION_CLOCK_OR_GAP')
            selected.append(number)
    need(selected,'NO_COMPLETED_ROUND')
    return job,selected


def validate_active_scope(scope,run,listing,now,get):
    """Bind the opt-in exact-ZIP path to the same actual job and inventory."""
    from race_ai.actions_contract import digest
    need(type(scope) is dict and scope.get('schema')==SCHEMA and scope.get('run')==run
         and scope.get('inventory')==listing and scope.get('captured_at')==now.isoformat(),
         'SNAPSHOT_CHANGED')
    need(run.get('head_sha')==OWNER_SHA and run.get('status')=='in_progress' and
         run.get('conclusion') is None and type(run.get('run_attempt')) is int and
         run['run_attempt']==1 and run.get('head_branch')==BRANCH and
         run.get('event')=='workflow_dispatch','ACTIVE_OWNER_IDENTITY')
    job,rounds=_jobs(get,run,now)
    need(scope.get('job')==job and scope.get('rounds')==rounds and
         scope.get('inventory_sha256')==digest(listing),'SNAPSHOT_CHANGED')
    initial=any(row.get('name')==f'boat-all-model-forecasts-{run["id"]}-r0' for row in listing)
    return ([0] if initial else [])+rounds


class _Reads:
    """Freeze actual API responses without changing or synthesizing metadata."""
    def __init__(self,get):self.get=get;self.cache={}
    def __call__(self,path):
        need(type(path) is str and (re.fullmatch(r'actions/(?:runs/[1-9][0-9]*(?:/(?:artifacts|jobs)\?per_page=100(?:&page=[1-9][0-9]*)?)?|artifacts/[1-9][0-9]*(?:/zip)?)',path)
             or path=='git/ref/heads/feat/four-sport-forecast-audit-view-20261022'
             or re.fullmatch(r'contents/docs/evidence/20[0-9]{2}-[0-9]{2}-[0-9]{2}/p0-first-receipt.json\?ref=[a-f0-9]{40}',path)),
             'READ_ENDPOINT_REJECTED')
        if path not in self.cache:
            raw=self.get(path);need(type(raw) is bytes,'RESPONSE_BYTES_REQUIRED');self.cache[path]=raw
        return self.cache[path]


def _canonical_p0(get,run,listing,now):
    from race_ai import boat_all_model_recovery as R
    from race_ai.cycle_recovery import artifact_pages
    from scripts.boat_owner_evidence_audit import _source_pinned
    found=[x for x in listing if x.get('name')==f'boat-p0-existing-{run["id"]}']
    if found:
        need(len(found)==1,'P0_DUPLICATE');return found[0],run
    # Resolve the immutable registry file directly. Never relabel an active run
    # as completed merely to enter the ordinary completed-owner resolver.
    reference=json.loads(get('git/ref/heads/feat/four-sport-forecast-audit-view-20261022'))
    commit=reference.get('object',{}).get('sha')
    need(type(commit) is str and re.fullmatch('[a-f0-9]{40}',commit),'P0_REGISTRY_REF')
    day=_time(run['created_at']).astimezone(timezone(timedelta(hours=9))).date().isoformat()
    path=f'docs/evidence/{day}/p0-first-receipt.json'
    value=json.loads(get(f'contents/{path}?ref={commit}'))
    need(value.get('type')=='file' and value.get('path')==path and value.get('encoding')=='base64'
         and type(value.get('content')) is str,'P0_REGISTRY_FILE')
    raw=base64.b64decode(value['content'].replace('\n',''),validate=True)
    need(0<len(raw)<=16384 and value.get('size')==len(raw) and value.get('sha')==
         sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest(),'P0_REGISTRY_HASH')
    receipt=json.loads(raw)
    need(receipt.get('schema')=='RACE_AI_P0_FIRST_RECEIPT_V1' and receipt.get('day_jst')==day
         and receipt.get('no_regeneration') is True and type(receipt.get('run_id')) is int and
         receipt['run_id']>0 and receipt['run_id']!=run['id'],'P0_REGISTRY_IDENTITY')
    origin=R._run(get(f'actions/runs/{receipt["run_id"]}'),receipt['run_id'],now)
    need(origin.get('status')=='completed' and type(origin.get('run_attempt')) is int and
         origin['run_attempt']==1 and origin.get('head_branch')==BRANCH and
         origin.get('event')=='workflow_dispatch' and _source_pinned(origin['id'],origin['head_sha']),
         'P0_ORIGIN_IDENTITY')
    originals=artifact_pages(get,origin['id'])
    matches=[x for x in originals if x.get('id')==receipt.get('artifact_id') and
             x.get('name')==f'boat-p0-existing-{origin["id"]}']
    need(len(matches)==1,'P0_ORIGINAL_MISSING_OR_DUPLICATE');meta=matches[0]
    need(meta.get('digest')=='sha256:'+str(receipt.get('zip_sha256')) and
         meta.get('created_at')==receipt.get('server_created_at') and
         _time(origin['created_at'])<=_time(meta['created_at'])<=_time(run['created_at']),
         'P0_REGISTRY_RECEIPT_CHANGED')
    return meta,origin


def _saved_view(repo,now,day):
    from race_ai.racer_result_bridge import SavedResultBridge
    from race_ai import saved_view_feed as F
    bridge=SavedResultBridge(repo,now=now)
    return F.current_view(bridge.git,bridge.bootstrap,day=day)[3]


def audit_active_snapshot(repo,run_id,*,now,get):
    from race_ai import boat_all_model_recovery as R
    from race_ai.cycle_recovery import artifact_pages,result_archive
    from race_ai.boat_private_original_archive import open_original_zip
    from race_ai.boat_private_original_vault import _artifact
    from race_ai.boat_source_control import _metadata
    from race_ai.frozen_day_cycle import read_p0,read_p1
    from race_ai.repeated_cycle import artifact_name
    from race_ai.actions_contract import digest
    from race_ai.existing_model_coverage import active_catalog
    from scripts import boat_exact_all_model_zip_readback as exact
    need(isinstance(now,datetime) and now.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
    reads=_Reads(get);run=R._run(reads(f'actions/runs/{run_id}'),run_id,now)
    job,rounds=_jobs(reads,run,now);listing=artifact_pages(reads,run_id)
    scope=dict(schema=SCHEMA,run=run,job=job,rounds=rounds,inventory=listing,
               inventory_sha256=digest(listing),captured_at=now.isoformat())
    validate_active_scope(scope,run,listing,now,reads)
    day=_time(run['created_at']).astimezone(exact.JST).date().isoformat()
    first,origin=_canonical_p0(reads,run,listing,now);scope['p0_original']=(first,origin)
    def read(item,kind,owner=run):
        meta_raw=reads(f'actions/artifacts/{item["id"]}');meta=json.loads(meta_raw)
        R._metadata(meta_raw,item,owner,now,reads)
        need(_time(owner['created_at'])<=_time(meta['created_at'])<=now,'ORIGINAL_CLOCK')
        raw=reads(f'actions/artifacts/{item["id"]}/zip')
        _metadata(raw,meta,name=item['name'],run_id=owner['id'],head_sha=owner['head_sha'])
        _artifact(raw,meta_raw,key=None,now=now,expected_kind=kind)
        return raw,meta
    p0_raw,p0_meta=read(first,'P0',origin)
    document,_=read_p0(p0_raw,p0_meta,expected_day=day)
    need(document.get('code_sha')==origin['head_sha'],'P0_CODE_HEAD')
    evidence=[];previous=None;supplements=0
    for number in rounds:
        packets=[]
        for prefix,kind in (('boat-national-cutoff','P1'),('race-existing-cycle','RESULT')):
            name=artifact_name(prefix,run_id,number)
            matches=[x for x in listing if x.get('name')==name]
            need(len(matches)==1,'ROUND_ORIGINAL_MISSING_OR_DUPLICATE')
            packets.append(read(matches[0],kind))
        (p1,pm),(result,rm)=packets
        step=next(s for s in job['steps'] if s.get('name')==f'Deadline-ordered five-model round {number:02}')
        need(_time(step['started_at'])<=_time(pm['created_at'])<=_time(rm['created_at'])<=_time(step['completed_at']),
             'ROUND_RECEIPT_COMPLETION_CLOCK')
        _,rows=read_p1(p1,pm)
        need(all(r['race_id'].startswith(day.replace('-','')+'-') for r in rows),'P1_DAY')
        result_archive(result,rm,day)
        with open_original_zip(result,rm,expected_kind='RESULT',max_plain_zip_bytes=32*1024*1024) as z:
            need(z.getinfo('status.json').file_size<=16*1024*1024,'RESULT_REPORT_BOUND')
            report=json.loads(z.read('status.json'))
            need(z.read('current-p1-original.zip')==p1,'NESTED_P1_CHANGED')
        need(report.get('report_sha256')==digest({k:v for k,v in report.items() if k!='report_sha256'})
             and report.get('round_no')==number and str(report.get('run_id'))==str(run_id)
             and report.get('code_sha')==OWNER_SHA and report.get('day_jst')==day,'RESULT_SCOPE_OR_HASH')
        need(_time(pm['created_at'])<=_time(report['updated_at'])<=_time(rm['created_at']),
             'RESULT_REPORT_CLOCK')
        references=[r for r in report.get('first_forecast_artifacts',[]) if r.get('id')==pm['id']]
        need(len(references)==1 and all(references[0].get(k)==pm.get(k) for k in
             ('id','name','digest','created_at','workflow_run')),'RESULT_P1_RECEIPT_CHANGED')
        state=report.get('bounded_repeat_session');need(type(state) is dict,'RESULT_COUNTERS')
        fields=('run_id','requests_used','completed_round','prepared_round','lifetime_requests_base',
                'lifetime_requests','lifetime_completed_rounds_base','lifetime_completed_rounds','day_start_lifetime_requests')
        need(all(type(state.get(k)) is int and state[k]>=0 for k in fields) and
             state['run_id']==run_id and state.get('day_jst')==day and state['completed_round']==number-1
             and state['prepared_round']==number and state['lifetime_requests_base']+state['requests_used']==state['lifetime_requests']
             and state['lifetime_completed_rounds_base']+state['completed_round']==state['lifetime_completed_rounds']
             and state['day_start_lifetime_requests']<=state['lifetime_requests']
             and state.get('source_wait') is None and state.get('halted_reason') is None,'RESULT_COUNTERS')
        if previous:
            need(all(state[k]==previous[k] for k in ('lifetime_requests_base','lifetime_completed_rounds_base','day_start_lifetime_requests'))
                 and state['requests_used']>=previous['requests_used'],'COUNTERS_DECREASED')
        previous=state
        safe={k:state[k] for k in fields};safe.update(day_jst=day,source_wait=None,halted_reason=None)
        evidence.append(dict(round=number,p1_artifact_id=pm['id'],result_artifact_id=rm['id'],
                             sealed_precompletion_counters=safe))
        additions=[x for x in listing if x.get('name')==artifact_name('boat-p0-existing',run_id,number)]
        need(len(additions)<=1,'P0_SUPPLEMENT_DUPLICATE')
        if additions:
            supplement,meta=read(additions[0],'P0')
            doc,_=read_p0(supplement,meta,expected_day=day)
            need(doc.get('code_sha')==OWNER_SHA and _time(step['started_at'])<=_time(meta['created_at'])
                 <=_time(step['completed_at']),'P0_SUPPLEMENT_SCOPE')
            supplements+=1
    view=_saved_view(repo,now,day)
    models=[m['model_id'] for m in active_catalog() if 'boat' in m['applicable_sports']]
    proof=exact.audit(get=reads,repo=repo,run_id=run_id,day=day,expected_models=models,
                     original_view=view,now=now,active_scope=scope)
    return dict(schema=SCHEMA,status='ACTIVE_COMPLETED_RECEIPTS_AES_VERIFIED_PARTIAL_SCOPE',
        owner_run_id=run_id,owner_source_commit=OWNER_SHA,owner_status_at_snapshot=run['status'],
        captured_at=now.isoformat(),inventory_sha256=scope['inventory_sha256'],
        completed_rounds_audited=rounds,round_evidence=evidence,
        p0_origin_run_id=origin['id'],p0_artifact_id=p0_meta['id'],
        p0_supplements_verified=supplements,
        raw_aes_archives_verified=1+supplements+2*len(rounds)+proof['aes_originals_independently_decrypted'],
        all_model_zip_readback=proof,full_day_coverage=False,successor_dispatch_allowed=False,
        latest_live_counters_audited=False,official_source_requests=0,new_forecasts=0,
        original_forecasts_changed=False)
