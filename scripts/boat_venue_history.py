"""All published official history: monthly encrypted checkpoints, venue samples.

No provider API crawl, raw public output, forecast mutation, substitute key,
new scheduler or new cloud. Missing/unsupported dates stay explicit gaps.
"""
import argparse
import atexit
import base64
from concurrent.futures import ThreadPoolExecutor,wait as wait_futures,FIRST_COMPLETED
from datetime import date,datetime,timedelta,timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import ssl
import tempfile
import threading
import time
import httpx

from race_ai.actions_contract import stamp
from race_ai.teiai_history import need
from race_ai.boat_racer_term import extract_term,parse_term
from race_ai.boat_history_catalog import HistoryMonth,published_months
from race_ai.boat_venue_history import VenueHistory,JST
from race_ai.official_archive_probe import official_url
from race_ai.source_retry_policy import SourceWait,plan_http_wait,wait_active
from scripts.boat_all_racers import _read,_write,_codec,_key_ready,_now

MENU='https://www1.mbrace.or.jp/od2/K/dmenu.html'
SOURCE=re.compile(r'https://www1\.mbrace\.or\.jp/od2/(?:K/(?:dmenu\.html|[0-9]{6}/(?:mday\.html|k[0-9]{6}\.lzh))|B/[0-9]{6}/b[0-9]{6}\.lzh)\Z')
_SESSION=None
_HTTP_LOCK=threading.Lock()
_HTTP_NEXT_START=0.
_HTTP_WAIT=None


def _source_wait(plan,*,attempted):
    global _HTTP_WAIT
    if plan.get('http_status')!=404:_HTTP_WAIT=plan
    wait=SourceWait(plan['reason'],plan['retry_at'],state=plan['state'])
    wait.plan=plan;wait.upstream_attempted=attempted
    raise wait from None


def _http_session():
    global _SESSION,_HTTP_NEXT_START,_HTTP_WAIT
    with _HTTP_LOCK:
        for pause in (False,True):
            if _HTTP_WAIT and wait_active(_HTTP_WAIT,_now()):_source_wait(_HTTP_WAIT,attempted=False)
            _HTTP_WAIT=None
            if not pause:time.sleep(max(0.,_HTTP_NEXT_START-time.monotonic()))
        _HTTP_NEXT_START=time.monotonic()+1. # one start/second across both connections
        if _SESSION is None:
            _SESSION=httpx.Client(verify=ssl.create_default_context(),follow_redirects=False,trust_env=True,
                timeout=25,limits=httpx.Limits(max_connections=2,max_keepalive_connections=2))
            atexit.register(_SESSION.close)
        return _SESSION


def _http(url):
    need(SOURCE.fullmatch(url),'HISTORY_TRANSPORT_URL_REJECTED')
    try:
        with _http_session().stream('GET',url,headers={'User-Agent':'RACE-AI-owner-personal-published-history/1'}) as response:
            if response.status_code!=200:_source_wait(plan_http_wait(response.status_code,response.headers,_now()),attempted=True)
            limit=200000 if url.endswith('.html') else 16000000
            chunks=[];size=0
            for chunk in response.iter_bytes():
                size+=len(chunk);need(size<=limit,'HISTORY_HTTP_IDENTITY_SIZE_REJECTED');chunks.append(chunk)
            raw=b''.join(chunks)
            need(str(response.url)==url and raw,'HISTORY_HTTP_IDENTITY_SIZE_REJECTED')
        captured=_now()
        return raw,captured
    except (httpx.HTTPError,TimeoutError,OSError):
        _source_wait(plan_http_wait(None,{},_now()),attempted=True)


def inspect_sources(source_dir,*,term_file,menu_file,end):
    menu=_read(menu_file,200000);months=published_months(menu)
    start=months[0][:4]+'-'+months[0][4:]+'-01'
    roster=[r['racer_id'] for r in parse_term(extract_term(_read(term_file),term='2026-2'),term='2026-2')]
    engine=VenueHistory(start=start,end=end,roster=roster);quarantine=[];files=0
    for path in sorted(Path(source_dir).glob('k??????.lzh')):
        m=re.fullmatch(r'k([0-9]{6})\.lzh',path.name)
        if not m:continue
        day=datetime.strptime(m[1],'%y%m%d').date()
        if day.strftime('%Y%m') not in months or not date.fromisoformat(start)<=day<=date.fromisoformat(end):continue
        files+=1
        try:engine.add_archive(_read(path,16000000),day=day.isoformat(),captured_at=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat())
        except ValueError:quarantine.append(dict(day=day.isoformat(),reason='OFFICIAL_FORMAT_OR_SPECIAL_RESULT_UNSUPPORTED'))
    report=engine.summary(as_of=_now())
    report.update(source_archive_files=files,quarantined_sources=quarantine,published_months_count=len(months),
                  first_published_month=months[0],latest_published_month=months[-1],
                  published_menu_sha256=hashlib.sha256(menu).hexdigest(),menu_source=MENU,
                  full_grid_readback_cells=sum(1 for _ in engine.profiles(as_of=_now())),
                  durable_encrypted_storage_verified=False,all_provider_periods_complete=False)
    return report


