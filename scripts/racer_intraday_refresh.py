"""Per-race athlete statistics; private delta retention and derived-only release."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import date,datetime,timezone
from pathlib import Path
import argparse,json,re,subprocess,sys,traceback
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

def refresh(repo,private_dir,*,initialize=False,daily_reconcile=False,now=None,fetch=None,base_transport=None,intraday_transport=None,pages_transport=None,roster=None,verify=False,sync_results=False,result_bridge=None,sync_beforeinfo=False):
    need(not sync_beforeinfo or sync_results,'BEFOREINFO_RESULT_FEED_REQUIRED')
    current=(lambda:clock(now)) if now is not None else (lambda:datetime.now(timezone.utc));started=current();root=private_root(private_dir)
    daily=None
    if daily_reconcile:
        with (OfficialClient() if fetch is None else nullcontext(fetch)) as source:
            daily=retain_daily(repo,root/'daily',now=now,publish=False,transport=base_transport,fetch=lambda day:source(official_url(date.fromisoformat(day),'K')))
    loaded_base=load_daily(repo,transport=base_transport,now=current());base=loaded_base['store'];base.clock=current
    try:
        result_sync=None;bridge=None;targets=();publication_error=None;publication_trace=[]
        if sync_results:
            from race_ai.racer_result_bridge import SavedResultBridge,status as result_status
            try:bridge=result_bridge or SavedResultBridge(repo,now=current())
            except Exception:bridge=None;result_sync=result_status(now=current(),state='HOLD')
        loaded=load_intraday(repo,initialize=initialize,transport=intraday_transport,now=current());state=loaded['state'];before={k:v for k,v in state.control.items() if k!='last_checked_at'};before=wire(before)
        if bridge:bridge.prepare(state);targets=bridge.targets()
        beforeinfo=dict(requests=0,parsed=0,rejected=0)
        if daily_reconcile:
            state.rollover(current());state.control['last_checked_at']=current().isoformat();outcome=dict(status='READY' if daily['status']=='DAILY_RETAINED' else 'SOURCE_WAIT',requests=0,new_observations=0)
        else:
            with (OfficialClient() if fetch is None else nullcontext(fetch)) as source:
                if sync_beforeinfo and bridge:
                    from race_ai.racer_beforeinfo import collect_beforeinfo
                    beforeinfo=collect_beforeinfo(state,getattr(bridge,'recent_rows',bridge.rows),now=current(),fetch=source,max_requests=4)
                outcome=state.advance(base,now=current(),fetch=source,max_requests=12-beforeinfo['requests'],**(dict(result_targets=targets) if bridge else {}))
                outcome['requests']+=beforeinfo['requests']
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
            except Exception as error:
                code=getattr(error,'reason_code',None) or str(error)
                publication_error=code if re.fullmatch(r'(?:RESULT|FEED|HISTORY|SAVED_MODEL_VIEW|BEFOREINFO)_[A-Z0-9_]{1,190}',code) else 'RESULT_FEED_OPERATION_FAILED'
                publication_trace=[Path(frame.filename).name+':'+str(frame.lineno)+':'+frame.name for frame in traceback.extract_tb(error.__traceback__)[-5:]]
                result_sync=result_status(now=finished,state='RETRY',rows=bridge.rows)
            if result_sync['state']=='READY' and outcome['status']!='READY':result_sync['state']='SOURCE_WAIT'
        public=publish_daily_catalogue(repo,catalogue,transport=pages_transport,checked_at=finished.isoformat(),state=outcome['status'],**(dict(result_sync=result_sync) if sync_results else {}))
        if verify:verify_public(public)
        implementation=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,timeout=10).strip();meta=state.metadata(finished)
        report=dict(schema='RACE_AI_RACER_INTRADAY_RUN_V1',status='INTRADAY_REFRESHED' if outcome['status']=='READY' else outcome['status'],implementation_commit=implementation,checked_at=finished.isoformat(),catalogue_at=catalogue['generated_at'],
          source_requests=outcome['requests']+(daily['source_requests'] if daily else 0),new_observations=outcome['new_observations'],public_profiles=len(catalogue['people']),period=catalogue['period'],
          today={k:v for k,v in meta.items() if k not in ('source_receipts',)},retained=retained,public=public,daily=daily,private_sources_published=False,forecast_inputs_changed=False)
        if sync_results:
            report['result_sync']=result_sync
            if bridge and getattr(bridge,'ledger_summary',None) is not None:
                report['result_due_ledger']=dict(bridge.ledger_summary)
            if publication_error:report.update(result_publication_error=publication_error,result_publication_trace=publication_trace)
            from collections import Counter
            reasons=[e.get('reason','RESULT_OBSERVATION_INVALID') for row in (bridge.rows if bridge else []) if (row.get('result') or {}).get('status')=='unsupported' for e in row.get('result_observation_rejections',[])]
            report['result_rejection_reason_counts']=dict(Counter(code for code in reasons if isinstance(code,str) and re.fullmatch(r'(?:RESULT|SAVED_MODEL_VIEW)_[A-Z0-9_]{1,190}',code)))
        if sync_beforeinfo:
            report['beforeinfo']=dict(beforeinfo,**dict(published_races=sum(bool((r.get('live_boat_observation') or {}).get('context')) for r in (bridge.rows if bridge else [])),forecast_inputs_used=False))
        save(root/'run-report.json',(wire(report)+'\n').encode());return report
    finally:base.close()

def stage_existing_pdca_without_source(repo,*,now=None,intraday_transport=None,bridge=None,key=None):
    """Authenticate retained results, archive model PDCA, and seal state without GET.

    Run with existing Actions owner credentials. The independent readback must
    happen in a NEW invocation; this producer does not declare acceptance.
    """
    from race_ai import model_pdca_history as H
    from race_ai.racer_result_bridge import SavedResultBridge
    current=clock(now or datetime.now(timezone.utc))
    loaded=load_intraday(repo,transport=intraday_transport,now=current,key=key)
    prior=loaded['previous'];need(prior is not None,'MODEL_PDCA_EXISTING_STATE_REQUIRED')
    state=loaded['state'];before=wire(state.control)
    bridge=bridge or SavedResultBridge(repo,now=current)
    bridge.prepare(state)
    audit=H.latest(state.control)
    # Existing signed catalogue binding is unchanged: this mode doesn't
    # alter the daily catalogue, fetch a source or publish any page.
    if wire(state.control)!=before:
        saved=save_intraday(loaded,catalogue_sha256=prior['catalogue_sha256'],now=current,key=key)
    else:
        saved=dict(status='INTRADAY_STATE_UNCHANGED',generation=prior['head']['generation'],
                   source_commit=loaded['parent'],new_capture_count=0,plaintext_published=False)
    return dict(schema='RACE_AI_SOURCE_FREE_MODEL_PDCA_STAGE_V1',status='STAGED_NEEDS_INDEPENDENT_READBACK',
        saved_state=saved['status'],generation=saved['generation'],archived_days=audit['days'],
        archived_revisions=audit['revisions'],model_group_count=len(audit['model_groups']),
        formally_scored_forecasts=sum(g['eligible'] for g in audit['model_groups']),
        outstanding_unscored=audit['unscored'],source_requests=0,source_provider_requests=0,
        forecast_rewrites=0,actual_purchases=False,independent_readback_verified=False)

def replay_retained_results(repo,*,now=None,intraday_transport=None,bridge=None):
    """Reproject authenticated retained bytes; do not collect or save source state."""
    from race_ai import saved_view_feed as F
    from race_ai.racer_result_bridge import SavedResultBridge,status
    current=(lambda:clock(now)) if now is not None else (lambda:datetime.now(timezone.utc))
    started=current();loaded=load_intraday(repo,transport=intraday_transport,now=started)
    need(loaded['previous'] is not None,'RESULT_REPLAY_EXISTING_STATE_REQUIRED')
    state=loaded['state'];control=wire(state.control);captures=wire(state.new_captures)
    bridge=bridge or SavedResultBridge(repo,now=started);before=deepcopy(bridge.rows)
    result=bridge.publish(state,now=current())
    need(wire(state.control)==control and wire(state.new_captures)==captures,'RESULT_REPLAY_SOURCE_STATE_CHANGED')
    checked=current();reader=SavedResultBridge(repo,now=checked,transport=bridge.git,bootstrap=bridge.bootstrap)
    rows={r['race_id']:r for r in reader.rows}
    view=lambda records:dict(schema='RACE_AI_PRIVATE_CYCLE_VIEW_V1',records=records)
    prior=F.forecast_inventory(view(before));after=F.forecast_inventory(view(reader.rows))
    need(all(after.get(k)==v for k,v in prior.items()),'RESULT_REPLAY_ORIGINAL_CHANGED')
    for row in before:
        restored=rows.get(row['race_id']);need(restored is not None,'RESULT_REPLAY_READBACK_MISSING')
        for field in ('result_observations','result_revisions'):
            kept={wire(o) for o in restored.get(field,[])}
            need(all(wire(o) in kept for o in row.get(field,[])),'RESULT_REPLAY_OBSERVATION_CHANGED')
    need(all(r['race_id'] in rows and wire(rows[r['race_id']].get('result'))==wire(r.get('result'))
             for r in bridge.rows),'RESULT_REPLAY_READBACK_MISMATCH')
    return dict(schema='RACE_AI_RETAINED_RESULT_REPLAY_V1',status='RETAINED_RESULTS_REPLAYED',
        checked_at=checked.isoformat(),source_requests=0,changed_races=result['changed_races'],
        result_sync=status(now=checked,rows=reader.rows,changed=result['changed_races']),
        readback_verified=True,original_observations_preserved=True,originals_changed=False,
        source_state_saved=False,public_catalogue_published=False,forecasting_performed=False,plaintext_published=False)



def _stage_git_header_scope():
    """Remove only checkout's host-wide auth for the existing source-free PDCA step.

    The existing owner Actions token is re-added by git_auth() for this
    exact repository. No disk Git config, source credential or URL is changed.
    """
    count=int(os.environ.get('GIT_CONFIG_COUNT','0'))
    need(0<=count<=30,'MODEL_PDCA_GIT_CONFIG_BOUND')
    key='http.https://github.com/.extraheader'
    existing=[os.environ.get('GIT_CONFIG_VALUE_'+str(i)) for i in range(count)
              if os.environ.get('GIT_CONFIG_KEY_'+str(i))==key]
    need(not any(existing),'MODEL_PDCA_CHECKOUT_HEADER_CONFLICT')
    if existing:return
    os.environ.update({'GIT_CONFIG_KEY_'+str(count):key,
                       'GIT_CONFIG_VALUE_'+str(count):'',
                       'GIT_CONFIG_COUNT':str(count+1)})

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=ROOT);p.add_argument('--private-dir',type=Path,required=True);p.add_argument('--initialize',action='store_true');p.add_argument('--daily-reconcile',action='store_true');p.add_argument('--verify-public',action='store_true');p.add_argument('--sync-results',action='store_true');p.add_argument('--sync-beforeinfo',action='store_true');p.add_argument('--replay-retained-results',action='store_true');p.add_argument('--stage-existing-pdca',action='store_true');a=p.parse_args(argv)
    try:
        if a.stage_existing_pdca:
            need(not any((a.initialize,a.daily_reconcile,a.verify_public,a.sync_results,a.sync_beforeinfo,a.replay_retained_results)),'MODEL_PDCA_STAGE_MODE_CONFLICT')
            from scripts.boat_private_original_vault import _environment
            from scripts.boat_saved_view_feed import git_auth
            _stage_git_header_scope()
            repo=_environment(a.repo);git_auth()
            report=stage_existing_pdca_without_source(repo)
            print(wire(report));return 0
        if a.replay_retained_results:
            need(not any((a.initialize,a.daily_reconcile,a.verify_public,a.sync_results,a.sync_beforeinfo)),'RESULT_REPLAY_MODE_CONFLICT')
            from scripts.boat_private_original_vault import _environment
            repo=_environment(a.repo)
            report=replay_retained_results(repo);print(wire(report));return 0
        report=refresh(a.repo,a.private_dir,initialize=a.initialize,daily_reconcile=a.daily_reconcile,verify=a.verify_public,sync_results=a.sync_results,sync_beforeinfo=a.sync_beforeinfo);print(wire(report));return 0 if report['status']=='INTRADAY_REFRESHED' and (not a.sync_results or report['result_sync']['state']=='READY') else 2
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and str(exc).isupper() and len(str(exc))<=100 else 'INTRADAY_REFRESH_FAILED';trace=[];frame=exc.__traceback__
        while frame:
            trace.append(Path(frame.tb_frame.f_code.co_filename).name+':'+str(frame.tb_lineno)+':'+frame.tb_frame.f_code.co_name);frame=frame.tb_next
        print(wire(dict(status='HOLD',reason=reason,exception_type=type(exc).__name__,code_trace=trace[-8:],private_sources_published=False)));return 1
if __name__=='__main__':raise SystemExit(main())
