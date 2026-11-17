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
from pathlib import Path

OWNER_SHA='eff296f6d54ad4be297d93e32f1ee0d4592ad9e3'
M2_OWNER_SHA='86b029ae5bddd5d4956497d8b32b2c92b8eec521'
PROFILE_OWNER_SHA='f55351dce855177a51330f72c37d6238ba2c9e3e'
RETENTION_OWNER_SHA='bb49215034b779ea1493b35dd91e5c3ebfc04032'
PARTIAL_RECEIPT_OWNER_SHAS=(M2_OWNER_SHA,PROFILE_OWNER_SHA,RETENTION_OWNER_SHA)
BRANCH='production/boat-p0-p1-20261111'
JOB='Existing frozen P0, exhibition P1, separate official results and PDCA'
SCHEMA='RACE_AI_ACTIVE_OWNER_RECEIPT_SNAPSHOT_V1'


def need(ok,reason):
    if not ok:raise ValueError('OWNER_ACTIVE_AUDIT_'+reason)


def failure_diagnostic(error):
    """Static public call-site only; never exception text, values, URLs or locals."""
    public=frozenset(('boat_owner_active_snapshot_audit.py','boat_exact_all_model_zip_readback.py',
                      'boat_owner_evidence_audit.py'))
    functions=frozenset(('audit_active_snapshot','audit','_official_cutoffs','_scan','_scan_unqualified_originals',
        '_owner_head','validate_active_scope','_canonical_p0','_jobs','read','moment','cutoff_source_disagreement',
        '_verified_reused_baseline','_final_control','_expected_source','_model_archive_scope'))
    output={};trace=error.__traceback__;folder=Path(__file__).resolve().parent
    while trace is not None:
        code=trace.tb_frame.f_code;path=Path(code.co_filename).resolve()
        if path.parent==folder and path.name in public and code.co_name in functions:
            output=dict(failure_at='scripts/'+path.name+':'+str(trace.tb_lineno),failure_function=code.co_name)
        trace=trace.tb_next
    return output


def _time(value):
    from scripts.boat_exact_all_model_zip_readback import moment
    return moment(value)


def _expected_source(value):
    need(type(value) is str and value in (OWNER_SHA,*PARTIAL_RECEIPT_OWNER_SHAS),'SOURCE_NOT_PINNED')
    return value


def select_audit_target(event_name,event,*,main_target=None):
    """Choose read-only evidence scope; never select or authorize a dispatcher."""
    need(type(event) is dict and type(event.get('repository')) is dict and
         event['repository'].get('full_name')=='haji84/RACE-AI','TARGET_REPOSITORY')
    if event_name=='workflow_run':
        run=event.get('workflow_run');need(type(run) is dict,'TARGET_EVENT')
        source=_expected_source(run.get('head_sha'));ident=run.get('id')
        need(run.get('head_branch')==BRANCH and run.get('event')=='workflow_dispatch' and
             type(run.get('head_repository')) is dict and run['head_repository'].get('full_name')=='haji84/RACE-AI' and
             run.get('status')=='completed' and run.get('conclusion') in ('success','failure'),'TARGET_EVENT')
    else:
        need(event_name=='push' and event.get('ref')=='refs/heads/main','TARGET_EVENT')
        if main_target is None:ident,source=44019591352,OWNER_SHA
        else:
            need(type(main_target) is dict and set(main_target)=={'schema','run_id','source_commit'} and
                 main_target.get('schema')=='RACE_AI_M2_READONLY_AUDIT_TARGET_V1' and
                 main_target.get('source_commit')==M2_OWNER_SHA,'TARGET_CONFIG')
            ident,source=main_target['run_id'],M2_OWNER_SHA
    need(type(ident) is int and 0<ident<10**20,'TARGET_RUN_ID')
    return dict(run_id=ident,expected_owner_sha=source,allow_completed_receipts=source in PARTIAL_RECEIPT_OWNER_SHAS)


