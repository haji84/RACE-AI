"""One explicitly reviewed sixteen-request normal-UI probe, never a reset.

The pure issuer authenticates all supplied historical journals. Runtime consumes
the distinct MAC/AES grant only on its exact reviewed run/HEAD/attempt2. Legacy
eight-request grants keep their existing schemas, domains, bytes and behavior.
"""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import hmac

from .actions_contract import digest
from . import all_existing_model_official_recovery as legacy
from .boat_all_model_store import seal_forecasts,open_forecasts,forecast_header

REQUEST='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V4'
SCHEMA='RACE_AI_OFFICIAL_RESULT_FIXED_SIXTEEN_PROBE_V1'
MODE='FIXED_ATTEMPT_TWO_SINGLE_NORMAL_UI_PROBE_16'
HISTORICAL_MODE='FIXED_ATTEMPT_TWO_HISTORICAL_SINGLE_NORMAL_UI_PROBE_16'
PROFILE='SINGLE_NORMAL_UI_PROBE_16_V1'
STATE='CONSERVED_AND_CONSUMED_FOR_FIXED_ATTEMPT_TWO'
DOMAIN=b'RACE_AI_OFFICIAL_RESULT_FIXED_SIXTEEN_PROBE_MAC_V1'
ROUND=900024
LIMIT=16
DATA_FIELDS={'request','target','issued_at','not_before','expires_at','old_journal_raw','old_journal_metadata',
             'old_run','prior_runs','first_attempt','old_plan','new_plan','prior_journal_archives'}
_CAPABILITY=object()
need=legacy.need
clock=legacy.clock


def validate_request(value,now):
    from scripts import all_existing_model_official_result_collect as collector
    fields={'schema','repository_id','pull_request','mode','probe_sport','old_journal_artifact_id','manifest'}
    need(type(value) is dict and set(value)==fields and value['schema']==REQUEST and
        value['mode'] in (MODE,HISTORICAL_MODE) and type(value['repository_id']) is int and
        value['repository_id']==legacy.REPOSITORY_ID and type(value['pull_request']) is int and
        value['pull_request']==71 and value['probe_sport'] in ('autorace','keirin') and
        type(value['old_journal_artifact_id']) is int and value['old_journal_artifact_id']==legacy.OLD_ARTIFACT,
        'SIXTEEN_REQUEST')
    manifest=collector._manifest(value['manifest'],clock(now))
    need(manifest['schema']==(collector.SCHEMA_V2 if value['mode']==MODE else collector.SCHEMA_V3) and
         manifest['allow_order_only'] is True,'SIXTEEN_MANIFEST')
    old=[p for p in manifest['prior_journal_artifacts'] if p['id']==legacy.OLD_ARTIFACT]
    need(len(old)==1 and old[0]['run_id']==legacy.OLD_RUN and old[0]['head_sha']==legacy.OLD_HEAD,'FIXED_OLD_JOURNAL')
    return deepcopy(value)


def _plans(request,body,old,new):
    return legacy._plans_with_limit(request,body,old,new,LIMIT)


def _window(request,issued,expires):
    from .all_existing_model_official_historical import validate_capture_window
    validate_capture_window(request['manifest'],issued,expires)


def _mac(body,key):
    need(type(key) is bytes and len(key)==32,'EXPLICIT_OWNER_KEY')
    return hmac.digest(hmac.digest(key,DOMAIN,'sha256'),digest(body).encode(),'sha256').hex()


