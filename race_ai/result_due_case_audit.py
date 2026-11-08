"""Encrypted-only reason index for each unresolved BOAT race across every saved day.

Authoritative outstanding bits remain in result_due_ledger. Never export case IDs,
raw observations, tickets, timestamps or credentials in a public run report.
No provider requests, model fitting, plaintext publication or forecast mutation.
"""
import hashlib
import json
import re
from datetime import datetime
from . import result_due_ledger as D

SCHEMA = 'RACE_AI_RESULT_DUE_CASE_REASONS_V1'
STATUS = {'m': 'missing', 'p': 'pending', 'u': 'unsupported'}
MAX_CASES = 100000
MAX_SERIALIZED_BYTES = 12 * 1024 * 1024
REASONS = frozenset({
    'UNSCANNED_SAVED_DAY', 'SAVED_DAY_EVIDENCE_UNAVAILABLE',
    'RESULT_SOURCE_NOT_OBSERVED', 'RESULT_SOURCE_REJECTED',
    'RESULT_NOT_FINAL', 'RESULT_UNSUPPORTED', 'RESULT_REFERENCE_ONLY',
    'MODEL_PRE_CUTOFF_PROOF_MISSING', 'MODEL_RESULT_EVIDENCE_MISSING',
    'MODEL_RESULT_EVIDENCE_MISMATCH', 'MODEL_FORMAL_EVIDENCE_HOLD',
    'MODEL_PDCA_OTHER_HOLD', 'INPUT_REASON_UNVERIFIED',
})


def need(ok, code):
    if not ok:
        raise ValueError('RESULT_DUE_CASE_' + code)


def _sha(data):
    raw = json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest(), len(raw)


def _ids(doc):
    """Expand validated private 24-venue x 12-race day bitsets without age eviction."""
    for day, entry in sorted(doc['pending_days'].items()):
        for name in ('m', 'p', 'u'):
            mask = D._mask(entry[name])
            while mask:
                bit = mask & -mask
                pos = bit.bit_length() - 1
                rid = f'{day.replace("-", "")}-{pos//12+1:02d}-{pos%12+1:02d}'
                yield rid, STATUS[name], entry['first_seen_at']
                mask ^= bit


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return t if t.utcoffset() is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


def _reason(row, status):
    result = row.get('result') or {}
    rejected = row.get('result_observation_rejections') or []
    if status == 'missing':
        return 'RESULT_SOURCE_REJECTED' if rejected else 'RESULT_SOURCE_NOT_OBSERVED'
    if status == 'pending':
        return 'RESULT_SOURCE_REJECTED' if rejected else 'RESULT_NOT_FINAL'
    reference = result.get('cutoff_reconciliation') or {}
    if (result.get('formal_eligible') is False or result.get('cutoff_reference') is not None
        or isinstance(reference, dict) and reference.get('formal_eligible') is False):
        return 'RESULT_REFERENCE_ONLY'
    if D.reconciled_status(row) not in ('final', 'void'):
        return 'RESULT_SOURCE_REJECTED' if rejected else 'RESULT_UNSUPPORTED'
    # A formal physical result may be complete while one or more models are
    # unscorable. The physical result MUST NOT be downloaded again for this.
    candidates = ([row['prediction']] if row.get('prediction') is not None else []) + list(row.get('comparison_predictions') or [])
    for p in candidates:
        if not isinstance(p, dict):
            return 'INPUT_REASON_UNVERIFIED'
        cutoff = _time(p.get('cutoff_at') or row.get('cutoff_at'))
        persisted = _time(p.get('persisted_at') or p.get('server_saved_at'))
        if cutoff is None or persisted is None or persisted >= cutoff:
            return 'MODEL_PRE_CUTOFF_PROOF_MISSING'
    observations = row.get('result_observations') or []
    if not observations:
        return 'MODEL_RESULT_EVIDENCE_MISSING'
    if not any(isinstance(o, dict) and o.get('source_sha256') == result.get('source_sha256')
               and o.get('captured_at') == result.get('observed_at')
               and o.get('body_identity_verified') is True for o in observations):
        return 'MODEL_RESULT_EVIDENCE_MISMATCH'
    return 'MODEL_FORMAL_EVIDENCE_HOLD'


def _validate(previous):
    if previous is None:
        return dict(schema=SCHEMA, cases={}, resolved_total=0, cases_sha256=_sha({})[0])
    need(isinstance(previous, dict) and set(previous) == {'schema','cases','resolved_total','cases_sha256'}
         and previous['schema'] == SCHEMA and type(previous['resolved_total']) is int
         and previous['resolved_total'] >= 0 and isinstance(previous['cases'], dict), 'SCHEMA_INVALID')
    cases = previous['cases']
    need(len(cases) <= MAX_CASES, 'CASE_LIMIT')
    checksum, size = _sha(cases)
    need(size <= MAX_SERIALIZED_BYTES and checksum == previous['cases_sha256'], 'CHECKSUM_INVALID')
    for rid, item in cases.items():
        D._slot(rid)
        need(isinstance(item, dict) and set(item) == {'status','reason','first_seen_at'}
             and item['status'] in STATUS.values() and item['reason'] in REASONS
             and _time(item['first_seen_at']) is not None, 'CASE_INVALID')
    return previous


