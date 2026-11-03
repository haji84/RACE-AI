"""Private-owner KEIRIN next-forecast consumer, with no provider I/O.

This module connects an independently authenticated result-trigger outbox
intent to a delegated pre-race model and an atomic private freeze store.
All callbacks must be real trusted owner services in production. Mocked
callbacks prove *only* synthetic behavior, never a real external receipt.
No automatic official result fetching, polling, GitHub writing or wagering.
"""
from __future__ import annotations

from datetime import timedelta, timezone
from hashlib import sha256
import json
import re

from .keirin_result_delivery import canonical, utc
from .keirin_result_reactor import _valid_id

SHA = re.compile(r"^[0-9a-f]{64}$")
INTENT_FIELDS = frozenset({
    'schema','idempotency_key','trigger_source_event_sha256','race_id',
    'official_cutoff_at','pre_race_snapshot_sha256','pre_race_snapshot_at',
    'permission_ref','max_trifecta_picks','prediction_generated',
})
USES = frozenset({'schedule','pre_race','private_retention','model_inference'})
BANNED_KEYS = frozenset((
    'odds','popularity','betting','payout','payouts','refund','result',
    'results','winning_triple','finish_order','race_outcome','final_rank',
))


class OwnerForecastError(ValueError):
    pass


def _require(test, reason):
    if not test:
        raise OwnerForecastError(reason)


def _oksha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def _safe(cb, *args):
    if not callable(cb):
        return None
    try:
        return cb(*args)
    except Exception:
        # Sensitive upstream errors never enter owner/public audit output.
        return None


def _no_market_features(node):
    if type(node) is dict:
        _require(not (set(node) & BANNED_KEYS), 'MARKET_OR_OUTCOME_DATA_FORBIDDEN')
        for v in node.values():
            _no_market_features(v)
    elif type(node) is list:
        _require(len(node) <= 4096, 'FEATURE_ARRAY_TOO_LARGE')
        for v in node:
            _no_market_features(v)


def _validate_intent(intent):
    _require(type(intent) is dict and set(intent) == INTENT_FIELDS and
             intent['schema'] == 'RACE_AI_KEIRIN_NEXT_FORECAST_INTENT_V1' and
             intent['prediction_generated'] is False and
             intent['max_trifecta_picks'] == 8, 'INVALID_OUTBOX_INTENT')
    rid = intent['race_id']
    race_day = _valid_id(rid)
    cutoff = utc(intent['official_cutoff_at'])
    _require(cutoff.astimezone(timezone(timedelta(hours=9))).date() == race_day,
             'CUTOFF_DAY_MISMATCH')
    _require(_oksha(intent['pre_race_snapshot_sha256']) and
             _oksha(intent['trigger_source_event_sha256']) and
             _oksha(intent['idempotency_key']) and
             type(intent['permission_ref']) is str and
             1 <= len(intent['permission_ref']) <= 256,
             'INVALID_INTENT_BINDING')
    expected = sha256(canonical({
        'race_id':rid,
        'official_cutoff_at':intent['official_cutoff_at'],
        'job_kind':'KEIRIN_NEXT_FORECAST_V1',
    })).hexdigest()
    _require(intent['idempotency_key'] == expected, 'OUTBOX_KEY_MISMATCH')
    return rid, cutoff


