"""Bounded, sequential rounds in the existing Actions writer.

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

MAX_ROUNDS = 24
POLL_SECONDS = 180
# The owner removed numeric GET ceilings. None means unlimited, while counts,
# round/time/day boundaries and HTTP/source-identity stop latches remain real.
SOURCE_LIMIT = None
MAX_SECONDS = 65 * 60
CACHE_SECONDS = 600
JST = timezone(timedelta(hours=9))

def _need(ok, reason):
    if not ok:
        raise ValueError(reason)

def instant(value):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    _need(t.utcoffset() is not None, 'aware timestamp required')
    return t

def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def write_state(path, value, key='session_sha256'):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {k:v for k,v in value.items() if k != key}
    if data.get('schema') == 'RACE_AI_BOUNDED_REPEAT_V1':
        _need(type(data.get('requests_used')) is int and data['requests_used'] >= 0,
              'session request count')
        if target.exists():
            previous = load(target)
            _need(data['requests_used'] >= previous['requests_used'], 'session request count decreased')
            _need(not previous['halted_reason'] or data.get('halted_reason'), 'session halt cannot be cleared')
        # Normalize only the now-unlimited policy metadata during an actual
        # authorized write. Never reset source counts or an old durable halt.
        data['source_limit'] = SOURCE_LIMIT
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
    _need(type(round_no) is int and 1 <= round_no <= MAX_ROUNDS, 'invalid round')
    return f'{prefix}-{run_id}' + (f'-cycle-{round_no:02d}' if round_no > 1 else '')

def matches(name, expected):
    if name == expected:
        return True
    if not isinstance(name, str):
        return False
    m = re.fullmatch(re.escape(expected) + r'-cycle-(\d\d)', name)
    return m is not None and 2 <= int(m[1]) <= MAX_ROUNDS

def start(path, *, day, run_id, now):
    _need(now.utcoffset() is not None and now.astimezone(JST).date().isoformat() == day,
          'session day/clock mismatch')
    if Path(path).exists():
        old = load(path)
        _need(old['run_id'] == run_id and old['day_jst'] == day, 'foreign existing session')
        return old
    # A successor may be queued in the SAME concurrency group. Do not stop
    # early merely because the existing hourly task is about to run.
    midnight = (now.astimezone(JST).replace(hour=0,minute=0,second=0,microsecond=0)
                + timedelta(days=1))
    stop_at = min(now + timedelta(seconds=MAX_SECONDS), midnight)
    state = dict(schema='RACE_AI_BOUNDED_REPEAT_V1', day_jst=day, run_id=run_id,
                 started_at=now.isoformat(), stop_at=stop_at.isoformat(),
                 completed_round=0, prepared_round=None, last_started_at=None,
                 requests_used=0, requests_by_kind={}, halted_reason=None, receipts=[],
                 interval_seconds=POLL_SECONDS, max_rounds=MAX_ROUNDS,
                 source_limit=SOURCE_LIMIT, all_day_coverage_proven=False)
    write_state(path, state)
    return state

def prepare(path, round_no, *, now):
    state = load(path)
    _need(type(round_no) is int and 1 <= round_no <= MAX_ROUNDS, 'invalid round')
    reason = state['halted_reason']
    if now.astimezone(JST).date().isoformat() != state['day_jst']:
        reason = 'DAY_CHANGED'
    if now >= instant(state['stop_at']):
        reason = reason or 'BOUNDED_SESSION_END'
    if reason:
        state['halted_reason'] = reason; write_state(path,state)
        return dict(active=False, wait_seconds=0, reason=reason)
    _need(state['prepared_round'] is None and state['completed_round'] == round_no-1,
          'UNCOMMITTED_PREVIOUS_ROUND_OR_DUPLICATE')
    ready = (instant(state['last_started_at']) + timedelta(seconds=POLL_SECONDS)
             if state['last_started_at'] else now)
    if ready > now:
        return dict(active=False, wait_seconds=max(1, int((ready-now).total_seconds())),
                    reason='POLL_INTERVAL')
    state['prepared_round']=round_no; state['last_started_at']=now.isoformat()
    write_state(path,state)
    return dict(active=True,wait_seconds=0,reason='READY',
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
    write_state(path,state)
    return state

class SourceGuard:
    """Count every request and retain the existing time/4xx stop latches."""
    def __init__(self,path,clock=lambda:datetime.now(timezone.utc)):
        self.path=Path(path);self.clock=clock
    def charge(self,kind):
        state=load(self.path)
        _need(kind in ('forecast','result'),'source kind')
        if self.clock() >= instant(state['stop_at']):
            state['halted_reason']='BOUNDED_SESSION_END';write_state(self.path,state)
        _need(not state['halted_reason'], state['halted_reason'] or 'halted')
        state['requests_used']+=1
        state['requests_by_kind'][kind]=state['requests_by_kind'].get(kind,0)+1
        write_state(self.path,state)
    def http_failure(self,status):
        if 400 <= status < 500:
            state=load(self.path);state['halted_reason']=f'SOURCE_HTTP_{status}_NO_RETRY'
            write_state(self.path,state)

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
        state['schedule_cache']={k:copy.deepcopy(p1_doc[k]) for k in ('official_day_source','official_race_registry','verified_active_venues') if k in p1_doc}
        for pair in p1_doc.get('paired_forecasts',[]):
            state['index_entries'].append(dict(race_id=pair['race_id'],cutoff_at=pair['cutoff_at'],
                run_id=p1_receipt['workflow_run']['id'],artifact_id=p1_receipt['id'],
                server_created_at=p1_receipt['created_at'],zip_sha256=p1_receipt['digest'][7:],
                json_sha256=body_sha,bundle_sha256=pair['bundle_sha256']))
    write_state(path,state,key='state_sha256')
    return state
