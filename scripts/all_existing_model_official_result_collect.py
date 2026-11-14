"""One explicit owner-scoped official-result collection epoch.

Authenticate encrypted plans/native inputs/checkpoints before provider reads.
Only due unconfirmed cases are collected. Published links and normal UI are
read-only source routes, never a claim of public API or provider ML permission.
"""
import argparse
import base64
from collections import Counter
from copy import deepcopy
from datetime import datetime,timedelta,timezone,date
from hashlib import sha256
import json
import io
import stat
import zipfile
import zlib
import os
from pathlib import Path,PurePosixPath
import re
import subprocess
import time
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit,urljoin,parse_qs
from urllib.request import Request,build_opener

from race_ai.actions_contract import digest
from race_ai import manual_official_capture as policy
from race_ai import all_existing_model_official_results as results
from race_ai.boat_all_model_store import open_forecasts,seal_forecasts,forecast_header,MAX_WIRE,MAX_PLAIN
from race_ai.boat_pdca_state import state_key
from race_ai.permissioned_source_delivery import read_json_bytes
from race_ai.existing_model_dispatch import _race_key
from race_ai.all_existing_model_learning import _sources
from scripts import all_existing_model_future_p0 as future
from scripts import all_existing_model_official_result_freeze as freeze
from scripts.all_existing_model_official_freeze import _repository_file
from scripts.all_existing_model_learning import _merge_verified_result_observations
from scripts.boat_all_racers import _read,_write
from scripts.boat_history_collect import save

ROOT=Path(__file__).resolve().parents[1]
SCHEMA='RACE_AI_OFFICIAL_RESULT_COLLECT_INPUT_V1'
SCHEMA_V2='RACE_AI_OFFICIAL_RESULT_COLLECT_INPUT_V2'
SCHEMA_V3='RACE_AI_OFFICIAL_RESULT_COLLECT_INPUT_V3'
PLAN='RACE_AI_OFFICIAL_RESULT_COLLECTION_PLAN_V1'
STATUS='RACE_AI_OFFICIAL_RESULT_COLLECTION_COUNTS_V1'
JOURNAL='RACE_AI_OFFICIAL_RESULT_COLLECTION_JOURNAL_V1'
JOURNAL_V2='RACE_AI_OFFICIAL_RESULT_COLLECTION_JOURNAL_V2'
JOURNAL_V3='RACE_AI_OFFICIAL_RESULT_COLLECTION_JOURNAL_V3'
ROUND=freeze.ROUND
MAX_BYTES=2*1024*1024
INTERVAL=.825
TIMEOUT=12
JST=timezone(timedelta(hours=9))


def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_OFFICIAL_COLLECT_'+reason)
def utc_now():return datetime.now(timezone.utc)
def stamp(value):return future.stamp(value)
def b64(raw):return base64.b64encode(raw).decode()


def _pins(values,*,empty=False):
    need(type(values) is list and (0 if empty else 1)<=len(values)<=16,'ARTIFACT_PIN_BOUND')
    seen=set()
    for pin in values:
        need(type(pin) is dict and set(pin)=={'id','digest','run_id','head_sha'} and
            type(pin['id']) is int and 0<pin['id']<10**16 and pin['id'] not in seen and
            type(pin['run_id']) is int and 0<pin['run_id']<10**20 and
            type(pin['digest']) is str and re.fullmatch('sha256:[a-f0-9]{64}',pin['digest']) and
            type(pin['head_sha']) is str and re.fullmatch('[a-f0-9]{40}',pin['head_sha']),'ARTIFACT_PIN')
        seen.add(pin['id'])
    return seen


def _manifest(value,now):
    need(type(now) is datetime and now.utcoffset() is not None,'AWARE_CLOCK')
    fields={'schema','execution_day','plan_path','plan_sha256','native_artifacts','checkpoint_artifacts','allow_order_only'}
    need(type(value) is dict and (value.get('schema')==SCHEMA and set(value)==fields or
        value.get('schema')==SCHEMA_V2 and set(value)==fields|{'prior_journal_artifacts'} or
        value.get('schema')==SCHEMA_V3 and set(value)==fields|{'prior_journal_artifacts','target_event_day'}),'MANIFEST_SCHEMA')
    need(value['execution_day']==now.astimezone(JST).date().isoformat() and
        type(value['allow_order_only']) is bool,'EXECUTION_DAY_OR_MODE')
    if value['schema']==SCHEMA_V3:
        try:
            target=value['target_event_day'];valid=type(target) is str and date.fromisoformat(target).isoformat()==target
            age=(date.fromisoformat(value['execution_day'])-date.fromisoformat(target)).days if valid else -1
        except ValueError:age=-1
        need(1<=age<=7,'HISTORICAL_TARGET_DAY')
    hashed=value['plan_sha256']
    need(type(hashed) is str and re.fullmatch('[a-f0-9]{64}',hashed) and
        value['plan_path']=='audit/state/official-result-collection-plan-'+hashed+'.enc','PLAN_CIPHER_PATH')
    natives=_pins(value['native_artifacts']);checkpoints=_pins(value['checkpoint_artifacts'],empty=True)
    journals=_pins(value['prior_journal_artifacts'],empty=True) if value['schema'] in (SCHEMA_V2,SCHEMA_V3) else set()
    need(not natives&checkpoints and not journals&(natives|checkpoints) and
        len(natives)+len(checkpoints)+len(journals)<=32,'ARTIFACT_PIN_CONFLICT')
    return value


def load_manifest(path,*,now):return _manifest(read_json_bytes(_read(Path(path),32768)),now)

def target_event_day(manifest):return manifest['target_event_day'] if manifest['schema']==SCHEMA_V3 else manifest['execution_day']

def journal_schema(manifest):return JOURNAL_V3 if manifest['schema']==SCHEMA_V3 else JOURNAL_V2 if manifest['schema']==SCHEMA_V2 else JOURNAL


def load_plan(manifest,*,key,now):
    raw=_repository_file(ROOT/manifest['plan_path'],MAX_WIRE)
    need(sha256(raw).hexdigest()==manifest['plan_sha256'],'PLAN_CIPHER_SHA')
    value=open_forecasts(raw,key=key)
    fields={'schema','execution_day','cases','terms_manifest','maximum_requests','result_wait_seconds'}
    need(type(value) is dict and fields<=set(value)<=fields|{'static_cache'} and value['schema']==PLAN and
        value['execution_day']==target_event_day(manifest) and len(future.wire(value))<=MAX_PLAIN,'PLAN_SCHEMA')
    need(type(value['maximum_requests']) is int and 1<=value['maximum_requests']<=32 and
        type(value['result_wait_seconds']) is int and 120<=value['result_wait_seconds']<=3600 and
        type(value['cases']) is list and 1<=len(value['cases'])<=32,'PLAN_BOUND')
    urls=[]
    for item in value['terms_manifest'].get('terms',[]) if type(value['terms_manifest']) is dict else []:
        need(type(item) is dict and type(item.get('source_urls')) is list,'TERMS_SCOPE');urls+=item['source_urls']
    policy._terms(value['terms_manifest'],urls,value['execution_day'],now)
    allowed=set(urls);seen=set()
    for case in value['cases']:
        need(type(case) is dict and set(case)=={'sport','race_id','route'} and
            case['sport'] in ('horse','autorace','keirin') and type(case['race_id']) is str,'CASE_SCHEMA')
        identity=(case['sport'],_race_key(case['race_id'],case['sport']))
        need(identity not in seen,'DUPLICATE_CASE');seen.add(identity)
        route=case['route'];need(type(route) is dict,'ROUTE_SCHEMA')
        if case['sport']=='horse':
            need(set(route)=={'kind','card_url','result_url','link_capture'} and
                route['kind']=='JRA_CARD_PUBLISHED_GET' and route['card_url'] in allowed,'JRA_ROUTE_SCOPE')
            need((route['result_url'] is None and route['link_capture'] is None) or
                (type(route['result_url']) is str and type(route['link_capture']) is dict),'JRA_LITERAL_PROOF_REQUIRED')
            policy.validate_source_pair(route['card_url'],policy.official_rights_ref('horse'))
        else:
            need({'kind','ui_entry_url','ui_venue_name'}<=set(route)<=
                {'kind','ui_entry_url','ui_venue_name','place_code'} and route['kind']=='NORMAL_UI' and
                route['ui_entry_url'] in allowed,'NORMAL_UI_ROUTE_SCOPE')
            policy.validate_source_pair(route['ui_entry_url'],policy.official_rights_ref(case['sport']))
            need(route['ui_venue_name'] is None or type(route['ui_venue_name']) is str and
                0<len(route['ui_venue_name'])<=80,'UI_VENUE_NAME')
            if 'place_code' in route:need(type(route['place_code']) is int and 1<=route['place_code']<=20,'ACTUAL_PLACE_CODE')
    if 'static_cache' in value:
        cache=value['static_cache'];need(type(cache) is list and len(cache)<=128,'STATIC_CACHE_BOUND')
        total=0;cached={}
        for item in cache:
            need(type(item) is dict and set(item)=={'raw_base64','metadata'} and type(item['metadata']) is dict,'STATIC_CACHE_SCHEMA')
            body=_blob(item['raw_base64']);total+=len(body);metadata=item['metadata'];url=metadata.get('source_url')
            sport,_=policy._url(url);parts=urlsplit(url);kind=metadata.get('resource_type')
            types=[v.lower().split(';',1)[0].strip() for k,v in metadata.get('headers',{}).items()
                if str(k).lower()=='content-type' and type(v) is str]
            need(total<=16*1024*1024 and sport in ('autorace','keirin') and metadata.get('final_url')==url and
                metadata.get('http_method')=='GET' and type(metadata.get('status')) is int and metadata['status']==200 and
                metadata.get('byte_count')==len(body) and metadata.get('source_sha256')==sha256(body).hexdigest() and
                stamp(metadata['fetched_at'])<=stamp(metadata['response_received_at'])<=now and
                not re.search('analytics|tracker|banner',parts.path,re.I) and
                (kind=='script' and parts.path.lower().endswith('.js') and len(types)==1 and
                 re.fullmatch(r'(?:application|text)/(?:javascript|x-javascript|ecmascript)',types[0]) is not None or
                 kind=='stylesheet' and parts.path.lower().endswith('.css') and types==['text/css']),'STATIC_CACHE_PROOF')
            need(url not in cached or cached[url]==body,'STATIC_CACHE_CONFLICT');cached[url]=body
    return value


