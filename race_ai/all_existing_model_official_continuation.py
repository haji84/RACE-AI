"""Separate consumed continuation after a fully authenticated same-host probe.

The original UNKNOWN remains UNKNOWN. A completed probe proves only its own
normal UI/source path; its original MAC authority, native inputs, journal and
raw RESULT must all replay before a new fixed-attempt grant can be used.
"""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import base64
import hmac
from pathlib import Path,PurePosixPath
import re
import tempfile

from .actions_contract import digest
from . import all_existing_model_official_recovery as probe
from .boat_all_model_store import seal_forecasts,open_forecasts,forecast_header

REQUEST='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V2'
SCHEMA='RACE_AI_OFFICIAL_RESULT_VERIFIED_CONTINUATION_V1'
MODE='FIXED_ATTEMPT_TWO_AFTER_VERIFIED_SAME_HOST_PROBE'
STATE='CONSERVED_AND_CONSUMED_VERIFIED_CONTINUATION_FOR_FIXED_ATTEMPT_TWO'
DOMAIN=b'RACE_AI_OFFICIAL_RESULT_VERIFIED_CONTINUATION_MAC_V1'
ROUND=900022
_CAPABILITY=object()
need=probe.need
clock=probe.clock

def validate_request(value,now):
    if type(value) is dict and value.get('schema')=='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V3':
        from .all_existing_model_official_historical import validate_request as historical,CONTINUATION_MODE
        checked=historical(value,now);need(checked['mode']==CONTINUATION_MODE,'HISTORICAL_CONTINUATION_MODE');return checked
    fields={'schema','repository_id','pull_request','mode','probe_sport','old_journal_artifact_id','manifest',
        'probe_journal_artifact_id','probe_result_artifact_id','probe_request_sha256'}
    need(type(value) is dict and set(value)==fields and value['schema']==REQUEST and value['mode']==MODE,
        'CONTINUATION_REQUEST')
    legacy={k:deepcopy(v) for k,v in value.items() if k not in ('probe_journal_artifact_id','probe_result_artifact_id','probe_request_sha256')}
    legacy.update(schema=probe.REQUEST,mode=probe.MODE);probe.validate_request(legacy,now)
    need(type(value['probe_request_sha256']) is str and re.fullmatch('[a-f0-9]{64}',value['probe_request_sha256']),
        'PROBE_REQUEST_SHA')
    jp=[p for p in value['manifest']['prior_journal_artifacts'] if p['id']==value['probe_journal_artifact_id']]
    rp=[p for p in value['manifest']['checkpoint_artifacts'] if p['id']==value['probe_result_artifact_id']]
    need(len(jp)==len(rp)==1 and jp[0]['id']!=probe.OLD_ARTIFACT and jp[0]['run_id']==rp[0]['run_id'] and
        jp[0]['head_sha']==rp[0]['head_sha'] and jp[0]['run_id']!=probe.OLD_RUN,'PROBE_ARTIFACT_PINS')
    return deepcopy(value)

def validate_plan(sport,original,new):
    from .manual_official_capture import _url
    need(type(original) is dict and type(new) is dict,'CONTINUATION_PLAN')
    cache=original.get('static_cache');filtered=None if cache is None else [c for c in cache if _url(c['metadata']['source_url'])[0]==sport]
    cases=new.get('cases')
    need(original.get('schema')==new.get('schema')=='RACE_AI_OFFICIAL_RESULT_COLLECTION_PLAN_V1' and
        original.get('execution_day')==new.get('execution_day') and type(new.get('maximum_requests')) is int and
        1<=new['maximum_requests']<=32 and type(cases) is list and 1<=len(cases)<=8 and
        len({digest(c) for c in cases})==len(cases) and all(type(c) is dict and c.get('sport')==sport and
        c in original.get('cases',[]) and c.get('route',{}).get('kind')=='NORMAL_UI' for c in cases) and
        len({c['route']['ui_entry_url'] for c in cases})==1 and
        new.get('terms_manifest')==original.get('terms_manifest') and new.get('static_cache') in (cache,filtered) and
        new.get('result_wait_seconds')==original.get('result_wait_seconds'),'EXACT_SAME_HOST_CONTINUATION_PLAN')

