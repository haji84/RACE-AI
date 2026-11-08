"""Pure fixed recovery issuance gates; no key lookup, provider or publication.

The public request names a previously fully verified parent run. Only the
Actions wrapper may supply the existing owner secret and actual GitHub records.
Publication verification deliberately returns no live collector capability.
"""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import hmac
import re

from .actions_contract import digest
from . import all_existing_model_official_recovery as R
from . import all_existing_model_official_continuation as C
from . import all_existing_model_official_historical as H
from .boat_all_model_store import open_forecasts,forecast_header
from .permissioned_source_delivery import read_json_bytes

SCHEMA='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V1'
SCHEMA_V2='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V2'
PROOF='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_PROOF_V1'
PROOF_V2='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_PROOF_V2'
ISSUE_PATH='audit/state/official-result-recovery-issue-request.json'
REQUEST_PATH='audit/state/official-result-recovery-request.json'
REPOSITORY='haji84/RACE-AI'
REPOSITORY_ID=1416489937
WORKFLOW=392270247
WORKFLOW_PATH='.github/workflows/forecast-audit-ui.yml'
BRANCH='feat/four-sport-forecast-audit-view-20261022'
BASE='codex/actions-four-sport-e2e'
OWNER_ID=173585154
OWNER='haji84'
PREFIX='official-results-issue:'
PIN_FIELDS=('native_artifacts','checkpoint_artifacts','prior_journal_artifacts')
# Reviewed bootstrap includes the actual last 901 epoch, not just base6a's
# older three-journal request. IDs select the exact bytes hashed below.
SEED_IDS=((13559236491,13555822588,13559826825,13562395496),
          (13559822755,13562547496,13565712482),
          (13562617631,13565712487,13572350517,13574582081))
SEED_SHA256='66fcc8f9ed82c25c969694871fd85f8606eaa22700f729df7732aec97e21a2ac'


def need(ok,reason):
    if not ok:raise ValueError('OFFICIAL_ISSUE_'+reason)


def _id(value):return type(value) is int and 0<value<10**20


def _hex(value,length=40):return type(value) is str and re.fullmatch('[a-f0-9]{'+str(length)+'}',value) is not None


def validate_issue_request(value):
    fields={'schema','repository_id','workflow_id','pull_request','target','target_first_viewer_job_id',
            'recovery_request_sha256','recovery_request_blob_sha256'}
    frozen=type(value) is dict and value.get('schema')==SCHEMA_V2
    expected=fields|{'tested_execution_head_sha','intent_parent_sha','failed_issue_dispositions'} if frozen else fields
    need(type(value) is dict and set(value)==expected and value['schema'] in (SCHEMA,SCHEMA_V2) and
         type(value['repository_id']) is int and value['repository_id']==REPOSITORY_ID and
         type(value['workflow_id']) is int and value['workflow_id']==WORKFLOW and
         type(value['pull_request']) is int and value['pull_request']==71,'REQUEST')
    target=value['target']
    need(type(target) is dict and set(target)=={'head_sha','run_id','run_attempt'} and
         _hex(target['head_sha']) and _id(target['run_id']) and type(target['run_attempt']) is int and
         target['run_attempt']==2 and _id(value['target_first_viewer_job_id']) and
         _hex(value['recovery_request_sha256'],64) and _hex(value['recovery_request_blob_sha256'],64),'TARGET')
    if frozen:
        need(value['tested_execution_head_sha']==target['head_sha'] and _hex(value['intent_parent_sha']),'FROZEN_TARGET')
        failed=value['failed_issue_dispositions']
        need(type(failed) is list and len(failed)<=8 and all(type(item) is dict and
            set(item)=={'intent_head_sha','issue_blob_sha256'} and _hex(item['intent_head_sha']) and
            _hex(item['issue_blob_sha256'],64) for item in failed) and
            len({item['intent_head_sha'] for item in failed})==len(failed),'FAILED_DISPOSITIONS')
    return deepcopy(value)


