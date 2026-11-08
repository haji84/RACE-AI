"""Read-only independent AES/Git PDCA acceptance check. No source GET or bets."""
from copy import deepcopy
from datetime import datetime,timezone
import argparse,json,os,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def _need(ok,code):
    if not ok:raise ValueError('ALL_HISTORY_PDCA_'+code)

def verify_snapshot(state,bridge,*,now):
    from race_ai import result_due_ledger as D,retained_model_pdca_audit as P
    from race_ai import saved_view_feed as F
    from race_ai.racer_daily import wire
    _need(isinstance(now,datetime) and now.utcoffset() is not None,'CLOCK_INVALID')
    original=wire(state.control)
    snapshot=state.control.get('model_pdca_recent_audit')
    _need(type(snapshot) is dict and snapshot.get('schema')=='RACE_AI_PRIVATE_MODEL_PDCA_SNAPSHOT_V1'
          and snapshot.get('verification')=='PRE_SOURCE_REPLAY' and type(snapshot.get('days')) is list,
          'SNAPSHOT_ABSENT_OR_UNTRUSTED')
    _need(0<len(snapshot['days'])<=4,'SNAPSHOT_DAY_BOUND')
    _need('result_due_ledger' in state.control,'PERSISTENT_DUE_LEDGER_MISSING')
    due=D.ledger(deepcopy(state.control),now=now.isoformat())
    authenticated=models=scored=historical=holds=pending=0
    seen=set()
    for item in snapshot['days']:
        _need(type(item) is dict and item.get('status')=='SCORED','MODEL_PDCA_PARTIAL_HOLD')
        day=item.get('day')
        _need(type(day) is str and (day=='CURRENT_VIEW' or
            re.fullmatch(r'\d{4}-\d{2}-\d{2}',day)),'MODEL_PDCA_DAY_INVALID')
        _need(day not in seen,'MODEL_PDCA_DUPLICATE_DAY');seen.add(day)
        _,_,_,view=F.current_view(bridge.git,bridge.bootstrap,
                                  **(dict(day=day) if day!='CURRENT_VIEW' else {}))
        _need(F.inventory_sha(view)==item.get('forecast_inventory_sha256'),'ORIGINAL_FORECAST_SHA_CHANGED')
        recomputed=P.score_view(view,authenticated=True)
        _need(wire(recomputed)==wire(item.get('summary')),'MODEL_PDCA_SNAPSHOT_MISMATCH')
        authenticated+=1;models+=recomputed['model_group_count'];scored+=recomputed['total_scored']
        holds+=sum(g['held'] for g in recomputed['model_groups'])
        pending+=sum(g['pending'] for g in recomputed['model_groups'])
        today=now.astimezone(D.JST).date().isoformat()
        if day!='CURRENT_VIEW' and day<today and recomputed['total_scored']:
            historical+=1
        elif day=='CURRENT_VIEW':
            previous=[r for r in view['records'] if r.get('sport')=='boat'
                      and r.get('event_date_jst','')<today]
            if previous and P.score_view(dict(view,records=previous),authenticated=True)['total_scored']:
                historical+=1
    _need(scored>0 and historical>0,'NO_REAL_HISTORICAL_MODEL_SCORE')
    _need(wire(state.control)==original,'SOURCE_CONTROL_MUTATED')
    return dict(schema='RACE_AI_INDEPENDENT_PDCA_READBACK_V1',
        status='AES_AUTHENTICATED_HISTORICAL_PDCA_READBACK_VERIFIED',
        saved_days_authenticated=authenticated,model_group_snapshots=models,
        historical_days_with_formal_scores=historical,formally_scored_forecasts=scored,
        pending_forecasts=pending,held_forecasts=holds,
        ledger_outstanding=D.pending_count(due),source_provider_requests=0,
        forecast_rewrites=0,actual_purchases=False,
        secret_or_private_original_logged=False,all_history_completion_proven=False)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repository-root',default=str(ROOT))
    a=p.parse_args(argv)
    try:
        _need(os.environ.get('GITHUB_ACTIONS')=='true' and
              os.environ.get('GITHUB_REPOSITORY')=='haji84/RACE-AI','EXISTING_ACTIONS_ONLY')
        _need(bool(os.environ.get('RACE_AI_STATE_KEY')),'EXISTING_SECRET_REQUIRED')
        from scripts.boat_private_original_vault import _environment
        from scripts.boat_saved_view_feed import git_auth
        from race_ai.racer_intraday_handoff import load_intraday
        from race_ai.racer_result_bridge import SavedResultBridge
        root=_environment(Path(a.repository_root));git_auth()
        instant=datetime.now(timezone.utc)
        state=load_intraday(root,now=instant)['state']
        bridge=SavedResultBridge(root,now=instant)
        result=verify_snapshot(state,bridge,now=instant)
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as exc:
        reason=(str(exc) if type(exc) is ValueError and
               re.fullmatch(r'ALL_HISTORY_PDCA_[A-Z0-9_]+',str(exc))
               else 'ALL_HISTORY_PDCA_READBACK_UNAVAILABLE')
        print(json.dumps(dict(schema='RACE_AI_INDEPENDENT_PDCA_READBACK_V1',
          status='HOLD',reason=reason,source_provider_requests=0,
          actual_purchases=False,all_history_completion_proven=False),sort_keys=True))
        return 2

if __name__=='__main__':raise SystemExit(main())