def _scope(generation=1,previous=None):
    return dict(schema='RACE_AI_GITHUB_SQLITE_V1',repository_id='1416489937',mode='production',
                generation=generation,previous_cipher_sha256=previous)


def restore_month(folder,*,expected_month):
    need(_key_ready(),'OWNER_STATE_KEY_REQUIRED')
    p=Path(folder);report=json.loads(_read(p/'summary.json',64000));scope=report['scope']
    need(report['month']==expected_month and scope['mode']=='production','HISTORY_CHECKPOINT_MONTH_OR_MODE_INVALID')
    cipher=_read(p/'history.checkpoint',12*1024*1024);sha=hashlib.sha256(cipher).hexdigest()
    need(sha==report['ciphertext_sha256'],'HISTORY_CHECKPOINT_CIPHER_HASH_INVALID')
    with tempfile.TemporaryDirectory(prefix='race-ai-history-restore-') as temp:
        t=Path(temp);_write(t/'scope.json',json.dumps(scope).encode())
        _codec('unseal',p/'history.checkpoint',t/'private.sqlite',t/'scope.json',cipher_sha=sha)
        c=HistoryMonth.restore(_read(t/'private.sqlite',8*1024*1024),expected_sha256=report['sqlite_sha256'],month=expected_month)
    need(c.summary()==report['catalog'],'HISTORY_CATALOG_READBACK_MISMATCH')
    return c,report


