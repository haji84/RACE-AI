"""Learn a coherent conditional finishing-order distribution on CPU.

At each rank, a softmax chooses from the remaining starters. Its scores use
pre-race features and learned effects of line members already selected. Those
effects depend on the selected *set*, so exact full-rank marginals need only
2**N states, not N! enumerated finishes. They are statistical dependence, not
measured drafting, power, fatigue or a video-verified race trajectory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from math import log
from typing import Sequence

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

MODEL_ID = 'chatgpt-dt-r1'
SCHEMA = 'dt-r1-conditional-ranking-v1'
PAIR_NAMES = ('same_line', 'selected_predecessor', 'selected_successor',
              'selected_line_head', 'same_line_score_gap', 'other_line_head_selected')


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('ISO_DAY_REQUIRED')
    return value


def _cars(row):
    cars = [r['car'] for r in row['riders']]
    if not (3 <= len(cars) <= 9 and len(set(cars)) == len(cars)
            and all(type(c) is int and 1 <= c <= 9 for c in cars)):
        raise ValueError('VALID_ROSTER_REQUIRED')
    return cars


def _verify_feature_binding(row, *, required=False):
    supplied = row.get('feature_input_sha256')
    if supplied is None:
        if required or row.get('feature_version'):
            raise ValueError('FEATURE_INPUT_HASH_REQUIRED')
        return
    from .features import _bind_feature_input
    try:
        expected = _bind_feature_input(dict(row))['feature_input_sha256']
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError('FEATURE_INPUT_HASH_INVALID') from error
    if supplied != expected:
        raise ValueError('FEATURE_INPUT_HASH_MISMATCH')


def pair_features(row):
    """C[i,j] describes candidate i after j has already finished ahead of it."""
    cars = _cars(row)
    n = len(cars)
    out = np.zeros((n, n, len(PAIR_NAMES)), dtype=np.float64)
    if not row.get('lines_known', False) or not row.get('lines_applicable', True):
        return out
    groups = row.get('line_groups', [])
    if any(not g for g in groups) or sorted(c for g in groups for c in g) != sorted(cars):
        raise ValueError('LINE_PARTITION')
    positions = {c: (g, p) for g, line in enumerate(groups) for p, c in enumerate(line)}
    points = {r['car']: r.get('competition_points') for r in row['riders']}
    for i, ci in enumerate(cars):
        gi, pi = positions[ci]
        for j, cj in enumerate(cars):
            if i == j:
                continue
            gj, pj = positions[cj]
            same = gi == gj
            gap = 0.
            if same and points[ci] is not None and points[cj] is not None:
                gap = float(np.clip((points[ci] - points[cj]) / 20., -3., 3.))
            out[i, j] = (same, same and pj == pi - 1, same and pj == pi + 1,
                         same and pj == 0, gap, not same and pi == 0 and pj == 0)
    return out


@dataclass
class RankModel:
    feature_names: tuple[str, ...]
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    pair_weights: np.ndarray
    temperature: float = 1.
    fit_meta: dict = field(default_factory=dict)

    @classmethod
    def zero(cls, feature_names):
        names = tuple(feature_names)
        return cls(names, np.zeros(len(names)), np.ones(len(names)),
                   np.zeros((4, len(names))), np.zeros((4, len(PAIR_NAMES))))

    def _prepared(self, row):
        if row.get('feature_status', 'READY') != 'READY':
            raise ValueError(row['feature_status'])
        cars = _cars(row)
        if tuple(row['feature_names']) != self.feature_names:
            raise ValueError('FEATURE_SCHEMA_MISMATCH')
        x = np.asarray(row['features'], dtype=np.float64)
        if x.shape != (len(cars), len(self.feature_names)) or not np.isfinite(x).all():
            raise ValueError('FINITE_FEATURE_MATRIX_REQUIRED')
        _verify_feature_binding(row, required=self.fit_meta.get('feature_digest_required', False))
        if not np.isfinite(self.temperature) or self.temperature <= 0:
            raise ValueError('TEMPERATURE_INVALID')
        # Scaling is fitted on the training set only. Clipping bounds extrapolation.
        x = np.clip((x - self.mean) / self.scale, -12., 12.)
        return cars, x @ self.weights.T, pair_features(row)

    def _choice(self, base, pairs, mask):
        n = len(base)
        selected = [j for j in range(n) if mask & (1 << j)]
        remaining = [j for j in range(n) if not mask & (1 << j)]
        stage = min(len(selected), 3)
        z = base[:, stage].copy()
        if selected:
            z += pairs[:, selected, :].sum(axis=1) @ self.pair_weights[stage]
        values = z[remaining] / self.temperature
        values -= values.max()
        prob = np.exp(values)
        prob /= prob.sum()
        return remaining, prob

    def distribution(self, row, *, full=False):
        """Exact joint top-3, exacta marginals, optionally every finish position."""
        cars, base, pairs = self._prepared(row)
        triples = []
        pair_mass = {}
        first, pfirst = self._choice(base, pairs, 0)
        for a, pa in zip(first, pfirst):
            second, psecond = self._choice(base, pairs, 1 << a)
            for b, pb in zip(second, psecond):
                third, pthird = self._choice(base, pairs, (1 << a) | (1 << b))
                pair_mass[(cars[a], cars[b])] = float(pa * pb)
                triples.extend({'cars': [cars[a], cars[b], cars[c]],
                                'probability': float(pa * pb * pc)}
                               for c, pc in zip(third, pthird))
        triples.sort(key=lambda t: (-t['probability'], t['cars']))
        exactas = [{'cars': list(k), 'probability': v} for k, v in pair_mass.items()]
        exactas.sort(key=lambda t: (-t['probability'], t['cars']))
        out = {'trifectas': triples, 'exactas': exactas,
               'distribution_condition': 'ordered_numeric_finish_without_ties; incidents not separately modelled'}
        if full:
            n = len(cars)
            reach = np.zeros(1 << n)
            reach[0] = 1.
            marginal = np.zeros((n, n))
            for mask in range((1 << n) - 1):
                if reach[mask] == 0:
                    continue
                rank = mask.bit_count()
                remaining, probs = self._choice(base, pairs, mask)
                for i, p in zip(remaining, probs):
                    mass = reach[mask] * p
                    marginal[i, rank] += mass
                    reach[mask | (1 << i)] += mass
            out['riders'] = [
                {'car': car, 'rank_probabilities': marginal[i].tolist(),
                 'win_probability': float(marginal[i, 0]),
                 'top2_probability': float(marginal[i, :2].sum()),
                 'top3_probability': float(marginal[i, :3].sum()),
                 'expected_rank': float(marginal[i] @ np.arange(1, n + 1))}
                for i, car in enumerate(cars)]
        return out

    def order_probability(self, row, order):
        cars, base, pairs = self._prepared(row)
        order = list(order)
        if not (len(order) == len(cars) and sorted(order) == sorted(cars)):
            raise ValueError('COMPLETE_ORDER_REQUIRED')
        index = {c: i for i, c in enumerate(cars)}
        probability, mask = 1., 0
        for car in order:
            remaining, probs = self._choice(base, pairs, mask)
            i = index[car]
            probability *= float(probs[remaining.index(i)])
            mask |= 1 << i
        return probability

    def top3_log_loss(self, rows):
        values = []
        for row in rows:
            if not row.get('top3'):
                continue
            cars, base, pairs = self._prepared(row)
            if len(set(row['top3'])) != 3 or not set(row['top3']) <= set(cars):
                raise ValueError('TOP3_LABEL_INVALID')
            mask, loss = 0, 0.
            for car in row['top3']:
                choices, p = self._choice(base, pairs, mask)
                i = cars.index(car)
                loss -= log(max(float(p[choices.index(i)]), 1e-300))
                mask |= 1 << i
            values.append(loss)
        if not values:
            raise ValueError('NO_EVALUABLE_RESULTS')
        return float(np.mean(values))

    def explain(self, row, *, count=5):
        """Model score contributions, never causal or physiological claims."""
        cars = _cars(row)
        x = np.clip((np.asarray(row['features']) - self.mean) / self.scale, -12., 12.)
        return [{'car': car, 'scope': 'first_place_log_score_contributions',
                 'terms': sorted(({'feature': name, 'contribution': float(x[i, j] * self.weights[0, j])}
                                  for j, name in enumerate(self.feature_names)),
                                 key=lambda t: -abs(t['contribution']))[:count]}
                for i, car in enumerate(cars)]

    def to_dict(self):
        out = {'schema': SCHEMA, 'model_id': MODEL_ID, 'feature_names': list(self.feature_names),
               'pair_names': list(PAIR_NAMES), 'mean': self.mean.tolist(), 'scale': self.scale.tolist(),
               'weights': self.weights.tolist(), 'pair_weights': self.pair_weights.tolist(),
               'temperature': self.temperature, 'fit_meta': self.fit_meta}
        out['model_sha256'] = digest(out)
        return out

    @classmethod
    def from_dict(cls, artifact):
        raw = dict(artifact)
        expected = raw.pop('model_sha256', None)
        if digest(raw) != expected:
            raise ValueError('ARTIFACT_HASH_MISMATCH')
        if raw.get('schema') != SCHEMA or raw.get('model_id') != MODEL_ID or tuple(raw.get('pair_names', [])) != PAIR_NAMES:
            raise ValueError('MODEL_SCHEMA_INVALID')
        names = tuple(raw['feature_names'])
        if not names or len(names) != len(set(names)) or any(not isinstance(n, str) for n in names):
            raise ValueError('FEATURE_SCHEMA_INVALID')
        arrays = [np.asarray(raw[k], dtype=np.float64) for k in ('mean', 'scale', 'weights', 'pair_weights')]
        expected_shapes = [(len(names),), (len(names),), (4, len(names)), (4, len(PAIR_NAMES))]
        if any(a.shape != s or not np.isfinite(a).all() for a, s in zip(arrays, expected_shapes)):
            raise ValueError('MODEL_ARRAY_INVALID')
        if np.any(arrays[1] <= 0) or not isinstance(raw['temperature'], (int, float)) or not 0 < raw['temperature'] < 100:
            raise ValueError('MODEL_SCALE_INVALID')
        return cls(names, *arrays, float(raw['temperature']), dict(raw['fit_meta']))


def fit_ranker(rows: Sequence[dict], *, before: str, ridge=.01, use_pairs=True,
               max_iter=160, feature_mask=None):
    """Fit first three and (downweighted) observed tail choices on older days.

    Date filtering is a hard validation, not an internal random train/test split.
    The caller must select the model on a separate later period. Records without
    usable top-three labels are explicitly counted, not assigned invented ranks.
    """
    before = _day(before)
    if not rows or not np.isfinite(ridge) or ridge <= 0 or type(max_iter) is not int or max_iter < 1:
        raise ValueError('FIT_ARGUMENTS_INVALID')
    seen = set()
    valid = []
    for row in rows:
        if _day(row['day']) >= before:
            raise ValueError('TRAINING_DATE_NOT_BEFORE_FREEZE')
        if row['race_id'] in seen:
            raise ValueError('DUPLICATE_TRAINING_RACE')
        seen.add(row['race_id'])
        if row.get('feature_status', 'READY') != 'READY':
            continue
        if row.get('top3'):
            valid.append(row)
    if len(valid) < 30:
        raise ValueError('TRAINING_MINIMUM_30_NOT_CERTIFICATION')
    names = tuple(valid[0]['feature_names'])
    f, rcount = len(names), len(valid)
    mask_features = np.ones(f, dtype=bool) if feature_mask is None else np.asarray(feature_mask, dtype=bool)
    if mask_features.shape != (f,):
        raise ValueError('FEATURE_MASK_INVALID')
    samples = []
    for row in valid:
        cars = _cars(row)
        x = np.asarray(row['features'], dtype=float)
        if tuple(row['feature_names']) != names or x.shape != (len(cars), f) or not np.isfinite(x).all():
            raise ValueError('FEATURE_SCHEMA_OR_VALUES_INVALID')
        _verify_feature_binding(row)
        if len(row['top3']) != 3 or len(set(row['top3'])) != 3 or not set(row['top3']) <= set(cars):
            raise ValueError('TOP3_LABEL_INVALID')
        samples.append(x)
    all_x = np.concatenate(samples)
    mean, scale = all_x.mean(axis=0), all_x.std(axis=0)
    scale[scale < 1e-6] = 1.
    x = np.zeros((rcount, 9, f))
    remaining = np.zeros((8, rcount, 9), dtype=bool)
    labels = np.zeros((8, rcount), dtype=int)
    decision = np.zeros((8, rcount), dtype=float)
    context = np.zeros((8, rcount, 9, len(PAIR_NAMES)))
    for ri, (row, raw) in enumerate(zip(valid, samples)):
        cars = _cars(row)
        x[ri, :len(cars)] = np.clip((raw - mean) / scale, -12., 12.) * mask_features
        order = row.get('finish') or row['top3']
        if row.get('finish') and (sorted(order) != sorted(cars) or order[:3] != row['top3']):
            raise ValueError('FINISH_LABEL_INVALID')
        selected, live = [], set(range(len(cars)))
        pair = pair_features(row) if use_pairs else np.zeros((len(cars), len(cars), len(PAIR_NAMES)))
        for pos, car in enumerate(order[:8]):
            if len(live) <= 1:
                break
            remaining[pos, ri, list(live)] = True
            labels[pos, ri] = cars.index(car)
            decision[pos, ri] = 1. if pos < 3 else .25
            if selected:
                context[pos, ri, :len(cars)] = pair[:, selected, :].sum(1)
            selected.append(cars.index(car))
            live.remove(cars.index(car))
    flat_x = x.reshape(-1, f)
    # Avoid -inf - -inf on rows that have no decision at a particular tail rank.
    for pos in range(8):
        remaining[pos, decision[pos] == 0, 0] = True
    chosen = np.arange(rcount)
    normalizer = float(rcount)
    pcount = len(PAIR_NAMES)

    def objective(theta):
        weights = theta[:4 * f].reshape(4, f)
        pairw = theta[4 * f:].reshape(4, pcount)
        base = (flat_x @ weights.T).reshape(rcount, 9, 4)
        grad_base = np.zeros_like(base)
        grad_pair = np.zeros_like(pairw)
        loss = 0.
        for pos in range(8):
            group = min(pos, 3)
            z = base[:, :, group] + context[pos] @ pairw[group]
            z = np.where(remaining[pos], z, -np.inf)
            normal = logsumexp(z, axis=1)
            loss += float(((normal - z[chosen, labels[pos]]) * decision[pos]).sum())
            diff = np.exp(z - normal[:, None])
            diff[chosen, labels[pos]] -= 1.
            diff *= decision[pos, :, None]
            grad_base[:, :, group] += diff
            grad_pair[group] += np.einsum('ri,rip->p', diff, context[pos], optimize=True)
        grad_weight = grad_base.reshape(-1, 4).T @ flat_x
        gradient = np.concatenate((grad_weight.ravel(), grad_pair.ravel())) / normalizer
        penalty = ridge * float(theta @ theta) / 2
        return loss / normalizer + penalty, gradient + ridge * theta

    start = np.zeros(4 * (f + pcount))
    fitted = minimize(objective, start, method='L-BFGS-B', jac=True,
                      options={'maxiter': max_iter, 'ftol': 1e-9, 'gtol': 1e-5, 'maxls': 30})
    if not np.isfinite(fitted.x).all() or not np.isfinite(fitted.fun):
        raise ValueError('OPTIMIZATION_FAILED_NONFINITE')
    weights = fitted.x[:4 * f].reshape(4, f) * mask_features
    pairw = fitted.x[4 * f:].reshape(4, pcount)
    if not use_pairs:
        pairw[:] = 0
    meta = {'fit_before_day': before, 'training_first_day': min(r['day'] for r in valid),
            'training_last_day': max(r['day'] for r in valid), 'training_races': rcount,
            'input_races': len(rows), 'no_top3_label': len(rows) - rcount,
            'ridge': ridge, 'use_pairs': bool(use_pairs), 'iterations': int(fitted.nit),
            'optimizer_converged': bool(fitted.success), 'optimizer_message': str(fitted.message),
            'objective': float(fitted.fun), 'feature_mask': mask_features.tolist(),
            'training_fingerprint': digest([{'race_id': r['race_id'], 'input': r['input_sha256'],
                                            'features': r.get('feature_input_sha256') or digest({'names': list(r['feature_names']), 'values': np.asarray(r['features']).tolist()}),
                                            'finish': r.get('finish'), 'top3': r['top3']} for r in valid]),
            'feature_digest_required': any(r.get('feature_version') for r in valid),
            'created_at': datetime.now(timezone.utc).isoformat(),
            'cohort': 'retrospective_archived_inputs_no_pre_cutoff_attestation'}
    return RankModel(names, mean, scale, weights, pairw, fit_meta=meta)


def fit_temperature(model, rows, *, start_day, end_day):
    """Optional scalar distribution calibration on a separately declared period."""
    start_day, end_day = _day(start_day), _day(end_day)
    if start_day <= model.fit_meta.get('training_last_day', '') or start_day > end_day:
        raise ValueError('CALIBRATION_OVERLAPS_TRAINING')
    if any(not start_day <= r['day'] <= end_day for r in rows):
        raise ValueError('CALIBRATION_DATE_OUTSIDE_DECLARED_PERIOD')
    original = model.temperature
    def loss(value):
        model.temperature = float(np.exp(value[0]))
        return model.top3_log_loss(rows)
    result = minimize(loss, np.array([0.]), method='L-BFGS-B', bounds=[(log(.35), log(3.))])
    model.temperature = original
    if not result.success or not np.isfinite(result.fun):
        raise ValueError('TEMPERATURE_FIT_FAILED')
    clone = RankModel.from_dict(model.to_dict())
    clone.temperature = float(np.exp(result.x[0]))
    clone.fit_meta['created_at'] = datetime.now(timezone.utc).isoformat()
    clone.fit_meta['parameter_information_end_day'] = max(end_day, clone.fit_meta.get('parameter_information_end_day', ''),
                                                          clone.fit_meta.get('training_last_day', ''))
    clone.fit_meta['temperature_calibration'] = {'start_day': start_day, 'end_day': end_day,
                                                 'races': len(rows), 'loss': float(result.fun)}
    return clone