def _complete(body,metadata,now,*,required=False,expected_limit=8):
    """Known wire outcomes, never a missing index or a reported count alone."""
    probe.no_known_denial(body)
    attempts=body['attempts'];need(all(a['state']!='RESERVED' and type(a.get('http_status')) is int and
        100<=a['http_status']<=599 for a in attempts),'PRIOR_OUTCOME_UNKNOWN')
    browser=body.get('browser_attempt')
    if browser is None:
        need(not required,'PROBE_BROWSER_REQUIRED');return len(attempts)
    if not required and type(browser) is dict and browser.get('state')=='REJECTED':
        from .all_existing_model_known_rejected_wire import known_data_rejected_wire
        return known_data_rejected_wire(body,metadata,now=now)['actual_request_count']
    need(type(browser) is dict and browser.get('state')=='COMPLETE' and type(browser.get('actual_request_count')) is int,
        'PROBE_BROWSER_INCOMPLETE')
    index=body.get('browser_index');count=browser['actual_request_count']
    need(type(index) is dict and index.get('schema')=='RACE_AI_OFFICIAL_RESULT_BROWSER_CAPTURE_V1' and
        index.get('normal_ui_only') is True and type(index.get('manual_api_requests')) is int and index['manual_api_requests']==0 and
        type(index.get('actual_request_count')) is int and index['actual_request_count']==count and
        0<=count<=body['maximum_requests']-len(attempts) and type(index.get('ledger')) is list,'PROBE_BROWSER_INDEX')
    requests=[entry for entry in index['ledger'] if type(entry) is dict and 'sequence' in entry]
    need(len(requests)==count and {e.get('sequence') for e in requests}==set(range(1,count+1)) and all(
        type(e.get('sequence')) is int and type(e.get('status')) is int and 100<=e['status']<=599 and
        clock(body['epoch_started_at'])<=clock(e['request_started_at'])<=clock(e['headers_received_at'])<=
        clock(browser['completed_at']) for e in requests),'PROBE_WIRE_OUTCOMES')
    bound=min(now,clock(metadata['created_at'])+timedelta(seconds=1))
    need(clock(body['epoch_started_at'])<=clock(browser['started_at'])<=clock(index['started_at'])<=
        clock(index['completed_at'])<=clock(browser['completed_at'])<=bound,'PROBE_BROWSER_CLOCK')
    if required:
        need(type(expected_limit) is int and expected_limit in (8,16),'EXPLICIT_PROBE_PROFILE_REQUIRED')
        need(not attempts and body['maximum_requests']==expected_limit and 1<=count<=expected_limit,
             'PROBE_EIGHT_REQUEST_BOUND' if expected_limit==8 else 'PROBE_SIXTEEN_REQUEST_BOUND')
        if expected_limit==16:
            need(type(browser.get('reserved_request_limit')) is int and browser['reserved_request_limit']==16,
                 'PROBE_SIXTEEN_RESERVATION_BOUND')
    return len(attempts)+count

def _pin_metadata(raw,metadata,pin,now):
    need(type(raw) is bytes and type(metadata) is dict and metadata.get('id')==pin['id'] and
        metadata.get('digest')==pin['digest']=='sha256:'+sha256(raw).hexdigest() and
        type(metadata.get('size_in_bytes')) is int and metadata['size_in_bytes']==len(raw) and
        metadata.get('workflow_run',{}).get('id')==pin['run_id'] and
        metadata.get('workflow_run',{}).get('head_sha')==pin['head_sha'],'EXACT_ARCHIVE_PIN')