def checkpoints(manifest,natives,*,now,key):
    observations=[];total=0
    for pin in manifest['checkpoint_artifacts']:
        actual=future.metadata(pin['id'])
        need(type(actual) is dict and actual.get('id')==pin['id'] and actual.get('digest')==pin['digest'] and
            actual.get('expired') is False and type(actual.get('size_in_bytes')) is int and
            0<actual['size_in_bytes']<=results.MAX_ARCHIVE_BYTES,'CHECKPOINT_ACTUAL_METADATA')
        need(stamp(actual.get('created_at'))<=now<stamp(actual.get('expires_at')),'CHECKPOINT_EXPIRED_OR_FUTURE')
        raw=future.gh('actions/artifacts/'+str(pin['id'])+'/zip');total+=len(raw)
        need(total<=256*1024*1024 and len(raw)==actual['size_in_bytes'] and
            'sha256:'+sha256(raw).hexdigest()==pin['digest'],'CHECKPOINT_BYTES')
        admitted=results.observations_from_official_result_artifact(raw,actual,now=now,
            expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'],frozen_native_payloads=natives,
            key=key,allow_order_only=manifest['allow_order_only'])
        observations.extend(admitted['observations'])
    return {(o['sport'],_race_key(o['race_id'],o['sport'])):o
        for o in _merge_verified_result_observations(observations)}


def _journal_cipher(raw):
    need(type(raw) is bytes and 0<len(raw)<=results.MAX_ARCHIVE_BYTES and raw.startswith(b'PK\x03\x04') and
        len(raw)>=22 and raw[-22:-18]==b'PK\x05\x06' and raw[-2:]==b'\0\0','JOURNAL_ZIP_ENVELOPE')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist();need(len(entries)==1 and not archive.comment,'JOURNAL_ZIP_EXACT_CIPHER')
            entry=entries[0]
            need(entry.filename==entry.orig_filename and re.fullmatch(
                r'(?:collection\.enc|[A-Za-z0-9][A-Za-z0-9_.-]{0,150}\.collection\.enc)',entry.filename) and
                stat.S_IFMT(entry.external_attr>>16) in (0,stat.S_IFREG) and not entry.flag_bits&0x41 and
                entry.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) and
                0<entry.file_size<=MAX_WIRE,'JOURNAL_ZIP_EXACT_CIPHER')
            with archive.open(entry) as source:cipher=source.read(MAX_WIRE+1)
            need(len(cipher)==entry.file_size,'JOURNAL_ZIP_CIPHER_SIZE');return cipher
    except (zipfile.BadZipFile,RuntimeError,NotImplementedError,EOFError,zlib.error) as exc:
        raise ValueError('ALL_MODEL_OFFICIAL_COLLECT_JOURNAL_ZIP_REJECTED') from exc


def _journal_origin(cipher,*,key,run_id,head_sha,now,saved_at=None):
    header=forecast_header(cipher);body=open_forecasts(cipher,key=key)
    need(header['run_id']==str(run_id) and header['round_no']==900006 and
        body.get('schema') in (JOURNAL_V2,JOURNAL_V3),'PRIOR_JOURNAL_ORIGIN_NOT_REPLAYABLE')
    fields={'schema','execution_day','manifest_sha256','maximum_requests','epoch_started_at','attempts','captures','cases',
        'manifest','workflow_run_id','code_sha','collection_plan_sha256'}
    if body.get('schema')==JOURNAL_V3:fields=fields|{'target_event_day'}
    need(fields<=set(body)<=fields|{'browser_attempt','browser_index','browser_captures','browser_request_checkpoint',
        'browser_process_diagnostic','browser_failure','browser_quarantine','recovery_authorization','prior_static_cache'} and
        type(body['workflow_run_id']) is int and body['workflow_run_id']==run_id and body['code_sha']==head_sha,
        'JOURNAL_ORIGIN_RUN')
    if 'prior_static_cache' in body:_prior_static_lineage(body['prior_static_cache'])
    epoch=stamp(body['epoch_started_at']);original=_manifest(body['manifest'],epoch)
    need(epoch<=now and (saved_at is None or epoch<=saved_at+timedelta(seconds=1)) and
        body['execution_day']==original['execution_day'] and body['manifest_sha256']==digest(original) and
        original['schema'] in (SCHEMA_V2,SCHEMA_V3) and body['schema']==journal_schema(original) and
        (original['schema']!=SCHEMA_V3 or body['target_event_day']==original['target_event_day']) and
        body['collection_plan_sha256']==original['plan_sha256'] and
        type(body['maximum_requests']) is int and 1<=body['maximum_requests']<=32 and
        type(body['attempts']) is list and len(body['attempts'])<=body['maximum_requests'] and
        type(body['captures']) is list and type(body['cases']) is list and len(body['cases'])<=32,
        'JOURNAL_ORIGIN_CLOCK_OR_SCOPE')
    bound=min(now,saved_at+timedelta(seconds=1)) if saved_at is not None else now
    for attempt in body['attempts']:
        need(type(attempt) is dict and attempt.get('state') in
            ('RESERVED','SUCCESS','DENIED','HTTP_OR_SOURCE_UNAVAILABLE') and
            epoch<=stamp(attempt['started_at'])<=bound,'JOURNAL_ATTEMPT_SCHEMA')
        if attempt['state']!='RESERVED':
            need(epoch<=stamp(attempt['started_at'])<=stamp(attempt['finished_at'])<=bound,
                'JOURNAL_ATTEMPT_CLOCK')
        need(attempt.get('http_status') is None or type(attempt['http_status']) is int,'JOURNAL_HTTP_STATUS')
    return body


def _journal_artifact(pin,*,now,key):
    actual=future.metadata(pin['id']);run=actual.get('workflow_run') if type(actual) is dict else None
    need(type(actual) is dict and actual.get('id')==pin['id'] and actual.get('digest')==pin['digest'] and
        actual.get('name')=='official-result-collection-journal-'+str(pin['run_id']) and actual.get('expired') is False and
        type(actual.get('size_in_bytes')) is int and 0<actual['size_in_bytes']<=results.MAX_ARCHIVE_BYTES and
        type(run) is dict and type(run.get('id')) is int and run['id']==pin['run_id'] and
        run.get('head_sha')==pin['head_sha'] and all(type(run.get(k)) is int and run[k]==results.REPOSITORY_ID
            for k in ('repository_id','head_repository_id')),'JOURNAL_ACTUAL_METADATA')
    saved=stamp(actual.get('created_at'));need(saved<=now<stamp(actual.get('expires_at')),'JOURNAL_EXPIRED_OR_FUTURE')
    raw=future.gh('actions/artifacts/'+str(pin['id'])+'/zip')
    need(type(raw) is bytes and len(raw)==actual['size_in_bytes'] and
        'sha256:'+sha256(raw).hexdigest()==pin['digest'],'JOURNAL_ACTUAL_BYTES')
    cipher=_journal_cipher(raw);body=_journal_origin(cipher,key=key,run_id=pin['run_id'],head_sha=pin['head_sha'],
        now=now,saved_at=saved)
    return body,cipher,actual


def _prior_static_lineage(value):
    """Count/hash/pin evidence only; no cached source bytes in public status."""
    need(type(value) is dict and set(value)=={'cache_entry_count','cache_sha256','source_journals','source_receipts_sha256'} and
        type(value['cache_entry_count']) is int and
        1<=value['cache_entry_count']<=128 and all(type(value.get(k)) is str and re.fullmatch('[a-f0-9]{64}',value[k])
            for k in ('cache_sha256','source_receipts_sha256')),'PRIOR_STATIC_CACHE_LINEAGE')
    _pins(value['source_journals'])
    return value


