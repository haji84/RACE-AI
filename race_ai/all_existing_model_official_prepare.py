"""Source-free KEIRIN plan preparation; no key lookup or transport mutation."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256

from .actions_contract import digest
from . import all_existing_model_official_issue as I
from . import all_existing_model_official_recovery as R
from . import all_existing_model_official_continuation as C
from . import all_existing_model_official_probe16 as S
from . import all_existing_model_official_historical as H
from . import manual_official_capture as policy
from .permissioned_source_delivery import read_json_bytes

SCHEMA='RACE_AI_OFFICIAL_RESULT_PLAN_PREPARE_REQUEST_V1'
SCHEMA_V2='RACE_AI_OFFICIAL_RESULT_PLAN_PREPARE_REQUEST_V2'
SCHEMA_V3='RACE_AI_OFFICIAL_RESULT_PLAN_PREPARE_REQUEST_V3'
COUNTS='RACE_AI_OFFICIAL_RESULT_PLAN_PREPARATION_COUNTS_V1'
COUNTS_V2='RACE_AI_OFFICIAL_RESULT_PLAN_PREPARATION_COUNTS_V2'
COUNTS_V3='RACE_AI_OFFICIAL_RESULT_PLAN_PREPARATION_COUNTS_V3'
PATH='audit/state/official-result-recovery-prepare-request.json'
PREFIX='official-results-prepare:'
SINGLE='KEIRIN_SINGLE_SIXTEEN_PROBE'
EIGHT='KEIRIN_FIRST_EIGHT_AFTER_VERIFIED_SIXTEEN'
ROUND=900033
FROZEN_COUNT_FIELDS=frozenset(('frozen_execution_head','source_issue_head','preparation_intent_head',
    'admitted_current_pr_head','protected_files_sha256','executed_workflow','frozen_code_execution',
    'current_pr_code_executed','reused_code_ancestor','parent_whole_first_verified','source_second_viewer_job_id'))
SOURCE_SECOND_STEPS=('Collect explicitly requested due official results using normal public navigation',
    'Verify the collected result artifact against the original frozen inputs',
    'Verify the actual encrypted collection journal even when results remain held')


def need(ok,reason):
    if not ok:raise ValueError('OFFICIAL_PREPARE_'+reason)


def validate_prepare_request(value):
    from scripts.all_existing_model_official_result_collect import _pins
    reused=type(value) is dict and value.get('schema') in (SCHEMA_V2,SCHEMA_V3)
    parent_key='verified_code_ancestor' if reused else 'verified_parent'
    fields={'schema','repository_id','workflow_id','pull_request',parent_key,'kind','target_event_day','previous_source'}
    need(type(value) is dict and set(value)==fields and value['schema'] in (SCHEMA,SCHEMA_V2,SCHEMA_V3) and
        type(value['repository_id']) is int and value['repository_id']==I.REPOSITORY_ID and
        type(value['workflow_id']) is int and value['workflow_id']==I.WORKFLOW and
        type(value['pull_request']) is int and value['pull_request']==71 and value['kind'] in (SINGLE,EIGHT),'REQUEST')
    parent=value[parent_key];source=value['previous_source']
    need(type(parent) is dict and set(parent)=={'head_sha','run_id','run_attempt','first_viewer_job_id'} and
        I._hex(parent['head_sha']) and I._id(parent['run_id']) and type(parent['run_attempt']) is int and
        parent['run_attempt']==1 and I._id(parent['first_viewer_job_id']),'VERIFIED_PARENT')
    fields={'head_sha','run_id','run_attempt','first_viewer_job_id','recovery_request_sha256',
        'recovery_request_blob_sha256','journal_artifact','result_artifact'}
    need(type(source) is dict and set(source)==fields and I._hex(source['head_sha']) and I._id(source['run_id']) and
        type(source['run_attempt']) is int and source['run_attempt']==2 and I._id(source['first_viewer_job_id']) and
        I._hex(source['recovery_request_sha256'],64) and I._hex(source['recovery_request_blob_sha256'],64),'PREVIOUS_SOURCE')
    _pins([source['journal_artifact'],source['result_artifact']])
    need(all(p['run_id']==source['run_id'] and p['head_sha']==source['head_sha'] for p in
        (source['journal_artifact'],source['result_artifact'])),'PREVIOUS_OUTPUT_PINS')
    if reused:need(all(parent[k]==source[k] for k in ('head_sha','run_id','first_viewer_job_id')),
                   'EXACT_SOURCE_CODE_ANCESTOR')
    from datetime import date
    need(type(value['target_event_day']) is str and date.fromisoformat(value['target_event_day']).isoformat()==
        value['target_event_day'],'TARGET_EVENT_DAY')
    return deepcopy(value)


def _full(value,current,first,jobs,now):
    from scripts.all_existing_model_official_result_recovery import _full_first_attempt
    active=I.run_scope(current);original=I.run_scope(first)
    need(original['id']==value['run_id'] and original['head_sha']==value['head_sha'] and
        original['run_attempt']==1 and original['status']=='completed' and original['conclusion']=='success' and
        active['id']==original['id'] and active['head_sha']==original['head_sha'] and active['status']=='completed' and
        active['conclusion']=='success' and R.clock(original['updated_at'])<=R.clock(active['updated_at'])<=now,'FULL_PARENT_OR_SOURCE')
    proof=_full_first_attempt(first,jobs,dict(run_id=value['run_id'],head_sha=value['head_sha']))
    viewer=next(job for job in jobs['jobs'] if job.get('name')=='Viewer audit contract')
    need(viewer['id']==value['first_viewer_job_id'],'EXACT_FULL_VIEWER')
    return active,original,proof


def _source_second_viewer(source,current,first,jobs,now):
    need(type(jobs) is dict and type(jobs.get('total_count')) is int and type(jobs.get('jobs')) is list and
        1<=jobs['total_count']==len(jobs['jobs'])<=100 and all(type(row) is dict for row in jobs['jobs']),
        'SOURCE_SECOND_JOBS_COMPLETE')
    found=[row for row in jobs['jobs'] if row.get('name')=='Viewer audit contract']
    need(len(found)==1,'SOURCE_SECOND_VIEWER');job=found[0];steps=job.get('steps')
    need(I._id(job.get('id')) and job['id']!=source['first_viewer_job_id'] and type(job.get('run_id')) is int and
        job['run_id']==source['run_id'] and type(job.get('run_attempt')) is int and job['run_attempt']==2 and
        job.get('head_sha')==source['head_sha'] and job.get('status')=='completed' and job.get('conclusion')=='success' and
        type(steps) is list and 1<=len(steps)<=1000 and all(type(row) is dict and type(row.get('name')) is str and
        0<len(row['name'])<=512 and type(row.get('number')) is int and row['number']>0 for row in steps) and
        len({row['number'] for row in steps})==len(steps),'SOURCE_SECOND_VIEWER')
    started=R.clock(job.get('started_at'));ended=R.clock(job.get('completed_at'))
    need(R.clock(first['updated_at'])<started<=ended<=R.clock(current['updated_at'])+timedelta(seconds=1) and
        ended<=now,'SOURCE_SECOND_VIEWER_CLOCK')
    for name in SOURCE_SECOND_STEPS:
        rows=[row for row in steps if row['name']==name]
        need(len(rows)==1 and rows[0].get('status')=='completed' and rows[0].get('conclusion')=='success',
            'SOURCE_SECOND_RESULT_READBACK')
        row=rows[0];need(started<=R.clock(row.get('started_at'))<=R.clock(row.get('completed_at'))<=ended,
            'SOURCE_SECOND_RESULT_READBACK_CLOCK')
    return dict(job_id=job['id'],run_id=source['run_id'],run_attempt=2,head_sha=source['head_sha'],
        started_at=job['started_at'],completed_at=job['completed_at'],steps_sha256=digest(steps))


def _frozen_snapshot(value,active,pr,snapshot,executed_workflow):
    """Bind facts produced by the verified frozen Git reader, never an intent JSON."""
    need(value.get('schema')==SCHEMA_V3 and type(snapshot) is dict,'FROZEN_CONTEXT')
    binding=snapshot.get('frozen_binding');current=snapshot.get('current_admission')
    need(type(binding) is dict and set(binding)=={'schema','kind','intent_head_sha','intent_parent_sha',
        'intent_blob_sha256','source_frozen_binding'} and binding['schema']=='RACE_AI_OFFICIAL_FROZEN_EXECUTION_BINDING_V1' and
        binding['kind']=='prepare' and type(current) is dict and set(current)=={'schema','current_head_sha','intent_head_sha',
        'latest_issue_head_sha','current_pr_head_sha','intent_is_ancestor','current_issue_head_sha',
        'issue_history_count','protected_files_sha256'} and
        current['schema']=='RACE_AI_OFFICIAL_FROZEN_CURRENT_ADMISSION_V1','FROZEN_BINDING_FIELDS')
    source_binding=binding['source_frozen_binding']
    need(type(source_binding) is dict and set(source_binding)=={'schema','tested_execution_head_sha','intent_head_sha',
        'intent_parent_sha','target','issue_request_blob_sha256','recovery_request_blob_sha256','protected_files_sha256'} and
        source_binding['schema']=='RACE_AI_OFFICIAL_FROZEN_SOURCE_BINDING_V1' and
        source_binding==snapshot.get('source_frozen_binding'),'FROZEN_SOURCE_BINDING')
    code=value['verified_code_ancestor']['head_sha'];intent=snapshot.get('head_sha');issue=source_binding['intent_head_sha']
    need(I._hex(intent) and I._hex(issue) and I._hex(current['current_head_sha']) and
        len({code,intent,issue})==3 and code==snapshot.get('execution_head_sha')==source_binding['tested_execution_head_sha'] and
        intent==active['head_sha']==binding['intent_head_sha']==current['intent_head_sha'] and
        issue==snapshot.get('source_issue_head')==snapshot.get('latest_issue_head_sha')==current['latest_issue_head_sha'] and
        current['current_head_sha']==current['current_pr_head_sha']==snapshot.get('current_head_sha')==pr.get('head',{}).get('sha') and
        current['intent_is_ancestor'] is True and current['current_issue_head_sha']==issue and
        type(current['issue_history_count']) is int and 1<=current['issue_history_count']<=128 and
        source_binding['target']=={k:value['previous_source'][k] for k in ('head_sha','run_id','run_attempt')},'FROZEN_HEAD_ROLES')
    preparation=snapshot.get('preparation_raw');raw=snapshot.get('latest_issue_raw')
    need(type(preparation) is bytes and read_json_bytes(preparation)==value and
        sha256(preparation).hexdigest()==binding['intent_blob_sha256'] and type(raw) is bytes and
        sha256(raw).hexdigest()==source_binding['issue_request_blob_sha256'] and
        source_binding['recovery_request_blob_sha256']==value['previous_source']['recovery_request_blob_sha256'],
        'FROZEN_INTENT_BYTES')
    need(I._hex(source_binding['protected_files_sha256'],64) and
        source_binding['protected_files_sha256']==snapshot.get('protected_files_sha256')==current['protected_files_sha256'] and
        I._hex(snapshot.get('tested_workflow_blob')) and
        type(executed_workflow) is dict and set(executed_workflow)=={'commit_sha','head_sha','blob_sha'} and
        I._hex(executed_workflow['commit_sha']) and executed_workflow['head_sha']==intent and
        executed_workflow['blob_sha']==snapshot['tested_workflow_blob'],'FROZEN_EXECUTED_WORKFLOW')
    source=snapshot.get('source_issue_commit');parents=snapshot.get('parents')
    need(type(source) is dict and set(source)=={'head_sha','parents','changed_files','subject'} and
        source['head_sha']==issue and type(source['parents']) is list and len(source['parents'])==1 and
        I._hex(source['parents'][0]) and source['parents'][0]==source_binding['intent_parent_sha'] and
        source['changed_files']==[I.ISSUE_PATH] and
        type(source['subject']) is str and source['subject'].startswith(I.PREFIX) and
        type(parents) is list and len(parents)==1 and I._hex(parents[0]) and parents[0]==binding['intent_parent_sha'] and
        snapshot.get('changed_files')==[PATH] and
        type(snapshot.get('subject')) is str and snapshot['subject'].startswith(PREFIX) and
        snapshot.get('source_is_ancestor') is True and snapshot.get('source_issue_is_ancestor') is True and
        snapshot.get('source_parent_is_code_descendant') is True,'FROZEN_PREPARATION_LINEAGE')
    return dict(frozen_execution_head=code,source_issue_head=issue,preparation_intent_head=intent,
        admitted_current_pr_head=current['current_head_sha'],protected_files_sha256=source_binding['protected_files_sha256'],
        executed_workflow=deepcopy(executed_workflow),frozen_binding=deepcopy(binding),
        frozen_code_execution=True,current_pr_code_executed=False,reused_code_ancestor=True,parent_whole_first_verified=False)


def context_digest(context):
    """The current PR tip is freshly admitted, not a frozen source identity."""
    if context.get('frozen_code_execution') is True:
        return digest({key:value for key,value in context.items() if key!='admitted_current_pr_head'})
    return digest(context)


def validate_frozen_counts(counts):
    need(type(counts) is dict and FROZEN_COUNT_FIELDS<=set(counts) and
        type(counts.get('verified_code_ancestor')) is dict and type(counts.get('previous_source')) is dict,
        'FROZEN_OUTPUT_PROVENANCE')
    code=counts['frozen_execution_head'];intent=counts['preparation_intent_head'];issue=counts['source_issue_head']
    workflow=counts['executed_workflow']
    need(all(I._hex(h) for h in (code,intent,issue,counts['admitted_current_pr_head'])) and len({code,intent,issue})==3 and
        code==counts['verified_code_ancestor'].get('head_sha')==counts['previous_source'].get('head_sha') and
        intent==counts.get('prepare_head_sha') and I._hex(counts['protected_files_sha256'],64) and
        type(workflow) is dict and set(workflow)=={'commit_sha','head_sha','blob_sha'} and
        I._hex(workflow['commit_sha']) and workflow['head_sha']==intent and I._hex(workflow['blob_sha']) and
        counts['frozen_code_execution'] is True and counts['current_pr_code_executed'] is False and
        counts['reused_code_ancestor'] is True and counts['parent_whole_first_verified'] is False and
        I._id(counts['source_second_viewer_job_id']) and counts['source_second_viewer_job_id']!=
        counts['previous_source'].get('first_viewer_job_id') and
        'immediate_issuer_parent' not in counts and 'verified_parent' not in counts,'FROZEN_OUTPUT_PROVENANCE')


def admit_context(value,*,prepare_run,current_pr,snapshot,parent_current,parent_first,parent_jobs,
                  source_current,source_first,source_jobs,now,executed_workflow=None,source_second_jobs=None):
    value=validate_prepare_request(value);now=R.clock(now);frozen=value['schema']==SCHEMA_V3
    reused=value['schema'] in (SCHEMA_V2,SCHEMA_V3)
    parent=value['verified_code_ancestor' if reused else 'verified_parent'];source=value['previous_source']
    active=I.run_scope(prepare_run)
    need(active['run_attempt']==1 and active['status'] in ('queued','in_progress') and
        active['id'] not in (parent['run_id'],source['run_id']) and active['head_sha']==snapshot.get('head_sha'),'PREPARE_RUN')
    pr=current_pr
    expected_head=active['head_sha']
    if frozen:
        current=snapshot.get('current_admission')
        need(type(current) is dict,'FROZEN_CURRENT_SCOPE');expected_head=current.get('current_head_sha')
    need(type(pr) is dict and pr.get('number')==71 and pr.get('state')=='open' and
        pr.get('user',{}).get('id')==I.OWNER_ID and pr.get('user',{}).get('login')==I.OWNER and
        pr.get('head',{}).get('sha')==expected_head and pr['head'].get('ref')==I.BRANCH and
        pr.get('base',{}).get('ref')==I.BASE and all(pr.get(side,{}).get('repo',{}).get('id')==I.REPOSITORY_ID and
        pr[side]['repo'].get('full_name')==I.REPOSITORY for side in ('head','base')),'CURRENT_OWNER_PR')
    frozen_proof=_frozen_snapshot(value,active,pr,snapshot,executed_workflow) if frozen else None
    immediate=snapshot.get('issuer_parent') if reused and not frozen else None
    if not frozen:
        need((not reused or type(immediate) is dict and I._hex(immediate.get('head_sha'))) and
            snapshot.get('parents')==[immediate['head_sha'] if reused else parent['head_sha']] and snapshot.get('changed_files')==[PATH] and
            type(snapshot.get('subject')) is str and snapshot['subject'].startswith(PREFIX) and
            snapshot.get('source_is_ancestor') is True,'PREPARE_ONLY_CHILD')
    if reused and not frozen:
        need(immediate.get('parents')==[parent['head_sha']] and immediate.get('changed_files')==[I.ISSUE_PATH] and
            type(immediate.get('subject')) is str and immediate['subject'].startswith(I.PREFIX) and
            immediate.get('issue_raw')==snapshot.get('latest_issue_raw'),'EXACT_ISSUE_ONLY_PARENT')
        changes=snapshot.get('data_only_changes')
        need(type(changes) is list and len(changes)==2 and [c.get('path') for c in changes]==[I.ISSUE_PATH,PATH] and
            all(type(c) is dict and set(c)=={'path','old_mode','new_mode','status'} and c['new_mode']=='100644' and
                (c['status']=='M' and c['old_mode']=='100644' or c['status']=='A' and c['old_mode']=='000000')
                for c in changes),'EXACT_TWO_DATA_ONLY_CHANGES')
        need(type(executed_workflow) is dict and set(executed_workflow)=={'commit_sha','head_sha','blob_sha'} and
            I._hex(executed_workflow['commit_sha']) and executed_workflow['head_sha']==active['head_sha'] and
            I._hex(snapshot.get('tested_workflow_blob')) and
            executed_workflow['blob_sha']==snapshot['tested_workflow_blob'],'EXECUTED_TESTED_WORKFLOW')
    prior,_,source_proof=_full(source,source_current,source_first,source_jobs,now)
    need(prior['run_attempt']==2,'ACTUAL_SOURCE_ATTEMPT_TWO')
    second=_source_second_viewer(source,source_current,source_first,source_second_jobs,now) if frozen else None
    current,first,parent_proof=_full(parent,parent_current,parent_first,parent_jobs,now)
    need(current['run_attempt']==1 and current==first or current['run_attempt']==2 and current==prior and
        parent['run_id']==source['run_id'] and parent['head_sha']==source['head_sha'],'VERIFIED_PARENT_CURRENT_ATTEMPT')
    raw=snapshot.get('recovery_raw')
    need(type(raw) is bytes and 0<len(raw)<=32768 and raw==snapshot.get('current_recovery_raw') and
        sha256(raw).hexdigest()==source['recovery_request_blob_sha256'],'IMMUTABLE_SOURCE_REQUEST_BYTES')
    request=read_json_bytes(raw);need(digest(request)==source['recovery_request_sha256'],'IMMUTABLE_SOURCE_REQUEST_DIGEST')
    latest=I.validate_issue_request(read_json_bytes(snapshot.get('latest_issue_raw')))
    need(latest['target']=={k:source[k] for k in ('head_sha','run_id','run_attempt')} and
        latest['target_first_viewer_job_id']==source['first_viewer_job_id'] and
        all(latest[k]==source[k] for k in ('recovery_request_sha256','recovery_request_blob_sha256')),'LATEST_SOURCE_ISSUE')
    if frozen:
        need(latest.get('schema')=='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V2' and
            latest.get('tested_execution_head_sha')==parent['head_sha'] and
            latest.get('intent_parent_sha')==snapshot['source_issue_commit']['parents'][0],'FROZEN_SOURCE_ISSUE')
    if value['kind']==SINGLE:
        need(request.get('schema')==H.REQUEST and request.get('mode')==H.CONTINUATION_MODE and
            request.get('probe_sport')=='autorace','ACTUAL_AUTO32_SOURCE_REQUIRED')
    else:
        need(request.get('schema')==S.REQUEST and request.get('mode')==S.HISTORICAL_MODE and
            request.get('probe_sport')=='keirin','ACTUAL_KEIRIN_SIXTEEN_SOURCE_REQUIRED')
    if frozen:
        return dict(verified_code_ancestor=deepcopy(parent),previous_source=deepcopy(source),
            verified_code_ancestor_proof=parent_proof,previous_source_first_proof=source_proof,
            source_second_viewer_job_id=second['job_id'],source_second_viewer_proof=second,**frozen_proof)
    if reused:
        return dict(verified_code_ancestor=deepcopy(parent),previous_source=deepcopy(source),
            verified_code_ancestor_proof=parent_proof,previous_source_first_proof=source_proof,
            immediate_issuer_parent=immediate['head_sha'],reused_code_ancestor=True,
            parent_whole_first_verified=False,executed_workflow=deepcopy(executed_workflow))
    return dict(verified_parent=deepcopy(parent),previous_source=deepcopy(source),
        verified_parent_proof=parent_proof,previous_source_first_proof=source_proof)


def derive_plan(kind,original,old_journal,*,probe_case=None):
    need(kind in (SINGLE,EIGHT) and type(original) is dict and
        original.get('schema')=='RACE_AI_OFFICIAL_RESULT_COLLECTION_PLAN_V1' and
        type(original.get('cases')) is list,'ORIGINAL_PLAN')
    rows=[case for case in original['cases'] if case.get('sport')=='keirin']
    need(rows and all(case.get('route',{}).get('kind')=='NORMAL_UI' for case in rows),'ORIGINAL_KEIRIN_NORMAL_UI')
    if kind==SINGLE:
        eligible=[case for case in rows if any(row.get('sport')=='keirin' and row.get('race_id')==case['race_id'] and
            row.get('state') in ('DUE','HOLD_BROWSER_SOURCE_UNVERIFIED') for row in old_journal.get('cases',[]))]
        need(eligible,'ORIGINAL_UNKNOWN_KEIRIN_CASE');selected=eligible[:1];limit=16
    else:
        need(probe_case in rows,'ORIGINAL_KEIRIN_PROBE_CASE')
        selected=[case for case in rows if case['route']['ui_entry_url']==probe_case['route']['ui_entry_url']][:8]
        need(len(selected)==8 and probe_case in selected,'EXACT_FIRST_EIGHT_KEIRIN_CASES');limit=32
    need(len({case['race_id'] for case in selected})==len(selected),'UNIQUE_ORIGINAL_CASES')
    plan=deepcopy(original);plan.update(cases=deepcopy(selected),maximum_requests=limit)
    if 'static_cache' in original:
        plan['static_cache']=[deepcopy(row) for row in original['static_cache'] if
            policy._url(row['metadata']['source_url'])[0]=='keirin']
    C.validate_plan('keirin',original,plan)
    return plan


def build_recovery_request(value,source_request,*,plan_sha256,now):
    from scripts import all_existing_model_official_result_collect as collector
    value=validate_prepare_request(value);need(I._hex(plan_sha256,64),'PLAN_CIPHER_SHA')
    source=value['previous_source'];manifest=deepcopy(source_request['manifest'])
    for field,pin in (('prior_journal_artifacts',source['journal_artifact']),('checkpoint_artifacts',source['result_artifact'])):
        need(pin['id'] not in {p['id'] for p in manifest[field]},'FRESH_SOURCE_OUTPUT_PIN');manifest[field].append(deepcopy(pin))
    manifest.update(schema=collector.SCHEMA_V3,execution_day=R.clock(now).astimezone(collector.JST).date().isoformat(),
        target_event_day=value['target_event_day'],plan_sha256=plan_sha256,
        plan_path='audit/state/official-result-collection-plan-'+plan_sha256+'.enc',allow_order_only=True)
    request={k:deepcopy(source_request[k]) for k in ('repository_id','pull_request','old_journal_artifact_id')}
    request.update(probe_sport='keirin',manifest=manifest)
    if value['kind']==SINGLE:request.update(schema=S.REQUEST,mode=S.HISTORICAL_MODE);S.validate_request(request,now)
    else:
        request.update(schema=H.REQUEST,mode=H.CONTINUATION_MODE,probe_journal_artifact_id=source['journal_artifact']['id'],
            probe_result_artifact_id=source['result_artifact']['id'],probe_request_sha256=digest(source_request))
        C.validate_request(request,now)
    return request


def prepare_from_evidence(value,data,*,context,run_id,head_sha,now,key):
    """Pure owner-codec preparation. Caller supplies actual authenticated transports."""
    from .boat_all_model_store import open_forecasts,seal_forecasts
    from .all_existing_model_receipt import _verified_private_pairs_artifact
    from .all_existing_model_order_only_pdca import _frozen
    from . import all_existing_model_official_results as official
    from . import all_existing_model_registry as registry
    from .four_sport_model_suite import ALL_MODELS
    from scripts import all_existing_model_official_result_collect as collector
    value=validate_prepare_request(value);now=R.clock(now);source=value['previous_source'];original_request=data['source_request']
    need(type(key) is bytes and len(key)==32 and I._id(run_id) and I._hex(head_sha),'OWNER_CODEC_CONTEXT')
    need(digest(original_request)==source['recovery_request_sha256'],'SOURCE_REQUEST_JOIN')
    source_inner=data['source_capsule_raw']
    if value['schema']==SCHEMA_V3:
        from .all_existing_model_official_frozen_capsule import unwrap_capsule
        source_inner=unwrap_capsule(source_inner,expected_binding=context['frozen_binding']['source_frozen_binding'],key=key)
    owner=I.archival_authority(data['source_capsule_raw'],request=original_request,
        target={k:source[k] for k in ('head_sha','run_id','run_attempt')},first_attempt=data['source_first_attempt'],key=key)
    # A prospective plan hash is never invented: existing encrypted source plan
    # anchors the cumulative metadata closure before the new plan is sealed.
    closure=deepcopy(original_request)
    for field,pin in (('prior_journal_artifacts',source['journal_artifact']),('checkpoint_artifacts',source['result_artifact'])):
        need(pin['id'] not in {p['id'] for p in closure['manifest'][field]},'FRESH_SOURCE_OUTPUT_PIN')
        closure['manifest'][field].append(deepcopy(pin))
    maps={field:C._archive_map(data['groups'][field],closure['manifest'][field]) for field in I.PIN_FIELDS}
    need(sum(len(a['raw']) for group in maps.values() for a in group.values())+len(data['source_capsule_raw'])<=
        256*1024*1024,'TOTAL_EVIDENCE_BOUND')
    old_pin=next(p for p in closure['manifest']['prior_journal_artifacts'] if p['id']==R.OLD_ARTIFACT)
    old=maps['prior_journal_artifacts'][R.OLD_ARTIFACT]
    old_body,_=R._evidence(old['raw'],old['metadata'],old_pin,now,key)
    prior=dict(request=closure,old_run=data['old_run'],prior_runs=data['prior_runs'],
        prior_journal_archives=data['groups']['prior_journal_artifacts'],old_journal_raw=old['raw'],old_journal_metadata=old['metadata'])
    bodies,receipts,runs=S._prior_evidence(prior,key,now)
    journal=bodies[source['journal_artifact']['id']]
    need(journal['manifest']==original_request['manifest'] and journal.get('recovery_authorization',{}).get(
        'authorization_sha256')==digest(owner),'SOURCE_JOURNAL_OWNER_BINDING')
    for run in (data['old_run'],*data['prior_runs']):I.run_scope(run)
    for field,manifest in (('old_plan_raw',old_body['manifest']),('source_plan_raw',original_request['manifest'])):
        need(type(data[field]) is bytes and sha256(data[field]).hexdigest()==manifest['plan_sha256'],'ORIGINAL_PLAN_CIPHER_SHA')
    original=open_forecasts(data['old_plan_raw'],key=key);source_plan=open_forecasts(data['source_plan_raw'],key=key)
    need(original['execution_day']==value['target_event_day'] and owner['old_plan']==original and
        owner['new_plan']==source_plan,'EXACT_ORIGINAL_OWNER_PLANS')
    if value['kind']==SINGLE:
        need(original_request.get('schema')==H.REQUEST and original_request.get('mode')==H.CONTINUATION_MODE and
            original_request.get('probe_sport')=='autorace' and source_plan['maximum_requests']==32 and
            len(source_plan['cases'])==8,'ACTUAL_AUTO32_SOURCE_REQUIRED')
        new_plan=derive_plan(SINGLE,original,old_body)
    else:
        need(original_request.get('schema')==S.REQUEST and original_request.get('mode')==S.HISTORICAL_MODE and
            original_request.get('probe_sport')=='keirin' and owner.get('probe_profile')==S.PROFILE and
            owner.get('maximum_new_requests')==16 and len(source_plan['cases'])==1,'ACTUAL_KEIRIN_SIXTEEN_SOURCE_REQUIRED')
        new_plan=derive_plan(EIGHT,original,old_body,probe_case=source_plan['cases'][0])
    raw=seal_forecasts(new_plan,run_id=str(run_id),round_no=ROUND,key=key)
    request=build_recovery_request(value,original_request,plan_sha256=sha256(raw).hexdigest(),now=now)
    I.check_pin_continuity(request['manifest'],previous_request=original_request,previous_run=data['source_current_run'],
        previous_artifacts=[maps['prior_journal_artifacts'][source['journal_artifact']['id']]['metadata'],
            maps['checkpoint_artifacts'][source['result_artifact']['id']]['metadata']])
    if value['kind']==SINGLE:
        S._plans(request,old_body,original,new_plan)
        replay=deepcopy(original_request);replay['manifest']=deepcopy(request['manifest'])
        replay['manifest'].update(plan_path=original_request['manifest']['plan_path'],plan_sha256=original_request['manifest']['plan_sha256'])
        from .all_existing_model_official_frozen_capsule import archival_probe_inner
        probe=next(pin for pin in original_request['manifest']['prior_journal_artifacts']
            if pin['id']==original_request['probe_journal_artifact_id'])
        probe_capsule=archival_probe_inner(data['probe_capsule_raw'],
            request_sha256=original_request['probe_request_sha256'],
            target=dict(head_sha=probe['head_sha'],run_id=probe['run_id'],run_attempt=2),key=key)
        objective_plan=source_plan;probe_first=data['probe_first_attempt']
    else:
        replay=request;objective_plan=new_plan;probe_capsule=source_inner;probe_first=data['source_first_attempt']
    verified=C.evidence(dict(request=replay,old_run=data['old_run'],prior_runs=data['prior_runs'],old_plan=original,
        new_plan=objective_plan,probe_first_attempt=probe_first,journal_archives=data['groups']['prior_journal_artifacts'],
        native_archives=data['groups']['native_artifacts'],checkpoint_archives=data['groups']['checkpoint_artifacts'],
        probe_capsule_raw=probe_capsule),key,now)
    records=[]
    for pin in request['manifest']['native_artifacts']:
        item=maps['native_artifacts'][pin['id']]
        _,rows=_verified_private_pairs_artifact(item['raw'],item['metadata'],now=now,
            expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'],key=key);records.extend(rows)
    frozen=_frozen(records);known,_=official._frozen(frozen)
    for case in new_plan['cases']:
        native=known.get(('keirin',collector._race_key(case['race_id'],'keirin')))
        need(native is not None,'SELECTED_CASE_WITHOUT_AUTHENTICATED_NATIVE')
        info=registry.identity(ALL_MODELS[0],'keirin',native);need(len(info['roster']) in (7,9),'ACTUAL_KEIRIN_REGISTERED_ROSTER')
    selected=maps['checkpoint_artifacts'][source['result_artifact']['id']]
    source_result=open_forecasts(official._cipher(selected['raw']),key=key)
    need(source_result['captures']==journal['captures'],'CURRENT_SOURCE_RESULT_CAPTURE_JOIN')
    labels=source_result['observations']
    sport='autorace' if value['kind']==SINGLE else 'keirin'
    normal=[o for o in labels if o.get('sport')==sport and o.get('status') in ('settled','rank_confirmed')]
    need(normal,'ACTUAL_NORMAL_PREVIOUS_SOURCE_REQUIRED')
    need(all(sum(row.get('sport')==o['sport'] and collector._race_key(row.get('race_id'),o['sport'])==
        collector._race_key(o['race_id'],o['sport']) and row.get('state')==o['status'] for row in journal['cases'])==1
        for o in normal),'CURRENT_SOURCE_NORMAL_CASE_JOIN')
    need(all(R.clock(journal['epoch_started_at'])<=R.clock(o['captured_at'])<=R.clock(
        journal['browser_attempt']['completed_at']) for o in normal),'CURRENT_SOURCE_NORMAL_CLOCK_JOIN')
    if value['kind']==EIGHT:need(len(normal)==1 and len(normal[0]['roster']) in (7,9),'ACTUAL_KEIRIN_NORMAL_ROSTER')
    latest=max(*(R.clock(r['updated_at'])+timedelta(seconds=1) for r in runs),
        *(R.clock(r['artifact_metadata']['created_at'])+timedelta(seconds=1) for r in receipts.values()))
    frozen=value['schema']==SCHEMA_V3;reused=value['schema'] in (SCHEMA_V2,SCHEMA_V3)
    counts=dict(schema=COUNTS_V3 if frozen else COUNTS_V2 if reused else COUNTS,state='AUTHENTICATED_KEIRIN_PLAN_PREPARED_NOT_AUTHORIZATION',ready=True,
        kind=value['kind'],prepare_run_id=run_id,prepare_head_sha=head_sha,prepared_at=now.isoformat(),
        preparation_request_sha256=digest(value),previous_source=deepcopy(source),
        **({'verified_code_ancestor':deepcopy(value['verified_code_ancestor'])} if reused else
           {'verified_parent':deepcopy(value['verified_parent'])}),context_sha256=context_digest(context),evidence_sha256=digest(verified),
        source_owner_authorization_sha256=digest(owner),original_plan_sha256=old_body['manifest']['plan_sha256'],
        selected_case_sha256=[digest(c) for c in new_plan['cases']],plan_plaintext_sha256=digest(new_plan),
        plan_cipher_sha256=sha256(raw).hexdigest(),recovery_request_sha256=digest(request),
        earliest_issue_at=(latest+timedelta(hours=1)).isoformat(),case_count=len(new_plan['cases']),
        maximum_new_requests=new_plan['maximum_requests'],previous_normal_observation_count=len(normal),
        source_requests=0,grants_issued=0,public_files_written=0,old_source_requests_actual=None,
        old_source_requests_upper_bound=32,plaintext_published=False,production_promoted=False,actual_purchases=False)
    if frozen:
        counts.update({k:deepcopy(context[k]) for k in FROZEN_COUNT_FIELDS});validate_frozen_counts(counts)
    elif reused:
        need(context.get('reused_code_ancestor') is True and context.get('parent_whole_first_verified') is False,
             'REUSED_CODE_CONTEXT')
        counts.update({k:deepcopy(context[k]) for k in ('immediate_issuer_parent','reused_code_ancestor',
            'parent_whole_first_verified','executed_workflow')})
    if value['kind']==EIGHT:
        from .keirin_future_selector import selector_metadata
        counts['future_selector']=selector_metadata(journal,receipts[source['journal_artifact']['id']],
            probe_case=source_plan['cases'][0],now=now,include_alternatives=True)
    return dict(plan_cipher=raw,request=request,counts=counts)
