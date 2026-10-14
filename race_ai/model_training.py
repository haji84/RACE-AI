"""Deterministic chronological offline learning; never live accuracy evidence.

Only explicit pre-race feature snapshots enter the model. Official labels stay
separate. Final-test rows never influence fitting, scaling, calibration or the
research-only model choice. No provider, network client or promotion is used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from . import prediction
from .money import recommend_allocation


class TrainingError(prediction.PredictionError):
    """Invalid offline research input or unavailable model/feature evidence."""


# A narrow typed schema prevents generic current-outcome fields entering a
# feature table. Source truth and derivation lineage remain caller obligations.
FEATURES = {
    'lane_bias': (-1000000, 1000000, 'supplied pre-race lane feature'),
    'historical_win_rate': (0, 1, 'past-only first-place fraction'),
    'historical_mean_st': (0, 1, 'past-only mean start seconds'),
    'motor_residual': (-1, 1, 'past-only adjusted motor residual'),
    'exhibition_time': (0, 100, 'pre-race exhibition seconds'),
    'exhibition_st': (0, 1, 'pre-race exhibition start seconds'),
    'predicted_course': (1, 6, 'predicted course, never current actual course'),
    'market_implied_win_probability': (0, 1, 'pre-race market-derived fraction'),
}


def _time(value):
    try:
        return prediction._time(value)
    except prediction.PredictionError as exc:
        raise TrainingError(str(exc)) from exc


def _stamp(value):
    return _time(value).isoformat(timespec='microseconds')


def _number(value, name, lower, upper):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not lower <= value <= upper
            or not math.isfinite(value)):
        raise TrainingError(f'invalid finite {name}')
    return float(value)


def _id(value, name):
    try:
        return prediction._id(value, name)
    except prediction.PredictionError as exc:
        raise TrainingError(str(exc)) from exc


def _description(value, name):
    try:
        return prediction._description(value, name, 256)
    except prediction.PredictionError as exc:
        raise TrainingError(str(exc)) from exc


def _json(value):
    try:
        return prediction._json(value)
    except prediction.PredictionError as exc:
        raise TrainingError(str(exc)) from exc


def _sha(value):
    try:
        return prediction._sha(value)
    except prediction.PredictionError as exc:
        raise TrainingError(str(exc)) from exc


def _feature_names(value):
    if (not isinstance(value, list) or not 1 <= len(value) <= 8
            or any(not isinstance(x, str) or x not in FEATURES for x in value)
            or len(set(value)) != len(value)):
        raise TrainingError('distinct supported pre-race feature_names required')
    return value[:]


def _configuration(value):
    keys = {'feature_names', 'train_end_at', 'validation_end_at', 'evaluation_as_of',
            'epochs', 'learning_rate', 'l2', 'temperature_grid', 'calibration_bins'}
    if not isinstance(value, dict) or set(value) != keys:
        raise TrainingError('configuration must contain exactly the documented fields')
    config = dict(value, feature_names=_feature_names(value['feature_names']))
    train, validation, evaluation = (_time(value[key]) for key in ('train_end_at', 'validation_end_at', 'evaluation_as_of'))
    if not train < validation < evaluation:
        raise TrainingError('train_end_at < validation_end_at < evaluation_as_of required')
    if evaluation > datetime.now(timezone.utc):
        raise TrainingError('future evaluation cutoff cannot establish observed outcomes')
    for key in ('train_end_at', 'validation_end_at', 'evaluation_as_of'):
        config[key] = _stamp(value[key])
    if type(value['epochs']) is not int or not 1 <= value['epochs'] <= 2000:
        raise TrainingError('epochs must be 1..2000')
    if type(value['calibration_bins']) is not int or not 1 <= value['calibration_bins'] <= 100:
        raise TrainingError('calibration_bins must be 1..100')
    config['learning_rate'] = _number(value['learning_rate'], 'learning_rate', 0.000001, 1)
    config['l2'] = _number(value['l2'], 'l2', 0, 100)
    grid = value['temperature_grid']
    if not isinstance(grid, list) or not 1 <= len(grid) <= 8:
        raise TrainingError('one to eight calibration temperatures required')
    config['temperature_grid'] = sorted(_number(t, 'temperature', .25, 8) for t in grid)
    if len(set(config['temperature_grid'])) != len(grid):
        raise TrainingError('duplicate calibration temperatures')
    return config


def _record(value, names, *, labeled):
    keys = {'race_id', 'race_start_at', 'as_of', 'source_kind', 'boats'} | ({'label'} if labeled else set())
    if not isinstance(value, dict) or set(value) != keys:
        raise TrainingError('record must contain exactly the documented pre-race fields and separate label')
    race = _id(value['race_id'], 'race_id')
    cutoff, start = _time(value['as_of']), _time(value['race_start_at'])
    if not cutoff < start:
        raise TrainingError('pre-race feature cutoff must precede start')
    if value['source_kind'] not in ('synthetic', 'operator_supplied', 'official_source_attested'):
        raise TrainingError('explicit source_kind required')
    raw_boats = value['boats']
    if not isinstance(raw_boats, list) or len(raw_boats) != 6:
        raise TrainingError('six explicit boat snapshots required')
    boats, lanes = [], set()
    for row in raw_boats:
        if not isinstance(row, dict) or set(row) != {'lane', 'features', 'available_at', 'captured_at', 'generated_at', 'source_ref'}:
            raise TrainingError('unsupported boat fields, including current outcome features')
        lane = row['lane']
        if type(lane) is not int or lane not in range(1, 7) or lane in lanes:
            raise TrainingError('six unique boat identities required')
        lanes.add(lane)
        available, captured, generated = (_time(row[key]) for key in ('available_at', 'captured_at', 'generated_at'))
        if not available <= captured <= cutoff or generated > cutoff:
            raise TrainingError('feature snapshot is unavailable at pre-race cutoff')
        if not isinstance(row['features'], dict) or set(row['features']) != set(names):
            raise TrainingError('complete exact feature schema required; no missing or outcome values')
        features = {name: _number(row['features'][name], name, FEATURES[name][0], FEATURES[name][1]) for name in names}
        boats.append(dict(lane=lane, features=features, available_at=_stamp(row['available_at']),
                          captured_at=_stamp(row['captured_at']), generated_at=_stamp(row['generated_at']),
                          source_ref=_description(row['source_ref'], 'source_ref')))
    clean = dict(race_id=race, race_start_at=_stamp(value['race_start_at']), as_of=_stamp(value['as_of']),
                 source_kind=value['source_kind'], boats=sorted(boats, key=lambda row: row['lane']))
    if labeled:
        label = value['label']
        if not isinstance(label, dict) or set(label) != {'status', 'confirmed', 'top3', 'available_at', 'captured_at', 'source_ref'}:
            raise TrainingError('separate complete timestamped official label required')
        if label['confirmed'] is not True:
            raise TrainingError('unconfirmed result label')
        if label['status'] not in ('settled', 'dead_heat', 'cancelled', 'no_contest', 'postponed', 'special'):
            raise TrainingError('unsupported result status')
        available, captured = _time(label['available_at']), _time(label['captured_at'])
        if not start <= available <= captured:
            raise TrainingError('official label must be available/captured after start')
        top3 = label['top3']
        if label['status'] == 'settled' and (not isinstance(top3, list) or len(top3) != 3
            or any(type(x) is not int or x not in range(1, 7) for x in top3) or len(set(top3)) != 3):
            raise TrainingError('normal result requires three distinct top-three identities')
        clean['label'] = dict(status=label['status'], confirmed=True, top3=top3,
                              available_at=_stamp(label['available_at']), captured_at=_stamp(label['captured_at']),
                              source_ref=_description(label['source_ref'], 'label source_ref'))
    return clean


def _split(records, config):
    if not isinstance(records, list) or not 3 <= len(records) <= 10000:
        raise TrainingError('dataset must contain 3..10000 explicitly labeled races')
    rows, ids = [], set()
    for record in records:
        row = _record(record, config['feature_names'], labeled=True)
        if row['race_id'] in ids:
            raise TrainingError('duplicate race; choose an explicit official revision before training')
        ids.add(row['race_id'])
        rows.append(row)
    rows.sort(key=lambda row: (row['race_start_at'], row['race_id']))
    split, excluded = dict(train=[], validation=[], final_test=[]), []
    train, validation, evaluation = (_time(config[key]) for key in ('train_end_at', 'validation_end_at', 'evaluation_as_of'))
    for row in rows:
        start, decision = _time(row['race_start_at']), _time(row['as_of'])
        if start >= evaluation:
            raise TrainingError('race is outside final evaluation cutoff')
        phase, freeze = ('train', train) if start < train else (('validation', validation) if start < validation else ('final_test', evaluation))
        if max(_time(row['label']['available_at']), _time(row['label']['captured_at'])) > freeze:
            raise TrainingError(f'{phase} label unavailable by phase freeze')
        if phase == 'validation' and decision < train or phase == 'final_test' and decision < validation:
            raise TrainingError('decision time precedes the applicable model freeze')
        if row['label']['status'] != 'settled':
            excluded.append(dict(race_id=row['race_id'], phase=phase, reason='unsupported_result:' + row['label']['status']))
        else:
            split[phase].append(row)
    if any(not values for values in split.values()):
        raise TrainingError('all chronological phases require at least one scorable race')
    return split, excluded, rows


def _scaler(rows, names):
    columns = [[boat['features'][name] for row in rows for boat in row['boats']] for name in names]
    means = [math.fsum(column) / len(column) for column in columns]
    scales = [math.sqrt(math.fsum((x - mean) ** 2 for x in column) / len(column))
              for column, mean in zip(columns, means)]
    return dict(mean=means, scale=[value if value > 1e-12 else 1.0 for value in scales], standardized_clip=8.0)


def _matrix(row, names, scaler):
    return [[max(-8.0, min(8.0, (boat['features'][name] - scaler['mean'][i]) / scaler['scale'][i]))
             for i, name in enumerate(names)] for boat in row['boats']]


def _scores(matrix, weights, temperature=1.0):
    return [max(-20.0, min(20.0, math.fsum(w * x for w, x in zip(weights, vector)) / temperature)) for vector in matrix]


def _conditional_log_loss(scores, top3):
    remaining, loss = list(range(6)), 0.0
    for lane in top3:
        winner = lane - 1
        maximum = max(scores[i] for i in remaining)
        denominator = math.fsum(math.exp(scores[i] - maximum) for i in remaining)
        loss += maximum + math.log(denominator) - scores[winner]
        remaining.remove(winner)
    return loss


def _objective(matrices, labels, weights, l2, *, gradient=False):
    losses, grad = [], [0.0] * len(weights)
    for matrix, top3 in zip(matrices, labels):
        raw = [math.fsum(w * x for w, x in zip(weights, vector)) for vector in matrix]
        scores = _scores(matrix, weights)
        losses.append(_conditional_log_loss(scores, top3))
        if gradient:
            remaining = list(range(6))
            active = [abs(x) < 20 for x in raw]
            for lane in top3:
                winner = lane - 1
                maximum = max(scores[i] for i in remaining)
                exps = {i: math.exp(scores[i] - maximum) for i in remaining}
                denominator = math.fsum(exps.values())
                for j in range(len(weights)):
                    grad[j] += math.fsum(exps[i] / denominator * matrix[i][j] * active[i] for i in remaining) - matrix[winner][j] * active[winner]
                remaining.remove(winner)
    objective = math.fsum(losses) / len(losses) + .5 * l2 * math.fsum(w * w for w in weights)
    return objective, [g / len(losses) + l2 * w for g, w in zip(grad, weights)]


def _fit(rows, names, scaler, config):
    matrices, labels = [_matrix(row, names, scaler) for row in rows], [row['label']['top3'] for row in rows]
    weights = [0.0] * len(names)
    initial, _ = _objective(matrices, labels, weights, config['l2'])
    iterations = 0
    for _ in range(config['epochs']):
        current, gradient = _objective(matrices, labels, weights, config['l2'], gradient=True)
        step = config['learning_rate']
        for _ in range(20):
            candidate = [max(-10.0, min(10.0, w - step * g)) for w, g in zip(weights, gradient)]
            objective, _ = _objective(matrices, labels, candidate, config['l2'])
            if objective <= current + 1e-12:
                weights = candidate
                break
            step /= 2
        else:
            break
        iterations += 1
        if math.fsum(g * g for g in gradient) < 1e-16:
            break
    final, _ = _objective(matrices, labels, weights, config['l2'])
    return weights, dict(iterations=iterations, initial_objective=initial, final_objective=final,
                         objective='mean_top3_negative_log_likelihood_plus_half_l2_squared_weights')


def _validation_loss(rows, names, scaler, weights, temperature):
    return math.fsum(_conditional_log_loss(_scores(_matrix(row, names, scaler), weights, temperature), row['label']['top3'])
                     for row in rows) / len(rows)


def _metrics(rows, names, scaler, weights, temperature, model_id, bins):
    samples = []
    uniform = prediction.plackett_luce({lane: 1 for lane in range(1, 7)}) if model_id == 'uniform' else None
    for row in rows:
        distribution = uniform or prediction.plackett_luce({lane: math.exp(score) for lane, score in enumerate(
            _scores(_matrix(row, names, scaler), weights, temperature), 1)})
        forecast = dict(race_id=row['race_id'], model_id=model_id, model_version='offline-research',
                        selection_reason='retrospective_same_cohort_comparison', **distribution)
        samples.append((forecast, row['label']))
    return prediction._metrics(samples, bins)[0]


def train_and_evaluate(records, configuration):
    """Return reproducible artifact plus actual run manifest and retrospective report."""
    config = _configuration(configuration)
    split, excluded, all_rows = _split(records, config)
    names = config['feature_names']
    scaler = _scaler(split['train'], names)
    weights, optimization = _fit(split['train'], names, scaler, config)
    choices = [(temperature, _validation_loss(split['validation'], names, scaler, weights, temperature))
               for temperature in config['temperature_grid']]
    temperature, validation_loss = min(choices, key=lambda item: (item[1], abs(item[0] - 1), item[0]))
    uniform_loss = math.log(120)
    selected = 'linear_plackett_luce' if validation_loss < uniform_loss - 1e-9 else 'uniform'
    reason = 'validation_log_loss_improved_over_uniform' if selected != 'uniform' else 'validation_did_not_improve_over_uniform'
    artifact = dict(format_version=1, implementation_version='linear-pl-research-v1', model_id='linear-plackett-luce-research',
        feature_names=names, feature_schema={name: dict(minimum=FEATURES[name][0], maximum=FEATURES[name][1], meaning=FEATURES[name][2]) for name in names},
        scaler=scaler, weights=weights, score_clip=20.0, selected_model=selected, selection_reason=reason,
        temperature=temperature if selected != 'uniform' else 1.0, fitted_candidate_temperature=temperature,
        calibration=dict(method='validation_only_temperature_grid', grid=config['temperature_grid'],
                         validation_log_loss=validation_loss, uniform_validation_log_loss=uniform_loss),
        optimizer=dict(method='deterministic_full_batch_gradient_descent_with_backtracking', epochs=config['epochs'],
                       learning_rate=config['learning_rate'], l2=config['l2'], **optimization),
        training_label_cutoff=config['train_end_at'], calibration_label_cutoff=config['validation_end_at'],
        training_dataset_sha256=_sha(split['train']), validation_dataset_sha256=_sha(split['validation']),
        training_race_ids=[row['race_id'] for row in split['train']], validation_race_ids=[row['race_id'] for row in split['validation']],
        source_kinds=sorted({row['source_kind'] for phase in ('train', 'validation') for row in split[phase]}),
        uses_odds='market_implied_win_probability' in names, validation_status='UNVALIDATED',
        research_only=True, eligible_for_live_recommendations=False)
    artifact['artifact_sha256'] = _sha(artifact)
    created = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    manifest = dict(artifact_sha256=artifact['artifact_sha256'], created_at=created,
                    kind='actual_offline_training_execution', retrospective_evaluation=True)
    manifest['manifest_sha256'] = _sha(manifest)
    metrics = {phase: dict(uniform=_metrics(rows, names, scaler, weights, 1, 'uniform', config['calibration_bins']),
                           fitted=_metrics(rows, names, scaler, weights, temperature, 'fitted', config['calibration_bins']))
               for phase, rows in split.items()}
    # Reuse the shared money gate: neither a fitted score nor retrospective
    # improvement is permission to recommend or spend money.
    allocation = recommend_allocation([], dict(budget_yen=0), dict(validated=False, data_complete=True))
    report = dict(configuration=config, dataset_sha256=_sha(all_rows),
        splits={phase: [row['race_id'] for row in rows] for phase, rows in split.items()}, excluded=excluded,
        metrics=metrics, selected_research_model=selected, selection_reason=reason,
        retrospective_research=True, actual_pre_race_performance=False,
        validation_status='UNVALIDATED', allocation_gate=allocation,
        limitations=['Synthetic or source-attested offline labels do not establish live held-out accuracy.',
                     'Final-test inspection must not be reused to tune or promote this artifact.',
                     'Calibration is fitted on validation only; sample sizes and uncertainty remain material.'])
    return dict(artifact=artifact, manifest=manifest, report=report)


def _bundle(value):
    if not isinstance(value, dict) or 'artifact' not in value or 'manifest' not in value:
        raise TrainingError('model bundle requires artifact and actual creation manifest')
    artifact, manifest = value['artifact'], value['manifest']
    if not isinstance(artifact, dict) or not isinstance(manifest, dict):
        raise TrainingError('invalid model artifact or manifest')
    artifact_keys = {'format_version', 'implementation_version', 'model_id', 'feature_names', 'feature_schema',
        'scaler', 'weights', 'score_clip', 'selected_model', 'selection_reason', 'temperature',
        'fitted_candidate_temperature', 'calibration', 'optimizer', 'training_label_cutoff',
        'calibration_label_cutoff', 'training_dataset_sha256', 'validation_dataset_sha256',
        'training_race_ids', 'validation_race_ids', 'source_kinds', 'uses_odds', 'validation_status',
        'research_only', 'eligible_for_live_recommendations', 'artifact_sha256'}
    if set(artifact) != artifact_keys or set(manifest) != {'artifact_sha256', 'created_at', 'kind', 'retrospective_evaluation', 'manifest_sha256'}:
        raise TrainingError('complete exact artifact/manifest schema required')
    body = {key: val for key, val in artifact.items() if key != 'artifact_sha256'}
    if artifact.get('artifact_sha256') != _sha(body):
        raise TrainingError('artifact integrity mismatch')
    manifest_body = {key: val for key, val in manifest.items() if key != 'manifest_sha256'}
    if manifest.get('manifest_sha256') != _sha(manifest_body) or manifest.get('artifact_sha256') != artifact['artifact_sha256']:
        raise TrainingError('manifest integrity mismatch')
    names = _feature_names(artifact.get('feature_names'))
    if (type(artifact.get('format_version')) is not int or artifact['format_version'] != 1
            or artifact.get('implementation_version') != 'linear-pl-research-v1'
            or artifact.get('validation_status') != 'UNVALIDATED' or artifact.get('research_only') is not True
            or artifact.get('eligible_for_live_recommendations') is not False
            or artifact.get('selected_model') not in ('uniform', 'linear_plackett_luce')):
        raise TrainingError('unsupported or improperly promoted artifact')
    if artifact['model_id'] != 'linear-plackett-luce-research':
        raise TrainingError('unsupported model identity')
    reason = 'validation_log_loss_improved_over_uniform' if artifact['selected_model'] != 'uniform' else 'validation_did_not_improve_over_uniform'
    if artifact['selection_reason'] != reason:
        raise TrainingError('model selection reason conflicts with selected family')
    if manifest['kind'] != 'actual_offline_training_execution' or manifest['retrospective_evaluation'] is not True:
        raise TrainingError('actual offline execution manifest required')
    if not _time(artifact['training_label_cutoff']) < _time(artifact['calibration_label_cutoff']) <= _time(manifest['created_at']) <= datetime.now(timezone.utc):
        raise TrainingError('artifact creation/freeze chronology is inconsistent')
    schema = {name: dict(minimum=FEATURES[name][0], maximum=FEATURES[name][1], meaning=FEATURES[name][2]) for name in names}
    if artifact['feature_schema'] != schema or artifact['uses_odds'] is not ('market_implied_win_probability' in names):
        raise TrainingError('feature interpretation or odds-use marker mismatch')
    if not isinstance(artifact.get('weights'), list) or len(artifact['weights']) != len(names):
        raise TrainingError('weight schema mismatch')
    for weight in artifact['weights']:
        _number(weight, 'weight', -10, 10)
    scaler = artifact.get('scaler')
    if not isinstance(scaler, dict) or set(scaler) != {'mean', 'scale', 'standardized_clip'} or scaler['standardized_clip'] != 8:
        raise TrainingError('invalid scaler schema')
    for key in ('mean', 'scale'):
        if not isinstance(scaler[key], list) or len(scaler[key]) != len(names):
            raise TrainingError('scaler feature schema mismatch')
    for i, name in enumerate(names):
        _number(scaler['mean'][i], 'scaler mean', FEATURES[name][0], FEATURES[name][1])
        _number(scaler['scale'][i], 'scaler scale', 1e-12, 2000000)
    _number(artifact.get('temperature'), 'temperature', .25, 8)
    if artifact.get('score_clip') != 20:
        raise TrainingError('unsupported score bound')
    return dict(artifact=json.loads(_json(artifact)), manifest=json.loads(_json(manifest)))


def export_model(run):
    return _json(_bundle(run))


def _parse_json(raw, maximum):
    def reject(value):
        raise TrainingError('nonfinite JSON value')
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise TrainingError('duplicate JSON key')
            value[key] = item
        return value
    try:
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > maximum:
            raise TrainingError('bounded UTF-8 JSON required')
        parsed = json.loads(raw, parse_constant=reject, object_pairs_hook=unique_object)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise TrainingError('invalid or ambiguous JSON') from exc
    return parsed


def load_model(raw):
    return _bundle(_parse_json(raw, 2_000_000))


def predict_with_artifact(bundle, pre_race_record, *, generated_at=None):
    checked = _bundle(bundle)
    artifact, manifest = checked['artifact'], checked['manifest']
    row = _record(pre_race_record, artifact['feature_names'], labeled=False)
    cutoff = _time(row['as_of'])
    if _time(manifest['created_at']) > cutoff or _time(artifact['calibration_label_cutoff']) > cutoff:
        raise TrainingError('model was unavailable at requested prediction cutoff')
    generated = generated_at or datetime.now(timezone.utc).isoformat(timespec='microseconds')
    matrix = _matrix(row, artifact['feature_names'], artifact['scaler'])
    scores = [0.0] * 6 if artifact['selected_model'] == 'uniform' else _scores(matrix, artifact['weights'], artifact['temperature'])
    boats = [dict(lane=boat['lane'], strength=math.exp(score), available_at=boat['available_at'],
                  captured_at=boat['captured_at'], generated_at=boat['generated_at'],
                  source_ref=boat['source_ref'], feature_kind='pre_race_strength')
             for boat, score in zip(row['boats'], scores)]
    try:
        return prediction.build_prediction(dict(race_id=row['race_id'], race_start_at=row['race_start_at'],
            as_of=row['as_of'], generated_at=generated, boats=boats, model_id=artifact['model_id'],
            model_version=artifact['artifact_sha256'], selection_reason=artifact['selection_reason']))
    except prediction.PredictionError as exc:
        raise TrainingError(str(exc)) from exc


def main():
    parser = argparse.ArgumentParser(description='Offline chronological research training; no live promotion')
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        records = _parse_json(Path(args.dataset).read_text(encoding='utf-8'), 20_000_000)
        configuration = _parse_json(Path(args.config).read_text(encoding='utf-8'), 100_000)
        run = train_and_evaluate(records, configuration)
        with Path(args.output).open('x', encoding='utf-8') as output:
            output.write(_json(run) + '\n')
        print('UNVALIDATED_OFFLINE_RESEARCH ' + run['artifact']['artifact_sha256'])
    except (TrainingError, OSError, ValueError) as exc:
        parser.exit(2, 'TRAINING_REJECTED: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