def _archive_map(values,pins):
    need(type(values) is list and len(values)==len(pins),'ALL_SOURCE_ARCHIVES_REQUIRED')
    answer={}
    for item in values:
        need(type(item) is dict and set(item)=={'raw','metadata'} and type(item['metadata']) is dict,'SOURCE_ARCHIVE_SCHEMA')
        ident=item['metadata'].get('id');need(ident not in answer,'DUPLICATE_SOURCE_ARCHIVE');answer[ident]=item
    need(set(answer)=={p['id'] for p in pins},'ALL_SOURCE_ARCHIVES_REQUIRED');return answer

def _replay_probe_wire(journal,case,*,expected_limit=8):
    need(type(expected_limit) is int and expected_limit in (8,16),'EXPLICIT_PROBE_PROFILE_REQUIRED')
    from scripts import all_existing_model_official_result_collect as collector
    from scripts.boat_all_racers import _write
    from .permissioned_source_delivery import read_json_bytes
    quarantine=journal.get('browser_quarantine')
    need(type(quarantine) is dict and quarantine.get('complete') is True and
        quarantine.get('schema')=='RACE_AI_OFFICIAL_BROWSER_QUARANTINE_V1' and
        type(quarantine.get('files')) is list and len(quarantine['files'])<=128 and
        quarantine.get('inventory_sha256')==digest(quarantine.get('inventory')),'PROBE_RAW_WIRE_REQUIRED')
    names=set();used=0;index=None
    with tempfile.TemporaryDirectory(prefix='official-continuation-wire-') as folder:
        root=Path(folder)
        for file in quarantine['files']:
            need(type(file) is dict and type(file.get('file')) is str and 0<len(file['file'])<=240 and
                not PurePosixPath(file['file']).is_absolute() and '..' not in PurePosixPath(file['file']).parts and
                PurePosixPath(file['file']).as_posix()==file['file'] and
                file['file'] not in names and type(file.get('raw_base64')) is str,'PROBE_WIRE_FILE')
            raw=base64.b64decode(file['raw_base64'],validate=True);used+=len(raw);names.add(file['file'])
            need(used<=8*1024*1024 and len(raw)==file.get('byte_count') and sha256(raw).hexdigest()==file.get('source_sha256'),
                'PROBE_WIRE_BYTES')
            if file.get('kind') in ('HTTP_METADATA','ORIGINAL_INDEX','CANONICAL_RETURNED_OBJECT'):
                document=read_json_bytes(raw);probe.no_known_denial(document)
                if file.get('kind')=='CANONICAL_RETURNED_OBJECT':need(index is None,'DUPLICATE_PROBE_INDEX');index=document
            destination=root/file['file'];destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            _write(destination,raw)
            need(collector._safe_file(root,file['file'],2*1024*1024)==raw,'PROBE_WIRE_PRIVATE_FILE')
        need(type(index) is dict and digest(index)==quarantine.get('returned_index_sha256'),'PROBE_ORIGINAL_INDEX')
        if expected_limit==16:
            need(type(index.get('maximum_requests')) is int and index['maximum_requests']==16,
                 'PROBE_SIXTEEN_RAW_INDEX_BOUND')
        planned=[dict(sport=case['sport'],race_id=case['race_id'])]
        need(collector._index_diagnostic(index,planned)==journal['browser_index'],'PROBE_ORIGINAL_INDEX_PROJECTION')
        found,states,originals=collector.browser_sources(index,root,planned,started=clock(journal['browser_attempt']['started_at']),
            now=clock(journal['browser_attempt']['completed_at']),remaining=expected_limit)
        need(len(found)==1 and [row[2] for row in found]==journal.get('captures') and
            originals==journal.get('browser_captures') and states==[dict(sport=case['sport'],race_id=case['race_id'],state='CAPTURED')],
            'PROBE_SOURCE_WIRE_JOIN')

