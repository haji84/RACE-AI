"""Opt-in private matched research using the TWO existing BOAT families.

An existing research caller supplies authenticated read_p0/read_p1 history and
official parser observations, then calls ``fit_matched``. It retains that
record in its existing private artifact flow, independently reads it back,
calls ``register_study`` and saves that registration before fresh P1 inputs.
``forecast`` invokes both actual trained models; its returned record must also
be independently saved before cutoff. ``score`` reads those exact originals
and later official observations. Nothing here schedules, fetches, stores,
backdates, places orders or changes a production model.

Every saved context is ``{document, receipt}``. The trusted Python dependency
``record_reader(receipt, document_sha256)`` must authenticate existing artifact
metadata and bytes, then extract the exact document from those members. The
hash selects a record when one existing archive contains several documents;
a JSON verification flag is insufficient.
Video authentication retains the existing VideoContextArchiveReader.verify
contract. Event/source grouping is an independently saved operator declaration,
not evidence that its semantic grouping or raw measurements are field-valid.
All returned bodies are OWNER PRIVATE and must never be published as plaintext.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import comb
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from .actions_contract import digest
from . import boat_observed_pairwise_models as native
from . import boat_video_learning as video
from . import four_sport_learning
from . import observed_weight_learning as existing
from .frozen_day_cycle import check_clock, official_id, rank_check, settle


EVENT_SCHEMA = 'RACE_AI_BOAT_VIDEO_EVENT_MAP_V1'
FIT_SCHEMA = 'RACE_AI_BOAT_VIDEO_MATCHED_TRAINING_V1'
STUDY_SCHEMA = 'RACE_AI_BOAT_VIDEO_FORWARD_STUDY_V1'
FORECAST_SCHEMA = 'RACE_AI_BOAT_VIDEO_FORWARD_FORECAST_V1'
_SECOND = timedelta(seconds=1)
_RACE = re.compile(r'[0-9]{8}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_POLICY = dict(metric='TOP8_HIT_RATE', pairing='SAME_NATIVE_INPUT_AND_EXISTING_FAMILY',
    denominator='ALL_REGISTERED_RACES_WITH_MISSING_AND_NONNORMAL_COUNTS',
    statistical_test='EXACT_TWO_SIDED_DISCORDANCE', multiple_comparisons='HOLM_TWO_FAMILIES',
    alpha=.05, production_eligible=False)


def _need(ok, reason):
    if not ok:
        raise ValueError('BOAT_VIDEO_FORWARD_' + reason)


def _now(value):
    _need(type(value) is datetime and value.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    return value


def _seal(document, field):
    return existing.seal(document, field)


def _checked(document, schema, field):
    _need(type(document) is dict and document.get('schema') == schema, 'RECORD_SCHEMA')
    existing.check(document, field)
    return document


def _source_pins():
    pins = {module.__name__: sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (native, video, existing, four_sport_learning)}
    pins[__name__] = sha256(Path(__file__).read_bytes()).hexdigest()
    return pins


def _saved(context, *, at, reader):
    """The callback authenticates storage; equality binds the actual body."""
    _need(callable(reader) and type(context) is dict and
          set(context) == {'document', 'receipt'}, 'INDEPENDENT_RECORD_READER_REQUIRED')
    receipt = context['receipt']
    _need(type(receipt) is dict and receipt.get('expired') is False and
          type(receipt.get('id')) is int and receipt['id'] > 0 and
          receipt.get('workflow_run', {}).get('head_repository_id') == 1416489937 and
          type(receipt.get('digest')) is str and
          re.fullmatch(r'sha256:[a-f0-9]{64}', receipt['digest']), 'RECEIPT_IDENTITY')
    _need(existing.ts(receipt['created_at']) + _SECOND <= at, 'RECEIPT_NOT_AVAILABLE')
    try:
        original = reader(deepcopy(receipt), digest(context['document']))
    except Exception:
        raise ValueError('BOAT_VIDEO_FORWARD_SAVED_RECORD_AUTHENTICATION') from None
    _need(original == context['document'], 'SAVED_RECORD_CHANGED')
    return deepcopy(original)


def _event_map(context, *, at, reader):
    mapping = _checked(_saved(context, at=at, reader=reader), EVENT_SCHEMA, 'event_map_sha256')
    _need(set(mapping) == {'schema', 'created_at', 'races', 'event_map_sha256'} and
          type(mapping['races']) is dict and mapping['races'], 'EVENT_MAP')
    _need(existing.ts(mapping['created_at']) <= existing.ts(context['receipt']['created_at']) + _SECOND,
          'EVENT_MAP_CLOCK')
    venue_days = {}
    for race, group in mapping['races'].items():
        _need(type(race) is str and _RACE.fullmatch(race) and type(group) is dict and
              set(group) == {'event_id', 'source_group'} and
              all(type(v) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', v)
                  for v in group.values()), 'EVENT_MAP_ENTRY')
        datetime.strptime(race[:8], '%Y%m%d')
        # A meet may span days; different races of one venue/day cannot be
        # relabelled as separate events to evade separation.
        _need(venue_days.setdefault(race[:11], group) == group, 'VENUE_DAY_EVENT_CONFLICT')
    return mapping


def _groups(mapping, races, field):
    _need(all(race in mapping['races'] for race in races), 'EVENT_MAP_INCOMPLETE')
    return {mapping['races'][race][field] for race in races}


def _disjoint(mapping, a, b):
    for field in ('event_id', 'source_group'):
        _need(not _groups(mapping, a, field) & _groups(mapping, b, field), 'EVENT_OR_SOURCE_OVERLAP')


def _official_result(observation, cutoff):
    race = observation['race_id']
    _need(type(race) is str and _RACE.fullmatch(race) and
          observation.get('body_identity_verified') is True and
          type(observation.get('source_sha256')) is str and _SHA.fullmatch(observation['source_sha256']),
          'OFFICIAL_RESULT_IDENTITY')
    url = urlsplit(observation['source_url'])
    query = parse_qs(url.query, keep_blank_values=True)
    _need(url.scheme == 'https' and url.netloc == 'www.boatrace.jp' and
          url.path == '/owpc/pc/race/raceresult' and not url.fragment and
          query == dict(hd=[race[:8]], jcd=[race[9:11]], rno=[str(int(race[-2:]))]),
          'OFFICIAL_RESULT_SOURCE')
    _need(existing.ts(observation['closed_at']) == existing.ts(cutoff) and
          existing.ts(observation['captured_at']) >= existing.ts(cutoff), 'RESULT_BEFORE_CUTOFF')


def _model_pins(control, challenger):
    return {model: {role: dict(model_version=training['models'][model]['model_version'],
                              training_sha256=training['training_sha256'])
                    for role, training in (('control', control), ('challenger', challenger))}
            for model in native.MODEL_IDS}


def _verify_fit(pair, mapping):
    _checked(pair, FIT_SCHEMA, 'training_pair_sha256')
    _need(pair['source_pins'] == _source_pins() and
          pair['event_map_sha256'] == mapping['event_map_sha256'], 'MODEL_OR_EVENT_VERSION_CHANGED')
    media = pair['training_video_media_sha256']
    _need(type(media) is list and media == sorted(set(media)) and
          all(type(value) is str and _SHA.fullmatch(value) for value in media), 'TRAINING_MEDIA_PINS')
    control, challenger = pair['control'], pair['challenger']
    existing.verify_training(control)
    video.verify_video_training(challenger)
    media_by_race = pair['training_video_media_by_race']
    video_lineage = {row['race_id']: row for row in challenger['source_lineage']
                     if row['video_context_sha256'] is not None}
    _need(type(media_by_race) is dict and set(media_by_race) == set(video_lineage),
          'TRAINING_MEDIA_LINEAGE')
    for race, entry in media_by_race.items():
        _need(type(entry) is dict and set(entry) == {'media_sha256', 'context_sha256', 'receipt_proof'} and
              type(entry['media_sha256']) is str and _SHA.fullmatch(entry['media_sha256']) and
              entry['context_sha256'] == video_lineage[race]['video_context_sha256'] and
              entry['receipt_proof'] == video_lineage[race]['video_receipt_proof'], 'TRAINING_MEDIA_LINEAGE')
    _need(media == sorted({entry['media_sha256'] for entry in media_by_race.values()}),
          'TRAINING_MEDIA_PINS')
    _need(control['schema'] == existing.SCHEMA_TRAIN and challenger['schema'] == video.SCHEMA_TRAIN,
          'EXISTING_FAMILIES_REQUIRED')
    lineage_fields = ('race_id', 'phase', 'cutoff_at', 'snapshot_sha256', 'forecast_sha256',
        'input_artifact_id', 'input_saved_at', 'result_sha256', 'result_captured_at')
    _need(control['unique_races'] == challenger['unique_races'], 'UNMATCHED_TRAINING_COHORT')
    _need([[row[key] for key in lineage_fields] for row in control['source_lineage']] ==
          [[row[key] for key in lineage_fields] for row in challenger['source_lineage']],
          'UNMATCHED_TRAINING_INPUTS')
    if pair['state'] == 'MATCHED_FITTED_RESEARCH':
        _need(control['state'] == 'FITTED_SHADOW_ONLY' and
              challenger['state'] == 'FITTED_VIDEO_EXPERIMENTAL' and
              set(control['models']) == set(challenger['models']) == set(native.MODEL_IDS), 'NOT_FITTED')
        for key in ('train_races', 'validation_races'):
            _need(control[key] == challenger[key], 'UNMATCHED_TRAINING_COHORT')
        for key in ('train_race_ids', 'validation_race_ids'):
            _need(control[key] == challenger[key], 'UNMATCHED_TRAINING_SPLIT')
        _disjoint(mapping, control['train_race_ids'], control['validation_race_ids'])
        train_media = {media_by_race[race]['media_sha256'] for race in control['train_race_ids']
                       if race in media_by_race}
        validation_media = {media_by_race[race]['media_sha256'] for race in control['validation_race_ids']
                            if race in media_by_race}
        _need(not train_media & validation_media, 'TRAIN_VALIDATION_MEDIA_OVERLAP')
        _need(pair['models'] == _model_pins(control, challenger), 'MODEL_VERSION_PINS')
        _need(all(control['models'][mid]['model_version'] == '0.2.0-FITTED-SHADOW' and
                  challenger['models'][mid]['model_version'] == video.MODEL_VERSION
                  for mid in native.MODEL_IDS), 'MODEL_VERSION')
    else:
        _need(pair['state'] == 'INSUFFICIENT_VIDEO_SUPPORT' and
              challenger['state'] == 'INSUFFICIENT_VIDEO_SUPPORT' and pair['models'] == {}, 'FIT_STATE')


def fit_matched(rows, observations, video_contexts, event_map_context, *, now,
                record_reader, video_receipt_verifier=None):
    """Fit both actual versions on identical caller-authenticated history.

    No ordinary observations are removed or zeroed for the trained control.
    The existing availability split must also separate whole declared events;
    otherwise fitting is rejected rather than quietly relabelling the split.
    Missing authenticated video returns explicit insufficient support.
    """
    _now(now)
    rows, observations, video_contexts = deepcopy((rows, observations, video_contexts))
    mapping = _event_map(event_map_context, at=now, reader=record_reader)
    _need(type(rows) is list and type(observations) is list and type(video_contexts) is dict,
          'TRAINING_INPUTS')
    cutoffs = {row['race_id']: row['cutoff_at'] for row in rows}
    _need(set(video_contexts) <= set(cutoffs), 'FOREIGN_TRAINING_VIDEO')
    for row in rows:
        _need(row['model_id'] in native.MODEL_IDS and len(row['roster']) == 6, 'SIX_BOAT_EXISTING_HISTORY')
    for outcome in observations:
        _need(outcome['race_id'] in cutoffs, 'FOREIGN_TRAINING_RESULT')
        _official_result(outcome, cutoffs[outcome['race_id']])
    control = existing.fit_from_verified(rows, observations, now=now)
    challenger = video.fit_with_video(rows, observations, video_contexts, now=now,
                                     receipt_verifier=video_receipt_verifier)
    admitted = [row['race_id'] for row in control['source_lineage']]
    _groups(mapping, admitted, 'event_id')
    fitted = control['state'] == 'FITTED_SHADOW_ONLY' and challenger['state'] == 'FITTED_VIDEO_EXPERIMENTAL'
    record = dict(schema=FIT_SCHEMA, created_at=now.isoformat(),
        state='MATCHED_FITTED_RESEARCH' if fitted else 'INSUFFICIENT_VIDEO_SUPPORT',
        event_map_context=deepcopy(event_map_context), event_map_sha256=mapping['event_map_sha256'],
        source_pins=_source_pins(), input_rows_sha256=digest(rows), observations_sha256=digest(observations),
        video_envelopes_sha256=digest(video_contexts), control=control, challenger=challenger,
        training_video_media_by_race={row['race_id']: dict(
            media_sha256=video_contexts[row['race_id']]['video_context']['media_sha256'],
            context_sha256=row['video_context_sha256'], receipt_proof=deepcopy(row['video_receipt_proof']))
            for row in challenger['source_lineage'] if row['video_context_sha256'] is not None},
        training_video_media_sha256=sorted({video_contexts[row['race_id']]['video_context']['media_sha256']
            for row in challenger['source_lineage'] if row['video_context_sha256'] is not None}),
        models=_model_pins(control, challenger) if fitted else {},
        production_eligible=False, accuracy_improvement_proven=False)
    _seal(record, 'training_pair_sha256')
    _verify_fit(record, mapping)
    return record


def register_study(training_context, targets, *, now, record_reader):
    """Freeze case/roster/cutoff, training versions, events and analysis policy."""
    _now(now)
    pair = _checked(_saved(training_context, at=now, reader=record_reader), FIT_SCHEMA, 'training_pair_sha256')
    mapping = _event_map(pair['event_map_context'], at=existing.ts(pair['created_at']), reader=record_reader)
    _verify_fit(pair, mapping)
    _need(pair['state'] == 'MATCHED_FITTED_RESEARCH', 'FITTED_VIDEO_REQUIRED')
    _need(existing.ts(pair['created_at']) <= existing.ts(training_context['receipt']['created_at']) + _SECOND,
          'TRAINING_SAVE_CLOCK')
    _need(type(targets) is list and targets, 'FORWARD_TARGETS_REQUIRED')
    cases = {}
    for target in targets:
        _need(type(target) is dict and set(target) == {'race_id', 'cutoff_at', 'roster_sha256'} and
              type(target['race_id']) is str and _RACE.fullmatch(target['race_id']) and
              target['race_id'] not in cases and type(target['roster_sha256']) is str and
              _SHA.fullmatch(target['roster_sha256']), 'TARGET_BINDING')
        cutoff = existing.ts(target['cutoff_at'])
        _need(now < cutoff and cutoff.astimezone(native.JST).strftime('%Y%m%d') == target['race_id'][:8],
              'FUTURE_TARGET_REQUIRED')
        cases[target['race_id']] = deepcopy(target)
    _disjoint(mapping, [r['race_id'] for r in pair['control']['source_lineage']], cases)
    return _seal(dict(schema=STUDY_SCHEMA, created_at=now.isoformat(), training_context=deepcopy(training_context),
        training_pair_sha256=pair['training_pair_sha256'], event_map_sha256=mapping['event_map_sha256'],
        source_pins=_source_pins(), models=deepcopy(pair['models']), targets=cases, policy=deepcopy(_POLICY),
        accuracy_improvement_proven=False, production_eligible=False), 'study_sha256')


def _study(context, *, at, reader):
    study = _checked(_saved(context, at=at, reader=reader), STUDY_SCHEMA, 'study_sha256')
    created = existing.ts(study['created_at'])
    _need(created <= existing.ts(context['receipt']['created_at']) + _SECOND and
          study['policy'] == _POLICY and study['source_pins'] == _source_pins(), 'STUDY_POLICY_OR_CLOCK')
    expected = register_study(study['training_context'], list(study['targets'].values()),
                              now=created, record_reader=reader)
    _need(study == expected, 'STUDY_BINDING_CHANGED')
    return study, study['training_context']['document']


def _predictions(study, pair, snapshot, envelope, *, verifier, allow_source):
    native._validate(snapshot)
    race = official_id(snapshot['race_id'])
    _need(snapshot['stage'] == 'P1' and snapshot['scope'] == 'OPERATOR_SUPPLIED_RESEARCH' and
          len(snapshot['participants']) == 6 and race in study['targets'], 'REGISTERED_SIX_BOAT_P1_REQUIRED')
    target = study['targets'][race]
    roster = {str(p['lane']): p['registration_no'] for p in snapshot['participants']}
    _need(target['cutoff_at'] == snapshot['sales_cutoff_at'] and
          target['roster_sha256'] == digest(roster), 'TARGET_CHANGED')
    _need(callable(allow_source), 'SOURCE_AUTHORIZER_REQUIRED')
    baseline = native.predict_pair(snapshot, allow_source=allow_source)
    receipt = study['training_context']['receipt']
    controls = existing.make_shadows(snapshot, baseline, dict(training=pair['control'], receipt=receipt))
    candidates = []
    if envelope is not None:
        _need(callable(verifier) and type(envelope) is dict and
              envelope.get('video_context', {}).get('dataset_status') != 'SYNTHETIC_ONLY',
              'AUTHENTICATED_REAL_VIDEO_REQUIRED')
        _need(envelope['video_context']['media_sha256'] not in pair['training_video_media_sha256'],
              'TRAINING_MEDIA_REUSED_FOR_EVALUATION')
        candidates = video.make_video_shadows(snapshot, baseline,
            dict(training=pair['challenger'], receipt=receipt), envelope, receipt_verifier=verifier)
        _need(len(candidates) == 2, 'ELIGIBLE_VIDEO_REQUIRED')
    _need(len(controls) == 2 and {r['model_id'] for r in controls} == set(native.MODEL_IDS) and
          (not candidates or {r['model_id'] for r in candidates} == set(native.MODEL_IDS)), 'EXISTING_MODEL_OUTPUTS')
    return controls, candidates


def forecast(study_context, snapshot, video_context, *, record_reader,
             video_receipt_verifier=None, allow_source, clock=None):
    """Actual opt-in native inference; caller saves the returned PRIVATE record.

    A missing target context still records the real trained control and an
    explicit missing challenger. A malformed, synthetic or late context rejects
    the invocation. Completion crossing cutoff returns no forecast.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    started = _now(clock())
    snapshot, video_context = deepcopy((snapshot, video_context))
    instant, cutoff = existing.ts(snapshot['as_of']), existing.ts(snapshot['sales_cutoff_at'])
    _need(instant <= started < cutoff, 'ACTUAL_INFERENCE_CLOCK')
    study, pair = _study(study_context, at=instant, reader=record_reader)
    controls, candidates = _predictions(study, pair, snapshot, video_context,
        verifier=video_receipt_verifier, allow_source=allow_source)
    completed = _now(clock())
    _need(started <= completed < cutoff, 'ACTUAL_INFERENCE_CROSSED_CUTOFF')
    return _seal(dict(schema=FORECAST_SCHEMA, study_sha256=study['study_sha256'],
        training_pair_sha256=pair['training_pair_sha256'], event_map_sha256=study['event_map_sha256'],
        source_pins=_source_pins(), race_id=official_id(snapshot['race_id']), snapshot=snapshot,
        input_sha256=digest(snapshot), video_context=video_context, control=controls, challenger=candidates,
        status='PAIRED_RESEARCH' if candidates else 'MISSING_VIDEO_CONTEXT',
        started_at=started.isoformat(), completed_at=completed.isoformat(),
        actual_purchases=False, production_eligible=False, accuracy_improvement_proven=False), 'forecast_sha256')


