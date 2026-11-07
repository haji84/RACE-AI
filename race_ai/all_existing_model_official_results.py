"""Authenticated non-BOAT official results joined to frozen native identities.

The caller fetches actual GitHub artifact metadata and authenticates frozen
native inputs first. This pure boundary performs no network, source grant or
model fitting. Raw captures and normalized labels remain private; public
summaries and receipts contain counts and cryptographic identities only.
"""
import base64
from collections import Counter
from copy import deepcopy
from datetime import datetime,timedelta,timezone,date
from hashlib import sha256
import io
import re
import stat
import zipfile
import zlib
from urllib.parse import urlsplit,parse_qsl

from .actions_contract import digest
from . import boat_all_model_store as store
from .boat_pdca_state import state_key
from .existing_model_dispatch import _race_key
from .four_sport_model_suite import ALL_MODELS
from .manual_official_capture import _url,official_rights_ref,validate_source_pair

SCHEMA='RACE_AI_ALL_EXISTING_OFFICIAL_RESULT_ARCHIVE_V1'
COUNTS='RACE_AI_ALL_EXISTING_OFFICIAL_RESULT_COUNTS_V1'
FIELDS={'schema','run_id','code_sha','generated_at','day_jst','captures','observations'}
OBSERVATION_FIELDS={'race_id','sport','status','ordered_top3','roster','identity_verified','captured_at',
    'published_at','source_ref','source_rights_ref','source_sha256','payout_per_100_yen','refund_numbers','closed_at','reason'}
MAX_CAPTURE_BYTES=2_000_000
MAX_TOTAL_CAPTURE_BYTES=16*1024*1024
MAX_MULTI_SOURCE_BYTES=32*1024*1024
AUTO_CONTEXT='RACE_AI_AUTORACE_OFFICIAL_RESULT_CONTEXT_V1'
AUTO_ARCHIVE_CONTEXT='RACE_AI_AUTORACE_OFFICIAL_RESULT_ARCHIVE_CONTEXT_V1'
KEIRIN_ARCHIVE_CONTEXT='RACE_AI_KEIRIN_OFFICIAL_RESULT_ARCHIVE_CONTEXT_V1'
SOURCE_EVIDENCE_SCHEMA='RACE_AI_AUTHENTICATED_RESULT_SOURCE_CLOSURE_V1'
MAX_ARCHIVE_BYTES=store.MAX_WIRE+65536
REPOSITORY_ID=1416489937
JST=timezone(timedelta(hours=9))


def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_OFFICIAL_RESULT_'+reason)


def _time(value):
    try:
        need(type(value) is str and 0<len(value)<=64,'AWARE_CLOCK_REQUIRED')
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        need(parsed.utcoffset() is not None,'AWARE_CLOCK_REQUIRED');return parsed
    except (ValueError,TypeError,AttributeError):
        raise ValueError('ALL_MODEL_OFFICIAL_RESULT_AWARE_CLOCK_REQUIRED') from None


def _now(value):
    need(type(value) is datetime and value.utcoffset() is not None,'AWARE_CLOCK_REQUIRED');return value


def _frozen(values):
    """Structural binding only; the caller owns independent native admission."""
    from . import all_existing_model_registry as registry
    need(type(values) in (tuple,list) and 1<=len(values)<=10000,'FROZEN_NATIVE_INPUTS_REQUIRED')
    known={};fingerprints={}
    for value in values:
        need(type(value) is dict,'FROZEN_NATIVE_PAYLOAD_REQUIRED')
        payload=value.get('native_payload',value)
        need(type(payload) is dict,'FROZEN_NATIVE_PAYLOAD_REQUIRED')
        snapshot=payload.get('snapshot')
        if type(snapshot) is not dict or type(snapshot.get('race')) is not dict:continue
        race=snapshot['race'];sport=race.get('sport')
        if sport not in ('horse','autorace','keirin'):continue
        info=registry.identity(ALL_MODELS[0],sport,payload)
        need(type(info['roster']) is dict and 3<=len(info['roster'])<=18 and
             _time(info['as_of'])<_time(info['race_cutoff_at']),'FROZEN_RACE_CLOCK_OR_ROSTER')
        key=(sport,_race_key(info['race_id'],sport));fingerprint=digest(snapshot)
        need(key not in fingerprints or fingerprints[key]==fingerprint,'CONFLICTING_FROZEN_NATIVE_INPUTS')
        fingerprints[key]=fingerprint;known.setdefault(key,deepcopy(payload))
    need(bool(known),'SUPPORTED_FROZEN_NATIVE_INPUTS_REQUIRED')
    return known,digest(sorted((sport,race,fingerprints[(sport,race)]) for sport,race in fingerprints))