def _completed_authority(raw,request,journal,journal_evidence,oldbody,old_evidence,oldplan,probe_first,prior_runs,key,
                         *,prior_journal_receipts=None,prior_journal_bodies=None):
    """Archival replay of original V1 authority; grants no live dispatch."""
    need(type(raw) is bytes,'ORIGINAL_PROBE_CAPSULE_REQUIRED')
    value=open_forecasts(raw,key=key);header=forecast_header(raw)
    from . import all_existing_model_official_probe16 as sixteen
    if type(value) is dict and value.get('schema')==sixteen.SCHEMA:
        return sixteen.completed_authority(raw,request=request,journal=journal,journal_evidence=journal_evidence,
            oldbody=oldbody,old_evidence=old_evidence,oldplan=oldplan,probe_first=probe_first,prior_runs=prior_runs,
            prior_journal_receipts=prior_journal_receipts,prior_journal_bodies=prior_journal_bodies,key=key)
    need(type(value) is dict and set(value)=={'schema','body','mac'} and value['schema']==probe.SCHEMA and
        type(value['body']) is dict and type(value['mac']) is str and
        hmac.compare_digest(value['mac'],probe._mac(value['body'],key)),'ORIGINAL_PROBE_CAPSULE_MAC')
    b=value['body'];source_request=b['request'];target=b['target'];pin=journal_evidence['pin']
    from .all_existing_model_official_historical import REQUEST as HISTORICAL,PROBE_MODE
    source_probe=(source_request.get('schema')==probe.REQUEST and source_request.get('mode')==probe.MODE or
        source_request.get('schema')==HISTORICAL and source_request.get('mode')==PROBE_MODE)
    probe.validate_request(source_request,clock(journal['epoch_started_at']))
    if source_request.get('schema')==HISTORICAL:
        from .all_existing_model_official_historical import validate_window
        validate_window(source_request,b['issued_at'],b['expires_at'])
    need(b['schema']==probe.SCHEMA and b['state']==probe.STATE and source_probe and
        digest(source_request)==request['probe_request_sha256']==b['request_sha256'] and
        source_request['probe_sport']==request['probe_sport'] and source_request['manifest']==journal['manifest'] and
        target==dict(run_id=pin['run_id'],head_sha=pin['head_sha'],run_attempt=2) and
        header['run_id']==str(pin['run_id']) and header['round_no']==probe.ROUND and b['old_journal']==old_evidence and
        b['old_plan']==oldplan and b['old_source_requests_actual'] is None and b['old_source_requests_upper_bound']==32 and
        b['old_browser_outcome']=='UNKNOWN' and b['maximum_new_requests']==8,'ORIGINAL_PROBE_AUTHORITY_BINDING')
    actual_probe=next(r for r in prior_runs if r['id']==pin['run_id'])
    first=probe.run_receipt(probe_first)
    need(actual_probe['status']=='completed' and actual_probe['run_attempt']==2 and actual_probe['head_sha']==target['head_sha'] and
        first==b['first_attempt'] and first['id']==target['run_id'] and first['head_sha']==target['head_sha'] and
        first['run_attempt']==1 and first['status']=='completed' and first['conclusion']=='success','COMPLETED_PROBE_RUN_RECEIPTS')
    expected_old=[r for r in prior_runs if r['id'] in {p['run_id'] for p in source_request['manifest']['prior_journal_artifacts']}]
    need(expected_old==b['prior_runs'] and b['old_run'] in expected_old,'ORIGINAL_PRIOR_RUN_RECEIPTS')
    probe._plans(source_request,oldbody,oldplan,b['new_plan'])
    audit=probe.ValidatedRecovery(b,probe._CAPABILITY).audit()
    need(journal.get('recovery_authorization')==audit,'ORIGINAL_PROBE_JOURNAL_AUTHORITY')
    starts=[journal['epoch_started_at'],journal['browser_attempt']['started_at']]+[
        e['request_started_at'] for e in journal['browser_index']['ledger'] if 'sequence' in e]+[
        c['metadata']['fetched_at'] for c in journal.get('browser_captures',[])]
    need(all(max(clock(b['not_before']),clock(b['issued_at']))<=clock(t)<clock(b['expires_at']) for t in starts) and
        clock(b['not_before'])<=clock(b['issued_at'])<clock(b['expires_at'])<=clock(b['issued_at'])+timedelta(hours=1),
        'ORIGINAL_PROBE_DISPATCH_WINDOW')
    latest=max(*(clock(r['updated_at'])+timedelta(seconds=1) for r in expected_old),
        clock(old_evidence['artifact_metadata']['created_at'])+timedelta(seconds=1))
    need(latest==clock(b['latest_possible_old_activity_at']) and latest+timedelta(hours=1)<=clock(b['not_before']),
        'ORIGINAL_PROBE_PACING')
    return dict(cipher_sha256=sha256(raw).hexdigest(),body_sha256=digest(b),request_sha256=b['request_sha256'],
        path=probe.capsule_path(source_request,target['head_sha'],target['run_id']))