def record(control, ledger, rows):
    """Update exact per-race private reasons in existing AES control, fail closed."""
    need(isinstance(control, dict) and isinstance(rows, list), 'INPUT_INVALID')
    previous = _validate(control.get('result_due_case_reasons'))
    indexed = {}
    for row in rows:
        if row.get('sport') != 'boat':
            continue
        rid = row.get('race_id')
        D._slot(rid)
        need(rid not in indexed, 'DUPLICATE_RACE')
        indexed[rid] = row
    cases = {}
    for rid, status, first_seen in _ids(ledger):
        need(rid not in cases and len(cases) < MAX_CASES, 'CASE_LIMIT')
        prior = previous['cases'].get(rid)
        if rid in indexed:
            reason = _reason(indexed[rid], status)
        elif prior and prior['status'] == status:
            reason = prior['reason']
        else:
            reason = 'UNSCANNED_SAVED_DAY'
        need(reason in REASONS and _time(first_seen) is not None, 'CASE_INVALID')
        cases[rid] = dict(status=status, reason=reason, first_seen_at=prior['first_seen_at'] if prior else first_seen)
    checksum, size = _sha(cases)
    need(size <= MAX_SERIALIZED_BYTES, 'CAPACITY_HOLD')
    resolved = len(set(previous['cases']) - set(cases))
    control['result_due_case_reasons'] = dict(schema=SCHEMA, cases=cases,
        resolved_total=previous['resolved_total'] + resolved, cases_sha256=checksum)
    return summary(control, ledger)


def summary(control, ledger):
    """Public-safe counts. Validate parity with every outstanding ledger bit."""
    state = _validate(control.get('result_due_case_reasons'))
    required = {rid: status for rid, status, _ in _ids(ledger)}
    need(set(required) == set(state['cases']), 'COVERAGE_MISMATCH')
    counters = {}
    reasons = {}
    for rid, case in state['cases'].items():
        need(case['status'] == required[rid], 'STATUS_MISMATCH')
        counters[case['status']] = counters.get(case['status'], 0) + 1
        reasons[case['reason']] = reasons.get(case['reason'], 0) + 1
    return dict(schema=SCHEMA, outstanding=len(required), status_counts=dict(sorted(counters.items())),
                reason_counts=dict(sorted(reasons.items())), resolved_total=state['resolved_total'],
                unattributed=sum(reasons.get(x,0) for x in ('UNSCANNED_SAVED_DAY','SAVED_DAY_EVIDENCE_UNAVAILABLE','INPUT_REASON_UNVERIFIED')),
                all_cases_accounted_for=True, source_provider_requests=0, actual_purchases=False)

def retained_source_inventory(state, ledger):
    """Count authenticated retained result pages that might be replayed offline.

    This is deliberately a *candidate* inventory, not a formal result label.
    The function only reads the existing encrypted capture store and never
    publishes exact race IDs or observes an online provider.
    """
    original=summary(state.control, ledger)
    cases=_validate(state.control.get('result_due_case_reasons'))['cases']
    pointers=state.control.get('settlement_captures', {})
    need(isinstance(pointers,dict),'CAPTURE_POINTER_MAP_INVALID')
    target={'RESULT_SOURCE_NOT_OBSERVED','RESULT_SOURCE_REJECTED',
            'MODEL_RESULT_EVIDENCE_MISMATCH'}
    by_reason={}
    authenticated=missing=failed=0
    for rid,case in sorted(cases.items()):
        reason=case['reason']
        if reason not in target:
            continue
        bucket=by_reason.setdefault(reason,dict(cases=0,authenticated_retained_bytes=0,
                                                no_retained_capture=0,capture_authentication_hold=0))
        bucket['cases']+=1
        pointer=pointers.get(rid)
        if pointer is None:
            missing+=1;bucket['no_retained_capture']+=1
            continue
        try:
            raw,receipt=state.capture(pointer)
            valid=isinstance(raw,bytes) and isinstance(receipt,dict) and (
                receipt.get('source_sha256') == hashlib.sha256(raw).hexdigest())
            if not valid:raise ValueError('CAPTURE_HASH')
        except (KeyError,TypeError,ValueError):
            failed+=1;bucket['capture_authentication_hold']+=1
        else:
            authenticated+=1;bucket['authenticated_retained_bytes']+=1
    need(sum(v['cases'] for v in by_reason.values())==authenticated+missing+failed,
         'REPLAY_INVENTORY_ACCOUNTING')
    return dict(schema='RACE_AI_RETAINED_SOURCE_REPLAY_INVENTORY_V1',
                outstanding=original['outstanding'],replay_candidate_cases=authenticated+missing+failed,
                authenticated_retained_bytes=authenticated,
                no_retained_capture=missing,capture_authentication_hold=failed,
                by_reason=dict(sorted(by_reason.items())),
                requires_formal_source_validation=True,
                cases_auto_resolved=0,source_provider_requests=0,actual_purchases=False)