def prior_journals(manifest,*,now,key,recovery_authorization=None,private_static_cache_out=None):
    """Guard only explicitly pinned epochs; never infer that unlisted history is safe."""
    if manifest['schema'] not in (SCHEMA_V2,SCHEMA_V3):return {}
    need(private_static_cache_out is None or type(private_static_cache_out) is dict and not private_static_cache_out,
        'EMPTY_PRIVATE_STATIC_CACHE_OUT_REQUIRED')
    receipts=[];latest=None;eligible=[]
    for pin in manifest['prior_journal_artifacts']:
        body,cipher,actual=_journal_artifact(pin,now=now,key=key);epoch=stamp(body['epoch_started_at'])
        latest=max(latest,epoch) if latest is not None else epoch
        attempts=body['attempts'];browser=body.get('browser_attempt')
        reviewed=False
        if recovery_authorization is not None:
            from race_ai.all_existing_model_official_recovery import ValidatedRecovery
            from race_ai.all_existing_model_official_continuation import ValidatedContinuation
            from race_ai.all_existing_model_official_probe16 import ValidatedProbe16
            need(type(recovery_authorization) in (ValidatedRecovery,ValidatedContinuation,ValidatedProbe16),'VALIDATED_RECOVERY_REQUIRED')
            reviewed=recovery_authorization.validate_prior(manifest,pin,body,cipher,actual,now)
        ledger=[]
        for field in ('browser_index','browser_request_checkpoint'):
            container=body.get(field,{})
            need(type(container) is dict and type(container.get('ledger',[])) is list and len(container.get('ledger',[]))<=2048,
                'PRIOR_JOURNAL_BROWSER_LEDGER')
            ledger+=container.get('ledger',[])
        need(all(type(e) is dict for e in ledger),'PRIOR_JOURNAL_BROWSER_LEDGER')
        need(not any(a.get('http_status') in (401,403,429) or a['state']=='DENIED' for a in attempts) and
            not any(e.get('status') in (401,403,429) for e in ledger) and
            (browser is None or browser.get('stop_reason') not in
                ('HOLD_ACCESS_DENIED','ACCESS_DENIED','HTTP_ACCESS_DENIED','DENIED')) and
            not any(body.get(field,{}).get('stop_reason') in
                ('HOLD_ACCESS_DENIED','ACCESS_DENIED','HTTP_ACCESS_DENIED','DENIED') or
                body.get(field,{}).get('stopped_host') is True for field in ('browser_index','browser_request_checkpoint')),
            'PRIOR_JOURNAL_DENIED_REQUIRES_OWNER_REVIEW')
        rejected_wire=None
        if not reviewed and type(browser) is dict and browser.get('state')=='REJECTED':
            from race_ai.all_existing_model_known_rejected_wire import known_data_rejected_wire
            rejected_wire=known_data_rejected_wire(body,actual,now=now)
        need(reviewed or not any(a['state']=='RESERVED' for a in attempts) and
            (browser is None or type(browser) is dict and (browser.get('state')=='COMPLETE' or rejected_wire is not None) and
             type(browser.get('actual_request_count')) is int and
             0<=browser['actual_request_count']<=body['maximum_requests']-len(attempts)),
            'PRIOR_JOURNAL_UNCERTAIN_REQUIRES_OWNER_REVIEW')
        if browser is not None and not reviewed:
            index=body.get('browser_index',{});requests=[e for e in index.get('ledger',[]) if 'sequence' in e]
            count=browser['actual_request_count']
            need(index.get('schema')=='RACE_AI_OFFICIAL_RESULT_BROWSER_CAPTURE_V1' and
                index.get('normal_ui_only') is True and type(index.get('manual_api_requests')) is int and
                index['manual_api_requests']==0 and type(index.get('actual_request_count')) is int and
                index['actual_request_count']==count and len(requests)==count and
                {e.get('sequence') for e in requests}==set(range(1,count+1)) and
                epoch<=stamp(browser['started_at'])<=stamp(index['started_at'])<=stamp(index['completed_at'])<=
                    stamp(browser['completed_at'])<=min(now,stamp(actual['created_at'])+timedelta(seconds=1)) and
                all(type(e.get('sequence')) is int and type(e.get('status')) is int and 100<=e['status']<=599 and
                    epoch<=stamp(e['request_started_at'])<=stamp(e['headers_received_at'])<=stamp(browser['completed_at'])
                    for e in requests),'PRIOR_JOURNAL_BROWSER_OUTCOME_UNKNOWN')
        receipts.append(dict(artifact_id=pin['id'],artifact_digest=pin['digest'],workflow_run_id=pin['run_id'],
            head_sha=pin['head_sha'],epoch_started_at=body['epoch_started_at'],saved_at=actual['created_at'],
            expires_at=actual['expires_at'],journal_cipher_sha256=sha256(cipher).hexdigest(),journal_payload_sha256=digest(body)))
        # Reviewed UNKNOWN may remain admissible under its existing bound, but
        # it can never supply reusable bytes. Delay extraction until ALL prior
        # authorization/denial/uncertainty/interval guards have passed.
        if private_static_cache_out is not None and type(browser) is dict and browser.get('state')=='COMPLETE' and \
                'browser_quarantine' in body and any(type(entry) is dict and entry.get('resource_type') in ('script','stylesheet')
                    for entry in body.get('browser_index',{}).get('responses',[])):
            eligible.append((deepcopy(pin),body,actual))
    need(latest is None or now-latest>=timedelta(seconds=3600),'PRIOR_EPOCH_TOO_RECENT')
    if private_static_cache_out is not None and eligible:
        from race_ai.all_existing_model_prior_static_cache import extract_static_cache,merge_static_cache
        entries=[];sources=[]
        for pin,body,actual in eligible:
            additions=extract_static_cache(body,actual,now=now)
            entries=merge_static_cache(entries,additions,now=now,sports=('autorace','keirin'))
            if additions:sources.append(pin)
        if entries:
            lineage=dict(cache_entry_count=len(entries),cache_sha256=digest(entries),
                source_journals=sources,source_receipts_sha256=digest(receipts))
            _prior_static_lineage(lineage)
            private_static_cache_out.update(entries=deepcopy(entries),lineage=lineage)

    return dict(prior_journal_artifact_count=len(receipts),prior_journal_receipts_sha256=digest(receipts),
        prior_journal_guard_scope='EXPLICIT_PINNED_JOURNALS_ONLY',minimum_epoch_interval_seconds=3600)


def _lineage(manifest):
    value=dict(collection_plan_sha256=manifest['plan_sha256'],manifest_sha256=digest(manifest),
        native_artifact_pins_sha256=digest(manifest['native_artifacts']),
        checkpoint_artifact_pins_sha256=digest(manifest['checkpoint_artifacts']),
        native_input_artifact_count=len(manifest['native_artifacts']),allow_order_only=manifest['allow_order_only'])
    if manifest['schema']==SCHEMA_V3:value.update(execution_day=manifest['execution_day'],target_event_day=manifest['target_event_day'],
        collection_mode='HISTORICAL_RESULT_LABELS_ONLY')
    return value


class Budget:
    def __init__(self,maximum,journal,persist,clock,sleeper,opener,*,before_source=None):
        self.maximum=maximum;self.journal=journal;self.persist=persist;self.clock=clock;self.sleeper=sleeper
        self.opener=opener or build_opener(policy._NoRedirect()).open;self.used=0;self.last=None;self.last_mono=None;self.denied=set()
        self.epoch=stamp(journal['epoch_started_at'])
        self.before_source=before_source
    @property
    def remaining(self):return self.maximum-self.used
    def wait(self):
        if self.last is not None:
            elapsed=(self.clock()-self.last).total_seconds()
            if self.last_mono is not None:elapsed=min(elapsed,time.monotonic()-self.last_mono)
            need(elapsed>=0,'CLOCK_REGRESSED')
            if elapsed<INTERVAL:self.sleeper(INTERVAL-elapsed)
    def get(self,url):
        sport,_=policy._url(url)
        if self.remaining<=0 or sport in self.denied:return None
        if self.before_source is not None:self.before_source()
        self.wait();started=self.clock()
        need(started>=self.epoch,'CLOCK_REGRESSED_BEFORE_SOURCE')
        need(started.astimezone(JST).date().isoformat()==self.journal['execution_day'],'DAY_ELAPSED')
        entry=dict(url=url,started_at=started.isoformat(),state='RESERVED',http_status=None)
        self.journal['attempts'].append(entry);self.used+=1;self.persist();response=None
        # If revoked after the durable checkpoint, preserve RESERVED/UNKNOWN.
        # No request has been dispatched and the existing conservative journal
        # reader must never turn the reserved slot into an invented zero.
        if self.before_source is not None:self.before_source()
        try:
            try:response=self.opener(Request(url,headers={'User-Agent':'RACE-AI-owner-private-official-results/1.0',
                'Accept':'text/html,application/json;q=0.8','Accept-Encoding':'identity'}),timeout=TIMEOUT)
            except HTTPError as exc:response=exc
            status=getattr(response,'status',None) or getattr(response,'code',None);entry['http_status']=status
            need(type(status) is int,'HTTP_STATUS')
            if status in (401,403,429):
                self.denied.add(sport);entry['state']='DENIED';return None
            need(response.geturl()==url and status==200,'HTTP_IDENTITY_OR_STATUS')
            headers=response.headers;length=headers.get('Content-Length')
            need(length is None or str(length).isdigit() and 0<int(length)<=MAX_BYTES,'SOURCE_SIZE')
            need(headers.get('Content-Encoding','identity').lower() in ('','identity'),'SOURCE_ENCODING')
            raw=response.read(MAX_BYTES+1)
            need(type(raw) is bytes and 0<len(raw)<=MAX_BYTES and (length is None or len(raw)==int(length)),'SOURCE_BODY')
            completed=self.clock();need(started<=completed and completed.astimezone(JST).date().isoformat()==
                self.journal['execution_day'],'SOURCE_CLOCK')
            mime=headers.get('Content-Type','');need(type(mime) is str and len(mime)<=512,'SOURCE_MIME')
            meta=dict(source_url=url,final_url=response.geturl(),status=status,byte_count=len(raw),source_sha256=sha256(raw).hexdigest(),
                fetched_at=started.isoformat(),response_received_at=completed.isoformat(),headers={'Content-Type':mime},
                method='GET',http_method='GET')
            capture=dict(raw_base64=b64(raw),metadata=meta);self.journal['captures'].append(capture)
            entry['state']='SUCCESS';return capture
        except (ValueError,OSError,URLError,TimeoutError):entry['state']='HTTP_OR_SOURCE_UNAVAILABLE';return None
        finally:
            if response is not None:response.close()
            self.last=self.clock();self.last_mono=time.monotonic();entry['finished_at']=self.last.isoformat();self.persist()