def _authority_limit(authority):
    if not {'probe_profile','maximum_new_requests'}&set(authority):return 8
    from .all_existing_model_official_probe16 import PROFILE,LIMIT
    need(authority.get('probe_profile')==PROFILE and type(authority.get('maximum_new_requests')) is int and
         authority['maximum_new_requests']==LIMIT,'AUTHENTICATED_PROBE_PROFILE')
    return LIMIT

def evidence(data,key,now):
    """Authenticate every original; no JSON-only label or audit can unlock this."""
    from scripts import all_existing_model_official_result_collect as collector
    from scripts.all_existing_model_learning import _merge_verified_result_observations
    from .all_existing_model_receipt import _verified_private_pairs_artifact
    from .all_existing_model_order_only_pdca import _frozen
    from . import all_existing_model_official_results as results
    request=validate_request(data['request'],now);manifest=request['manifest']
    runs=probe._prior_runs(request,data['old_run'],data.get('prior_runs',[]))
    journals=_archive_map(data['journal_archives'],manifest['prior_journal_artifacts'])
    native_archives=_archive_map(data['native_archives'],manifest['native_artifacts'])
    result_archives=_archive_map(data['checkpoint_archives'],manifest['checkpoint_artifacts'])
    total=sum(len(item['raw']) for group in (journals,native_archives,result_archives) for item in group.values())+len(data['probe_capsule_raw'])
    need(total<=256*1024*1024,'TOTAL_EVIDENCE_BOUND')
    bodies={};receipts={}
    for pin in manifest['prior_journal_artifacts']:
        item=journals[pin['id']];body,receipt=probe._evidence(item['raw'],item['metadata'],pin,now,key)
        run=next(r for r in runs if r['id']==pin['run_id'])
        need(clock(run['run_started_at'])<=clock(body['epoch_started_at'])<=clock(item['metadata']['created_at'])+timedelta(seconds=1) and
            clock(item['metadata']['created_at'])<=clock(run['updated_at'])+timedelta(seconds=1),'PRIOR_RUN_JOURNAL_CLOCK')
        bodies[pin['id']]=body;receipts[pin['id']]=receipt
        if pin['id']!=probe.OLD_ARTIFACT:_complete(body,item['metadata'],now)
    old=bodies[probe.OLD_ARTIFACT];old_receipt=receipts[probe.OLD_ARTIFACT]
    journal=bodies[request['probe_journal_artifact_id']];journal_receipt=receipts[request['probe_journal_artifact_id']]
    original=old['manifest'];need(manifest['native_artifacts']==original['native_artifacts'] and len(manifest['native_artifacts'])==4 and
        all(p in manifest['checkpoint_artifacts'] for p in original['checkpoint_artifacts']) and
        all(p in manifest['prior_journal_artifacts'] for p in original['prior_journal_artifacts']),'ORIGINAL_PINS')
    validate_plan(request['probe_sport'],data['old_plan'],data['new_plan'])
    authority=_completed_authority(data['probe_capsule_raw'],request,journal,journal_receipt,old,old_receipt,
        data['old_plan'],data['probe_first_attempt'],runs,key,prior_journal_receipts=receipts,prior_journal_bodies=bodies)
    limit=_authority_limit(authority)
    _complete(journal,journal_receipt['artifact_metadata'],now,required=True,expected_limit=limit)
    value=open_forecasts(data['probe_capsule_raw'],key=key)['body']
    cases=value['new_plan']['cases'];need(len(cases)==1,'ORIGINAL_SINGLE_PROBE')
    selected=cases[0];need(selected['sport']==request['probe_sport'] and all(c['route']['ui_entry_url']==
        selected['route']['ui_entry_url'] for c in data['new_plan']['cases']),'SAME_ORIGINAL_PROBE_ROUTE')
    _replay_probe_wire(journal,selected,expected_limit=limit)
    parts=[];native_receipts=[]
    for pin in manifest['native_artifacts']:
        item=native_archives[pin['id']];_pin_metadata(item['raw'],item['metadata'],pin,now)
        admission,records=_verified_private_pairs_artifact(item['raw'],item['metadata'],now=now,
            expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'],key=key)
        native_receipts.append(admission);parts.extend(records)
    frozen=_frozen(parts);known,_=results._frozen(frozen)
    need(all((c['sport'],collector._race_key(c['race_id'],c['sport'])) in known for c in data['new_plan']['cases']),
        'CONTINUATION_CASE_WITHOUT_FROZEN_NATIVE')
    observations=[];result_receipts=[];chosen=None;chosen_payload=None
    for pin in manifest['checkpoint_artifacts']:
        item=result_archives[pin['id']];_pin_metadata(item['raw'],item['metadata'],pin,now)
        admitted=results.observations_from_official_result_artifact(item['raw'],item['metadata'],now=now,
            expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'],frozen_native_payloads=frozen,key=key,allow_order_only=True)
        observations.extend(admitted['observations']);result_receipts.append(admitted['receipt'])
        if pin['id']==request['probe_result_artifact_id']:
            chosen=admitted;chosen_payload=open_forecasts(results._cipher(item['raw']),key=key)
    case_identity=lambda o:(o['sport'],collector._race_key(o['race_id'],o['sport']))
    latest={case_identity(o):o for o in _merge_verified_result_observations(observations)}
    case_key=(selected['sport'],collector._race_key(selected['race_id'],selected['sport']))
    normal=[o for o in chosen['observations'] if case_identity(o)==case_key and o['status'] in ('settled','rank_confirmed')]
    need(len(normal)==1 and latest.get(case_key)==normal[0] and len(chosen['observations'])==1 and
        all(capture in journal['captures'] for capture in chosen_payload['captures']) and
        len(chosen_payload['captures'])==len(journal['captures']) and
        any(c.get('sport')==selected['sport'] and collector._race_key(c.get('race_id'),selected['sport'])==case_key[1] and
            c.get('state')==normal[0]['status'] for c in journal['cases']),'ACTUAL_NORMAL_PROBE_TEACHER_JOIN')
    return dict(old_journal=old_receipt,prior_journal_receipts=[receipts[p['id']] for p in manifest['prior_journal_artifacts']],
        prior_runs=runs,native_admissions=native_receipts,result_receipts=result_receipts,probe_authority=authority,
        probe_normal_observation_sha256=digest(normal[0]),verified_probe_requests=journal['browser_attempt']['actual_request_count'])

def _mac(body,key):return hmac.digest(hmac.digest(key,DOMAIN,'sha256'),digest(body).encode(),'sha256').hex()

DATA_FIELDS={'request','target','issued_at','not_before','expires_at','old_run','prior_runs','first_attempt',
    'probe_first_attempt','old_plan','new_plan','journal_archives','native_archives','checkpoint_archives','probe_capsule_raw'}

def issue_consume_capsule(data,key):
    need(type(key) is bytes and len(key)==32 and type(data) is dict and set(data)==DATA_FIELDS,'CONTINUATION_ISSUE_FIELDS')
    now=clock(data['issued_at']);request=validate_request(data['request'],now);target=data['target']
    if request['schema']=='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V3':
        from .all_existing_model_official_historical import validate_window
        validate_window(request,data['issued_at'],data['expires_at'])
    need(type(target) is dict and set(target)=={'head_sha','run_id','run_attempt'} and type(target['run_attempt']) is int and
        target['run_attempt']==2,'TARGET');probe.capsule_path(request,target['head_sha'],target['run_id'])
    first=probe.run_receipt(data['first_attempt']);need(first['id']==target['run_id'] and first['head_sha']==target['head_sha'] and
        first['run_attempt']==1 and first['status']=='completed' and first['conclusion']=='success' and clock(first['updated_at'])<=now,
        'FIRST_ATTEMPT_SUCCESS')
    proof=evidence(data,key,now)
    need(target['run_id'] not in {r['id'] for r in proof['prior_runs']},'FRESH_CONTINUATION_RUN_REQUIRED')
    latest=max(*(clock(r['updated_at'])+timedelta(seconds=1) for r in proof['prior_runs']),
        *(clock(r['artifact_metadata']['created_at'])+timedelta(seconds=1) for r in proof['prior_journal_receipts']))
    need(latest+timedelta(hours=1)<=clock(data['not_before'])<=now<clock(data['expires_at'])<=now+timedelta(hours=1),
        'CONTINUATION_CLOCK')
    body=dict(schema=SCHEMA,state=STATE,request=request,request_sha256=digest(request),target=deepcopy(target),
        issued_at=data['issued_at'],not_before=data['not_before'],expires_at=data['expires_at'],first_attempt=first,
        old_plan=deepcopy(data['old_plan']),new_plan=deepcopy(data['new_plan']),evidence=proof,
        old_source_requests_actual=None,old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN',
        maximum_new_requests=data['new_plan']['maximum_requests'],latest_possible_old_activity_at=latest.isoformat())
    return seal_forecasts(dict(schema=SCHEMA,body=body,mac=_mac(body,key)),run_id=str(target['run_id']),round_no=ROUND,key=key)

class ValidatedContinuation:
    def __init__(self,body,seal):need(seal is _CAPABILITY,'CONTINUATION_CAPABILITY');self._body=deepcopy(body);self._seal=seal
    def audit(self):
        b=self._body
        return dict(schema=SCHEMA,state=STATE,authorization_sha256=digest(b),request_sha256=b['request_sha256'],target=deepcopy(b['target']),
            old_journal=deepcopy(b['evidence']['old_journal']),old_source_requests_actual=None,old_source_requests_upper_bound=32,
            old_browser_outcome='UNKNOWN',maximum_new_requests=b['maximum_new_requests'],verified_probe_requests=b['evidence']['verified_probe_requests'],
            prior_evidence_sha256=digest(b['evidence']),issued_at=b['issued_at'],not_before=b['not_before'],expires_at=b['expires_at'])
    def validate_collector(self,manifest,plan,env,now):
        b=self._body;need(self._seal is _CAPABILITY and manifest==b['request']['manifest'] and plan==b['new_plan'] and
            env['run_id']==b['target']['run_id'] and env['head_sha']==b['target']['head_sha'] and
            max(clock(b['not_before']),clock(b['issued_at']))<=now<clock(b['expires_at']),
            'COLLECTOR_BINDING');return self.audit()
    def validate_prior(self,manifest,pin,body,cipher,actual,now):
        need(self._seal is _CAPABILITY and manifest==self._body['request']['manifest'] and
            clock(self._body['not_before'])<=now<clock(self._body['expires_at']),'HISTORY_SCOPE');probe.no_known_denial(body)
        expected=next(r for r in self._body['evidence']['prior_journal_receipts'] if r['pin']['id']==pin['id'])
        need(pin==expected['pin'] and actual==expected['artifact_metadata'] and sha256(cipher).hexdigest()==expected['cipher_sha256'] and
            digest(body)==expected['payload_sha256'],'EXACT_CONTINUATION_PRIOR_RECEIPT')
        if pin['id']==probe.OLD_ARTIFACT:return True
        _complete(body,actual,now,required=pin['id']==self._body['request']['probe_journal_artifact_id'],
                  expected_limit=_authority_limit(self._body['evidence']['probe_authority']));return False

def validate_capsule(raw,*,data,current_run,now,key):
    need(type(key) is bytes and len(key)==32,'EXPLICIT_OWNER_KEY');now=clock(now)
    need(type(data) is dict and set(data)==DATA_FIELDS,'CONTINUATION_REPLAY_FIELDS')
    request=validate_request(data['request'],now);value=open_forecasts(raw,key=key);header=forecast_header(raw)
    need(type(value) is dict and set(value)=={'schema','body','mac'} and value['schema']==SCHEMA and
        type(value['body']) is dict and type(value['mac']) is str and hmac.compare_digest(value['mac'],_mac(value['body'],key)),
        'CONTINUATION_CAPSULE_MAC')
    b=value['body'];current=probe.run_receipt(current_run)
    if request['schema']=='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V3':
        from .all_existing_model_official_historical import validate_window
        validate_window(request,b['issued_at'],b['expires_at'])
    need(set(b)=={'schema','state','request','request_sha256','target','issued_at','not_before','expires_at','first_attempt',
        'old_plan','new_plan','evidence','old_source_requests_actual','old_source_requests_upper_bound','old_browser_outcome',
        'maximum_new_requests','latest_possible_old_activity_at'},'CONTINUATION_CAPSULE_FIELDS')
    need(b['schema']==SCHEMA and b['state']==STATE and b['request']==request and b['request_sha256']==digest(request) and
        b['target']==dict(run_id=current['id'],head_sha=current['head_sha'],run_attempt=current['run_attempt']) and
        current['run_attempt']==2 and current['status'] in ('queued','in_progress') and header['run_id']==str(current['id']) and
        header['round_no']==ROUND,'FIXED_ATTEMPT_TWO')
    proof=evidence(data,key,now)
    latest=max(*(clock(r['updated_at'])+timedelta(seconds=1) for r in proof['prior_runs']),
        *(clock(r['artifact_metadata']['created_at'])+timedelta(seconds=1) for r in proof['prior_journal_receipts']))
    need(probe.run_receipt(data['first_attempt'])==b['first_attempt'] and b['first_attempt']['id']==current['id'] and
        b['first_attempt']['head_sha']==current['head_sha'] and b['first_attempt']['run_attempt']==1 and
        b['first_attempt']['status']=='completed' and b['first_attempt']['conclusion']=='success' and
        clock(b['first_attempt']['updated_at'])<=clock(b['issued_at']) and b['old_plan']==data['old_plan'] and
        b['new_plan']==data['new_plan'] and proof==b['evidence'] and current['id'] not in {r['id'] for r in proof['prior_runs']} and
        latest==clock(b['latest_possible_old_activity_at']) and latest+timedelta(hours=1)<=clock(b['not_before'])<=clock(b['issued_at'])<=
        now<clock(b['expires_at'])<=clock(b['issued_at'])+timedelta(hours=1) and b['old_source_requests_actual'] is None and
        b['old_source_requests_upper_bound']==32 and b['old_browser_outcome']=='UNKNOWN' and
        type(b['maximum_new_requests']) is int and b['maximum_new_requests']==data['new_plan']['maximum_requests'],
        'CONTINUATION_REPLAY')
    return ValidatedContinuation(b,_CAPABILITY)