def _verify_source(snapshot, intent, at, cutoff, cert):
    _require(type(snapshot) is dict and
             set(snapshot) == {'schema','race_id','as_of','starters','facts',
                               'permission_ref','official_cutoff_at'} and
             snapshot['schema'] == 'RACE_AI_KEIRIN_PRIVATE_PRE_RACE_V1' and
             snapshot['race_id'] == intent['race_id'] and
             snapshot['official_cutoff_at'] == intent['official_cutoff_at'] and
             snapshot['permission_ref'] == intent['permission_ref'],
             'UNTRUSTED_OR_INCOMPLETE_PRE_RACE_SOURCE')
    _no_market_features(snapshot['facts'])
    starters = snapshot['starters']
    _require(type(starters) is list and 3 <= len(starters) <= 9 and
             all(type(n) is int and 1 <= n <= 9 for n in starters) and
             len(set(starters)) == len(starters),
             'INVALID_STARTER_LIST')
    _require(type(snapshot['facts']) is dict and snapshot['facts'],
             'MISSING_MODEL_FEATURES')
    source_hash = sha256(canonical(snapshot)).hexdigest()
    _require(source_hash == intent['pre_race_snapshot_sha256'], 'SNAPSHOT_SHA_MISMATCH')
    stamp = utc(snapshot['as_of'])
    _require(stamp == utc(intent['pre_race_snapshot_at']) and
             stamp <= at < cutoff, 'PRE_RACE_TIME_MISMATCH')
    _require(type(cert) is dict and set(cert) == {
        'race_id','source_sha256','permission_ref','official_cutoff_at',
        'verified_purposes','valid_until'} and
        cert['race_id'] == intent['race_id'] and
        cert['source_sha256'] == source_hash and
        cert['permission_ref'] == intent['permission_ref'] and
        cert['official_cutoff_at'] == intent['official_cutoff_at'] and
        type(cert['verified_purposes']) is list and
        all(type(p) is str for p in cert['verified_purposes']) and
        len(set(cert['verified_purposes'])) == len(cert['verified_purposes']) and
        USES <= set(cert['verified_purposes']) and
        utc(cert['valid_until']) >= at, 'SOURCE_AUTHORIZATION_UNVERIFIED')
    return source_hash, starters


def _validate_model(prediction, intent, starters, snapshot_sha, cutoff, now):
    _require(type(prediction) is dict and set(prediction) == {
        'race_id','model_id','model_version','generated_at',
        'trained_until','snapshot_sha256','top8'}, 'INVALID_MODEL_OUTPUT')
    _require(prediction['race_id'] == intent['race_id'] and
             prediction['snapshot_sha256'] == snapshot_sha and
             type(prediction['model_id']) is str and
             1 <= len(prediction['model_id']) <= 128 and
             type(prediction['model_version']) is str and
             1 <= len(prediction['model_version']) <= 128,
             'MODEL_BINDING_MISMATCH')
    generated = utc(prediction['generated_at'])
    _require(utc(intent['pre_race_snapshot_at']) <= generated <= now < cutoff and
             utc(prediction['trained_until']) < generated,
             'MODEL_TIME_AFTER_CUTOFF')
    top8 = prediction['top8']
    _require(type(top8) is list and len(top8) == 8,
             'EXACTLY_EIGHT_PICKS_REQUIRED')
    tickets = []
    for p in top8:
        _require(type(p) is list and len(p) == 3 and
                 all(type(n) is int and n in starters for n in p) and
                 len(set(p)) == 3, 'INVALID_TRIFECTA')
        tickets.append(tuple(p))
    _require(len(set(tickets)) == 8, 'DUPLICATE_TRIFECTA')
    return tickets