def _final_control(get,run,listing,now):
    """Authenticate the final AES session and its exact public companion."""
    from race_ai import boat_all_model_recovery as R,boat_source_control as source
    from race_ai import boat_private_original_archive as archive
    from race_ai.boat_pending_round_recovery import read_final_control
    packets=[]
    for prefix,limit in (('race-cycle-continuity',source.MAX_CONTINUITY_ZIP),
                         ('race-source-control',source.MAX_SUMMARY_ZIP)):
        matches=[item for item in listing if item.get('name')==f'{prefix}-{run["id"]}']
        need(len(matches)==1,'FINAL_CONTROL_MISSING_OR_DUPLICATE');item=matches[0]
        meta_raw=get(f'actions/artifacts/{item["id"]}');meta=json.loads(meta_raw)
        R._metadata(meta_raw,item,run,now,get)
        need(_time(run['created_at'])<=_time(meta['created_at'])<=_time(run['updated_at']),
             'FINAL_CONTROL_CLOCK')
        raw=get(f'actions/artifacts/{item["id"]}/zip')
        need(type(raw) is bytes and 0<len(raw)<=limit,'FINAL_CONTROL_BOUND')
        packets.append((raw,meta))
    control=read_final_control(get,run)
    (continuity,meta),(public,public_meta)=packets
    with archive._checked_zip(continuity,max_zip_bytes=source.MAX_CONTINUITY_ZIP) as z:
        need(z.namelist()==[archive.CIPHER_MEMBER],'FINAL_CONTROL_AES_REQUIRED')
        derived=source.build_summary(z.read(archive.CIPHER_MEMBER),run_id=run['id'],head_sha=run['head_sha'])
    with archive._checked_zip(public,max_zip_bytes=source.MAX_SUMMARY_ZIP,max_expanded=source.MAX_SUMMARY) as z:
        need(z.namelist()==[source.MEMBER] and source._json(z.read(source.MEMBER))==derived,
             'FINAL_CONTROL_AES_PUBLIC_DISAGREE')
    need(control==source.read_summary(public,public_meta,continuity,meta,
         run_id=run['id'],head_sha=run['head_sha']),'FINAL_CONTROL_CHANGED')
    need(type(control.get('completed_round')) is int and 1<=control['completed_round']<=24,
         'NO_COMPLETED_ROUND')
    return control


