"""One bounded name-bound exhibition publication; normalized forensic backups only."""
import argparse
from datetime import datetime, timezone
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
from publish_race_updates import workflow_session,select_race
from publish_name_binding import margin
from race_ai.name_bound_exhibition_source import collect_name_bound_inputs
from race_ai.official_update_worker import fetch_update
from collect_original_exhibition import fetch_original
from api.name_binding_store import validate_finalized_binding
from api.name_bound_exhibition_store import metadata,REVIEW,MEDIA_REVIEW
from web.name_bound_prediction import validate_name_bound_envelope
from web.name_bound_inputs import validate_name_bound_inputs
from web.race_contract import canonical,stamp,JST,_time as instant

PAYLOADS={'baseline.json','name-binding.json','inputs.json','request.json','receipt.json'}
ALLOWED=PAYLOADS|{'manifest.json'}
MAX_BYTES=256000
class BudgetExhausted(RuntimeError):pass

def utc_now():return datetime.now(timezone.utc)
def require(value):
    if not value:raise ValueError('NAME_BOUND_EXHIBITION_STOPPED')

def write_checked(folder,name,value):
    require(name in ALLOWED)
    raw=canonical(value);require(0<len(raw)<=MAX_BYTES)
    with (folder/name).open('xb') as handle:handle.write(raw)
    require((folder/name).read_bytes()==raw)
    return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def inventory(folder):
    result={}
    require({p.name for p in folder.iterdir()}<=ALLOWED)
    for name in sorted(PAYLOADS):
        path=folder/name
        if path.exists():
            require(path.is_file() and not path.is_symlink())
            raw=path.read_bytes();require(0<len(raw)<=MAX_BYTES)
            result[name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    return result

def verify_response(report,envelope,request,race,baseline,binding,commit,now):
    validate_name_bound_envelope(envelope,race,now=now)
    require(canonical(report)==canonical(dict(metadata(envelope,race),commit_sha=commit)))
    require(canonical(envelope['baseline'])==canonical(baseline) and canonical(envelope['name_binding'])==canonical(binding))
    require(canonical(envelope['inputs'])==canonical(request['inputs']))
    require(all(envelope['receipt'][k]==request[k] for k in ('request_id','baseline_request_id','name_binding_request_id')))
    require(envelope['receipt']['snapshot']['input_link']['runner_saved_at']==request['runner_saved_at'])

def verify_backups(folder,manifest):
    require(isinstance(manifest['backups'],dict))
    for name,meta in manifest['backups'].items():
        require(name in PAYLOADS and isinstance(meta,dict) and set(meta)=={'bytes','sha256'})
        require(type(meta['bytes']) is int and 0<meta['bytes']<=MAX_BYTES and isinstance(meta['sha256'],str) and re.fullmatch('[0-9a-f]{64}',meta['sha256']))
    require(manifest['backups']==inventory(folder))
    require(set(manifest)=={'schema_version','status','failure_reason','race_id','request_id','name_binding_request_id','commit_sha','backups','reads_used','posts_attempted','official_source_requests','max_seconds','validation_status','purchase_decision','purchase_recommendations'})
    require(type(manifest['schema_version']) is int and manifest['schema_version']==1 and manifest['max_seconds']==240)
    require(manifest['validation_status']=='UNVALIDATED' and manifest['purchase_decision']=='skip' and manifest['purchase_recommendations']==[])
    for key,limit in [('reads_used',4),('posts_attempted',1),('official_source_requests',3)]:
        require(type(manifest[key]) is int and 0<=manifest[key]<=limit)
    reasons={'COMPLETED':None,'STOPPED':'NAME_BOUND_EXHIBITION_STOPPED','TIME_LIMIT_REACHED':'NAME_BOUND_EXHIBITION_TIME_LIMIT'}
    require(manifest['status'] in reasons and manifest['failure_reason']==reasons[manifest['status']])
    if manifest['status']=='COMPLETED':
        require(set(manifest['backups'])==PAYLOADS and manifest['reads_used']==4 and manifest['posts_attempted']==1 and manifest['official_source_requests']==3)
        values={n:json.loads((folder/n).read_bytes()) for n in PAYLOADS}
        for n,v in values.items():require(canonical(v)==(folder/n).read_bytes())
        request=values['request.json'];envelope=values['receipt.json']
        require(request['request_id']==manifest['request_id'] and request['race_id']==manifest['race_id'] and request['name_binding_request_id']==manifest['name_binding_request_id'])
        require(canonical(request['inputs'])==canonical(values['inputs.json']))
        # The immutable baseline carries the original program needed for pure replay.
        snapshot=values['baseline.json']['snapshot'];source=snapshot['program_source']
        race=dict(race_id=snapshot['race_id'],closed_at=snapshot['closed_at'],boats=snapshot['program_boats'],program_source_url=source['source_url'],program_source_sha256=source['source_sha256'],program_observed_at=source['captured_at'])
        verify_response(dict(metadata(envelope,race),commit_sha=manifest['commit_sha']),envelope,request,race,values['baseline.json'],values['name-binding.json'],manifest['commit_sha'],instant(envelope['finalization']['receipt_confirmed_at']))

def finalize_manifest(folder,manifest,guard):
    """Finalize only this invocation's exclusively owned manifest handle."""
    with (folder/'manifest.json').open('x+b') as handle:
        def persist():
            raw=canonical(manifest);require(0<len(raw)<=MAX_BYTES)
            handle.seek(0);handle.truncate(0);handle.write(raw);handle.flush()
            handle.seek(0);require(handle.read()==raw)
        try:
            persist()
            if manifest['status']=='COMPLETED':
                guard();verify_backups(folder,manifest);guard()
        except BudgetExhausted:
            manifest.update(status='TIME_LIMIT_REACHED',failure_reason='NAME_BOUND_EXHIBITION_TIME_LIMIT')
            # Make failure truthful before residual inspection can itself fail.
            persist()
            manifest['backups']=inventory(folder)
            persist()
        except (ValueError,RuntimeError,OSError,KeyError,TypeError,AttributeError,OverflowError,UnicodeError,RecursionError):
            manifest.update(status='STOPPED',failure_reason='NAME_BOUND_EXHIBITION_STOPPED')
            persist()
            manifest['backups']=inventory(folder)
            persist()
    return manifest


def run(facts_review,media_review,output_dir,*,race_id,name_binding_request_id,execute=False):
    if not execute:return None
    started=time.monotonic();folder=Path(output_dir)
    require(not folder.exists());folder.mkdir(parents=True,exist_ok=False)
    manifest=dict(schema_version=1,status='STOPPED',failure_reason='NAME_BOUND_EXHIBITION_STOPPED',race_id=race_id,request_id=None,name_binding_request_id=name_binding_request_id,commit_sha=None,backups={},reads_used=0,posts_attempted=0,official_source_requests=0,max_seconds=240,validation_status='UNVALIDATED',purchase_decision='skip',purchase_recommendations=[])
    race=None
    def guard(seconds=0):
        if time.monotonic()-started+seconds>240:raise BudgetExhausted('NAME_BOUND_EXHIBITION_TIME_LIMIT')
        now=utc_now()
        require(now.astimezone(JST).strftime('%Y%m%d')==race_id[:8])
        if race is not None:margin(race,now)
    def read(path):
        raw=Path(path).read_bytes();require(0<len(raw)<=MAX_BYTES);return json.loads(raw)
    try:
        url=os.environ.get('RACE_AI_NAME_BOUND_PUBLISH_URL','');require(url.endswith('/api/publish-name-bound-exhibition'))
        validate_target(url[:-len('publish-name-bound-exhibition')]+'publish-day')
        commit=os.environ.get('RACE_AI_NAME_BOUND_COMMIT_SHA','')
        nonce=os.environ.get('GITHUB_RUN_ID','')+'-'+os.environ.get('GITHUB_RUN_ATTEMPT','')
        require(re.fullmatch('[0-9a-f]{40}',commit) and re.fullmatch('[1-9][0-9]{0,19}-[1-9][0-9]{0,3}',nonce))
        require(re.fullmatch('[1-9][0-9]{0,19}-[1-9][0-9]{0,3}',name_binding_request_id))
        require(re.fullmatch(r'[0-9]{8}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])',race_id))
        manifest.update(request_id=nonce,commit_sha=commit)
        facts=read(facts_review);media=read(media_review)
        guard(30);opener,headers=workflow_session(commit);guard();base=url.rsplit('/',1)[0]
        def fetch(path,limit=MAX_BYTES):
            guard(30);require(manifest['reads_used']<4);manifest['reads_used']+=1
            value=get_json(opener,urllib.request.Request(base+path,headers=headers),limit=limit)
            guard();return value
        feed=fetch('/today',6000000)
        race,_=select_race(feed,utc_now(),mode='exhibition',race_id=race_id);require(race is not None);guard()
        binding=fetch('/name-binding?race_id='+race_id+'&request_id='+name_binding_request_id)
        require(binding['receipt']['request_id']==name_binding_request_id)
        baseline_id=binding['receipt']['baseline_request_id']
        baseline=fetch('/prediction?race_id='+race_id+'&request_id='+baseline_id)
        require(baseline['request_id']==baseline_id)
        validate_finalized_binding(binding,race,baseline,now=utc_now());parents_read_at=stamp(utc_now());guard()
        write_checked(folder,'baseline.json',baseline);write_checked(folder,'name-binding.json',binding)
        def transport(function,seconds):
            def bounded(*args,**kwargs):
                guard(seconds+60);require(manifest['official_source_requests']<3)
                manifest['official_source_requests']+=1
                result=function(*args,**kwargs);guard();return result
            return bounded
        collected=collect_name_bound_inputs(race,baseline,binding,parents_read_at=parents_read_at,facts_review=facts,media_review=media,execute=True,transport_update=transport(fetch_update,10),transport_original=transport(fetch_original,15),clock=utc_now)
        guard();require(collected['status']=='COLLECTED');inputs=collected['snapshot']
        validate_name_bound_inputs(inputs,race,baseline,binding,now=utc_now())
        write_checked(folder,'inputs.json',inputs);guard();runner=stamp(utc_now())
        require(instant(inputs['generated_at'])<instant(runner))
        request=dict(publication_review=REVIEW,media_review=MEDIA_REVIEW,race_id=race_id,request_id=nonce,baseline_request_id=baseline_id,name_binding_request_id=name_binding_request_id,inputs=inputs,runner_saved_at=runner)
        write_checked(folder,'request.json',request)
        guard(60);manifest['posts_attempted']+=1
        report=get_json(opener,urllib.request.Request(url,data=canonical(request),method='POST',headers=headers),limit=MAX_BYTES);guard()
        envelope=fetch('/name-bound-exhibition?race_id='+race_id+'&request_id='+nonce)
        verify_response(report,envelope,request,race,baseline,binding,commit,utc_now());guard()
        write_checked(folder,'receipt.json',envelope);guard()
        manifest.update(status='COMPLETED',failure_reason=None)
        manifest['backups']=inventory(folder);verify_backups(folder,manifest);guard()
    except BudgetExhausted:
        manifest.update(status='TIME_LIMIT_REACHED',failure_reason='NAME_BOUND_EXHIBITION_TIME_LIMIT')
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,AttributeError,OverflowError,UnicodeError,RecursionError):
        manifest.update(status='STOPPED',failure_reason='NAME_BOUND_EXHIBITION_STOPPED')
    manifest['backups']=inventory(folder)
    # Account for all actual residual bytes, including failed writes, without JSON normalization.
    if time.monotonic()-started>240:manifest.update(status='TIME_LIMIT_REACHED',failure_reason='NAME_BOUND_EXHIBITION_TIME_LIMIT')
    return finalize_manifest(folder,manifest,guard)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('facts-review','media-review','output-dir','race-id','name-binding-request-id'):parser.add_argument('--'+flag,required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    try:result=run(args.facts_review,args.media_review,args.output_dir,race_id=args.race_id,name_binding_request_id=args.name_binding_request_id,execute=args.execute)
    except (ValueError,OSError,RuntimeError):print('NAME_BOUND_EXHIBITION_STOPPED');raise SystemExit(2)
    print(json.dumps(result or {'status':'DRY_RUN','network_requests':0,'official_source_requests':0},sort_keys=True))
    if result and result['status']!='COMPLETED':raise SystemExit(2)