def consume_next_intent(intent, *, clock, read_queued_intent, read_snapshot,
                        attest_source, frozen_status, model_forecast,
                        atomic_freeze, freeze_readback,
                        independent_receipt_check,
                        margin_seconds=60):
    """Run one guarded attempt. Never retry an uncertain private-store write.

    The private callbacks provide the actual source grant, model and durable
    store. Without ALL trusted callbacks, nothing gets predicted or persisted.
    """
    rid, cutoff = _validate_intent(intent)
    _require(type(margin_seconds) is int and 1 <= margin_seconds <= 900,
             'INVALID_DEADLINE_MARGIN')
    margin = timedelta(seconds=margin_seconds)
    report = {
        'schema':'RACE_AI_KEIRIN_NEXT_FORECAST_WORKER_V1',
        'race_id':rid,'mode':'OWNER_PRIVATE_RESEARCH_BOUNDARY',
        'model_called':False,'forecast_durably_saved':False,
        'independent_receipt_accepted_by_callback':False,
        'formal_hit_at_8_all':None, 'live_autorun_enabled':False,
    }

    def stop(reason):
        return {**report, 'state':reason}

    first = utc(_safe(clock))
    if first + margin >= cutoff:
        return stop('CUTOFF_TOO_CLOSE_OR_PASSED')
    if _safe(read_queued_intent, intent['idempotency_key']) != intent:
        return stop('PRIVATE_OUTBOX_READBACK_MISSING')
    if _safe(frozen_status, rid) != {
            'race_id':rid, 'state':'ABSENT_VERIFIED_BY_OWNER'}:
        return stop('EXISTING_OR_UNVERIFIED_FORECAST')

    snapshot = _safe(read_snapshot, intent)
    cert = _safe(attest_source, snapshot, intent)
    try:
        source_sha, starters = _verify_source(snapshot,intent,first,cutoff,cert)
    except (OwnerForecastError, TypeError, ValueError, AttributeError):
        return stop('PRE_RACE_SOURCE_RIGHTS_OR_HASH_UNVERIFIED')

    if not callable(model_forecast):
        return stop('MODEL_RUNTIME_NOT_CONNECTED')
    forecast = _safe(model_forecast, snapshot)
    report['model_called'] = True
    if forecast is None:
        return stop('MODEL_RUNTIME_FAILED')
    second = utc(_safe(clock))
    if second + margin >= cutoff:
        return stop('MODEL_MISSED_CUTOFF')
    try:
        _validate_model(forecast,intent,starters,source_sha,cutoff,second)
    except (OwnerForecastError, TypeError, ValueError, AttributeError):
        return stop('MODEL_OUTPUT_REJECTED')

    record = {
        'schema':'RACE_AI_KEIRIN_PRIVATE_TOP8_V1',
        'race_id':rid, 'model_id':forecast['model_id'],
        'model_version':forecast['model_version'],
        'trained_until':forecast['trained_until'],
        'generated_at':forecast['generated_at'],
        'official_cutoff_at':intent['official_cutoff_at'],
        'snapshot_sha256':source_sha,
        'source_permission_ref':intent['permission_ref'],
        'trigger_event_sha256':intent['trigger_source_event_sha256'],
        'outbox_idempotency_key':intent['idempotency_key'],
        'top8':forecast['top8'],
        'calibrated_probabilities_verified':False,
        'officially_frozen':False,
    }
    digest = sha256(canonical(record)).hexdigest()
    if _safe(frozen_status, rid) != {
            'race_id':rid, 'state':'ABSENT_VERIFIED_BY_OWNER'}:
        return stop('FORECAST_STATE_CHANGED_BEFORE_WRITE')
    # If write or receipt readback is uncertain, fail closed without retry.
    ack = _safe(atomic_freeze, record, digest)
    if ack != {'race_id':rid,'forecast_sha256':digest,'state':'CREATED_ONCE'}:
        return stop('PRIVATE_FREEZE_WRITE_UNCERTAIN_NO_RETRY')
    if _safe(freeze_readback,rid,digest) != record:
        return stop('PRIVATE_FREEZE_READBACK_MISMATCH_NO_RETRY')

    report['forecast_durably_saved'] = True
    report['model_id'] = forecast['model_id']
    report['forecast_sha256'] = digest
    receipt = _safe(independent_receipt_check, record, digest)
    allowed = (type(receipt) is dict and set(receipt) == {
        'race_id','forecast_sha256','trusted_persisted_at','external_witness'}
        and receipt['race_id']==rid and receipt['forecast_sha256']==digest
        and type(receipt['external_witness']) is str and
        bool(receipt['external_witness']))
    if allowed:
        try:
            persisted=utc(receipt['trusted_persisted_at'])
            allowed=(utc(record['generated_at']) <= persisted < cutoff)
        except (ValueError,TypeError,AttributeError):
            allowed=False
    if not allowed:
        return stop('EXTERNAL_PRE_CUTOFF_RECEIPT_UNVERIFIED')
    report['independent_receipt_accepted_by_callback'] = True
    report['state']='PRIVATE_RESEARCH_FORECAST_SAVED_REQUIRES_REAL_WITNESS_AUDIT'
    return report