def authority_for(request):
    """A literal registry; public input cannot choose a Python module."""
    need(type(request) is dict,'RECOVERY_REQUEST')
    pair=(request.get('schema'),request.get('mode'))
    if pair in ((R.REQUEST,R.MODE),(H.REQUEST,H.PROBE_MODE)):return R
    if pair in ((C.REQUEST,C.MODE),(H.REQUEST,H.CONTINUATION_MODE)):return C
    if pair in (('RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V4','FIXED_ATTEMPT_TWO_SINGLE_NORMAL_UI_PROBE_16'),
                ('RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V4','FIXED_ATTEMPT_TWO_HISTORICAL_SINGLE_NORMAL_UI_PROBE_16')):
        from . import all_existing_model_official_probe16 as S
        return S
    need(False,'UNSUPPORTED_AUTHORITY')


def run_scope(value):
    receipt=R.run_receipt(value)
    need(value.get('workflow_id')==WORKFLOW and value.get('path')==WORKFLOW_PATH and
         value.get('head_branch')==BRANCH and value.get('event')=='pull_request','RUN_SCOPE')
    for field in ('actor','triggering_actor'):
        actor=value.get(field)
        need(type(actor) is dict and type(actor.get('id')) is int and actor['id']==OWNER_ID and
             actor.get('login')==OWNER,'OWNER_ACTOR')
    return receipt


def admit_context(value,*,issuer_run,current_pr,snapshot,target_run,first_attempt,jobs,now):
    """Admit an issue-only child commit against actual successful parent facts."""
    value=validate_issue_request(value);target=value['target'];now=R.clock(now)
    issuer=run_scope(issuer_run)
    need(issuer['run_attempt']==1 and issuer['status'] in ('queued','in_progress') and
         issuer['id']!=target['run_id'] and issuer['head_sha']==snapshot.get('head_sha'),'ISSUER_ATTEMPT')
    pr=current_pr;frozen=value['schema']==SCHEMA_V2
    need(type(pr) is dict and pr.get('number')==71 and pr.get('state')=='open' and
         pr.get('user',{}).get('id')==OWNER_ID and pr.get('user',{}).get('login')==OWNER and
         (frozen or pr.get('head',{}).get('sha')==issuer['head_sha']) and pr['head'].get('ref')==BRANCH and
         pr.get('base',{}).get('ref')==BASE and all(pr.get(side,{}).get('repo',{}).get('id')==REPOSITORY_ID and
         pr[side]['repo'].get('full_name')==REPOSITORY for side in ('head','base')),'CURRENT_PR')
    need(snapshot.get('parents')==[value['intent_parent_sha'] if frozen else target['head_sha']] and snapshot.get('changed_files')==[ISSUE_PATH] and
         type(snapshot.get('subject')) is str and snapshot['subject'].startswith(PREFIX) and
         type(snapshot.get('target_subject')) is str and snapshot['target_subject'].startswith('official-results-collect:'),
         'ISSUE_ONLY_PARENT')
    if frozen:_frozen_context(value,snapshot,pr)
    raw=snapshot.get('recovery_raw')
    need(type(raw) is bytes and 0<len(raw)<=32768 and raw==snapshot.get('current_recovery_raw') and
         sha256(raw).hexdigest()==value['recovery_request_blob_sha256'],'IMMUTABLE_REQUEST_BYTES')
    request=read_json_bytes(raw);authority_for(request).validate_request(request,now)
    need(digest(request)==value['recovery_request_sha256'],'IMMUTABLE_REQUEST_DIGEST')
    current=run_scope(target_run);first=run_scope(first_attempt)
    need(current==first and current['id']==target['run_id'] and current['head_sha']==target['head_sha'] and
         current['run_attempt']==1 and current['status']=='completed' and current['conclusion']=='success' and
         R.clock(current['updated_at'])<=now,'ACTUAL_FIRST_ATTEMPT')
    from scripts.all_existing_model_official_result_recovery import _full_first_attempt
    proof=_full_first_attempt(first_attempt,jobs,dict(run_id=target['run_id'],head_sha=target['head_sha']))
    viewers=[job for job in jobs['jobs'] if job.get('name')=='Viewer audit contract']
    need(viewers[0]['id']==value['target_first_viewer_job_id'],'EXACT_VIEWER_JOB')
    result=dict(proof,target=deepcopy(target),target_first_viewer_job_id=value['target_first_viewer_job_id'])
    if frozen:result.update(tested_execution_head_sha=target['head_sha'],intent_head_sha=issuer['head_sha'],
        intent_parent_sha=value['intent_parent_sha'],admitted_current_pr_head=pr['head']['sha'],
        protected_files_sha256=snapshot['protected_files_sha256'],frozen_code_execution=True,current_pr_code_executed=False)
    return result


