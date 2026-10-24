"""Minimal, nonpersistent probe for an officially published BOATRACE K LZH.

Downloading a specifically announced official file is not equivalent to
permission for mass reproduction, redistribution or commercial database use.
Probe fetches one daily archive; no raw data is retained or uploaded.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import sys
from urllib import request,parse,error

from .core import SourceError
HOST="www1.mbrace.or.jp"
MAX_ARCHIVE_BYTES=16_000_000


def official_url(day:date, kind:str="K")->str:
    if kind not in ("B","K"):
        raise SourceError("only official B/K archive identifiers are allowed")
    name=f"{kind.lower()}{day.strftime('%y%m%d')}.lzh"
    return f"https://{HOST}/od2/{kind}/{day.strftime('%Y%m')}/{name}"


class StrictRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target=parse.urlsplit(newurl)
        if target.scheme!="https" or target.netloc!=HOST:
            raise SourceError("external official archive redirect rejected")
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def inspect_lzh(raw:bytes)->dict:
    """Check normal level-0/1 LZH header, not decompression or archive content."""
    if len(raw)<25:
        raise SourceError("archive too small")
    if len(raw)>MAX_ARCHIVE_BYTES:
        raise SourceError("official archive exceeds size cap")
    method=raw[2:7]
    if len(method)!=5 or method[:3]!=b"-lh" or method[-1:]!=b"-":
        raise SourceError("LZH method header missing")
    level=raw[20]
    if level not in (0,1,2):
        raise SourceError("unexpected LZH header level")
    return dict(format="LZH",method=method.decode("ascii"),header_level=level,
                byte_count=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
                contents_parsed=False,official_races_reconciled=False)


def probe(day:date,kind:str="K")->dict:
    url=official_url(day,kind)
    opener=request.build_opener(StrictRedirect)
    req=request.Request(url,headers={"User-Agent":"RACE-AI-official-data-integrity-probe/0.12",
                                      "Accept":"application/octet-stream"})
    try:
        with opener.open(req,timeout=25) as res:
            final=parse.urlsplit(res.geturl())
            if final.scheme!="https" or final.netloc!=HOST:
                raise SourceError("unexpected host")
            if res.status!=200:
                raise SourceError(f"HTTP {res.status}")
            raw=res.read(MAX_ARCHIVE_BYTES+1)
    except (error.URLError,TimeoutError) as exc:
        raise SourceError(f"official archive download unavailable: {type(exc).__name__}") from exc
    info=inspect_lzh(raw)
    return dict(day=day.isoformat(),kind=kind,url=url,
                verification="ARCHIVE_HEADER_ONLY",**info)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--date",required=True,help="YYYY-MM-DD")
    p.add_argument("--kind",choices=("B","K"),default="K")
    a=p.parse_args()
    try:
        info=probe(date.fromisoformat(a.date),a.kind)
    except (SourceError,ValueError) as exc:
        print(f"SAFE_STOP: {exc}",file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(info,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
