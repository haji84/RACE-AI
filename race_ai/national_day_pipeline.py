"""Two-request current-day official feed: complete index plus official B archive.

Default dry-run performs no network or output writes. Explicit execution uses
the owner's recorded factual-data review, not a permission-granting CLI flag.
Only normalized factual JSON is saved; source HTML, archive and text stay in
memory. A B failure preserves the verified schedule and explicit venue errors.
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib import request

from .core import SourceError
from .day_snapshot_publisher import validate
from .official_archive_probe import official_url, inspect_lzh, StrictRedirect, MAX_ARCHIVE_BYTES
from .official_b_snapshot_adapter import normalize_b_snapshot
from .official_day_schedule import collect_day_schedule, merge_schedule_programs, endpoint, SOURCE_SCOPE, JST
from .official_lzh_extract import extract_daily_lzh
from .tokuyama_day_worker import FetchResponse
from .venue_source_rights import RightsRecord

ARCHIVE_SCOPE = 'https://www1.mbrace.or.jp/od2/B/'


def validate_review(review, *, day, now):
    if (not isinstance(review, dict) or review.get('review_type') != 'owner_attestation'
            or not all(review.get(purpose) is True for purpose in ('facts_ingest','facts_store','facts_publish'))
            or not review.get('evidence_reference') or not review.get('reviewed_by') or not review.get('owner_statement')
            or set(review.get('venue_codes',[])) != {f'{n:02d}' for n in range(1,25)}
            or not {SOURCE_SCOPE,ARCHIVE_SCOPE}.issubset(set(review.get('source_scopes',[])))):
        raise SourceError('operator factual-data review incomplete')
    stamp = datetime.fromisoformat(review['reviewed_at'].replace('Z','+00:00'))
    if stamp.tzinfo is None or stamp > now or now.tzinfo is None or now.astimezone(JST).date() != day:
        raise SourceError('operator review timestamp or requested day invalid')
    return review


def fetch_archive(url, *, max_bytes=MAX_ARCHIVE_BYTES, timeout=25):
    # Caller has already matched the exact generated current-day URL against
    # the owner's source scope. This boundary never accepts arbitrary hosts.
    from urllib.parse import urlsplit
    u=urlsplit(url)
    if (u.scheme != 'https' or u.netloc != 'www1.mbrace.or.jp' or not re.fullmatch(r'/od2/B/[0-9]{6}/b[0-9]{6}\.lzh',u.path)
            or u.query or u.fragment or max_bytes != MAX_ARCHIVE_BYTES or timeout != 25):
        raise SourceError('unexpected archive endpoint or fetch bounds')
    req=request.Request(url,headers={'User-Agent':'RACE-AI-authorized-national-worker/0.15','Accept':'application/octet-stream'})
    with request.build_opener(StrictRedirect).open(req,timeout=timeout) as response:
        return FetchResponse(response.read(max_bytes+1),response.geturl(),response.status,
                             response.headers.get('Content-Type',''))


def collect_national_day(day, *, review, execute=False, now=None,
                         schedule_transport=None, archive_transport=None):
    supplied_clock=now is not None
    now=now or datetime.now(timezone.utc)
    validate_review(review,day=day,now=now)
    if not execute:
        return dict(status='DRY_RUN',date_jst=day.isoformat(),network_requests=0,
                    maximum_source_requests=2,source_urls=[endpoint(day),official_url(day,'B')],
                    source_originals_retained=False)
    rights=[RightsRecord(code,'facts_ingest','allowed',SOURCE_SCOPE,review['reviewed_at'],
                         review['evidence_reference'],review['reviewed_by']) for code in review['venue_codes']]
    schedule=collect_day_schedule(day,rights=rights,execute=True,now=now if supplied_clock else None,
                                  transport=schedule_transport)
    if schedule['status']!='OFFICIAL_DAY_SCHEDULE_VERIFIED':
        raise SourceError('official current-day schedule unavailable or invalid')
    programs=None
    errors={}
    try:
        url=official_url(day,'B')
        response=(archive_transport or fetch_archive)(url,timeout=25,max_bytes=MAX_ARCHIVE_BYTES)
        if not isinstance(response,FetchResponse) or response.status!=200 or response.url!=url or not isinstance(response.body,bytes):
            raise SourceError('official B response invalid')
        info=inspect_lzh(response.body)
        text=extract_daily_lzh(response.body,'B'+day.strftime('%y%m%d')+'.TXT')
        captured=now if supplied_clock else datetime.now(timezone.utc)
        programs=normalize_b_snapshot(text,day=day,source_url=url,observed_at=captured.isoformat(),
                                      require_details=True,archive_sha256=info['sha256'])
    except (ValueError,OSError,TimeoutError,TypeError):
        errors={code:'OFFICIAL_PROGRAM_UNAVAILABLE_OR_INVALID' for code in schedule['active_venues']}
    payload=merge_schedule_programs(schedule,programs,errors=errors)
    payload['publication_review']=review['evidence_reference']
    payload['source_originals_retained']=False
    if programs:
        payload['sources'][1].update(extracted_text_sha256=programs['extracted_text_sha256'],source_hash_scope='downloaded_archive')
    def permission(url):
        return dict(source_url=url,redistribution_authorized=True,
                    evidence_reference=review['evidence_reference'],reviewed_by=review['reviewed_by'])
    approval=permission(payload['source_url'])
    approval['source_approvals']=[permission(source['source_url']) for source in payload['sources'][1:]]
    approved=validate(payload,today=day,approval=approval,now=now if supplied_clock else None)
    approved['status']='APPROVED_CURRENT_DAY_SNAPSHOT'
    approved['maximum_source_requests']=2
    return approved


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',type=date.fromisoformat,default=datetime.now(JST).date())
    parser.add_argument('--review',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    try:
        if args.review.stat().st_size>100000:
            raise SourceError('operator review too large')
        review=json.loads(args.review.read_text(encoding='utf-8-sig'))
        result=collect_national_day(args.date,review=review,execute=args.execute)
        if args.execute:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
        print(json.dumps({key:result[key] for key in ('status','date_jst','races','complete_six_boat_races','maximum_source_requests') if key in result},ensure_ascii=False))
    except (ValueError,OSError,TypeError,KeyError):
        print('SAFE_STOP: official day source or operator review invalid',file=sys.stderr)
        raise SystemExit(2)


if __name__=='__main__':
    main()
