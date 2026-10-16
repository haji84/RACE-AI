"""Publish one postclose official label for an exact frozen name-bound forecast.

Only normalized facts are retained. Source and application requests never retry.
The bundled operator facts review supplies the existing explicit rights scope.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'web')); sys.path.insert(0,str(ROOT/'scripts'))
from publish_day_feed import get_json, validate_target
from publish_race_updates import workflow_session, select_race
from scripts.verify_name_bound_evaluation import (REASONS, BudgetExhausted, finalize_manifest,
    identifiers, verify_response as verify_evaluation, ERRORS as OLD_ERRORS)
from race_ai.name_bound_result_source import collect_name_bound_result,collect_name_bound_result_v2
from race_ai.official_race_updates import RESULT_DISPOSITION_V2
from race_ai.official_update_worker import fetch_update
from api.name_bound_result_store import metadata, REVIEW, REQUEST
from web.name_bound_result import (result_context, validate_name_bound_result,
    validate_name_bound_result_envelope, result_bundle)
from web.race_contract import canonical, stamp, JST, _time as instant

PAYLOADS = {'program.json','forecast.json','request.json','result.json','evaluation.json'}
ALLOWED = PAYLOADS | {'manifest.json'}
MAX_BYTES = 256000
MAX_SECONDS = 240
MANIFEST = set('schema_version operation race_id forecast_request_id request_id commit_sha status failure_reason backups reads_used posts_attempted official_source_requests max_seconds validation_status purchase_decision purchase_recommendations'.split())
ERRORS = OLD_ERRORS + (http.client.HTTPException,)


def utc_now(): return datetime.now(timezone.utc)


def require(value):
    if not value: raise ValueError(REASONS['STOPPED'])


def write_checked(folder, name, value):
    require(name in PAYLOADS)
    raw = canonical(value); require(0 < len(raw) <= MAX_BYTES)
    with (folder/name).open('xb') as handle: handle.write(raw)
    require((folder/name).read_bytes() == raw)
    return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def inventory(folder):
    """Retain the actual bytes of every partial write without following links."""
    require({p.name for p in folder.iterdir()} <= ALLOWED)
    result = {}
    for name in sorted(ALLOWED):
        path = folder/name
        if path.exists() or path.is_symlink():
            require(path.is_file() and not path.is_symlink())
            if name == 'manifest.json': continue
            raw = path.read_bytes(); require(0 < len(raw) <= MAX_BYTES)
            result[name] = dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    return result


def validate_request(request, race, forecast, now):
    require(isinstance(request,dict) and set(request) == REQUEST)
    require(request['publication_review'] == REVIEW and request['race_id'] == race['race_id'])
    identifiers(race['race_id'],request['request_id'])
    require(request['forecast_request_id'] == forecast['receipt']['request_id'])
    validate_name_bound_result(request['snapshot'],race,forecast,now=now)
    saved = instant(request['runner_saved_at'])
    require(request['runner_saved_at'] == stamp(saved)
        and instant(request['snapshot']['generated_at']) <= saved <= instant(now)
        and saved.astimezone(JST).date() == instant(now).astimezone(JST).date())


def verify_result(envelope, request, race, forecast, now):
    validate_request(request,race,forecast,now)
    validate_name_bound_result_envelope(envelope,race,forecast,now=now)
    receipt = envelope['receipt']
    require(all(receipt[k] == request[k] for k in ('request_id','forecast_request_id','runner_saved_at'))
        and canonical(receipt['snapshot']) == canonical(request['snapshot']))


def verify_backups(folder, manifest):
    """Check exact inventory, then replay all parents, label and three scores."""
    try:
        require(isinstance(manifest,dict) and set(manifest) in (MANIFEST,MANIFEST|{'result_disposition_contract'}))
        selected=manifest.get('result_disposition_contract')
        require('result_disposition_contract' not in manifest or selected==RESULT_DISPOSITION_V2)
        require(type(manifest['schema_version']) is int and manifest['schema_version'] == 1
            and manifest['operation'] == 'NAME_BOUND_RESULT_PUBLICATION')
        require(type(manifest['max_seconds']) is int and manifest['max_seconds'] == MAX_SECONDS)
        identifiers(manifest['race_id'],manifest['forecast_request_id'])
        identifiers(manifest['race_id'],manifest['request_id'])
        require(isinstance(manifest['commit_sha'],str) and re.fullmatch('[0-9a-f]{40}',manifest['commit_sha']))
        require(manifest['validation_status'] == 'UNVALIDATED' and manifest['purchase_decision'] == 'skip'
            and manifest['purchase_recommendations'] == [])
        for field,limit in [('reads_used',5),('posts_attempted',1),('official_source_requests',1)]:
            require(type(manifest[field]) is int and 0 <= manifest[field] <= limit)
        require(isinstance(manifest['status'],str) and manifest['status'] in REASONS
            and manifest['failure_reason'] == REASONS[manifest['status']])
        backups = manifest['backups']; require(isinstance(backups,dict))
        for name,meta in backups.items():
            require(name in PAYLOADS and isinstance(meta,dict) and set(meta) == {'bytes','sha256'})
            require(type(meta['bytes']) is int and 0 < meta['bytes'] <= MAX_BYTES
                and isinstance(meta['sha256'],str) and re.fullmatch('[0-9a-f]{64}',meta['sha256']))
        require(backups == inventory(folder))
        path = folder/'manifest.json'; require(path.is_file() and not path.is_symlink())
        raw = path.read_bytes(); require(0 < len(raw) <= MAX_BYTES and raw == canonical(manifest))
        if manifest['status'] == 'COMPLETED':
            require(set(backups) == PAYLOADS and (manifest['reads_used'],manifest['posts_attempted'],manifest['official_source_requests']) == (5,1,1))
            values = {}
            for name in sorted(PAYLOADS):
                raw = (folder/name).read_bytes(); value = json.loads(raw)
                require(canonical(value) == raw); values[name] = value
            race,forecast,request,label,report = (values[n] for n in ('program.json','forecast.json','request.json','result.json','evaluation.json'))
            require(request['snapshot']['result_record'].get('result_disposition_contract')==selected)
            require(race['race_id'] == manifest['race_id'] and request['request_id'] == manifest['request_id']
                and request['forecast_request_id'] == manifest['forecast_request_id'])
            # The server's unchanged as_of is the replay clock. Only the existing
            # remote report allowance applies, never fabricated evidence times.
            replay = instant(report['as_of'])
            verify_result(label,request,race,forecast,replay)
            bundle = result_bundle(label,race,forecast,now=replay)
            verify_evaluation(report,forecast,bundle,race,manifest['forecast_request_id'],utc_now())
        return manifest
    except ERRORS as exc:
        raise ValueError('NAME_BOUND_RESULT_BACKUP_REJECTED') from exc


def latest_result(opener, request):
    """Only this endpoint's exact missing-label response permits acquisition."""
    try:
        with opener.open(request,timeout=30) as response:
            raw = response.read(MAX_BYTES+1)
            require(response.status == 200 and response.geturl() == request.full_url
                and len(raw) <= MAX_BYTES and 'application/json' in response.headers.get('Content-Type','').lower())
            value = json.loads(raw.decode('utf-8'))
            require(isinstance(value,dict))
            return value
    except urllib.error.HTTPError as error:
        with error:
            raw = error.read(MAX_BYTES+1)
            require(error.code == 404 and error.geturl() == request.full_url and 0 < len(raw) <= MAX_BYTES
                and 'application/json' in error.headers.get('Content-Type','').lower())
            # Inspect object pairs so duplicate keys cannot hide an auth error.
            require(json.loads(raw.decode('utf-8'),object_pairs_hook=list)
                == [('error','NAME_BOUND_RESULT_NOT_SAVED')])
        return None


