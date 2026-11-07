"""Resumable private official B/K collection. No BOATERS, forecasts or upload."""
from datetime import date,datetime,timedelta,timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib import request,error
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from race_ai.boat_history_store import HistoryStore,wire,instant,JST
from race_ai.core import SourceError
from race_ai.official_archive_probe import official_url,StrictRedirect,MAX_ARCHIVE_BYTES,inspect_lzh
from race_ai.source_retry_policy import SourceWait,plan_http_wait,wait_active


def private_root(path):
    path=Path(path).absolute()
    if path.is_symlink():raise ValueError('HISTORY_PRIVATE_ROOT_OUTSIDE_GIT_REQUIRED')
    path=path.resolve()
    if any((p/'.git').exists() for p in (path,*path.parents)):
        raise ValueError('HISTORY_PRIVATE_ROOT_OUTSIDE_GIT_REQUIRED')
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    if path.stat().st_mode&0o077:raise ValueError('HISTORY_PRIVATE_ROOT_REQUIRED')
    return path


def save(path,body,*,replace=False):
    if path.is_symlink():raise ValueError('HISTORY_CAPTURE_SYMLINK_REJECTED')
    if path.exists() and not replace:
        if path.read_bytes()!=body:raise ValueError('HISTORY_CAPTURE_OVERWRITE_REJECTED')
        return
    temp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex)
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        with os.fdopen(fd,'wb') as out:out.write(body);out.flush();os.fsync(out.fileno())
        if replace:os.replace(temp,path)
        else:os.link(temp,path);temp.unlink()
    finally:
        if temp.exists():temp.unlink()


def transport(url):
    opener=request.build_opener(StrictRedirect)
    req=request.Request(url,headers={'User-Agent':'RACE-AI-personal-official-history/0.1','Accept':'application/octet-stream'})
    with opener.open(req,timeout=25) as response:
        if response.geturl()!=url:raise ValueError('HISTORY_SOURCE_REDIRECT_IDENTITY_REJECTED')
        raw=response.read(MAX_ARCHIVE_BYTES+1)
    inspect_lzh(raw)
    return raw,datetime.now(timezone.utc).isoformat()


def collect_day(day,root,store,*,fetch=transport):
    root=private_root(root)
    captures=root/'captures';captures.mkdir(mode=0o700,exist_ok=True)
    if captures.is_symlink() or captures.stat().st_mode&0o077:raise ValueError('HISTORY_PRIVATE_CAPTURE_DIRECTORY_REQUIRED')
    wait_path=root/'source-wait.json'
    if wait_path.exists():
        wait=json.loads(wait_path.read_text())
        if wait_active(wait,datetime.now(timezone.utc)):
            raise SourceWait(wait['reason'],wait['retry_at'],state=wait['state'])
    raw={};sources={}
    for kind in ('K','B'):
        url=official_url(day,kind);meta_path=captures/f'{kind}{day:%Y%m%d}.json'
        if meta_path.exists():
            if meta_path.is_symlink():raise ValueError('HISTORY_CAPTURE_METADATA_SYMLINK_REJECTED')
            meta=json.loads(meta_path.read_text())
            expected=f'{kind}{day:%Y%m%d}-{meta["source_sha256"]}.lzh'
            if meta.get('file')!=expected or not re.fullmatch(r'[BK][0-9]{8}-[a-f0-9]{64}\.lzh',expected) or meta.get('source_url')!=url:
                raise ValueError('HISTORY_CAPTURE_METADATA_IDENTITY_REJECTED')
            path=captures/expected
            if path.is_symlink():raise ValueError('HISTORY_CAPTURE_SYMLINK_REJECTED')
            body=path.read_bytes()
            if len(body)>MAX_ARCHIVE_BYTES or hashlib.sha256(body).hexdigest()!=meta['source_sha256']:
                raise ValueError('HISTORY_CAPTURE_BYTES_HASH_REJECTED')
        else:
            try:body,captured=fetch(url)
            except error.HTTPError as exc:
                if exc.code==404:return dict(day=day.isoformat(),status='HISTORICAL_ARCHIVE_UNAVAILABLE',missing_kind=kind)
                plan=plan_http_wait(exc.code,exc.headers,datetime.now(timezone.utc))
                save(wait_path,wire(plan).encode(),replace=True)
                raise SourceWait(plan['reason'],plan['retry_at'],state=plan['state']) from None
            except (error.URLError,TimeoutError):
                plan=plan_http_wait(None,{},datetime.now(timezone.utc))
                save(wait_path,wire(plan).encode(),replace=True)
                raise SourceWait(plan['reason'],plan['retry_at'],state=plan['state']) from None
            inspect_lzh(body)
            captured=instant(captured).isoformat()
            if instant(captured)>datetime.now(timezone.utc):raise ValueError('HISTORY_FUTURE_CAPTURE_REJECTED')
            sha=hashlib.sha256(body).hexdigest();filename=f'{kind}{day:%Y%m%d}-{sha}.lzh'
            meta=dict(source_url=url,source_sha256=sha,captured_at=captured,file=filename)
            save(captures/filename,body);save(meta_path,wire(meta).encode())
        raw[kind]=body;sources[kind]={k:meta[k] for k in ('source_url','source_sha256','captured_at')}
    return dict(store.ingest_day(day,raw['B'],raw['K'],sources['B'],sources['K']),status='IMPORTED_PRIVATE')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start',required=True,type=date.fromisoformat)
    p.add_argument('--end',required=True,type=date.fromisoformat)
    p.add_argument('--private-dir',required=True,type=Path)
    p.add_argument('--delay-seconds',type=float,default=2.)
    args=p.parse_args()
    if not args.start<=args.end<datetime.now(JST).date() or (args.end-args.start).days>=366 or not 1<=args.delay_seconds<=60:
        p.error('past date range up to 366 days and 1..60 second request interval required')
    root=private_root(args.private_dir);store=HistoryStore(root/'history.sqlite')
    outcomes=[];last=[None]
    def fetch(url):
        if last[0] is not None:
            remaining=args.delay_seconds-(time.monotonic()-last[0])
            if remaining>0:time.sleep(remaining)
        last[0]=time.monotonic()
        return transport(url)
    try:
        day=args.start
        while day<=args.end:
            stopped=False
            try:result=collect_day(day,root,store,fetch=fetch)
            except SourceWait as exc:
                result=dict(day=day.isoformat(),status=exc.state,reason=exc.reason,retry_at=exc.retry_at)
                stopped=True
            except (ValueError,SourceError,UnicodeError,OSError) as exc:
                # No source text or exception payload in progress logs.
                result=dict(day=day.isoformat(),status='PARSE_REVIEW_REQUIRED',error_class=type(exc).__name__)
            outcomes.append(result);print(wire(result),flush=True)
            save(root/'collection-report.json',wire(dict(requested_start=args.start.isoformat(),requested_end=args.end.isoformat(),days=outcomes,inventory=store.inventory(),complete=day==args.end and all(r['status']=='IMPORTED_PRIVATE' for r in outcomes))).encode(),replace=True)
            if stopped:break
            day+=timedelta(days=1)
    finally:store.close()
    return 0 if len(outcomes)==(args.end-args.start).days+1 and all(r['status']=='IMPORTED_PRIVATE' for r in outcomes) else 2


if __name__=='__main__':raise SystemExit(main())
