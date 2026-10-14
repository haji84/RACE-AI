"""Bounded current-race collection and signed Preview cloud/API verification.

Reuses the approved current-day program rather than re-fetching the day source.
At most two upcoming preview/odds GETs, or one closed-race result GET. No polling,
source originals, Blob credentials, or manufactured historical availability.
Explicit --mode result selects the most recent closed race even while others
are upcoming. Before the first current-day closing, result mode is a no-op.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import urllib.request
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from publish_day_feed import NoRedirect, get_json, validate_target, canonical_sha
from race_ai.official_update_worker import collect_race_update
from race_ai.official_observation_store import setup_store, save_observation, latest_observation
from race_ai.race_update_merge import bundle_for_race
from web.race_contract import stamp

JST=ZoneInfo('Asia/Tokyo')


class RaceSourceFailure(ValueError):
    """Only fixed kind/status codes; never originals, transport details or tokens."""
    def __init__(self,failed):
        super().__init__('RACE_ALL_SOURCES_UNAVAILABLE')
        self.failed_kinds=dict(failed)


def selection_options(mode,race_id):
    if not isinstance(mode,str) or mode not in {'auto','result'} or (race_id is not None and mode!='result'):
        raise ValueError('RACE_SELECTION_MODE_INVALID')
    if race_id is not None:
        if not isinstance(race_id,str) or not re.fullmatch(r'[0-9]{8}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])',race_id):
            raise ValueError('RESULT_RACE_ID_INVALID')
        try:datetime.strptime(race_id[:8],'%Y%m%d')
        except ValueError as error:raise ValueError('RESULT_RACE_ID_INVALID') from error


def select_race(feed,now,mode='auto',race_id=None):
    selection_options(mode,race_id)
    now=datetime.fromisoformat(stamp(now))
    if (feed.get('date_jst')!=now.astimezone(JST).date().isoformat() or feed.get('schedule_verified') is not True
            or feed.get('redistribution_authorized') is not True or len(feed.get('venues',[]))!=24):
        raise ValueError('CURRENT_APPROVED_PROGRAM_REQUIRED')
    closing=lambda race:datetime.fromisoformat(stamp(race['closed_at']))
    day=now.astimezone(JST).date();prefix=day.strftime('%Y%m%d')+'-'
    if race_id is not None and not race_id.startswith(prefix):raise ValueError('RESULT_RACE_ID_INVALID')
    races=[race for venue in feed['venues'] if venue.get('status')=='READY' for race in venue['races']
           if len(race['boats'])==6 and isinstance(race.get('race_id'),str) and race['race_id'].startswith(prefix)
           and closing(race).tzinfo is not None and closing(race).astimezone(JST).date()==day]
    closed=[race for race in races if closing(race)<=now]
    if mode=='result':
        if race_id is not None:
            matches=[race for race in races if race['race_id']==race_id]
            if len(matches)>1:raise ValueError('CURRENT_APPROVED_PROGRAM_REQUIRED')
            return (matches[0],('raceresult',)) if matches and closing(matches[0])<=now else (None,())
        return (max(closed,key=lambda r:(closing(r),r['race_id'])),('raceresult',)) if closed else (None,())
    upcoming=sorted((r for r in races if closing(r)>now),key=lambda r:(closing(r),r['race_id']))
    if upcoming:return upcoming[0],('beforeinfo','odds3t')
    if races:return max(races,key=lambda r:(closing(r),r['race_id'])),('raceresult',)
    return None,()


def workflow_session(commit):
    issuer_url=os.environ.get('ACTIONS_ID_TOKEN_REQUEST_URL','');issuer_token=os.environ.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN','')
    try:
        parsed=urlsplit(issuer_url)
        valid=(parsed.scheme=='https' and (parsed.hostname or '').endswith('.actions.githubusercontent.com')
            and not parsed.username and not parsed.password and not parsed.fragment and parsed.port in (None,443)
            and not any(ord(c)<=32 or ord(c)>126 for c in issuer_url))
    except ValueError:valid=False
    if not valid or not re.fullmatch(r'[0-9a-f]{40}',commit) or not re.fullmatch(r'[A-Za-z0-9_.-]+',issuer_token):
        raise ValueError('RACE_WORKFLOW_CONFIG_INVALID')
    opener=urllib.request.build_opener(NoRedirect())
    separator='&' if '?' in issuer_url else '?'
    response=get_json(opener,urllib.request.Request(issuer_url+separator+'audience=race-ai-preview-blob-probe',
        headers={'Authorization':'Bearer '+issuer_token}),limit=16384)
    token=response.get('value')
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,8192}',token):raise ValueError('OIDC_TOKEN_INVALID')
    return opener,{'Authorization':'Bearer '+token,'x-vercel-trusted-oidc-idp-token':token,
        'X-Race-AI-Commit':commit,'Content-Type':'application/json'}


def collect_bundle(feed,review,*,now=None,collector=collect_race_update,clock=None,mode='auto',race_id=None):
    clock=clock or (lambda:datetime.now(timezone.utc))
    now=now or clock();race,kinds=select_race(feed,now,mode=mode,race_id=race_id)
    if race is None:return None,{}
    day=datetime.strptime(race['race_id'][:8],'%Y%m%d').date();venue=race['race_id'][9:11];number=int(race['race_id'][-2:])
    records=[];failed={}
    with sqlite3.connect(':memory:') as db:
        setup_store(db)
        for kind in kinds:
            observation=collector(day,venue,number,kind,review=review,execute=True,entries=race['boats'])
            if observation.get('status') not in {'AVAILABLE','PARTIAL','PENDING'}:
                # Independent kinds can succeed. A failed endpoint never creates
                # an observation or overwrites its last verified cloud version.
                status=observation.get('status')
                failed[kind]=status if status in {'SOURCE_RIGHTS_BLOCKED','SOURCE_UNAVAILABLE','SOURCE_INVALID'} else 'SOURCE_INVALID'
                continue
            save_observation(db,observation)
            records.append(latest_observation(db,race['race_id'],kind,as_of=clock()))
    if not records:raise RaceSourceFailure(failed)
    return bundle_for_race(race,records,now=clock()),failed


def run(review_path,output_path,*,execute=False,mode='auto',race_id=None):
    selection_options(mode,race_id)
    url=os.environ.get('RACE_AI_RACE_PUBLISH_URL','')
    if not url.endswith('/api/publish-race'):raise ValueError('RACE_PUBLISH_TARGET_INVALID')
    validate_target(url[:-len('publish-race')]+'publish-day')
    commit=os.environ.get('RACE_AI_RACE_COMMIT_SHA','')
    if not execute:
        print(json.dumps({'result':'DRY_RUN','network_requests':0,'maximum_official_source_requests':1 if mode=='result' else 2}));return
    if review_path.stat().st_size>100000:raise ValueError('REVIEW_SIZE_INVALID')
    review=json.loads(review_path.read_text(encoding='utf-8-sig'))
    opener,headers=workflow_session(commit);base=url.rsplit('/',1)[0]
    feed=get_json(opener,urllib.request.Request(base+'/today',headers=headers),limit=6_000_000)
    bundle,failed=collect_bundle(feed,review,mode=mode,race_id=race_id)
    if bundle is None:
        print(json.dumps({'result':'NO_CLOSED_RACE' if mode=='result' else 'NO_ACTIVE_RACE','date_jst':feed['date_jst']}));return
    request={'publication_review':'user-confirmation-2026-10-15-official-facts','bundle':bundle}
    raw=json.dumps(request,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    if len(raw)>256000:raise ValueError('RACE_BUNDLE_TOO_LARGE')
    # A failed API call remains reproducible from approved normalized input.
    # This file contains neither credentials nor original source HTML.
    output_path.parent.mkdir(parents=True,exist_ok=True)
    with output_path.with_suffix('.request.json').open('xb') as handle:handle.write(raw)
    result=get_json(opener,urllib.request.Request(url,data=raw,method='POST',headers=headers),limit=16384)
    served=get_json(opener,urllib.request.Request(base+'/race?race_id='+bundle['race_id'],headers=headers),limit=256000)
    digest=canonical_sha(served)
    if (result.get('status')!='verified' or result.get('commit_sha')!=commit or result.get('race_id')!=bundle['race_id']
            or served.get('race_id')!=bundle['race_id'] or digest!=result.get('sha256')
            or set(result.get('accepted_snapshot_ids',[]))!={r['snapshot_id'] for r in bundle['records']}
            or not set(result['accepted_snapshot_ids'])<=set(served.get('latest',{}).values())):
        raise ValueError('RACE_API_READBACK_MISMATCH')
    # Only normalized approved facts. No originals, token, response headers or ledger.
    backup=json.dumps(served,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    output_path.parent.mkdir(parents=True,exist_ok=True)
    with output_path.open('xb') as handle:handle.write(backup)
    print(json.dumps({'result':'OFFICIAL_RACE_API_PARTIAL_VERIFIED' if failed else 'OFFICIAL_RACE_API_VERIFIED',
        'failed_kinds':failed,'race_id':bundle['race_id'],'commit_sha':commit,
        'sha256':digest,'backup_file_sha256':hashlib.sha256(backup).hexdigest(),'records':[
            {'kind':r['record']['kind'],'status':r['record']['status'],'captured_at':r['record']['captured_at'],
             'cloud_saved_at':r['cloud_saved_at'],'cloud_eligible_pre_race':r['cloud_eligible_pre_race'],
             'source_sha256':r['record']['source_sha256'],'snapshot_id':r['record']['snapshot_id']}
            for r in served['records']]},sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--mode',choices=('auto','result'),default='auto')
    parser.add_argument('--race-id',help='Exact approved current-day closed race; requires --mode result')
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    try:run(args.review,args.output,execute=args.execute,mode=args.mode,race_id=args.race_id)
    except (ValueError,RuntimeError,OSError,sqlite3.Error) as error:
        if isinstance(error,RaceSourceFailure):
            print(json.dumps({'result':'OFFICIAL_RACE_SOURCES_REJECTED','failed_kinds':error.failed_kinds},sort_keys=True))
        code=str(error)
        allowed={'RACE_ALL_SOURCES_UNAVAILABLE','RACE_SELECTION_MODE_INVALID','RESULT_RACE_ID_INVALID',
                 'RACE_API_READBACK_MISMATCH','CURRENT_APPROVED_PROGRAM_REQUIRED','RACE_BUNDLE_TOO_LARGE',
                 'RACE_WORKFLOW_CONFIG_INVALID','OIDC_TOKEN_INVALID','RACE_PUBLISH_TARGET_INVALID','PUBLISH_TARGET_INVALID'}
        stage=code if code in allowed or re.fullmatch(r'DAY_PUBLISH_HTTP_[0-9]{3}',code) else type(error).__name__
        print('SAFE_STOP: bounded race publication failed '+stage,flush=True);raise SystemExit(2)
