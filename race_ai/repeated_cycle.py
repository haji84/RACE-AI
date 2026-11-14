"""Continuous, sequential logical rounds in the existing Actions writer.

This module never predicts, fetches official data, changes model coefficients,
or proves a receipt on its own. Callers must verify independent artifact bytes.
"""
from __future__ import annotations
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from .source_retry_policy import SourceWait, plan_http_wait, wait_active

MAX_ROUNDS = 24
POLL_SECONDS = 180
# Fixed operational bounds. Do not migrate or reopen stopped prior sessions.
# Tests may inject None only to verify legacy unbounded snapshot handling.
SOURCE_LIMIT = 240
MAX_SECONDS = 65 * 60
ROUND_SOURCE_LIMIT = 45
CACHE_SECONDS = 180
JST = timezone(timedelta(hours=9))
_NORMAL_ENDS=frozenset(('BOUNDED_SESSION_END','MAX_ROUNDS_REACHED','DAY_CHANGED','DAY_HANDOFF',
                       'SOURCE_BUDGET_EXHAUSTED','SESSION_SOURCE_BUDGET_EXHAUSTED',
                       'ROUND_SOURCE_BUDGET_EXHAUSTED'))

def _need(ok, reason):
    if not ok:
        raise ValueError(reason)

def instant(value):
    t = value if isinstance(value,datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    _need(t.utcoffset() is not None, 'aware timestamp required')
    return t

def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def _verification_wait(reason, attempts):
    _need(type(reason) is str and re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}',reason),
          'SOURCE_VERIFICATION_REASON_INVALID')
    _need(type(attempts) is int and attempts>=1,'SOURCE_VERIFICATION_ATTEMPT_INVALID')
    return dict(state='SOURCE_REVIEW_WAIT',reason=reason,retry_at=None,http_status=None,attempts=attempts)