def _blob(value):return results._nested_raw(value,maximum=MAX_BYTES)


def published_result(capture,native,now):
    """Read a published href; never derive a result namespace from a checksum."""
    from race_ai.jra_official_sparse_adapter import _document
    raw=_blob(capture['raw_base64']);metadata=capture['metadata'];document,url,_=_document(raw,metadata,now)
    expected=native['snapshot']['race'];found=[]
    for anchor in document.nodes('a'):
        href=anchor.attrs.get('href')
        if type(href) is not str:continue
        candidate=urljoin(url,href)
        try:
            policy.validate_source_pair(candidate,policy.official_rights_ref('horse'))
            parts=urlsplit(candidate);query=parse_qs(parts.query)
            need(parts.path=='/JRADB/accessS.html' and set(query)=={'CNAME'} and len(query['CNAME'])==1,'PUBLISHED_RESULT_LINK')
            match=re.fullmatch(r'pw01sde(?:01|10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/[A-Fa-f0-9]{2}',query['CNAME'][0])
            need(match is not None,'PUBLISHED_RESULT_LINK')
            venue,year,_,_,race_no,day=match.groups()
            key=f'horse:{day[:4]}-{day[4:6]}-{day[6:]}:jra-{venue}:{int(race_no)}'
            need(_race_key(key,'horse')==_race_key(expected['race_id'],'horse') and
                year==expected['event_date_jst'][:4],'PUBLISHED_RESULT_CASE')
            found.append(candidate)
        except (ValueError,TypeError,KeyError):continue
    found=sorted(set(found));need(len(found)<=1,'AMBIGUOUS_PUBLISHED_RESULT_LINK')
    return found[0] if found else None


def _safe_file(root,name,maximum):
    need(type(name) is str and 0<len(name)<=240 and not PurePosixPath(name).is_absolute() and
        '..' not in PurePosixPath(name).parts,'BROWSER_FILE_PATH')
    path=root/name
    from race_ai.all_existing_model_runtime import _private_file
    need(not any(p.is_symlink() for p in (path,*path.parents)),'BROWSER_SYMLINK')
    _private_file(path);return _read(path,maximum)


class BrowserCaptureFailure(ValueError):
    def __init__(self,diagnostic):
        super().__init__('ALL_MODEL_OFFICIAL_COLLECT_BROWSER_CAPTURE_PROCESS')
        self.process_diagnostic=diagnostic


def _process_diagnostic(process=None,error=None):
    """Retain bounded facts/hashes, never child output text or environment."""
    result=dict(schema='RACE_AI_OFFICIAL_BROWSER_PROCESS_DIAGNOSTIC_V1',
        timed_out=isinstance(error,subprocess.TimeoutExpired),stdout_request_count_authoritative=False)
    code=getattr(process,'returncode',None)
    result['returncode']=code if type(code) is int and -255<=code<=255 else None
    outputs={}
    for name in ('stdout','stderr'):
        value=getattr(process,name,None) if process is not None else getattr(error,name,None)
        if name=='stdout' and value is None:value=getattr(error,'output',None)
        raw=value.encode('utf8') if type(value) is str else value if type(value) is bytes else None
        result[name+'_present']=raw is not None
        if raw is not None:
            result[name+'_byte_count']=len(raw);result[name+'_sha256']=sha256(raw).hexdigest();outputs[name]=raw
    raw=outputs.get('stdout',b'')
    if 0<len(raw)<=16384:
        try:
            value=read_json_bytes(raw)
            if type(value) is dict:
                if value.get('state') in ('HOLD','CAPTURED'):result['stdout_state']=value['state']
                for name in ('actual_request_count','captured_case_count','held_case_count'):
                    if type(value.get(name)) is int and 0<=value[name]<=32:result['stdout_reported_'+name]=value[name]
                if type(value.get('stopped_host')) is bool:result['stdout_stopped_host']=value['stopped_host']
                # This fixed namespace contains code constants, not exception
                # messages. Unknown stdout fields are never copied.
                codes={'PRIVATE_PLAN','PLAN_SCHEMA','CASE_SCHEMA','CASE_CLOCK_OR_NUMBER','CASE_VENUE','CASE_IDENTITY',
                    'STATIC_CACHE_SCHEMA','STATIC_CACHE_BYTES','STATIC_CACHE_PROOF','STATIC_CACHE_MIME','STATIC_CACHE_CLOCK',
                    'STATIC_CACHE_BOUND','CONFLICTING_STATIC_CACHE','CLOCK_REGRESSION','PRIVATE_PATH','PRIVATE_SYMLINK',
                    'PRIVATE_OUTSIDE_GIT','PRIVATE_PARENT','OUTPUT_EXISTS','FIXED_CHROMIUM_REQUIRED','PROXY_CONFIGURATION',
                    'WEBSOCKET_BLOCK_REQUIRED','CHROMIUM_BYTE_GUARD_REQUIRED','CLI_ARGUMENTS'}
                if value.get('error_code') in {'OFFICIAL_BROWSER_'+code for code in codes}:
                    result['stdout_error_code']=value['error_code']
        except (ValueError,TypeError,UnicodeError):pass
    if error is not None:result.update(future.safe_diagnostic(error))
    return result


def browser_capture(plan,directory,*,diagnostic_sink=None):
    request=directory.with_name(directory.name+'.plan.json');_write(request,future.wire(plan))
    env=dict(os.environ)
    for name in list(env):
        if name=='RACE_AI_STATE_KEY' or name in ('GH_TOKEN','GITHUB_TOKEN') or name.startswith(('ACTIONS_','GIT_CONFIG_VALUE_')):
            env.pop(name,None)
    process=None;error=None
    try:
        process=subprocess.run(['node',str(ROOT/'scripts/official_result_browser_capture.cjs'),'--plan',str(request),
            '--out-dir',str(directory)],capture_output=True,timeout=100,env=env,check=False)
    except (subprocess.TimeoutExpired,OSError) as exc:error=exc
    diagnostic=_process_diagnostic(process,error)
    if diagnostic_sink is not None:diagnostic_sink(diagnostic)
    if not (directory/'capture-index.json').exists() and not directory.is_dir():
        raise BrowserCaptureFailure(diagnostic)
    if (directory/'capture-index.json').exists():
        return read_json_bytes(_safe_file(directory,'capture-index.json',4*1024*1024))
    checkpoints=[]
    if directory.is_dir():
        for path in directory.iterdir():
            match=re.fullmatch(r'request-ledger-([0-9]{3})\.json',path.name)
            if match and 1<=int(match[1])<=32:checkpoints.append((int(match[1]),path.name))
    if not checkpoints:raise BrowserCaptureFailure(diagnostic)
    number,name=max(checkpoints)
    checkpoint=read_json_bytes(_safe_file(directory,name,4*1024*1024))
    need(type(checkpoint) is dict and checkpoint.get('schema')=='RACE_AI_OFFICIAL_RESULT_BROWSER_REQUEST_CHECKPOINT_V1' and
        type(checkpoint.get('actual_request_count')) is int and checkpoint['actual_request_count']==number and
        type(checkpoint.get('maximum_requests')) is int and checkpoint['maximum_requests']==plan['request_budget'] and
        number<=plan['request_budget'] and type(checkpoint.get('ledger')) is list and len(checkpoint['ledger'])<=2048 and
        stamp(plan['not_before'])<=stamp(checkpoint['started_at'])<=stamp(checkpoint['last_updated_at']),
        'BROWSER_INTERRUPTED_CHECKPOINT')
    return dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_INTERRUPTED_V1',checkpoint=checkpoint)


def _index_header(index,planned,*,started,now,remaining):
    need(type(index) is dict and len(future.wire(index))<=4*1024*1024 and
        index.get('schema')=='RACE_AI_OFFICIAL_RESULT_BROWSER_CAPTURE_V1' and
        type(index.get('actual_request_count')) is int and 0<=index['actual_request_count']<=remaining and
        index.get('normal_ui_only') is True and type(index.get('manual_api_requests')) is int and
        index['manual_api_requests']==0 and started<=stamp(index['started_at'])<=stamp(index['completed_at'])<=now and
        type(index.get('responses')) is list and len(index['responses'])<=160 and
        type(index.get('cases')) is list and len(index['cases'])<=len(planned) and
        type(index.get('ledger')) is list and len(index['ledger'])<=2048,'BROWSER_CAPTURE_INDEX')
    count=index['actual_request_count'];responses=index['responses'];ledger=index['ledger']
    need(all(type(e) is dict and type(e.get('sequence')) is int and 1<=e['sequence']<=count for e in responses) and
        len({e['sequence'] for e in responses})==len(responses) and all(type(e) is dict for e in ledger),
        'BROWSER_CAPTURE_INDEX_COUNTER')
    requests=[e for e in ledger if 'sequence' in e]
    need(all(type(e['sequence']) is int and 1<=e['sequence']<=count for e in requests) and
        len(requests)==count and {e['sequence'] for e in requests}==set(range(1,count+1)),
        'BROWSER_CAPTURE_INDEX_COUNTER')
    for case in index['cases']:
        need(type(case) is dict and type(case.get('responses',[])) is list and len(case.get('responses',[]))<=160 and
            all(type(r) is dict and type(r.get('sequence')) is int and 1<=r['sequence']<=count
                for r in case.get('responses',[])),'BROWSER_CAPTURE_INDEX_COUNTER')


