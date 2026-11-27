"""Private DT projection of an already independently admitted official original.

``project(payload, original, prediction_at=actual_clock, source_verifier=...)``
returns a normalized prospective record. ``prepare`` also builds the existing
106 base features and their v3 digest. Neither function predicts, seals, fetches,
loads a key, promotes a model, or authenticates itself. The caller supplies the
ACTUAL new processing clock; the old A/B generation clock is never reused as a
new DT prediction time. A post-cutoff replay cannot enter this prospective API.

The native Codex input projector reparses the same card/profile source bytes;
only its factual fields are mapped. Existing DT admission helpers supply the
same official-registration namespace and line semantics. No archive composite,
name, car-number-only or rival-forecast join is permitted. Target results, odds
and conditioned forecasts are excluded even from the verification projection.

source_verifier(packet) must call the EXISTING records.admit_original on the
caller's retained full payload/store, using its real independent origin client,
then recompute verification_payload with the newly admitted original and the
packet's prediction_at and match its exact digest. The packet uses records.wire for exact bytes and
clock serialization. It deliberately omits unrelated/conditioned fields and is
not a replacement full argument to records.admit_original. Return the existing
receipt fields verified=True, independent=True, nonempty verifier, receipt_sha256
and payload_sha256=digest(packet). source_verified_at retains the original's
actual independent server-evidence clock. The current revalidation may happen
later; it must never be backdated into that historic source-availability clock.
An echo callback is only a synthetic fixture, never independent admission.

Nonempty normalized history additionally requires history_verifier(packet) with
the same receipt contract, rerunning existing source AND official-result replay.
Only earlier days and matching official IDs enter the existing feature builder.
Zero history remains explicit missing evidence. Confidence remains HOLD.

For the frozen 462-column family, the caller must subsequently use the existing
augment_features with its genuinely available, pinned VenueStore, followed by
augment_agari and augment_abilities, and check exact model feature_names. This
module does not pad missing schema columns or bypass declared context sidecars.
Forecast seal/readback and an independently audited policy remain separate.
"""
from copy import deepcopy
from datetime import timedelta
import re

from race_ai import keirin_learned_official_inputs as native
from race_ai.keirin_official_nationwide_records import wire

from .admission import _lines, _number, _riders
from .data import _class, input_digest
from .features import _bind_feature_input, build_features, require_history_available
from .policy import check_race_day, checked_day, checked_sha, clock, digest
from .runtime import _checked_receipt


SCHEMA = 'dt-r1-official-input-projection-v1'
SOURCE_SCHEMA = 'dt-r1-official-input-reverify-v1'
HISTORY_SCHEMA = 'dt-r1-official-history-reverify-v1'
IDENTITY_NAMESPACE = 'KEIRIN_JP_OFFICIAL_REGISTRATION'
_NATIVE_FIELDS = ('schema', 'day_jst', 'race_id', 'cohort', 'cohort_sha256',
                  'producer_run_id', 'producer_commit', 'snapshot', 'baseline',
                  'baseline_cipher_sha256', 'baseline_sealed_at', 'confidence_assessment')


def _need(ok, reason):
    if not ok:
        raise ValueError('DT_R1_OFFICIAL_INPUT_' + reason)


def source_projection(payload, original):
    """Return only the native pre-race material this adapter consumes.

    This is a deterministic PRIVATE comparison value, not a public projection
    or an admission receipt. The real verifier must compare it with a freshly
    admitted original. Binary source documents remain private wire values.
    """
    p = {key: deepcopy(payload[key]) for key in _NATIVE_FIELDS if key in payload}
    p['baseline_arguments'] = deepcopy(payload['baseline_arguments'])
    o = {key: deepcopy(original[key]) for key in _NATIVE_FIELDS if key in original}
    o['origin_receipts'] = {'baseline_origin': deepcopy(original['origin_receipts']['baseline_origin'])}
    return {'native_payload': wire(p), 'native_original': wire(o)}


def _receipt(verifier, packet, purpose):
    _need(callable(verifier), purpose + '_VERIFIER_REQUIRED')
    try:
        # Keep our binding separate from the callback's mutable argument.
        return _checked_receipt(verifier(deepcopy(packet)), packet)
    except Exception:
        raise ValueError('DT_R1_OFFICIAL_INPUT_' + purpose + '_INDEPENDENT_RECEIPT_REQUIRED') from None