def run(race_id, forecast_request_id, output_dir, *, execute=False,result_disposition_contract=None):
    if not execute: return None
    require(result_disposition_contract in (None,RESULT_DISPOSITION_V2))
    started = time.monotonic()
    identifiers(race_id,forecast_request_id)
    nonce = os.environ.get('GITHUB_RUN_ID','')+'-'+os.environ.get('GITHUB_RUN_ATTEMPT','')
    identifiers(race_id,nonce)
    url = os.environ.get('RACE_AI_NAME_BOUND_RESULT_PUBLISH_URL','')
    require(url.endswith('/api/publish-name-bound-result'))
    validate_target(url[:-len('publish-name-bound-result')]+'publish-day')
    commit = os.environ.get('RACE_AI_NAME_BOUND_RESULT_COMMIT_SHA','')
    require(re.fullmatch('[0-9a-f]{40}',commit))
    folder = Path(output_dir)
    require(not folder.exists()); folder.mkdir(parents=True,exist_ok=False)
    manifest = dict(schema_version=1,operation='NAME_BOUND_RESULT_PUBLICATION',race_id=race_id,
        forecast_request_id=forecast_request_id,request_id=nonce,commit_sha=commit,status='STOPPED',
        failure_reason=REASONS['STOPPED'],backups={},reads_used=0,posts_attempted=0,
        official_source_requests=0,max_seconds=MAX_SECONDS,validation_status='UNVALIDATED',
        purchase_decision='skip',purchase_recommendations=[])
    if result_disposition_contract is not None:manifest['result_disposition_contract']=result_disposition_contract
    previous = None
    def guard(seconds=0):
        nonlocal previous
        if time.monotonic()-started+seconds > MAX_SECONDS: raise BudgetExhausted(REASONS['TIME_LIMIT_REACHED'])
        now = instant(utc_now())
        require(now.astimezone(JST).strftime('%Y%m%d') == race_id[:8] and (previous is None or previous <= now))
        previous = now
        return now
    try:
        guard()
        raw = (ROOT/'config/operator-official-facts.json').read_bytes()
        require(0 < len(raw) <= MAX_BYTES); facts = json.loads(raw)
        guard(30); opener,headers = workflow_session(commit); guard()
        base = url.rsplit('/',1)[0]
        def fetch(path,limit=MAX_BYTES,*,latest=False):
            guard(30); require(manifest['reads_used'] < 5); manifest['reads_used'] += 1
            req = urllib.request.Request(base+path,headers=headers)
            value = latest_result(opener,req) if latest else get_json(opener,req,limit=limit)
            guard(); return value
        feed = fetch('/today',6_000_000)
        race,_ = select_race(feed,guard(),mode='result',race_id=race_id); require(race is not None)
        write_checked(folder,'program.json',race); guard()
        forecast = fetch('/name-bound-exhibition?race_id='+race_id+'&request_id='+forecast_request_id)
        require(forecast['receipt']['request_id'] == forecast_request_id)
        result_context(race,forecast,guard())
        write_checked(folder,'forecast.json',forecast); parents_read_at = stamp(guard())
        path = '/name-bound-result?race_id='+race_id+'&forecast_request_id='+forecast_request_id
        existing = fetch(path,latest=True)
        if existing is not None:
            validate_name_bound_result_envelope(existing,race,forecast,now=guard())
            raise ValueError(REASONS['STOPPED'])
        def transport(source_url,**kwargs):
            guard(10); require(manifest['official_source_requests'] == 0)
            manifest['official_source_requests'] += 1
            try: return fetch_update(source_url,**kwargs)
            finally: guard()
        collector=collect_name_bound_result if result_disposition_contract is None else collect_name_bound_result_v2
        source = collector(race,forecast,parents_read_at=parents_read_at,
            facts_review=facts,execute=True,transport=transport,clock=guard)
        guard()
        require(isinstance(source,dict) and source.get('status') == 'COLLECTED'
            and type(source.get('official_source_requests')) is int
            and source['official_source_requests'] == manifest['official_source_requests'] == 1)
        require(source['snapshot']['result_record'].get('result_disposition_contract')==result_disposition_contract)
        request = dict(publication_review=REVIEW,race_id=race_id,request_id=nonce,
            forecast_request_id=forecast_request_id,snapshot=source['snapshot'],runner_saved_at=stamp(guard()))
        validate_request(request,race,forecast,guard())
        write_checked(folder,'request.json',request); guard()
        guard(30); manifest['posts_attempted'] += 1
        report = get_json(opener,urllib.request.Request(url,data=canonical(request),method='POST',headers=headers),limit=MAX_BYTES)
        guard()
        label = fetch(path+'&request_id='+nonce)
        verify_result(label,request,race,forecast,guard())
        require(canonical(report) == canonical(dict(metadata(label,race),commit_sha=commit)))
        write_checked(folder,'result.json',label); guard()
        evaluation = fetch('/name-bound-evaluation?race_id='+race_id+'&forecast_request_id='+forecast_request_id)
        bundle = result_bundle(label,race,forecast,now=instant(evaluation['as_of']))
        verify_evaluation(evaluation,forecast,bundle,race,forecast_request_id,guard())
        write_checked(folder,'evaluation.json',evaluation); guard()
        manifest.update(status='COMPLETED',failure_reason=None)
    except BudgetExhausted:
        manifest.update(status='TIME_LIMIT_REACHED',failure_reason=REASONS['TIME_LIMIT_REACHED'])
    except ERRORS:
        manifest.update(status='STOPPED',failure_reason=REASONS['STOPPED'])
    return finalize_manifest(folder,manifest,guard,inventory_fn=inventory,verify_fn=verify_backups)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('race-id','forecast-request-id','output-dir'): parser.add_argument('--'+flag,required=True)
    parser.add_argument('--result-disposition-contract',choices=[RESULT_DISPOSITION_V2])
    parser.add_argument('--execute',action='store_true'); args = parser.parse_args()
    try: result = run(args.race_id,args.forecast_request_id,args.output_dir,execute=args.execute,
        result_disposition_contract=args.result_disposition_contract)
    except ERRORS:
        print(REASONS['STOPPED']); raise SystemExit(2)
    print(json.dumps(result or {'status':'DRY_RUN','network_requests':0,'official_source_requests':0},sort_keys=True))
    if result and result['status'] != 'COMPLETED': raise SystemExit(2)
