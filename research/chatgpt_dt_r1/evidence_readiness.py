"""Read existing inputs and report aggregate evidence gaps without admitting them.

This diagnostic reuses the motion, phase-provenance and weather contracts. It
does not fetch media, infer missing labels, fit a model, authenticate sources,
create a forecast, change a schedule or modify its inputs. Public checkpoint
summaries remain summaries; no adapter silently upgrades them into observations.

The CLI accepts explicit local files, including private JSON/JSONL inputs, and
prints counts and input-byte hashes only. It never prints IDs, URLs, labels,
measurements, filenames, raw exception messages or private source documents.
"""
from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from .abilities import validate_motion, split_sidecars, motion_history
from .context import _weather
from .observations import PHASES, PhaseObservation, Provenance, SourceKind, day, utc


SCHEMA = 'dt-r1-evidence-readiness-v1'
PROVENANCE_FIELDS = ('kind', 'source_url', 'source_sha256', 'retrieved_at',
                     'available_at', 'reviewer_id', 'reviewed_at')
MOTION_FIELDS = ('rider_id', 'registration_id', 'identity_receipt_sha256',
                 'measurement_receipt_sha256', 'measurement_evidence')
WEATHER_FIELDS = ('kind', 'source_sha256', 'issued_at', 'available_at')
PUBLIC_FIELDS = ('complete_order', 'media_sha256', 'source_sha256',
                 'reviewed_at', 'reviewer_id', 'receipt')
INPUT_ERRORS = (ValueError, TypeError, KeyError, AttributeError, OverflowError)


def _missing(counter, record, fields):
    record = record if isinstance(record, dict) else {}
    for field in fields:
        counter[field] += not bool(record.get(field))


def _provenance_missing(counter, record):
    provenance = record.get('provenance') if isinstance(record, dict) else None
    fields = PROVENANCE_FIELDS
    if isinstance(provenance, dict) and provenance.get('kind') != 'reviewed_video':
        fields = fields[:-2]
    _missing(counter, provenance, fields)


def _public_counts(document):
    result = dict(races=0, checkpoints=0, races_with_leader_registration=0,
                  by_phase={key: 0 for key in ('home', 'back', 'corner', 'other')},
                  missing={key: 0 for key in PUBLIC_FIELDS},
                  usable_as_complete_phase_labels=0,
                  conversion_to_training_records='NOT_PERFORMED')
    if document is None:
        return result
    if not isinstance(document, dict) or not isinstance(document.get('races'), list):
        raise ValueError('PUBLIC_OBSERVATION_SUMMARY_REQUIRED')
    result['races'] = len(document['races'])
    result['declared_race_count_matches'] = document.get('observed_race_count') == result['races']
    for row in document['races']:
        result['races_with_leader_registration'] += bool(row.get('B_leader_registration'))
        for checkpoint in row.get('checkpoints', []):
            result['checkpoints'] += 1
            phase = checkpoint.get('phase')
            result['by_phase'][phase if phase in ('home', 'back', 'corner') else 'other'] += 1
            provenance = checkpoint.get('provenance') or {}
            present = dict(
                complete_order=isinstance(checkpoint.get('order'), list) and
                    bool(checkpoint['order']) and checkpoint.get('complete') is True,
                media_sha256=checkpoint.get('media_sha256') or checkpoint.get('video_sha256'),
                source_sha256=provenance.get('source_sha256') or checkpoint.get('source_sha256'),
                reviewed_at=provenance.get('reviewed_at') or checkpoint.get('reviewed_at'),
                reviewer_id=provenance.get('reviewer_id') or checkpoint.get('reviewer_id'),
                receipt=checkpoint.get('receipt'))
            _missing(result['missing'], present, PUBLIC_FIELDS)
    return result


def _public_starter_counts(document):
    result = dict(races=0, rider_entries=0, registration_present=0, registration_missing=0,
                  normalized_input_created=False, source_admission='NOT_PERFORMED')
    if document is None:
        return result
    if not isinstance(document, dict) or not isinstance(document.get('races'), list):
        raise ValueError('PUBLIC_STARTER_PROJECTION_REQUIRED')
    result['races'] = len(document['races'])
    for row in document['races']:
        for rider in row['riders']:
            present = bool(rider.get('registration'))
            result['rider_entries'] += 1
            result['registration_present'] += present
            result['registration_missing'] += not present
    return result


