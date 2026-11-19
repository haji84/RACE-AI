"""Audit missed BOAT GitHub schedules without issuing or authorizing a source GET.

This is *not* the P0/P1 producer and does not reset any source budget.
It may precede an authenticated zero-source-request retained-result replay.
"""
import argparse
from datetime import datetime,timedelta,timezone
import json
import re
from pathlib import Path

JST=timezone(timedelta(hours=9))
BOAT='BOAT per-race results and athlete statistics'
SCHEMA='RACE_AI_BOAT_RESULT_GAP_AUDIT_V1'

def _need(condition,why):
    if not condition:raise ValueError('BOAT_GAP_'+why)

def _time(raw):
    _need(type(raw) is str and len(raw)<=48,'TIME')
    try:result=datetime.fromisoformat(raw.replace('Z','+00:00'))
    except ValueError:raise ValueError('BOAT_GAP_TIME') from None
    _need(result.utcoffset() is not None,'TIMEZONE')
    return result.astimezone(timezone.utc)

def inspect_runs(payload,*,now,gap_minutes=15):
    _need(type(payload) is dict and type(payload.get('workflow_runs')) is list
          and len(payload['workflow_runs'])<=100,'RUNS_SCHEMA')
    _need(type(now) is datetime and now.utcoffset() is not None,'NOW')
    _need(type(gap_minutes) is int and 10<=gap_minutes<=60,'GAP_BOUND')
    current=now.astimezone(timezone.utc)
    js=current.astimezone(JST)
    in_window=7<=js.hour<=23
    known={}
    for r in payload['workflow_runs']:
        _need(type(r) is dict,'RUN_ENTRY')
        if r.get('name')!=BOAT or r.get('event')!='schedule':
            continue
        _need(type(r.get('id')) is int and r['id']>0,'RUN_ID')
        created=_time(r['created_at'])
        _need(created<=current+timedelta(minutes=5),'FUTURE_RUN')
        prior=known.get(r['id'])
        _need(prior is None or prior==created,'RUN_DUPLICATE_CONFLICT')
        known[r['id']]=created
    latest=max(known.values(),default=None)
    gap_seconds=None if latest is None else max(0,int((current-latest).total_seconds()))
    stale=latest is None or gap_seconds>gap_minutes*60
    state=('SCHEDULE_WINDOW_INACTIVE' if not in_window else
           'SCHEDULE_GAP_CONFIRMED' if stale else
           'SCHEDULE_EVENT_SEEN')
    return dict(schema=SCHEMA,status=state,checked_at=current.isoformat(),
                latest_scheduled_at=latest.isoformat() if latest else None,
                latest_scheduled_age_seconds=gap_seconds,
                checked_run_count=len(known),window_active=in_window,
                requested_source_gets=0,source_budget_extended=False,
                existing_original_forecasts_mutated=False,
                replay_only_allowed=True,
                source_get_recovery_proven=False)

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--runs',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--now',help='UTC offset-aware ISO time for offline fixture only')
    p.add_argument('--gap-minutes',type=int,default=15)
    opts=p.parse_args(argv)
    _need(opts.runs.is_file() and not opts.runs.is_symlink()
          and opts.runs.stat().st_size<=512000,'INPUT_BOUND')
    data=json.loads(opts.runs.read_bytes())
    out=inspect_runs(data,now=_time(opts.now) if opts.now else
                     datetime.now(timezone.utc),gap_minutes=opts.gap_minutes)
    _need(not opts.output.exists() and opts.output.parent.is_dir(),'OUTPUT_EXISTS')
    opts.output.write_text(json.dumps(out,sort_keys=True,separators=(',',':'))+'\n')
    print(json.dumps(out,sort_keys=True,separators=(',',':')))
    return 0

if __name__=='__main__':raise SystemExit(main())
