"""Fail-closed BOAT result admission with no fixed 30-minute pause.

Pure policy is testable without network access; the live wrapper reads authenticated
GitHub Actions history and already sealed private state only. A conservative
96 GET / rolling 60-minute recovery budget coexists with the original
12 GET / primary run (up to 144/hour); the owner's 240 cap is NOT reset.
"""
import argparse,json,os,re,subprocess
from datetime import datetime,timedelta,timezone
from pathlib import Path

JST=timezone(timedelta(hours=9))
SCHEMA='RACE_AI_BOAT_FRESH_GAP_GATE_V1'
BOAT='BOAT per-race results and athlete statistics'
FRESH='Fresh bounded official result intake'
RECOVERY_BUDGET_60M=96
PRIOR_ATTEMPT_RESERVATION=36

def _need(ok,why):
    if not ok:raise ValueError('BOAT_FRESH_GAP_'+why)
def _time(value):
    _need(type(value) is str and len(value)<=48,'CLOCK')
    try:d=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise ValueError('BOAT_FRESH_GAP_CLOCK') from None
    _need(d.utcoffset() is not None,'CLOCK_AWARE')
    return d.astimezone(timezone.utc)
def _runs(payload,now,window):
    _need(type(payload) is dict and type(payload.get('workflow_runs')) is list,'RUNS_SCHEMA')
    rows=payload['workflow_runs'];_need(len(rows)<=100,'RUNS_BOUND')
    for item in rows:
        _need(type(item) is dict and type(item.get('id')) is int and item['id']>0
              and type(item.get('created_at')) is str,'RUN_METADATA')
        _need(_time(item['created_at'])<=now+timedelta(minutes=5),'RUN_FUTURE')
    if len(rows)==100:
        oldest=min(_time(x['created_at']) for x in rows)
        _need(oldest<=now-window,'RUN_HISTORY_TRUNCATED')
    return rows
def inspect(boat_runs,recovery_runs,prior_attempts,source,*,now,current_run_id,run_attempt=1):
    _need(type(now) is datetime and now.utcoffset() is not None,'NOW')
    utc=now.astimezone(timezone.utc);jst=utc.astimezone(JST)
    _need(type(current_run_id) is int and current_run_id>0,'CURRENT_RUN')
    _need(type(run_attempt) is int and run_attempt>0,'RUN_ATTEMPT')
    boats=_runs(boat_runs,utc,timedelta(minutes=60))
    recoveries=_runs(recovery_runs,utc,timedelta(minutes=60))
    _need(type(prior_attempts) is list and len(prior_attempts)<=100,'ATTEMPTS_SCHEMA')
    _need(type(source) is dict and type(source.get('due_count')) is int
          and source['due_count']>=0,'SOURCE_STATUS')
    current=[r for r in recoveries if r['id']==current_run_id and
             r.get('head_branch')=='main' and
             r.get('event') in ('workflow_run','push','schedule','workflow_dispatch')]
    _need(len(current)==1,'CURRENT_ORIGIN')
    _need(type(source.get('last_checked_at')) is str,'SOURCE_CLOCK')
    checked=_time(source['last_checked_at'])
    _need(checked<=utc+timedelta(minutes=5),'SOURCE_FUTURE')
    hold_until=source.get('boatrace_hold_until')
    if hold_until is not None:_time(hold_until)
    trusted=[r for r in boats if r.get('name')==BOAT and
             r.get('head_branch')=='main']
    scheduled=[r for r in trusted if r.get('event')=='schedule']
    latest=max((_time(r['created_at']) for r in scheduled),default=None)
    if not 7<=jst.hour<=23:return dict(status='HOLD_OUTSIDE_JST_WINDOW',authorized_source_gets=0)
    if run_attempt!=1:return dict(status='HOLD_ATTEMPT_RETRY',authorized_source_gets=0)
    if latest is None:return dict(status='HOLD_NO_TRUSTED_SCHEDULE',authorized_source_gets=0)
    if utc-latest<timedelta(minutes=15):return dict(status='HOLD_SCHEDULE_RECENT',authorized_source_gets=0)
    if source['due_count']==0:return dict(status='HOLD_NO_PENDING_DUE_RESULTS',authorized_source_gets=0)
    # Never impose a fixed age delay on authenticated saved results.
    # Per-race settlement_next eligibility is verified by the AES preflight;
    # source_denial hold_until remains authoritative for 403/429, unchanged.
    if hold_until and _time(hold_until)>utc:return dict(status='HOLD_PROVIDER_DENIAL',authorized_source_gets=0)
    # A running or recent legitimate original collector always wins.
    for r in trusted:
        if r.get('event') not in ('schedule','workflow_dispatch') and not (
                r.get('event')=='push' and
                str(r.get('display_title','')).startswith('boat-result-refresh:')):
            continue
        at=_time(r['created_at'])
        if r.get('status') in ('queued','pending','waiting','requested','in_progress'):
            return dict(status='HOLD_ORIGINAL_COLLECTOR_ACTIVE',authorized_source_gets=0)
        # Completed primary runs have no artificial 20-minute cooldown.
        # Their worst-case 12 GET every 5 minutes is already reserved from
        # the rolling 240 owner budget by the recovery 96 GET/hour ceiling.
    # Count every prior *started* source job pessimistically at its maximum
    # 36 GET, even when it failed before GET. Do not reset this quota on
    # workflow failure, rerun, branch merge, or successive dispatch.
    # Use the JOB start time (not just run creation) to avoid a late-start
    # job aging out of the rolling window too early.
    recent_attempts=set()
    for p in prior_attempts:
        _need(type(p) is dict and type(p.get('run_id')) is int and
              type(p.get('created_at')) is str and
              p.get('job_name')==FRESH,'ATTEMPT_METADATA')
        at=max(_time(p['created_at']),
               _time(p['started_at']) if p.get('started_at') else _time(p['created_at']))
        _need(at<=utc+timedelta(minutes=5),'ATTEMPT_FUTURE')
        if p['run_id']==current_run_id:continue
        if p.get('job_status') in ('queued','in_progress','waiting','pending','requested'):
            return dict(status='HOLD_PRIOR_SOURCE_JOB_ACTIVE',authorized_source_gets=0)
        if utc-at<timedelta(minutes=60) and p.get('provider_step_attempted',True):
            recent_attempts.add(p['run_id'])
    spent=len(recent_attempts)*PRIOR_ATTEMPT_RESERVATION
    _need(spent<=RECOVERY_BUDGET_60M,'RECOVERY_BUDGET_EXCEEDED')
    available=RECOVERY_BUDGET_60M-spent
    if available<12:
        return dict(status='HOLD_RECOVERY_ROLLING_BUDGET',authorized_source_gets=0,
                    remaining_60m_gets=available)
    # No 30-minute pause: after the current single writer completes and a
    # DIFFERENT saved race is due, another run can use the remaining budget.
    # Normal primary collector: at most 12 GET per 5m = 144/hour.
    # Recovery: at most 96/hour. Combined conservative bound: 240/hour.
    approved=min(available,36,max(12,source['due_count']))
    return dict(status='FRESH_RESULT_GET_ADMITTED',authorized_source_gets=approved,
                source_owner_240_unchanged=True,original_race_forecasts_unchanged=True,
                pending_due_count=source['due_count'],
                remaining_60m_gets=available)

