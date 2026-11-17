"""Internal source-free failed-owner admission contract; no I/O or owner key."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re

JST = timezone(timedelta(hours=9))
OWNER_BRANCH = 'production/boat-p0-p1-20261111'
SCHEMA = 'RACE_AI_PENDING_ROUND_RECOVERY_V1'
REVIEWED_PREVIOUS_OWNER_SHAS = frozenset({
    '84128e0ec8bd9fe3da64ad49f74b8511b07e72be',
    # Exact immutable worker retained through the next protected release.
    # This admits original/control readback, never dispatch of an old source.
    'b491fb21ce58ba085dd8f54bb7326442b840d8f4',
    # Exact pre-storage-repair release: original readback only, never dispatch.
    'c123b8538006b3189181195bbc91d8f28d216ba5',
    # Exact pre-batch/video release: checkpoint/original readback only.
    # Recovery still executes and emits proofs bound to the new expected head.
    'eff296f6d54ad4be297d93e32f1ee0d4592ad9e3',
    # Actual M2 worker originals/control remain readable by the next release.
    # Old checkout/proof never authorizes recovery or dispatch of that release.
    '86b029ae5bddd5d4956497d8b32b2c92b8eec521',
    # Reviewed profile release: historical original/control readback only.
    # Recovery checkout and its proof must still match the new expected head.
    'f55351dce855177a51330f72c37d6238ba2c9e3e',
    # Historical retention release only; checkout/proof still use current head.
    'bb49215034b779ea1493b35dd91e5c3ebfc04032',
})


def need(ok, reason):
    if not ok: raise ValueError('ROUND_RECOVERY_' + reason)


def ts(value):
    stamp = datetime.fromisoformat(value.replace('Z','+00:00'))
    need(stamp.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    return stamp


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def reviewed_recovery_origin(head, expected_head):
    """Exact current release or explicitly reviewed original; never ancestry."""
    return (type(head) is str and type(expected_head) is str and
            re.fullmatch('[a-f0-9]{40}',expected_head) is not None and
            (head==expected_head or head in REVIEWED_PREVIOUS_OWNER_SHAS))


def _counts(control):
    names = ('completed_round', 'prepared_round', 'previous_session_requests',
             'lifetime_requests', 'lifetime_completed_rounds', 'day_start_lifetime_requests')
    need(all(type(control.get(n)) is int and control[n] >= 0 for n in names), 'COUNTERS_INVALID')
    need(control['prepared_round'] >= 1 and
         control['prepared_round'] == control['completed_round'] + 1, 'ROUND_ORDER_INVALID')
    total, base, used = (control[n] for n in ('lifetime_requests', 'day_start_lifetime_requests',
                                            'previous_session_requests'))
    need(base <= total and used <= total-base and
         control['lifetime_completed_rounds'] >= control['completed_round'], 'BUDGET_INVALID')
    need(control.get('source_wait') is None and control.get('previous_halted_reason') is None
         and control.get('previous_stop_reason') is None, 'SOURCE_HOLD')

IDLE_SCHEMA = 'RACE_AI_NO_PENDING_FAILED_OWNER_V1'
BOOTSTRAP_SCHEMA = 'RACE_AI_SAVED_BOOTSTRAP_FAILED_OWNER_V1'
ORPHAN_SCHEMA = 'RACE_AI_ORPHAN_P1_ABANDONMENT_V1'
ORPHAN_EVIDENCE_FIELDS = frozenset(('schema','previous_run_id','round_no','verified_at',
    'original_control_receipt','original_control','p1_receipt','continuity_receipt',
    'source_control_receipt','checkpoint_AES_authenticated','public_control_matches_AES',
    'missing_result_inventory_verified','first_receipt_union_verified',
    'completed_round_advanced','originals_rewritten'))
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
        need(all(type(r.get('id')) is int and r['id'] > 0 and reviewed_recovery_origin(r.get('head_sha'),expected_head)
             and r.get('head_branch') == OWNER_BRANCH and r.get('event') == 'workflow_dispatch'
             and r.get('status') == 'completed' and r.get('conclusion') in ('success','failure')
             for r in runs), 'PROOF_RUN')
        need(proof.get('history_sha256') == history_digest(runs), 'PROOF_HISTORY_CHANGED')
        failed = {r['id'] for r in runs if r['conclusion'] == 'failure'}
        repairs = proof.get('repairs')
        need(type(repairs) is list and len(repairs) == len(failed) and
             {r['run_id'] for r in repairs} == failed and failed, 'PROOF_REPAIRS')
        checked = {}
        origins={r['id']:r['head_sha'] for r in runs}
        run_details={r['id']:r for r in runs}
        for repair in repairs:
            original, fixed = repair['original_control'], repair['control']
            need(original.get('previous_run_id') == repair['run_id'] and
                 original.get('day_jst') == proof['day_jst'], 'PROOF_ORIGINAL_IDENTITY')
            if origins[repair['run_id']]!=expected_head:
                need(repair.get('original_head_sha')==origins[repair['run_id']],
                     'PROOF_REVIEWED_ORIGIN_MISSING')
            evidence = fixed['recovery']
            need(evidence.get('previous_run_id') == repair['run_id'] and
                 evidence.get('original_control_receipt') == original['receipt'], 'PROOF_LINK')
            need(0 <= (now-ts(evidence['verified_at'])).total_seconds() <= 600, 'PROOF_REPAIR_CLOCK')
            expected = deepcopy(original)
            if original.get('prepared_round') is None:
                names=('completed_round','previous_session_requests','lifetime_requests',
                       'lifetime_completed_rounds','day_start_lifetime_requests')
                need(all(type(original.get(k)) is int and original[k]>=0 for k in names)
                     and original['completed_round']==0
                     and original['previous_session_requests'] in (0,1)
                     and original['previous_session_requests']<=original['lifetime_requests']-original['day_start_lifetime_requests']
                     and original['day_start_lifetime_requests']<=original['lifetime_requests']
                     and original.get('source_wait') is None
                     and original.get('previous_halted_reason') is None
                     and original.get('previous_stop_reason') is None, 'PROOF_IDLE_SOURCE_UNVERIFIED')
                need(evidence.get('round_no') is None
                     and evidence.get('no_p1_or_result_artifacts_verified') is True
                     and evidence.get('no_future_forecast_generated') is True
                     and evidence.get('originals_rewritten') is False,'PROOF_IDLE_MISMATCH')
                if original['previous_session_requests']==0:
                    need(evidence.get('schema')==IDLE_SCHEMA and evidence.get('source_attempts')==0
                         and repair.get('original_artifact_ids')==[] and repair.get('vault_commit') is None,
                         'PROOF_IDLE_MISMATCH')
                else:
                    need(evidence.get('schema')==BOOTSTRAP_SCHEMA and type(evidence.get('source_attempts')) is int
                         and evidence['source_attempts']==1 and
                         re.fullmatch('[a-f0-9]{40}',str(repair.get('vault_commit'))) and
                         all(evidence.get(k) is True for k in ('checkpoint_AES_authenticated',
                             'public_control_matches_AES','first_receipt_union_verified')),
                         'PROOF_BOOTSTRAP_AUTHENTICATION_REQUIRED')
                    references=[evidence['p0_receipt'],evidence['continuity_receipt'],evidence['source_control_receipt']]
                    need(references[1]==original['receipt'] and references[2]==original['source_control_receipt'] and
                         repair.get('original_artifact_ids')==[r['id'] for r in references] and
                         len({r['id'] for r in references})==3 and all(type(r['id']) is int and r['id']>0 and
                             re.fullmatch('sha256:[a-f0-9]{64}',str(r['digest'])) for r in references) and
                         ts(run_details[repair['run_id']]['created_at'])<=ts(references[0]['created_at'])<=
                             ts(references[1]['created_at'])<=ts(references[2]['created_at'])<=now,
                         'PROOF_BOOTSTRAP_RECEIPTS_CHANGED')
                expected['recovery']=evidence
            elif evidence.get('schema')==ORPHAN_SCHEMA:
                _counts(original)
                need(set(evidence)==ORPHAN_EVIDENCE_FIELDS and
                     repair.get('original_head_sha')==origins[repair['run_id']] and
                     type(run_details[repair['run_id']].get('run_attempt')) is int and
                     run_details[repair['run_id']]['run_attempt']==1,
                     'PROOF_ORPHAN_ORIGIN_UNVERIFIED')
                need(re.fullmatch('[a-f0-9]{40}',str(repair.get('vault_commit'))),
                     'PROOF_ORPHAN_VAULT_REQUIRED')
                need(evidence.get('round_no')==original['prepared_round'] and
                     evidence.get('original_control')==original and
                     evidence.get('continuity_receipt')==original['receipt'] and
                     evidence.get('source_control_receipt')==original['source_control_receipt'],
                     'PROOF_ORPHAN_CHECKPOINT_CHANGED')
                need(all(evidence.get(k) is True for k in (
                     'checkpoint_AES_authenticated','public_control_matches_AES',
                     'missing_result_inventory_verified','first_receipt_union_verified')) and
                     evidence.get('completed_round_advanced') is False and
                     evidence.get('originals_rewritten') is False,
                     'PROOF_ORPHAN_AUTHENTICATION_MISSING')
                references=[evidence['p1_receipt'],evidence['continuity_receipt'],
                            evidence['source_control_receipt']]
                need(repair.get('original_artifact_ids')==[r['id'] for r in references] and
                     len({r['id'] for r in references})==3 and all(
                     type(r['id']) is int and r['id']>0 and
                     re.fullmatch('sha256:[a-f0-9]{64}',str(r['digest'])) and
                     ts(r['created_at'])<=ts(original['source_control_receipt']['created_at'])
                     for r in references) and
                     ts(references[0]['created_at'])<=ts(original['receipt']['created_at']),
                     'PROOF_ORPHAN_RECEIPTS_CHANGED')
                expected.update(prepared_round=None,recovery=evidence)
            else:
                _counts(original)
                need(re.fullmatch('[a-f0-9]{40}',str(repair.get('vault_commit'))),
                     'PROOF_ORIGINAL')
                need(evidence.get('schema') == SCHEMA and
                     evidence.get('round_no') == original['prepared_round'], 'PROOF_ROUND')
                references = [evidence['p1_receipt'], evidence['result_receipt']]
                need(repair.get('original_artifact_ids') == [r['id'] for r in references] and
                     len({r['id'] for r in references}) == 2 and
                     all(type(r['id']) is int and r['id'] > 0 and
                         re.fullmatch('sha256:[a-f0-9]{64}',str(r['digest'])) and
                         ts(r['created_at']) <= ts(original['receipt']['created_at'])
                         for r in references), 'PROOF_RECEIPTS')
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

