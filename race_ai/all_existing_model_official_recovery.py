"""One consumed attempt-two recovery grant; never clears historical UNKNOWN.

Issuance is explicit and pure. Runtime admission still fetches actual GitHub
journal/run metadata and authenticates the original encrypted plans. This grant
cannot override a recorded denial or authorize a second uncertain generation.
"""
from copy import deepcopy
from datetime import datetime,timedelta
from hashlib import sha256
import hmac
import re

from .actions_contract import digest
from .boat_all_model_store import seal_forecasts,open_forecasts,forecast_header

REQUEST='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V1'
SCHEMA='RACE_AI_OFFICIAL_RESULT_FIXED_RECOVERY_V1'
MODE='FIXED_ATTEMPT_TWO_SINGLE_NORMAL_UI_PROBE'
STATE='CONSERVED_AND_CONSUMED_FOR_FIXED_ATTEMPT_TWO'
DOMAIN=b'RACE_AI_OFFICIAL_RESULT_FIXED_RECOVERY_MAC_V1'
ROUND=900021
OLD_ARTIFACT=13565712487
OLD_RUN=42349536138
OLD_HEAD='9b4bc37648fbfad421daa80bd2300cda5e97e9df'
REPOSITORY_ID=1416489937
_CAPABILITY=object()

def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_OFFICIAL_RECOVERY_'+reason)

def clock(value):
    parsed=value if type(value) is datetime else datetime.fromisoformat(value.replace('Z','+00:00'))
    need(parsed.utcoffset() is not None,'AWARE_CLOCK');return parsed

def validate_request(value,now):
    if type(value) is dict and value.get('schema')=='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V4':
        from .all_existing_model_official_probe16 import validate_request as sixteen_request
        return sixteen_request(value,now)
    if type(value) is dict and value.get('schema')=='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V3':
        from .all_existing_model_official_historical import validate_request as historical_request
        return historical_request(value,now)
    if type(value) is dict and value.get('schema')=='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V2':
        from .all_existing_model_official_continuation import validate_request as continuation_request
        return continuation_request(value,now)
    from scripts import all_existing_model_official_result_collect as collector
    need(type(value) is dict and set(value)=={'schema','repository_id','pull_request','mode','probe_sport',
        'old_journal_artifact_id','manifest'} and value['schema']==REQUEST and
        type(value['repository_id']) is int and value['repository_id']==REPOSITORY_ID and
        type(value['pull_request']) is int and value['pull_request']==71 and value['mode']==MODE and
        value['probe_sport'] in ('autorace','keirin') and value['old_journal_artifact_id']==OLD_ARTIFACT,'REQUEST')
    manifest=collector._manifest(value['manifest'],clock(now))
    need(manifest['schema']==collector.SCHEMA_V2 and manifest['allow_order_only'] is True,'MANIFEST')
    pins=[p for p in manifest['prior_journal_artifacts'] if p['id']==OLD_ARTIFACT]
    need(len(pins)==1 and pins[0]['run_id']==OLD_RUN and pins[0]['head_sha']==OLD_HEAD,'FIXED_OLD_JOURNAL')
    return deepcopy(value)

def capsule_path(request,head_sha,run_id):
    need(type(head_sha) is str and re.fullmatch('[a-f0-9]{40}',head_sha) and type(run_id) is int and run_id>0,'TARGET')
    return 'recovery/official-results/'+digest(request)+'/'+head_sha+'/'+str(run_id)+'/2.enc'

def is_continuation_request(request):
    return request.get('schema')=='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V2' or (
        request.get('schema')=='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V3' and
        request.get('mode')=='FIXED_ATTEMPT_TWO_HISTORICAL_AFTER_VERIFIED_SAME_HOST_PROBE')

def run_receipt(value):
    need(type(value) is dict and type(value.get('id')) is int and value['id']>0 and
        type(value.get('head_sha')) is str and re.fullmatch('[a-f0-9]{40}',value['head_sha']) and
        type(value.get('run_attempt')) is int and value['run_attempt']>0 and all(type(value.get(k)) is dict and
        value[k].get('id')==REPOSITORY_ID and value[k].get('full_name')=='haji84/RACE-AI'
        for k in ('repository','head_repository')),'RUN_IDENTITY')
    need(any(type(p) is dict and p.get('number')==71 for p in value.get('pull_requests',[])),'PULL_REQUEST')
    for key in ('updated_at','run_started_at'):clock(value[key])
    return {k:deepcopy(value[k]) for k in ('id','head_sha','run_attempt','status','conclusion','updated_at','run_started_at')}

