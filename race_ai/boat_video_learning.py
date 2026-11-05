"""Optional video dimensions for parameter versions of the TWO existing families.

The trusted caller must authenticate historical forecast/result inputs exactly
as for ``fit_from_verified``. Video admission additionally needs a Python
``receipt_verifier(receipt, context_sha256, as_of)`` dependency. It must obtain
independent external saved bytes and return their bound proof, or reject them;
JSON assertions, reviewer labels and matching local hashes cannot replace it.
Current-race exhibition video is admitted only for P1; P0 retains its original
feature contract and can participate in history without a video context.
These experiments preserve raw UNVALIDATED measurements and never certify
strength, calibrated probabilities, production eligibility or improvement.
"""
from collections import Counter
from copy import deepcopy
from fractions import Fraction
import math
import re

from .actions_contract import digest
from .boat_observed_pairwise_models import MODEL_IDS, WEIGHTS, _validate
from .boat_video_model_context import FEATURE_IDS, FEATURE_SCHEMA, validate_video_context
from .four_sport_learning import _gradient, _all_triples
from . import observed_weight_learning as existing


SCHEMA_TRAIN = 'RACE_AI_EXISTING_OBSERVED_VIDEO_WEIGHT_FIT_V1'
SCHEMA_SHADOW = 'RACE_AI_EXISTING_OBSERVED_VIDEO_SHADOW_V1'
MODEL_VERSION = '0.3.0-VIDEO-EXPERIMENTAL'
NORMALIZATION = 'WITHIN_RACE_INTERVAL_RESOLVED_SPAN_NO_ORIENTATION_V1'
FEATURES = existing.FEATURES + FEATURE_IDS
MIN_VIDEO_SUPPORT = 4
_SHA = re.compile(r'sha256:[0-9a-f]{64}\Z')


def _policy():
    return dict(epochs=existing.EPOCHS, learning_rate=existing.LR,
        l2_to_initial_weights=existing.L2, base_weight_min=0., base_weight_max=4.,
        video_weight_min=-4., video_weight_max=4., minimum_observed_train_races=MIN_VIDEO_SUPPORT,
        pair_resolution='ABS_DELTA_GT_SUM_ABSOLUTE_UNCERTAINTY')


def _target(snapshot):
    from .frozen_day_cycle import official_id
    return dict(race_id=official_id(snapshot['race_id']), cutoff_at=snapshot['sales_cutoff_at'],
        as_of=snapshot['as_of'], roster=[dict(lane=p['lane'], registration_number=p['registration_no'])
                                       for p in snapshot['participants']])


def _bound_context(snapshot, video_context):
    """Validate the frozen context at its own time without rebinding its seal."""
    existing.need(snapshot['stage'] == 'P1', 'current exhibition video requires P1 input')
    existing.need(type(video_context) is dict and type(video_context.get('as_of')) is str,
                  'frozen video context as_of required')
    target = _target(snapshot)
    target['as_of'] = video_context['as_of']
    context = validate_video_context(video_context, **target)
    existing.need(existing.ts(context['as_of']) <= existing.ts(snapshot['as_of']),
                  'video context not available at model as_of')
    return context


def video_vectors(snapshot, video_context=None):
    """Original eight contrasts plus four unsigned raw-order contrast dimensions.

    Observed min/max scaling happens within a single feature/race/comparison,
    never across pixel scales or source contexts. A pair contributes only when
    its raw difference exceeds the sum of its absolute uncertainty bounds.
    Missing/unresolved pairs and all-equal measurements contribute zero. Exact
    rational division keeps tiny or extreme finite spans bounded. Signed coefficients,
    initially zero, determine direction rather than a radius/quality heuristic.
    This arithmetic helper does not authenticate the supplied measurements.
    """
    _validate(snapshot)
    vectors = existing.vectors(snapshot)
    context = None if video_context is None else _bound_context(snapshot, video_context)
    for feature in FEATURE_IDS:
        cells = {} if context is None else {row['lane']: row['feature_cells'][feature]
            for row in context['participants'] if row['feature_cells'][feature]['value'] is not None}
        values = {lane: Fraction(str(cell['value'])) for lane, cell in cells.items()}
        errors = {lane: Fraction(str(cell['uncertainty'])) for lane, cell in cells.items()}
        span = max(values.values())-min(values.values()) if values else Fraction(0)
        for lane in range(1, 7):
            contrast = Fraction(0)
            if span and lane in values:
                for other in values:
                    if other == lane:
                        continue
                    delta = values[lane]-values[other]
                    if abs(delta) > errors[lane]+errors[other]:
                        contrast += delta/span
            vectors[lane].append(float(contrast/6))
    return vectors