def verification_payload(payload, original, *, prediction_at):
    """Build a PRIVATE revalidation request, never an authenticated record.

    The existing authority can call this again after real re-admission to check
    the entire request, including the deterministic normalized inputs. There is
    no receipt, source-attestation flag, or independently admitted status here.
    """
    at = clock(prediction_at)
    try:
        projected = native.project(payload, original)
        snapshot = original['snapshot']
        proof = original['origin_receipts']['baseline_origin']
        rid, day, cutoff = original['race_id'], original['day_jst'], snapshot['published_cutoff_at']
        check_race_day(day, cutoff)
        _need(clock(snapshot['as_of']) <= clock(proof['latest_server_evidence_at']) <= at <=
              clock(cutoff) - timedelta(minutes=15), 'SOURCE_OR_PREDICTION_CLOCK')
        # Native projection has already reparsed and matched this exact car /
        # registration roster against the official card and every profile.
        starter = {'race_id': rid, 'source_at': snapshot['cutoff_source']['captured_at'],
                   'riders': [{'number': r['car'], 'registration': r['athlete_id']}
                              for r in snapshot['riders']]}
        riders = _riders(snapshot, starter, rid)
        by_car = {r['car']: r for r in projected['riders']}
        for rider in riders:
            facts = by_car[rider['car']]
            rider.update(rider_class=facts['rider_class'], age=_number(facts['age'], 18, 80),
                         gear_ratio=_number(facts['gear'], 0, 10, positive=True))
            for field in ('top2_rate', 'top3_rate'):
                percent = _number(facts[field], 0, 100)
                rider[field] = percent / 100 if percent is not None else None
            rider['missing_fields'] = [key for key in ('competition_points', 'win_rate',
                'top2_rate', 'top3_rate', 'age', 'gear_ratio') if rider[key] is None]
        race_class = _class(riders)
        row = dict(race_id=rid, day=day, venue_code=rid[8:10], race_class=race_class,
            race_type=projected['round_stage'], meeting_grade=projected['meeting_grade'],
            field_size=len(riders), field_supported=3 <= len(riders) <= 9, riders=riders,
            identity_scope=IDENTITY_NAMESPACE, cohort='prospective',
            cutoff_at=cutoff, published_cutoff_at=cutoff,
            available_at=snapshot['as_of'], source_available_at=snapshot['as_of'],
            source_sha256=snapshot['cutoff_source']['bytes_sha256'],
            source_sha256s=sorted({p['bytes_sha256'] for p in snapshot['source_pages']}),
            context_as_of=prediction_at, source_projection_schema=SCHEMA,
            finish=None, top3=None, result_rows=[], result_status='PENDING', result_at=None,
            official_result_authenticated=False, result_admission_status='NOT_REQUESTED',
            publication_time_authenticated=False,
            confidence={'label': 'HOLD', 'reason': 'NO_INDEPENDENTLY_AUDITED_PROSPECTIVE_POLICY'},
            validation_scope='PROSPECTIVE_SHADOW_PENDING_FORECAST_READBACK',
            forecast_original_sealed=False, production_promoted=False)
        row.update(_lines(snapshot, [r['car'] for r in riders], race_class))
        row['input_sha256'] = input_digest(row)
        return dict(schema=SOURCE_SCHEMA, prediction_at=prediction_at,
                    **source_projection(payload, original), normalized_input=deepcopy(row))
    except Exception:
        # Native parsing failures must never expose source text or private IDs.
        raise ValueError('DT_R1_OFFICIAL_INPUT_NATIVE_SOURCE_PROJECTION_FAILED') from None


def project(payload, original, *, prediction_at, source_verifier):
    """Normalize factual inputs; the output contains no DT prediction clock."""
    _need(callable(source_verifier), 'SOURCE_VERIFIER_REQUIRED')
    packet = verification_payload(payload, original, prediction_at=prediction_at)
    row = deepcopy(packet['normalized_input'])
    proof = original['origin_receipts']['baseline_origin']
    verified = _receipt(source_verifier, packet, 'SOURCE')
    row.update(source_attestation_sha256=verified['receipt_sha256'],
        source_verified_at=proof['latest_server_evidence_at'], source_available_at_verified=True,
        source_admission_status='ADMITTED', pre_cutoff_authenticated=True,
        source_proof={'schema': SCHEMA, 'input_payload_sha256': digest(packet),
            'source_receipt_sha256': verified['receipt_sha256'],
            'baseline_cipher_sha256': original['baseline_cipher_sha256'],
            'origin_receipt_sha256': proof['evidence_sha256']})
    return row