def _frozen_context(value,snapshot,pr):
    """Consume only freshly proven Git facts, never substitute current code."""
    from .all_existing_model_official_frozen_capsule import validate_binding
    target=value['target'];head=snapshot['head_sha'];live=pr['head']['sha']
    need(snapshot.get('execution_head_sha')==target['head_sha']==value['tested_execution_head_sha'] and
        snapshot.get('intent_head_sha')==head and snapshot.get('source_issue_head')==head and
        snapshot.get('latest_issue_head_sha')==head and snapshot.get('current_head_sha')==live and
        snapshot.get('source_is_ancestor') is True and snapshot.get('intent_is_ancestor_of_current') is True and
        snapshot.get('frozen_code_execution') is True and snapshot.get('current_pr_code_executed') is False,
        'FROZEN_EXECUTION_AND_ACTIVE_INTENT')
    current=snapshot.get('current_admission')
    need(type(current) is dict and current.get('current_pr_head_sha')==live and
        current.get('intent_is_ancestor') is True and current.get('current_issue_head_sha')==head,'FRESH_CURRENT_INTENT')
    workflow=snapshot.get('executed_workflow')
    need(type(workflow) is dict and set(workflow)=={'commit_sha','head_sha','blob_sha'} and
        _hex(workflow['commit_sha']) and workflow['head_sha']==head and _hex(snapshot.get('tested_workflow_blob')) and
        workflow['blob_sha']==snapshot['tested_workflow_blob'],'FROZEN_EXECUTED_WORKFLOW')
    binding=validate_binding(snapshot.get('source_frozen_binding'))
    need(binding['tested_execution_head_sha']==target['head_sha'] and binding['intent_head_sha']==head and
        binding['intent_parent_sha']==value['intent_parent_sha'] and binding['target']==target and
        binding['recovery_request_blob_sha256']==value['recovery_request_blob_sha256'] and
        _hex(snapshot.get('protected_files_sha256'),64) and
        binding['protected_files_sha256']==snapshot['protected_files_sha256'],'FROZEN_AUTHORITY_CLOSURE')
    raw=snapshot.get('latest_issue_raw')
    need(type(raw) is bytes and read_json_bytes(raw)==value and sha256(raw).hexdigest()==binding['issue_request_blob_sha256'],
         'FROZEN_IMMUTABLE_ISSUE')


def pin_from_metadata(metadata):
    run=metadata.get('workflow_run',{})
    need(_id(metadata.get('id')) and type(metadata.get('digest')) is str and
         re.fullmatch('sha256:[a-f0-9]{64}',metadata['digest']) and _id(run.get('id')) and
         _hex(run.get('head_sha')) and all(type(run.get(k)) is int and run[k]==REPOSITORY_ID
         for k in ('repository_id','head_repository_id')),'OUTPUT_METADATA')
    return dict(id=metadata['id'],digest=metadata['digest'],run_id=run['id'],head_sha=run['head_sha'])


