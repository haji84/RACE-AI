"""One bounded official name proof, pinned to an existing immutable baseline."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'web'));sys.path.insert(0,str(ROOT/'scripts'))
from publish_day_feed import get_json,validate_target
from publish_race_updates import workflow_session
from race_ai.name_binding_source import collect_name_binding
from api.name_binding_store import validate_finalized_binding
from web.evaluation_contract import _checked_prediction
from web.race_contract import canonical,JST,_time as instant,stamp

ALLOWED={'baseline.json','name-proof.json','request.json','receipt.json','manifest.json'}
REVIEW='user-confirmation-2026-10-15-official-facts'

class BudgetExhausted(Exception):
    """Keep deadline exhaustion distinct from a source transport timeout."""
    pass

def utc_now():return datetime.now(timezone.utc)

def margin(race,now):
    if now.astimezone(JST).strftime('%Y%m%d')!=race['race_id'][:8] or now+timedelta(seconds=120)>=instant(race['closed_at']):
        raise ValueError('NAME_BINDING_STOPPED')

def write_checked(folder,name,value):
    if name not in ALLOWED:raise ValueError('NAME_BINDING_STOPPED')
    raw=canonical(value)
    if not 0<len(raw)<=64000:raise ValueError('NAME_BINDING_STOPPED')
    with (folder/name).open('xb') as handle:handle.write(raw)
    if (folder/name).read_bytes()!=raw:raise ValueError('NAME_BINDING_STOPPED')
    return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def verify_response(report,envelope,request,race,baseline,commit,now):
    validate_finalized_binding(envelope,race,baseline,now=now)
    receipt=envelope['receipt'];marker=envelope['finalization']
    expected=dict(status='verified',race_id=race['race_id'],request_id=request['request_id'],
        snapshot_id=request['snapshot']['snapshot_id'],baseline_request_id=baseline['request_id'],
        baseline_snapshot_id=baseline['snapshot']['snapshot_id'],b_program_sha256=baseline['program_sha256'],
        program_identity_sha256=request['snapshot']['program_identity_sha256'],runner_saved_at=request['runner_saved_at'],
        cloud_saved_at=receipt['cloud_saved_at'],receipt_confirmed_at=marker['receipt_confirmed_at'],
        cloud_eligible_pre_race=True,pathname=f"race-ai/name-binding/{race['race_id']}.json",
        sha256=hashlib.sha256(canonical(envelope)).hexdigest(),research_only=True,validation_status='UNVALIDATED',
        purchase_decision='skip',purchase_recommendations=[],commit_sha=commit)
    if report!=expected or receipt['snapshot']!=request['snapshot'] or receipt['runner_saved_at']!=request['runner_saved_at'] or receipt['request_id']!=request['request_id']:
        raise ValueError('NAME_BINDING_STOPPED')

def run(review_path,output_dir,*,race_id,execute=False):
    if not execute:return None
    started=time.monotonic()
    folder=Path(output_dir)
    if folder.exists():raise ValueError('NAME_BINDING_STOPPED')
    folder.mkdir(parents=True,exist_ok=False)
    manifest=dict(schema_version=1,status='STOPPED',failure_reason='NAME_BINDING_STOPPED',race_id=race_id,
        request_id=None,commit_sha=None,backups={},reads_used=0,posts_attempted=0,official_source_requests=0,
        max_seconds=180,validation_status='UNVALIDATED',purchase_decision='skip',purchase_recommendations=[])
    def reserve(seconds):
        if time.monotonic()-started+seconds>180:raise BudgetExhausted('NAME_BINDING_TIME_LIMIT')
    try:
        url=os.environ.get('RACE_AI_NAME_BINDING_PUBLISH_URL','')
        if not url.endswith('/api/publish-name-binding'):raise ValueError()
        validate_target(url[:-len('publish-name-binding')]+'publish-day')
        commit=os.environ.get('RACE_AI_NAME_BINDING_COMMIT_SHA','')
        nonce=os.environ.get('GITHUB_RUN_ID','')+'-'+os.environ.get('GITHUB_RUN_ATTEMPT','')
        if not re.fullmatch('[0-9a-f]{40}',commit) or not re.fullmatch('[1-9][0-9]{0,19}-[1-9][0-9]{0,3}',nonce):raise ValueError()
        if not re.fullmatch(r'[0-9]{8}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])',race_id):raise ValueError()
        manifest.update(request_id=nonce,commit_sha=commit)
        path=Path(review_path)
        if not 0<path.stat().st_size<=64000:raise ValueError()
        review=json.loads(path.read_bytes())
        reserve(30);opener,headers=workflow_session(commit);base=url.rsplit('/',1)[0]
        def fetch(endpoint,limit=64000):
            reserve(30);manifest['reads_used']+=1
            return get_json(opener,urllib.request.Request(base+endpoint,headers=headers),limit=limit)
        feed=fetch('/today',6000000);now=utc_now()
        if (feed.get('date_jst')!=now.astimezone(JST).date().isoformat() or feed.get('schedule_verified') is not True
                or feed.get('redistribution_authorized') is not True or len(feed.get('venues',[]))!=24):raise ValueError()
        races=[r for v in feed['venues'] if v.get('status')=='READY' for r in v['races'] if r['race_id']==race_id]
        if len(races)!=1:raise ValueError()
        race=races[0];margin(race,now)
        baseline=fetch('/prediction?race_id='+race_id)
        _checked_prediction(baseline,race,utc_now(),now.astimezone(JST).date(),instant(race['closed_at']))
        if baseline is None:raise ValueError()
        pinned=fetch('/prediction?race_id='+race_id+'&request_id='+baseline['request_id'])
        if canonical(pinned)!=canonical(baseline):raise ValueError()
        _checked_prediction(pinned,race,utc_now(),now.astimezone(JST).date(),instant(race['closed_at']))
        manifest['backups']['baseline.json']=write_checked(folder,'baseline.json',baseline)
        reserve(10);margin(race,utc_now())
        # Collector validates rights before its sole GET. Count actual transport invocations.
        from race_ai.official_racelist_worker import fetch_racelist
        def transport(*args,**kwargs):
            reserve(10);manifest['official_source_requests']+=1
            return fetch_racelist(*args,**kwargs)
        collected=collect_name_binding(race,baseline_snapshot_id=baseline['snapshot']['snapshot_id'],
            b_program_sha256=baseline['program_sha256'],review=review,execute=True,transport=transport,clock=utc_now)
        if collected.get('status')!='COLLECTED':raise ValueError()
        proof=collected['snapshot']
        manifest['backups']['name-proof.json']=write_checked(folder,'name-proof.json',proof)
        runner_now=utc_now()
        margin(race,runner_now)
        if not instant(baseline['cloud_saved_at'])<=instant(proof['source']['captured_at'])<=instant(proof['generated_at'])<=runner_now:
            raise ValueError('NAME_BINDING_STOPPED')
        runner=stamp(runner_now)
        request=dict(publication_review=REVIEW,race_id=race_id,request_id=nonce,baseline_request_id=baseline['request_id'],snapshot=proof,runner_saved_at=runner)
        manifest['backups']['request.json']=write_checked(folder,'request.json',request)
        for name,meta in manifest['backups'].items():
            raw=(folder/name).read_bytes()
            if len(raw)!=meta['bytes'] or hashlib.sha256(raw).hexdigest()!=meta['sha256']:raise ValueError()
        reserve(60);margin(race,utc_now());manifest['posts_attempted']+=1
        report=get_json(opener,urllib.request.Request(url,data=canonical(request),method='POST',headers=headers),limit=16384)
        envelope=fetch('/name-binding?race_id='+race_id+'&request_id='+nonce)
        verify_response(report,envelope,request,race,baseline,commit,utc_now())
        manifest['backups']['receipt.json']=write_checked(folder,'receipt.json',envelope)
        manifest.update(status='COMPLETED',failure_reason=None)
    except BudgetExhausted:
        manifest.update(status='TIME_LIMIT_REACHED',failure_reason='NAME_BINDING_TIME_LIMIT')
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,AttributeError,OverflowError):
        pass
    finally:
        # A normalized exclusive write may succeed before local readback fails.
        # Keep that partial file accounted for without replacing earlier pins.
        for name in sorted(ALLOWED-{'manifest.json'}-set(manifest['backups'])):
            path=folder/name
            if path.is_file():
                raw=path.read_bytes()
                if not 0<len(raw)<=64000:raise ValueError('NAME_BINDING_STOPPED')
                manifest['backups'][name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        write_checked(folder,'manifest.json',manifest)
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review',required=True);parser.add_argument('--output-dir',required=True)
    parser.add_argument('--race-id',required=True);parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    try:result=run(args.review,args.output_dir,race_id=args.race_id,execute=args.execute)
    except (ValueError,OSError):print('NAME_BINDING_STOPPED');raise SystemExit(2)
    print(json.dumps(result or {'status':'DRY_RUN','network_requests':0,'official_source_requests':0},sort_keys=True))
    if result and result['status']!='COMPLETED':raise SystemExit(2)
