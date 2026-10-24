"""Publish normalized original evidence, then replay a separate original-v1 model.

--original-input collector/input.json --race-input durable-race.json
--output-dir NEW_DIRECTORY [--execute]. Environment:
RACE_AI_ORIGINAL_PUBLISH_URL=<protected-preview>/api/publish-original-exhibition,
RACE_AI_ORIGINAL_COMMIT_SHA=<reviewed app SHA>, GITHUB_RUN_ID/ATTEMPT and existing
GitHub OIDC request variables. Existing baseline is preserved; missing baseline
uses the existing server writer with this run's nonce. No official source GETs.
All complete normalized requests/receipts and their hashes are backed up; no
source bodies, playback tokens, credentials or purchase ledger are retained.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import sys
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from collect_original_exhibition import _read,_write,REVIEW as ORIGINAL_REVIEW
from publish_day_feed import get_json,validate_target,canonical_sha
from publish_race_updates import workflow_session,select_race
from publish_exhibition_prediction import _margin,REVIEW
from publish_research_prediction import verify_receipt as verify_baseline
from web.evaluation_contract import _checked_prediction
from web.original_exhibition_contract import validate_original_receipt,validate_original_observation
from web.original_prediction_contract import validate_original_prediction_bundle
from web.race_contract import canonical,program_digest,validate_cloud_bundle,_time as instant,JST


def verify_source(receipt,packet,race,report,commit,request_id,now):
    validate_original_receipt(receipt,race,now)
    if (receipt['request_id']!=request_id or canonical(receipt['observation'])!=canonical(packet['observation'])
        or instant(receipt['runner_saved_at'])!=instant(packet['runner_saved_at'])
        or report.get('status')!='verified' or report.get('commit_sha')!=commit or report.get('race_id')!=race['race_id']
        or report.get('request_id')!=request_id or report.get('snapshot_id')!=receipt['observation']['snapshot_id']
        or report.get('sha256')!=canonical_sha(receipt) or report.get('cloud_saved_at')!=receipt['cloud_saved_at']
        or report.get('runner_saved_at')!=receipt['runner_saved_at']
        or type(report.get('cloud_eligible_pre_race')) is not bool or report['cloud_eligible_pre_race']!=receipt['cloud_eligible_pre_race']
        or report.get('program_identity_sha256')!=program_digest(race)):
        raise ValueError('ORIGINAL_API_READBACK_MISMATCH')


def verify_receipt(receipt,baseline,source,original,race,report,commit,request_id,now):
    fields={'schema_version','request_id','snapshot','cloud_saved_at','cloud_eligible_pre_race','program_identity_sha256'}
    if (not isinstance(receipt,dict) or set(receipt)!=fields or type(receipt['schema_version']) is not int
        or receipt['schema_version']!=1 or receipt['request_id']!=request_id or receipt['cloud_eligible_pre_race'] is not True
        or receipt['program_identity_sha256']!=program_digest(race)):
        raise ValueError('ORIGINAL_POST_READBACK_MISMATCH')
    preview=validate_cloud_bundle(source,race,now).get('beforeinfo')
    snapshot=validate_original_prediction_bundle(receipt['snapshot'],baseline,preview,original,race,now)
    if (not instant(snapshot['generated_at'])<=instant(receipt['cloud_saved_at'])<instant(race['closed_at'])
        or instant(receipt['cloud_saved_at'])>now or report.get('status')!='verified' or report.get('variant')!='original-v1'
        or report.get('commit_sha')!=commit or report.get('race_id')!=race['race_id'] or report.get('request_id')!=request_id
        or report.get('snapshot_id')!=snapshot['snapshot_id'] or report.get('sha256')!=canonical_sha(receipt)
        or report.get('cloud_saved_at')!=receipt['cloud_saved_at'] or report.get('cloud_eligible_pre_race') is not True
        or type(report.get('models')) is not int or report['models']!=1
        or report.get('program_identity_sha256')!=program_digest(race)
        or report.get('baseline_snapshot_id')!=snapshot['baseline_link']['snapshot_id']
        or report.get('beforeinfo_snapshot_id')!=snapshot['beforeinfo_link']['snapshot_id']
        or report.get('original_request_id')!=original['request_id']
        or report.get('original_snapshot_id')!=original['observation']['snapshot_id']
        or report.get('research_only') is not True or report.get('validation_status')!='UNVALIDATED'
        or report.get('purchase_decision')!='skip' or report.get('purchase_recommendations')!=[]):
        raise ValueError('ORIGINAL_POST_READBACK_MISMATCH')


def run(original_input,race_input,output_dir,*,execute=False,clock=None):
    if not execute:
        result=dict(result='DRY_RUN',network_requests=0,official_source_requests=0)
        print(json.dumps(result));return result
    output_dir=Path(output_dir)
    if output_dir.exists():raise ValueError('ORIGINAL_OUTPUT_ALREADY_EXISTS')
    packet=_read(original_input,256000);supplied=_read(race_input,256000)
    if (not isinstance(packet,dict) or set(packet)!={'schema_version','race_id','observation','runner_saved_at'}
        or type(packet['schema_version']) is not int or packet['schema_version']!=1):raise ValueError('ORIGINAL_INPUT_INVALID')
    url=os.environ.get('RACE_AI_ORIGINAL_PUBLISH_URL','')
    if not url.endswith('/api/publish-original-exhibition'):raise ValueError('ORIGINAL_TARGET_INVALID')
    validate_target(url[:-len('publish-original-exhibition')]+'publish-day')
    commit=os.environ.get('RACE_AI_ORIGINAL_COMMIT_SHA','')
    nonce=os.environ.get('GITHUB_RUN_ID','')+'-'+os.environ.get('GITHUB_RUN_ATTEMPT','')
    if re.fullmatch(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,3}',nonce) is None:raise ValueError('ORIGINAL_REQUEST_ID_INVALID')
    opener,headers=workflow_session(commit);base=url.rsplit('/',1)[0]
    fetch=lambda path,limit=256000:get_json(opener,urllib.request.Request(base+path,headers=headers),limit=limit)
    clock=clock or (lambda:datetime.now(timezone.utc))
    feed=fetch('/today',6000000);now=clock()
    race,_=select_race(feed,now,mode='exhibition',race_id=packet['race_id'])
    if race is None:raise ValueError('ORIGINAL_NO_UPCOMING_RACE')
    if supplied.get('race_id')!=race['race_id']:raise ValueError('ORIGINAL_RACE_INPUT_CONFLICT')
    source=fetch('/race?race_id='+race['race_id'])
    if canonical(source)!=canonical(supplied):raise ValueError('ORIGINAL_RACE_SOURCE_CHANGED')
    _margin(race,clock())
    validate_cloud_bundle(source,race,now);validate_original_observation(packet['observation'],race,now)
    # Preflight supplied runner/capture proof before any external write. The
    # actual cloud clock is still measured exclusively by the trusted server.
    candidate=dict(schema_version=1,request_id=nonce,observation=packet['observation'],runner_saved_at=packet['runner_saved_at'],
        cloud_saved_at=now.isoformat(timespec='microseconds'),cloud_eligible_pre_race=True,program_identity_sha256=program_digest(race))
    validate_original_receipt(candidate,race,now)
    output_dir.mkdir(parents=True,exist_ok=False)
    backups={'race.json':_write(output_dir/'race.json',source)}
    request=dict(publication_review=ORIGINAL_REVIEW,race_id=race['race_id'],request_id=nonce,
        observation=packet['observation'],runner_saved_at=packet['runner_saved_at'])
    backups['original-request.json']=_write(output_dir/'original-request.json',request)
    _margin(race,clock())
    report=get_json(opener,urllib.request.Request(url,data=canonical(request),method='POST',headers=headers),limit=16384)
    original=fetch('/original-exhibition?race_id='+race['race_id']+'&request_id='+nonce)
    verify_source(original,packet,race,report,commit,nonce,clock())
    backups['original.json']=_write(output_dir/'original.json',original)
    if original['observation']['status']!='AVAILABLE':
        manifest=dict(schema_version=1,result='ORIGINAL_EXHIBITION_PARTIAL_VERIFIED',race_id=race['race_id'],request_id=nonce,
            commit_sha=commit,backups=backups,official_source_requests=0,validation_status='UNVALIDATED',purchase_decision='skip',purchase_recommendations=[])
        _write(output_dir/'manifest.json',manifest);print(json.dumps(manifest,sort_keys=True));return manifest
    if original['cloud_eligible_pre_race'] is not True:raise ValueError('ORIGINAL_NOT_PRE_RACE')
    try:baseline=fetch('/prediction?race_id='+race['race_id'])
    except RuntimeError as error:
        if str(error)!='DAY_PUBLISH_HTTP_404':raise
        baseline=None
    baseline_request=dict(publication_review=REVIEW,race_id=race['race_id'],request_id=nonce)
    if baseline is None:
        backups['baseline-request.json']=_write(output_dir/'baseline-request.json',baseline_request)
        _margin(race,clock())
        report=get_json(opener,urllib.request.Request(base+'/publish-prediction',data=canonical(baseline_request),method='POST',headers=headers),limit=16384)
        baseline=fetch('/prediction?race_id='+race['race_id']+'&request_id='+nonce)
        verify_baseline(baseline,race,report,commit,nonce,clock())
    else:
        current=clock();_checked_prediction(baseline,race,current,current.astimezone(JST).date(),instant(race['closed_at']))
    backups['baseline.json']=_write(output_dir/'baseline.json',baseline)
    # Do not mint a model against a different mutable source that appeared after
    # our immutable receipt was published. Immutable model replay remains pinned.
    if canonical(fetch('/original-exhibition?race_id='+race['race_id']))!=canonical(original):
        raise ValueError('ORIGINAL_SOURCE_CHANGED')
    if canonical(fetch('/race?race_id='+race['race_id']))!=canonical(source):raise ValueError('ORIGINAL_RACE_SOURCE_CHANGED')
    post_request={**baseline_request,'variant':'original-v1'}
    backups['post-request.json']=_write(output_dir/'post-request.json',post_request)
    _margin(race,clock())
    report=get_json(opener,urllib.request.Request(base+'/publish-exhibition-prediction',data=canonical(post_request),method='POST',headers=headers),limit=16384)
    receipt=fetch('/exhibition-prediction?race_id='+race['race_id']+'&request_id='+nonce+'&variant=original-v1')
    verify_receipt(receipt,baseline,source,original,race,report,commit,nonce,clock())
    backups['post.json']=_write(output_dir/'post.json',receipt)
    manifest=dict(schema_version=1,result='ORIGINAL_EXHIBITION_PREDICTION_VERIFIED',race_id=race['race_id'],request_id=nonce,
        commit_sha=commit,variant='original-v1',snapshot_id=receipt['snapshot']['snapshot_id'],cloud_saved_at=receipt['cloud_saved_at'],
        closed_at=race['closed_at'],backups=backups,official_source_requests=0,validation_status='UNVALIDATED',purchase_decision='skip',purchase_recommendations=[])
    _write(output_dir/'manifest.json',manifest);print(json.dumps(manifest,sort_keys=True));return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-input',required=True,type=Path);parser.add_argument('--race-input',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path);parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    try:run(args.original_input,args.race_input,args.output_dir,execute=args.execute)
    except (ValueError,RuntimeError,OSError,KeyError,TypeError) as error:
        code=str(error);safe=code if re.fullmatch(r'(ORIGINAL|EXHIBITION|CURRENT_APPROVED_PROGRAM|DAY_PUBLISH_HTTP)_[A-Z0-9_]+',code) else type(error).__name__
        print('SAFE_STOP: bounded original publication failed '+safe,flush=True);raise SystemExit(2)