def _prior_evidence(data,key,now):
    from . import all_existing_model_official_continuation as continuation
    request=data['request'];pins=request['manifest']['prior_journal_artifacts']
    runs=legacy._prior_runs(request,data['old_run'],data['prior_runs'])
    archives=continuation._archive_map(data['prior_journal_archives'],pins)
    bodies={};receipts={}
    for pin in pins:
        item=archives[pin['id']]
        body,receipt=legacy._evidence(item['raw'],item['metadata'],pin,now,key)
        run=next(r for r in runs if r['id']==pin['run_id'])
        need(clock(run['run_started_at'])<=clock(body['epoch_started_at'])<=clock(item['metadata']['created_at'])+timedelta(seconds=1) and
             clock(item['metadata']['created_at'])<=clock(run['updated_at'])+timedelta(seconds=1),'PRIOR_RUN_JOURNAL_CLOCK')
        if pin['id']!=legacy.OLD_ARTIFACT:
            continuation._complete(body,item['metadata'],now)
        bodies[pin['id']]=body;receipts[pin['id']]=receipt
    fixed=archives[legacy.OLD_ARTIFACT]
    need(fixed['raw']==data['old_journal_raw'] and fixed['metadata']==data['old_journal_metadata'],
         'SIXTEEN_FIXED_OLD_ARCHIVE_BINDING')
    return bodies,receipts,runs


