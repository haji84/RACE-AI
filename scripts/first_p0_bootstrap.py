"""Create or recover the FIRST current-day P0 only after exhaustive same-workflow receipt checks.

This helper does not alter the existing five models, touch old ZIP bytes, or
interpret a missing index as proof that the original is absent. The only
repository write is a create-only metadata index on the existing PR branch.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

# GitHub Actions invokes this file directly, not via `python -m`.
# Import the checked-out repository packages without modifying dependencies.
ROOT_SCRIPT = Path(__file__).resolve().parents[1]
if str(ROOT_SCRIPT) not in sys.path:
    sys.path.insert(0, str(ROOT_SCRIPT))

from race_ai.cycle_recovery import (day_runs, p0_original_or_empty, artifact_pages,
                                   previous_source_control)
from race_ai.frozen_day_cycle import archive_json, need, read_p0, ts
from race_ai.repeated_cycle import matches
from scripts.github_existing_cycle import ROOT, REPO, JST, gh, original, event_day, source_identity_conflict

BRANCH = 'feat/four-sport-forecast-audit-view-20261022'
WORKFLOW = 405276784


def index_path(day):
    return ROOT / 'docs' / 'evidence' / day / 'p0-first-receipt.json'


def receipt_index(raw, meta, day):
    doc, rows = read_p0(raw, meta, expected_day=day)
    need(doc.get('race_count', 0) > 0 and len(rows) == doc['model_forecast_count'],
         'FIRST_P0_EMPTY_OR_INCOMPLETE')
    _, body_sha = archive_json(raw, meta, 'forecasts.json',
                               f"boat-p0-existing-{meta['workflow_run']['id']}")
    need(all(r['original_json_sha256'] == body_sha for r in rows), 'P0_BODY_HASH_CONFLICT')
    return dict(schema='RACE_AI_P0_FIRST_RECEIPT_V1', day_jst=day,
                artifact_id=meta['id'], run_id=meta['workflow_run']['id'],
                server_created_at=meta['created_at'], zip_sha256=meta['digest'][7:],
                json_sha256=body_sha, race_count=doc['race_count'],
                model_forecast_count=doc['model_forecast_count'],
                no_regeneration=True, retention_days=7,
                permanent_private_storage_proven=False)


def previous_first_receipt(day, run_id):
    """Enumerate every earlier run in the existing workflow, failing closed."""
    candidates = []
    for run in day_runs(gh, day, current_run=run_id):
        try:
            artifacts = artifact_pages(gh, run['id'])
        except ValueError as exc:
            raise ValueError('FIRST_P0_ARTIFACT_PAGINATION_INCOMPLETE') from exc
        for item in artifacts:
            if not matches(item['name'], f"boat-p0-existing-{run['id']}"):
                continue
            meta = json.loads(gh(f"actions/artifacts/{item['id']}"))
            need(meta['id'] == item['id'] and
                 meta['workflow_run']['id'] == run['id'], 'FOREIGN_FIRST_P0_ARTIFACT')
            raw = gh(f"actions/artifacts/{item['id']}/zip")
            # Empty/failed early source attempts are retained, never fabricated.
            prior_doc,_=archive_json(raw,meta,'forecasts.json',f"boat-p0-existing-{run['id']}")
            prior_day=prior_doc.get('day_jst')
            doc, rows = p0_original_or_empty(raw, meta, prior_day)
            if prior_day != day:
                continue
            if rows:
                candidates.append((ts(meta['created_at']), meta['id'], raw, meta))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    _, _, raw, meta = candidates[0]
    return raw, meta


def _remote_file(path, *, ref=BRANCH):
    cmd = ['gh', 'api', f'repos/{REPO}/contents/{path}?ref={ref}']
    reply = subprocess.run(cmd, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=50)
    if reply.returncode:
        if b'HTTP 404' in reply.stderr:
            return None
        raise RuntimeError('P0_REGISTRY_REMOTE_READ_FAILED: ' +
                           reply.stderr.decode(errors='replace')[:200])
    return json.loads(reply.stdout)


def _receipt_file_matches(value, path, body, *, with_content=True):
    """Bind the Contents receipt to this path and the exact Git blob bytes."""
    blob_sha = hashlib.sha1(f'blob {len(body)}\0'.encode() + body).hexdigest()
    if not (isinstance(value, dict) and value.get('path') == path and
            value.get('type') == 'file' and type(value.get('size')) is int and
            value['size'] == len(body) and value.get('sha') == blob_sha):
        return False
    if not with_content:
        return True
    if value.get('encoding') != 'base64' or not isinstance(value.get('content'), str):
        return False
    try:
        decoded = base64.b64decode(value['content'].replace('\n', ''), validate=True)
    except ValueError:
        return False
    return decoded == body


def register(day, raw, meta):
    """Write-once GitHub index, then check the server-returned bytes."""
    need(datetime.now(timezone.utc).astimezone(JST).date().isoformat() == day,
         'DAY_CHANGED_BEFORE_FIRST_P0_INDEX')
    path = index_path(day)
    value = receipt_index(raw, meta, day)
    body = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8') + b'\n'
    rel = path.relative_to(ROOT).as_posix()
    existing = _remote_file(rel)
    if existing is not None:
        need(_receipt_file_matches(existing, rel, body),
             'FIRST_RECEIPT_EXISTS_WITH_OTHER_ORIGINAL')
        # This independent GET already authenticates an existing immutable blob;
        # no write occurred, so another moving-branch read adds no evidence.
    else:
        payload = dict(message=f"evidence(boat): register first authenticated P0 for {day}",
                       content=base64.b64encode(body).decode(),
                       branch=BRANCH)
        result = subprocess.run(
            ['gh', 'api', '--method', 'PUT', f'repos/{REPO}/contents/{rel}', '--input', '-'],
            input=json.dumps(payload).encode(), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=50)
        need(result.returncode == 0,
             'FIRST_RECEIPT_INDEX_CREATE_REJECTED: ' +
             result.stderr.decode(errors='replace')[:180])
        try:
            created = json.loads(result.stdout)
            commit = created['commit']['sha']
            valid = (isinstance(commit, str) and len(commit) == 40 and
                     all(char in '0123456789abcdef' for char in commit) and
                     _receipt_file_matches(created['content'], rel, body, with_content=False))
        except (ValueError, KeyError, TypeError):
            valid = False
        need(valid, 'FIRST_RECEIPT_INDEX_CREATE_RECEIPT_INVALID')
        # Read the creation commit, not the mutable branch just read as absent.
        # The PUT response itself never substitutes for independent readback.
        checked = _remote_file(rel, ref=commit)
        need(_receipt_file_matches(checked, rel, body),
             'FIRST_RECEIPT_INDEPENDENT_READBACK_MISMATCH')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        need(path.read_bytes() == body, 'LOCAL_FIRST_RECEIPT_CONFLICT')
    else:
        with path.open('xb') as f:
            f.write(body)
    original(day)
    return value


def output_capture(value):
    target = os.environ.get('GITHUB_OUTPUT')
    if target:
        with open(target, 'a', encoding='utf-8') as f:
            f.write('capture=' + ('true' if value else 'false') + '\n')

def output_complete(value):
    target=os.environ.get('GITHUB_OUTPUT')
    if target:
        with open(target,'a',encoding='utf-8') as stream:
            stream.write('capture_complete='+('true' if value else 'false')+'\n')

def _control_path():
    return ROOT/'cycle_recovery_output/bootstrap-source-control.json'

def _save_control(value):
    from race_ai.repeated_cycle import write_state
    return write_state(_control_path(),value,key='source_control_sha256')

def bootstrap_control(day,run_id,*,inherited=None):
    path=_control_path()
    if path.exists():
        value=json.loads(path.read_text());claimed=value.pop('source_control_sha256')
        need(claimed==hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
             ensure_ascii=False,allow_nan=False).encode()).hexdigest(),'BOOTSTRAP_SOURCE_CONTROL_HASH')
        need(value.get('schema')=='RACE_AI_BOOTSTRAP_SOURCE_CONTROL_V1' and
             value.get('day_jst')==day and value.get('run_id')==run_id and
             type(value.get('requests_used')) is int and value['requests_used']>=0,
             'BOOTSTRAP_SOURCE_CONTROL_IDENTITY')
        return value
    inherited=inherited or {}
    from race_ai.repeated_cycle import SOURCE_LIMIT
    total=inherited.get('lifetime_requests',0)
    day_base=(inherited.get('day_start_lifetime_requests')
              if inherited.get('day_jst')==day else total)
    need(type(total) is int and type(day_base) is int and 0<=day_base<=total,
         'BOOTSTRAP_DAY_SOURCE_BUDGET_UNVERIFIED')
    need(SOURCE_LIMIT is None or total-day_base<=SOURCE_LIMIT,
         'BOOTSTRAP_DAY_SOURCE_BUDGET_EXCEEDED')
    value=dict(schema='RACE_AI_BOOTSTRAP_SOURCE_CONTROL_V1',day_jst=day,run_id=run_id,
        requests_used=0,completed_round=0,source_wait=inherited.get('source_wait'),
        lifetime_requests_base=total,
        lifetime_requests=total,day_start_lifetime_requests=day_base,
        lifetime_completed_rounds=inherited.get('lifetime_completed_rounds',0),
        previous_halted_reason=inherited.get('previous_halted_reason'),halted_reason=None,
        inherited_source_receipt=inherited.get('receipt'))
    _save_control(value)
    return value


def preflight(day, run_id):
    inherited=previous_source_control(gh,day,current_run=run_id)
    # Even a manually-dispatched production worker must not restart the
    # official-source allowance after an unresolved same-day owner attempt.
    # PR-only offline CI is filtered by day_runs/owner_run_origin.
    earlier=[run for run in day_runs(gh,day,current_run=run_id)
             if ts(run['created_at']).astimezone(JST).date().isoformat()==day]
    if earlier:
        need(inherited is not None and inherited.get('day_jst')==day and
             type(inherited.get('day_start_lifetime_requests')) is int,
             'SAME_DAY_OWNER_SOURCE_CONTROL_REQUIRED')
    bootstrap_control(day,run_id,inherited=inherited)
    prior = previous_first_receipt(day, run_id)
    path = index_path(day)
    if path.is_file():
        _, rows, meta, _ = original(day)
        need(rows, 'REGISTERED_FIRST_P0_EMPTY')
        if prior is not None:
            _, first_meta = prior
            need(first_meta['id'] == meta['id'], 'INDEX_IS_NOT_EARLIEST_FIRST_P0')
        output_capture(False)
        output_complete(True)
        return 'REGISTERED_P0_REUSED'
    if prior is not None:
        raw, meta = prior
        register(day, raw, meta)
        output_capture(False)
        output_complete(True)
        return 'PREVIOUS_FIRST_P0_RECOVERED'
    output_capture(True)
    output_complete(False)
    return 'NO_SAME_WORKFLOW_FIRST_P0_FOUND_CAPTURE_REQUIRED'


def capture(day, run_id, *, now=None, clock=None, handoff_at=None):
    from race_ai.source_retry_policy import plan_http_wait,wait_active,SourceWait
    clock=clock or (lambda:now or datetime.now(timezone.utc))
    moment=clock()
    need(moment.utcoffset() is not None,'aware first-P0 clock')
    if moment.astimezone(JST).date().isoformat()!=day:
        return dict(state='DAY_HANDOFF',capture_complete=False,retry_at=None)
    control=bootstrap_control(day,run_id)
    if handoff_at is None and os.environ.get('RACE_AI_WORKER_HANDOFF_AT'):
        handoff_at=ts(os.environ['RACE_AI_WORKER_HANDOFF_AT'])
    wait=control.get('source_wait')
    if wait_active(wait,moment):
        return dict(state=wait['state'],reason=wait['reason'],retry_at=wait['retry_at'],
                    capture_complete=False)
    # Cross-check again immediately before the only official GET.
    need(not index_path(day).exists(), 'FIRST_P0_ALREADY_INDEXED')
    need(previous_first_receipt(day, run_id) is None,
         'FIRST_P0_ALREADY_PRESENT_NO_REGENERATION')
    from scripts.existing_day_program import collect
    def actual_day_clock():
        observed=clock()
        if observed.astimezone(JST).date().isoformat()!=day:
            raise SourceWait('DAY_HANDOFF',state='SOURCE_WAIT')
        if handoff_at is not None and observed>=handoff_at:
            raise SourceWait('WORKER_HANDOFF',state='SOURCE_WAIT')
        return observed
    class BootstrapGuard:
        def charge(self,kind):
            from race_ai.repeated_cycle import SOURCE_LIMIT
            need(kind=='forecast','BOOTSTRAP_SOURCE_KIND_REJECTED')
            actual_day_clock()
            base=control.get('day_start_lifetime_requests')
            need(type(base) is int and 0<=base<=control['lifetime_requests'],
                 'BOOTSTRAP_DAY_SOURCE_BUDGET_UNVERIFIED')
            need(SOURCE_LIMIT is None or control['lifetime_requests']-base<SOURCE_LIMIT,
                 'BOOTSTRAP_DAY_SOURCE_BUDGET_EXCEEDED')
            control['requests_used']+=1
            control['lifetime_requests']=control['lifetime_requests_base']+control['requests_used']
            _save_control(control)  # Immediately before the actual GET.
    try:
        actual_day_clock()  # Receipt reads may have crossed a control boundary.
        result = collect(clock=actual_day_clock,source_guard=BootstrapGuard())
    except SourceWait as exc:
        if exc.reason not in ('DAY_HANDOFF','WORKER_HANDOFF'):raise
        control['control_reason']=exc.reason;_save_control(control)
        return dict(state=exc.reason,capture_complete=False,retry_at=None)
    observed=clock()
    boundary=('DAY_HANDOFF' if observed.astimezone(JST).date().isoformat()!=day else
              'WORKER_HANDOFF' if handoff_at is not None and observed>=handoff_at else None)
    if boundary is not None:
        # A denial received just before midnight still governs the next day.
        # The expected control boundary must not discard its Retry-After.
        if result.get('http_status') is not None:
            control['source_wait']=plan_http_wait(result['http_status'],
                result.get('source_response_headers',{}),clock(),
                attempt=(wait or {}).get('attempts',0)+1,
                not_yet_published=result['http_status']==404)
            _save_control(control)
        control['control_reason']=boundary;_save_control(control)
        return dict(state=boundary,capture_complete=False,retry_at=None)
    if (result.get('day_jst')!=day or result.get('source_requests')!=1 or
            result.get('race_count',0)<=0 or result.get('model_forecast_count',0)<=0):
        status=result.get('http_status')
        attempt=(wait or {}).get('attempts',0)+1
        validation=(status is None and bool(result.get('failure_class')) and
                    result.get('source_error_kind')!='TRANSPORT' and
                    result.get('failure_class') not in ('TimeoutError','URLError','OSError'))
        if result.get('source_error_kind')=='TRANSPORT' or result.get('failure_class') in ('TimeoutError','URLError','OSError'):
            status=None
        elif status is None:
            status=200 if not result.get('failure_class') else None
        if source_identity_conflict(result.get('reason')) and (status is None or status<400):
            plan=dict(state='SOURCE_REVIEW_WAIT',reason='SOURCE_VERIFICATION_REQUIRED',
                      retry_at=None,http_status=None,attempts=attempt)
        else:
            plan=plan_http_wait(status,result.get('source_response_headers',{}),clock(),
                                attempt=attempt,not_yet_published=status in (200,404))
            if validation:plan.update(state='WAITING_PUBLICATION',reason='NO_QUALIFIED_FIRST_P0')
        if status==200:plan['reason']='NO_QUALIFIED_FIRST_P0'
        control['source_wait']=plan;_save_control(control)
        return dict(state=plan['state'],reason=plan['reason'],retry_at=plan['retry_at'],
                    capture_complete=False)
    control['source_wait']=None;_save_control(control)
    need(result.get('day_jst') == day and result.get('source_requests') == 1 and
         result.get('race_count', 0) > 0 and result.get('model_forecast_count', 0) > 0,
         'FIRST_P0_SOURCE_OR_MODEL_BLOCKED: ' +
         str(result.get('failure_class', result.get('state', 'unknown'))) + ': ' +
         str(result.get('reason', ''))[:120])
    folder = ROOT / 'boat_all_day_output'
    folder.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode()
    with (folder / 'forecasts.json').open('xb') as f:
        f.write(payload)
    return dict(state='FIRST_P0_CREATED_PENDING_SERVER_RECEIPT',
                capture_complete=True,
                races=result['race_count'], models=result['model_forecast_count'],
                json_sha256=hashlib.sha256(payload).hexdigest())

def capture_wait(day,run_id,*,clock=lambda:datetime.now(timezone.utc),sleep=time.sleep,
                 handoff_at=None):
    """Wait respectfully for first-day input without creating an empty original."""
    from race_ai.source_retry_policy import wait_active
    if handoff_at is None and os.environ.get('RACE_AI_WORKER_HANDOFF_AT'):
        handoff_at=ts(os.environ['RACE_AI_WORKER_HANDOFF_AT'])
    while True:
        now=clock()
        if now.astimezone(JST).date().isoformat()!=day or handoff_at is not None and now>=handoff_at:
            reason='DAY_HANDOFF' if now.astimezone(JST).date().isoformat()!=day else 'WORKER_HANDOFF'
            control=bootstrap_control(day,run_id)
            control['control_reason']=reason;_save_control(control)
            output_complete(False)
            return dict(state=reason,capture_complete=False,retry_at=None)
        control=bootstrap_control(day,run_id)
        wait=control.get('source_wait')
        if wait_active(wait,now):
            delay=max(1,(ts(wait['retry_at'])-now).total_seconds()) if wait['retry_at'] else 30
            sleep(min(delay,30));continue
        result=capture(day,run_id,clock=clock,handoff_at=handoff_at)
        if result.get('capture_complete'):
            output_complete(True);return result
        if result['state'] in ('DAY_HANDOFF','WORKER_HANDOFF'):
            output_complete(False);return result


def finalize(day, run_id, artifact_id):
    need(not index_path(day).exists(), 'FIRST_P0_INDEX_ALREADY_EXISTS')
    need(previous_first_receipt(day, run_id) is None,
         'PRIOR_FIRST_P0_FOUND_BEFORE_FINALIZE')
    meta = json.loads(gh(f'actions/artifacts/{artifact_id}'))
    need(meta.get('workflow_run', {}).get('id') == run_id and
         meta.get('name') == f'boat-p0-existing-{run_id}',
         'FIRST_P0_THIS_RUN_ARTIFACT_IDENTITY')
    raw = gh(f'actions/artifacts/{artifact_id}/zip')
    indexed = receipt_index(raw, meta, day)
    local = (ROOT / 'boat_all_day_output' / 'forecasts.json').read_bytes()
    need(hashlib.sha256(local).hexdigest() == indexed['json_sha256'],
         'FIRST_P0_UPLOAD_DOES_NOT_MATCH_LOCAL_SOURCE')
    return register(day, raw, meta)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=('preflight', 'capture', 'capture-wait', 'finalize'))
    p.add_argument('--artifact-id', type=int)
    a = p.parse_args()
    day = event_day()
    run_id = int(os.environ['GITHUB_RUN_ID'])
    if a.command == 'preflight':
        result = preflight(day, run_id)
    elif a.command == 'capture':
        result = capture(day, run_id)
    elif a.command == 'capture-wait':
        result = capture_wait(day, run_id)
    else:
        need(a.artifact_id is not None and a.artifact_id > 0,
             'FIRST_P0_ARTIFACT_ID_REQUIRED')
        result = finalize(day, run_id, a.artifact_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 75 if a.command=='capture' and not result.get('capture_complete') else 0


if __name__ == '__main__':
    raise SystemExit(main())