def capture_month(out,*,month,not_after=None,roster=(),resume=None,max_files=31,reparse_only=False,only_days=None,minimum_source_at=None):
    out=Path(out);out.mkdir(parents=True,mode=0o700,exist_ok=True)
    need(not any(out.iterdir()),'HISTORY_OUTPUT_EXISTS_DO_NOT_RESET')
    if not _key_ready():
        report=dict(status='HOLD_OWNER_STATE_KEY_MISSING',upstream_gets=0,encrypted_checkpoint_created=False,
                    all_available_period_complete=False)
        _write(out/'summary.json',json.dumps(report).encode());return report
    need(type(max_files) is int and 1<=max_files<=31,'HISTORY_BATCH_LIMIT_INVALID')
    until=not_after or datetime.now(JST).date().isoformat()
    gets=0;counter_lock=threading.Lock();paused=[None]
    def fetch(url):
        nonlocal gets
        if paused[0]:
            plan=paused[0];exc=SourceWait(plan['reason'],plan['retry_at'],state=plan['state'])
            exc.plan=plan;exc.upstream_attempted=False;raise exc
        if only_days is not None:
            need(minimum_source_at is not None and stamp(_now())>=stamp(minimum_source_at),'HISTORY_DELTA_CLOCK_REGRESSION')
        attempted=True
        try:return _http(url)
        except SourceWait as exc:
            attempted=getattr(exc,'upstream_attempted',True)
            if exc.plan.get('http_status')!=404:paused[0]=exc.plan
            raise
        finally:
            if attempted:
                with counter_lock:gets+=1
    def hold(plan):
        report=dict(status='HOLD_SOURCE_WAIT',month=month,upstream_gets=gets,source_wait=plan,
                    encrypted_checkpoint_created=False,all_available_period_complete=False)
        report['hold_mac']=_manifest_mac(report)
        _write(out/'summary.json',json.dumps(report,sort_keys=True).encode());return report
    if resume is not None:
        previous=json.loads(_read(Path(resume)/'summary.json',64000))
        if previous.get('encrypted_checkpoint_created') is not True:
            need(not (Path(resume)/'history.checkpoint').exists(),'HISTORY_HOLD_HAS_UNEXPECTED_CIPHERTEXT')
            if previous['status']=='HOLD_SOURCE_WAIT':
                mac=previous.pop('hold_mac',None)
                need(isinstance(mac,str) and hmac.compare_digest(mac,_manifest_mac(previous)),'HISTORY_WAIT_AUTHENTICATION_FAILED')
                if wait_active(previous['source_wait'],_now()):return hold(previous['source_wait'])
            else:need(previous['status']=='HOLD_OWNER_STATE_KEY_MISSING','HISTORY_RESUME_STATE_INVALID')
            resume=None
    need(not reparse_only or resume is not None,'HISTORY_REPARSE_REQUIRES_CHECKPOINT')
    if resume is not None:
        catalog,old=restore_month(resume,expected_month=month)
        scope=_scope(old['scope']['generation']+1,old['ciphertext_sha256'])
        if reparse_only:
            for day in catalog.reparse_candidates():catalog.reparse(day,parsed_at=_now())
    else:
        try:
            menu,_=fetch(MENU);need(month in published_months(menu),'HISTORY_MONTH_NOT_PUBLISHED')
            index,_=fetch(f'https://www1.mbrace.or.jp/od2/K/{month}/mday.html')
        except SourceWait as exc:return hold(exc.plan)
        catalog=HistoryMonth(month=month,index_raw=index,not_after=until,roster=roster);scope=_scope()
    wait=catalog.active_wait(_now())
    if not wait and not reparse_only:
        pending_days=catalog.pending()
        if only_days is not None:
            need(type(only_days) is list and len(only_days)==len(set(only_days)),'HISTORY_DELTA_DAY_SCOPE_INVALID')
            for day in only_days:catalog._day(day)
            pending_days=[d for d in pending_days if d in only_days]
        days=iter(pending_days[:max_files])
        with ThreadPoolExecutor(max_workers=2,thread_name_prefix='official-history') as pool:
            pending={}
            def submit():
                day=next(days,None)
                if day is not None:pending[pool.submit(fetch,official_url(date.fromisoformat(day),'K'))]=day
            submit();submit()
            while pending:
                done,_=wait_futures(pending,return_when=FIRST_COMPLETED)
                for future in done:
                    day=pending.pop(future)
                    try:
                        raw,captured=future.result()
                        if only_days is not None:
                            need(stamp(minimum_source_at)<=stamp(captured)<=stamp(_now()),'HISTORY_DELTA_SOURCE_CLOCK_INVALID')
                        catalog.record(day,raw,captured_at=captured,parsed_at=_now())
                    except SourceWait as exc:
                        plan=exc.plan
                        if plan.get('http_status')==404:catalog.missing(day,captured_at=_now(),http_status=404)
                        else:wait=plan
                if not wait and not paused[0]:
                    while len(pending)<2:
                        before=len(pending);submit()
                        if len(pending)==before:break
        # A late successful in-flight response must not erase an earlier 429.
        catalog.set_wait(wait)
    return seal_catalog(out,catalog,scope,upstream_gets=gets,source_wait=wait)


def seal_catalog(out,catalog,scope,*,upstream_gets=0,source_wait=None):
    """The unchanged checkpoint codec shared by explicit dated extensions."""
    out=Path(out);out.mkdir(parents=True,mode=0o700,exist_ok=True)
    need(not any(out.iterdir()),'HISTORY_OUTPUT_EXISTS_DO_NOT_RESET')
    plain=catalog.serialize();sha=hashlib.sha256(plain).hexdigest()
    with tempfile.TemporaryDirectory(prefix='race-ai-history-seal-') as temp:
        t=Path(temp);_write(t/'private.sqlite',plain);_write(t/'scope.json',json.dumps(scope).encode())
        _codec('seal',t/'private.sqlite',out/'history.checkpoint',t/'scope.json')
    cipher=_read(out/'history.checkpoint',12*1024*1024)
    report=dict(status='ENCRYPTED_MONTH_HISTORY_CHECKPOINT_CREATED',month=catalog.month,catalog=catalog.summary(),
        upstream_gets=upstream_gets,scope=scope,source_wait=source_wait,sqlite_sha256=sha,ciphertext_sha256=hashlib.sha256(cipher).hexdigest(),
        encrypted_checkpoint_created=True,all_available_period_complete=False,plaintext_published=False)
    _write(out/'summary.json',json.dumps(report,sort_keys=True).encode())
    restored,_=restore_month(out,expected_month=catalog.month);need(restored.summary()==catalog.summary(),'HISTORY_IMMEDIATE_READBACK_MISMATCH');restored.db.close()
    return report