def _nested_raw(encoded,*,maximum=MAX_CAPTURE_BYTES):
    need(type(encoded) is str and 0<len(encoded)<=((maximum+2)//3)*4,'NESTED_CAPTURE_BOUND')
    try:raw=base64.b64decode(encoded,validate=True)
    except (ValueError,UnicodeError):raise ValueError('ALL_MODEL_OFFICIAL_RESULT_NESTED_CAPTURE_BASE64') from None
    need(0<len(raw)<=maximum and base64.b64encode(raw).decode()==encoded,'NESTED_CAPTURE_BASE64')
    return raw


def _nested_http(raw,metadata,generated,*,host,endpoint=None):
    """Authenticate closure bytes and clocks before any result interpretation."""
    need(type(metadata) is dict,'NESTED_HTTP_METADATA')
    url=metadata.get('source_url');sport,actual_host=_url(url)
    validate_source_pair(url,official_rights_ref('autorace'))
    need(sport=='autorace' and (host is None or actual_host==host) and metadata.get('final_url')==url and
         type(metadata.get('status')) is int and metadata['status']==200 and
         type(metadata.get('byte_count')) is int and metadata['byte_count']==len(raw) and
         metadata.get('source_sha256')==sha256(raw).hexdigest() and
         type(metadata.get('headers')) is dict,'NESTED_HTTP_BYTES_OR_SOURCE')
    completed=_time(metadata.get('response_received_at'))
    need(_time(metadata.get('fetched_at'))<=completed<=generated,'NESTED_HTTP_AVAILABILITY_CLOCK')
    if 'source_rights_ref' in metadata:
        need(metadata['source_rights_ref']==official_rights_ref('autorace'),'NESTED_HTTP_RIGHTS')
    if endpoint is not None:
        parts=urlsplit(url)
        need(parts.path=='/race_info/'+endpoint and not parts.query and
             metadata.get('http_method')=='POST' and metadata.get('ui_capture_kind')=='NORMAL_BROWSER_UI' and
             type(metadata.get('request_content_type')) is str and
             metadata['request_content_type'].lower().split(';',1)[0].strip()=='application/json',
             'NORMAL_READONLY_UI_ENDPOINT')
    elif 'http_method' in metadata:
        need(metadata['http_method']=='GET','UNIT_SOURCE_READONLY_GET')
    return completed


def _auto_closure(raw,metadata,generated):
    """Retain actual UI requests, companion HTTP and DOM; grant no source use."""
    _,host=_url(metadata.get('source_url'))
    main_at=_nested_http(raw,metadata,generated,host=host,endpoint='RaceResult')
    context=metadata.get('auto_result_context')
    need(type(context) is dict and set(context)=={'schema','request_body_base64','race_info_capture',
         'rendered_dom_capture'} and context['schema']==AUTO_CONTEXT,'AUTO_CONTEXT_FIELDS')
    request=_nested_raw(context['request_body_base64'],maximum=16384)
    need(metadata.get('request_body_sha256')==sha256(request).hexdigest(),'AUTO_ORIGINAL_REQUEST_BYTES')
    companion=context['race_info_capture']
    need(type(companion) is dict and set(companion)=={'raw_base64','metadata','request_body_base64'},
         'AUTO_COMPANION_FIELDS')
    info=_nested_raw(companion['raw_base64']);info_request=_nested_raw(companion['request_body_base64'],maximum=16384)
    info_at=_nested_http(info,companion['metadata'],generated,host=host,endpoint='OtherRaceInfo')
    need(info_at<=main_at and companion['metadata'].get('request_body_sha256')==sha256(info_request).hexdigest(),
         'AUTO_COMPANION_CLOCK_OR_REQUEST')
    dom=context['rendered_dom_capture']
    need(type(dom) is dict and set(dom)=={'raw_base64','metadata'} and type(dom['metadata']) is dict and
         set(dom['metadata'])=={'source_url','final_url','captured_at','byte_count','source_sha256'},
         'AUTO_DOM_FIELDS')
    body=_nested_raw(dom['raw_base64']);dom_meta=dom['metadata']
    need(_url(dom_meta['source_url'])==('autorace',host) and _url(dom_meta['final_url'])==('autorace',host) and
         type(dom_meta['byte_count']) is int and dom_meta['byte_count']==len(body) and
         dom_meta['source_sha256']==sha256(body).hexdigest() and
         main_at<=_time(dom_meta['captured_at'])<=generated,'AUTO_DOM_BYTES_OR_CLOCK')
    total=len(raw)+len(request)+len(info)+len(info_request)+len(body)
    unit_context=metadata.get('auto_result_archive_context')
    if unit_context is not None:
        need(type(unit_context) is dict and set(unit_context)=={'schema','payout_unit_capture'} and
             unit_context['schema']==AUTO_ARCHIVE_CONTEXT,'AUTO_ARCHIVE_CONTEXT_FIELDS')
        capture=unit_context['payout_unit_capture']
        need(type(capture) is dict and set(capture)=={'raw_base64','metadata'},'AUTO_UNIT_CAPTURE_FIELDS')
        unit=_nested_raw(capture['raw_base64'])
        _nested_http(unit,capture['metadata'],generated,host=None)
        total+=len(unit)
    return total


def _keirin_http(raw,metadata,generated,*,kind=None):
    need(type(metadata) is dict,'KEIRIN_HTTP_METADATA')
    url=metadata.get('source_url');sport,_=_url(url);validate_source_pair(url,official_rights_ref('keirin'))
    need(sport=='keirin' and metadata.get('final_url')==url and metadata.get('method')=='GET' and
         type(metadata.get('status')) is int and metadata['status']==200 and
         type(metadata.get('byte_count')) is int and metadata['byte_count']==len(raw) and
         metadata.get('source_sha256')==sha256(raw).hexdigest() and type(metadata.get('headers')) is dict,
         'KEIRIN_HTTP_BYTES_OR_SOURCE')
    completed=_time(metadata.get('response_received_at'))
    need(_time(metadata.get('fetched_at'))<=completed<=generated,'KEIRIN_HTTP_AVAILABILITY_CLOCK')
    if 'source_rights_ref' in metadata:
        need(metadata['source_rights_ref']==official_rights_ref('keirin'),'KEIRIN_HTTP_RIGHTS')
    if kind is not None:
        parts=urlsplit(url)
        try:query=parse_qsl(parts.query,keep_blank_values=True,max_num_fields=3)
        except ValueError:raise ValueError('ALL_MODEL_OFFICIAL_RESULT_KEIRIN_SELECTOR') from None
        need(parts.path=='/pc/json' and len(query)==2 and len({k for k,_ in query})==2 and
             set(k for k,_ in query)=={'type','encp'} and dict(query)['type']==kind and
             0<len(dict(query)['encp'])<=1024,'KEIRIN_SELECTOR')
        return completed,dict(query)['encp']
    return completed,None


def _keirin_closure(raw,metadata,generated):
    main_at,selector=_keirin_http(raw,metadata,generated,kind='JSJ012')
    context=metadata.get('keirin_result_archive_context')
    need(type(context) is dict and set(context)=={'schema','identity_capture','browser_capture','payout_unit_capture'} and
         context['schema']==KEIRIN_ARCHIVE_CONTEXT,'KEIRIN_CONTEXT_FIELDS')
    identity=context['identity_capture']
    need(type(identity) is dict and set(identity)=={'raw_base64','metadata'},'KEIRIN_IDENTITY_CAPTURE_FIELDS')
    info=_nested_raw(identity['raw_base64'])
    info_at,info_selector=_keirin_http(info,identity['metadata'],generated,kind='JSJ001')
    need(info_at<=main_at and selector==info_selector,'KEIRIN_IDENTITY_CLOCK_OR_SELECTOR')
    browser=context['browser_capture']
    need(type(browser) is dict and set(browser)=={'metadata','rendered_dom_base64'} and
         type(browser['metadata']) is dict,'KEIRIN_BROWSER_CAPTURE_FIELDS')
    dom=_nested_raw(browser['rendered_dom_base64']);proof=browser['metadata'];dom_meta=proof.get('rendered_dom')
    need(proof.get('schema')=='RACE_AI_PRIVATE_OFFICIAL_BROWSER_PROBE_V1' and
         _url(proof.get('source_url'))[0]=='keirin' and proof.get('normal_ui_only') is True and
         proof.get('undocumented_api_manually_called') is False and proof.get('http_access_denied') is False and
         proof.get('entire_host_stopped') is False and proof.get('stop_reason')=='FINISHED' and
         type(proof.get('network_host_allowlist')) is list and
         sorted(proof['network_host_allowlist'])==['keirin.jp','www.keirin.jp'] and
         type(proof.get('ledger')) is list and 1<=len(proof['ledger'])<=2048 and
         type(dom_meta) is dict and set(dom_meta)=={'byte_count','source_sha256'} and
         type(dom_meta['byte_count']) is int and dom_meta['byte_count']==len(dom) and
         dom_meta['source_sha256']==sha256(dom).hexdigest() and
         _time(proof.get('started_at'))<=info_at<=main_at<=_time(proof.get('captured_at'))<=generated,
         'KEIRIN_BROWSER_BYTES_OR_CLOCK')
    total=len(raw)+len(info)+len(dom);unit=context['payout_unit_capture']
    if unit is not None:
        need(type(unit) is dict and set(unit)=={'raw_base64','metadata'},'KEIRIN_UNIT_CAPTURE_FIELDS')
        body=_nested_raw(unit['raw_base64']);_keirin_http(body,unit['metadata'],generated);total+=len(body)
    return total


def _capture(value,generated):
    need(type(value) is dict and set(value)=={'raw_base64','metadata'},'CAPTURE_SCHEMA')
    encoded=value['raw_base64'];metadata=value['metadata']
    need(type(encoded) is str and 0<len(encoded)<=((MAX_CAPTURE_BYTES+2)//3)*4 and
         type(metadata) is dict,'CAPTURE_BOUND')
    try:raw=base64.b64decode(encoded,validate=True)
    except (ValueError,UnicodeError):raise ValueError('ALL_MODEL_OFFICIAL_RESULT_CAPTURE_BASE64') from None
    need(base64.b64encode(raw).decode()==encoded and 0<len(raw)<=MAX_CAPTURE_BYTES,'CAPTURE_BASE64')
    url=metadata.get('source_url');sport,_=_url(url)
    validate_source_pair(url,official_rights_ref(sport))
    need(sport in ('horse','autorace','keirin') and metadata.get('final_url')==url and metadata.get('status')==200 and
         type(metadata.get('byte_count')) is int and metadata['byte_count']==len(raw) and
         metadata.get('source_sha256')==sha256(raw).hexdigest() and type(metadata.get('headers')) is dict,
         'CAPTURE_SOURCE_OR_BYTES')
    completed=_time(metadata.get('response_received_at'));started=_time(metadata.get('fetched_at'))
    need(started<=completed<=generated,'CAPTURE_AVAILABILITY_CLOCK')
    if 'source_rights_ref' in metadata:
        need(metadata['source_rights_ref']==official_rights_ref(sport),'CAPTURE_RIGHTS_MISMATCH')
    total=(_auto_closure(raw,metadata,generated) if sport=='autorace' else
        _keirin_closure(raw,metadata,generated) if sport=='keirin' else len(raw))
    return (sport,url,completed),raw,deepcopy(metadata),total


def _validated(payload,*,now,frozen_native_payloads,allow_order_only=False):
    need(type(allow_order_only) is bool,'EXPLICIT_ORDER_ONLY_MODE')
    need(type(payload) is dict and set(payload)==FIELDS and payload.get('schema')==SCHEMA,'PAYLOAD_SCHEMA')
    need(type(payload['run_id']) is int and 0<payload['run_id']<10**20 and
         type(payload['code_sha']) is str and re.fullmatch('[a-f0-9]{40}',payload['code_sha']),'PAYLOAD_RUN_OR_HEAD')
    now=_now(now);generated=_time(payload['generated_at'])
    need(generated<=now,'PAYLOAD_FROM_FUTURE')
    day=payload['day_jst']
    try:valid_day=type(day) is str and date.fromisoformat(day).isoformat()==day
    except ValueError:valid_day=False
    need(valid_day and date.fromisoformat(day)<=generated.astimezone(JST).date(),'PAYLOAD_DAY')
    captures=payload['captures'];observations=payload['observations']
    need(type(captures) is list and 1<=len(captures)<=32 and type(observations) is list and
         1<=len(observations)<=10000,'BOUNDED_RESULT_CAPTURE_LISTS')
    known,frozen_sha=_frozen(frozen_native_payloads)
    indexed={};total=0
    for capture in captures:
        key,raw,metadata,footprint=_capture(capture,generated);total+=footprint
        need(total<=MAX_MULTI_SOURCE_BYTES,'TOTAL_CAPTURE_BOUND')
        fingerprint=digest(capture)
        need(key not in indexed or indexed[key]['fingerprint']==fingerprint,'CONFLICTING_SOURCE_CAPTURE')
        indexed[key]=dict(raw=raw,metadata=metadata,fingerprint=fingerprint)
    limit=MAX_MULTI_SOURCE_BYTES if any(key[0] in ('autorace','keirin') for key in indexed) else MAX_TOTAL_CAPTURE_BYTES
    need(total<=limit,'TOTAL_CAPTURE_BOUND')
    seen={};used=set();duplicates=0
    for observation in observations:
        from .official_order_only_result import has_order_only_markers,validate_order_only
        order_only=has_order_only_markers(observation)
        if order_only:
            need(allow_order_only,'ORDER_ONLY_RESEARCH_MODE_REQUIRED');validate_order_only(observation)
        need(type(observation) is dict and (order_only or set(observation)==OBSERVATION_FIELDS) and
             observation.get('sport') in ('horse','autorace','keirin') and type(observation.get('race_id')) is str,
             'NORMALIZED_OBSERVATION_SCHEMA')
        sport=observation['sport'];race=_race_key(observation['race_id'],sport)
        native=known.get((sport,race));need(native is not None,'RESULT_WITHOUT_FROZEN_NATIVE_INPUT')
        need(native['snapshot']['race']['event_date_jst']==day,'RESULT_EVENT_DAY')
        captured=_time(observation.get('captured_at'))
        source=(sport,observation.get('source_ref'),captured)
        need(source in indexed,'RESULT_CAPTURE_JOIN')
        source_value=indexed[source];actual=source_value['metadata']
        need(observation.get('source_rights_ref')==official_rights_ref(sport) and
             observation.get('source_sha256')==actual['source_sha256'],'RESULT_SOURCE_BINDING')
        if sport=='horse':
            from .jra_official_result_adapter import parse_result
            replay_at=now
        elif sport=='autorace':
            from .autorace_official_result_adapter import parse_result
            need(observation.get('status')!='settled' or 'auto_result_archive_context' in actual,
                 'AUTO_PAYOUT_UNIT_PROOF_REQUIRED')
            replay_at=generated
        else:
            from .keirin_official_result_adapter import parse_result
            replay_at=generated
        options=dict(allow_order_only=True) if allow_order_only and sport in ('autorace','keirin') else {}
        normalized=parse_result(source_value['raw'],actual,frozen_native_payload=deepcopy(native),
            now=replay_at,source_rights_ref=official_rights_ref(sport),**options)
        need(observation==normalized,'INDEPENDENT_RESULT_REPLAY_MISMATCH')
        used.add(source);key=(sport,race,captured);fingerprint=digest(observation)
        need(key not in seen or seen[key][0]==fingerprint,'CONFLICTING_RESULT_REVISION')
        if key in seen:duplicates+=1
        seen[key]=(fingerprint,deepcopy(observation))
    need(used==set(indexed),'UNREFERENCED_RESULT_CAPTURE')
    latest={}
    for (sport,race,captured),(_,observation) in sorted(seen.items(),key=lambda row:(row[0][2],row[0][0],row[0][1])):
        latest[(sport,race)]=observation
    return [latest[key] for key in sorted(latest)],dict(unique_revision_count=len(seen),
        duplicate_revision_count=duplicates,capture_count=len(indexed),frozen_inputs_sha256=frozen_sha)


def _source_entry(kind,metadata,*,dom=False):
    return dict(kind=kind,source_ref=metadata['source_url'],
        source_rights_ref=official_rights_ref(_url(metadata['source_url'])[0]),
        source_sha256=metadata['source_sha256'],
        captured_at=metadata['captured_at' if dom else 'response_received_at'])


def _result_source_evidence(payload,observation,receipt):
    """Retain source authorization identities outside immutable model inputs."""
    capture=next(c for c in payload['captures'] if c['metadata']['source_url']==observation['source_ref'] and
        c['metadata']['source_sha256']==observation['source_sha256'] and
        _time(c['metadata']['response_received_at'])==_time(observation['captured_at']))
    metadata=capture['metadata'];sport=observation['sport']
    sources=[_source_entry('MAIN_HTTP',metadata)]
    if sport=='autorace':
        context=metadata['auto_result_context']
        sources.extend((_source_entry('IDENTITY_HTTP',context['race_info_capture']['metadata']),
            _source_entry('RENDERED_DOM',context['rendered_dom_capture']['metadata'],dom=True)))
        unit=metadata.get('auto_result_archive_context',{}).get('payout_unit_capture')
    else:
        context=metadata['keirin_result_archive_context']
        browser=context['browser_capture']['metadata']
        dom_meta=dict(source_url=browser['source_url'],captured_at=browser['captured_at'],**browser['rendered_dom'])
        sources.extend((_source_entry('IDENTITY_HTTP',context['identity_capture']['metadata']),
            _source_entry('RENDERED_DOM',dom_meta,dom=True)))
        unit=context['payout_unit_capture']
    if unit is not None:sources.append(_source_entry('PAYOUT_UNIT_HTTP',unit['metadata']))
    return dict(schema=SOURCE_EVIDENCE_SCHEMA,purpose='MODEL_LABEL_NORMALIZATION',
        scope='OWNER_PERSONAL_PRIVATE_FACTUAL_ANALYSIS',provider_permission_confirmed=False,
        generated_at=payload['generated_at'],
        result_observation_sha256=digest(observation),
        result_binding={name:deepcopy(observation[name]) for name in ('sport','race_id','source_ref',
            'source_rights_ref','source_sha256','captured_at')},artifact_receipt=deepcopy(receipt),
        source_closure_sha256=digest(capture),sources=sources)


def verify_result_source_evidence(proof,*,result,now):
    """Recheck retained source closure identities; this never grants a licence.

    Only the authenticated archive reader creates this proof. It is bound in
    the owner's intake MAC and fit lineage; it cannot authenticate raw JSON
    or recreate a missing original artifact by itself.
    """
    fields={'schema','purpose','scope','provider_permission_confirmed','generated_at','result_binding','result_observation_sha256',
        'artifact_receipt','source_closure_sha256','sources'}
    need(type(proof) is dict and set(proof)==fields and proof['schema']==SOURCE_EVIDENCE_SCHEMA and
         proof['purpose']=='MODEL_LABEL_NORMALIZATION' and proof['scope']=='OWNER_PERSONAL_PRIVATE_FACTUAL_ANALYSIS' and
         proof['provider_permission_confirmed'] is False,'SOURCE_EVIDENCE_CONTRACT')
    now=_now(now);binding=proof['result_binding'];receipt=proof['artifact_receipt']
    binding_fields={'sport','race_id','source_ref','source_rights_ref','source_sha256','captured_at'}
    need(type(binding) is dict and set(binding)==binding_fields and binding.get('sport') in ('autorace','keirin') and
         type(result) is dict and binding['sport']==result.get('sport') and
         _race_key(binding['race_id'],binding['sport'])==_race_key(result.get('race_id'),binding['sport']) and
         all(binding[name]==result.get(name) for name in ('source_ref','source_rights_ref','source_sha256')) and
         _time(binding['captured_at'])==_time(result.get('captured_at')) and
         proof['result_observation_sha256']==digest(result),'SOURCE_EVIDENCE_RESULT_BINDING')
    hex64=lambda value:type(value) is str and re.fullmatch('[a-f0-9]{64}',value) is not None
    need(type(receipt) is dict and receipt.get('authenticated_encrypted_result_artifact') is True and
         type(receipt.get('artifact_metadata')) is dict and type(receipt.get('artifact_id')) is int and
         type(receipt.get('workflow_run_id')) is int and 0<receipt['workflow_run_id']<10**20 and
         type(receipt.get('head_sha')) is str and re.fullmatch('[a-f0-9]{40}',receipt['head_sha']) and
         type(receipt.get('digest')) is str and re.fullmatch('sha256:[a-f0-9]{64}',receipt['digest']) and
         all(hex64(receipt.get(name)) for name in ('cipher_sha256','original_payload_sha256',
             'original_journal_sha256','capture_index_sha256','frozen_inputs_sha256')) and
         hex64(proof['source_closure_sha256']),'SOURCE_EVIDENCE_ARTIFACT_RECEIPT')
    metadata=receipt['artifact_metadata'];run=metadata.get('workflow_run')
    name=receipt.get('artifact_name')
    need(type(name) is str and re.fullmatch('all-existing-official-results-'+str(receipt['workflow_run_id'])+
         '-[1-9][0-9]{0,5}',name) and type(metadata.get('id')) is int and metadata['id']==receipt['artifact_id']>0 and
         metadata.get('name')==name and metadata.get('digest')==receipt['digest'] and metadata.get('expired') is False and
         type(metadata.get('size_in_bytes')) is int and 0<metadata['size_in_bytes']<=MAX_ARCHIVE_BYTES and
         type(run) is dict and type(run.get('id')) is int and run['id']==receipt['workflow_run_id'] and
         run.get('head_sha')==receipt['head_sha'] and all(type(run.get(k)) is int and run[k]==REPOSITORY_ID
             for k in ('repository_id','head_repository_id')),'SOURCE_EVIDENCE_ARTIFACT_IDENTITY')
    saved=_time(receipt.get('saved_at'));generated=_time(proof['generated_at'])
    need(saved==_time(metadata.get('created_at')) and _time(receipt.get('expires_at'))==_time(metadata.get('expires_at')) and
         generated<saved+timedelta(seconds=1) and saved<=now<_time(receipt['expires_at']),
         'SOURCE_EVIDENCE_ARTIFACT_CLOCK')
    sources=proof['sources'];need(type(sources) is list and 3<=len(sources)<=4,'SOURCE_EVIDENCE_SOURCES')
    kinds={};pairs=set();sport=binding['sport']
    for source in sources:
        need(type(source) is dict and set(source)=={'kind','source_ref','source_rights_ref','source_sha256','captured_at'} and
             source.get('kind') in ('MAIN_HTTP','IDENTITY_HTTP','RENDERED_DOM','PAYOUT_UNIT_HTTP') and
             source['kind'] not in kinds and _url(source.get('source_ref'))[0]==sport and
             source.get('source_rights_ref')==official_rights_ref(sport) and hex64(source.get('source_sha256')) and
             _time(source.get('captured_at'))<=generated,'SOURCE_EVIDENCE_SOURCE_BINDING')
        validate_source_pair(source['source_ref'],source['source_rights_ref'])
        kinds[source['kind']]=source;pairs.add((source['source_ref'],source['source_rights_ref']))
    need({'MAIN_HTTP','IDENTITY_HTTP','RENDERED_DOM'}<=set(kinds) and
         (result.get('status')!='settled' or 'PAYOUT_UNIT_HTTP' in kinds) and
         all(kinds['MAIN_HTTP'][name]==binding[name] for name in ('source_ref','source_rights_ref','source_sha256')) and
         _time(kinds['MAIN_HTTP']['captured_at'])==_time(binding['captured_at']) and
         _time(kinds['IDENTITY_HTTP']['captured_at'])<=_time(binding['captured_at'])<=
         _time(kinds['RENDERED_DOM']['captured_at']),'SOURCE_EVIDENCE_MAIN_CLOSURE')
    return pairs


def build_result_payload(captures,observations,*,run_id,code_sha,generated_at,day_jst,frozen_native_payloads,
                         allow_order_only=False):
    """Build private normalized originals; creates no external save receipt."""
    if type(generated_at) is datetime:generated_at=_now(generated_at).isoformat()
    need(type(run_id) in (str,int) and type(run_id) is not bool and re.fullmatch('[1-9][0-9]{0,19}',str(run_id)),
         'PAYLOAD_RUN_OR_HEAD')
    payload=dict(schema=SCHEMA,run_id=int(run_id),code_sha=code_sha,generated_at=generated_at,
        day_jst=day_jst,captures=deepcopy(captures),observations=deepcopy(observations))
    _validated(payload,now=_time(generated_at),frozen_native_payloads=frozen_native_payloads,allow_order_only=allow_order_only)
    return payload


def seal_results(payload,*,round_no,frozen_native_payloads,key=None,allow_order_only=False):
    """Return only results.enc bytes for the existing artifact uploader."""
    state_key('production',key)
    need(type(payload) is dict,'PAYLOAD_SCHEMA')
    need(type(round_no) is int and 1<=round_no<=999999,'POSITIVE_ROUND_REQUIRED')
    _validated(payload,now=_time(payload.get('generated_at')),frozen_native_payloads=frozen_native_payloads,
        allow_order_only=allow_order_only)
    return store.seal_forecasts(payload,run_id=str(payload['run_id']),round_no=round_no,key=key)


def _metadata(raw,metadata,now,run_id,head):
    need(type(run_id) is int and 0<run_id<10**20 and type(head) is str and re.fullmatch('[a-f0-9]{40}',head),
         'EXPECTED_RUN_IDENTITY')
    need(type(raw) is bytes and 0<len(raw)<=MAX_ARCHIVE_BYTES and type(metadata) is dict and
         type(metadata.get('id')) is int and metadata['id']>0 and metadata.get('expired') is False,'ARTIFACT_IDENTITY')
    name=metadata.get('name');match=re.fullmatch('all-existing-official-results-'+str(run_id)+'-([1-9][0-9]{0,5})',
        name) if type(name) is str else None
    run=metadata.get('workflow_run')
    need(match is not None and type(run) is dict and type(run.get('id')) is int and run['id']==run_id and
         run.get('head_sha')==head and all(type(run.get(k)) is int and run[k]==REPOSITORY_ID
             for k in ('repository_id','head_repository_id')),'ARTIFACT_RUN_OR_NAME')
    need(type(metadata.get('size_in_bytes')) is int and metadata['size_in_bytes']==len(raw) and
         metadata.get('digest')=='sha256:'+sha256(raw).hexdigest(),'ARTIFACT_BYTES')
    saved=_time(metadata.get('created_at'))
    need(saved<=now<_time(metadata.get('expires_at')),'ARTIFACT_CLOCK_OR_EXPIRY')
    return saved,int(match[1])


def _cipher(raw):
    need(raw.startswith(b'PK\x03\x04') and len(raw)>=22 and raw[-22:-18]==b'PK\x05\x06' and raw[-2:]==b'\0\0',
         'ZIP_ENVELOPE')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist();need(len(entries)==1 and not archive.comment,'ZIP_EXACT_CIPHER')
            entry=entries[0]
            need(entry.filename==entry.orig_filename=='results.enc' and
                 stat.S_IFMT(entry.external_attr>>16) in (0,stat.S_IFREG) and
                 0<entry.file_size<=store.MAX_WIRE and not entry.flag_bits&0x41 and
                 entry.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED),'ZIP_EXACT_CIPHER')
            with archive.open(entry) as source:cipher=source.read(store.MAX_WIRE+1)
            need(len(cipher)==entry.file_size,'ZIP_CIPHER_SIZE');return cipher
    except (zipfile.BadZipFile,RuntimeError,NotImplementedError,EOFError,zlib.error) as exc:
        raise ValueError('ALL_MODEL_OFFICIAL_RESULT_ZIP_REJECTED') from exc


def observations_from_official_result_artifact(raw,metadata,*,now,expected_run_id,expected_head_sha,
                                               frozen_native_payloads,key=None,allow_order_only=False):
    """Authenticate actual ciphertext/save proof, then independently replay labels.

    ``metadata`` must be freshly fetched from the actual GitHub endpoint by the
    caller. ``frozen_native_payloads`` must already have independent encrypted
    input-artifact admission. A local JSON flag grants neither source identity
    nor a pre-cutoff receipt. Expired artifacts are never refreshed here.
    """
    state_key('production',key);now=_now(now)
    saved,round_no=_metadata(raw,metadata,now,expected_run_id,expected_head_sha)
    cipher=_cipher(raw);payload=store.open_forecasts(cipher,key=key);header=store.forecast_header(cipher)
    need(header['run_id']==str(expected_run_id) and header['round_no']==round_no and
         payload.get('run_id')==expected_run_id and payload.get('code_sha')==expected_head_sha,
         'AUTHENTICATED_HEADER_BINDING')
    generated=_time(payload.get('generated_at'))
    need(generated<saved+timedelta(seconds=1),'PAYLOAD_AFTER_SERVER_SAVE')
    observations,details=_validated(payload,now=now,frozen_native_payloads=frozen_native_payloads,
        allow_order_only=allow_order_only)
    counts=Counter(row['status'] for row in observations)
    need(set(counts)<=set(('settled','pending','special','rank_confirmed')),'NORMALIZED_RESULT_STATUS')
    receipt=dict(artifact_id=metadata['id'],artifact_name=metadata['name'],digest=metadata['digest'],
        workflow_run_id=expected_run_id,head_sha=expected_head_sha,saved_at=metadata['created_at'],
        expires_at=metadata['expires_at'],artifact_metadata=deepcopy(metadata),
        cipher_sha256=sha256(cipher).hexdigest(),original_payload_sha256=digest(payload),
        original_journal_sha256=digest(payload['observations']),capture_index_sha256=digest(payload['captures']),
        frozen_inputs_sha256=details['frozen_inputs_sha256'],authenticated_encrypted_result_artifact=True)
    summary=dict(schema=COUNTS,state='AUTHENTICATED_OFFICIAL_RESULT_OBSERVATIONS_READY',
        artifact_id=metadata['id'],artifact_digest=metadata['digest'],workflow_run_id=expected_run_id,
        head_sha=expected_head_sha,original_observation_count=len(payload['observations']),
        latest_observation_count=len(observations),unique_revision_count=details['unique_revision_count'],
        duplicate_revision_count=details['duplicate_revision_count'],capture_count=details['capture_count'],
        ordinary_settled_result_count=counts['settled'],pending_result_count=counts['pending'],
        special_result_count=counts['special'],authenticated_encrypted_result_artifact=True,
        missing_results_are_not_losses=True,provider_permission_confirmed=False,
        production_promoted=False,actual_purchases=False,plaintext_published=False)
    if counts['rank_confirmed']:
        from .official_order_only_result import EVALUATION_SCOPE
        summary.update(order_only_confirmed_result_count=counts['rank_confirmed'],
            label_evaluation_scope=EVALUATION_SCOPE,monetary_evaluation_available=False)
    out=dict(observations=observations,summary=summary,receipt=receipt)
    supplemental=[_result_source_evidence(payload,observation,receipt) for observation in observations
        if observation['sport'] in ('autorace','keirin')]
    if supplemental:
        for observation,proof in zip((o for o in observations if o['sport'] in ('autorace','keirin')),supplemental):
            verify_result_source_evidence(proof,result=observation,now=now)
        out['result_source_evidence']=supplemental
    return out