def _model_counts(artifact):
    if artifact is None:
        return dict(supplied=False)
    from .model import RankModel
    model = RankModel.from_dict(artifact)
    context = model.fit_meta.get('context', {})
    motion = [i for i, name in enumerate(model.feature_names) if name.startswith('history_dt_motion_')]
    weather = [i for i, name in enumerate(model.feature_names) if name.startswith('context_weather_')]
    return dict(supplied=True, artifact_integrity_verified=True, model_sha256=artifact['model_sha256'],
                feature_columns=len(model.feature_names), motion_feature_columns=len(motion),
                motion_columns_with_nonzero_weight=int((model.weights[:, motion] != 0).any(axis=0).sum()),
                weather_context_feature_columns=len(weather),
                weather_context_columns_with_nonzero_weight=int((model.weights[:, weather] != 0).any(axis=0).sum()),
                timing_sidecar_declared=bool(context.get('timing_file_sha256')),
                weather_sidecar_declared=bool(context.get('weather_file_sha256')),
                observation_counts_inferred_from_weights=False, source_admission='NOT_PERFORMED')


def inspect_evidence(*, as_of, targets=(), public_observations=None,
                     motion_records=(), phase_observations=(), public_starters=None, frozen_model=None):
    """Return safe counts; passing a shape/clock check is never source admission.

    targets are existing normalized DT-R1 race inputs. Motion files use the
    existing dt-reviewed-motion schema; phase files use PhaseObservation.
    Raw Mac attack/follow labels are intentionally not transformed into either.
    """
    cutoff = utc(as_of)
    targets, motion_records, phase_observations = list(targets), list(motion_records), list(phase_observations)
    identity = dict(target_races=len(targets), rider_targets=0, identity_unusable=0,
                    missing_official_registration=0, duplicate_target_race_groups=0)
    race_counts = Counter()
    for row in targets:
        if not isinstance(row, dict) or not isinstance(row.get('race_id'), str) or not row['race_id']:
            raise ValueError('NORMALIZED_TARGET_REQUIRED')
        day(row['day'])
        if not isinstance(row.get('riders'), list):
            raise ValueError('NORMALIZED_TARGET_ROSTER_REQUIRED')
        race_counts[row['race_id']] += 1
        for rider in row['riders']:
            identity['rider_targets'] += 1
            identity['identity_unusable'] += rider.get('identity_usable') is not True
            identity['missing_official_registration'] += not bool(rider.get('official_registration_id'))
    identity['duplicate_target_race_groups'] = sum(count > 1 for count in race_counts.values())

    motion = dict(supplied=len(motion_records), schema_valid=0, schema_rejected=0,
                  unavailable_by_as_of=0, duplicate_race_rider_groups=0, joint_schema_valid=True,
                  missing_fields={key: 0 for key in MOTION_FIELDS},
                  missing_provenance={key: 0 for key in PROVENANCE_FIELDS},
                  target_races_with_history=0, rider_targets_with_history=0, joined_observation_uses=0,
                  source_admission='NOT_PERFORMED')
    valid_motion = []
    for record in motion_records:
        _missing(motion['missing_fields'], record, MOTION_FIELDS)
        _provenance_missing(motion['missing_provenance'], record)
        try:
            validate_motion(record)
        except INPUT_ERRORS:
            motion['schema_rejected'] += 1
        else:
            motion['schema_valid'] += 1
            valid_motion.append(record)
            motion['unavailable_by_as_of'] += utc(record['provenance']['available_at']) > cutoff
    duplicate_motion = Counter((row['race_id'], row['rider_id']) for row in valid_motion)
    motion['duplicate_race_rider_groups'] = sum(count > 1 for count in duplicate_motion.values())
    try:
        _, valid_motion = split_sidecars(valid_motion)
    except INPUT_ERRORS:
        motion['joint_schema_valid'] = False
        valid_motion = []
    for row in targets:
        if race_counts[row['race_id']] != 1:
            continue
        joined = motion_history(row, valid_motion, as_of)
        motion['target_races_with_history'] += bool(joined)
        motion['rider_targets_with_history'] += len(joined)
        motion['joined_observation_uses'] += sum(item['count'] for item in joined.values())

    phases = dict(supplied=len(phase_observations), schema_valid=0, schema_rejected=0,
                  unreviewed_source=0, unavailable_by_as_of=0, declared_complete=0,
                  duplicate_race_phase_groups=0, complete_order_matching_supplied_roster=0,
                  by_phase={key: 0 for key in PHASES},
                  missing_provenance={key: 0 for key in PROVENANCE_FIELDS},
                  training_admission='NOT_PERFORMED', existing_fitter_required=True)
    valid_phases = []
    for record in phase_observations:
        _provenance_missing(phases['missing_provenance'], record)
        try:
            value = dict(record)
            value['provenance'] = Provenance(**value['provenance'])
            observation = PhaseObservation(**value)
        except INPUT_ERRORS:
            phases['schema_rejected'] += 1
        else:
            valid_phases.append(observation)
            phases['schema_valid'] += 1
            phases['by_phase'][observation.phase] += 1
            phases['declared_complete'] += observation.complete
            phases['unreviewed_source'] += observation.provenance.kind not in (
                SourceKind.OFFICIAL_RECORD, SourceKind.REVIEWED_VIDEO)
            phases['unavailable_by_as_of'] += utc(observation.provenance.available_at) > cutoff
    duplicates = Counter((row.race_id, row.phase) for row in valid_phases)
    phases['duplicate_race_phase_groups'] = sum(count > 1 for count in duplicates.values())
    rosters = {row['race_id']: [rider['car'] for rider in row['riders']]
               for row in targets if race_counts[row['race_id']] == 1}
    for observation in valid_phases:
        if (observation.complete and duplicates[observation.race_id, observation.phase] == 1
                and observation.race_id in rosters
                and sorted(observation.order) == sorted(rosters[observation.race_id])):
            phases['complete_order_matching_supplied_roster'] += 1

    weather = dict(target_races=len(targets), missing=0, supplied=0,
                   source_clock_schema_accepted=0, with_usable_numeric_values=0,
                   rejected_by_existing_filter=0, missing_fields={key: 0 for key in WEATHER_FIELDS},
                   source_admission='NOT_PERFORMED')
    for row in targets:
        supplied = row.get('weather_observation')
        if supplied is None:
            weather['missing'] += 1
            continue
        weather['supplied'] += 1
        _missing(weather['missing_fields'], supplied, WEATHER_FIELDS)
        values, source = _weather(row, as_of)
        if source is None:
            weather['rejected_by_existing_filter'] += 1
        else:
            weather['source_clock_schema_accepted'] += 1
            weather['with_usable_numeric_values'] += bool(values)

    return dict(schema=SCHEMA, status='DIAGNOSTIC_ONLY', as_of=cutoff.isoformat(),
                independent_source_authentication=False, real_media_replayed=False,
                modifies_models_or_originals=False, public_observations=_public_counts(public_observations),
                public_starters=_public_starter_counts(public_starters), frozen_model=_model_counts(frozen_model),
                identity=identity, motion=motion, phases=phases, weather=weather)