def _settlement_row(prediction, snapshot):
    ranked = [r['combination'] for r in prediction['candidates']]
    rank_check(ranked, prediction['ordered_top8'])
    return dict(race_id=prediction['race_id'], stage='P1', model_id=prediction['model_id'],
        cutoff_at=snapshot['sales_cutoff_at'], top8=prediction['ordered_top8'], ranked=ranked,
        roster={str(p['lane']): p['registration_no'] for p in snapshot['participants']})


def _record_reference(context):
    return dict(document_sha256=digest(context['document']), receipt=deepcopy(context['receipt']))


def score(study_context, forecast_contexts, result_contexts, *, now, record_reader,
          video_receipt_verifier=None, allow_source):
    """Descriptive paired settlement; neither historical fitting nor promotion.

    Official observations are independently saved documents extracted by the
    same trusted reader from existing result journals. No local timestamp,
    embedded flag or resealed forecast substitutes for its original bytes.
    The returned PRIVATE comparison seals its exact document/receipt references
    and retains them even for unpaired declared cases. The caller can retain
    this comparison in the same authorized private archive flow.
    """
    _now(now)
    study, pair = _study(study_context, at=now, reader=record_reader)
    _need(type(forecast_contexts) is list and type(result_contexts) is list, 'SAVED_INPUT_LISTS')
    forecasts, outcomes, forecast_references, result_references = {}, {}, {}, {}
    for context in forecast_contexts:
        record = _checked(_saved(context, at=now, reader=record_reader), FORECAST_SCHEMA, 'forecast_sha256')
        race = record['race_id']
        _need(race in study['targets'] and race not in forecasts, 'DUPLICATE_OR_FOREIGN_FORECAST')
        snapshot = record['snapshot']; cutoff = snapshot['sales_cutoff_at']
        _need(record['study_sha256'] == study['study_sha256'] and
              record['training_pair_sha256'] == pair['training_pair_sha256'] and
              record['event_map_sha256'] == study['event_map_sha256'] and
              record['source_pins'] == _source_pins() and record['input_sha256'] == digest(snapshot) and
              race == official_id(snapshot['race_id']), 'FORECAST_BINDING')
        _study(study_context, at=existing.ts(snapshot['as_of']), reader=record_reader)
        check_clock(record['completed_at'], cutoff, context['receipt']['created_at'])
        _need(existing.ts(context['receipt']['created_at']) + _SECOND <= existing.ts(cutoff) and
              existing.ts(snapshot['as_of']) <= existing.ts(record['started_at']) <=
              existing.ts(record['completed_at']), 'FORECAST_SAVE_CLOCK')
        controls, candidates = _predictions(study, pair, snapshot, record['video_context'],
            verifier=video_receipt_verifier, allow_source=allow_source)
        _need(record['control'] == controls and record['challenger'] == candidates and
              record['status'] == ('PAIRED_RESEARCH' if candidates else 'MISSING_VIDEO_CONTEXT') and
              record['actual_purchases'] is False and record['production_eligible'] is False and
              record['accuracy_improvement_proven'] is False, 'FROZEN_MODEL_REPLAY_CHANGED')
        forecasts[race] = record
        forecast_references[race] = dict(_record_reference(context),
            forecast_sha256=record['forecast_sha256'], input_sha256=record['input_sha256'])
    for context in result_contexts:
        outcome = _saved(context, at=now, reader=record_reader)
        race = outcome['race_id']
        _need(race in study['targets'] and race not in outcomes, 'DUPLICATE_OR_FOREIGN_RESULT')
        _official_result(outcome, study['targets'][race]['cutoff_at'])
        _need(existing.ts(outcome['captured_at']) <= existing.ts(context['receipt']['created_at']) + _SECOND,
              'RESULT_SAVE_CLOCK')
        outcomes[race] = outcome
        result_references[race] = dict(_record_reference(context), source_sha256=outcome['source_sha256'],
            source_url=outcome['source_url'], captured_at=outcome['captured_at'])
    models = []
    for model in native.MODEL_IDS:
        a = b = both = discord_a = discord_b = paired = 0
        exclusions, cases = {}, []
        for race in sorted(study['targets']):
            record, outcome = forecasts.get(race), outcomes.get(race)
            state = 'MISSING_FORECAST' if record is None else (
                'MISSING_VIDEO_CONTEXT' if not record['challenger'] else 'RESULT_PENDING')
            if record is not None and record['challenger']:
                predictions = [{r['model_id']: r for r in record[role]}[model]
                               for role in ('control', 'challenger')]
                verdicts = [settle(_settlement_row(p, record['snapshot']), outcome) for p in predictions]
                if all(v['state'] in ('HIT', 'MISS') for v in verdicts):
                    x, y = [v['state'] == 'HIT' for v in verdicts]
                    paired += 1; a += x; b += y; both += x and y
                    discord_a += x and not y; discord_b += y and not x
                    state = 'PAIRED'
                else:
                    state = verdicts[0]['state']
            prediction_hashes = {role: next((p['prediction_sha256'] for p in record[role]
                                  if p['model_id'] == model), None) if record else None
                                 for role in ('control', 'challenger')}
            cases.append(dict(race_id=race, state=state,
                forecast_reference=deepcopy(forecast_references.get(race)),
                result_reference=deepcopy(result_references.get(race)),
                control_prediction_sha256=prediction_hashes['control'],
                challenger_prediction_sha256=prediction_hashes['challenger']))
            if state != 'PAIRED':
                exclusions[state] = exclusions.get(state, 0) + 1
        discordant = discord_a + discord_b
        p_value = min(1., 2*sum(comb(discordant, k) for k in range(min(discord_a, discord_b)+1)) /
                      2**discordant) if discordant else 1.
        models.append(dict(model_id=model, declared_races=len(study['targets']), paired_races=paired,
            control_hits=a, challenger_hits=b, both_hit=both, control_only=discord_a, challenger_only=discord_b,
            both_miss=paired-a-b+both, control_hit_rate=a/paired if paired else None,
            challenger_hit_rate=b/paired if paired else None, hit_rate_difference=(b-a)/paired if paired else None,
            effect='OBSERVED_GAIN' if b > a else 'DEGRADED' if b < a else 'NO_EFFECT',
            exact_discordance_p_value=p_value, excluded=exclusions, cases=cases))
    adjusted = 0.
    for index, model in enumerate(sorted(models, key=lambda m: m['exact_discordance_p_value'])):
        adjusted = max(adjusted, min(1., (len(models)-index)*model['exact_discordance_p_value']))
        model['holm_adjusted_p_value'] = adjusted
    references = dict(study=_record_reference(study_context),
                      forecasts=forecast_references, results=result_references)
    return _seal(dict(schema='RACE_AI_BOAT_VIDEO_FORWARD_COMPARISON_V1', study_sha256=study['study_sha256'],
        input_references=references, comparison_inputs_sha256=digest(references),
        evaluated_at=now.isoformat(), declared_races=len(study['targets']), models=models,
        evidence_scope='SAVED_PRE_CUTOFF_RESEARCH_NOT_FIELD_VALIDATION',
        accuracy_improvement_proven=False, production_eligible=False, actual_purchases=False), 'comparison_sha256')
