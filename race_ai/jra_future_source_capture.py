"""One literal event-morning JRA card and a separate consumed MAC scope."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from html.parser import HTMLParser
import hmac
import re
from urllib.parse import parse_qs,urljoin,urlsplit

from .actions_contract import digest
from . import manual_official_capture as capture
from . import jra_official_sparse_adapter as jra
from .jra_capture_metadata import build_jra_http_metadata
from .all_existing_model_future_baseline import validate_pin
from .all_existing_model_official_issue_transport import GithubIssueTransport
from .boat_all_model_store import seal_forecasts,open_forecasts,forecast_header,MAX_WIRE
from .four_sport_learning import LEARNED_ID

SCHEMA='RACE_AI_JRA_FUTURE_SOURCE_CAPTURE_INPUT_V1'
JOURNAL='RACE_AI_JRA_FUTURE_SOURCE_JOURNAL_V1'
STATUS='RACE_AI_JRA_FUTURE_SOURCE_CAPTURE_COUNTS_V1'
PATH='future-source/all-thirty-first-forward-cycle-v1/horse/consumed.enc'
ONCE='RACE_AI_JRA_FUTURE_SOURCE_ONCE_V1'
DOMAIN=b'RACE_AI_JRA_FUTURE_SOURCE_ONCE_MAC_V1'
ROUND=900027
clock=capture._time


def need(ok,reason):
    if not ok:raise ValueError('JRA_FUTURE_SOURCE_'+reason)


def validate_manifest(value,*,now):
    day=now.astimezone(jra.JST).date().isoformat()
    fields={'schema','execution_day','discovery_url','card_url','rule_url','race_id','cutoff_at','terms_manifest',
        'maximum_requests','horse_baseline_artifact','carrier_artifact','excluded_native_artifacts','prior_journal_artifacts'}
    need(type(value) is dict and set(value)==fields and value['schema']==SCHEMA and value['execution_day']==day and
        type(value['maximum_requests']) is int and value['maximum_requests']==32,'MANIFEST_SCHEMA_DAY_OR_BOUND')
    urls=[value[k] for k in ('discovery_url','card_url','rule_url')]
    need(len(set(urls))==3 and value['rule_url']==jra.RULE_URL,'EXACT_THREE_PUBLIC_SOURCES')
    for url in urls:
        capture.validate_source_pair(url,capture.official_rights_ref('horse'));parts=urlsplit(url)
        need(parts.hostname=='www.jra.go.jp','SINGLE_PUBLISHED_HOST')
        need(parts.port is None and not re.search(r'login|logout|account|password|vote|purchase',parts.path,re.I),
            'PUBLIC_LITERAL_URL')
    parsed=urlsplit(value['card_url']);query=parse_qs(parsed.query,keep_blank_values=True)
    identity=re.fullmatch(r'pw01dde01(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/[A-Fa-f0-9]{2}',query.get('CNAME',[''])[0])
    need(parsed.path=='/JRADB/accessD.html' and set(query)=={'CNAME'} and len(query['CNAME'])==1 and identity and
        identity[2]==day[:4] and identity[6]==day.replace('-','') and identity[1] in jra.VENUES.values() and
        1<=int(identity[5])<=12 and value['race_id']==f'horse:{day}:jra-{identity[1]}:{int(identity[5])}',
        'LITERAL_CARD_IDENTITY')
    cutoff=clock(value['cutoff_at'])
    need(cutoff.astimezone(jra.JST).date().isoformat()==day and now+timedelta(seconds=600)<cutoff,'FUTURE_MARGIN')
    baseline=validate_pin(value['horse_baseline_artifact']);carrier=validate_pin(value['carrier_artifact'])
    need(baseline['id']!=carrier['id'],'DISTINCT_CARRIER')
    from scripts.all_existing_model_official_freeze import _exclusion_pins,V3_SCHEMA
    _exclusion_pins(dict(value,schema=V3_SCHEMA))
    from scripts.all_existing_model_official_result_collect import _pins
    _pins(value['prior_journal_artifacts'])
    need(not {baseline['id'],carrier['id']}&{p['id'] for p in value['prior_journal_artifacts']},'DISTINCT_HISTORY')
    capture._terms(value['terms_manifest'],urls,day,now)
    need(len(value['terms_manifest']['terms'])==1 and value['terms_manifest']['terms'][0]['sport']=='horse' and
        set(value['terms_manifest']['terms'][0]['source_urls'])==set(urls),'EXACT_HORSE_TERMS')
    return deepcopy(value)


def prepare(manifest,baseline,*,now):
    validate_manifest(manifest,now=now)
    training=baseline['training'];model=training['models'].get('horse/'+LEARNED_ID)
    need(training['scope']=='OPERATOR_SUPPLIED_RESEARCH' and len(training['models'])==30 and type(model) is dict and
        model['sport']==model['native_training']['sport']=='horse','ACTUAL_THIRTY_HORSE_BASELINE')
    need(model.get('input_schema')==model['native_training'].get('input_schema')==jra.native.SCHEMA_SPARSE,
        'MATCHING_SPARSE_HORSE_RANKER')
    ready=clock(baseline['receipt']['created_at'])+timedelta(seconds=1);created=clock(model['native_training']['created_at'])
    need(ready<=now and created<now,'BASELINE_AVAILABILITY')
    midnight=now.astimezone(jra.JST).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
    expires=min(now+timedelta(hours=1),midnight,clock(manifest['cutoff_at'])-timedelta(seconds=600))
    need(expires-now>=timedelta(seconds=100),'CAPTURE_WINDOW')
    return dict(schema='RACE_AI_JRA_FUTURE_SOURCE_PLAN_V1',available_after=now.isoformat(),not_after=expires.isoformat(),
        urls=[manifest[k] for k in ('discovery_url','card_url','rule_url')])


def verify_discovery(manifest,raw,encoding):
    class Links(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=True);self.links=[]
        def handle_starttag(self,tag,attrs):
            if tag=='a':self.links.extend(v for k,v in attrs if k=='href' and v)
    parsed=Links();parsed.feed(raw.decode(encoding,'strict'))
    need(manifest['card_url'] in {urljoin(manifest['discovery_url'],href) for href in parsed.links},'PUBLISHED_CARD_HREF')


def originals(manifest,plan,cache,bodies):
    """Replay the exact fresh three-source closure, including its literal link."""
    urls=[manifest[k] for k in ('discovery_url','card_url','rule_url')]
    capture._validate_cache(cache)
    need(cache['urls']==plan['urls']==urls and cache['execution_day']==manifest['execution_day'] and
        cache['terms_manifest']==manifest['terms_manifest'] and cache['request_limit']==32 and
        set(cache['captures'])==set(bodies)==set(urls) and not cache['blocked_hosts'] and not cache['failures'],
        'EXACT_ORIGINAL_SOURCE_CLOSURE')
    need(len(cache['attempts'])==3 and all(a['state']=='SUCCESS' and a['url']==a['target_url']==urls[n] and
        clock(plan['available_after'])<=clock(a['started_at'])<clock(plan['not_after'])
        for n,a in enumerate(cache['attempts'])),'ORIGINAL_WIRE_BOUNDARY')
    sidecar=build_jra_http_metadata(cache,bodies);need(sidecar['state']=='READY_ORIGINAL_METADATA','HTTP_SIDECAR_HOLD')
    actual=sidecar['document']['metadata_by_url'][manifest['discovery_url']]
    content_type=next(v for k,v in actual['headers'].items() if k.lower()=='content-type')
    encoding=re.search(r'charset\s*=\s*[\'\"]?([\w-]+)',content_type,re.I)[1].lower()
    verify_discovery(manifest,bodies[manifest['discovery_url']],{'shift_jis':'cp932','shift-jis':'cp932','utf8':'utf-8'}.get(encoding,encoding))
    return sidecar


class MarkerTransport(GithubIssueTransport):
    @staticmethod
    def _validate_path(path):need(type(path) is str and path==PATH,'CANONICAL_ONCE_PATH')
    _commit_message='Retain consumed first horse forward source reservation'


def marker_body(manifest,env,baseline,history,plan,*,now):
    need(type(env.get('run_id')) is int and env['run_id']>0 and type(env.get('run_attempt')) is int and
        env['run_attempt']==1 and type(env.get('head_sha')) is str and re.fullmatch('[a-f0-9]{40}',env['head_sha']),
        'ACTUAL_ATTEMPT_ONE')
    expected=prepare(manifest,baseline,now=now);need(plan==expected,'ORIGINAL_PLAN')
    model=baseline['training']['models']['horse/'+LEARNED_ID]['native_training']
    return dict(schema=ONCE,purpose='ALL_THIRTY_FIRST_FORWARD_CYCLE_V1_HORSE',state='CONSUMED_BEFORE_DISPATCH',
        marker_path=PATH,repository_id=1416489937,pull_request=71,target=dict(run_id=env['run_id'],head_sha=env['head_sha'],run_attempt=1),
        issued_at=now.isoformat(),expires_at=plan['not_after'],manifest=deepcopy(manifest),manifest_sha256=digest(manifest),
        plan=deepcopy(plan),plan_sha256=digest(plan),baseline_receipt=deepcopy(baseline['receipt']),
        baseline_training_sha256=baseline['training']['training_sha256'],native_model_sha256=digest(model),
        native_created_at=model['created_at'],history=deepcopy(history),source_requests_actual=None,
        source_request_upper_bound=32,old_source_requests_actual=None,old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN')


def _mac(value,key):
    need(type(key) is bytes and len(key)==32,'EXPLICIT_KEY')
    return hmac.digest(hmac.digest(key,DOMAIN,'sha256'),digest(value).encode(),'sha256').hex()


def validate_marker(raw,body,key,*,now):
    fields={'schema','purpose','state','marker_path','repository_id','pull_request','target','issued_at','expires_at',
        'manifest','manifest_sha256','plan','plan_sha256','baseline_receipt','baseline_training_sha256','native_model_sha256',
        'native_created_at','history','source_requests_actual','source_request_upper_bound','old_source_requests_actual',
        'old_source_requests_upper_bound','old_browser_outcome'}
    need(type(body) is dict and set(body)==fields and body['purpose']=='ALL_THIRTY_FIRST_FORWARD_CYCLE_V1_HORSE' and
        body['state']=='CONSUMED_BEFORE_DISPATCH' and type(body['repository_id']) is int and type(body['pull_request']) is int and
        body['source_requests_actual'] is None and type(body['source_request_upper_bound']) is int and body['source_request_upper_bound']==32 and
        body['old_source_requests_actual'] is None and type(body['old_source_requests_upper_bound']) is int and
        body['old_source_requests_upper_bound']==32 and body['old_browser_outcome']=='UNKNOWN','ONCE_SCOPE')
    issued=clock(body['issued_at']);expires=clock(body['expires_at']);manifest=validate_manifest(body['manifest'],now=issued)
    target=body['target'];receipt=body['baseline_receipt'];run=receipt['workflow_run'];pin=manifest['horse_baseline_artifact']
    need(set(target)=={'run_id','head_sha','run_attempt'} and type(target['run_id']) is int and target['run_id']>0 and
        type(target['run_attempt']) is int and target['run_attempt']==1 and re.fullmatch('[a-f0-9]{40}',target['head_sha']) and
        (receipt['id'],receipt['digest'],run['id'],run['head_sha'])==(pin['id'],pin['digest'],pin['run_id'],pin['head_sha']) and
        clock(receipt['created_at'])+timedelta(seconds=1)<=issued and clock(body['native_created_at'])<issued and
        all(type(body[k]) is str and re.fullmatch('[a-f0-9]{64}',body[k]) for k in ('baseline_training_sha256','native_model_sha256')),
        'ONCE_ACTUAL_BASELINE')
    midnight=issued.astimezone(jra.JST).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
    plan=body['plan']
    need(set(plan)=={'schema','available_after','not_after','urls'} and plan['schema']=='RACE_AI_JRA_FUTURE_SOURCE_PLAN_V1' and
        plan['urls']==[manifest[k] for k in ('discovery_url','card_url','rule_url')] and
        issued+timedelta(seconds=100)<=expires<=min(issued+timedelta(hours=1),midnight,clock(manifest['cutoff_at'])-timedelta(seconds=600)),
        'ONCE_CLOCK_OR_PLAN')
    header=forecast_header(raw);value=open_forecasts(raw,key=key)
    need(set(value)=={'schema','body','mac'} and value['schema']==ONCE and value['body']==body and
        hmac.compare_digest(value['mac'],_mac(body,key)) and header['round_no']==ROUND and
        header['run_id']==str(body['target']['run_id']) and body['schema']==ONCE and body['marker_path']==PATH and
        body['repository_id']==1416489937 and body['pull_request']==71 and body['target']['run_attempt']==1 and
        body['manifest_sha256']==digest(body['manifest']) and body['plan_sha256']==digest(body['plan']) and
        body['plan']['available_after']==body['issued_at'] and body['plan']['not_after']==body['expires_at'] and
        clock(body['issued_at'])<=now<clock(body['expires_at']),'AUTHENTICATED_ONCE')
    return dict(marker_path=PATH,marker_cipher_sha256=sha256(raw).hexdigest(),authorization_sha256=digest(body),
        issued_at=body['issued_at'],expires_at=body['expires_at'],source_request_upper_bound=32)


def reserve(body,key,transport,*,now):
    parent=transport.head();need(transport.read_file(parent,PATH,MAX_WIRE) is None,'ONCE_ALREADY_CONSUMED')
    raw=seal_forecasts(dict(schema=ONCE,body=deepcopy(body),mac=_mac(body,key)),
        run_id=str(body['target']['run_id']),round_no=ROUND,key=key)
    validate_marker(raw,body,key,now=now);commit=transport.publish_capsule(PATH,raw,parent)
    actual=transport.read_file(commit,PATH,MAX_WIRE);need(actual==raw,'ONCE_ACTUAL_READBACK_BYTES')
    return dict(validate_marker(actual,body,key,now=now),commit_sha=commit,_ciphertext=raw)
