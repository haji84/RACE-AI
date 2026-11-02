"""Read-only race-identity join of manual discovery, audit ledger and frozen archives.

This is NOT a real forecasting, source acquisition, provider-rights or formal
Hit@8 gate. Existing archives are never rewritten or promoted by this join.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
import re

from .discovery_audit_cli import audit
from .discovery_reconcile import CoverageError, SPORTS
from .evaluation_experiment import verify_seal

_REAL_SPORT = {'boat': 'boat', 'keirin': 'keirin', 'autorace': 'autorace'}
_RETAINED_ID = re.compile(r'(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])\Z')


def _key(sport, day, venue, number):
    if (sport not in SPORTS or type(day) is not str or type(venue) is not str or
            not venue.strip() or type(number) is not int or not 1 <= number <= 99):
        raise CoverageError('INVALID_PHYSICAL_RACE_IDENTITY')
    return sport, day, venue, number


def _retained_key(race_id):
    if type(race_id) is not str:
        raise CoverageError('INVALID_RETAINED_RACE_ID')
    match = _RETAINED_ID.fullmatch(race_id)
    if not match:
        raise CoverageError('INVALID_RETAINED_RACE_ID')
    try:
        event_day = date.fromisoformat(f'{race_id[:4]}-{race_id[4:6]}-{race_id[6:8]}').isoformat()
    except ValueError as exc:
        raise CoverageError('INVALID_RETAINED_DATE') from exc
    return _key('boat', event_day, 'boatrace-jcd-' + match[2], int(match[3]))


def _archived_seal_slots(seal, day, authority):
    """Integrity-checked local seal, not an authenticated independent receipt."""
    checked = verify_seal(seal)
    plan = checked['plan']
    races = {}
    for race in plan['races']:
        if race['event_date_jst'] != day:
            raise CoverageError('ARCHIVE_DIFFERENT_EVENT_DATE')
        source_sport = race['sport']
        sport = _REAL_SPORT.get(source_sport)
        if source_sport == 'horse':
            sport = authority.get(race['race_id'])
            if sport not in ('horse_jra', 'horse_local'):
                raise CoverageError('HORSE_AUTHORITY_REQUIRED_FOR_EACH_ARCHIVED_RACE')
        if sport is None:
            raise CoverageError('UNSUPPORTED_ARCHIVE_SPORT')
        key = _key(sport, day, race['venue'], race['race_no'])
        if key in races:
            raise CoverageError('ARCHIVE_PHYSICAL_RACE_COLLISION')
        races[key] = race['race_id']
    rid_keys = {v: k for k, v in races.items()}
    slots = []
    models = {m['model_id']: m for m in plan['models']}
    for out in checked['outputs']:
        model = models[out['model_id']]
        slots.append((rid_keys[out['race_id']], {
            'source': 'VERIFIED_LOCAL_EVALUATION_SEAL',
            'model_id': out['model_id'], 'model_version': model['version'],
            'stage': out['stage'], 'forecast_state': out['status'],
            'no_forecast_reason': out['reason'],
            'archive_race_id': out['race_id'],
            'archive_sha256': checked['seal_sha256'],
            'external_pre_cutoff_receipt_verified': False,
            'formal_prediction_admitted': False,
        }))
    return slots


def _retained_slots(report, day):
    """Read-only development data. Caller must independently verify its journal.

    A raw report passed directly to this function does not prove journal integrity.
    Even a verified private journal is retrospective and not a formal test.
    """
    if (type(report) is not dict or report.get('schema') != 'RACE_AI_RETAINED_AUDIT_REPORT_V1'
            or report.get('mode') != 'RETAINED_PREDICTION_AUDIT'
            or report.get('final_test_eligible') is not False
            or type(report.get('rows')) is not list):
        raise CoverageError('UNSUPPORTED_RETAINED_RESEARCH_REPORT')
    result = []
    for row in report['rows']:
        if type(row) is not dict:
            raise CoverageError('INVALID_RETAINED_ROW')
        key = _retained_key(row.get('race_id'))
        if key[1] != day:
            raise CoverageError('RETAINED_DIFFERENT_EVENT_DATE')
        status = row.get('prediction_status')
        if status not in ('FORECAST', 'NO_FORECAST') or row.get('stage') != 'P0':
            raise CoverageError('INVALID_RETAINED_SLOT_STATE')
        model_id, version = row.get('model_id'), row.get('model_version')
        if not all(type(x) is str and 0 < len(x) <= 200 for x in (model_id, version)):
            raise CoverageError('INVALID_RETAINED_MODEL')
        result.append((key, {
            'source': 'RETAINED_DEVELOPMENT_REPORT', 'model_id': model_id,
            'model_version': version, 'stage': 'P0',
            'forecast_state': 'PREDICTED' if status == 'FORECAST' else 'NO_FORECAST',
            'no_forecast_reason': row.get('missing_reason') if status == 'NO_FORECAST' else None,
            'archive_race_id': row['race_id'],
            'archive_sha256': report.get('import_sha256'),
            'external_pre_cutoff_receipt_verified': False,
            'formal_prediction_admitted': False,
        }))
    return result


def link_day(reference, ledger, *, secondary_reference=None, sealed_bundles=(),
             retained_reports=(), horse_authorities=None):
    """Join on (sport, JST date, venue, race number), never by model's alias.

    The supplied manual reference can contain a partially known venue; unknown
    counts and missing sports remain UNKNOWN, not a fabricated 0. Source rights,
    independent cutoff/witness and official outcome authority stay unverified.
    """
    coverage = audit(reference, ledger, secondary_reference)
    day = coverage['event_date_jst']
    authority = horse_authorities if horse_authorities is not None else {}
    if (type(authority) is not dict or any(type(k) is not str or v not in
            ('horse_jra', 'horse_local') for k, v in authority.items())):
        raise CoverageError('HORSE_AUTHORITY_MAPPING_INVALID')
    if type(sealed_bundles) not in (list, tuple) or type(retained_reports) not in (list, tuple):
        raise CoverageError('ARCHIVE_LIST_REQUIRED')
    if len(sealed_bundles) + len(retained_reports) > 32:
        raise CoverageError('ARCHIVE_COUNT_EXCEEDS_BOUND')

    reference_keys = set()
    for venue in reference['venues']:
        for number in venue['race_numbers'] or ():
            reference_keys.add(_key(venue['sport'], day, venue['venue'], number))
    ledger_keys = {}
    for record in ledger['records']:
        key = _key(record['sport'], day, record['venue'], record['race_no'])
        ledger_keys[key] = record

    slots_by_key = {}
    for bundle in sealed_bundles:
        for key, slot in _archived_seal_slots(bundle, day, authority):
            identity = (slot['stage'], slot['model_id'])
            entries = slots_by_key.setdefault(key, {})
            if identity in entries:
                raise CoverageError('DUPLICATE_MODEL_STAGE_FOR_PHYSICAL_RACE')
            entries[identity] = slot
    for report in retained_reports:
        for key, slot in _retained_slots(report, day):
            identity = (slot['stage'], slot['model_id'])
            entries = slots_by_key.setdefault(key, {})
            if identity in entries:
                raise CoverageError('DUPLICATE_MODEL_STAGE_FOR_PHYSICAL_RACE')
            entries[identity] = slot

    rows = []
    counts = Counter()
    for key in sorted(reference_keys | set(ledger_keys) | set(slots_by_key)):
        sport, _, venue, race_no = key
        record = ledger_keys.get(key)
        models = sorted(slots_by_key.get(key, {}).values(), key=lambda m:
                        (m['stage'], m['model_id']))
        anomalies = []
        if key not in reference_keys: anomalies.append('NOT_IN_EXPLICIT_REFERENCE_RACE_LIST')
        if record is None: anomalies.append('MISSING_AUDIT_LEDGER_RECORD')
        if not models: anomalies.append('NO_FROZEN_ARCHIVE_SLOT_LINKED')
        if record is not None and record.get('prediction') is not None:
            anomalies.append('LEDGER_PREDICTION_CLAIM_NOT_INDEPENDENTLY_VERIFIED')
        if models and record is not None and record.get('prediction') is None:
            anomalies.append('LEDGER_WITHOUT_TRUSTED_PREDICTION_ARCHIVE_LINK')
        if record is not None and record.get('prediction') is None and not record.get('no_forecast_reason'):
            anomalies.append('MISSING_NO_FORECAST_REASON')
        if record is not None and record.get('cutoff_verified') is not True:
            anomalies.append('OFFICIAL_CUTOFF_NOT_VERIFIED')
        for model in models:
            counts[model['forecast_state']] += 1
        rows.append({
            'race_id': f'{sport}:{day}:{venue}:{race_no}',
            'sport': sport, 'event_date_jst': day, 'venue': venue, 'race_no': race_no,
            'in_manual_reference': key in reference_keys,
            'in_audit_ledger': record is not None,
            'ledger_no_forecast_reason': (None if record is None or
                                         record.get('prediction') is not None else
                                         record.get('no_forecast_reason')),
            'archive_slots': models,
            'unresolved': anomalies,
        })

    return {
        'schema': 'RACE_AI_FOUR_SPORT_COHORT_BRIDGE_V1',
        'mode': 'OFFLINE_RESEARCH_COVERAGE_LINK',
        'event_date_jst': day,
        'reference_scope': 'MANUAL_REFERENCE_ONLY',
        'reported_race_identities': len(rows),
        'explicit_manual_reference_races': len(reference_keys),
        'audit_ledger_races': len(ledger_keys),
        'local_archived_race_identities': len(slots_by_key),
        'local_archived_slot_counts': dict(sorted(counts.items())),
        'sports_missing_reference': coverage['sports_without_reference'],
        'unknown_reference_race_counts': coverage['reconciliation']['unknown_expected_race_counts'],
        'coverage_audit': coverage,
        'records': rows,
        'official_complete_denominator': None,
        'formal_pre_cutoff_prediction_count': None,
        'formal_hit_at_1': None, 'formal_hit_at_8_all': None,
        'formal_capture_rate': None, 'real_payout_roi': None,
        'brier': None, 'log_loss': None,
        'official_completeness_verified': False,
        'source_rights_verified': False,
        'external_pre_cutoff_receipts_verified': False,
        'official_result_revisions_joined': False,
        'retained_development_is_formal_test': False,
        'predictions_mutated': False,
    }
