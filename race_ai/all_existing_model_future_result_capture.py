"""Explicit first forward RESULT purpose; no source or credential lookup.

Legacy recovery authority types and their old-day cases remain unchanged.
Thirty-two is a local combined wire bound, not a provider quota.
"""
from copy import deepcopy
from datetime import date,timedelta
from hashlib import sha256
import hmac
import re
from urllib.parse import urlsplit

from .actions_contract import digest
from . import all_existing_model_registry as registry
from . import all_existing_model_future_source_capture as history_core
from . import manual_official_capture as policy
from .all_existing_model_future_baseline import validate_pin
from .all_existing_model_receipt import _verified_private_pairs_artifact
from .all_existing_model_cash_pdca_origin import verify_origin_artifact
from .all_existing_model_official_issue_transport import GithubIssueTransport
from .boat_all_model_store import seal_forecasts,open_forecasts,forecast_header,MAX_WIRE
from .existing_model_dispatch import _race_key
from .all_existing_model_future_batches import admit_batch_origins as admit_forecast_batches,validate_forecast_batches

SCHEMA='RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_INPUT_V1'
SCHEMA_V2='RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_INPUT_V2'
JOURNAL='RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_JOURNAL_V1'
JOURNAL_V2='RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_JOURNAL_V2'
STATUS='RACE_AI_ALL_NATIVE_FUTURE_RESULT_CAPTURE_COUNTS_V1'
ONCE='RACE_AI_ALL_NATIVE_FUTURE_RESULT_ONCE_V1'
PURPOSE='ALL_THIRTY_FIRST_FORWARD_RESULTS_V1'
PATH='future-result/all-thirty-first-forward-cycle-v1/official/consumed.enc'
DOMAIN=b'RACE_AI_ALL_NATIVE_FUTURE_RESULT_ONCE_MAC_V1'
ROUND=900028
ONCE_ROUND=900029
RESULT_ROUND=900030
SPORTS={'autorace','keirin','horse'}
clock=history_core.clock


def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_FUTURE_RESULT_'+reason)


def validate_manifest(value,*,now):
    now=clock(now);fields={'schema','execution_day','target_event_day','forecast_artifact','origin_artifact',
        'cases','terms_manifest','prior_journal_artifacts','maximum_requests','allow_order_only'}
    need(type(value) is dict and (set(value)==fields and value.get('schema')==SCHEMA or
        set(value)==fields-{'forecast_artifact','origin_artifact'}|{'forecast_batches'} and value.get('schema')==SCHEMA_V2) and
        value['execution_day']==now.astimezone(policy.JST).date().isoformat() and
        type(value['maximum_requests']) is int and value['maximum_requests']==32 and
        value['allow_order_only'] is True,'MANIFEST_SCHEMA_DAY_OR_BOUND')
    target=date.fromisoformat(value['target_event_day']);execution=date.fromisoformat(value['execution_day'])
    need(0<=(execution-target).days<=7,'TARGET_EVENT_DAY')
    if value['schema']==SCHEMA_V2:validate_forecast_batches(value['forecast_batches'])
    else:
        for name in ('forecast_artifact','origin_artifact'):validate_pin(value[name])
        need(value['forecast_artifact']['id']!=value['origin_artifact']['id'] and
            all(value['forecast_artifact'][k]==value['origin_artifact'][k] for k in ('run_id','head_sha')),
            'FORECAST_ORIGIN_PINS')
    from scripts.all_existing_model_official_result_collect import _pins
    _pins(value['prior_journal_artifacts'])
    cases=value['cases'];need(type(cases) is list and len(cases)==3 and
        {c.get('sport') for c in cases if type(c) is dict}==SPORTS,'EXACT_THREE_CASES')
    urls=[]
    for case in cases:
        need(type(case) is dict and set(case)=={'sport','race_id','route'},'CASE_SCHEMA')
        sport=case['sport'];key=_race_key(case['race_id'],sport);route=case['route']
        need(type(route) is dict and key.startswith(sport+':'+value['target_event_day']+':'),'CASE_EVENT_DAY')
        if sport=='horse':
            need(set(route)=={'kind','card_url'} and route['kind']=='JRA_CARD_PUBLISHED_GET','HORSE_ROUTE')
            url=route['card_url'];parts=urlsplit(url)
            need(parts.hostname=='www.jra.go.jp' and parts.path=='/JRADB/accessD.html' and
                not parts.fragment,'HORSE_LITERAL_CARD')
            from .official_future_horse_result import _url_identity
            venue,year,_,_,number,day=_url_identity(url,'dde')
            need(key==f'horse:{day[:4]}-{day[4:6]}-{day[6:]}:jra-{venue}:{int(number)}' and
                year==day[:4],'HORSE_CARD_CASE')
        else:
            need({'kind','ui_entry_url','ui_venue_name'}<=set(route)<=
                {'kind','ui_entry_url','ui_venue_name','place_code'} and route['kind']=='NORMAL_UI','NORMAL_UI_ROUTE')
            url=route['ui_entry_url'];parts=urlsplit(url);venue=key.split(':')[2]
            need(not parts.query and not parts.fragment and parts.path==(
                '/race_info/Live/'+venue if sport=='autorace' else '/pc/top'),'PUBLISHED_NORMAL_UI')
            need(venue in ('isesaki','kawaguchi','hamamatsu','iizuka','sanyou') if sport=='autorace' else
                re.fullmatch('keirin-jyo-[0-9]{2}',venue),'KNOWN_VENUE')
            name=route['ui_venue_name'];need(name is None or type(name) is str and 0<len(name)<=80 and
                not re.search('[<>\r\n]',name),'UI_VENUE_NAME')
            if 'place_code' in route:need(sport=='autorace' and type(route['place_code']) is int and
                1<=route['place_code']<=20,'ACTUAL_PLACE_CODE')
        policy.validate_source_pair(url,policy.official_rights_ref(sport));urls.append(url)
    terms=value['terms_manifest'];all_urls=[u for term in terms['terms'] for u in term['source_urls']]
    policy._terms(terms,all_urls,value['execution_day'],now)
    need({t['sport'] for t in terms['terms']}==SPORTS and set(urls)==set(all_urls),'EXACT_TERMS_SPORTS')
    return deepcopy(value)