def _body(data,key,now):
    need(type(data) is dict and set(data)==DATA_FIELDS,'SIXTEEN_ISSUE_FIELDS')
    issued=clock(data['issued_at']);request=validate_request(data['request'],now);target=data['target']
    need(type(target) is dict and set(target)=={'head_sha','run_id','run_attempt'} and
         type(target['run_attempt']) is int and target['run_attempt']==2,'TARGET')
    legacy.capsule_path(request,target['head_sha'],target['run_id'])
    first=legacy.run_receipt(data['first_attempt']);old=legacy.run_receipt(data['old_run'])
    need(first['id']==target['run_id'] and first['head_sha']==target['head_sha'] and first['run_attempt']==1 and
         first['status']=='completed' and first['conclusion']=='success' and clock(first['updated_at'])<=issued,
         'FIRST_ATTEMPT_SUCCESS')
    need(old['id']==legacy.OLD_RUN and old['head_sha']==legacy.OLD_HEAD and old['status']=='completed','OLD_RUN_TERMINAL')
    bodies,receipts,runs=_prior_evidence(data,key,now)
    need(target['run_id'] not in {r['id'] for r in runs} and all(clock(r['updated_at'])<=issued for r in runs),
         'FRESH_SIXTEEN_RUN_AND_PRIOR_CLOCK')
    _plans(request,bodies[legacy.OLD_ARTIFACT],data['old_plan'],data['new_plan'])
    latest=max(*(clock(r['updated_at'])+timedelta(seconds=1) for r in runs),
               *(clock(r['artifact_metadata']['created_at'])+timedelta(seconds=1) for r in receipts.values()))
    before=clock(data['not_before']);expires=clock(data['expires_at']);_window(request,data['issued_at'],data['expires_at'])
    need(latest+timedelta(hours=1)<=before<=issued<=now<expires<=issued+timedelta(hours=1) and
         expires-issued>=timedelta(seconds=600),'SIXTEEN_CLOCK')
    return dict(schema=SCHEMA,state=STATE,request=request,request_sha256=digest(request),target=deepcopy(target),
        issued_at=data['issued_at'],not_before=data['not_before'],expires_at=data['expires_at'],
        old_journal=receipts[legacy.OLD_ARTIFACT],prior_journal_receipts=[receipts[p['id']] for p in request['manifest']['prior_journal_artifacts']],
        old_run=old,prior_runs=runs,first_attempt=first,old_plan=deepcopy(data['old_plan']),new_plan=deepcopy(data['new_plan']),
        latest_possible_old_activity_at=latest.isoformat(),old_source_requests_actual=None,
        old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN',maximum_new_requests=LIMIT,probe_profile=PROFILE)


def issue_consume_capsule(data,key):
    """Pure actual-evidence issuer; performs no fetch/key lookup/publication."""
    need(type(key) is bytes and len(key)==32,'EXPLICIT_OWNER_KEY')
    body=_body(data,key,clock(data['issued_at']))
    return seal_forecasts(dict(schema=SCHEMA,body=body,mac=_mac(body,key)),
        run_id=str(body['target']['run_id']),round_no=ROUND,key=key)


class ValidatedProbe16:
    def __init__(self,body,seal):
        need(seal is _CAPABILITY,'SIXTEEN_CAPABILITY');self._body=deepcopy(body);self._seal=seal
    def audit(self):
        b=self._body
        return dict(schema=SCHEMA,state=STATE,authorization_sha256=digest(b),request_sha256=b['request_sha256'],
            target=deepcopy(b['target']),old_journal=deepcopy(b['old_journal']),old_source_requests_actual=None,
            old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN',maximum_new_requests=LIMIT,probe_profile=PROFILE,
            prior_journal_receipts_sha256=digest(b['prior_journal_receipts']),issued_at=b['issued_at'],
            not_before=b['not_before'],expires_at=b['expires_at'])
    def validate_collector(self,manifest,plan,env,now):
        b=self._body
        need(self._seal is _CAPABILITY,'SIXTEEN_CAPABILITY');validate_request(b['request'],now)
        need(manifest==b['request']['manifest'] and plan==b['new_plan'] and plan['maximum_requests']==LIMIT and
             env['run_id']==b['target']['run_id'] and env['head_sha']==b['target']['head_sha'] and
             max(clock(b['not_before']),clock(b['issued_at']))<=now<clock(b['expires_at']),'SIXTEEN_COLLECTOR_BINDING')
        return self.audit()
    def validate_prior(self,manifest,pin,body,cipher,actual,now):
        b=self._body
        need(self._seal is _CAPABILITY and manifest==b['request']['manifest'] and
             max(clock(b['not_before']),clock(b['issued_at']))<=now<clock(b['expires_at']),'SIXTEEN_HISTORY_SCOPE')
        legacy.no_known_denial(body)
        expected=next(r for r in b['prior_journal_receipts'] if r['pin']['id']==pin['id'])
        need(expected['pin']==pin and expected['artifact_metadata']==actual and
             expected['cipher_sha256']==sha256(cipher).hexdigest() and expected['payload_sha256']==digest(body),
             'SIXTEEN_ORIGINAL_HISTORY_BINDING')
        if pin['id']!=legacy.OLD_ARTIFACT:return False
        _plans(b['request'],body,b['old_plan'],b['new_plan']);return True


def validate_capsule(raw,*,data,current_run,now,key):
    need(type(key) is bytes and len(key)==32,'EXPLICIT_OWNER_KEY');now=clock(now)
    value=open_forecasts(raw,key=key);header=forecast_header(raw)
    need(type(value) is dict and set(value)=={'schema','body','mac'} and value['schema']==SCHEMA and
         type(value['body']) is dict and type(value['mac']) is str and
         hmac.compare_digest(value['mac'],_mac(value['body'],key)),'SIXTEEN_CAPSULE_MAC')
    current=legacy.run_receipt(current_run);expected=_body(data,key,now);target=expected['target']
    need(value['body']==expected and target==dict(run_id=current['id'],head_sha=current['head_sha'],run_attempt=current['run_attempt']) and
         current['run_attempt']==2 and current['status'] in ('in_progress','queued') and
         header['run_id']==str(target['run_id']) and header['round_no']==ROUND,'SIXTEEN_FIXED_ATTEMPT_BINDING')
    return ValidatedProbe16(expected,_CAPABILITY)


def completed_authority(raw,*,request,journal,journal_evidence,oldbody,old_evidence,oldplan,
                        probe_first,prior_runs,prior_journal_receipts,prior_journal_bodies,key):
    """Authenticate a completed original16 grant; never grant a fresh dispatch."""
    from . import all_existing_model_official_continuation as continuation
    value=open_forecasts(raw,key=key);header=forecast_header(raw)
    need(type(value) is dict and set(value)=={'schema','body','mac'} and value['schema']==SCHEMA and
         type(value['body']) is dict and type(value['mac']) is str and
         hmac.compare_digest(value['mac'],_mac(value['body'],key)),'SIXTEEN_ORIGINAL_CAPSULE_MAC')
    b=value['body'];source=validate_request(b['request'],clock(journal['epoch_started_at']))
    pin=journal_evidence['pin'];target=dict(run_id=pin['run_id'],head_sha=pin['head_sha'],run_attempt=2)
    need(b['schema']==SCHEMA and b['state']==STATE and b['probe_profile']==PROFILE and
         type(b['maximum_new_requests']) is int and b['maximum_new_requests']==LIMIT and
         b['request_sha256']==digest(source)==request['probe_request_sha256'] and
         source['probe_sport']==request['probe_sport'] and source['manifest']==journal['manifest'] and
         b['target']==target and header['run_id']==str(target['run_id']) and header['round_no']==ROUND and
         b['old_journal']==old_evidence and b['old_plan']==oldplan and
         b['old_source_requests_actual'] is None and b['old_source_requests_upper_bound']==32 and
         b['old_browser_outcome']=='UNKNOWN','SIXTEEN_ORIGINAL_AUTHORITY_BINDING')
    actual=next(r for r in prior_runs if r['id']==pin['run_id']);first=legacy.run_receipt(probe_first)
    need(actual['status']=='completed' and actual['run_attempt']==2 and actual['head_sha']==target['head_sha'] and
         first==b['first_attempt'] and first['id']==target['run_id'] and first['head_sha']==target['head_sha'] and
         first['run_attempt']==1 and first['status']=='completed' and first['conclusion']=='success',
         'SIXTEEN_COMPLETED_RUN_RECEIPTS')
    expected_runs=[r for r in prior_runs if r['id'] in {p['run_id'] for p in source['manifest']['prior_journal_artifacts']}]
    expected_receipts=[prior_journal_receipts[p['id']] for p in source['manifest']['prior_journal_artifacts']]
    need(b['prior_runs']==expected_runs and b['old_run'] in expected_runs and
         b['prior_journal_receipts']==expected_receipts and target['run_id'] not in {r['id'] for r in expected_runs},
         'SIXTEEN_ALL_ORIGINAL_PRIOR_RECEIPTS')
    for prior in source['manifest']['prior_journal_artifacts']:
        body=prior_journal_bodies[prior['id']];legacy.no_known_denial(body)
        if prior['id']!=legacy.OLD_ARTIFACT:
            continuation._complete(body,prior_journal_receipts[prior['id']]['artifact_metadata'],
                                   clock(b['issued_at']))
    _plans(source,oldbody,oldplan,b['new_plan']);_window(source,b['issued_at'],b['expires_at'])
    need(journal.get('recovery_authorization')==ValidatedProbe16(b,_CAPABILITY).audit(),
         'SIXTEEN_ORIGINAL_JOURNAL_AUTHORITY')
    starts=[journal['epoch_started_at'],journal['browser_attempt']['started_at']]+[
        e['request_started_at'] for e in journal['browser_index']['ledger'] if 'sequence' in e]+[
        c['metadata']['fetched_at'] for c in journal.get('browser_captures',[])]
    latest=max(*(clock(r['updated_at'])+timedelta(seconds=1) for r in expected_runs),
               *(clock(r['artifact_metadata']['created_at'])+timedelta(seconds=1) for r in expected_receipts))
    need(all(max(clock(b['not_before']),clock(b['issued_at']))<=clock(t)<clock(b['expires_at']) for t in starts) and
         clock(b['not_before'])<=clock(b['issued_at'])<clock(b['expires_at'])<=clock(b['issued_at'])+timedelta(hours=1) and
         clock(b['expires_at'])-clock(b['issued_at'])>=timedelta(seconds=600) and
         latest==clock(b['latest_possible_old_activity_at']) and latest+timedelta(hours=1)<=clock(b['not_before']) and
         clock(first['updated_at'])<=clock(b['issued_at']) and
         all(clock(r['updated_at'])<=clock(b['issued_at']) for r in expected_runs),'SIXTEEN_ORIGINAL_WINDOW')
    return dict(cipher_sha256=sha256(raw).hexdigest(),body_sha256=digest(b),request_sha256=b['request_sha256'],
                path=legacy.capsule_path(source,target['head_sha'],target['run_id']),
                probe_profile=PROFILE,maximum_new_requests=LIMIT)