def no_known_denial(value):
    if type(value) is dict:
        for key,item in value.items():
            need(not (key in ('http_status','status') and type(item) is int and item in (401,403,429)) and
                not (key in ('state','stop_reason') and item in ('DENIED','HTTP_ACCESS_DENIED','ACCESS_DENIED',
                    'HOLD_ACCESS_DENIED','HOLD_HOST_DENIED')) and
                not (key in ('stopped_host','http_access_denied','entire_host_stopped','stdout_stopped_host') and item is True),
                'KNOWN_DENIAL_NON_OVERRIDABLE')
            no_known_denial(item)
    elif type(value) is list:
        for item in value:no_known_denial(item)

def _evidence(raw,metadata,pin,now,key):
    from scripts import all_existing_model_official_result_collect as c
    need(type(raw) is bytes and type(metadata) is dict and metadata.get('id')==pin['id'] and
        metadata.get('name')=='official-result-collection-journal-'+str(pin['run_id']) and
        metadata.get('expired') is False and type(metadata.get('size_in_bytes')) is int and
        metadata['size_in_bytes']==len(raw)<=c.results.MAX_ARCHIVE_BYTES and
        metadata.get('digest')==pin['digest']=='sha256:'+sha256(raw).hexdigest(),'JOURNAL_BYTES')
    run=metadata.get('workflow_run');need(type(run) is dict and run.get('id')==pin['run_id'] and
        run.get('head_sha')==pin['head_sha'] and all(type(run.get(k)) is int and run[k]==REPOSITORY_ID
            for k in ('repository_id','head_repository_id')),'JOURNAL_IDENTITY')
    saved=clock(metadata['created_at']);need(saved<=now<clock(metadata['expires_at']),'JOURNAL_CLOCK')
    cipher=c._journal_cipher(raw);body=c._journal_origin(cipher,key=key,run_id=pin['run_id'],head_sha=pin['head_sha'],now=now,saved_at=saved)
    no_known_denial(body)
    return body,dict(pin=deepcopy(pin),artifact_metadata=deepcopy(metadata),cipher_sha256=sha256(cipher).hexdigest(),
        payload_sha256=digest(body))

def _plans(request,body,old,new):
    return _plans_with_limit(request,body,old,new,8)

def _plans_with_limit(request,body,old,new,limit):
    need(type(limit) is int and limit in (8,16),'FIXED_PROBE_PROFILE_LIMIT')
    from .manual_official_capture import _url
    from scripts.all_existing_model_official_result_collect import target_event_day
    original=body['manifest'];manifest=request['manifest']
    cache=old.get('static_cache');filtered=None if cache is None else [entry for entry in cache
        if _url(entry['metadata']['source_url'])[0]==request['probe_sport']]
    need(manifest['native_artifacts']==original['native_artifacts'] and len(manifest['native_artifacts'])==4 and
        all(p in manifest['checkpoint_artifacts'] for p in original['checkpoint_artifacts']) and
        all(p in manifest['prior_journal_artifacts'] for p in original['prior_journal_artifacts']),'ORIGINAL_PINS')
    need(type(old) is dict and type(new) is dict and old.get('execution_day')==new.get('execution_day')==target_event_day(manifest) and
        old.get('schema')==new.get('schema')=='RACE_AI_OFFICIAL_RESULT_COLLECTION_PLAN_V1' and
        type(new.get('maximum_requests')) is int and new['maximum_requests']==limit and
        type(new.get('cases')) is list and len(new['cases'])==1 and
        new['cases'][0].get('sport')==request['probe_sport'] and new['cases'][0] in old.get('cases',[]) and
        new['cases'][0]['route'].get('kind')=='NORMAL_UI' and
        new.get('terms_manifest')==old.get('terms_manifest') and
        new.get('static_cache') in (cache,filtered) and
        new.get('result_wait_seconds')==old.get('result_wait_seconds'),'EXACT_SINGLE_NORMAL_UI_PLAN')
    browser=body.get('browser_attempt')
    need(type(browser) is dict and browser.get('state')=='RESERVED' and
        'actual_request_count' not in browser and body['maximum_requests']==32 and
        len(body['attempts'])==8 and browser.get('reserved_request_limit')==24 and
        all(a.get('state')=='SUCCESS' and a.get('http_status')==200 for a in body['attempts']) and
        not any(name in body for name in ('browser_index','browser_request_checkpoint')),'FIXED_UNKNOWN_SHAPE')
    # The one selected case must have been due and entrusted to this old browser.
    cases=[c for c in body.get('cases',[]) if c.get('sport')==request['probe_sport'] and
        c.get('race_id')==new['cases'][0]['race_id']]
    need(len(cases)==1 and cases[0].get('state') in ('DUE','HOLD_BROWSER_SOURCE_UNVERIFIED'),'OLD_UNKNOWN_CASE')