def _index_diagnostic(index,planned):
    """Allowlisted evidence of a returned index, not a source or label grant."""
    answer={k:index[k] for k in ('schema','started_at','completed_at','actual_request_count','normal_ui_only','manual_api_requests')}
    answer.update(diagnostic_projection_only=True,original_index_sha256=digest(index))
    reasons={'FINISHED','HTTP_ACCESS_DENIED','TIME_LIMIT','REQUEST_LIMIT','REQUEST_TIMEOUT','REQUEST_DISPATCH_FAILED',
        'CAPTURE_ERROR','CAPTURE_HOLD','BODY_BOUND','BYTE_GUARD_UNAVAILABLE','LEDGER_LIMIT'}
    answer['stop_reason']=index.get('stop_reason') if index.get('stop_reason') in reasons else 'UNRECOGNIZED_STOP_REASON'
    answer['stopped_host']=index.get('stopped_host') is True
    def facts(entry):
        value={}
        if type(entry) is not dict:return value
        for key in ('sequence','status','byte_count'):
            if type(entry.get(key)) is int and 0<=entry[key]<=2*1024*1024:value[key]=entry[key]
        for key in ('request_started_at','headers_received_at','response_received_at','body_captured_at'):
            try:
                if type(entry.get(key)) is str and len(entry[key])<=64:stamp(entry[key]);value[key]=entry[key]
            except (ValueError,TypeError):pass
        if entry.get('method') in ('GET','POST'):value['method']=entry['method']
        if entry.get('resource_type') in ('document','xhr','fetch','script','stylesheet'):value['resource_type']=entry['resource_type']
        return value
    answer['responses']=[facts(e) for e in index['responses']]
    answer['ledger']=[facts(e) for e in index['ledger']]
    known={(c['sport'],c['race_id']) for c in planned};answer['cases']=[]
    for entry in index['cases']:
        if type(entry) is not dict or (entry.get('sport'),entry.get('race_id')) not in known:continue
        case=dict(sport=entry['sport'],race_id=entry['race_id'],responses=[])
        for ref in entry.get('responses',[]) if type(entry.get('responses')) is list else []:
            if type(ref) is dict and ref.get('role') in ('identity','result','program','result_companion') and \
                type(ref.get('sequence')) is int and 0<ref['sequence']<=32:
                case['responses'].append(dict(role=ref['role'],sequence=ref['sequence']))
        answer['cases'].append(case)
    return answer


def _browser_quarantine(index,directory,*,maximum_json):
    """Retain bounded opaque originals before interpreting or admitting sources."""
    refs={};invalid=[]
    def reference(name,kind,limit):
        if type(name) is not str:invalid.append((None,kind,None,limit));return
        old=refs.get(name);refs[name]=(kind,min(limit,old[1])) if old else (kind,limit)
    for entry in index['responses']:
        for field,kind,limit in (('body_file','RESPONSE_BODY',MAX_BYTES),('metadata_file','HTTP_METADATA',65536),
                ('request_body_file','REQUEST_BODY',16384)):
            if entry.get(field) is not None:reference(entry[field],kind,limit)
    for case in index['cases']:
        dom=case.get('rendered_dom')
        if type(dom) is dict and dom.get('file') is not None:reference(dom['file'],'RENDERED_DOM',MAX_BYTES)
    if (directory/'capture-index.json').exists():refs['capture-index.json']=('ORIGINAL_INDEX',MAX_BYTES)
    value=dict(schema='RACE_AI_OFFICIAL_BROWSER_QUARANTINE_V1',complete=True,failure_code=None,
        returned_index_sha256=digest(index),files=[],inventory=[])
    inventory=[];used=0
    items=[('returned-index.canonical.json','CANONICAL_RETURNED_OBJECT',future.wire(index),MAX_BYTES)]
    items.extend((name,kind,None,limit) for name,(kind,limit) in refs.items());items.extend(invalid)
    for name,kind,body,limit in items:
        item=dict(file=name if type(name) is str and len(name)<=240 else None,kind=kind,status='REJECTED')
        try:
            need(type(name) is str,'QUARANTINE_FILE_REFERENCE')
            remaining=8*1024*1024-used;need(remaining>0,'QUARANTINE_RAW_BOUND')
            if body is None:body=_safe_file(directory,name,min(limit,remaining))
            need(type(body) is bytes and len(body)<=limit and len(body)<=remaining,'QUARANTINE_FILE_BOUND')
            used+=len(body);item.update(status='RETAINED',byte_count=len(body),source_sha256=sha256(body).hexdigest())
            value['files'].append(dict(file=name,kind=kind,byte_count=len(body),source_sha256=sha256(body).hexdigest(),raw_base64=b64(body)))
        except Exception:
            value.update(complete=False,failure_code='QUARANTINE_FILE_MISSING_UNSAFE_OR_BOUND')
        inventory.append(item)
    value.update(inventory=inventory,inventory_sha256=digest(inventory),referenced_file_count=len(items),retained_raw_bytes=used)
    if len(future.wire(value))>min(12*1024*1024,maximum_json):
        value.update(complete=False,failure_code='QUARANTINE_JSON_BOUND',files=[],inventory=[],retained_raw_bytes=0)
    return value


def _browser_complete_source_wire(index,responses,directory,*,started,now):
    """Require complete original transport before any narrow HTTP exception."""
    rows={entry['sequence']:entry for entry in index['responses']}
    numbered={entry['sequence']:entry for entry in index['ledger'] if 'sequence' in entry}
    need(len(responses)==index['actual_request_count'] and rows==numbered,'BROWSER_COMPLETE_SOURCE_LEDGER')
    names=[]
    for sequence,(raw,meta,request) in responses.items():
        entry=rows[sequence];headers=meta.get('headers')
        need(type(headers) is dict and all(type(k) is str and type(v) is str for k,v in headers.items()),'BROWSER_SOURCE_HEADERS')
        mime=[v for k,v in headers.items() if k.lower()=='content-type']
        need(len(mime)==1 and mime[0] and entry.get('content_type')==mime[0],'BROWSER_SOURCE_HEADERS')
        need(entry.get('method') in ('GET','POST') and entry.get('resource_type') in ('document','xhr','fetch','script','stylesheet') and
            meta.get('source_url')==meta.get('final_url')==entry.get('url') and
            meta.get('method')==meta.get('http_method')==entry['method'] and meta.get('resource_type')==entry['resource_type'] and
            type(entry.get('status')) is int and entry['status']==meta.get('status') and 100<=entry['status']<=599 and
            type(entry.get('byte_count')) is int and entry['byte_count']==meta.get('byte_count')==len(raw) and
            entry.get('source_sha256')==meta.get('source_sha256')==sha256(raw).hexdigest(),'BROWSER_SOURCE_WIRE_JOIN')
        policy._url(entry['url'])
        need(started<=stamp(entry['request_started_at'])==stamp(meta['fetched_at'])<=stamp(entry['headers_received_at'])<=
            stamp(entry['response_received_at'])==stamp(entry['body_captured_at'])==stamp(meta['response_received_at'])<=now,
            'BROWSER_SOURCE_WIRE_CLOCK')
        names.extend((entry['body_file'],entry['metadata_file']))
        if entry['method']=='POST':
            need(request is not None and entry.get('request_body_sha256')==meta.get('request_body_sha256')==sha256(request).hexdigest() and
                type(entry.get('request_content_type')) is str and entry['request_content_type'] and
                meta.get('request_content_type')==entry['request_content_type'] and
                meta.get('request_body_file')==entry.get('request_body_file'),'BROWSER_SOURCE_WIRE_REQUEST')
            names.append(entry['request_body_file'])
        else:
            need(not any(k in entry or k in meta for k in ('request_body_file','request_body_sha256','request_content_type')),
                'BROWSER_SOURCE_WIRE_REQUEST')
    for case in index['cases']:
        dom=case.get('rendered_dom')
        if dom is not None:
            need(type(dom) is dict,'BROWSER_DOM_BYTES');body=_safe_file(directory,dom['file'],MAX_BYTES)
            need(type(dom.get('byte_count')) is int and dom['byte_count']==len(body) and
                dom.get('source_sha256')==sha256(body).hexdigest() and started<=stamp(dom['captured_at'])<=now,'BROWSER_DOM_BYTES')
            names.append(dom['file'])
    need(len(names)==len(set(names)),'BROWSER_DUPLICATE_SOURCE_FILE')


def _browser_unselected_refund_404(entry,meta,*,index,planned,referenced):
    if meta.get('status')!=404 or entry['sequence'] in referenced or entry.get('method')!='GET' or \
            entry.get('resource_type') not in ('xhr','fetch'):return False
    url=urlsplit(meta['source_url'])
    if url.scheme!='https' or url.hostname not in ('autorace.jp','www.autorace.jp') or url.query or url.fragment:return False
    known={(c['sport'],c['race_id']) for c in planned}
    for case in index['cases']:
        if case.get('sport')!='autorace' or (case['sport'],case['race_id']) not in known:continue
        match=re.fullmatch(r'autorace:(\d{4}-\d{2}-\d{2}):([a-z]+):([1-9]|1[0-2])',case['race_id'])
        if match:
            day,venue,number=match.groups()
            if url.path=='/data/refund/'+date.fromisoformat(day).strftime('%Y%m%d')+'-'+venue+'-'+number.zfill(2)+'R-refund.csv':return True
    return False


