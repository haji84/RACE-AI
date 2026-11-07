"""Per-race athlete statistics; private delta retention and derived-only release."""
from contextlib import nullcontext
from datetime import date,datetime,timezone
from pathlib import Path
import argparse,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from race_ai.racer_daily import wire,sha,clock,need
from race_ai.racer_daily_handoff import load_daily,publish_daily_catalogue
from race_ai.racer_intraday import build_catalogue
from race_ai.racer_intraday_handoff import load_intraday,save_intraday
from race_ai.racer_intraday_transport import OfficialClient
from race_ai.official_archive_probe import official_url
from scripts.boat_history_collect import private_root,save
from scripts.racer_daily_refresh import refresh as retain_daily,verify_public

def refresh(repo,private_dir,*,initialize=False,daily_reconcile=False,now=None,fetch=None,base_transport=None,intraday_transport=None,pages_transport=None,roster=None,verify=False,sync_results=False,result_bridge=None):
    current=(lambda:clock(now)) if now is not None else (lambda:datetime.now(timezone.utc));started=current();root=private_root(private_dir)
    daily=None
    if daily_reconcile:
        with (OfficialClient() if fetch is None else nullcontext(fetch)) as source:
            daily=retain_daily(repo,root/'daily',now=now,publish=False,transport=base_transport,fetch=lambda day:source(official_url(date.fromisoformat(day),'K')))
    loaded_base=load_daily(repo,transport=base_transport,now=current());base=loaded_base['store'];base.clock=current
    try:
        result_sync=None;bridge=None;targets=()
        if sync_results:
            from race_ai.racer_result_bridge import SavedResultBridge,status as result_status
            try:bridge=result_bridge or SavedResultBridge(repo,now=current());targets=bridge.targets()
            except Exception:bridge=None;result_sync=result_status(now=current(),state='HOLD')
        loaded=load_intraday(repo,initialize=initialize,transport=intraday_transport,now=current());state=loaded['state'];before={k:v for k,v in state.control.items() if k!='last_checked_at'};before=wire(before)
        if bridge:bridge.prepare(state)
        if daily_reconcile:
            state.rollover(current());state.control['last_checked_at']=current().isoformat();outcome=dict(status='READY' if daily['status']=='DAILY_RETAINED' else 'SOURCE_WAIT',requests=0,new_observations=0)
        else:
            with (OfficialClient() if fetch is None else nullcontext(fetch)) as source:outcome=state.advance(base,now=current(),fetch=source,max_requests=12,**(dict(result_targets=targets) if bridge else {}))
        finished=current();state.control['last_checked_at']=finished.isoformat()
        roster=roster if roster is not None else json.loads((ROOT/'web/data/racer-profiles.json').read_text())['people']
        catalogue=build_catalogue(base,state,roster,now=finished,base_sha=loaded_base['previous']['cipher_sha256']);raw=(wire(catalogue)+'\n').encode();digest=sha(raw)
        after=wire({k:v for k,v in state.control.items() if k!='last_checked_at'})
        if loaded['previous'] is None or state.new_captures or before!=after:
            retained=save_intraday(loaded,catalogue_sha256=digest,now=finished)
        else:
            prior=loaded['previous'];need(prior['catalogue_sha256']==digest,'INTRADAY_REPLAY_CATALOGUE_MISMATCH')
            retained=dict(status='INTRADAY_STATE_UNCHANGED',source_commit=loaded['parent'],cipher_path=prior['cipher_path'],cipher_sha256=prior['head']['cipher_sha256'],generation=prior['head']['generation'],new_capture_count=0,plaintext_published=False)
        if bridge:
            try:result_sync=bridge.publish(state,now=finished)
            except Exception:result_sync=result_status(now=finished,state='RETRY',rows=bridge.rows)
            if result_sync['state']=='READY' and outcome['status']!='READY':result_sync['state']='SOURCE_WAIT'
        public=publish_daily_catalogue(repo,catalogue,transport=pages_transport,checked_at=finished.isoformat(),state=outcome['status'],**(dict(result_sync=result_sync) if sync_results else {}))
        if verify:verify_public(public)
        implementation=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,timeout=10).strip();meta=state.metadata(finished)
        report=dict(schema='RACE_AI_RACER_INTRADAY_RUN_V1',status='INTRADAY_REFRESHED' if outcome['status']=='READY' else outcome['status'],implementation_commit=implementation,checked_at=finished.isoformat(),catalogue_at=catalogue['generated_at'],
          source_requests=outcome['requests']+(daily['source_requests'] if daily else 0),new_observations=outcome['new_observations'],public_profiles=len(catalogue['people']),period=catalogue['period'],
          today={k:v for k,v in meta.items() if k not in ('source_receipts',)},retained=retained,public=public,daily=daily,private_sources_published=False,forecast_inputs_changed=False)
        if sync_results:report['result_sync']=result_sync
        save(root/'run-report.json',(wire(report)+'\n').encode());return report
    finally:base.close()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=ROOT);p.add_argument('--private-dir',type=Path,required=True);p.add_argument('--initialize',action='store_true');p.add_argument('--daily-reconcile',action='store_true');p.add_argument('--verify-public',action='store_true');p.add_argument('--sync-results',action='store_true');a=p.parse_args()
    try:
        report=refresh(a.repo,a.private_dir,initialize=a.initialize,daily_reconcile=a.daily_reconcile,verify=a.verify_public,sync_results=a.sync_results);print(wire(report));return 0 if report['status']=='INTRADAY_REFRESHED' and (not a.sync_results or report['result_sync']['state']=='READY') else 2
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and str(exc).isupper() and len(str(exc))<=100 else 'INTRADAY_REFRESH_FAILED';trace=[];frame=exc.__traceback__
        while frame:
            trace.append(Path(frame.tb_frame.f_code.co_filename).name+':'+str(frame.tb_lineno)+':'+frame.tb_frame.f_code.co_name);frame=frame.tb_next
        print(wire(dict(status='HOLD',reason=reason,exception_type=type(exc).__name__,code_trace=trace[-8:],private_sources_published=False)));return 1
if __name__=='__main__':raise SystemExit(main())