def _jobs(get,run,now,*,expected_owner_sha=OWNER_SHA,completed_round_limit=None):
    expected_owner_sha=_expected_source(expected_owner_sha)
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
    need(type(job.get('id')) is int and job['id']>0 and job.get('run_id')==run['id'] and job.get('head_sha')==expected_owner_sha and
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
        if completed_round_limit is not None and number>completed_round_limit:continue
        if step.get('status')=='completed' and step.get('conclusion')=='success':
            need(number==len(selected)+1 and _time(run['created_at'])<=_time(step['started_at'])<=
                 _time(step['completed_at'])<=now,'ROUND_COMPLETION_CLOCK_OR_GAP')
            selected.append(number)
    need(selected,'NO_COMPLETED_ROUND')
    if completed_round_limit is not None:
        need(job.get('status')=='completed' and job.get('conclusion') in ('success','failure'),'FINAL_OWNER_JOB_STATUS')
        need(selected==list(range(1,completed_round_limit+1)),'FINAL_COMPLETED_ROUND_PREFIX_MISSING')
    return job,selected


def _model_archive_scope(listing,run_id,rounds,now):
    """Names attest presence only; absent conditional uploads stay unexplained.

    The producer can continue after generation/upload failure, so neither a
    missing archive nor a successful native step attests zero model issuance.
    """
    from race_ai import boat_all_model_recovery as R
    listed={};ids=set()
    for item in listing:
        record=R._listed(item,run_id,now)
        if str(item.get('name','')).startswith(f'boat-all-model-forecasts-{run_id}-'):
            need(record is not None,'MODEL_ARCHIVE_NAME_UNSUPPORTED')
        if record is None:continue
        ident,number=record
        need(number not in listed and ident not in ids,'MODEL_ARCHIVE_DUPLICATE')
        listed[number]=ident;ids.add(ident)
    eligible={0,*rounds}
    return dict(present_rounds=sorted(set(listed)&eligible),
                missing_rounds=[number for number in rounds if number not in listed],
                excluded_rounds=sorted(set(listed)-eligible))


def validate_active_scope(scope,run,listing,now,get,*,expected_owner_sha=OWNER_SHA,allow_completed_receipts=False):
    """Bind the opt-in exact-ZIP path to the same actual job and inventory."""
    from race_ai.actions_contract import digest
    expected_owner_sha=_expected_source(expected_owner_sha)
    need(type(allow_completed_receipts) is bool and (not allow_completed_receipts or expected_owner_sha in PARTIAL_RECEIPT_OWNER_SHAS),
         'COMPLETED_SCOPE_NOT_PINNED')
    need(type(scope) is dict and scope.get('schema')==SCHEMA and scope.get('run')==run
         and scope.get('inventory')==listing and scope.get('captured_at')==now.isoformat(),
         'SNAPSHOT_CHANGED')
    need(scope.get('expected_owner_sha',OWNER_SHA)==expected_owner_sha and
         scope.get('allow_completed_receipts',False)==allow_completed_receipts,'SNAPSHOT_CHANGED')
    active=run.get('status')=='in_progress' and run.get('conclusion') is None
    completed=allow_completed_receipts and run.get('status')=='completed' and run.get('conclusion') in ('success','failure')
    need(run.get('head_sha')==expected_owner_sha and (active or completed) and type(run.get('run_attempt')) is int and
         run['run_attempt']==1 and run.get('head_branch')==BRANCH and
         run.get('event')=='workflow_dispatch','ACTIVE_OWNER_IDENTITY')
    control=_final_control(get,run,listing,now) if completed else None
    need(scope.get('final_control')==control,'SNAPSHOT_CHANGED')
    job,rounds=_jobs(get,run,now,expected_owner_sha=expected_owner_sha,
                      completed_round_limit=control['completed_round'] if control else None)
    need(scope.get('job')==job and scope.get('rounds')==rounds and
         scope.get('inventory_sha256')==digest(listing),'SNAPSHOT_CHANGED')
    if expected_owner_sha in PARTIAL_RECEIPT_OWNER_SHAS:
        derived=_model_archive_scope(listing,run['id'],rounds,now)
        declared=scope.get('all_model_archive_scope')
        need(type(declared) is dict and digest(declared)==digest(derived),'MODEL_ARCHIVE_SCOPE_CHANGED')
        return derived['present_rounds']
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


def _canonical_p0(get,run,listing,now,*,expected_owner_sha=OWNER_SHA):
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
         origin.get('event')=='workflow_dispatch' and (_source_pinned(origin['id'],origin['head_sha']) or
             expected_owner_sha in PARTIAL_RECEIPT_OWNER_SHAS and origin['head_sha']==expected_owner_sha or
             expected_owner_sha==PROFILE_OWNER_SHA and origin['head_sha']==M2_OWNER_SHA or
             expected_owner_sha==RETENTION_OWNER_SHA and origin['head_sha'] in (M2_OWNER_SHA,PROFILE_OWNER_SHA)),
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


def audit_active_snapshot(repo,run_id,*,now,get,expected_owner_sha=OWNER_SHA,allow_completed_receipts=False):
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
    expected_owner_sha=_expected_source(expected_owner_sha)
    need(type(allow_completed_receipts) is bool and (not allow_completed_receipts or expected_owner_sha in PARTIAL_RECEIPT_OWNER_SHAS),
         'COMPLETED_SCOPE_NOT_PINNED')
    reads=_Reads(get);run=R._run(reads(f'actions/runs/{run_id}'),run_id,now)
    need(run.get('head_sha')==expected_owner_sha,'ACTIVE_OWNER_IDENTITY')
    listing=artifact_pages(reads,run_id)
    control=_final_control(reads,run,listing,now) if allow_completed_receipts and run.get('status')=='completed' else None
    job,rounds=_jobs(reads,run,now,expected_owner_sha=expected_owner_sha,
                    completed_round_limit=control['completed_round'] if control else None)
    scope=dict(schema=SCHEMA,run=run,job=job,rounds=rounds,inventory=listing,
               inventory_sha256=digest(listing),captured_at=now.isoformat(),
               expected_owner_sha=expected_owner_sha,allow_completed_receipts=allow_completed_receipts,final_control=control)
    if expected_owner_sha in PARTIAL_RECEIPT_OWNER_SHAS:
        scope['all_model_archive_scope']=_model_archive_scope(listing,run_id,rounds,now)
    validate_active_scope(scope,run,listing,now,reads,expected_owner_sha=expected_owner_sha,
                          allow_completed_receipts=allow_completed_receipts)
    day=_time(run['created_at']).astimezone(exact.JST).date().isoformat()
    first,origin=_canonical_p0(reads,run,listing,now,expected_owner_sha=expected_owner_sha);scope['p0_original']=(first,origin)
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
             and report.get('code_sha')==expected_owner_sha and report.get('day_jst')==day,'RESULT_SCOPE_OR_HASH')
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
            need(doc.get('code_sha')==expected_owner_sha and _time(step['started_at'])<=_time(meta['created_at'])
                 <=_time(step['completed_at']),'P0_SUPPLEMENT_SCOPE')
            supplements+=1
    if control:
        need(control.get('day_jst')==day and control['previous_session_requests']>=previous['requests_used'] and
             control['lifetime_requests']==previous['lifetime_requests_base']+control['previous_session_requests'] and
             control['lifetime_completed_rounds']==previous['lifetime_completed_rounds_base']+len(rounds) and
             control.get('day_start_lifetime_requests')==previous['day_start_lifetime_requests'] and
             all(_time(rm['created_at'])<=_time(control[field]['created_at'])<=_time(run['updated_at'])
                 for field in ('receipt','source_control_receipt')),'FINAL_COUNTERS_OR_RECEIPT_CHANGED')
    view=_saved_view(repo,now,day)
    models=[m['model_id'] for m in active_catalog() if 'boat' in m['applicable_sports']]
    proof=exact.audit(get=reads,repo=repo,run_id=run_id,day=day,expected_models=models,
                     original_view=view,now=now,active_scope=scope,expected_owner_sha=expected_owner_sha,
                     allow_completed_receipts=allow_completed_receipts)
    excluded=[int(match[1]) for step in job['steps']
              if (match:=re.fullmatch(r'Deadline-ordered five-model round ([0-9]{2})',str(step.get('name')))) and
                 int(match[1]) not in rounds and step.get('status')=='completed' and step.get('conclusion')=='success']
    return dict(schema=SCHEMA,status=('HOLD_ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED' if proof['missing_all_model_rounds'] else
                'COMPLETED_OWNER_RECEIPTS_AES_VERIFIED_PARTIAL_SCOPE' if control else
                'ACTIVE_COMPLETED_RECEIPTS_AES_VERIFIED_PARTIAL_SCOPE'),
        owner_run_id=run_id,owner_source_commit=expected_owner_sha,owner_status_at_snapshot=run['status'],
        captured_at=now.isoformat(),inventory_sha256=scope['inventory_sha256'],
        completed_rounds_audited=rounds,round_evidence=evidence,
        p0_origin_run_id=origin['id'],p0_artifact_id=p0_meta['id'],
        p0_supplements_verified=supplements,
        raw_aes_archives_verified=1+supplements+2*len(rounds)+proof['aes_originals_independently_decrypted']+
                                 proof['additional_native_p1_archives_verified']+int(control is not None),
        final_control=control,final_control_aes_authenticated=control is not None,
        successful_round_steps_excluded=excluded,
        official_cutoff_qualification=proof['official_cutoff_qualification'],
        cutoff_qualification_blocker=proof['cutoff_qualification_blocker'],
        missing_all_model_rounds=proof['missing_all_model_rounds'],
        all_model_zip_readback=proof,full_day_coverage=False,successor_dispatch_allowed=False,
        latest_live_counters_audited=False,official_source_requests=0,new_forecasts=0,
        original_forecasts_changed=False)