def _manifest_mac(document,*,key=None):
    import os
    if key is None:key=base64.b64decode(os.environ['RACE_AI_STATE_KEY'],validate=True)
    else:
        from race_ai.boat_pdca_state import state_key
        key=state_key('production',key)
    domain_key=hmac.digest(key,b'RACE_AI_ALL_PUBLISHED_HISTORY_MANIFEST_V1','sha256')
    return hmac.new(domain_key,json.dumps(document,sort_keys=True,separators=(',',':')).encode(),'sha256').hexdigest()


def _store_progress(out,state):
    body=json.dumps(dict(state=state,mac=_manifest_mac(state)),sort_keys=True).encode()
    numbers=[int(p.stem.split('-')[1]) for p in out.glob('progress-*.json')]
    _write(out/f'progress-{max(numbers,default=0)+1:06}.json',body)
    fd,name=tempfile.mkstemp(prefix='.collection-pointer-',suffix='.tmp',dir=out)
    with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
    os.replace(name,out/'collection.json')


def _verify_hold(report):
    report=dict(report);mac=report.pop('hold_mac',None)
    need(isinstance(mac,str) and hmac.compare_digest(mac,_manifest_mac(report)),'HISTORY_WAIT_AUTHENTICATION_FAILED')
    return report


def collect_all(out,*,initialize=False,max_months=None):
    """Resume a fixed as-of inventory of every published official month.

    Authenticated bootstrap is durable before its first download. A complete
    source listing is distinct from an independently proven no-race calendar.
    """
    if not _key_ready():return dict(status='HOLD_OWNER_STATE_KEY_MISSING',upstream_gets=0,all_available_period_complete=False)
    need(max_months is None or type(max_months) is int and max_months>=1,'HISTORY_MONTH_BATCH_LIMIT_INVALID')
    out=Path(out);progress=out/'collection.json'
    versions=sorted(out.glob('progress-*.json')) if out.exists() else []
    if versions or progress.exists():
        # A version is written before its atomic pointer; the latest signed
        # version recovers even the very first pointer-write interruption.
        record=json.loads(_read(versions[-1] if versions else progress,1000000));state=record['state']
        need(hmac.compare_digest(record['mac'],_manifest_mac(state)),'HISTORY_PROGRESS_AUTHENTICATION_FAILED')
        need(state['schema']=='RACE_AI_ALL_PUBLISHED_HISTORY_PROGRESS_V1','HISTORY_V2_REQUIRES_EXPLICIT_COLLECT_DELTA')
    else:
        waits=sorted(out.glob('initial-wait-*.json')) if out.exists() else []
        if waits:
            prior=_verify_hold(json.loads(_read(waits[-1],64000)))
            if wait_active(prior['source_wait'],_now()):return dict(prior,upstream_gets=0)
        need((initialize or waits) and (not out.exists() or not any(p.name not in {w.name for w in waits} for p in out.iterdir())),
             'HISTORY_PROGRESS_MISSING_DO_NOT_RESET')
        out.mkdir(parents=True,mode=0o700,exist_ok=True)
        try:menu,at=_http(MENU)
        except SourceWait as exc:
            report=dict(status='HOLD_SOURCE_WAIT',upstream_gets=1,source_wait=exc.plan,encrypted_checkpoint_created=False,
                        all_available_period_complete=False)
            report['hold_mac']=_manifest_mac(report)
            _write(out/f'initial-wait-{len(waits)+1:06}.json',json.dumps(report,sort_keys=True).encode());return report
        state=dict(schema='RACE_AI_ALL_PUBLISHED_HISTORY_PROGRESS_V1',months=published_months(menu),
                   menu_sha256=hashlib.sha256(menu).hexdigest(),captured_at=at,
                   not_after=stamp(at).astimezone(JST).date().isoformat(),heads={})
        _store_progress(out,state) # before any month attempt can be orphaned
    completed=0
    for month in state['months']:
        old=state['heads'].get(month)
        if old:
            folder=out/old['folder'];need(folder.is_dir(),'HISTORY_MONTH_MISSING_DO_NOT_RESET')
            if old.get('kind')!='HOLD':
                catalog,receipt=restore_month(folder,expected_month=month)
                need(receipt['ciphertext_sha256']==old['ciphertext_sha256'],'HISTORY_PROGRESS_HEAD_MISMATCH')
                if catalog.summary()['month_complete']:continue
                if not catalog.pending() and not catalog.reparse_candidates():continue
        else:folder=None
        if max_months is not None and completed>=max_months:break
        attempt=old.get('attempt',old.get('generation',0))+1 if old else 1
        relative=f'{month}/attempt-{attempt:06}'
        target=out/relative
        if target.exists() and any(target.iterdir()):
            report=json.loads(_read(target/'summary.json',64000))
            if report.get('encrypted_checkpoint_created'):
                _,report=restore_month(target,expected_month=month)
                expected_previous=old.get('ciphertext_sha256') if old and old.get('kind')!='HOLD' else None
                need(report['scope']['previous_cipher_sha256']==expected_previous,'HISTORY_ORPHAN_PARENT_MISMATCH')
            else:
                need(not (target/'history.checkpoint').exists(),'HISTORY_HOLD_HAS_UNEXPECTED_CIPHERTEXT')
                report=_verify_hold(report) # authenticated orphan HOLD, never decrypt as a SQLite checkpoint
        else:
            report=capture_month(target,month=month,resume=folder,not_after=state.get('not_after',stamp(state['captured_at']).astimezone(JST).date().isoformat()),
                                 reparse_only=bool(old and old.get('kind')!='HOLD' and not catalog.pending() and catalog.reparse_candidates()))
        if report['encrypted_checkpoint_created']:
            head=dict(kind='ENCRYPTED',folder=relative,ciphertext_sha256=report['ciphertext_sha256'],attempt=attempt,
                      generation=report['scope']['generation'],month_complete=report['catalog']['month_complete'])
        else:head=dict(kind='HOLD',folder=relative,attempt=attempt,generation=0,month_complete=False)
        state['heads'][month]=head;_store_progress(out,state)
        completed+=1
        if report.get('source_wait'):break
    all_listed=len(state['heads'])==len(state['months']) and all(h['month_complete'] for h in state['heads'].values())
    return dict(status='ALL_PERIOD_COLLECTION_CHECKPOINTED',published_months=len(state['months']),
                complete_months=sum(h['month_complete'] for h in state['heads'].values()),
                months_processed_this_invocation=completed,all_published_files_collected=all_listed,
                all_available_period_complete=False,source_gaps_require_separate_review=True,plaintext_published=False)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    s=sub.add_parser('inspect');s.add_argument('--source-dir',required=True);s.add_argument('--term-file',required=True);s.add_argument('--menu-file',required=True);s.add_argument('--end',required=True)
    s=sub.add_parser('capture-month');s.add_argument('--out-dir',required=True);s.add_argument('--month',required=True);s.add_argument('--resume');s.add_argument('--max-files',type=int,default=31);s.add_argument('--reparse-only',action='store_true')
    s=sub.add_parser('restore-month');s.add_argument('--folder',required=True);s.add_argument('--month',required=True)
    s=sub.add_parser('collect-all');s.add_argument('--out-dir',required=True);s.add_argument('--initialize',action='store_true');s.add_argument('--max-months',type=int)
    s=sub.add_parser('extend-all');s.add_argument('--source-dir',required=True);s.add_argument('--out-dir',required=True);s.add_argument('--not-after');s.add_argument('--max-files',type=int,default=31)
    s=sub.add_parser('collect-delta');s.add_argument('--out-dir',required=True);s.add_argument('--max-files',type=int,default=31)
    args=p.parse_args(argv)
    if args.action=='inspect':report=inspect_sources(args.source_dir,term_file=args.term_file,menu_file=args.menu_file,end=args.end)
    elif args.action=='capture-month':report=capture_month(args.out_dir,month=args.month,resume=args.resume,max_files=args.max_files,reparse_only=args.reparse_only)
    elif args.action=='restore-month':
        catalog,report=restore_month(args.folder,expected_month=args.month)
        report=dict(status='ENCRYPTED_MONTH_HISTORY_READBACK_VERIFIED',month=args.month,catalog=catalog.summary(),plaintext_published=False)
    elif args.action=='extend-all':
        from race_ai.boat_history_dated_inventory import extend_collection
        report=extend_collection(args.source_dir,args.out_dir,not_after=args.not_after,max_files=args.max_files)
    elif args.action=='collect-delta':
        from race_ai.boat_history_dated_inventory import collect_delta
        report=collect_delta(args.out_dir,max_files=args.max_files)
    else:report=collect_all(args.out_dir,initialize=args.initialize,max_months=args.max_months)
    print(json.dumps(report,ensure_ascii=False,sort_keys=True));return report


if __name__=='__main__':main()
