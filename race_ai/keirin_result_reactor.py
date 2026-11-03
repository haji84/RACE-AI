"""Result-triggered, research-only KEIRIN PDCA -> next-forecast outbox adapter.

This module NEVER fetches a provider, grants source use rights, signs a real
provider receipt, scores formal Hit@8, writes a prediction, or places a bet.
On each genuinely authorized result-delivery event, a trusted private runtime
can supply authentication/readback/append-only queue callbacks. The callbacks
MUST verify their own authority; a mock callback is never legal permission.

The output contract is suitable for a separate approved forecast worker. That
worker must independently re-check source grants, official cutoff and immutable
forecast storage before it performs any prediction or freezes its receipt.
"""
from __future__ import annotations

from datetime import date, timedelta, timezone
from hashlib import sha256
import re

from .keirin_result_delivery import (
    BATCH, SCOPE, KeirinDeliveryError, canonical, digest, research_hit8, utc,
)

JST = timezone(timedelta(hours=9))
SHA = re.compile(r"^[0-9a-f]{64}$")
RID = re.compile(r"^keirin:(\d{4}-\d{2}-\d{2}):([a-z0-9_-]{2,40}):([1-9]\d?)$")
REQUIRED_RESULT_USES = {'result_collection', 'result_analysis'}
REQUIRED_PRE_RACE_USES = {'schedule', 'pre_race', 'private_retention'}


class ReactorError(KeirinDeliveryError):
    pass


def _ensure(ok, reason):
    if not ok:
        raise ReactorError(reason)


def _valid_id(value):
    _ensure(type(value) is str and RID.fullmatch(value) is not None,
            'INVALID_KEIRIN_RACE_ID')
    match = RID.fullmatch(value)
    try:
        d = date.fromisoformat(match.group(1))
    except ValueError:
        raise ReactorError('INVALID_KEIRIN_RACE_DATE') from None
    return d


def _safe_callback(callback, *args):
    if not callable(callback):
        return None
    try:
        return callback(*args)
    except Exception:
        # A failed rights/readback/storage check fails closed. No raw source,
        # private forecast or exception text leaks into the public report.
        return None


def _is_sha(v):
    return type(v) is str and SHA.fullmatch(v) is not None


def _verified_result(obs, authenticate_result):
    fingerprint = digest(obs)
    receipt = _safe_callback(authenticate_result, obs, fingerprint)
    return (type(receipt) is dict and
            set(receipt) == {'race_id','observation_sha256','provider_receipt_sha256',
                             'verified_purposes'} and
            receipt['race_id'] == obs['race_id'] and
            receipt['observation_sha256'] == fingerprint and
            _is_sha(receipt['provider_receipt_sha256']) and
            type(receipt['verified_purposes']) is list and
            all(type(p) is str for p in receipt['verified_purposes']) and
            len(receipt['verified_purposes']) == len(set(receipt['verified_purposes'])) and
            REQUIRED_RESULT_USES <= set(receipt['verified_purposes']))


def _verified_next(row, verify_next, now, margin):
    cert = _safe_callback(verify_next, row)
    if type(cert) is not dict or set(cert) != {
        'race_id','official_cutoff_at','pre_race_snapshot_sha256',
        'snapshot_captured_at','permission_ref','verified_purposes'}:
        return None
    if cert['race_id'] != row['race_id'] or cert['official_cutoff_at'] != row['official_cutoff_at']:
        return None
    if (not _is_sha(cert['pre_race_snapshot_sha256']) or
            type(cert['permission_ref']) is not str or not cert['permission_ref'] or
            type(cert['verified_purposes']) is not list or
            not all(type(p) is str for p in cert['verified_purposes']) or
            len(set(cert['verified_purposes'])) != len(cert['verified_purposes']) or
            not REQUIRED_PRE_RACE_USES <= set(cert['verified_purposes'])):
        return None
    try:
        snapshot_at = utc(cert['snapshot_captured_at'])
        cutoff = utc(cert['official_cutoff_at'])
    except (ValueError, TypeError):
        return None
    return cert if snapshot_at <= now < cutoff - margin and snapshot_at < cutoff else None


