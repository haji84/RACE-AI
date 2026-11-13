"""Reconcile a genuinely saved pending round without prediction or source GET.

This is not permission to ignore a failed owner. Callers independently obtain
its final control, then read original GitHub bytes and decrypt them here. Only a
P1/RESULT pair bound to that exact checkpoint can complete the pending round.
The failed run and its original archives remain unchanged.
"""
from copy import deepcopy
from datetime import timezone, timedelta
import json
import re

from .actions_contract import digest
from .boat_owner_source_identity import authenticated_live_owner_run, OWNER_BRANCH
from .boat_private_original_archive import open_original_zip
from .boat_private_original_vault import _artifact, MAX_METADATA
from .boat_source_control import _metadata
from .frozen_day_cycle import read_p1, ts
from .repeated_cycle import artifact_name

SCHEMA = 'RACE_AI_PENDING_ROUND_RECOVERY_V1'
JST = timezone(timedelta(hours=9))


def need(ok, reason):
    if not ok:
        raise ValueError('ROUND_RECOVERY_' + reason)


def _counts(control):
    names = ('completed_round', 'prepared_round', 'previous_session_requests',
             'lifetime_requests', 'lifetime_completed_rounds', 'day_start_lifetime_requests')
    need(all(type(control.get(n)) is int and control[n] >= 0 for n in names), 'COUNTERS_INVALID')
    need(1 <= control['prepared_round'] <= 24 and
         control['prepared_round'] == control['completed_round'] + 1, 'ROUND_ORDER_INVALID')
    total, base, used = (control[n] for n in ('lifetime_requests', 'day_start_lifetime_requests',
                                            'previous_session_requests'))
    need(base <= total and used <= total-base <= 240 and
         control['lifetime_completed_rounds'] >= control['completed_round'], 'BUDGET_INVALID')
    need(control.get('source_wait') is None and control.get('previous_halted_reason') is None
         and control.get('previous_stop_reason') is None, 'SOURCE_HOLD')