def _read(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(50 * 1024 * 1024 + 1)
    if len(raw) > 50 * 1024 * 1024:
        raise ValueError('READINESS_INPUT_TOO_LARGE')
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = [json.loads(line) for line in raw.splitlines() if line.strip()]
    return value, sha256(raw).hexdigest()


def _records(document):
    if isinstance(document, list):
        return document
    if isinstance(document, dict):
        if 'records' in document:
            if not isinstance(document['records'], list):
                raise ValueError('RECORD_LIST_REQUIRED')
            return document['records']
        return [document]
    raise ValueError('RECORD_LIST_REQUIRED')


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--public-observations', type=Path)
    parser.add_argument('--public-starters', type=Path, help='Count a public projection without creating admitted inputs.')
    parser.add_argument('--frozen-model', type=Path, help='Verify existing model integrity and summarize declared sidecars.')
    parser.add_argument('--targets', type=Path, help='Existing normalized DT-R1 inputs; no public-card conversion.')
    parser.add_argument('--motion-records', type=Path, help='Existing reviewed-motion JSON or JSONL.')
    parser.add_argument('--phase-observations', type=Path, help='Existing PhaseObservation JSON or JSONL.')
    args = parser.parse_args(argv)
    try:
        documents, hashes = {}, {}
        for name in ('public_observations', 'public_starters', 'frozen_model', 'targets',
                     'motion_records', 'phase_observations'):
            path = getattr(args, name)
            if path is not None:
                document, hashes[name] = _read(path)
                documents[name] = document if name in ('public_observations', 'public_starters', 'frozen_model') else _records(document)
        if not documents:
            raise ValueError('AT_LEAST_ONE_INPUT_REQUIRED')
        report = inspect_evidence(as_of=args.as_of, **documents)
        report['input_bytes_sha256'] = hashes
    except (OSError, UnicodeError) + INPUT_ERRORS:
        print(json.dumps(dict(schema=SCHEMA, status='HOLD_INVALID_INPUT',
                              independent_source_authentication=False), sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