def react_to_result_delivery(batch, future_races, *, now, forecast_reference,
                             authenticate_result=None, verify_next=None,
                             frozen_readback=None, enqueue_once=None,
                             enqueue_readback=None, margin_seconds=60, max_jobs=8):
    """Audit a new batch; enqueue remaining races only after independent gates.

    This does not run a model or write forecasts. enqueue_once must be an
    authenticated atomic create-only private writer with post-write readback.
    No result event / no independently authenticated result => no new job.
    """
    _ensure(type(margin_seconds) is int and 1 <= margin_seconds <= 3600 and
            type(max_jobs) is int and 1 <= max_jobs <= 100,
            'INVALID_SAFETY_BOUNDS')
    _ensure(type(batch) is dict and batch.get('schema') == BATCH and
            batch.get('scope') == SCOPE and type(batch.get('observations')) is list and
            type(batch.get('event_date_jst')) is str,
            'UNTRUSTED_RESULT_BATCH')
    _ensure(type(future_races) is list and len(future_races) <= 10000,
            'FUTURE_LEDGER_BOUNDS')
    try:
        at = utc(now)
        day = date.fromisoformat(batch['event_date_jst'])
        _ensure(day.isoformat() == batch['event_date_jst'], 'INVALID_RESULT_DAY')
    except ValueError:
        raise ReactorError('INVALID_TIME_OR_RESULT_DAY') from None
    settled = []
    for obs in batch['observations']:
        _ensure(type(obs) is dict and _valid_id(obs.get('race_id')) == day and
                obs.get('status') in {'FINAL_NORMAL','PENDING','CANCELLED',
                      'NOT_OFFERED','SOURCE_UNAVAILABLE','CUTOFF_MISMATCH',
                      'UNSUPPORTED_SPECIAL'}, 'INVALID_RESULT_EVENT')
        _ensure(utc(obs['observed_at']) <= at, 'FUTURE_RESULT_OBSERVATION')
        if obs['status'] == 'FINAL_NORMAL' and obs.get('refund_status') == 'NONE':
            settled.append(obs)
    # A caller-supplied forecast map is not an externally validated receipt.
    score = research_hit8(batch, forecast_reference)
    authenticated = [o for o in settled if _verified_result(o, authenticate_result)]
    result_ids = [o['race_id'] for o in authenticated]
    summary = {
        'schema': 'RACE_AI_KEIRIN_RESULT_TRIGGER_V1',
        'mode': 'RESEARCH_ONLY_NOT_OFFICIAL',
        'as_of': at.isoformat(),
        'result_events_received': len(batch['observations']),
        'simple_final_events': len(set(o['race_id'] for o in settled)),
        'independently_attested_events_by_callback': len(set(result_ids)),
        'reference_hit8': score,
        'formal_hit_at_8_all': None,
        'queue': [], 'forecast_generated': False,
        'external_prediction_receipts_verified': False,
    }
    if not authenticated:
        summary['dispatch_state'] = 'NO_VERIFIED_FINAL_RESULT_EVENT'
        return summary
    source_event_sha = digest(sorted((o['race_id'], digest(o)) for o in authenticated))
    seen = set()
    candidates = []
    for row in future_races:
        _ensure(type(row) is dict and set(row) ==
                {'race_id','official_cutoff_at'}, 'INVALID_FUTURE_RACE_FIELDS')
        rid = row['race_id']
        target_day = _valid_id(rid)
        _ensure(rid not in seen, 'DUPLICATE_FUTURE_RACE')
        seen.add(rid)
        cutoff = utc(row['official_cutoff_at'])
        _ensure(cutoff.astimezone(JST).date() == target_day,
                'NEXT_CUTOFF_RACE_DATE_MISMATCH')
        candidates.append((cutoff, rid, row))
    candidates.sort(key=lambda t: (t[0], t[1]))
    margin = timedelta(seconds=margin_seconds)
    queued = 0
    for cutoff, rid, row in candidates:
        status = {'race_id':rid, 'cutoff_at':row['official_cutoff_at'],
                  'state':'NOT_QUEUED'}
        if cutoff <= at + margin:
            status['state'] = 'CUTOFF_TOO_CLOSE_OR_PASSED'
        elif queued >= max_jobs:
            status['state'] = 'DAILY_QUEUE_BUDGET_DEFERRED'
        else:
            cert = _verified_next(row, verify_next, at, margin)
            if cert is None:
                status['state'] = 'PRE_RACE_AUTHORITY_OR_SNAPSHOT_UNVERIFIED'
            else:
                frozen = _safe_callback(frozen_readback, rid)
                if frozen != {'race_id':rid, 'state':'ABSENT_VERIFIED_BY_OWNER'}:
                    status['state'] = 'FROZEN_OR_PRIVATE_READBACK_UNVERIFIED'
                else:
                    key = sha256(canonical({
                        'race_id':rid,
                        'official_cutoff_at':row['official_cutoff_at'],
                        'job_kind':'KEIRIN_NEXT_FORECAST_V1',
                    })).hexdigest()
                    intent = {
                        'schema':'RACE_AI_KEIRIN_NEXT_FORECAST_INTENT_V1',
                        'idempotency_key':key,
                        'trigger_source_event_sha256':source_event_sha,
                        'race_id':rid,
                        'official_cutoff_at':row['official_cutoff_at'],
                        'pre_race_snapshot_sha256':cert['pre_race_snapshot_sha256'],
                        'pre_race_snapshot_at':cert['snapshot_captured_at'],
                        'permission_ref':cert['permission_ref'],
                        'max_trifecta_picks':8,
                        'prediction_generated':False,
                    }
                    ack = _safe_callback(enqueue_once, dict(intent))
                    if (ack == {'idempotency_key':key,'state':'CREATED_OR_EXISTS'} and
                            _safe_callback(enqueue_readback, key) == intent):
                        status['state'] = 'DURABLY_QUEUED_FOR_APPROVED_MODEL'
                        status['idempotency_key'] = key
                        queued += 1
                    else:
                        status['state'] = 'OUTBOX_WRITE_OR_READBACK_UNCERTAIN_NO_RETRY'
        summary['queue'].append(status)
    summary['dispatch_state'] = 'QUEUED' if queued else 'NO_DURABLY_QUEUED_JOB'
    summary['queued_count'] = queued
    return summary