def _history(records, target, prediction_at, verifier):
    history = deepcopy(list(records))
    _need(len(history) <= 100_000, 'HISTORY_SIZE_LIMIT')
    seen = {target['race_id']}
    for row in history:
        _need(isinstance(row, dict) and 'features' not in row, 'NORMALIZED_HISTORY_REQUIRED')
        day = checked_day(row.get('day')).isoformat()
        rid = row.get('race_id')
        _need(isinstance(rid, str) and re.fullmatch(r'20[0-9]{10}', rid) is not None and
              rid.startswith(day.replace('-', '')) and rid not in seen and day < target['day'],
              'HISTORY_MUST_PRECEDE_TARGET_DAY')
        seen.add(rid)
        _need(row.get('input_sha256') == input_digest(row), 'HISTORY_INPUT_HASH_MISMATCH')
        riders = row.get('riders')
        _need(isinstance(riders, list) and 3 <= len(riders) <= 9, 'OFFICIAL_HISTORY_ROSTER_REQUIRED')
        registrations, cars = set(), set()
        for rider in riders:
            registration, car = rider.get('official_registration_id'), rider.get('car')
            _need(isinstance(registration, str) and re.fullmatch(r'[0-9]{6}', registration) is not None and
                  registration != '000000' and registration not in registrations and
                  rider.get('identity_status') == 'OFFICIAL_REGISTRATION_SOURCE_BOUND' and
                  rider.get('identity_usable') is True and
                  rider.get('identity_key') == digest({'namespace': IDENTITY_NAMESPACE, 'registration': registration}) and
                  type(car) is int and 1 <= car <= 9 and car not in cars, 'OFFICIAL_HISTORY_IDENTITY_REQUIRED')
            registrations.add(registration); cars.add(car)
        _need(row.get('source_admission_status') == row.get('result_admission_status') == 'ADMITTED' and
              row.get('source_available_at_verified') is True and
              row.get('official_result_authenticated') is True, 'INDEPENDENT_HISTORY_SOURCE_AND_RESULT_REQUIRED')
        checked_sha(row.get('source_attestation_sha256'))
        checked_sha(row.get('result_source_sha256'))
        check_race_day(day, row.get('cutoff_at'))
        _need(clock(row['available_at']) <= clock(row['source_verified_at']) <= clock(prediction_at) and
              clock(row['cutoff_at']) < clock(row['result_source_observed_at']) <=
              clock(row['result_at']) <= clock(prediction_at), 'HISTORY_AVAILABILITY_CLOCK')
        outcomes = row.get('result_rows')
        _need(isinstance(outcomes, list) and len(outcomes) <= len(cars), 'HISTORY_RESULT_ROSTER')
        result_cars = [r.get('car') for r in outcomes if isinstance(r, dict)]
        _need(len(result_cars) == len(outcomes) == len(set(result_cars)) and set(result_cars) <= cars,
              'HISTORY_RESULT_ROSTER')
    require_history_available(history, prediction_at)
    history.sort(key=lambda row: (row['day'], row['race_id']))
    snapshot = digest(history)
    receipt = None
    if history:
        packet = {'schema': HISTORY_SCHEMA, 'prediction_at': prediction_at,
                  'target_race_id': target['race_id'], 'target_input_sha256': target['input_sha256'],
                  'identity_namespace': IDENTITY_NAMESPACE, 'history_records': history}
        receipt = _receipt(verifier, packet, 'HISTORY')
    return history, {'history_races': len(history), 'history_snapshot_sha256': snapshot,
                    'status': 'INDEPENDENTLY_VERIFIED' if receipt else 'MISSING_HISTORY',
                    'verification_receipt_sha256': receipt['receipt_sha256'] if receipt else None}


def prepare(payload, original, *, prediction_at, source_verifier,
            history_records=(), history_verifier=None):
    """Return the base feature row; missing history remains missing, never zero evidence."""
    target = project(payload, original, prediction_at=prediction_at, source_verifier=source_verifier)
    history, support = _history(history_records, target, prediction_at, history_verifier)
    row = next(r for r in build_features(history + [target]) if r['race_id'] == target['race_id'])
    row['history_evidence'].update(identities_are_unresolved=False,
        identity_namespace=IDENTITY_NAMESPACE, official_support=support)
    for evidence in row['history_evidence']['rider_evidence'].values():
        evidence['official_identity_verified'] = True
    return _bind_feature_input(row)
