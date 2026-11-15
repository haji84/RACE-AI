"""Refresh BOAT descriptive daily cards using existing GitHub-only storage."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import argparse,json,subprocess,sys,time
from urllib.request import Request,build_opener
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from race_ai.racer_daily import wire,sha,need,JST,PUBLIC_PATH,PUBLIC_URL,STATUS_PATH,STATUS_URL
from race_ai.racer_daily_handoff import load_daily,save_daily,collect_recent,seed_recent_months,publish_daily_catalogue
from scripts.boat_history_collect import private_root,save
from race_ai.permissioned_source_delivery import NoRedirect

def verify_public(receipt):
    need(receipt['path']==PUBLIC_PATH and receipt['public_url']==PUBLIC_URL,'DAILY_PUBLIC_URL_REJECTED')
    targets=[(PUBLIC_URL,receipt['public_sha256'])]
    if 'status_path' in receipt:
        need(receipt['status_path']==STATUS_PATH and receipt['status_url']==STATUS_URL,'DAILY_PUBLIC_URL_REJECTED');targets.append((STATUS_URL,receipt['status_sha256']))
    for target,expected in targets:
        url=target+'?stats='+expected[:16]
        for attempt in range(18):
            try:
                with build_opener(NoRedirect()).open(Request(url,headers={'Cache-Control':'no-cache'}),timeout=20) as response:raw=response.read(4*1024*1024+1)
                if sha(raw)==expected:break
            except Exception:pass
            time.sleep(10)
        else:raise ValueError('DAILY_PUBLIC_HTTP_NOT_LIVE')
    return True

def refresh(repo,private_dir,*,initialize=False,now=None,verify=False,publish=True,transport=None,fetch=None):
    current=(lambda:now) if now is not None else (lambda:datetime.now(timezone.utc))
    started=current();root=private_root(private_dir)
    options={'transport':transport} if transport is not None else {}
    loaded=load_daily(repo,initialize=initialize,now=started,**options);store=loaded['store'];store.clock=current
    try:
        seeded=0
        if loaded['previous'] is None:
            pointer=json.loads((ROOT/'audit/state/boat-venue-history-input.json').read_text())
            seeded=seed_recent_months(repo,store,now=started,pointer=pointer)
        options={'fetch':fetch} if fetch is not None else {}
        outcome=collect_recent(store,now=started,max_requests=7,**options)
        finished=current()
        # Old authenticated generations keep originals. The active snapshot is bounded.
        start=(finished.astimezone(JST).date()-timedelta(days=97)).isoformat();store.compact(start)
        catalogue=store.catalogue(json.loads((ROOT/'web/data/racer-profiles.json').read_text())['people'],as_of=finished.isoformat())
        need(catalogue['status']=='READY','DAILY_NO_SOURCE_AVAILABLE')
        if outcome['status']=='SOURCE_WAIT' and outcome['requests']==0 and loaded['previous']:
            previous=json.loads(loaded['previous_raw'])
            retained=dict(status='DAILY_STATE_UNCHANGED',source_commit=loaded['parent'],cipher_path=previous['cipher_path'],cipher_sha256=loaded['previous']['cipher_sha256'],generation=loaded['previous']['generation'],plaintext_published=False)
        else:retained=save_daily(loaded,catalogue)
        public=None
        if publish and (outcome['status'] not in ('SOURCE_WAIT','SOURCE_HOLD') or seeded):
            public=publish_daily_catalogue(repo,catalogue)
            if verify:verify_public(public)
        healthy=outcome['status'] not in ('SOURCE_WAIT','SOURCE_HOLD')
        implementation=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,timeout=10).strip()
        report=dict(schema='RACE_AI_RACER_DAILY_RUN_V1',implementation_commit=implementation,status='DAILY_REFRESHED' if public and healthy else 'DAILY_RETAINED' if not publish and healthy else outcome['status'],collection_status=outcome['status'],as_of=finished.isoformat(),
            source_requests=outcome['requests'],new_source_files=outcome['new_files'],seeded_days=seeded,
            public_profiles=len(catalogue['people']),parsed_days=catalogue['coverage']['parsed_days'],missing_days=catalogue['coverage']['missing_days_count'],
            partial_days=len(catalogue['coverage']['partial_days']),period=catalogue['period'],last_source_at=catalogue['last_source_at'],
            retained=retained,public=public,private_sources_published=False,forecast_inputs_changed=False)
        save(root/'run-report.json',(wire(report)+'\n').encode());return report
    finally:store.close()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=ROOT);p.add_argument('--private-dir',type=Path,required=True)
    p.add_argument('--initialize',action='store_true');p.add_argument('--verify-public',action='store_true');a=p.parse_args()
    try:report=refresh(a.repo,a.private_dir,initialize=a.initialize,verify=a.verify_public);print(wire(report));return 0 if report['status']=='DAILY_REFRESHED' else 2
    except Exception as exc:
        code=str(exc) if isinstance(exc,ValueError) and str(exc).isupper() and len(str(exc))<=100 else 'DAILY_REFRESH_FAILED'
        trace=[];frame=exc.__traceback__
        while frame:
            trace.append(Path(frame.tb_frame.f_code.co_filename).name+':'+str(frame.tb_lineno)+':'+frame.tb_frame.f_code.co_name);frame=frame.tb_next
        # Code locations diagnose runner/network failures without exception text,
        # subprocess arguments, captured output, source values or local variables.
        print(wire(dict(status='HOLD',reason=code,exception_type=type(exc).__name__,code_trace=trace[-8:],private_sources_published=False)));return 1
if __name__=='__main__':raise SystemExit(main())