def browser_sources(index,directory,planned,*,started,now,remaining):
    _index_header(index,planned,started=started,now=now,remaining=remaining)
    need(index.get('stopped_host') is not True and index.get('stop_reason')!='HTTP_ACCESS_DENIED' and
        not any(entry.get('status') in (401,403,429) for entry in index['ledger']),'BROWSER_ACCESS_DENIED')
    responses={};total=0;originals=[]
    for entry in index['responses']:
        need(type(entry) is dict and type(entry.get('sequence')) is int and entry['sequence'] not in responses,'BROWSER_RESPONSE_INDEX')
        raw=_safe_file(directory,entry['body_file'],MAX_BYTES);total+=len(raw);need(total<=32*1024*1024,'BROWSER_SOURCE_BOUND')
        meta=read_json_bytes(_safe_file(directory,entry['metadata_file'],65536))
        need(type(meta) is dict and type(meta.get('status')) is int and type(meta.get('byte_count')) is int and meta['byte_count']==len(raw) and
            meta.get('source_sha256')==sha256(raw).hexdigest(),'BROWSER_SOURCE_BYTES')
        need(meta['status'] not in (401,403,429),'BROWSER_ACCESS_DENIED')
        if meta.get('resource_type') not in ('script','stylesheet'):
            need(started<=stamp(meta['fetched_at'])<=stamp(meta['response_received_at'])<=now,'BROWSER_FRESH_SOURCE_CLOCK')
        request=None
        if entry.get('request_body_file'):
            request=_safe_file(directory,entry['request_body_file'],16384)
            need(meta.get('request_body_sha256')==sha256(request).hexdigest(),'BROWSER_REQUEST_BODY')
        if meta.get('resource_type') not in ('script','stylesheet'):
            original=dict(raw_base64=b64(raw),metadata=deepcopy(meta))
            if request is not None:original['request_body_base64']=b64(request)
            originals.append(original)
        responses[entry['sequence']]=(raw,meta,request)
    if any(meta['status']!=200 for _,meta,_ in responses.values()):
        _browser_complete_source_wire(index,responses,directory,started=started,now=now)
    referenced={ref['sequence'] for case in index['cases'] for ref in case.get('responses',[])}
    entries={entry['sequence']:entry for entry in index['responses']}
    for sequence,(_,meta,_) in responses.items():
        need(meta['status']==200 or _browser_unselected_refund_404(entries[sequence],meta,
            index=index,planned=planned,referenced=referenced),'BROWSER_SOURCE_HTTP_STATUS')
    known={(c['sport'],c['race_id']):c for c in planned};captures=[];states=[];seen_cases=set()
    for item in index['cases']:
        identity=(item.get('sport'),item.get('race_id'))
        need(type(item) is dict and identity in known and identity not in seen_cases,'BROWSER_FOREIGN_OR_DUPLICATE_CASE')
        seen_cases.add(identity)
        state=item.get('state');states.append(dict(sport=item['sport'],race_id=item['race_id'],state=state))
        if state!='CAPTURED':continue
        roles={}
        for ref in item['responses']:
            need(type(ref) is dict and ref.get('role') not in roles and ref.get('sequence') in responses,'BROWSER_CASE_RESPONSES')
            need(responses[ref['sequence']][1]['status']==200,'BROWSER_SELECTED_SOURCE_STATUS')
            roles[ref['role']]=responses[ref['sequence']]
        need('result' in roles and 'identity' in roles and type(item.get('rendered_dom')) is dict,'BROWSER_CASE_CLOSURE')
        dom=item['rendered_dom'];body=_safe_file(directory,dom['file'],MAX_BYTES)
        need(dom.get('byte_count')==len(body) and dom.get('source_sha256')==sha256(body).hexdigest() and
            started<=stamp(dom['captured_at'])<=now,'BROWSER_DOM_BYTES')
        raw,metadata,request=roles['result'];info,info_meta,info_request=roles['identity'];metadata=deepcopy(metadata)
        if item['sport']=='autorace':
            need(request is not None and info_request is not None,'BROWSER_ORIGINAL_POST_REQUIRED')
            dom_meta={k:dom[k] for k in ('source_url','final_url','captured_at','byte_count','source_sha256')}
            metadata['auto_result_context']=dict(schema=results.AUTO_CONTEXT,request_body_base64=b64(request),
                race_info_capture=dict(raw_base64=b64(info),metadata=info_meta,request_body_base64=b64(info_request)),
                rendered_dom_capture=dict(raw_base64=b64(body),metadata=dom_meta))
        else:
            need(type(item.get('browser_metadata')) is dict,'BROWSER_ACTUAL_PROVENANCE')
            metadata['keirin_result_archive_context']=dict(schema=results.KEIRIN_ARCHIVE_CONTEXT,
                identity_capture=dict(raw_base64=b64(info),metadata=info_meta),
                browser_capture=dict(metadata=deepcopy(item['browser_metadata']),rendered_dom_base64=b64(body)),payout_unit_capture=None)
        captures.append((item['sport'],item['race_id'],dict(raw_base64=b64(raw),metadata=metadata)))
    return captures,states,originals


def _parse(capture,native,sport,*,now,allow_order_only):
    if sport=='horse':from race_ai.jra_official_result_adapter import parse_result
    elif sport=='autorace':from race_ai.autorace_official_result_adapter import parse_result
    else:from race_ai.keirin_official_result_adapter import parse_result
    options=dict(allow_order_only=True) if allow_order_only and sport!='horse' else {}
    return parse_result(_blob(capture['raw_base64']),capture['metadata'],frozen_native_payload=native,now=now,
        source_rights_ref=policy.official_rights_ref(sport),**options)


def _status(journal,manifest,*,ready=False,state='NO_NEW_AUTHENTICATED_RESULTS'):
    counts=Counter(c['state'] for c in journal['cases']);attempts=journal['attempts']
    browser=journal.get('browser_attempt')
    uncertain=browser is not None and browser['state']=='RESERVED'
    if manifest['schema'] in (SCHEMA_V2,SCHEMA_V3):uncertain=uncertain or any(a['state']=='RESERVED' for a in attempts)
    requests=len(attempts)+(browser.get('actual_request_count',0) if browser else 0)
    sports={case['sport'] for case in journal['cases']};normal={sport:0 for sport in sports}
    for case in journal['cases']:
        if case['state'] in ('settled','rank_confirmed') or case.get('confirmed_result_status') in ('settled','rank_confirmed'):
            normal[case['sport']]+=1
    status=dict(_lineage(manifest),state=state,ready=ready,source_requests=None if uncertain else requests,
        source_requests_upper_bound=journal['maximum_requests'],collection_source_requests=None if uncertain else requests,
        planned_case_count=len(journal['cases']),confirmed_case_count=counts['ALREADY_CONFIRMED'],
        not_due_case_count=counts['NOT_DUE'],no_published_link_case_count=counts['NO_PUBLISHED_RESULT_LINK'],
        request_limited_case_count=counts['REQUEST_LIMIT'],denied_source_count=sum(a['state']=='DENIED' for a in attempts)+
            sum(e.get('status') in (401,403,429) for e in journal.get('browser_index',{}).get('ledger',[]) if type(e) is dict),
        source_failure_case_count=sum(v for k,v in counts.items() if k.startswith('HOLD_')),
        journal_encrypted_local_only=True,independent_journal_artifact_receipt_verified=False,
        source_request_count_semantics=('STARTED_OR_DURABLY_RESERVED_ATTEMPTS' if browser and
            browser['state'] in ('INTERRUPTED','INDEX_RECEIVED','REJECTED') else 'VERIFIED_REQUEST_ATTEMPTS' if not uncertain else 'UNKNOWN_WITH_RESERVED_LIMIT'),
        independent_result_artifact_receipt_verified=False,artifact_retention_days=7,
        normal_confirmed_cases_by_sport=normal,normal_eight_case_requirement_met=bool(sports) and all(n>=8 for n in normal.values()))
    if 'prior_static_cache' in journal:
        proof=_prior_static_lineage(journal['prior_static_cache'])
        status.update(prior_static_cache_entry_count=proof['cache_entry_count'],prior_static_cache_sha256=proof['cache_sha256'],
            prior_static_cache_source_journal_count=len(proof['source_journals']))
    return status


