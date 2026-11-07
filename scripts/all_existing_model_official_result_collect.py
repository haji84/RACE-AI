"""One explicit owner-scoped official-result collection epoch.

Authenticate encrypted plans/native inputs/checkpoints before provider reads.
Only due unconfirmed cases are collected. Published links and normal UI are
read-only source routes, never a claim of public API or provider ML permission.
"""
import argparse
import base64
from collections import Counter
from copy import deepcopy
from datetime import datetime,timedelta,timezone
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
PLAN='RACE_AI_OFFICIAL_RESULT_COLLECTION_PLAN_V1'
STATUS='RACE_AI_OFFICIAL_RESULT_COLLECTION_COUNTS_V1'
JOURNAL='RACE_AI_OFFICIAL_RESULT_COLLECTION_JOURNAL_V1'
JOURNAL_V2='RACE_AI_OFFICIAL_RESULT_COLLECTION_JOURNAL_V2'
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
        value.get('schema')==SCHEMA_V2 and set(value)==fields|{'prior_journal_artifacts'}),'MANIFEST_SCHEMA')
    need(value['execution_day']==now.astimezone(JST).date().isoformat() and
        type(value['allow_order_only']) is bool,'EXECUTION_DAY_OR_MODE')
    hashed=value['plan_sha256']
    need(type(hashed) is str and re.fullmatch('[a-f0-9]{64}',hashed) and
        value['plan_path']=='audit/state/official-result-collection-plan-'+hashed+'.enc','PLAN_CIPHER_PATH')
    natives=_pins(value['native_artifacts']);checkpoints=_pins(value['checkpoint_artifacts'],empty=True)
    journals=_pins(value['prior_journal_artifacts'],empty=True) if value['schema']==SCHEMA_V2 else set()
    need(not natives&checkpoints and not journals&(natives|checkpoints) and
        len(natives)+len(checkpoints)+len(journals)<=32,'ARTIFACT_PIN_CONFLICT')
    return value


def load_manifest(path,*,now):return _manifest(read_json_bytes(_read(Path(path),32768)),now)


