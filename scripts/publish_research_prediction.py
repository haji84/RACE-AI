"""Save one actual pre-cutoff research forecast and verify its protected API.

No official source requests; existing approved day data is frozen by the server.
Existing pinned OIDC identity only. Normalized request/receipt backup contains no
credentials or source originals. Dry run performs no network or file writes.
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
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from publish_day_feed import get_json,validate_target,canonical_sha
from publish_race_updates import workflow_session
from web.research_contract import validate_research_bundle, _time as instant

JST=ZoneInfo('Asia/Tokyo')


def choose_race(feed,now):
    if (feed.get('date_jst')!=now.astimezone(JST).date().isoformat() or feed.get('schedule_verified') is not True
            or feed.get('redistribution_authorized') is not True or len(feed.get('venues',[]))!=24):
        raise ValueError('CURRENT_APPROVED_PROGRAM_REQUIRED')
    races=[r for v in feed['venues'] if v.get('status')=='READY' for r in v['races']
        if len(r.get('boats',[]))==6 and instant(r['closed_at'])>now+timedelta(seconds=60)]
    return min(races,key=lambda r:(instant(r['closed_at']),r['race_id'])) if races else None


def verify_receipt(receipt,race,report,commit,request_id,now):
    fields={'schema_version','request_id','snapshot','cloud_saved_at','cloud_eligible_pre_race','program_sha256'}
    if (not isinstance(receipt,dict) or set(receipt)!=fields or type(receipt['schema_version']) is not int
            or receipt['schema_version']!=1 or receipt['request_id']!=request_id or receipt['cloud_eligible_pre_race'] is not True):
        raise ValueError('RESEARCH_API_READBACK_MISMATCH')
    snapshot=validate_research_bundle(receipt['snapshot'],race,now)
    if (receipt['program_sha256']!=snapshot['program_sha256']
            or not instant(snapshot['generated_at'])<=instant(receipt['cloud_saved_at'])<instant(race['closed_at'])
            or instant(receipt['cloud_saved_at'])>now
            or report.get('status')!='verified' or report.get('commit_sha')!=commit or report.get('race_id')!=race['race_id']
            or report.get('request_id')!=request_id or report.get('snapshot_id')!=snapshot['snapshot_id']
            or report.get('cloud_saved_at')!=receipt['cloud_saved_at'] or report.get('cloud_eligible_pre_race') is not True
            or report.get('models')!=len(snapshot['models']) or report.get('sha256')!=canonical_sha(receipt)):
        raise ValueError('RESEARCH_API_READBACK_MISMATCH')


def run(output_path,*,execute=False):
    if not execute:
        print(json.dumps({'result':'DRY_RUN','network_requests':0,'official_source_requests':0}));return
    url=os.environ.get('RACE_AI_RESEARCH_PUBLISH_URL','')
    if not url.endswith('/api/publish-prediction'):raise ValueError('RESEARCH_TARGET_INVALID')
    validate_target(url[:-len('publish-prediction')]+'publish-day')
    commit=os.environ.get('RACE_AI_RESEARCH_COMMIT_SHA','')
    request_id=os.environ.get('GITHUB_RUN_ID','')+'-'+os.environ.get('GITHUB_RUN_ATTEMPT','')
    if not re.fullmatch(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,3}',request_id):raise ValueError('RESEARCH_REQUEST_ID_INVALID')
    opener,headers=workflow_session(commit);base=url.rsplit('/',1)[0]
    feed=get_json(opener,urllib.request.Request(base+'/today',headers=headers),limit=6_000_000)
    race=choose_race(feed,datetime.now(timezone.utc))
    if race is None:
        print(json.dumps({'result':'NO_UPCOMING_RACE','date_jst':feed['date_jst'],'official_source_requests':0}));return
    request={'publication_review':'user-confirmation-2026-10-15-official-facts','race_id':race['race_id'],'request_id':request_id}
    raw=json.dumps(request,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    output_path.parent.mkdir(parents=True,exist_ok=True)
    with output_path.with_suffix('.request.json').open('xb') as handle:handle.write(raw)
    report=get_json(opener,urllib.request.Request(url,data=raw,method='POST',headers=headers),limit=16384)
    receipt=get_json(opener,urllib.request.Request(base+'/prediction?race_id='+race['race_id']+'&request_id='+request_id,headers=headers),limit=256000)
    verify_receipt(receipt,race,report,commit,request_id,datetime.now(timezone.utc))
    backup=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    with output_path.open('xb') as handle:handle.write(backup)
    snapshot=receipt['snapshot']
    print(json.dumps({'result':'RESEARCH_PREDICTION_API_VERIFIED','race_id':race['race_id'],'request_id':request_id,
        'commit_sha':commit,'sha256':canonical_sha(receipt),'backup_file_sha256':hashlib.sha256(backup).hexdigest(),
        'snapshot_id':snapshot['snapshot_id'],'source_sha256':snapshot['program_sha256'],
        'source_captured_at':snapshot['program_source']['captured_at'],'as_of':snapshot['as_of'],
        'generated_at':snapshot['generated_at'],'cloud_saved_at':receipt['cloud_saved_at'],'closed_at':snapshot['closed_at'],
        'cloud_eligible_pre_race':True,'models':[{'model_id':m['model_id'],'triples':len(m['triples']),
            'probability_mass':sum(row['probability'] for row in m['triples'])} for m in snapshot['models']],
        'validation_status':'UNVALIDATED','purchase_decision':'skip','official_source_requests':0},sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    try:run(args.output,execute=args.execute)
    except (ValueError,RuntimeError,OSError) as error:
        code=str(error)
        allowed={'RESEARCH_API_READBACK_MISMATCH','CURRENT_APPROVED_PROGRAM_REQUIRED','RESEARCH_TARGET_INVALID','RESEARCH_REQUEST_ID_INVALID'}
        stage=code if code in allowed or re.fullmatch(r'DAY_PUBLISH_HTTP_[0-9]{3}',code) else type(error).__name__
        print('SAFE_STOP: bounded research publication failed '+stage,flush=True);raise SystemExit(2)