def _github(endpoint):
    value=subprocess.run(['gh','api',endpoint],capture_output=True,text=True,timeout=20,check=True)
    _need(len(value.stdout)<=12*1024*1024,'GH_RESPONSE_BOUND')
    return json.loads(value.stdout)

def _source_file(path):
    p=Path(path);_need(p.is_file() and not p.is_symlink() and
                   p.stat().st_size<=8192,'SOURCE_FILE')
    return json.loads(p.read_text())

def live(repo,run_id,attempt,source):
    _need(repo=='haji84/RACE-AI','REPOSITORY')
    boats=_github(f'repos/{repo}/actions/workflows/boat-racer-daily.yml/runs?per_page=100')
    recoveries=_github(f'repos/{repo}/actions/workflows/boat-result-gap-recovery.yml/runs?per_page=100')
    now=datetime.now(timezone.utc)
    _runs(recoveries,now,timedelta(minutes=60))
    recent=[r for r in recoveries['workflow_runs'] if
            r['id']!=run_id and r.get('head_branch')=='main' and
            now-_time(r['created_at'])<timedelta(minutes=65)]
    prior=[]
    for row in recent:
        jobs=_github(f'repos/{repo}/actions/runs/{row["id"]}/jobs?per_page=100')
        _need(type(jobs.get('jobs')) is list and len(jobs['jobs'])<100,'JOB_HISTORY_TRUNCATED')
        for job in jobs['jobs']:
            if job.get('name')==FRESH and job.get('conclusion')!='skipped':
                steps=job.get('steps')
                _need(type(steps) is list and len(steps)<100,'SOURCE_STEPS_UNVERIFIED')
                sources=[s for s in steps if s.get('name','').startswith(
                    'Consume at most 36 owner-admitted official-result GETs')]
                _need(len(sources)==1,'SOURCE_STEP_UNVERIFIED')
                step=sources[0]
                performed=step.get('status')=='in_progress' or (
                    step.get('status')=='completed' and
                    step.get('conclusion') not in ('skipped',None))
                prior.append(dict(run_id=row['id'],created_at=row['created_at'],
                                  started_at=job.get('started_at'),job_status=job.get('status'),
                                  provider_step_attempted=performed,job_name=FRESH))
    return inspect(boats,recoveries,prior,source,now=now,current_run_id=run_id,run_attempt=attempt)

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--source',required=True)
    p.add_argument('--output',required=True);a=p.parse_args(argv)
    try:
        _need(re.fullmatch('[0-9]+',os.environ.get('GITHUB_RUN_ID','')) is not None,'RUN_ID')
        _need(re.fullmatch('[0-9]+',os.environ.get('GITHUB_RUN_ATTEMPT','')) is not None,'ATTEMPT')
        result=live(os.environ.get('GITHUB_REPOSITORY',''),int(os.environ['GITHUB_RUN_ID']),
                    int(os.environ['GITHUB_RUN_ATTEMPT']),_source_file(a.source))
    except Exception:
        result=dict(status='HOLD_UNVERIFIED_GATE_INPUT',authorized_source_gets=0)
    target=Path(a.output)
    _need(not target.exists() and target.parent==Path(os.environ['RUNNER_TEMP']).resolve(),'PRIVATE_OUTPUT')
    fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump(result,f,sort_keys=True);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k in
          ('status','authorized_source_gets','source_owner_240_unchanged',
           'pending_due_count','remaining_60m_gets')},sort_keys=True))
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:
        f.write('admitted='+str(result['status']=='FRESH_RESULT_GET_ADMITTED').lower()+'\n')
        f.write('source_get_cap='+str(result['authorized_source_gets'])+'\n')
    return 0

if __name__=='__main__':raise SystemExit(main())