def check_pin_continuity(manifest,*,previous_request=None,previous_run=None,previous_artifacts=None):
    """Missing prior journal is uncertainty, never evidence of zero requests."""
    need(type(manifest) is dict,'MANIFEST')
    if previous_request is None:
        selected={}
        for field,ids in zip(PIN_FIELDS,SEED_IDS):
            pins=manifest.get(field);need(type(pins) is list,'SEED_PINS')
            by_id={p.get('id'):p for p in pins if type(p) is dict}
            need(len(by_id)==len(pins) and all(ident in by_id for ident in ids),'SEED_PINS')
            selected[field]=[by_id[ident] for ident in ids]
        need(digest(selected)==SEED_SHA256,'SEED_HASH')
        return
    need(type(previous_request) is dict and all(type(manifest.get(field)) is list and
         all(pin in manifest[field] for pin in previous_request['manifest'][field]) for field in PIN_FIELDS),
         'CUMULATIVE_PINS')
    need(manifest['native_artifacts']==previous_request['manifest']['native_artifacts'],'ORIGINAL_NATIVE_PINS')
    run=run_scope(previous_run)
    need(run['run_attempt']==2 and run['status']=='completed','PREVIOUS_ACTUAL_ATTEMPT_TWO_TERMINAL')
    need(type(previous_artifacts) is list and len(previous_artifacts)<=10000,'PREVIOUS_ARTIFACTS')
    journal='official-result-collection-journal-'+str(run['id'])
    result='all-existing-official-results-'+str(run['id'])+'-900005'
    journals=[a for a in previous_artifacts if a.get('name')==journal]
    results=[a for a in previous_artifacts if a.get('name')==result]
    need(len(journals)==1 and len(results)<=1,'PREVIOUS_ACTUAL_JOURNAL_REQUIRED')
    for field,items in (('prior_journal_artifacts',journals),('checkpoint_artifacts',results)):
        for metadata in items:
            pin=pin_from_metadata(metadata)
            need(pin['run_id']==run['id'] and pin['head_sha']==run['head_sha'] and pin in manifest[field],
                 'PREVIOUS_ACTUAL_OUTPUT_PIN_REQUIRED')


def archival_authority(raw,*,request,target,first_attempt,key):
    """Authenticate a retained issuer body without creating live authority."""
    from .all_existing_model_official_frozen_capsule import archival_inner
    inner=archival_inner(raw,request=request,target=target,key=key)
    return _archival_legacy_authority(inner,request=request,target=target,first_attempt=first_attempt,key=key)


def archival_capsule_bytes(raw,*,request,target,first_attempt,key):
    """Preserve the exact legacy evidence bytes for original C/S readers."""
    from .all_existing_model_official_frozen_capsule import archival_inner
    inner=archival_inner(raw,request=request,target=target,key=key)
    _archival_legacy_authority(inner,request=request,target=target,first_attempt=first_attempt,key=key)
    return inner


def _archival_legacy_authority(raw,*,request,target,first_attempt,key):
    authority=authority_for(request);value=open_forecasts(raw,key=key);header=forecast_header(raw)
    need(type(value) is dict and set(value)=={'schema','body','mac'} and value['schema']==authority.SCHEMA and
         type(value['body']) is dict and type(value['mac']) is str and
         hmac.compare_digest(value['mac'],authority._mac(value['body'],key)),'PUBLICATION_MAC')
    body=value['body'];issued=R.clock(body['issued_at']);expires=R.clock(body['expires_at'])
    authority.validate_request(request,issued)
    need(body.get('schema')==authority.SCHEMA and body.get('state')==authority.STATE and
         body.get('request')==request and body.get('request_sha256')==digest(request) and body.get('target')==target and
         target.get('run_attempt')==2 and header['run_id']==str(target['run_id']) and header['round_no']==authority.ROUND and
         body.get('first_attempt')==R.run_receipt(first_attempt) and
         body['first_attempt']['id']==target['run_id'] and body['first_attempt']['head_sha']==target['head_sha'] and
         body['first_attempt']['run_attempt']==1 and body['first_attempt']['status']=='completed' and
         body['first_attempt']['conclusion']=='success' and R.clock(body['not_before'])<=issued<expires<=issued+timedelta(hours=1) and
         body.get('old_source_requests_actual') is None and body.get('old_source_requests_upper_bound')==32 and
         body.get('old_browser_outcome')=='UNKNOWN','PUBLICATION_BODY')
    R.no_known_denial(body)
    return deepcopy(body)