def collect(root,env,manifest,*,clock=utc_now,sleeper=time.sleep,opener=None,browser=browser_capture,recovery_authorization=None,
            before_source=None):
    key=state_key('production');now=clock();_manifest(manifest,now)
    need(manifest['schema']!=SCHEMA_V3 or recovery_authorization is not None,'HISTORICAL_REVIEWED_AUTHORITY_REQUIRED')
    plan=load_plan(manifest,key=key,now=now)
    recovery=None
    if recovery_authorization is not None:
        from race_ai.all_existing_model_official_recovery import ValidatedRecovery
        from race_ai.all_existing_model_official_continuation import ValidatedContinuation
        from race_ai.all_existing_model_official_probe16 import ValidatedProbe16
        need(type(recovery_authorization) in (ValidatedRecovery,ValidatedContinuation,ValidatedProbe16),'VALIDATED_RECOVERY_REQUIRED')
        recovery=recovery_authorization.validate_collector(manifest,plan,env,now)
    need(before_source is None or recovery is not None and callable(before_source),'REVIEWED_SOURCE_CALLBACK')
    private_prior_cache={}
    prior=prior_journals(manifest,now=now,key=key,recovery_authorization=recovery_authorization,
        private_static_cache_out=private_prior_cache)
    need(not root.exists() and not any(p.is_symlink() for p in (root,*root.parents)), 'OUTPUT_EXISTS_DO_NOT_RESET')
    natives=freeze.frozen_inputs(manifest,now=now);known,_=results._frozen(natives)
    previous=checkpoints(manifest,natives,now=now,key=key)
    for case in plan['cases']:
        native=known.get((case['sport'],_race_key(case['race_id'],case['sport'])))
        need(native is not None,'CASE_WITHOUT_NATIVE_INPUT');route=case['route']
        if case['sport']=='horse':
            need((route['card_url'],policy.official_rights_ref('horse')) in _sources(native),'CARD_NOT_FROM_FROZEN_SOURCE')
            if route['result_url'] is not None:
                need(published_result(route['link_capture'],native,now)==route['result_url'],'LITERAL_RESULT_LINK_PROOF')
        else:
            parts=urlsplit(route['ui_entry_url']);venue=native['snapshot']['race']['venue']
            need((case['sport']=='autorace' and parts.path=='/race_info/Live/'+venue or
                case['sport']=='keirin' and parts.path=='/pc/top') and not parts.query,'NORMAL_UI_ENTRY_CASE')
    work=root.with_name(root.name+'.work');need(not work.exists(),'UNCERTAIN_PRIOR_EPOCH_DO_NOT_RESET');work.mkdir(mode=0o700)
    journal=dict(schema=JOURNAL,execution_day=manifest['execution_day'],manifest_sha256=digest(manifest),
        maximum_requests=plan['maximum_requests'],epoch_started_at=now.isoformat(),attempts=[],captures=[],cases=[])
    if manifest['schema'] in (SCHEMA_V2,SCHEMA_V3):
        journal.update(schema=journal_schema(manifest),manifest=deepcopy(manifest),workflow_run_id=env['run_id'],
            code_sha=env['head_sha'],collection_plan_sha256=manifest['plan_sha256'])
    if manifest['schema']==SCHEMA_V3:journal['target_event_day']=manifest['target_event_day']
    if recovery is not None:journal['recovery_authorization']=deepcopy(recovery)
    journal_path=root.with_name(root.name+'.collection.enc')
    def persist():save(journal_path,seal_forecasts(journal,run_id=str(env['run_id']),round_no=900006,key=key),replace=journal_path.exists())
    budget=Budget(plan['maximum_requests'],journal,persist,clock,sleeper,opener,before_source=before_source);due=[]
    for case in plan['cases']:
        identity=(case['sport'],_race_key(case['race_id'],case['sport']));native=known.get(identity)
        need(native is not None and native['snapshot']['race']['event_date_jst']==target_event_day(manifest),'CASE_WITHOUT_NATIVE_INPUT')
        race=native['snapshot']['race'];cutoff=stamp(race['sales_cutoff_at'])
        entry=dict(sport=case['sport'],race_id=case['race_id'],state='NOT_DUE');journal['cases'].append(entry)
        old=previous.get(identity)
        if old is not None and old['status'] in ('settled','rank_confirmed','special'):
            entry.update(state='ALREADY_CONFIRMED',confirmed_result_status=old['status'])
        elif now>=cutoff+timedelta(seconds=plan['result_wait_seconds']):
            entry['state']='DUE';due.append((case,native,entry))
    persist();captures=[];observations=[];browser_cases=[];native_by_case={}
    for case,native,entry in due:
        sport=case['sport'];route=case['route'];race=native['snapshot']['race']
        if sport!='horse':
            venue=race['venue'];parts=urlsplit(route['ui_entry_url'])
            need((sport=='autorace' and parts.path=='/race_info/Live/'+venue or
                sport=='keirin' and parts.path=='/pc/top') and not parts.query,'NORMAL_UI_ENTRY_CASE')
            canonical=_race_key(case['race_id'],sport)
            request=dict(sport=sport,race_id=canonical,ui_entry_url=route['ui_entry_url'],expected_date=race['event_date_jst'],
                venue=venue,race_no=int(_race_key(case['race_id'],sport).rsplit(':',1)[1]),due_at=race['sales_cutoff_at'])
            if route['ui_venue_name'] is not None:request['ui_venue_name']=route['ui_venue_name']
            if 'place_code' in route:request['place_code']=route['place_code']
            browser_cases.append(request);native_by_case[(sport,canonical)]=(native,entry);continue
        need((route['card_url'],policy.official_rights_ref('horse')) in _sources(native),'CARD_NOT_FROM_FROZEN_SOURCE')
        if budget.remaining<=0:entry['state']='REQUEST_LIMIT';continue
        if sport in budget.denied:entry['state']='HOLD_HOST_DENIED';continue
        if route['result_url'] is None:
            card=budget.get(route['card_url'])
            if card is None:entry['state']='HOLD_CARD_SOURCE_UNAVAILABLE';continue
            try:target=published_result(card,native,clock())
            except (ValueError,KeyError,TypeError):entry['state']='HOLD_PUBLISHED_ROUTE_UNVERIFIED';persist();continue
        else:
            target=published_result(route['link_capture'],native,clock())
            need(target==route['result_url'],'LITERAL_RESULT_LINK_PROOF')
            journal['captures'].append(deepcopy(route['link_capture']));persist()
        if target is None:entry['state']='NO_PUBLISHED_RESULT_LINK';continue
        if budget.remaining<=0:entry['state']='REQUEST_LIMIT';continue
        capture=budget.get(target)
        if capture is None:entry['state']='HOLD_RESULT_SOURCE_UNAVAILABLE';continue
        try:label=_parse(capture,native,sport,now=clock(),allow_order_only=manifest['allow_order_only'])
        except (ValueError,KeyError,TypeError):entry['state']='HOLD_RESULT_PARSE';continue
        captures.append(capture);observations.append(label);entry['state']=label['status'];persist()
    if browser_cases:
        if budget.remaining<=0:
            for _,entry in native_by_case.values():entry['state']='REQUEST_LIMIT'
        else:
            budget.wait();started=clock();need(started>=now,'CLOCK_REGRESSED_BEFORE_BROWSER');remaining=budget.remaining
            if recovery_authorization is not None:
                recovery_authorization.validate_collector(manifest,plan,env,started)
            runtime_cache=None
            if private_prior_cache.get('entries'):
                from race_ai.all_existing_model_prior_static_cache import merge_static_cache
                sports={case['sport'] for case in browser_cases}
                previous_static=[entry for entry in plan.get('static_cache',[]) if policy._url(entry['metadata']['source_url'])[0] in sports]
                additions=[entry for entry in private_prior_cache['entries'] if policy._url(entry['metadata']['source_url'])[0] in sports]
                if additions:
                    # The MAC-bound plan stays exact. Only this private runtime
                    # browser request receives already-authenticated originals.
                    runtime_cache=merge_static_cache(previous_static,additions,now=started,sports=sports)
                    journal['prior_static_cache']=deepcopy(private_prior_cache['lineage'])
            journal['browser_attempt']=dict(state='RESERVED',reserved_request_limit=remaining,started_at=started.isoformat());persist()
            browser_plan=dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_PLAN_V1',cases=browser_cases,request_budget=remaining,
                not_before=now.isoformat())
            if recovery is not None:browser_plan['not_after']=recovery['expires_at']
            if manifest['schema']==SCHEMA_V3:
                midnight=datetime.fromisoformat(manifest['execution_day']).replace(tzinfo=JST)+timedelta(days=1)
                browser_plan['not_after']=min(midnight,stamp(browser_plan.get('not_after',midnight.isoformat()))).isoformat()
            if runtime_cache is not None:browser_plan['static_cache']=runtime_cache
            elif 'static_cache' in plan:
                sports={case['sport'] for case in browser_cases}
                browser_plan['static_cache']=[entry for entry in plan['static_cache']
                    if policy._url(entry['metadata']['source_url'])[0] in sports]
            directory=work/'browser';stage='PROCESS';index=None
            def process_diagnostic(value):
                journal['browser_process_diagnostic']=deepcopy(value);persist()
            try:
                if before_source is not None:before_source()
                index=(browser(browser_plan,directory,diagnostic_sink=process_diagnostic) if browser is browser_capture
                    else browser(browser_plan,directory));finished=clock();stage='INDEX_VALIDATION'
                if index.get('schema')=='RACE_AI_OFFICIAL_RESULT_BROWSER_INTERRUPTED_V1':
                    checkpoint=index['checkpoint'];count=checkpoint['actual_request_count']
                    need(type(count) is int and 0<count<=remaining and
                        started<=stamp(checkpoint['started_at'])<=stamp(checkpoint['last_updated_at'])<=finished,
                        'BROWSER_INTERRUPTED_CLOCK')
                    budget.used+=count;journal['browser_attempt'].update(state='INTERRUPTED',
                        actual_request_count=count,completed_at=finished.isoformat())
                    journal['browser_request_checkpoint']=checkpoint
                    for _,entry in native_by_case.values():entry['state']='HOLD_BROWSER_SOURCE_INTERRUPTED'
                    persist()
                    index=None
                if index is None:raise ValueError('ALL_MODEL_OFFICIAL_COLLECT_BROWSER_INTERRUPTED')
                _index_header(index,browser_cases,started=started,now=finished,remaining=remaining)
                count=index['actual_request_count'];budget.used+=count;budget.last=finished
                journal['browser_attempt'].update(state='INDEX_RECEIVED',actual_request_count=count,completed_at=finished.isoformat())
                journal['browser_index']=_index_diagnostic(index,browser_cases);persist();stage='QUARANTINE'
                journal['browser_quarantine']=_browser_quarantine(index,directory,
                    maximum_json=max(0,MAX_PLAIN-len(future.wire(journal))-4096))
                persist();need(journal['browser_quarantine']['complete'],'BROWSER_QUARANTINE_INCOMPLETE');stage='SOURCE_VALIDATION'
                found,states,originals=browser_sources(index,directory,browser_cases,started=started,now=finished,remaining=remaining)
                journal['browser_attempt'].update(state='COMPLETE',stop_reason=index['stop_reason']);journal['browser_captures']=originals
                for value in states:native_by_case[(value['sport'],value['race_id'])][1]['state']=value['state']
                for sport,race_id,capture in found:
                    native,entry=native_by_case[(sport,race_id)]
                    journal['captures'].append(capture)
                    try:label=_parse(capture,native,sport,now=finished,allow_order_only=manifest['allow_order_only'])
                    except (ValueError,KeyError,TypeError):entry['state']='HOLD_RESULT_PARSE';continue
                    captures.append(capture);observations.append(label);entry['state']=label['status']
            except Exception as exc:
                journal['browser_failure']=dict(stage=stage,**future.safe_diagnostic(exc))
                if isinstance(exc,BrowserCaptureFailure):journal['browser_process_diagnostic']=deepcopy(exc.process_diagnostic)
                if journal['browser_attempt']['state']=='INDEX_RECEIVED':journal['browser_attempt']['state']='REJECTED'
                if journal['browser_attempt']['state']!='INTERRUPTED':
                    for _,entry in native_by_case.values():entry['state']='HOLD_BROWSER_SOURCE_UNVERIFIED'
            persist()
    if not observations:
        status=dict(_status(journal,manifest),**prior);status['collection_journal_sha256']=sha256(_read(journal_path,MAX_WIRE)).hexdigest();return status
    generated=clock();need(generated.astimezone(JST).date().isoformat()==manifest['execution_day'],'DAY_ELAPSED')
    payload=results.build_result_payload(captures,observations,run_id=env['run_id'],code_sha=env['head_sha'],generated_at=generated,
        day_jst=target_event_day(manifest),frozen_native_payloads=natives,allow_order_only=manifest['allow_order_only'])
    cipher=results.seal_results(payload,round_no=ROUND,frozen_native_payloads=natives,key=key,allow_order_only=manifest['allow_order_only'])
    need(freeze._local_payload(cipher,env,key=key)==payload,'LOCAL_ENCRYPTED_REPLAY')
    root.mkdir(mode=0o700,exist_ok=False);_write(root/'results.enc',cipher);need(freeze._private_local(root)==cipher,'LOCAL_READBACK')
    persist();status=dict(_status(journal,manifest,ready=True,state='OFFICIAL_RESULTS_ENCRYPTED_LOCAL_ONLY'),**prior)
    status.update(freeze._counts(payload,natives,now=clock(),allow_order_only=manifest['allow_order_only']),
        result_cipher_sha256=sha256(cipher).hexdigest(),result_payload_sha256=digest(payload),encrypted_readback_verified=True,
        collection_journal_sha256=sha256(_read(journal_path,MAX_WIRE)).hexdigest())
    return status