def load_plan(manifest,*,key,now):
    raw=_repository_file(ROOT/manifest['plan_path'],MAX_WIRE)
    need(sha256(raw).hexdigest()==manifest['plan_sha256'],'PLAN_CIPHER_SHA')
    value=open_forecasts(raw,key=key)
    fields={'schema','execution_day','cases','terms_manifest','maximum_requests','result_wait_seconds'}
    need(type(value) is dict and fields<=set(value)<=fields|{'static_cache'} and value['schema']==PLAN and
        value['execution_day']==manifest['execution_day'] and len(future.wire(value))<=MAX_PLAIN,'PLAN_SCHEMA')
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
        body.get('schema')==JOURNAL_V2,'PRIOR_JOURNAL_ORIGIN_NOT_REPLAYABLE')
    fields={'schema','execution_day','manifest_sha256','maximum_requests','epoch_started_at','attempts','captures','cases',
        'manifest','workflow_run_id','code_sha','collection_plan_sha256'}
    need(fields<=set(body)<=fields|{'browser_attempt','browser_index','browser_captures','browser_request_checkpoint'} and
        type(body['workflow_run_id']) is int and body['workflow_run_id']==run_id and body['code_sha']==head_sha,
        'JOURNAL_ORIGIN_RUN')
    epoch=stamp(body['epoch_started_at']);original=_manifest(body['manifest'],epoch)
    need(epoch<=now and (saved_at is None or epoch<=saved_at+timedelta(seconds=1)) and
        body['execution_day']==original['execution_day'] and body['manifest_sha256']==digest(original) and
        original['schema']==SCHEMA_V2 and body['collection_plan_sha256']==original['plan_sha256'] and
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


def prior_journals(manifest,*,now,key):
    """Guard only explicitly pinned epochs; never infer that unlisted history is safe."""
    if manifest['schema']!=SCHEMA_V2:return {}
    receipts=[];latest=None
    for pin in manifest['prior_journal_artifacts']:
        body,cipher,actual=_journal_artifact(pin,now=now,key=key);epoch=stamp(body['epoch_started_at'])
        latest=max(latest,epoch) if latest is not None else epoch
        attempts=body['attempts'];browser=body.get('browser_attempt')
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
        need(not any(a['state']=='RESERVED' for a in attempts) and
            (browser is None or type(browser) is dict and browser.get('state')=='COMPLETE' and
             type(browser.get('actual_request_count')) is int and
             0<=browser['actual_request_count']<=body['maximum_requests']-len(attempts)),
            'PRIOR_JOURNAL_UNCERTAIN_REQUIRES_OWNER_REVIEW')
        if browser is not None:
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
    need(latest is None or now-latest>=timedelta(seconds=3600),'PRIOR_EPOCH_TOO_RECENT')
    return dict(prior_journal_artifact_count=len(receipts),prior_journal_receipts_sha256=digest(receipts),
        prior_journal_guard_scope='EXPLICIT_PINNED_JOURNALS_ONLY',minimum_epoch_interval_seconds=3600)


def _lineage(manifest):
    return dict(collection_plan_sha256=manifest['plan_sha256'],manifest_sha256=digest(manifest),
        native_artifact_pins_sha256=digest(manifest['native_artifacts']),
        checkpoint_artifact_pins_sha256=digest(manifest['checkpoint_artifacts']),
        native_input_artifact_count=len(manifest['native_artifacts']),allow_order_only=manifest['allow_order_only'])


class Budget:
    def __init__(self,maximum,journal,persist,clock,sleeper,opener):
        self.maximum=maximum;self.journal=journal;self.persist=persist;self.clock=clock;self.sleeper=sleeper
        self.opener=opener or build_opener(policy._NoRedirect()).open;self.used=0;self.last=None;self.last_mono=None;self.denied=set()
        self.epoch=stamp(journal['epoch_started_at'])
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
        self.wait();started=self.clock()
        need(started>=self.epoch,'CLOCK_REGRESSED_BEFORE_SOURCE')
        need(started.astimezone(JST).date().isoformat()==self.journal['execution_day'],'DAY_ELAPSED')
        entry=dict(url=url,started_at=started.isoformat(),state='RESERVED',http_status=None)
        self.journal['attempts'].append(entry);self.used+=1;self.persist();response=None
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


def browser_capture(plan,directory):
    request=directory.with_name(directory.name+'.plan.json');_write(request,future.wire(plan))
    env=dict(os.environ)
    for name in list(env):
        if name=='RACE_AI_STATE_KEY' or name in ('GH_TOKEN','GITHUB_TOKEN') or name.startswith(('ACTIONS_','GIT_CONFIG_VALUE_')):
            env.pop(name,None)
    try:
        subprocess.run(['node',str(ROOT/'scripts/official_result_browser_capture.cjs'),'--plan',str(request),
            '--out-dir',str(directory)],capture_output=True,timeout=100,env=env,check=False)
    except subprocess.TimeoutExpired:pass
    if (directory/'capture-index.json').exists():
        return read_json_bytes(_safe_file(directory,'capture-index.json',4*1024*1024))
    checkpoints=[]
    if directory.is_dir():
        for path in directory.iterdir():
            match=re.fullmatch(r'request-ledger-([0-9]{3})\.json',path.name)
            if match and 1<=int(match[1])<=32:checkpoints.append((int(match[1]),path.name))
    need(bool(checkpoints),'BROWSER_CAPTURE_PROCESS')
    number,name=max(checkpoints)
    checkpoint=read_json_bytes(_safe_file(directory,name,4*1024*1024))
    need(type(checkpoint) is dict and checkpoint.get('schema')=='RACE_AI_OFFICIAL_RESULT_BROWSER_REQUEST_CHECKPOINT_V1' and
        type(checkpoint.get('actual_request_count')) is int and checkpoint['actual_request_count']==number and
        type(checkpoint.get('maximum_requests')) is int and checkpoint['maximum_requests']==plan['request_budget'] and
        number<=plan['request_budget'] and type(checkpoint.get('ledger')) is list and len(checkpoint['ledger'])<=2048 and
        stamp(plan['not_before'])<=stamp(checkpoint['started_at'])<=stamp(checkpoint['last_updated_at']),
        'BROWSER_INTERRUPTED_CHECKPOINT')
    return dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_INTERRUPTED_V1',checkpoint=checkpoint)


def browser_sources(index,directory,planned,*,started,now,remaining):
    need(type(index) is dict and index.get('schema')=='RACE_AI_OFFICIAL_RESULT_BROWSER_CAPTURE_V1' and
        type(index.get('actual_request_count')) is int and 0<=index['actual_request_count']<=remaining and
        index.get('normal_ui_only') is True and index.get('manual_api_requests')==0 and
        started<=stamp(index['started_at'])<=stamp(index['completed_at'])<=now and
        type(index.get('responses')) is list and len(index['responses'])<=160 and
        type(index.get('cases')) is list and len(index['cases'])<=len(planned),'BROWSER_CAPTURE_INDEX')
    responses={};total=0;originals=[]
    for entry in index['responses']:
        need(type(entry) is dict and type(entry.get('sequence')) is int and entry['sequence'] not in responses,'BROWSER_RESPONSE_INDEX')
        raw=_safe_file(directory,entry['body_file'],MAX_BYTES);total+=len(raw);need(total<=32*1024*1024,'BROWSER_SOURCE_BOUND')
        meta=read_json_bytes(_safe_file(directory,entry['metadata_file'],65536))
        need(type(meta) is dict and meta.get('status')==200 and meta.get('byte_count')==len(raw) and
            meta.get('source_sha256')==sha256(raw).hexdigest(),'BROWSER_SOURCE_BYTES')
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
    if manifest['schema']==SCHEMA_V2:uncertain=uncertain or any(a['state']=='RESERVED' for a in attempts)
    requests=len(attempts)+(browser.get('actual_request_count',0) if browser else 0)
    sports={case['sport'] for case in journal['cases']};normal={sport:0 for sport in sports}
    for case in journal['cases']:
        if case['state'] in ('settled','rank_confirmed') or case.get('confirmed_result_status') in ('settled','rank_confirmed'):
            normal[case['sport']]+=1
    return dict(_lineage(manifest),state=state,ready=ready,source_requests=None if uncertain else requests,
        source_requests_upper_bound=journal['maximum_requests'],collection_source_requests=None if uncertain else requests,
        planned_case_count=len(journal['cases']),confirmed_case_count=counts['ALREADY_CONFIRMED'],
        not_due_case_count=counts['NOT_DUE'],no_published_link_case_count=counts['NO_PUBLISHED_RESULT_LINK'],
        request_limited_case_count=counts['REQUEST_LIMIT'],denied_source_count=sum(a['state']=='DENIED' for a in attempts)+
            sum(e.get('status') in (401,403,429) for e in journal.get('browser_index',{}).get('ledger',[]) if type(e) is dict),
        source_failure_case_count=sum(v for k,v in counts.items() if k.startswith('HOLD_')),
        journal_encrypted_local_only=True,independent_journal_artifact_receipt_verified=False,
        source_request_count_semantics=('STARTED_OR_DURABLY_RESERVED_ATTEMPTS' if browser and
            browser['state']=='INTERRUPTED' else 'VERIFIED_REQUEST_ATTEMPTS' if not uncertain else 'UNKNOWN_WITH_RESERVED_LIMIT'),
        independent_result_artifact_receipt_verified=False,artifact_retention_days=7,
        normal_confirmed_cases_by_sport=normal,normal_eight_case_requirement_met=bool(sports) and all(n>=8 for n in normal.values()))


def collect(root,env,manifest,*,clock=utc_now,sleeper=time.sleep,opener=None,browser=browser_capture):
    key=state_key('production');now=clock();_manifest(manifest,now);plan=load_plan(manifest,key=key,now=now)
    prior=prior_journals(manifest,now=now,key=key)
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
    if manifest['schema']==SCHEMA_V2:
        journal.update(schema=JOURNAL_V2,manifest=deepcopy(manifest),workflow_run_id=env['run_id'],
            code_sha=env['head_sha'],collection_plan_sha256=manifest['plan_sha256'])
    journal_path=root.with_name(root.name+'.collection.enc')
    def persist():save(journal_path,seal_forecasts(journal,run_id=str(env['run_id']),round_no=900006,key=key),replace=journal_path.exists())
    budget=Budget(plan['maximum_requests'],journal,persist,clock,sleeper,opener);due=[]
    for case in plan['cases']:
        identity=(case['sport'],_race_key(case['race_id'],case['sport']));native=known.get(identity)
        need(native is not None and native['snapshot']['race']['event_date_jst']==manifest['execution_day'],'CASE_WITHOUT_NATIVE_INPUT')
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
            journal['browser_attempt']=dict(state='RESERVED',reserved_request_limit=remaining,started_at=started.isoformat());persist()
            browser_plan=dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_PLAN_V1',cases=browser_cases,request_budget=remaining,
                not_before=now.isoformat())
            if 'static_cache' in plan:
                sports={case['sport'] for case in browser_cases}
                browser_plan['static_cache']=[entry for entry in plan['static_cache']
                    if policy._url(entry['metadata']['source_url'])[0] in sports]
            directory=work/'browser'
            try:
                index=browser(browser_plan,directory);finished=clock()
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
                found,states,originals=browser_sources(index,directory,browser_cases,started=started,now=finished,remaining=remaining)
                count=index['actual_request_count'];budget.used+=count;budget.last=finished
                journal['browser_attempt'].update(state='COMPLETE',actual_request_count=count,completed_at=finished.isoformat(),
                    stop_reason=index['stop_reason']);journal['browser_index']=index;journal['browser_captures']=originals
                for value in states:native_by_case[(value['sport'],value['race_id'])][1]['state']=value['state']
                for sport,race_id,capture in found:
                    native,entry=native_by_case[(sport,race_id)]
                    journal['captures'].append(capture)
                    try:label=_parse(capture,native,sport,now=finished,allow_order_only=manifest['allow_order_only'])
                    except (ValueError,KeyError,TypeError):entry['state']='HOLD_RESULT_PARSE';continue
                    captures.append(capture);observations.append(label);entry['state']=label['status']
            except Exception:
                if journal['browser_attempt']['state']!='INTERRUPTED':
                    for _,entry in native_by_case.values():entry['state']='HOLD_BROWSER_SOURCE_UNVERIFIED'
            persist()
    if not observations:
        status=dict(_status(journal,manifest),**prior);status['collection_journal_sha256']=sha256(_read(journal_path,MAX_WIRE)).hexdigest();return status
    generated=clock();need(generated.astimezone(JST).date().isoformat()==manifest['execution_day'],'DAY_ELAPSED')
    payload=results.build_result_payload(captures,observations,run_id=env['run_id'],code_sha=env['head_sha'],generated_at=generated,
        day_jst=manifest['execution_day'],frozen_native_payloads=natives,allow_order_only=manifest['allow_order_only'])
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
        header['round_no']==900006 and journal.get('schema')==(JOURNAL_V2 if manifest['schema']==SCHEMA_V2 else JOURNAL) and
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
        if manifest['schema']==SCHEMA_V2:
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