def _admit(envelope, snapshot, receipt_verifier, *, now=None):
    """Authenticate exact context identity through an independent caller reader."""
    if envelope is None:
        return None, None
    existing.need(snapshot['stage'] == 'P1', 'current exhibition video requires P1 input')
    if receipt_verifier is None:
        return None, None
    existing.need(callable(receipt_verifier), 'video receipt verifier must be callable')
    existing.need(type(envelope) is dict and {'video_context', 'receipt'} <= envelope.keys() and
                  type(envelope['receipt']) is dict, 'video input envelope required')
    context = _bound_context(snapshot, envelope['video_context'])
    receipt = deepcopy(envelope['receipt'])
    existing.need(receipt.get('expired') is False and
        receipt.get('workflow_run', {}).get('head_repository_id') == 1416489937 and
        type(receipt.get('id')) is int and receipt['id'] > 0 and
        type(receipt.get('digest')) is str and _SHA.fullmatch(receipt['digest']),
        'video receipt identity')
    expected = dict(context_sha256=context['context_sha256'], id=receipt['id'],
                    digest=receipt['digest'], created_at=receipt['created_at'])
    try:
        proof = receipt_verifier(deepcopy(receipt), context['context_sha256'], snapshot['as_of'])
    except Exception as exc:
        raise ValueError('independent video receipt authentication failed') from exc
    existing.need(type(proof) is dict and proof == expected,
                  'independent video receipt/context binding mismatch')
    from .frozen_day_cycle import check_clock
    check_clock(context['as_of'], snapshot['sales_cutoff_at'], receipt['created_at'])
    saved, as_of = existing.ts(receipt['created_at']), existing.ts(snapshot['as_of'])
    # GHA receipts have whole-second resolution. Require the complete possible
    # receipt interval to precede model input, including fractional test times.
    existing.need(saved + existing.timedelta_one_second() <= as_of,
                  'video receipt availability interval not before model as_of')
    if now is not None:
        existing.need(saved <= now, 'future video receipt cannot train')
    return (context if context['eligible_for_research'] else None), deepcopy(proof)