def _mac(body,key):
    need(type(key) is bytes and len(key)==32,'EXPLICIT_OWNER_KEY')
    return hmac.digest(hmac.digest(key,DOMAIN,'sha256'),digest(body).encode(),'sha256').hex()

def _prior_runs(request,old_run,others):
    need(type(others) in (list,tuple) and len(others)<=16,'PRIOR_RUNS')
    receipts=[run_receipt(old_run),*[run_receipt(value) for value in others]]
    expected={pin['run_id']:pin['head_sha'] for pin in request['manifest']['prior_journal_artifacts']}
    need(len(receipts)==len({r['id'] for r in receipts})==len(expected) and
        all(r['id'] in expected and r['head_sha']==expected[r['id']] and r['status']=='completed' for r in receipts),
        'ALL_PRIOR_RUNS_TERMINAL')
    return sorted(receipts,key=lambda r:r['id'])

def issue_consume_capsule(data,key):
    """Return consumed AES bytes for a parent-owned create-only CAS publication.

    This performs no publication, fetching, source call, environment key lookup
    or automatic issuance. The caller supplies actual fetched metadata.
    """
    need(type(key) is bytes and len(key)==32,'EXPLICIT_OWNER_KEY')
    fields={'request','target','issued_at','not_before','expires_at','old_journal_raw','old_journal_metadata',
        'old_run','first_attempt','old_plan','new_plan'}
    need(type(data) is dict and fields<=set(data)<=fields|{'prior_runs'},'ISSUE_FIELDS')
    issued=clock(data['issued_at']);request=validate_request(data['request'],issued);target=data['target']
    need(request['schema'] in (REQUEST,'RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V3') and
        request['mode'] in (MODE,'FIXED_ATTEMPT_TWO_HISTORICAL_SINGLE_NORMAL_UI_PROBE'),'LEGACY_PROBE_PROFILE_REQUIRED')
    need(type(target) is dict and set(target)=={'head_sha','run_id','run_attempt'} and target['run_attempt']==2 and
        type(target['run_attempt']) is int,'TARGET')
    capsule_path(request,target['head_sha'],target['run_id'])
    first=run_receipt(data['first_attempt']);oldrun=run_receipt(data['old_run'])
    need(first['id']==target['run_id'] and first['head_sha']==target['head_sha'] and first['run_attempt']==1 and
        first['status']=='completed' and first['conclusion']=='success' and clock(first['updated_at'])<=issued,'FIRST_ATTEMPT_SUCCESS')
    need(oldrun['id']==OLD_RUN and oldrun['head_sha']==OLD_HEAD and oldrun['status']=='completed' and
        clock(oldrun['updated_at'])<=issued,'OLD_RUN_TERMINAL')
    prior_runs=_prior_runs(request,data['old_run'],data.get('prior_runs',[]))
    need(all(clock(r['updated_at'])<=issued for r in prior_runs),'PRIOR_RUN_FUTURE')
    pin=next(p for p in request['manifest']['prior_journal_artifacts'] if p['id']==OLD_ARTIFACT)
    oldbody,evidence=_evidence(data['old_journal_raw'],data['old_journal_metadata'],pin,issued,key)
    _plans(request,oldbody,data['old_plan'],data['new_plan'])
    latest=max(*(clock(r['updated_at'])+timedelta(seconds=1) for r in prior_runs),clock(evidence['artifact_metadata']['created_at'])+timedelta(seconds=1))
    not_before=clock(data['not_before']);expires=clock(data['expires_at'])
    if request['schema']=='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V3':
        from .all_existing_model_official_historical import validate_window
        validate_window(request,data['issued_at'],data['expires_at'])
    need(latest+timedelta(hours=1)<=not_before<=issued<expires<=issued+timedelta(hours=1),'RECOVERY_CLOCK')
    body=dict(schema=SCHEMA,state=STATE,request=request,request_sha256=digest(request),target=deepcopy(target),
        issued_at=data['issued_at'],not_before=data['not_before'],expires_at=data['expires_at'],old_journal=evidence,
        old_run=oldrun,prior_runs=prior_runs,first_attempt=first,old_plan=deepcopy(data['old_plan']),new_plan=deepcopy(data['new_plan']),
        latest_possible_old_activity_at=latest.isoformat(),old_source_requests_actual=None,old_source_requests_upper_bound=32,
        old_browser_outcome='UNKNOWN',maximum_new_requests=8)
    return seal_forecasts(dict(schema=SCHEMA,body=body,mac=_mac(body,key)),run_id=str(target['run_id']),round_no=ROUND,key=key)

