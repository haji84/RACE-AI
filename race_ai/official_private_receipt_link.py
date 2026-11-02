"""Read-only evidence join for the Issue #67 four-sport race cohort.

The caller must supply separately authenticated source authorizations, private
readback and the PINNED PR71 GitHub verifier. This module performs no network,
no source or private writes, no inference and no result scoring. A manual
coverage ledger can NEVER become an official all-race denominator through it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import re

SPORTS = frozenset(('boat', 'keirin', 'autorace', 'horse_jra', 'horse_local'))
SHA = re.compile(r'[0-9a-f]{64}\Z')
MAX_WIRE = 4 * 1024 * 1024
REQUIRED_USES = frozenset(('schedule', 'pre_race', 'private_retention'))


class ReceiptLinkError(ValueError):
    pass


def _require(ok, reason):
    if not ok:
        raise ReceiptLinkError(reason)


def _time(value):
    _require(type(value) is str and re.fullmatch(
        r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)', value),
        'INVALID_TIME')
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _require(instant.utcoffset() is not None, 'TIMEZONE_REQUIRED')
        return instant.astimezone(timezone.utc)
    except ValueError:
        raise ReceiptLinkError('INVALID_TIME') from None


def _exact(obj, fields, reason):
    _require(type(obj) is dict and set(obj) == set(fields.split()), reason)


def _validate(bridge, sources, forecasts):
    _require(type(bridge) is dict and bridge.get('schema') ==
             'RACE_AI_FOUR_SPORT_COHORT_BRIDGE_V1' and
             bridge.get('mode') == 'OFFLINE_RESEARCH_COVERAGE_LINK' and
             bridge.get('official_completeness_verified') is False and
             bridge.get('source_rights_verified') is False and
             bridge.get('external_pre_cutoff_receipts_verified') is False and
             bridge.get('formal_hit_at_8_all') is None and
             type(bridge.get('records')) is list and len(bridge['records']) <= 100000,
             'INVALID_UNVERIFIED_COHORT')
    races = {}
    for row in bridge['records']:
        _require(type(row) is dict and type(row.get('sport')) is str and row['sport'] in SPORTS, 'BAD_RACE_ROW')
        key = row.get('race_id')
        _require(type(key) is str and key == f"{row['sport']}:{bridge['event_date_jst']}:{row.get('venue')}:{row.get('race_no')}" and
                 key not in races and type(row.get('race_no')) is int and
                 1 <= row['race_no'] <= 99, 'RACE_ID_COLLISION_OR_MISMATCH')
        races[key] = row
    _require(type(sources) is list and len(sources) <= 100000, 'SOURCE_LIST_BOUND')
    _require(type(forecasts) is list and len(forecasts) <= 100000, 'FORECAST_LIST_BOUND')
    source_map = {}
    for src in sources:
        _exact(src, 'race_id source_id source_sha256 permission_ref published_at observed_at official_cutoff_at', 'SOURCE_FIELDS')
        rid = src['race_id']
        _require(type(rid) is str and rid in races and rid not in source_map, 'SOURCE_IDENTITY_COLLISION')
        _require(type(src['source_id']) is str and 1 <= len(src['source_id']) <= 128 and
                 type(src['permission_ref']) is str and 1 <= len(src['permission_ref']) <= 256 and
                 type(src['source_sha256']) is str and SHA.fullmatch(src['source_sha256']), 'SOURCE_PROVENANCE_INVALID')
        _require(src['published_at'] is not None and
                 _time(src['published_at']) <= _time(src['observed_at']) < _time(src['official_cutoff_at']),
                 'SOURCE_NOT_PRE_CUTOFF')
        source_map[rid] = src
    forecast_map = {}
    for p in forecasts:
        _exact(p, 'race_id model_id model_version stage original_wire_sha256 original_generated_at '
                  'private_persisted_at private_ref cutoff_at github_receipt provenance', 'PRIVATE_BINDING_FIELDS')
        rid = p['race_id']
        key = (rid, p['stage'], p['model_id'])
        _require(type(rid) is str and rid in races and key not in forecast_map and
                 p['provenance'] == 'PROSPECTIVE_PROTECTED_OWNER_ORIGINAL' and
                 p['stage'] in ('P0', 'P1') and
                 all(type(p[k]) is str and 1 <= len(p[k]) <= 200 for k in ('model_id','model_version','private_ref')) and
                 type(p['original_wire_sha256']) is str and SHA.fullmatch(p['original_wire_sha256']),
                 'PRIVATE_IDENTITY_OR_DUPLICATE')
        _require(_time(p['original_generated_at']) <= _time(p['private_persisted_at']) < _time(p['cutoff_at']),
                 'LATE_OR_REORDERED_PRIVATE_FORECAST')
        forecast_map[key] = p
    return races, source_map, forecast_map


def link_protected_receipts(bridge, sources, forecasts, *, source_attestor=None,
                            protected_reader=None, forecast_validator=None,
                            trusted_legacy_verifier=None, github_fetch=None):
    """Bind authorized source evidence to private raw bytes and external receipt.

    All *attestor*, *reader*, *validator*, and GitHub callbacks must be wired to
    independently trusted implementations by a private operator. A supplied
    fixture callback is NOT real provider authorization or protected readback.
    No official KPI is produced, even when all provided callbacks succeed.
    """
    races, source_map, forecast_map = _validate(bridge, sources, forecasts)
    outputs = []
    by_race = {}
    for key, item in forecast_map.items():
        by_race.setdefault(key[0], []).append((key, item))
    for rid, race in sorted(races.items()):
        src = source_map.get(rid)
        jobs = by_race.get(rid, [])
        row = {'race_id':rid, 'sport':race['sport'],
               'research_archive_slots':len(race.get('archive_slots',[])),
               'source_admitted_by_callback':False, 'private_checks':[],
               'unresolved':[]}
        if src is None:
            row['unresolved'].append('NO_INDEPENDENT_SOURCE_SNAPSHOT')
        elif not callable(source_attestor):
            row['unresolved'].append('NO_INDEPENDENT_PERMISSION_OR_CUTOFF_VERIFIER')
        else:
            # A callback MUST bind the same source bytes, rights reference and
            # exact official cutoff. A standalone flag in user JSON cannot pass.
            try:
                cert = source_attestor(dict(src))
            except Exception:
                cert = None
            valid = (type(cert) is dict and set(cert) ==
                     {'race_id','source_sha256','permission_ref','cutoff_at','admitted_uses'} and
                     cert['race_id'] == rid and cert['source_sha256'] == src['source_sha256'] and
                     cert['permission_ref'] == src['permission_ref'] and
                     cert['cutoff_at'] == src['official_cutoff_at'] and
                     type(cert['admitted_uses']) is list and
                     all(type(v) is str for v in cert['admitted_uses']) and
                     len(cert['admitted_uses']) == len(set(cert['admitted_uses'])) and
                     REQUIRED_USES <= set(cert['admitted_uses']))
            if valid:
                row['source_admitted_by_callback'] = True
            else:
                row['unresolved'].append('SOURCE_PERMISSION_AND_CUTOFF_NOT_ATTESTED')
        if not jobs:
            row['unresolved'].append('NO_PROSPECTIVE_PRIVATE_PREDICTION')
        for (key, item) in sorted(jobs):
            entry = {'model_id':item['model_id'], 'model_version':item['model_version'],
                     'stage':item['stage'], 'external_receipt_checked':False,
                     'protected_original_sha_checked':False,
                     'status':'NOT_ADMITTED'}
            row['private_checks'].append(entry)
            if race.get('ledger_no_forecast_reason'):
                entry['status'] = 'ORIGINAL_LEDGER_DECLARED_NO_FORECAST'
                continue
            if not row['source_admitted_by_callback']:
                entry['status'] = 'SOURCE_GATE_BLOCKED'
                continue
            if item['cutoff_at'] != src['official_cutoff_at'] or _time(src['observed_at']) > _time(item['original_generated_at']):
                entry['status'] = 'OFFICIAL_CUTOFF_OR_SOURCE_TIME_MISMATCH'
                continue
            if not callable(protected_reader) or not callable(forecast_validator):
                entry['status'] = 'PRIVATE_READER_OR_VALIDATOR_UNAVAILABLE'
                continue
            try:
                wire = protected_reader(item['private_ref'])
                if (type(wire) is not bytes or not 0 < len(wire) <= MAX_WIRE or
                        sha256(wire).hexdigest() != item['original_wire_sha256']):
                    entry['status'] = 'PROTECTED_ORIGINAL_BYTES_MISMATCH'
                    continue
                checked = forecast_validator(wire, dict(item))
                if (type(checked) is not dict or set(checked) !=
                        {'race_id','model_id','model_version','stage','top8_count','wire_sha256'} or
                        any(checked[k] != item[k] for k in ('race_id','model_id','model_version','stage')) or
                        type(checked['top8_count']) is not int or not 1 <= checked['top8_count'] <= 8 or
                        checked['wire_sha256'] != item['original_wire_sha256']):
                    entry['status'] = 'ORIGINAL_FORECAST_CONTENT_NOT_VALIDATED'
                    continue
                entry['protected_original_sha_checked'] = True
            except Exception:
                entry['status'] = 'PRIVATE_READBACK_OR_VALIDATION_ERROR'
                continue
            if not callable(trusted_legacy_verifier) or not callable(github_fetch):
                entry['status'] = 'EXTERNAL_GITHUB_VERIFIER_UNAVAILABLE'
                continue
            try:
                # This existing adapter binds SHA, cutoff and the exact race ID
                # to a pinned external GitHub run/anchor. No self-signed proof.
                from .race_bound_freeze_receipt import verify_bound_receipt
                verify_bound_receipt(item['github_receipt'], item['original_wire_sha256'],
                                     item['private_persisted_at'], item['cutoff_at'],
                                     expected_race_id=rid,
                                     trusted_legacy_verifier=trusted_legacy_verifier,
                                     github_fetch=github_fetch)
            except Exception:
                entry['status'] = 'GITHUB_RACE_BOUND_RECEIPT_NOT_VERIFIED'
                continue
            entry['external_receipt_checked'] = True
            entry['status'] = 'CALLBACK_BOUND_PROOFS_REQUIRE_INDEPENDENT_OPERATOR_AUDIT'
        outputs.append(row)
    return {'schema':'RACE_AI_SOURCE_PRIVATE_RECEIPT_LINK_V1',
            'scope':'READ_ONLY_UNVERIFIED_COHORT',
            'event_date_jst':bridge['event_date_jst'],
            'records':outputs,
            'source_snapshot_races':len(source_map),
            'private_forecast_records':len(forecast_map),
            'source_admission_claims_checked':sum(r['source_admitted_by_callback'] for r in outputs),
            'external_receipts_checked':sum(p['external_receipt_checked'] for r in outputs for p in r['private_checks']),
            'all_official_races_verified':False, 'official_complete_denominator':None,
            'formal_hit_at_1':None, 'formal_hit_at_8_all':None,
            'formal_capture_rate':None, 'actual_purchase_roi':None,
            'brier':None, 'log_loss':None, 'private_forecasts_mutated':False}