def _split(records):
    if not records:
        return [], []
    validation_size = max(2, len(records)//4)
    train, holdout = records[:-validation_size], records[-validation_size:]
    boundary = existing.ts(holdout[0]['result_captured_at'])
    while train and existing.ts(train[-1]['result_captured_at']) == boundary:
        holdout.insert(0, train.pop())
    return train, holdout


def _supports(records):
    return [sum(any(row['vectors'][lane][column] != 0 for lane in range(1, 7)) for row in records)
            for column in range(len(FEATURES))]


def _fit(train, supports, mid):
    base = list(WEIGHTS[mid]) + [0.] * len(FEATURE_IDS)
    weights = base[:]
    for _ in range(existing.EPOCHS):
        gradients = [_gradient(row['vectors'], row['winner'], weights)[0] for row in train]
        weights = [min(4., max(0. if j < len(existing.FEATURES) else -4.,
            weight + existing.LR * (sum(g[j] for g in gradients)/(3*len(train)) -
                                    existing.L2*(weight-base[j]))))
            if supports[j] >= MIN_VIDEO_SUPPORT else base[j] for j, weight in enumerate(weights)]
    return weights


def fit_with_video(rows, observations, video_contexts, *, now, receipt_verifier=None):
    """Fit experimental parameter versions from caller-authenticated history.

    ``video_contexts`` maps official race IDs to ``{video_context, receipt}``.
    The receipt verifier returns exactly ``{context_sha256,id,digest,created_at}``
    after independently reading/authenticating the external saved context. It is
    a trusted code dependency, never a serializable human-verification claim.
    Missing verifier/context yields zero video support. Official settlement,
    snapshot/clock checks and one input/outcome per race are reused unchanged.
    Explicit video contexts on P0 inputs are rejected, regardless of timestamps.
    """
    existing.need(now.utcoffset() is not None, 'aware video fit time required')
    existing.need(type(video_contexts) is dict, 'video contexts must map race IDs')
    rows, observations, video_contexts = deepcopy((rows, observations, video_contexts))
    admitted = existing.fit_from_verified(rows, observations, now=now)
    by_input = {(row['race_id'], row.get('learning_snapshot_sha256'), row.get('model_sha256')): row
                for row in rows if row.get('learning_snapshot') is not None}
    by_result = {result['race_id']: result for result in observations}
    from .frozen_day_cycle import settle
    records = []
    for lineage in admitted['source_lineage']:
        row = by_input[(lineage['race_id'], lineage['snapshot_sha256'], lineage['forecast_sha256'])]
        snapshot = row['learning_snapshot']
        existing.need(row['roster'] == {str(p['lane']): p['registration_no'] for p in snapshot['participants']},
                      'video learning snapshot/official roster binding mismatch')
        context, proof = _admit(video_contexts.get(row['race_id']), snapshot, receipt_verifier, now=now)
        verdict = settle(row, by_result[row['race_id']])
        records.append(dict(**deepcopy(lineage), input_as_of=row['as_of'],
            roster_sha256=digest(row['roster']), vectors=video_vectors(snapshot, context),
            winner=verdict['winning_combination'], payout=verdict['payout_per_100_yen'],
            video_context_sha256=context['context_sha256'] if context else None,
            video_receipt_proof=proof))
    records.sort(key=lambda row: (existing.ts(row['result_captured_at']), row['race_id']))
    train, holdout = _split(records)
    supports = _supports(train)
    fitted = (len(records) >= existing.MIN_RACES and len(train) >= 6 and
              any(value >= MIN_VIDEO_SUPPORT for value in supports[len(existing.FEATURES):]))
    public_rows = [{key: deepcopy(value) for key, value in row.items()
                   if key not in ('vectors', 'winner', 'payout')} for row in records]
    out = dict(schema=SCHEMA_TRAIN, created_at=now.isoformat(),
        state='FITTED_VIDEO_EXPERIMENTAL' if fitted else 'INSUFFICIENT_VIDEO_SUPPORT',
        model_version=MODEL_VERSION, feature_schema=list(FEATURES),
        video_feature_schema=[dict(feature_id=f, phase=p, metric_name=m, unit=u) for f,p,m,u in FEATURE_SCHEMA],
        normalization=NORMALIZATION, source_family_ids=list(MODEL_IDS), unique_races=len(records),
        video_admitted_races=sum(row['video_context_sha256'] is not None for row in records),
        minimum_fit_races=existing.MIN_RACES, minimum_video_train_support=MIN_VIDEO_SUPPORT,
        observed_phase_counts=dict(Counter(row['phase'] for row in records)),
        source_lineage=public_rows, excluded_races=deepcopy(admitted['excluded_races']),
        training_data_sha256=digest(records),
        replay_input_sha256=digest(dict(rows=rows, observations=observations, video_contexts=video_contexts)),
        train_races=len(train), validation_races=len(holdout),
        train_race_ids=[row['race_id'] for row in train], validation_race_ids=[row['race_id'] for row in holdout],
        data_available_until=max((row['result_captured_at'] for row in records), key=existing.ts) if records else None,
        feature_support_train=dict(zip(FEATURE_IDS, supports[len(existing.FEATURES):])),
        base_feature_support_train=dict(zip(existing.FEATURES, supports[:len(existing.FEATURES)])),
        training_policy=_policy(),
        models={}, target_scope='OPERATOR_SUPPLIED_RESEARCH', calibrated=False,
        auto_promoted=False, accuracy_improvement_proven=False, production_eligible=False,
        raw_report_validation_status='UNVALIDATED', independent_human_heldout_verified=False,
        validation_type='RETROSPECTIVE_AVAILABILITY_ORDERED_HOLDOUT',
        limitations=['Controlled fitting does not establish real video validity or outcome improvement.',
            'Pixel measurements are normalized only within a comparable feature/race context.',
            'Directions are signed learned coefficients; raw radius has no assigned quality direction.',
            'Pairs with overlapping uncertainty intervals contribute no contrast or directional evidence.',
            'Unsupported video coefficients remain zero; no automatic production adoption.',
            'Independent human heldout validation remains unsatisfied.'])
    for mid in MODEL_IDS:
        base = list(WEIGHTS[mid]) + [0.] * len(FEATURE_IDS)
        weights = _fit(train, supports, mid) if fitted else base[:]
        out['models'][mid] = dict(model_id=mid, model_version=MODEL_VERSION,
            weights=weights, base_weights=base, video_weights=weights[len(existing.FEATURES):],
            coefficients_changed=weights != base,
            training=existing._metrics(train, weights), holdout=existing._metrics(holdout, weights),
            holdout_baseline=existing._metrics(holdout, base), calibrated=False,
            performance_claim='NOT_A_PROSPECTIVE_ACCURACY_RESULT')
    return existing.seal(out, 'training_sha256')


def verify_video_training(training):
    """Check sealed experimental semantics; external archive authentication is separate."""
    existing.check(training, 'training_sha256')
    existing.need(training['schema'] == SCHEMA_TRAIN and training['feature_schema'] == list(FEATURES) and
        training['video_feature_schema'] == [dict(feature_id=f, phase=p, metric_name=m, unit=u)
                                            for f,p,m,u in FEATURE_SCHEMA] and
        training['normalization'] == NORMALIZATION and training['source_family_ids'] == list(MODEL_IDS) and
        training['model_version'] == MODEL_VERSION and set(training['models']) == set(MODEL_IDS),
        'video training schema or existing family mismatch')
    existing.need(training['training_policy'] == _policy() and
        training['minimum_fit_races'] == existing.MIN_RACES and
        training['minimum_video_train_support'] == MIN_VIDEO_SUPPORT,
        'video training policy mismatch')
    existing.need(all(training[key] is False for key in ('auto_promoted', 'accuracy_improvement_proven',
        'calibrated', 'production_eligible', 'independent_human_heldout_verified')) and
        training['raw_report_validation_status'] == 'UNVALIDATED' and
        training['target_scope'] == 'OPERATOR_SUPPLIED_RESEARCH', 'video training certification claim')
    existing.need(training['state'] in ('FITTED_VIDEO_EXPERIMENTAL', 'INSUFFICIENT_VIDEO_SUPPORT'),
                  'video training state')
    ids = [row['race_id'] for row in training['source_lineage']]
    train_ids, validation_ids = training['train_race_ids'], training['validation_race_ids']
    existing.need(len(ids) == len(set(ids)) == training['unique_races'] and
        len(train_ids) == training['train_races'] and len(validation_ids) == training['validation_races'] and
        len(train_ids) == len(set(train_ids)) and len(validation_ids) == len(set(validation_ids)) and
        not set(train_ids) & set(validation_ids) and set(train_ids) | set(validation_ids) == set(ids),
        'video training race split mismatch')
    by_id = {row['race_id']: row for row in training['source_lineage']}
    if train_ids and validation_ids:
        existing.need(max(existing.ts(by_id[r]['result_captured_at']) for r in train_ids) <
                      min(existing.ts(by_id[r]['result_captured_at']) for r in validation_ids),
                      'simultaneous or unordered video holdout')
    supports = training['feature_support_train']
    existing.need(set(supports) == set(FEATURE_IDS) and all(type(s) is int and
        0 <= s <= training['train_races'] for s in supports.values()), 'video train support mismatch')
    fitted = training['state'] == 'FITTED_VIDEO_EXPERIMENTAL'
    if fitted:
        existing.need(training['unique_races'] >= existing.MIN_RACES and training['train_races'] >= 6 and
            any(s >= MIN_VIDEO_SUPPORT for s in supports.values()), 'insufficient fitted video support')
    base_supports = training['base_feature_support_train']
    existing.need(set(base_supports) == set(existing.FEATURES) and all(type(s) is int and
        0 <= s <= training['train_races'] for s in base_supports.values()), 'base train support mismatch')
    created = existing.ts(training['created_at'])
    from .frozen_day_cycle import check_clock
    availability = []
    for row in training['source_lineage']:
        check_clock(row['input_as_of'], row['cutoff_at'], row['input_saved_at'])
        cutoff, as_of = existing.ts(row['cutoff_at']), existing.ts(row['input_as_of'])
        saved, result_at = existing.ts(row['input_saved_at']), existing.ts(row['result_captured_at'])
        existing.need(result_at >= cutoff, 'video training result precedes cutoff')
        availability.extend((saved, result_at))
        proof = row['video_receipt_proof']
        existing.need(proof is None or row['phase'] == 'P1',
                      'current exhibition video training lineage must be P1')
        existing.need(row['video_context_sha256'] is None or type(proof) is dict and
            proof.get('context_sha256') == row['video_context_sha256'], 'video lineage receipt binding mismatch')
        if proof is not None:
            existing.need(type(proof) is dict and set(proof) == {'context_sha256', 'id', 'digest', 'created_at'} and
                type(proof['id']) is int and proof['id'] > 0 and type(proof['digest']) is str and
                _SHA.fullmatch(proof['digest']), 'video lineage receipt identity')
            video_saved = existing.ts(proof['created_at'])
            existing.need(video_saved + existing.timedelta_one_second() <= as_of < cutoff,
                          'video lineage receipt interval not available pre-cutoff')
            availability.append(video_saved)
    existing.need(all(available <= created for available in availability), 'training precedes source availability')
    if availability:
        existing.need(existing.ts(training['data_available_until']) == max(availability),
                      'video training availability differs from source lineage')
    else:
        existing.need(training['data_available_until'] is None, 'empty training availability mismatch')
    for mid, model in training['models'].items():
        weights = model['weights']; base = list(WEIGHTS[mid]) + [0.] * len(FEATURE_IDS)
        existing.need(model['model_id'] == mid and model['model_version'] == MODEL_VERSION and
            model['base_weights'] == base and type(weights) is list and len(weights) == len(FEATURES) and
            all(type(weight) in (int,float) and math.isfinite(weight) and
                (0. <= weight <= 4. if j < len(existing.FEATURES) else -4. <= weight <= 4.)
                for j,weight in enumerate(weights)) and model['video_weights'] == weights[len(existing.FEATURES):] and
            model['calibrated'] is False and model['performance_claim'] == 'NOT_A_PROSPECTIVE_ACCURACY_RESULT',
            'invalid video fitted parameters')
        existing.need(all(weights[j] == base[j] for j,feature in enumerate(existing.FEATURES)
            if base_supports[feature] < MIN_VIDEO_SUPPORT), 'unsupported original coefficient changed')
        existing.need(all(weights[len(existing.FEATURES)+j] == 0. for j,feature in enumerate(FEATURE_IDS)
            if supports[feature] < MIN_VIDEO_SUPPORT), 'unsupported video coefficient changed')
        existing.need(fitted or weights == base, 'insufficient video support must retain zero additions')


def replay_video_training(training, rows, observations, video_contexts, *, now, receipt_verifier=None):
    """Recompute exact parameters/metrics from independently reauthenticated inputs."""
    verify_video_training(training)
    recreated = fit_with_video(rows, observations, video_contexts, now=now, receipt_verifier=receipt_verifier)
    existing.need(recreated == training, 'video training deterministic replay differs')
    return True


def make_video_shadows(snapshot, baseline_suite, context, video_context, *, receipt_verifier=None):
    """Score a separately frozen prior artifact; no target result enters this path."""
    if context is None or video_context is None or receipt_verifier is None:
        return []
    snapshot, baseline_suite, context, video_context = deepcopy((snapshot, baseline_suite, context, video_context))
    training, receipt = context['training'], context['receipt']
    verify_video_training(training)
    if training['state'] != 'FITTED_VIDEO_EXPERIMENTAL':
        return []
    _validate(snapshot)
    existing.check(baseline_suite, 'suite_sha256')
    existing.need(snapshot['scope'] == training['target_scope'], 'video training/inference scope mismatch')
    existing.need(baseline_suite['snapshot_sha256'] == digest(snapshot), 'video candidate/baseline input mismatch')
    existing.need(receipt.get('expired') is False and
        receipt.get('workflow_run', {}).get('head_repository_id') == 1416489937 and
        type(receipt.get('digest')) is str and _SHA.fullmatch(receipt['digest']), 'video training receipt identity')
    created, saved, as_of = existing.ts(training['created_at']), existing.ts(receipt['created_at']), existing.ts(snapshot['as_of'])
    existing.need(created <= saved+existing.timedelta_one_second() and saved < as_of and created < as_of and
        existing.ts(training['data_available_until']) <= created, 'video training/receipt must precede input')
    target = _target(snapshot)['race_id']
    existing.need(target not in {row['race_id'] for row in training['source_lineage']}, 'target result leaked into video training')
    admitted, proof = _admit(video_context, snapshot, receipt_verifier)
    if admitted is None:
        return []
    vectors = video_vectors(snapshot, admitted)
    out = []
    for mid in MODEL_IDS:
        model = training['models'][mid]
        ranked = _all_triples(vectors, model['weights'])
        record = dict(schema=SCHEMA_SHADOW, variant='LEARNED_VIDEO_EXPERIMENTAL',
            model_id=mid, model_version=MODEL_VERSION, race_id=target, stage=snapshot['stage'],
            as_of=snapshot['as_of'], cutoff_at=snapshot['sales_cutoff_at'], input_sha256=digest(snapshot),
            training_sha256=training['training_sha256'], training=deepcopy(training),
            training_receipt=deepcopy(receipt), video_context=deepcopy(admitted), video_receipt_proof=proof,
            video_receipt=deepcopy(video_context['receipt']), video_context_sha256=admitted['context_sha256'],
            baseline_model_sha256=baseline_suite['models'][mid]['prediction_sha256'],
            candidates=ranked, ordered_top8=[row['combination'] for row in ranked[:8]], candidate_count=120,
            calibrated=False, auto_promoted=False, actual_purchases=False, production_eligible=False,
            raw_report_validation_status='UNVALIDATED', independent_human_heldout_verified=False,
            performance_claim='NOT_A_PROSPECTIVE_ACCURACY_RESULT')
        out.append(existing.seal(record, 'prediction_sha256'))
    return out
