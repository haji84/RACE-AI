"""Explicit one-race one-endpoint collector and append-only observation CLI.

Dry-run by default. Source originals are never saved. Official data-not-ready
responses become pending observations, never zero odds or losing results.
"""
import argparse
from datetime import date,datetime,timezone
import json
from pathlib import Path
import sqlite3
import sys
from urllib import request,error

from .core import SourceError
from .official_race_updates import KINDS,endpoint,parse_update
from .official_racelist_adapter import HOST,JST,MAX_BYTES,identity
from .official_observation_store import setup_store,save_observation
from .tokuyama_day_worker import FetchResponse,NoRedirects,TIMEOUT


def reviewed_scope(review,*,day,venue,kind,now):
    scope=f'https://{HOST}/owpc/pc/race/{kind}'
    if (not isinstance(review,dict) or review.get('review_type')!='owner_attestation'
            or review.get('facts_ingest') is not True or review.get('facts_store') is not True
            or venue not in review.get('venue_codes',[]) or scope not in review.get('source_scopes',[])
            or not review.get('evidence_reference') or not review.get('reviewed_by') or not review.get('owner_statement')):
        raise SourceError('official update purpose or source scope unapproved')
    reviewed=datetime.fromisoformat(review['reviewed_at'].replace('Z','+00:00'))
    if now.tzinfo is None or reviewed.tzinfo is None or reviewed>now or day>now.astimezone(JST).date():
        raise SourceError('invalid review clock or future race date')


def fetch_update(url,*,timeout=TIMEOUT,max_bytes=MAX_BYTES):
    from urllib.parse import urlsplit
    kind=urlsplit(url).path.rsplit('/',1)[-1]
    if kind not in KINDS: raise SourceError('unsupported official endpoint')
    hd,venue,number=identity(url,path='/owpc/pc/race/'+kind)
    day=datetime.strptime(hd,'%Y%m%d').date()
    if url!=endpoint(day,venue,number,kind) or timeout!=TIMEOUT or max_bytes!=MAX_BYTES: raise SourceError('update bounds or endpoint changed')
    req=request.Request(url,headers={'User-Agent':'RACE-AI-authorized-single-race-worker/0.16','Accept':'text/html'})
    with request.build_opener(NoRedirects).open(req,timeout=timeout) as response:
        return FetchResponse(response.read(max_bytes+1),response.geturl(),response.status,response.headers.get('Content-Type',''))


def collect_race_update(day,venue,race_no,kind,*,review,execute=False,now=None,transport=None,entries=None):
    url=endpoint(day,venue,race_no,kind);base=dict(race_id=f'{day:%Y%m%d}-{venue}-{race_no:02d}',kind=kind,source_url=url)
    supplied_clock=now is not None;now=now or datetime.now(timezone.utc)
    try: reviewed_scope(review,day=day,venue=venue,kind=kind,now=now)
    except (ValueError,TypeError,AttributeError,KeyError): return {**base,'status':'SOURCE_RIGHTS_BLOCKED'}
    if not execute: return {**base,'status':'DRY_RUN','network_requests':0,'maximum_source_requests':1}
    try:
        response=(transport or fetch_update)(url,timeout=TIMEOUT,max_bytes=MAX_BYTES)
    except (error.URLError,OSError,TimeoutError): return {**base,'status':'SOURCE_UNAVAILABLE'}
    except SourceError: return {**base,'status':'SOURCE_INVALID'}
    if (not isinstance(response,FetchResponse) or response.status!=200 or response.url!=url
            or not isinstance(response.body,bytes) or len(response.body)>MAX_BYTES
            or not isinstance(response.content_type,str) or response.content_type.split(';')[0].strip().lower()!='text/html'):
        return {**base,'status':'SOURCE_INVALID'}
    captured=now if supplied_clock else datetime.now(timezone.utc)
    try:
        result=parse_update(response.body,kind=kind,day=day,venue=venue,race_no=race_no,
            source_url=url,captured_at=captured.isoformat(),entries=entries)
        result['rights_review']=review['evidence_reference']
        return result
    except SourceError: return {**base,'status':'SOURCE_INVALID'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',required=True,type=date.fromisoformat)
    parser.add_argument('--venue',required=True)
    parser.add_argument('--race',required=True,type=int)
    parser.add_argument('--kind',required=True,choices=sorted(KINDS))
    parser.add_argument('--review',required=True,type=Path)
    parser.add_argument('--db',required=True,type=Path)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    try:
        if args.review.stat().st_size>100000: raise SourceError('review too large')
        review=json.loads(args.review.read_text(encoding='utf-8-sig'))
        result=collect_race_update(args.date,args.venue,args.race,args.kind,review=review,execute=args.execute)
        report={key:result[key] for key in ('race_id','kind','status','source_url','source_sha256','captured_at','network_requests') if key in result}
        if args.execute and result['status'] in {'AVAILABLE','PARTIAL','PENDING'}:
            args.db.parent.mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(args.db) as db:
                setup_store(db);report['snapshot_id']=save_observation(db,result)
        print(json.dumps(report,ensure_ascii=False))
        if result['status'] not in {'DRY_RUN','AVAILABLE','PARTIAL','PENDING'}: raise SystemExit(2)
    except (ValueError,TypeError,OSError,sqlite3.Error):
        print('SAFE_STOP: official update or operator configuration invalid',file=sys.stderr)
        raise SystemExit(2)


if __name__=='__main__': main()
