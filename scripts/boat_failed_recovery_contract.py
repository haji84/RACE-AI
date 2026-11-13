"""Internal source-free failed-owner admission contract; no I/O or owner key."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re

JST = timezone(timedelta(hours=9))
OWNER_BRANCH = 'production/boat-p0-p1-20261111'
SCHEMA = 'RACE_AI_PENDING_ROUND_RECOVERY_V1'


def need(ok, reason):
    if not ok: raise ValueError('ROUND_RECOVERY_' + reason)


def ts(value):
    stamp = datetime.fromisoformat(value.replace('Z','+00:00'))
    need(stamp.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    return stamp


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


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

PROOF_SCHEMA = 'RACE_AI_FAILED_OWNER_RECOVERY_PROOF_V1'


def history_digest(runs):
    fields = ('id', 'head_sha', 'head_branch', 'event', 'status', 'conclusion', 'created_at')
    return digest([{k:r.get(k) for k in fields} for r in sorted(runs, key=lambda r:r['id'])])


def verify_dispatch_proof(proof, runs, fresh_control, expected_head, now):
    """Validate a trusted recovery step's output against independently re-read control.

    This is an internal Actions step boundary, not public JSON authentication.
    The runtime creates this proof only after actual AES and vault readback.
    It cannot be supplied through workflow_dispatch or a PR artifact.
    """
    try:
        need(type(proof) is dict and proof.get('schema') == PROOF_SCHEMA and
             proof.get('head_sha') == expected_head and proof.get('day_jst') ==
             now.astimezone(JST).date().isoformat(), 'PROOF_SCOPE')
        need(0 <= (now-ts(proof['verified_at'])).total_seconds() <= 600, 'PROOF_CLOCK')
        need(type(runs) is list and 1 <= len(runs) <= 24 and
             len({r['id'] for r in runs}) == len(runs), 'PROOF_HISTORY')
        need(all(type(r.get('id')) is int and r['id'] > 0 and r.get('head_sha') == expected_head
             and r.get('head_branch') == OWNER_BRANCH and r.get('event') == 'workflow_dispatch'
             and r.get('status') == 'completed' and r.get('conclusion') in ('success','failure')
             for r in runs), 'PROOF_RUN')
        need(proof.get('history_sha256') == history_digest(runs), 'PROOF_HISTORY_CHANGED')
        failed = {r['id'] for r in runs if r['conclusion'] == 'failure'}
        repairs = proof.get('repairs')
        need(type(repairs) is list and len(repairs) == len(failed) and
             {r['run_id'] for r in repairs} == failed and failed, 'PROOF_REPAIRS')
        checked = {}
        for repair in repairs:
            original, fixed = repair['original_control'], repair['control']
            _counts(original)
            need(original.get('previous_run_id') == repair['run_id'] and
                 original.get('day_jst') == proof['day_jst'] and
                 re.fullmatch('[a-f0-9]{40}',str(repair.get('vault_commit'))), 'PROOF_ORIGINAL')
            evidence = fixed['recovery']
            need(evidence.get('schema') == SCHEMA and evidence.get('previous_run_id') == repair['run_id']
                 and evidence.get('round_no') == original['prepared_round'] and
                 evidence.get('original_control_receipt') == original['receipt'], 'PROOF_LINK')
            need(0 <= (now-ts(evidence['verified_at'])).total_seconds() <= 600, 'PROOF_REPAIR_CLOCK')
            references = [evidence['p1_receipt'], evidence['result_receipt']]
            need(repair.get('original_artifact_ids') == [r['id'] for r in references] and
                 len({r['id'] for r in references}) == 2 and
                 all(type(r['id']) is int and r['id'] > 0 and
                     re.fullmatch('sha256:[a-f0-9]{64}',str(r['digest'])) and
                     ts(r['created_at']) <= ts(original['receipt']['created_at'])
                     for r in references), 'PROOF_RECEIPTS')
            expected = deepcopy(original)
            expected.update(completed_round=original['prepared_round'], prepared_round=None,
                            lifetime_completed_rounds=original['lifetime_completed_rounds']+1,
                            recovery=evidence)
            need(expected == fixed, 'PROOF_COUNTER_OR_STATE_CHANGED')
            checked[repair['run_id']] = repair
        latest = max(runs,key=lambda r:ts(r['created_at']))
        if latest['id'] in checked:
            need(checked[latest['id']]['original_control'] == fresh_control, 'PROOF_FRESH_CONTROL_CHANGED')
            final = checked[latest['id']]['control']
        else:
            final = fresh_control
        need(proof.get('latest_control') == final, 'PROOF_LATEST_CONTROL_CHANGED')
        need(all(r['control']['lifetime_requests'] <= final['lifetime_requests'] and
                 r['control']['day_start_lifetime_requests'] == final['day_start_lifetime_requests']
                 for r in checked.values()), 'PROOF_LIFETIME_DECREASED')
        return deepcopy(final)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return None