def readback(ident,root,env,manifest,*,clock=utc_now):
    key=state_key('production');now=clock();_manifest(manifest,now);load_plan(manifest,key=key,now=now)
    natives=freeze.frozen_inputs(manifest,now=now);cipher=freeze._private_local(root);payload=freeze._local_payload(cipher,env,key=key)
    from race_ai.all_existing_model_runtime import _private_file
    path=root.with_name(root.name+'.generation.json');_private_file(path);previous=read_json_bytes(_read(path,128*1024))
    need(previous.get('schema')==STATUS and previous.get('ready') is True and previous.get('workflow_run_id')==env['run_id'] and
        previous.get('expected_head_sha')==env['head_sha'] and all(previous.get(k)==v for k,v in _lineage(manifest).items()) and
        previous.get('result_cipher_sha256')==sha256(cipher).hexdigest() and previous.get('result_payload_sha256')==digest(payload),
        'LOCAL_GENERATION_PROOF')
    journal_path=root.with_name(root.name+'.collection.enc');_private_file(journal_path);journal_raw=_read(journal_path,MAX_WIRE)
    journal=open_forecasts(journal_raw,key=key);header=forecast_header(journal_raw)
    need(sha256(journal_raw).hexdigest()==previous.get('collection_journal_sha256') and header['run_id']==str(env['run_id']) and
        header['round_no']==900006 and journal.get('schema')==journal_schema(manifest) and
        journal.get('manifest_sha256')==digest(manifest),
        'LOCAL_COLLECTION_JOURNAL')
    actual=future.metadata(ident);need(actual.get('id')==ident and actual.get('name')==
        f'all-existing-official-results-{env["run_id"]}-{ROUND}','ACTUAL_RESULT_ARTIFACT')
    raw=future.gh('actions/artifacts/'+str(ident)+'/zip')
    admitted=results.observations_from_official_result_artifact(raw,actual,now=now,expected_run_id=env['run_id'],
        expected_head_sha=env['head_sha'],frozen_native_payloads=natives,key=key,allow_order_only=manifest['allow_order_only'])
    need(results._cipher(raw)==cipher and admitted['receipt']['original_payload_sha256']==digest(payload),'ACTUAL_CIPHER_READBACK')
    counts=freeze._counts(payload,natives,now=now,allow_order_only=manifest['allow_order_only'])
    need(all(previous.get(k)==v for k,v in counts.items()),'ACTUAL_COUNTS_READBACK')
    return dict(previous,**counts,state='OFFICIAL_RESULTS_ACTUAL_ARTIFACT_VERIFIED',ready=True,source_requests=0,
        artifact_id=ident,artifact_digest=actual['digest'],saved_at=actual['created_at'],expires_at=actual['expires_at'],
        independent_result_artifact_receipt_verified=True)


def readback_journal(ident,root,env,manifest,*,clock=utc_now):
    """Authenticate the separate actual journal upload, including denied epochs."""
    key=state_key('production');now=clock();_manifest(manifest,now)
    from race_ai.all_existing_model_runtime import _private_file
    path=root.with_name(root.name+'.collection.enc');_private_file(path);cipher=_read(path,MAX_WIRE)
    local=_journal_origin(cipher,key=key,run_id=env['run_id'],head_sha=env['head_sha'],now=now)
    need(local['manifest']==manifest,'LOCAL_JOURNAL_MANIFEST')
    actual=future.metadata(ident)
    pin=dict(id=ident,digest=actual.get('digest'),run_id=env['run_id'],head_sha=env['head_sha']);_pins([pin])
    # The archive reader obtains actual metadata independently at its boundary.
    body,remote,receipt=_journal_artifact(pin,now=now,key=key)
    need(cipher==remote and body==local,'ACTUAL_JOURNAL_READBACK')
    return dict(independent_journal_artifact_receipt_verified=True,source_requests=0,
        journal_artifact_id=ident,journal_artifact_digest=receipt['digest'],journal_saved_at=receipt['created_at'],
        journal_expires_at=receipt['expires_at'],collection_journal_sha256=sha256(cipher).hexdigest())


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',required=True);parser.add_argument('--out-dir',required=True)
    parser.add_argument('--readback-artifact',type=int);parser.add_argument('--readback-journal-artifact',type=int)
    args=parser.parse_args(argv)
    status=dict(schema=STATUS,state='HOLD_OFFICIAL_RESULT_COLLECTION',ready=False,source_requests=0,plaintext_published=False,
        public_redistribution=False,provider_model_training_permission_confirmed=False,production_promoted=False,actual_purchases=False,
        missing_results_are_not_losses=True,artifact_retention_days=7,independent_result_artifact_receipt_verified=False)
    root=None;manifest=None
    try:
        env=future.environment();root=future.output_path(args.out_dir,env);state_key('production')
        status.update(workflow_run_id=env['run_id'],expected_head_sha=env['head_sha'],artifact_name=
            f'all-existing-official-results-{env["run_id"]}-{ROUND}')
        manifest=load_manifest(args.input,now=utc_now())
        if manifest['schema'] in (SCHEMA_V2,SCHEMA_V3):
            status['journal_artifact_name']='official-result-collection-journal-'+str(env['run_id'])
        if args.readback_journal_artifact is not None and args.readback_artifact is None:
            path=root.with_name(root.name+'.status.json')
            if path.exists():
                previous=read_json_bytes(_read(path,128*1024))
                need(previous.get('workflow_run_id')==env['run_id'] and previous.get('expected_head_sha')==env['head_sha'] and
                    all(previous.get(k)==v for k,v in _lineage(manifest).items()),'LOCAL_JOURNAL_STATUS')
                status.update(previous)
        elif args.readback_artifact is None:status.update(collect(root,env,manifest))
        else:status.update(readback(args.readback_artifact,root,env,manifest))
        if args.readback_journal_artifact is not None:
            status.update(readback_journal(args.readback_journal_artifact,root,env,manifest,clock=utc_now))
    except Exception as exc:
        status.update(state='HOLD_OFFICIAL_RESULT_COLLECTION',ready=False,**future.safe_diagnostic(exc))
        if root is not None and manifest is not None:
            try:
                journal_path=root.with_name(root.name+'.collection.enc')
                if journal_path.exists():
                    journal=open_forecasts(_read(journal_path,MAX_WIRE),key=state_key('production'))
                    status.update(_status(journal,manifest,state='HOLD_OFFICIAL_RESULT_COLLECTION'))
            except Exception:status.update(source_requests=None)
    if root is not None:
        try:
            if args.readback_artifact is None and args.readback_journal_artifact is None and status['ready']:_write(root.with_name(root.name+'.generation.json'),future.wire(status))
            path=root.with_name(root.name+'.status.json');save(path,future.wire(status),replace=path.exists())
        except Exception as exc:status.update(state='HOLD_OFFICIAL_RESULT_COLLECTION',ready=False,**future.safe_diagnostic(exc))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('ready='+str(status['ready']).lower()+'\n')
            if status.get('artifact_name'):output.write('artifact_name='+status['artifact_name']+'\n')
            if status.get('journal_artifact_name'):output.write('journal_artifact_name='+status['journal_artifact_name']+'\n')
    print(json.dumps(status,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