def verify_pending_round(get, run, control, *, now):
    """Authenticate original payloads before deriving a separate repaired control.

    `control` must come from the existing independent final-control reader. Raw
    bytes in this return value are private and must never be logged/published.
    A caller must retain/read back both originals before using this for dispatch.
    """
    from .cycle_recovery import artifact_pages
    need(now.utcoffset() is not None and type(run) is dict and type(control) is dict,
         'INPUT_INVALID')
    need(authenticated_live_owner_run(run) and run.get('head_branch') == OWNER_BRANCH and
         run.get('event') == 'workflow_dispatch' and run.get('status') == 'completed' and
         run.get('conclusion') == 'failure' and type(run.get('run_attempt', 1)) is int and
         run.get('run_attempt', 1) == 1, 'RUN_INVALID')
    ident = run.get('id')
    need(type(ident) is int and ident > 0 and control.get('previous_run_id') == ident and
         type(run.get('head_sha')) is str and re.fullmatch('[a-f0-9]{40}', run['head_sha']),
         'RUN_CONTROL_IDENTITY')
    need(control.get('day_jst') == now.astimezone(JST).date().isoformat(), 'DAY_CHANGED')
    _counts(control)
    start, end = ts(run['created_at']), ts(run['updated_at'])
    need(start <= end <= now, 'RUN_CLOCK_INVALID')
    for name in ('receipt', 'source_control_receipt'):
        receipt = control.get(name)
        need(type(receipt) is dict and type(receipt.get('id')) is int and receipt['id'] > 0
             and re.fullmatch('sha256:[a-f0-9]{64}', str(receipt.get('digest')))
             and start <= ts(receipt['created_at']) <= end, 'CONTROL_RECEIPT_INVALID')
    round_no = control['prepared_round']
    listing = artifact_pages(get, ident)
    selected = []
    for kind, prefix in (('P1', 'boat-national-cutoff'), ('RESULT', 'race-existing-cycle')):
        name = artifact_name(prefix, ident, round_no)
        matches = [m for m in listing if m.get('name') == name]
        need(len(matches) == 1, 'MISSING_OR_DUPLICATE_' + kind)
        artifact_id = matches[0]['id']
        metadata_raw = get(f'actions/artifacts/{artifact_id}')
        need(type(metadata_raw) is bytes and 0 < len(metadata_raw) <= MAX_METADATA, 'METADATA_BOUND')
        metadata = json.loads(metadata_raw)
        need(metadata.get('id') == artifact_id, 'ARTIFACT_ID_CHANGED')
        raw = get(f'actions/artifacts/{artifact_id}/zip')
        _metadata(raw, metadata, name=name, run_id=ident, head_sha=run['head_sha'])
        _artifact(raw, metadata_raw, key=None, now=now, expected_kind=kind)
        need(start <= ts(metadata['created_at']) <= ts(control['receipt']['created_at']),
             'ORIGINAL_CLOCK_INVALID')
        selected.append(dict(raw_zip=raw, metadata_raw=metadata_raw, metadata=metadata))
    p1, result = selected
    need(ts(p1['metadata']['created_at']) <= ts(result['metadata']['created_at']), 'PAIR_CLOCK_INVALID')
    _, rows = read_p1(p1['raw_zip'], p1['metadata'])
    need(all(r['race_id'].startswith(control['day_jst'].replace('-', '')+'-') for r in rows),
         'FOREIGN_RACE_DAY')
    with open_original_zip(result['raw_zip'], result['metadata'], expected_kind='RESULT',
                           max_plain_zip_bytes=32*1024*1024) as bundle:
        need('status.json' in bundle.namelist() and 'current-p1-original.zip' in bundle.namelist(),
             'RESULT_LINK_MISSING')
        need(bundle.getinfo('status.json').file_size <= 16*1024*1024, 'RESULT_REPORT_BOUND')
        report = json.loads(bundle.read('status.json'))
        need(bundle.read('current-p1-original.zip') == p1['raw_zip'], 'NESTED_P1_CHANGED')
    need(report.get('report_sha256') == digest({k:v for k,v in report.items() if k != 'report_sha256'}),
         'RESULT_REPORT_HASH')
    need(report.get('round_no') == round_no and str(report.get('run_id')) == str(ident) and
         report.get('code_sha') == run['head_sha'] and report.get('day_jst') == control['day_jst'],
         'RESULT_SCOPE_INVALID')
    references = [r for r in report.get('first_forecast_artifacts', []) if r.get('id') == p1['metadata']['id']]
    need(len(references) == 1 and all(references[0].get(k) == p1['metadata'].get(k)
         for k in ('id', 'name', 'digest', 'created_at', 'workflow_run')), 'RESULT_P1_RECEIPT_MISMATCH')
    state = report.get('bounded_repeat_session')
    need(type(state) is dict and state.get('day_jst') == control['day_jst'] and state.get('run_id') == ident,
         'RESULT_SESSION_MISSING')
    for field, original in (('requests_used', 'previous_session_requests'),
                            ('completed_round', 'completed_round'), ('prepared_round', 'prepared_round'),
                            ('lifetime_requests', 'lifetime_requests'),
                            ('lifetime_completed_rounds', 'lifetime_completed_rounds'),
                            ('day_start_lifetime_requests', 'day_start_lifetime_requests')):
        need(type(state.get(field)) is int and state[field] == control[original], 'RESULT_COUNTER_MISMATCH')
    need(state.get('source_wait') is None and state.get('halted_reason') is None, 'RESULT_SOURCE_HOLD')
    repaired = deepcopy(control)
    repaired.update(completed_round=round_no, prepared_round=None,
                    lifetime_completed_rounds=control['lifetime_completed_rounds'] + 1)
    repaired['recovery'] = dict(schema=SCHEMA, previous_run_id=ident, round_no=round_no,
        verified_at=now.isoformat(), original_control_receipt=deepcopy(control['receipt']),
        p1_receipt={k:deepcopy(p1['metadata'][k]) for k in ('id','digest','created_at')},
        result_receipt={k:deepcopy(result['metadata'][k]) for k in ('id','digest','created_at')})
    return dict(schema=SCHEMA, control=repaired, originals=selected,
                original_artifact_ids=[v['metadata']['id'] for v in selected],
                replayed_p1_rows=len(rows), new_forecasts=0, official_source_requests=0)

from scripts.boat_failed_recovery_contract import (PROOF_SCHEMA, history_digest, verify_dispatch_proof)


def read_final_control(get, run):
    """Read the public companion and real encrypted sibling, not a success flag."""
    from .cycle_recovery import artifact_pages
    from .boat_source_control import read_summary
    items = artifact_pages(get, run['id'])
    pair = []
    for prefix in ('race-cycle-continuity', 'race-source-control'):
        selected = [m for m in items if m.get('name') == f'{prefix}-{run["id"]}']
        need(len(selected) == 1, 'CHECKPOINT_MISSING_OR_DUPLICATE')
        ident = selected[0]['id']
        meta = json.loads(get(f'actions/artifacts/{ident}'))
        need(meta.get('id') == ident, 'CHECKPOINT_ID_CHANGED')
        pair.append((get(f'actions/artifacts/{ident}/zip'),meta))
    return read_summary(*pair[1], *pair[0], run_id=run['id'], head_sha=run['head_sha'])


def reconcile_restored_state(state, get, *, now):
    """Derive a repaired control from independently decrypted original state.

    No checkpoint/forecast bytes are changed. Restoration must happen before
    the next owner starts a source session; unavailable evidence raises HOLD.
    """
    control = state.get('source_control')
    if not control or control.get('prepared_round') is None:
        return state, None
    # Prior-day originals are not turned into today's inference permission.
    if control.get('day_jst') != state.get('day_jst'):
        return state, None
    run = json.loads(get(f'actions/runs/{control["previous_run_id"]}'))
    public = read_final_control(get, run)
    need(all(public.get(k) == v for k,v in control.items()), 'SEALED_AND_PUBLIC_CONTROL_DISAGREE')
    verified = verify_pending_round(get, run, public, now=now)
    restored = deepcopy(state)
    restored['source_control'] = verified['control']
    return restored, dict(run=run, verified=verified)