class ValidatedRecovery:
    def __init__(self,body,seal):need(seal is _CAPABILITY,'VALIDATED_CAPABILITY');self._body=deepcopy(body);self._seal=seal
    def audit(self):
        b=self._body
        return dict(schema=SCHEMA,state=STATE,authorization_sha256=digest(b),request_sha256=b['request_sha256'],
            target=deepcopy(b['target']),old_journal=deepcopy(b['old_journal']),old_source_requests_actual=None,
            old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN',maximum_new_requests=8,
            issued_at=b['issued_at'],not_before=b['not_before'],expires_at=b['expires_at'])
    def validate_collector(self,manifest,plan,env,now):
        b=self._body
        need(self._seal is _CAPABILITY and manifest==b['request']['manifest'] and plan==b['new_plan'] and
            env['run_id']==b['target']['run_id'] and env['head_sha']==b['target']['head_sha'] and
            clock(b['not_before'])<=now<clock(b['expires_at']),'COLLECTOR_BINDING')
        return self.audit()
    def validate_prior(self,manifest,pin,body,cipher,actual,now):
        need(self._seal is _CAPABILITY and manifest==self._body['request']['manifest'],'HISTORY_SCOPE')
        no_known_denial(body)
        if pin['id']!=OLD_ARTIFACT:return False
        expected=self._body['old_journal']
        need(pin==expected['pin'] and actual==expected['artifact_metadata'] and sha256(cipher).hexdigest()==expected['cipher_sha256'] and
            digest(body)==expected['payload_sha256'] and clock(self._body['not_before'])<=now<clock(self._body['expires_at']),
            'ORIGINAL_UNKNOWN_RECEIPT')
        _plans(self._body['request'],body,self._body['old_plan'],self._body['new_plan']);return True

def validate_capsule(raw,*,request,current_run,first_attempt,old_run,now,key,prior_runs=()):
    need(type(key) is bytes and len(key)==32,'EXPLICIT_OWNER_KEY')
    now=clock(now);validate_request(request,now)
    need(request['schema'] in (REQUEST,'RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V3') and
        request['mode'] in (MODE,'FIXED_ATTEMPT_TWO_HISTORICAL_SINGLE_NORMAL_UI_PROBE'),'LEGACY_PROBE_PROFILE_REQUIRED')
    value=open_forecasts(raw,key=key);header=forecast_header(raw)
    need(type(value) is dict and set(value)=={'schema','body','mac'} and value['schema']==SCHEMA and
        type(value['body']) is dict and type(value['mac']) is str and hmac.compare_digest(value['mac'],_mac(value['body'],key)),'CAPSULE_MAC')
    b=value['body'];target=b['target'];current=run_receipt(current_run)
    if request['schema']=='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V3':
        from .all_existing_model_official_historical import validate_window
        validate_window(request,b['issued_at'],b['expires_at'])
    need(b['schema']==SCHEMA and b['state']==STATE and b['request']==request and b['request_sha256']==digest(request) and
        target==dict(head_sha=current['head_sha'],run_id=current['id'],run_attempt=current['run_attempt']) and
        target['run_attempt']==2 and current['status'] in ('in_progress','queued') and
        header['run_id']==str(target['run_id']) and header['round_no']==ROUND,'FIXED_ATTEMPT_TWO')
    need(run_receipt(first_attempt)==b['first_attempt'] and b['first_attempt']['run_attempt']==1 and
        b['first_attempt']['status']=='completed' and b['first_attempt']['conclusion']=='success' and
        run_receipt(old_run)==b['old_run'] and b['old_run']['status']=='completed' and
        _prior_runs(request,old_run,prior_runs)==b['prior_runs'],'ACTUAL_RUN_RECEIPTS')
    latest=max(*(clock(r['updated_at'])+timedelta(seconds=1) for r in b['prior_runs']),
        clock(b['old_journal']['artifact_metadata']['created_at'])+timedelta(seconds=1))
    need(clock(b['not_before'])<=clock(b['issued_at'])<=now<clock(b['expires_at']) and
        latest==clock(b['latest_possible_old_activity_at']) and latest+timedelta(hours=1)<=clock(b['not_before']) and
        b['old_source_requests_actual'] is None and b['old_source_requests_upper_bound']==32 and
        b['old_browser_outcome']=='UNKNOWN' and b['maximum_new_requests']==8,'CONSERVED_CLOCK_AND_BUDGET')
    return ValidatedRecovery(b,_CAPABILITY)
