"""Supervised six-phase transitions, only where real phase labels are available.

Training conditions each phase on the previous *observed* full order. Prediction
conditions it on the previous *sampled* order, integrating over uncertain paths.
This is a statistical transition model, not a calibrated physical simulation.
No video labels means HOLD; the ordinary finish model remains usable separately.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone

import numpy as np

from .features import _bind_feature_input
from .model import RankModel, digest, fit_ranker, _verify_feature_binding
from .observations import PhaseObservation, Provenance, SourceKind, utc

PHASES = ('INITIAL', 'BELL', 'FINAL_HOME', 'FINAL_BACK', 'FOURTH_CORNER', 'GOAL')


def _state_row(row, previous, origin, *, past_orders=None):
    _verify_feature_binding(row)
    cars = [r['car'] for r in row['riders']]
    if previous is not None and (len(previous) != len(cars) or set(previous) != set(cars)):
        raise ValueError('PREVIOUS_PHASE_FULL_ORDER_REQUIRED')
    extra = np.array([[previous.index(car) / max(1, len(cars) - 1) if previous else 0., float(previous is None)] for car in cars])
    out = dict(row, features=np.concatenate((np.asarray(row['features']), extra), axis=1),
               feature_names=tuple(row['feature_names']) + ('phase_previous_rank', 'phase_previous_unknown'),
               feature_version=row.get('feature_version', 'supplied-features') + '+phase-state-v1',
               feature_status=row.get('feature_status', 'READY'), feature_scope='CONDITIONAL_PHASE_STATE',
               history_evidence=dict(row.get('history_evidence', {}), phase_state={'order': previous, 'origin': origin}))
    from .abilities import uses_abilities, phase_state_features, STATE_NAMES
    if uses_abilities(row['feature_names']):
        orders=[] if past_orders is None else past_orders
        if (orders[-1] if orders else None)!=previous:
            raise ValueError('DYNAMIC_PHASE_PREVIOUS_ORDER_MISMATCH')
        out['features']=np.concatenate((out['features'],phase_state_features(row,orders)),axis=1)
        out['feature_names']+=STATE_NAMES
        out['feature_version']+='+dynamic-state-v1'
        out['history_evidence']['phase_state']['past_orders']=orders
    return _bind_feature_input(out)


def fit_phase_bundle(rows, observations, *, train_before, available_by, min_races=30, max_iter=120):
    from datetime import date
    date.fromisoformat(train_before)
    if type(min_races) is not int or min_races < 30:
        raise ValueError('PHASE_MINIMUM_30_NOT_CERTIFICATION')
    cutoff = utc(available_by)
    if any(r['day'] >= train_before for r in rows):
        raise ValueError('PHASE_TRAINING_DATE')
    for row in rows:
        _verify_feature_binding(row)
    index = {r['race_id']: r for r in rows}
    if len(index) != len(rows):
        raise ValueError('DUPLICATE_PHASE_TRAINING_RACE')
    accepted, excluded = {}, Counter()
    for raw in observations:
        if isinstance(raw, PhaseObservation):
            observation = raw
        else:
            value = dict(raw)
            value['provenance'] = Provenance(**value['provenance'])
            observation = PhaseObservation(**value)
        if observation.provenance.kind not in (SourceKind.OFFICIAL_RECORD, SourceKind.REVIEWED_VIDEO):
            excluded['unreviewed_source'] += 1
            continue
        if utc(observation.provenance.available_at) > cutoff:
            excluded['not_available_by_training_freeze'] += 1
            continue
        row = index.get(observation.race_id)
        if row is None:
            excluded['no_bound_pre_race_features'] += 1
            continue
        cars = [r['car'] for r in row['riders']]
        if not observation.complete or sorted(observation.order) != sorted(cars):
            excluded['incomplete_phase_order'] += 1
            continue
        key = observation.race_id, observation.phase
        if key in accepted:
            raise ValueError('DUPLICATE_OR_CONFLICTING_PHASE_LABEL')
        accepted[key] = observation
    models, coverage = {}, {}
    for i, phase in enumerate(PHASES):
        training = []
        for rid, row in index.items():
            label = accepted.get((rid, phase))
            previous = accepted.get((rid, PHASES[i - 1])) if i else None
            if label is None or i and previous is None or row.get('feature_status', 'READY') != 'READY':
                continue
            from .abilities import uses_abilities
            earlier=[accepted.get((rid,p)) for p in PHASES[:i]]
            if uses_abilities(row['feature_names']) and any(p is None for p in earlier):
                continue
            state = _state_row(row, list(previous.order) if previous else None, 'observed_training_state',
                past_orders=[list(p.order) for p in earlier if p is not None])
            state.update(finish=list(label.order), top3=list(label.order[:3]))
            training.append(state)
        coverage[phase] = {'usable_label_pairs': len(training), 'status': 'HOLD'}
        if len(training) >= min_races:
            model = fit_ranker(training, before=train_before, max_iter=max_iter)
            model.fit_meta['phase'] = phase
            model.fit_meta['label_available_by'] = available_by
            model.fit_meta['label_scope'] = 'source-declared official or independently reviewed video; authenticity remains externally verified'
            models[phase] = model.to_dict()
            coverage[phase]['status'] = 'FITTED_UNVALIDATED'
    artifact = {'schema': 'dt-r1-six-phase-transition-v1', 'models': models, 'coverage': coverage,
                'excluded': dict(excluded), 'training_before': train_before, 'available_by': available_by,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'observation_sha256': digest([asdict(v) for _, v in sorted(accepted.items())]),
                'real_trajectory_validation': False, 'confidence': 'HOLD'}
    artifact['artifact_sha256'] = digest(artifact)
    return artifact


def forecast_phase_paths(bundle, row, *, prediction_at=None, samples=64, seed=731, favorite_car=None):
    from .pipeline import validate_prediction_inputs
    _verify_feature_binding(row)
    validate_prediction_inputs(row, prediction_at=prediction_at)
    if digest({k: v for k, v in bundle.items() if k != 'artifact_sha256'}) != bundle.get('artifact_sha256'):
        raise ValueError('PHASE_ARTIFACT_HASH_MISMATCH')
    if bundle.get('schema') != 'dt-r1-six-phase-transition-v1' or type(samples) is not int or not 1 <= samples <= 4096:
        raise ValueError('PHASE_BUNDLE_OR_SAMPLE_COUNT_INVALID')
    if row.get('cohort') == 'prospective':
        if prediction_at is None or utc(bundle['created_at']) > utc(prediction_at) or utc(bundle['available_by']) > utc(prediction_at):
            raise ValueError('PHASE_MODEL_FROM_FUTURE')
        if row['day'] < bundle['training_before']:
            raise ValueError('PHASE_TRAINING_NOT_BEFORE_TARGET')
    missing = [phase for phase in PHASES if phase not in bundle['models']]
    if missing:
        return {'status': 'HOLD', 'reason': 'INSUFFICIENT_OBSERVED_PHASE_TRANSITIONS', 'missing_phases': missing,
                'paths': [], 'confidence': 'HOLD', 'coverage': bundle['coverage']}
    models = {phase: RankModel.from_dict(bundle['models'][phase]) for phase in PHASES}
    for model in models.values():
        validate_prediction_inputs(row, prediction_at=prediction_at, model_meta=model.fit_meta)
    rng = np.random.default_rng(seed)
    paths = Counter()
    cars = [r['car'] for r in row['riders']]
    counts = {phase: np.zeros((len(cars), len(cars))) for phase in PHASES}
    if favorite_car is not None and favorite_car not in cars:
        raise ValueError('FAVORITE_NOT_IN_ROSTER')
    failure_counts=Counter(); condition_counts=Counter(); finish_counts=Counter()
    for _ in range(samples):
        previous, path = None, []
        for phase in PHASES:
            state = _state_row(row, previous, 'sampled_predictive_state',past_orders=[list(o) for o in path])
            _, base, pairs = models[phase]._prepared(state)
            mask, order = 0, []
            for rank in range(len(cars)):
                available, probs = models[phase]._choice(base, pairs, mask)
                chosen = int(rng.choice(available, p=probs))
                mask |= 1 << chosen
                order.append(cars[chosen])
                counts[phase][chosen, rank] += 1
            path.append(tuple(order))
            previous = order
        paths[tuple(path)] += 1
        finish_counts[path[-1][:3]]+=1
        if favorite_car is not None:
            lost=path[-1][0]!=favorite_car
            for phase,order in zip(PHASES[:-1],path[:-1]):
                label=(phase,'front' if order[0]==favorite_car else 'not_front')
                condition_counts[label]+=1;failure_counts[label]+=int(lost)
    return {'status': 'SAMPLED_UNVALIDATED', 'confidence': 'HOLD', 'samples': samples, 'seed': seed,
            'scope': 'statistical phase paths, no measured speed/power/fatigue; frequencies are not calibrated confidence',
            'paths': [{'phases': [{'phase': phase, 'order': list(order)} for phase, order in zip(PHASES, path)],
                       'sample_count': n, 'sample_fraction': n / samples}
                      for path, n in paths.most_common(8)],
            'phase_marginals': {phase: [{'car': car, 'position_probabilities': (matrix[i] / samples).tolist()}
                                       for i, car in enumerate(cars)] for phase, matrix in counts.items()},
            'finish_samples':[{'cars':list(k),'sample_count':v,'sample_fraction':v/samples} for k,v in finish_counts.most_common()],
            'favorite_failure_paths':{'favorite_car':favorite_car,'scope':'sampled conditional associations, not causal or calibrated',
                'conditions':[{'phase':k[0],'position':k[1],'sample_count':v,'loss_count':failure_counts[k],
                    'sample_loss_fraction':failure_counts[k]/v} for k,v in sorted(condition_counts.items())]},
            'artifact_sha256': bundle['artifact_sha256']}