def _pin_metadata(pin,metadata):
    run=metadata.get('workflow_run',{})
    need((metadata.get('id'),metadata.get('digest'),run.get('id'),run.get('head_sha'))==
        (pin['id'],pin['digest'],pin['run_id'],pin['head_sha']),'ACTUAL_PIN')


def admit_forecast(manifest,*,forecast_raw=None,forecast_metadata=None,origin_raw=None,origin_metadata=None,
                   batch_archives=None,now,key,manifest_at=None):
    """Authenticate immutable saved thirty-cell forecast/origin before source I/O."""
    now=clock(now);validate_manifest(manifest,now=clock(manifest_at) if manifest_at is not None else now)
    if manifest['schema']==SCHEMA_V2:
        need(all(value is None for value in (forecast_raw,forecast_metadata,origin_raw,origin_metadata)),
             'NO_SINGLE_ORIGIN_WITH_BATCHES')
        union=admit_forecast_batches(manifest['forecast_batches'],batch_archives,now=now,key=key)
        records=union['records'];bysport,joined=_join_cases(manifest,records,now)
        identities=[dict(forecast_artifact=deepcopy(archive['future']['metadata']),
            origin_artifact=deepcopy(archive['origin']['metadata']),forecast_receipt=deepcopy(batch['admission']),
            origin_summary=deepcopy(batch['origin']['summary']),record_sha256=sorted(digest(r) for r in batch['records']))
            for archive,batch in zip(batch_archives,union['batches'],strict=True)]
        identity=dict(schema='RACE_AI_FORWARD_MULTI_ORIGIN_IDENTITY_V1',atomic_all_thirty_origin=False,
            candidate_context_sha256=union['candidate_context_sha256'],training_sha256=union['training_sha256'],
            candidate_receipt=deepcopy(union['candidate_receipt']),owner_record_sha256=union['owner_record_sha256'],
            forecast_counts_by_sport=deepcopy(union['forecast_counts_by_sport']),forecast_batches=identities,
            record_sha256=sorted(digest(r) for r in records))
        return dict(batch_contexts=union['batches'],records=records,natives=list(bysport.values()),cases=joined,
            source_input_artifacts=deepcopy(union['source_input_artifacts']),forecast_identity=identity)
    need(batch_archives is None,'NO_BATCHES_WITH_SINGLE_ORIGIN')
    _pin_metadata(manifest['forecast_artifact'],forecast_metadata);_pin_metadata(manifest['origin_artifact'],origin_metadata)
    pin=manifest['forecast_artifact']
    admission,records=_verified_private_pairs_artifact(forecast_raw,forecast_metadata,now=now,
        expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'],key=key)
    origin=verify_origin_artifact(origin_raw,origin_metadata,forecast_raw,forecast_metadata,admission,records,
        now=now,candidate_cell_count=30)
    expected={'boat':14,'autorace':6,'keirin':5,'horse':5};summary=origin['summary']
    need(summary['all_candidate_cells_produced'] is True and summary['forecast_partition_count']==30 and
        summary['forecast_counts_by_sport']==expected and not origin['generation']['held_sports'],
        'COMPLETE_THIRTY_FORECAST_REQUIRED')
    bysport,joined=_join_cases(manifest,records,now)
    identity=dict(forecast_artifact=deepcopy(forecast_metadata),origin_artifact=deepcopy(origin_metadata),
        forecast_receipt=deepcopy(admission),origin_summary=deepcopy(summary),
        record_sha256=sorted(digest(r) for r in records))
    return dict(forecast_admission=admission,records=records,origin=origin,natives=list(bysport.values()),
        cases=joined,source_input_artifacts=deepcopy(origin['manifest']['source_input_artifacts']),forecast_identity=identity)


def _join_cases(manifest,records,now):
    bysport={}
    from .four_sport_model_suite import ALL_MODELS
    for record in records:
        sport,mid=record['cell_key'].split('/',1);info=registry.identity(mid,sport,record['native_payload'])
        need(_race_key(info['race_id'],sport).split(':')[1]==manifest['target_event_day'],'FORECAST_TARGET_DAY')
        if sport in SPORTS and mid==ALL_MODELS[0]:bysport[sport]=record['native_payload']
    joined=[]
    for case in manifest['cases']:
        sport=case['sport'];native=bysport[sport]
        info=registry.identity(ALL_MODELS[0],sport,native)
        need(_race_key(case['race_id'],sport)==_race_key(info['race_id'],sport),'FORECAST_CASE_BINDING')
        need(clock(info['race_cutoff_at'])+timedelta(seconds=120)<=now,'ORIGINAL_FORECAST_NOT_DUE')
        joined.append(dict(case=deepcopy(case),native_payload=deepcopy(native),identity=deepcopy(info)))
    return bysport,joined


def admit_native_sources(admitted,archives,*,now,key):
    """Independently replay every source-input pin and join its original capsules."""
    pins=admitted['source_input_artifacts'];need(type(archives) is list and len(archives)==len(pins),'SOURCE_ARCHIVES')
    known={a['metadata']['id']:a for a in archives};need(len(known)==len(pins),'SOURCE_ARCHIVE_DUPLICATE')
    originals=[];bindings=[]
    for pin in pins:
        item=known.get(pin['id']);need(item is not None,'SOURCE_ARCHIVE_MISSING');_pin_metadata(pin,item['metadata'])
        receipt,rows=_verified_private_pairs_artifact(item['raw'],item['metadata'],now=now,
            expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'],key=key)
        origins=[batch['origin'] for batch in admitted['batch_contexts']] if 'batch_contexts' in admitted else [admitted['origin']]
        audits=[a for origin in origins for a in origin['source_audit']['source_admissions'] if a['artifact_id']==pin['id']]
        need(bool(audits) and all(receipt['artifact_digest']==audit['artifact_digest'] and receipt['saved_at']==audit['saved_at'] and
            sorted(receipt['record_sha256'])==sorted(audit['record_sha256']) for audit in audits),'SOURCE_ACTUAL_RECEIPT')
        capsules=[c for row in rows for c in row.get('captured_native_inputs',[])]
        originals.extend(capsules)
        bindings.append(dict(pin=deepcopy(pin),receipt=deepcopy(receipt),
            sports=sorted({c['cell_key'].split('/',1)[0] for c in capsules})))
    for record in admitted['records']:
        need(any(c['cell_key']==record['cell_key'] and c['input_sha256']==digest(record['native_payload']) and
            c['native_payload']==record['native_payload'] for c in originals),'ORIGINAL_NATIVE_CAPSULE_REQUIRED')
    return dict(source_input_artifact_count=len(pins),source_input_receipts_verified=True,
        source_input_pins_sha256=digest(pins),source_native_bindings=bindings)


def bind_source_history(admitted,proof,history):
    """A fresh-source epoch may not be omitted from its own native-input chain."""
    covered=set()
    for binding in proof['source_native_bindings']:
        sports=set(binding['sports'])&SPORTS
        if not sports:continue
        need(sports in ({'autorace','keirin'},{'horse'}),'EXACT_FUTURE_SOURCE_SPORTS')
        pin=binding['pin'];matches=[(ident,b) for ident,b in history['bodies'].items() if
            b.get('workflow_run_id')==pin['run_id'] and b.get('code_sha')==pin['head_sha'] and
            b.get('schema')==('RACE_AI_JRA_FUTURE_SOURCE_JOURNAL_V1' if sports=={'horse'} else
                history_core.JOURNAL)]
        need(len(matches)==1,'ACTUAL_FUTURE_SOURCE_HISTORY_REQUIRED')
        ident,body=matches[0];generation=body.get('native_generation',{});receipt=binding['receipt']
        need(body.get('native_ready') is True and type(body.get('once_proof')) is dict and
            generation.get('record_sha256')==sorted(receipt['record_sha256']) and
            generation.get('workflow_run_id')==pin['run_id'] and generation.get('expected_head_sha')==pin['head_sha'] and
            receipt['artifact_name']==f'all-existing-model-pairs-{pin["run_id"]}-{900002 if sports=={"horse"} else 900003}',
            'ACTUAL_FUTURE_NATIVE_GENERATION_BINDING')
        saved=clock(history['receipts'][ident]['artifact_metadata']['created_at'])
        for item in admitted['cases']:
            if item['case']['sport'] in sports:
                need(saved+timedelta(seconds=601)<clock(item['identity']['race_cutoff_at']),
                    'ORIGINAL_FUTURE_SOURCE_SAVE_MARGIN')
                need(clock(item['identity']['as_of'])==clock(body['fixed_as_of']),'ORIGINAL_FIXED_ASOF')
        covered|=sports
    need(covered==SPORTS,'ALL_FUTURE_SOURCE_HISTORY_REQUIRED')
    return dict(authenticated_future_source_sports=sorted(covered),original_future_source_journals_joined=True)


def prepare_plan(manifest,admitted,*,now,expires_at,static_cache=None):
    now=clock(now);validate_manifest(manifest,now=now);expires=clock(expires_at);cases=[]
    midnight=now.astimezone(policy.JST).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
    need(now+timedelta(seconds=100)<=expires<=min(now+timedelta(hours=1),midnight),'CAPTURE_WINDOW')
    for item in admitted['cases']:
        case=item['case'];sport=case['sport'];info=item['identity'];key=_race_key(info['race_id'],sport)
        need(clock(info['race_cutoff_at'])+timedelta(seconds=120)<=now,'ORIGINAL_FORECAST_NOT_DUE')
        if sport=='horse':continue
        route=case['route'];part=key.split(':')
        value=dict(sport=sport,race_id=key,ui_entry_url=route['ui_entry_url'],expected_date=part[1],
            venue=part[2],race_no=int(part[3]),due_at=info['race_cutoff_at'])
        for name in ('ui_venue_name','place_code'):
            if route.get(name) is not None:value[name]=route[name]
        cases.append(value)
    plan=dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_PLAN_V1',cases=cases,request_budget=30,
        not_before=now.isoformat(),not_after=expires.isoformat())
    if static_cache:plan['static_cache']=deepcopy(static_cache)
    return plan


class MarkerTransport(GithubIssueTransport):
    @staticmethod
    def _validate_path(path):need(path==PATH,'CANONICAL_RESULT_ONCE_PATH')
    _commit_message='Retain consumed first all-model forward RESULT reservation'


ONCE_FIELDS={'schema','purpose','marker_path','state','target','repository_id','pull_request','issued_at','expires_at',
    'execution_day','manifest_sha256','forecast_identity_sha256','history_sha256','plan_sha256',
    'source_requests_actual','source_request_upper_bound','old_source_requests_actual','old_source_requests_upper_bound','old_browser_outcome'}


def marker_body(manifest,env,admitted,history,plan,*,now):
    now=clock(now)
    return dict(schema=ONCE,purpose=PURPOSE,marker_path=PATH,state='CONSUMED_BEFORE_DISPATCH',
        target={k:env[k] for k in ('run_id','head_sha','run_attempt')},repository_id=1416489937,pull_request=71,
        issued_at=now.isoformat(),expires_at=plan['not_after'],execution_day=manifest['execution_day'],
        manifest_sha256=digest(manifest),forecast_identity_sha256=digest(admitted['forecast_identity']),
        history_sha256=digest({k:v for k,v in history.items() if k not in ('bodies','receipts','runs')}),plan_sha256=digest(plan),
        source_requests_actual=None,source_request_upper_bound=32,old_source_requests_actual=None,
        old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN')


def _validate_body(body):
    need(type(body) is dict and set(body)==ONCE_FIELDS and body['schema']==ONCE and body['purpose']==PURPOSE and
        body['marker_path']==PATH and body['state']=='CONSUMED_BEFORE_DISPATCH' and
        type(body['repository_id']) is int and body['repository_id']==1416489937 and body['pull_request']==71,'ONCE_SCOPE')
    target=body['target'];need(type(target) is dict and set(target)=={'run_id','head_sha','run_attempt'} and
        type(target['run_id']) is int and target['run_id']>0 and type(target['run_attempt']) is int and target['run_attempt']==1 and
        type(target['head_sha']) is str and re.fullmatch('[a-f0-9]{40}',target['head_sha']),'ONCE_TARGET')
    issued=clock(body['issued_at']);expires=clock(body['expires_at']);midnight=issued.astimezone(policy.JST).replace(
        hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
    need(body['execution_day']==issued.astimezone(policy.JST).date().isoformat() and
        issued+timedelta(seconds=100)<=expires<=min(issued+timedelta(hours=1),midnight) and
        body['source_requests_actual'] is None and type(body['source_request_upper_bound']) is int and
        body['source_request_upper_bound']==32 and body['old_source_requests_actual'] is None and
        type(body['old_source_requests_upper_bound']) is int and body['old_source_requests_upper_bound']==32 and
        body['old_browser_outcome']=='UNKNOWN','ONCE_CLOCK_OR_COUNT')
    need(all(type(body[k]) is str and re.fullmatch('[a-f0-9]{64}',body[k]) for k in
        ('manifest_sha256','forecast_identity_sha256','history_sha256','plan_sha256')),'ONCE_HASH')


def _mac(body,key):
    need(type(key) is bytes and len(key)==32,'EXPLICIT_KEY')
    return hmac.digest(hmac.digest(key,DOMAIN,'sha256'),digest(body).encode(),'sha256').hex()


def issue_marker(body,key):
    _validate_body(body)
    return seal_forecasts(dict(schema=ONCE,body=deepcopy(body),mac=_mac(body,key)),
        run_id=str(body['target']['run_id']),round_no=ONCE_ROUND,key=key)


def validate_marker(raw,body,key,*,now):
    _validate_body(body);value=open_forecasts(raw,key=key);header=forecast_header(raw)
    need(type(value) is dict and set(value)=={'schema','body','mac'} and value['schema']==ONCE and value['body']==body and
        hmac.compare_digest(value['mac'],_mac(body,key)) and header['round_no']==ONCE_ROUND and
        header['run_id']==str(body['target']['run_id']) and clock(body['issued_at'])<=now<clock(body['expires_at']),
        'AUTHENTICATED_RESULT_ONCE')
    return dict(marker_path=PATH,authorization_sha256=digest(body),marker_cipher_sha256=sha256(raw).hexdigest(),
        issued_at=body['issued_at'],expires_at=body['expires_at'],source_request_upper_bound=32)


def reserve(body,key,transport,*,now):
    parent=transport.head();need(transport.read_file(parent,PATH,MAX_WIRE) is None,'ONCE_ALREADY_CONSUMED')
    raw=issue_marker(body,key);validate_marker(raw,body,key,now=now)
    commit=transport.publish_capsule(PATH,raw,parent);actual=transport.read_file(commit,PATH,MAX_WIRE)
    need(actual==raw,'ONCE_ACTUAL_READBACK_BYTES')
    return dict(validate_marker(actual,body,key,now=now),commit_sha=commit,_ciphertext=raw)