def _publication_expected(data,key,now):
    """Replay the existing pure evidence rules, without sealing or live admission."""
    request=data['request'];authority=authority_for(request)
    if request['schema']=='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V4':
        return authority._body(data,key,now)
    issued=R.clock(data['issued_at']);authority.validate_request(request,issued)
    target=data['target'];R.capsule_path(request,target['head_sha'],target['run_id'])
    need(target==dict(head_sha=data['first_attempt']['head_sha'],run_id=data['first_attempt']['id'],run_attempt=2),
         'PUBLICATION_TARGET')
    first=R.run_receipt(data['first_attempt']);old=R.run_receipt(data['old_run'])
    runs=R._prior_runs(request,data['old_run'],data.get('prior_runs',[]))
    need(first['run_attempt']==1 and first['status']=='completed' and first['conclusion']=='success' and
         R.clock(first['updated_at'])<=issued and target['run_id'] not in {r['id'] for r in runs} and
         all(R.clock(run['updated_at'])<=issued for run in runs),'PUBLICATION_ACTUAL_EVIDENCE')
    body=dict(schema=authority.SCHEMA,state=authority.STATE,request=deepcopy(request),request_sha256=digest(request),
        target=deepcopy(target),issued_at=data['issued_at'],not_before=data['not_before'],expires_at=data['expires_at'],
        first_attempt=first,old_plan=deepcopy(data['old_plan']),new_plan=deepcopy(data['new_plan']),
        old_source_requests_actual=None,old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN')
    if authority is C:
        need(set(data)==C.DATA_FIELDS,'PUBLICATION_CONTINUATION_FIELDS')
        evidence=C.evidence(data,key,now)
        latest=max(*(R.clock(run['updated_at'])+timedelta(seconds=1) for run in evidence['prior_runs']),
            *(R.clock(receipt['artifact_metadata']['created_at'])+timedelta(seconds=1) for receipt in evidence['prior_journal_receipts']))
        body.update(evidence=evidence,maximum_new_requests=data['new_plan']['maximum_requests'])
    else:
        pin=next(p for p in request['manifest']['prior_journal_artifacts'] if p['id']==R.OLD_ARTIFACT)
        oldbody,evidence=R._evidence(data['old_journal_raw'],data['old_journal_metadata'],pin,issued,key)
        R._plans(request,oldbody,data['old_plan'],data['new_plan'])
        need(old['id']==R.OLD_RUN and old['head_sha']==R.OLD_HEAD and old['status']=='completed','PUBLICATION_OLD_RUN')
        latest=max(*(R.clock(run['updated_at'])+timedelta(seconds=1) for run in runs),
            R.clock(evidence['artifact_metadata']['created_at'])+timedelta(seconds=1))
        body.update(old_journal=evidence,old_run=old,prior_runs=runs,maximum_new_requests=8)
    if request['schema']==H.REQUEST:H.validate_window(request,data['issued_at'],data['expires_at'])
    need(latest+timedelta(hours=1)<=R.clock(data['not_before'])<=issued<=now<R.clock(data['expires_at'])<=
         issued+timedelta(hours=1),'PUBLICATION_EVIDENCE_CLOCK')
    body['latest_possible_old_activity_at']=latest.isoformat()
    return body


def verify_publication(raw,*,data,current_run,now,key,expected_raw=None):
    """Verify actual remote bytes while the target remains actual attempt one."""
    current=run_scope(current_run);first=R.run_receipt(data['first_attempt'])
    need(current==first and current['run_attempt']==1 and current['status']=='completed' and
         current['conclusion']=='success','PUBLICATION_ACTUAL_FIRST')
    if expected_raw is not None:need(raw==expected_raw,'PUBLICATION_EXACT_BYTES')
    body=archival_authority(raw,request=data['request'],target=data['target'],first_attempt=data['first_attempt'],key=key)
    now=R.clock(now)
    need(body==_publication_expected(data,key,now),'PUBLICATION_EXACT_EVIDENCE_BODY')
    need(R.clock(body['not_before'])<=R.clock(body['issued_at'])<=now<R.clock(body['expires_at']) and
         (R.clock(body['expires_at'])-now).total_seconds()>=600,'PUBLICATION_WINDOW')
    for field in ('issued_at','not_before','expires_at','old_plan','new_plan'):
        need(body[field]==data[field],'PUBLICATION_EXACT_BODY')
    return dict(authorization_sha256=digest(body),capsule_sha256=sha256(raw).hexdigest(),
        old_source_requests_actual=None,old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN',
        maximum_new_requests=body['maximum_new_requests'],issued_at=body['issued_at'],
        not_before=body['not_before'],expires_at=body['expires_at'])