def write_state(path, value, key='session_sha256'):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {k:v for k,v in value.items() if k != key}
    if data.get('schema') == 'RACE_AI_BOUNDED_REPEAT_V1':
        previous = None
        _need(type(data.get('requests_used')) is int and data['requests_used'] >= 0,
              'session request count')
        _need(type(data.get('completed_round')) is int and data['completed_round']>=0,'session round count')
        for field in ('lifetime_requests_base','lifetime_completed_rounds_base'):
            _need(type(data.get(field,0)) is int and data.get(field,0)>=0,'session lifetime count')
        if target.exists():
            previous = load(target)
            _need(data['requests_used'] >= previous['requests_used'], 'session request count decreased')
            _need(data['completed_round']>=previous['completed_round'],'session round count decreased')
            for field in ('lifetime_requests_base','lifetime_completed_rounds_base'):
                _need(data.get(field,0)>=previous.get(field,0),'session lifetime count decreased')
            migration=data.get('policy_migration',{})
            allowed=(all(limit is None for limit in (MAX_ROUNDS,MAX_SECONDS,SOURCE_LIMIT,ROUND_SOURCE_LIMIT)) and
                     previous['halted_reason'] in _NORMAL_ENDS and
                     migration.get('from_session_sha256')==_digest(previous) and
                     migration.get('previous_halted_reason')==previous['halted_reason'] and
                     data.get('stop_at') is None and data.get('max_rounds') is None)
            _need(not previous['halted_reason'] or data.get('halted_reason') or allowed,
                  'session halt cannot be cleared')
        if SOURCE_LIMIT is not None:
            _need(data['requests_used'] <= SOURCE_LIMIT, 'SESSION_SOURCE_BUDGET_EXCEEDED')
        data['source_limit'] = SOURCE_LIMIT
        data['lifetime_requests'] = data.get('lifetime_requests_base',0)+data['requests_used']
        data['lifetime_completed_rounds'] = data.get('lifetime_completed_rounds_base',0)+data['completed_round']
        if previous is not None:
            for total,base,used in (('lifetime_requests','lifetime_requests_base','requests_used'),
                                    ('lifetime_completed_rounds','lifetime_completed_rounds_base','completed_round')):
                claimed=previous.get(total,previous.get(base,0)+previous[used])
                _need(type(claimed) is int and claimed>=0,'session lifetime total')
                _need(data[total]>=claimed,'session lifetime total decreased')
    data[key] = _digest(data)
    temp = target.with_name(target.name + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    os.replace(temp, target)
    return data

def load(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    claimed = data.pop('session_sha256')
    _need(claimed == _digest(data), 'session hash mismatch')
    _need(data['schema'] == 'RACE_AI_BOUNDED_REPEAT_V1', 'session schema')
    _need(type(data['requests_used']) is int and data['requests_used'] >= 0,
          'session request count')
    _need(data.get('source_limit') is None or
          type(data.get('source_limit')) is int and data['source_limit'] == 240,
          'session source policy metadata')
    return data

def artifact_name(prefix, run_id, round_no):
    _need(prefix in ('boat-national-cutoff', 'race-existing-cycle', 'boat-p0-existing'),
          'artifact prefix rejected')
    _need(type(run_id) is int and run_id > 0, 'invalid run ID')
    _need(type(round_no) is int and round_no >= 1, 'invalid round')
    return f'{prefix}-{run_id}' + (f'-cycle-{round_no:02d}' if prefix=='boat-p0-existing' or round_no > 1 else '')

def matches(name, expected):
    if name == expected:
        return True
    if not isinstance(name, str):
        return False
    m = re.fullmatch(re.escape(expected) + r'-cycle-([0-9]{2,})', name)
    minimum=1 if re.fullmatch(r'boat-p0-existing-[1-9][0-9]*',expected) else 2
    return m is not None and int(m[1]) >= minimum and m[1] == f'{int(m[1]):02d}'

def start(path, *, day, run_id, now, source_control=None):
    _need(now.utcoffset() is not None and now.astimezone(JST).date().isoformat() == day,
          'session day/clock mismatch')
    if Path(path).exists():
        old = load(path)
        _need(old['run_id'] == run_id and old['day_jst'] == day, 'foreign existing session')
        unlimited=all(limit is None for limit in (MAX_ROUNDS,MAX_SECONDS,SOURCE_LIMIT,ROUND_SOURCE_LIMIT))
        if unlimited and (old.get('stop_at') is not None or old.get('max_rounds') is not None or
                          old.get('source_limit') is not None or old['halted_reason'] in _NORMAL_ENDS):
            prior=copy.deepcopy(old)
            migration=dict(from_session_sha256=_digest(prior),
                previous_halted_reason=prior['halted_reason'],previous_stop_at=prior.get('stop_at'),
                previous_max_rounds=prior.get('max_rounds'),previous_source_limit=prior.get('source_limit'))
            if prior.get('policy_migration') is not None:
                migration['previous_policy_migration']=copy.deepcopy(prior['policy_migration'])
            old.update(stop_at=None,max_rounds=None,source_limit=None,policy_migration=migration)
            if old['halted_reason'] in _NORMAL_ENDS:old['halted_reason']=None
            return write_state(path,old)
        if not unlimited:
            _need(old.get('source_limit') == SOURCE_LIMIT and old.get('max_rounds') == MAX_ROUNDS and
                  (MAX_SECONDS is None or old.get('stop_at') is not None) and
                  (SOURCE_LIMIT is None or old['requests_used'] <= SOURCE_LIMIT),
                  'SESSION_POLICY_MIGRATION_REQUIRES_NEW_RUN')
        return old
    control = {} if source_control is None else source_control
    _need(type(control) is dict,'source control mapping')
    for key in ('lifetime_requests','lifetime_completed_rounds'):
        _need(type(control.get(key,0)) is int and control.get(key,0)>=0,'source lifetime count')
    source_wait=copy.deepcopy(control.get('source_wait'))
    if source_wait is not None:wait_active(source_wait,now)
    previous_halt=control.get('previous_halted_reason')
    legacy_rate_limit=previous_halt in ('SOURCE_HTTP_429_NO_RETRY','SOURCE_HTTP_429','HTTP_RATE_LIMIT')
    if previous_halt and previous_halt not in _NORMAL_ENDS and (source_wait is None or not legacy_rate_limit):
        source_wait=_verification_wait('PREVIOUS_SOURCE_HALT_REQUIRES_REVIEW',
                                      (source_wait or {}).get('attempts',0)+1)
    state = dict(schema='RACE_AI_BOUNDED_REPEAT_V1', day_jst=day, run_id=run_id,
                 started_at=now.isoformat(),
                 stop_at=(now+timedelta(seconds=MAX_SECONDS)).isoformat() if MAX_SECONDS is not None else None,
                 completed_round=0, prepared_round=None, last_started_at=None,
                 requests_used=0, requests_by_kind={}, halted_reason=None, receipts=[],
                 source_wait=source_wait, source_control=copy.deepcopy(control),
                 lifetime_requests_base=control.get('lifetime_requests',0),
                 lifetime_completed_rounds_base=control.get('lifetime_completed_rounds',0),
                 interval_seconds=POLL_SECONDS, max_rounds=MAX_ROUNDS,
                 source_limit=SOURCE_LIMIT, all_day_coverage_proven=False)
    return write_state(path, state)

def prepare(path, round_no, *, now, next_action_at=None):
    state = load(path)
    _need(type(round_no) is int and round_no >= 1, 'invalid round')
    reason = state['halted_reason']
    if now.astimezone(JST).date().isoformat() != state['day_jst']:
        return dict(active=False,wait_seconds=0,reason='DAY_HANDOFF')
    if reason:
        return dict(active=False, wait_seconds=0, reason=reason)
    # Mandatory operational limits; previously stopped sessions must not restart.
    if state.get('stop_at') is not None and now >= instant(state['stop_at']):
        state['halted_reason']='BOUNDED_SESSION_END'
        write_state(path,state)
        return dict(active=False,wait_seconds=0,reason='BOUNDED_SESSION_END')
    if MAX_ROUNDS is not None and (round_no > MAX_ROUNDS or state['completed_round'] >= MAX_ROUNDS):
        state['halted_reason']='MAX_ROUNDS_REACHED'
        write_state(path,state)
        return dict(active=False,wait_seconds=0,reason='MAX_ROUNDS_REACHED')
    if (SOURCE_LIMIT is not None and
            SOURCE_LIMIT-state['requests_used'] < (ROUND_SOURCE_LIMIT or 1)):
        state['halted_reason']='SESSION_SOURCE_BUDGET_EXHAUSTED'
        write_state(path,state)
        return dict(active=False,wait_seconds=0,reason='SESSION_SOURCE_BUDGET_EXHAUSTED')
    waiting=state.get('source_wait')
    if wait_active(waiting,now):
        retry=waiting.get('retry_at')
        return dict(active=False,wait_seconds=max(1,int((instant(retry)-now).total_seconds())) if retry else POLL_SECONDS,
                    reason=waiting['state'],retry_at=retry)
    _need(state['prepared_round'] is None and state['completed_round'] == round_no-1,
          'UNCOMMITTED_PREVIOUS_ROUND_OR_DUPLICATE')
    ready = (instant(state['last_started_at']) + timedelta(seconds=POLL_SECONDS)
             if state['last_started_at'] else now)
    if next_action_at is not None and state['last_started_at']:
        ready=min(ready,max(instant(state['last_started_at'])+timedelta(seconds=1),instant(next_action_at)))
    if ready > now:
        return dict(active=False, wait_seconds=max(1, int((ready-now).total_seconds())),
                    reason='POLL_INTERVAL')
    state['prepared_round']=round_no; state['last_started_at']=now.isoformat()
    state['round_started_requests']=state['requests_used']
    write_state(path,state)
    return dict(active=True,wait_seconds=0,reason='READY',
                p0_name=artifact_name('boat-p0-existing',state['run_id'],round_no),
                forecast_name=artifact_name('boat-national-cutoff',state['run_id'],round_no),
                result_name=artifact_name('race-existing-cycle',state['run_id'],round_no))

def complete(path, round_no, *, now, forecast_artifact, result_artifact):
    state=load(path)
    _need(state['prepared_round']==round_no and state['completed_round']==round_no-1,
          'round completion order mismatch')
    _need(all(type(i) is int and i>0 for i in (forecast_artifact,result_artifact)) and
          forecast_artifact!=result_artifact, 'two independent artifact IDs required')
    prior={item[k] for item in state['receipts'] for k in ('forecast_artifact','result_artifact')}
    _need(forecast_artifact not in prior and result_artifact not in prior,'artifact reused across rounds')
    state['receipts'].append(dict(round=round_no,forecast_artifact=forecast_artifact,
                                  result_artifact=result_artifact,verified_at=now.isoformat()))
    state['completed_round']=round_no;state['prepared_round']=None
    return write_state(path,state)

class SourceGuard:
    """Count requests without bypassing durable upstream waits or hard latches."""
    def __init__(self,path,clock=lambda:datetime.now(timezone.utc)):
        self.path=Path(path);self.clock=clock
    def charge(self,kind):
        state=load(self.path)
        _need(kind in ('forecast','result'),'source kind')
        now=self.clock()
        _need(now.astimezone(JST).date().isoformat()==state['day_jst'],'DAY_HANDOFF')
        handoff=state.get('worker_handoff_at')
        _need(handoff is None or now<instant(handoff),'WORKER_HANDOFF')
        _need(not state['halted_reason'], state['halted_reason'] or 'halted')
        _need(state.get('stop_at') is None or now < instant(state['stop_at']), 'BOUNDED_SESSION_END')
        if SOURCE_LIMIT is not None and state['requests_used']>=SOURCE_LIMIT:
            state['halted_reason']='SESSION_SOURCE_BUDGET_EXHAUSTED'
            write_state(self.path,state)
            raise ValueError('SESSION_SOURCE_BUDGET_EXHAUSTED')
        if (ROUND_SOURCE_LIMIT is not None and state['prepared_round'] is not None and
                state['requests_used']-state.get('round_started_requests',0)>=ROUND_SOURCE_LIMIT):
            state['halted_reason']='ROUND_SOURCE_BUDGET_EXHAUSTED'
            write_state(self.path,state)
            raise ValueError('ROUND_SOURCE_BUDGET_EXHAUSTED')
        waiting=state.get('source_wait')
        if wait_active(waiting,now):
            raise SourceWait(waiting['reason'],waiting.get('retry_at'),state=waiting['state'])
        state['requests_used']+=1
        state['requests_by_kind'][kind]=state['requests_by_kind'].get(kind,0)+1
        write_state(self.path,state)
    def http_failure(self,status,headers=None,*,not_yet_published=False):
        state=load(self.path)
        previous=state.get('source_wait') or {}
        waiting=plan_http_wait(status,headers,self.clock(),attempt=previous.get('attempts',0)+1,
                               not_yet_published=not_yet_published)
        state['source_wait']=waiting;write_state(self.path,state)
        return waiting
    def http_success(self):
        state=load(self.path);waiting=state.get('source_wait')
        if (waiting and waiting.get('state') in ('RATE_LIMIT_WAIT','TRANSIENT_SOURCE_WAIT','WAITING_PUBLICATION') and
                waiting.get('retry_at') is not None and not wait_active(waiting,self.clock())):
            state['source_wait']=None;write_state(self.path,state)
    def verification_failure(self,reason='SOURCE_VERIFICATION_REQUIRED'):
        state=load(self.path)
        waiting=_verification_wait(reason,(state.get('source_wait') or {}).get('attempts',0)+1)
        state['source_wait']=waiting;write_state(self.path,state)
        return waiting

def usable_schedule(doc, *, day, now):
    """Only short-lived previously validated schedule metadata, never race inputs."""
    try:
        source=doc['official_day_source'];rows=doc['official_race_registry']
        if not rows or not source or not doc['verified_active_venues']:return False
        expected='https://www.boatrace.jp/owpc/pc/race/index?hd='+day.replace('-','')
        if source['url']!=expected:return False
        times=[instant(source['captured_at'])]+[instant(row['schedule_captured_at']) for row in rows]
        return (all(t<=now and (now-t).total_seconds()<=CACHE_SECONDS for t in times)
                and all(row['race_id'].startswith(day.replace('-','')+'-') for row in rows)
                and len({row['race_id'] for row in rows})==len(rows)
                and all(instant(row['cutoff_at']).astimezone(JST).date().isoformat()==day for row in rows))
    except (KeyError,ValueError,TypeError,AttributeError):
        return False

def checkpoint(path, previous, rows, observations, receipts, *, p1_doc, p1_receipt):
    from .first_receipt_continuity import first_receipt_rows,latest_result_observations
    unique,extra=first_receipt_rows(rows)
    _,journal=latest_result_observations(observations)
    metadata={}
    for receipt in receipts:
        old=metadata.setdefault(receipt['id'],receipt)
        _need(old==receipt,'one artifact has conflicting metadata')
    state=copy.deepcopy(previous)
    state.update(rows=unique,observations=journal,receipts=list(metadata.values()),complete=True)
    state['excluded_repeats']+=extra
    if p1_doc is not None:
        _need(p1_receipt is not None,'missing authenticated P1 receipt')
        body_hashes={x['original_json_sha256'] for x in unique if x['artifact_id']==p1_receipt['id']}
        _need(len(body_hashes)<=1,'conflicting P1 body hashes')
        body_sha=next(iter(body_hashes),None)
        _need(not p1_doc.get('paired_forecasts') or body_sha is not None,'P1 pair without verified rows')
        state['schedule_cache']={k:copy.deepcopy(p1_doc[k]) for k in
            ('official_day_source','official_race_registry','verified_active_venues','candidate_source_waits','next_check_at') if k in p1_doc}
        if p1_doc.get('entry_observation_history') is not None:
            from .boat_entry_source_collection import optional_cache_from_document
            candidate,rejection=optional_cache_from_document(p1_doc,
                day=state['day_jst'],as_of=p1_receipt['created_at'])
            if rejection is None:
                state['entry_observation_history']=candidate
            else:
                state['entry_observation_history_rejections']=state.get('entry_observation_history_rejections',0)+1
                state['entry_observation_history_rejection_reason']=rejection
                old,old_rejection=optional_cache_from_document(state,
                    day=state['day_jst'],as_of=p1_receipt['created_at'])
                if old_rejection is not None:state.pop('entry_observation_history',None)
                elif old is not None:state['entry_observation_history']=old
        for pair in p1_doc.get('paired_forecasts',[]):
            state['index_entries'].append(dict(race_id=pair['race_id'],cutoff_at=pair['cutoff_at'],
                run_id=p1_receipt['workflow_run']['id'],artifact_id=p1_receipt['id'],
                server_created_at=p1_receipt['created_at'],zip_sha256=p1_receipt['digest'][7:],
                json_sha256=body_sha,bundle_sha256=pair['bundle_sha256']))
    write_state(path,state,key='state_sha256')
    return state
