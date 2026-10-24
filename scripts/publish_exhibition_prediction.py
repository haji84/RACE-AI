"""Freeze one real post-exhibition forecast and replay all pinned input bytes.

Requires a separately collected, durable race input. Uses existing scoped OIDC
only; no official source requests, media originals or purchase ledger writes.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from publish_day_feed import get_json, validate_target, canonical_sha
from publish_race_updates import workflow_session
from publish_research_prediction import verify_receipt as verify_baseline
from web.evaluation_contract import _checked_prediction
from web.exhibition_contract import validate_post_exhibition_bundle
from web.race_contract import canonical, program_digest, validate_cloud_bundle, _time as instant, JST

MARGIN = timedelta(seconds=120)
REVIEW = 'user-confirmation-2026-10-15-official-facts'


def _margin(race, now):
    if (now.astimezone(JST).strftime('%Y%m%d') != race['race_id'][:8]
            or instant(race['closed_at']) <= now+MARGIN):
        raise ValueError('EXHIBITION_CUTOFF_MARGIN')


def _write(path, value):
    raw=canonical(value)
    if not 0<len(raw)<=256000:raise ValueError('EXHIBITION_BACKUP_SIZE_INVALID')
    with path.open('xb') as handle:handle.write(raw)
    return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def verify_receipt(receipt, baseline, source, race, report, commit, request_id, now):
    fields={'schema_version','request_id','snapshot','cloud_saved_at','cloud_eligible_pre_race','program_identity_sha256'}
    if (not isinstance(receipt,dict) or set(receipt)!=fields or type(receipt['schema_version']) is not int
            or receipt['schema_version']!=1 or receipt['request_id']!=request_id or receipt['cloud_eligible_pre_race'] is not True
            or receipt['program_identity_sha256']!=program_digest(race)):
        raise ValueError('EXHIBITION_API_READBACK_MISMATCH')
    snapshot=receipt['snapshot']
    inputs=validate_cloud_bundle(source,race,now)
    preview=inputs.get('beforeinfo')
    validate_post_exhibition_bundle(snapshot,baseline,preview,race,now)
    if (not instant(snapshot['generated_at'])<=instant(receipt['cloud_saved_at'])<instant(race['closed_at'])
            or instant(receipt['cloud_saved_at'])>now or report.get('status')!='verified' or report.get('commit_sha')!=commit
            or report.get('race_id')!=race['race_id'] or report.get('request_id')!=request_id
            or report.get('snapshot_id')!=snapshot['snapshot_id'] or report.get('sha256')!=canonical_sha(receipt)
            or report.get('cloud_saved_at')!=receipt['cloud_saved_at'] or report.get('cloud_eligible_pre_race') is not True
            or report.get('models')!=1 or report.get('program_identity_sha256')!=receipt['program_identity_sha256']
            or report.get('baseline_snapshot_id')!=snapshot['baseline_link']['snapshot_id']
            or report.get('beforeinfo_snapshot_id')!=snapshot['beforeinfo_link']['snapshot_id']):
        raise ValueError('EXHIBITION_API_READBACK_MISMATCH')


def run(input_path, output_dir, *, execute=False):
    if not execute:
        print(json.dumps(dict(result='DRY_RUN',network_requests=0,official_source_requests=0)));return
    output_dir=Path(output_dir)
    if output_dir.exists():raise ValueError('EXHIBITION_OUTPUT_ALREADY_EXISTS')
    input_path=Path(input_path)
    if input_path.stat().st_size>256000:raise ValueError('EXHIBITION_INPUT_SIZE_INVALID')
    supplied=json.loads(input_path.read_bytes())
    url=os.environ.get('RACE_AI_EXHIBITION_PUBLISH_URL','')
    if not url.endswith('/api/publish-exhibition-prediction'):raise ValueError('EXHIBITION_TARGET_INVALID')
    validate_target(url[:-len('publish-exhibition-prediction')]+'publish-day')
    commit=os.environ.get('RACE_AI_EXHIBITION_COMMIT_SHA','')
    request_id=os.environ.get('GITHUB_RUN_ID','')+'-'+os.environ.get('GITHUB_RUN_ATTEMPT','')
    if not re.fullmatch(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,3}',request_id):raise ValueError('EXHIBITION_REQUEST_ID_INVALID')
    opener,headers=workflow_session(commit);base=url.rsplit('/',1)[0]
    fetch=lambda endpoint,limit=256000:get_json(opener,urllib.request.Request(base+endpoint,headers=headers),limit=limit)
    feed=fetch('/today',6_000_000); now=datetime.now(timezone.utc)
    if (not isinstance(feed,dict) or feed.get('date_jst')!=now.astimezone(JST).date().isoformat()
            or feed.get('schedule_verified') is not True or feed.get('redistribution_authorized') is not True
            or len(feed.get('venues',[]))!=24):raise ValueError('CURRENT_APPROVED_PROGRAM_REQUIRED')
    races=[r for v in feed['venues'] if v.get('status')=='READY' for r in v['races'] if r['race_id']==supplied.get('race_id')]
    if len(races)!=1:raise ValueError('EXHIBITION_PROGRAM_IDENTITY_INVALID')
    race=races[0];_margin(race,now)
    source=fetch('/race?race_id='+race['race_id'])
    if canonical_sha(source)!=canonical_sha(supplied):raise ValueError('EXHIBITION_SOURCE_CHANGED')
    validate_cloud_bundle(source,race,datetime.now(timezone.utc))
    try:baseline=fetch('/prediction?race_id='+race['race_id'])
    except RuntimeError as error:
        if str(error)!='DAY_PUBLISH_HTTP_404':raise
        baseline=None
    output_dir.mkdir(parents=True,exist_ok=False)
    backups={}
    backups['source.json']=_write(output_dir/'source.json',source)
    request=dict(publication_review=REVIEW,race_id=race['race_id'],request_id=request_id)
    if baseline is None:
        backups['baseline-request.json']=_write(output_dir/'baseline-request.json',request)
        _margin(race,datetime.now(timezone.utc))
        report=get_json(opener,urllib.request.Request(base+'/publish-prediction',data=canonical(request),method='POST',headers=headers),limit=16384)
        baseline=fetch('/prediction?race_id='+race['race_id']+'&request_id='+request_id)
        verify_baseline(baseline,race,report,commit,request_id,datetime.now(timezone.utc))
    else:
        _checked_prediction(baseline,race,datetime.now(timezone.utc),now.astimezone(JST).date(),instant(race['closed_at']))
    backups['baseline.json']=_write(output_dir/'baseline.json',baseline)
    backups['post-request.json']=_write(output_dir/'post-request.json',request)
    # File I/O and earlier source/baseline network latency cannot consume the
    # margin and silently turn this into a near-cutoff or historical write.
    _margin(race,datetime.now(timezone.utc))
    report=get_json(opener,urllib.request.Request(url,data=canonical(request),method='POST',headers=headers),limit=16384)
    receipt=fetch('/exhibition-prediction?race_id='+race['race_id']+'&request_id='+request_id)
    verify_receipt(receipt,baseline,source,race,report,commit,request_id,datetime.now(timezone.utc))
    backups['post.json']=_write(output_dir/'post.json',receipt)
    manifest=dict(schema_version=1,result='POST_EXHIBITION_API_VERIFIED',race_id=race['race_id'],request_id=request_id,
        commit_sha=commit,snapshot_id=receipt['snapshot']['snapshot_id'],cloud_saved_at=receipt['cloud_saved_at'],
        closed_at=race['closed_at'],backups=backups,official_source_requests=0,
        validation_status='UNVALIDATED',purchase_decision='skip',purchase_recommendations=[])
    _write(output_dir/'manifest.json',manifest)
    print(json.dumps(manifest,sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--race-input',required=True,type=Path);parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    try:run(args.race_input,args.output_dir,execute=args.execute)
    except (ValueError,RuntimeError,OSError,KeyError,TypeError) as error:
        code=str(error)
        stage=code if re.fullmatch(r'(EXHIBITION|DAY_PUBLISH_HTTP|CURRENT_APPROVED_PROGRAM)_[A-Z0-9_]+',code) else type(error).__name__
        print('SAFE_STOP: bounded exhibition publication failed '+stage,flush=True);raise SystemExit(2)
