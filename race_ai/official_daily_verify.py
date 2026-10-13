"""Read a single official K/B daily archive to an ephemeral parsed report.

No raw races, copyrightable text or binary archive are saved or republished.
Reports only aggregate counts and structural validation status. Expected
publication time is not invented from the retrieval time.
"""
from __future__ import annotations

import argparse
from datetime import date,datetime,timezone
import hashlib
import json
import sys
from urllib import request,parse,error

from .core import SourceError,parse_k,parse_b
from .official_archive_probe import official_url,inspect_lzh,HOST,MAX_ARCHIVE_BYTES,StrictRedirect
from .official_lzh_extract import extract_daily_lzh


def fetch_and_parse(day:date,kind:str="K")->dict:
    url=official_url(day,kind)
    opener=request.build_opener(StrictRedirect)
    req=request.Request(url,headers={"User-Agent":"RACE-AI-official-daily-integrity/0.12",
                                     "Accept":"application/octet-stream"})
    try:
        with opener.open(req,timeout=25) as response:
            final=parse.urlsplit(response.geturl())
            if final.scheme!="https" or final.netloc!=HOST:
                raise SourceError('unapproved source')
            raw=response.read(MAX_ARCHIVE_BYTES+1)
    except (error.URLError,TimeoutError) as exc:
        raise SourceError(f"official archive unavailable ({type(exc).__name__})") from exc
    meta=inspect_lzh(raw)
    entry_name=kind+day.strftime('%y%m%d')+'.TXT'
    text=extract_daily_lzh(raw,entry_name)
    rows=(parse_k(text,day.isoformat()) if kind=='K' else parse_b(text,day.isoformat()))
    ids={(x['race_id'],x['lane']) for x in rows}
    if len(ids)!=len(rows):
        raise SourceError('duplicate lane in official parsed text')
    ids_race={x['race_id'] for x in rows}
    venues={rid[9:11] for rid in ids_race}
    if len(ids_race)*6!=len(rows):
        raise SourceError('not every race has six parsed entrants')
    if len(venues)>24:
        raise SourceError('unreasonable official venue count')
    return dict(date_jst=day.isoformat(),kind=kind,source_url=url,
      download_sha256=meta['sha256'],
      extracted_text_sha256=hashlib.sha256(text).hexdigest(),
      retrieved_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
      source_official=True,source_published_at=None,
      lzh_header_validated=True,text_decoded=True,
      structural_entries=len(rows),races=len(ids_race),venue_count=len(venues),
      venues=sorted(venues),parsed_results_verified_against_official_site=False,
      complete_24_venue_calendar_checked=False,
      status='STRUCTURAL_ACCEPTED_REQUIRES_OFFICIAL_RECONCILIATION')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--date',required=True)
    p.add_argument('--kind',choices=('B','K'),default='K')
    a=p.parse_args()
    try:
        res=fetch_and_parse(date.fromisoformat(a.date),a.kind)
    except (SourceError,ValueError,TypeError) as exc:
        print(f"SAFE_STOP: {exc}",file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(res,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
