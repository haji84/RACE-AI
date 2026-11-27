"""Reproducible, time-separated DT-R1 archive study and prediction adapter.

Study outputs belong in a private directory. Only the aggregate report and
reviewed model parameters may be copied into the public research branch.
Historical collection clocks are never backdated into pre-cutoff receipts.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import importlib.metadata
import json
from math import isfinite, log
import os
from pathlib import Path
import platform
import time
from hashlib import sha256

import numpy as np

from .model import MODEL_ID, RankModel, digest, fit_ranker, fit_temperature

DEFAULT_SPLITS = {
    'fit': {'start': '2025-10-01', 'end': '2026-06-30'},
    'tune': {'start': '2026-07-01', 'end': '2026-07-31'},
    'calibration': {'start': '2026-08-01', 'end': '2026-08-31'},
    'audit': {'start': '2026-09-01', 'end': '2026-09-30'},
    'test': {'start': '2026-10-01', 'end': '2026-11-22'},
}
EXPECTED_ENTRANTS = ('existing-integrated', 'codex-new', MODEL_ID)
TRIFECTA_K = (1, 2, 4, 9, 12)
EXACTA_K = (1, 2)


def check_splits(splits):
    if set(splits) != set(DEFAULT_SPLITS):
        raise ValueError('FIVE_CHRONOLOGICAL_SPLITS_REQUIRED')
    previous = None
    for name in DEFAULT_SPLITS:
        window = splits[name]
        start, end = window['start'], window['end']
        if date.fromisoformat(start).isoformat() != start or date.fromisoformat(end).isoformat() != end or start > end:
            raise ValueError('SPLIT_DATE_INVALID')
        if previous is not None and start <= previous:
            raise ValueError('SPLIT_OVERLAP_OR_ORDER')
        previous = end
    return splits


def partition(rows, splits):
    check_splits(splits)
    out = {key: [] for key in splits}
    out['outside'] = []
    seen = set()
    for row in rows:
        if row['race_id'] in seen:
            raise ValueError('DUPLICATE_RACE_IN_PARTITION')
        seen.add(row['race_id'])
        match = next((key for key, w in splits.items() if w['start'] <= row['day'] <= w['end']), 'outside')
        out[match].append(row)
    return out


def write_private_json(path, value):
    """Create-only and no symlinks: an evaluated original is never overwritten."""
    from .runtime import _private_path
    path = _private_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def freeze_evaluation_contract(directory, splits, source_audit):
    from .runtime import _private_path
    check_splits(splits)
    directory = _private_path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    contract = {
        'schema': 'dt-r1-study-contract-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
        'splits': splits, 'source_audit_sha256': digest(source_audit),
        'scope': 'retrospective_reused_archive_no_prospective_attestation',
        'selection_metric': 'tune_joint_top3_log_loss',
        'candidates': [
            {'name': 'full_without_pairs', 'history': True, 'pairs': False, 'ridge': .01},
            {'name': 'full_with_pairs', 'history': True, 'pairs': True, 'ridge': .01},
            {'name': 'without_history_with_pairs', 'history': False, 'pairs': True, 'ridge': .01}],
        'trifecta_k': list(TRIFECTA_K), 'exacta_k': list(EXACTA_K),
        'all_target_rule': 'all registered races with verified unique ordered top3; missing predictions count as misses',
        'result_exclusions': ['no unique top3', 'cancelled', 'unresolved dead heat', 'pending'],
        'incident_rule': 'score valid unique top3 even if other riders have incidents',
        'confidence_thresholds': {'HOT': .9, 'HIGH': .8, 'MEDIUM': .6},
        'expected_contest_entrants': list(EXPECTED_ENTRANTS),
        'production_promotion': False,
        'calibration_config': {'bins': 10, 'min_calibration_n': 50, 'min_audit_n': 100,
                               'min_audit_days': 5, 'confidence_level': .95, 'max_calibration_error': .10,
                               'prior_alpha': 1., 'prior_beta': 1.},
    }
    if source_audit.get('context_requested'):
        contract['candidates'].append({'name': 'without_context_with_pairs', 'history': True,
                                       'pairs': True, 'context': False, 'ridge': .01})
    if source_audit.get('agari_interactions'):
        contract['agari_interactions'] = source_audit['agari_interactions']
        contract['candidates'].append({'name': 'without_agari_interactions_with_pairs', 'history': True,
                                       'pairs': True, 'agari': False, 'ridge': .01})
        if source_audit.get('context_requested'):
            contract['candidates'].append({'name': 'without_context_or_agari_with_pairs', 'history': True,
                                           'pairs': True, 'agari': False, 'context': False, 'ridge': .01})
    contract['input_context'] = source_audit.get('context', {})
    contract['contract_sha256'] = digest(contract)
    write_private_json(directory / 'evaluation_contract.json', contract)
    return contract


def _when(value):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.utcoffset() is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return t


def validate_prediction_inputs(row, *, prediction_at=None, model_meta=None):
    """Shared eligibility boundary for finish and phase prediction APIs.

    Declared clocks and source bindings are checked here. Independent source
    authentication is still performed by the existing admission/readback path.
    """
    prospective = row.get('cohort') == 'prospective'
    cutoff = row.get('cutoff_at') or row.get('published_cutoff_at')
    if prospective:
        if not prediction_at or not cutoff or not row.get('source_attestation_sha256'):
            raise ValueError('AUTHENTICATED_SOURCE_AND_CLOCKS_REQUIRED')
        at, close = _when(prediction_at), _when(cutoff)
        from .policy import check_race_day, checked_sha
        checked_sha(row['source_attestation_sha256'], 'SOURCE_ATTESTATION_SHA_REQUIRED')
        if row.get('pre_cutoff_authenticated') is False:
            raise ValueError('SOURCE_AUTHENTICATION_EXPLICITLY_ABSENT')
        check_race_day(row['day'], cutoff)
        if (close - at).total_seconds() < 900:
            raise ValueError('PRE_CUTOFF_15_MINUTES_REQUIRED')
        if not row.get('available_at') or _when(row['available_at']) > at:
            raise ValueError('SOURCE_AFTER_PREDICTION')
        context_clock = row.get('history_evidence', {}).get('external_context', {}).get('as_of')
        if context_clock is not None and _when(context_clock) > at:
            raise ValueError('CONTEXT_AFTER_PREDICTION')
        if model_meta is not None:
            created = model_meta.get('created_at')
            information_end = max(model_meta.get('training_last_day', row['day']),
                                  model_meta.get('temperature_calibration', {}).get('end_day', ''),
                                  model_meta.get('parameter_information_end_day', ''))
            if not created or _when(created) > at or information_end >= row['day']:
                raise ValueError('MODEL_FROM_FUTURE')
    elif prediction_at is not None:
        raise ValueError('RETROSPECTIVE_CLOCK_MUST_NOT_BE_INVENTED')
    return prospective, cutoff


def forecast_row(model, row, *, prediction_at=None, full=False):
    prospective, cutoff = validate_prediction_inputs(row, prediction_at=prediction_at, model_meta=model.fit_meta)
    try:
        values = model.distribution(row, full=full)
    except (ValueError, KeyError) as error:
        return {'race_id': row['race_id'], 'day': row['day'], 'model_id': MODEL_ID,
                'model_sha256': model.to_dict()['model_sha256'], 'input_sha256': row.get('input_sha256'),
                'status': 'HOLD', 'reason': str(error), 'cohort': 'prospective' if prospective else 'retrospective',
                'prediction_at': prediction_at, 'cutoff_at': cutoff if prospective else None}
    return {'race_id': row['race_id'], 'day': row['day'], 'model_id': MODEL_ID,
            'model_sha256': model.to_dict()['model_sha256'], 'input_sha256': row['input_sha256'],
            'feature_input_sha256': row.get('feature_input_sha256'),
            'dataset_sha256': row.get('dataset_sha256'),
            'status': 'READY', 'cohort': 'prospective' if prospective else 'retrospective',
            'prediction_at': prediction_at, 'cutoff_at': cutoff if prospective else None,
            'field_size': len(row['riders']), 'class': row.get('race_class', 'UNKNOWN'),
            'venue': row.get('venue_code', 'UNKNOWN'),
            'confidence': {'label': 'HOLD', 'reason': 'NO_AUDITED_ACTUAL_SELECTION_POLICY'},
            'source_attestation_sha256': row.get('source_attestation_sha256'),
            'scope': 'prospective_shadow_pending_independent_readback' if prospective else 'retrospective_reused_archive',
            **values}


def _result_key(row):
    top = row.get('top3')
    if not (isinstance(top, (list, tuple)) and len(top) == 3 and len(set(top)) == 3
            and all(type(c) is int and 1 <= c <= 9 for c in top)):
        return None
    status = str(row.get('result_status', '')).lower()
    if status in ('cancelled', 'pending', 'missing'):
        return None
    if row.get('riders') and not set(top) <= {r['car'] for r in row['riders']}:
        return None
    if status == 'dead_heat':
        # Ties below third do not invalidate a uniquely resolved trifecta.
        resolved = []
        for rank in (1, 2, 3):
            cars = [r.get('car') for r in row.get('result_rows', []) if type(r.get('rank')) is int and r['rank'] == rank]
            if len(cars) != 1:
                return None
            resolved.append(cars[0])
        if tuple(resolved) != tuple(top):
            return None
    return tuple(top)


def summarize_predictions(forecasts, rows):
    """Aggregate only; proper scores use the declared predicted-result subset."""
    index = {}
    for forecast in forecasts:
        rid = forecast['race_id']
        if rid in index:
            raise ValueError('DUPLICATE_FORECAST')
        index[rid] = forecast
    metrics = {'registered': len(rows), 'evaluable': 0, 'predicted_evaluable': 0,
               'not_evaluable': Counter(), 'holds': Counter(),
               'trifecta': {str(k): {'hits': 0} for k in TRIFECTA_K},
               'exacta': {str(k): {'hits': 0} for k in EXACTA_K}}
    losses, briers, exacta_losses = [], [], []
    seen = set()
    for row in rows:
        if row['race_id'] in seen:
            raise ValueError('DUPLICATE_REGISTRY_RACE')
        seen.add(row['race_id'])
        truth = _result_key(row)
        if truth is None:
            metrics['not_evaluable'][row.get('result_status', 'no_unique_top3')] += 1
            continue
        metrics['evaluable'] += 1
        f = index.get(row['race_id'])
        if f is None or f.get('status') != 'READY':
            metrics['holds'][f.get('reason', 'MISSING_PREDICTION') if f else 'MISSING_PREDICTION'] += 1
            continue
        if f.get('input_sha256') != row.get('input_sha256'):
            raise ValueError('PREDICTION_INPUT_MISMATCH')
        metrics['predicted_evaluable'] += 1
        masses = []
        for market, kvalues, target in (('trifecta', TRIFECTA_K, truth), ('exacta', EXACTA_K, truth[:2])):
            tickets = f[market + 's']
            values = {tuple(t['cars']): t['probability'] for t in tickets}
            if (len(values) != len(tickets) or any(not isfinite(p) or p < 0 for p in values.values())
                    or abs(sum(values.values()) - 1) > 1e-8):
                raise ValueError('PROBABILITY_DISTRIBUTION_INVALID')
            ranking = sorted(values, key=lambda t: (-values[t], t))
            for k in kvalues:
                metrics[market][str(k)]['hits'] += int(target in ranking[:k])
            masses.append(values.get(target, 0.))
            if market == 'trifecta':
                briers.append(sum(p * p for p in values.values()) + 1 - 2 * values.get(target, 0.))
        losses.append(-log(max(masses[0], 1e-300)))
        exacta_losses.append(-log(max(masses[1], 1e-300)))
    for market in ('trifecta', 'exacta'):
        for cell in metrics[market].values():
            cell['all_target_rate'] = cell['hits'] / metrics['evaluable'] if metrics['evaluable'] else None
            cell['predicted_rate'] = cell['hits'] / metrics['predicted_evaluable'] if metrics['predicted_evaluable'] else None
    metrics['not_evaluable'] = dict(metrics['not_evaluable'])
    metrics['holds'] = dict(metrics['holds'])
    metrics['prediction_coverage'] = metrics['predicted_evaluable'] / metrics['evaluable'] if metrics['evaluable'] else None
    metrics['proper_scores'] = {'n': len(losses), 'joint_top3_log_loss': float(np.mean(losses)) if losses else None,
                               'exacta_log_loss': float(np.mean(exacta_losses)) if losses else None,
                               'multiclass_brier': float(np.mean(briers)) if briers else None}
    return metrics


def subgroup_metrics(forecasts, rows):
    out = {}
    index = {f['race_id']: f for f in forecasts}
    for label, getter in (
            ('field_size', lambda r: str(len(r.get('riders', [])))),
            ('class', lambda r: r.get('race_class', 'UNKNOWN')),
            ('venue', lambda r: str(r.get('venue_code', 'UNKNOWN'))),
            ('line_data', lambda r: 'known' if r.get('lines_known') else 'unknown_or_not_applicable')):
        groups = defaultdict(list)
        for row in rows:
            groups[getter(row)].append(row)
        out[label] = {key: summarize_predictions([index[r['race_id']] for r in group if r['race_id'] in index], group)
                      for key, group in sorted(groups.items())}
    return out


def _available_features(row):
    return ('features' in row and row.get('feature_status', 'READY') == 'READY'
            and 3 <= len(row.get('riders', [])) <= 9)


def _calibration_rows(forecasts, rows, k, market):
    from .policy import fixed_selection
    index = {r['race_id']: r for r in rows}
    out = []
    for f in forecasts:
        row = index[f['race_id']]
        truth = _result_key(row)
        if f.get('status') != 'READY' or truth is None:
            continue
        selection = fixed_selection(f, k, market=market)
        target = truth if market == 'trifecta' else truth[:2]
        selected = selection.get('selected_tickets', [])
        cars = [tuple(t['cars']) if isinstance(t, dict) else tuple(t) for t in selected]
        out.append({**selection, 'hit': target in cars, 'day': row['day'],
                    'field_size': len(row['riders']), 'class': row.get('race_class', 'UNKNOWN')})
    return out


def run_study(paths, directory, *, splits=None, max_iter=160, progress=None,
              venue_path=None, timing_path=None, weather_path=None, analysis_at=None, allow_current_geometry_assumption=False):
    """Complete archive admission -> fitting -> calibration -> frozen evaluation.

    This function never dispatches a workflow, places a bet, publishes raw
    predictions, or changes a production model. A new output directory is
    mandatory for each run; no previous result can be silently rewritten.
    """
    from .data import load_archives
    from .features import build_features
    from .agari import augment_agari, VERSION as AGARI_VERSION, AGARI_NAMES, uses_agari, CONTEXT_PREFIX
    from .calibration import fit_calibrator, audit_calibrator, assess_selection
    from .policy import fixed_selection
    splits = DEFAULT_SPLITS if splits is None else splits
    report_progress = progress or (lambda text: None)
    start = time.monotonic()
    directory = Path(directory)
    records, source_audit = load_archives(paths)
    context_enabled = venue_path is not None or timing_path is not None or weather_path is not None
    # Hash and parse exactly the same bytes. Do not let a mutable path swap data
    # between contract freezing and feature construction.
    venue_bytes = Path(venue_path).read_bytes() if venue_path else None
    timing_bytes = Path(timing_path).read_bytes() if timing_path else None
    weather_bytes = Path(weather_path).read_bytes() if weather_path else None
    source_audit['agari_interactions'] = {'version': AGARI_VERSION, 'columns': list(AGARI_NAMES),
                                         'official_half_lap_only': True}
    if allow_current_geometry_assumption and venue_path is None:
        raise ValueError('GEOMETRY_FILE_REQUIRED_FOR_ASSUMPTION')
    analysis_at = analysis_at or datetime.now(timezone.utc).isoformat()
    if context_enabled:
        source_audit['context_requested'] = True
        source_audit['context'] = {'analysis_at': analysis_at,
            'venue_file_sha256': sha256(venue_bytes).hexdigest() if venue_bytes is not None else None,
            'timing_file_sha256': sha256(timing_bytes).hexdigest() if timing_bytes is not None else None,
            'weather_file_sha256': sha256(weather_bytes).hexdigest() if weather_bytes is not None else None,
            'current_geometry_for_history_is_assumption': bool(allow_current_geometry_assumption)}
    code_files = ('data.py', 'features.py', 'model.py', 'pipeline.py', 'policy.py', 'calibration.py', 'comparison.py',
                  'context.py', 'observations.py', 'venues.py', 'runtime.py', 'agari.py')
    source_code_sha256 = {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in code_files}
    contract = freeze_evaluation_contract(directory, splits, source_audit)
    report_progress(f'Admitted {len(records)} archived races; retrospective scope only.')
    if weather_bytes is not None:
        weather_records = json.loads(weather_bytes)
        if not isinstance(weather_records, dict) or any(not isinstance(k, str) or not isinstance(v, dict) for k, v in weather_records.items()):
            raise ValueError('WEATHER_RACE_ID_MAPPING_REQUIRED')
        records = [dict(r, weather_observation=weather_records[r['race_id']]) if r['race_id'] in weather_records else r for r in records]
    featured = build_features(records)
    context_summary = {'enabled': False, 'timing_records': 0, 'historical_geometry_assumption': False}
    if context_enabled:
        from .context import augment_features
        from .venues import VenueStore
        venue_store = VenueStore.from_records(json.loads(venue_bytes)) if venue_bytes is not None else None
        timing_records = json.loads(timing_bytes) if timing_bytes is not None else []
        if isinstance(timing_records, dict):
            timing_records = timing_records['records']
        featured = augment_features(featured, venue_store=venue_store, timing_records=timing_records,
                                    as_of=analysis_at, allow_current_geometry_assumption=allow_current_geometry_assumption)
        context_summary = {'enabled': True, 'timing_records': len(timing_records),
            'venue_source_summary': venue_store.summary() if venue_store else None,
            'historical_geometry_assumption': bool(allow_current_geometry_assumption),
            'geometry_assumption_races': sum(r['context_evidence']['current_geometry_assumption'] for r in featured),
            'races_with_measured_timing': sum(r['context_evidence']['measured_timing_rider_count'] > 0 for r in featured)}
    featured = augment_agari(featured)
    for row in featured:
        row['dataset_sha256'] = source_audit.get('dataset_sha256')
    groups = partition(featured, splits)
    for name, group in groups.items():
        report_progress(f'{name}: {len(group)} registered races.')
    train = [r for r in groups['fit'] if _available_features(r)]
    tune = [r for r in groups['tune'] if _available_features(r) and _result_key(r)]
    if not train or not tune:
        raise ValueError('TRAIN_AND_TUNE_PERIODS_REQUIRED')
    names = tuple(train[0]['feature_names'])
    models, candidate_reports = {}, {}
    # Feature-group metadata, when available, makes ablations explicit.
    history_mask = [not (name.startswith(('hist_', 'history_', 'recent_', 'venue_history_', 'rest_', 'starts_', 'past_'))
                         or name.startswith(('agari_', 'half_lap_', 'form_'))) for name in names]
    for candidate in contract['candidates']:
        name = candidate['name']
        report_progress(f'Fitting {name} on {len(train)} historical races.')
        fitted_at = time.monotonic()
        mask = np.asarray(history_mask if not candidate['history'] else [True] * len(names))
        if candidate.get('context') is False:
            mask &= np.asarray([not n.startswith(('context_', 'history_observed_', CONTEXT_PREFIX)) for n in names])
        if candidate.get('agari') is False:
            mask &= np.asarray([not uses_agari((n,)) for n in names])
        model = fit_ranker(train, before=splits['tune']['start'], ridge=candidate['ridge'],
                           use_pairs=candidate['pairs'], max_iter=max_iter,
                           feature_mask=mask)
        loss = model.top3_log_loss(tune)
        candidate_reports[name] = {'tune_joint_top3_log_loss': loss,
                                   'fit_seconds': time.monotonic() - fitted_at,
                                   'fit_meta': model.fit_meta,
                                   'masked_features': [n for n, keep in zip(names, model.fit_meta['feature_mask']) if not keep]}
        models[name] = model
        write_private_json(directory / (name + '.model.json'), model.to_dict())
        report_progress(f'{name}: July top3 log loss={loss:.6f}; optimizer converged={model.fit_meta["optimizer_converged"]}.')
    winner = min(candidate_reports, key=lambda name: (candidate_reports[name]['tune_joint_top3_log_loss'], name))
    selected = fit_temperature(models[winner], tune, start_day=splits['tune']['start'], end_day=splits['tune']['end'])
    selected.fit_meta['selection'] = {'candidate': winner, 'period': 'tune',
                                      'criterion': 'joint_top3_log_loss', 'contract_sha256': contract['contract_sha256']}
    selected.fit_meta['context'] = source_audit.get('context', {})
    selected.fit_meta['source_code_sha256'] = source_code_sha256
    frozen = selected.to_dict()
    write_private_json(directory / 'frozen_model.json', frozen)
    write_private_json(directory / 'selection_receipt.json', {
        'selected': winner, 'model_sha256': frozen['model_sha256'], 'candidates': candidate_reports,
        'frozen_at': datetime.now(timezone.utc).isoformat(), 'test_results_consulted': False})
    report_progress(f'Frozen {winner}; generating separate calibration and audit predictions.')
    cal_forecasts = [forecast_row(selected, row) for row in groups['calibration']]
    audit_forecasts = [forecast_row(selected, row) for row in groups['audit']]
    calibrators, cal_summary = {}, {}
    for market, ks in (('trifecta', TRIFECTA_K), ('exacta', EXACTA_K)):
        for k in ks:
            key = f'{market}_{k}'
            cal_rows = _calibration_rows(cal_forecasts, groups['calibration'], k, market)
            audit_rows = _calibration_rows(audit_forecasts, groups['audit'], k, market)
            if not cal_rows:
                cal_summary[key] = {'status': 'HOLD', 'reason': 'NO_CALIBRATION_ROWS'}
                continue
            lineage = {'model_id': MODEL_ID, 'model_sha256': frozen['model_sha256'],
                       'policy_sha256': cal_rows[0]['policy_sha256']}
            artifact = fit_calibrator(cal_rows, split_manifest={x: splits[x] for x in ('fit', 'tune', 'calibration', 'audit')},
                                      lineage=lineage, config=contract['calibration_config'])
            artifact = audit_calibrator(artifact, audit_rows)
            calibrators[key] = artifact
            write_private_json(directory / (key + '.calibration.json'), artifact)
            cal_summary[key] = {'calibration_rows': len(cal_rows), 'audit_rows': len(audit_rows)}
    write_private_json(directory / 'pre_test_freeze.json', {
        'model_sha256': frozen['model_sha256'], 'calibration_sha256': {k: digest(v) for k, v in calibrators.items()},
        'frozen_at': datetime.now(timezone.utc).isoformat(), 'contract_sha256': contract['contract_sha256']})
    report_progress('All parameters and calibration artifacts frozen; evaluating the reused historical final period.')
    predictions = [forecast_row(selected, row) for row in groups['test']]
    main_metrics = summarize_predictions(predictions, groups['test'])
    # Save private exact originals once. Public evidence contains aggregates only.
    write_private_json(directory / 'test_forecasts.private.json', predictions)
    confidence_summary = {}
    for key, artifact in calibrators.items():
        market, text_k = key.rsplit('_', 1)
        rows = _calibration_rows(predictions, groups['test'], int(text_k), market)
        labels = defaultdict(lambda: {'n': 0, 'hits': 0})
        for row in rows:
            assessment = assess_selection(row, artifact)
            label = assessment.get('label', assessment.get('confidence', 'HOLD'))
            labels[str(label)]['n'] += 1
            labels[str(label)]['hits'] += int(row['hit'])
        confidence_summary[key] = {label: dict(v, observed_rate=v['hits'] / v['n']) for label, v in labels.items()}
    ablations = {}
    ablation_forecasts = {}
    for name, model in models.items():
        fs = [forecast_row(model, row) for row in groups['test']]
        ablations[name] = summarize_predictions(fs, groups['test'])
        ablation_forecasts[name] = fs
    outcomes = [{'race_id': r['race_id'], 'day': r['day'], 'top3': r.get('top3'),
                 'status': 'settled' if _result_key(r) else
                           ('dead_heat' if str(r.get('result_status', '')).lower() == 'dead_heat' else
                            'cancelled' if str(r.get('result_status', '')).lower() == 'cancelled' else 'pending'),
                 'field_size': len(r.get('riders', [])), 'class': r.get('race_class'), 'venue': r.get('venue_code')}
                for r in groups['test']]
    registry = [{'race_id': r['race_id'], 'day': r['day'], 'cohort': 'retrospective',
                 'input_sha256': r['input_sha256'], 'field_size': len(r.get('riders', [])),
                 'dataset_sha256': source_audit.get('dataset_sha256')} for r in groups['test']]
    write_private_json(directory / 'test_registry.private.json', registry)
    write_private_json(directory / 'test_outcomes.private.json', outcomes)
    from .comparison import compare_models
    contest = compare_models(predictions, outcomes, registry, expected_model_ids=list(EXPECTED_ENTRANTS))
    if any(sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != expected
           for name, expected in source_code_sha256.items()):
        raise ValueError('EXECUTABLE_SOURCE_CHANGED_DURING_STUDY')
    report = {
        'schema': 'dt-r1-real-archive-study-v1', 'scope': contract['scope'],
        'source_audit': source_audit, 'evaluation_contract': contract,
        'split_counts': {name: len(group) for name, group in groups.items()},
        'feature_count': len(names), 'feature_names': list(names),
        'context': context_summary, 'source_code_sha256': source_code_sha256,
        'selected_candidate': winner, 'model_sha256': frozen['model_sha256'],
        'candidate_selection': candidate_reports, 'distribution_temperature': selected.temperature,
        'final_period': main_metrics, 'subgroups': subgroup_metrics(predictions, groups['test']),
        'ablations_frozen_before_test': ablations,
        'fixed_policy_calibration': cal_summary, 'fixed_policy_confidence_test': confidence_summary,
        'three_way_contest': contest,
        'unavailable_evidence': ['authenticated historical pre-cutoff clocks', 'two independently frozen rival outputs',
                                 'independently verified agari timing sidecar and video phase labels for this archive', 'contemporaneous complete odds snapshots',
                                 'unseen future shadow evaluation and production acceptance'],
        'runtime': {'seconds': time.monotonic() - start, 'python': platform.python_version(),
                    'numpy': importlib.metadata.version('numpy'), 'scipy': importlib.metadata.version('scipy'),
                    'platform': platform.system(), 'cpu_only': True},
        'production_promoted': False,
    }
    write_private_json(directory / 'aggregate_report.json', report)
    report_progress(f'Completed retrospective study in {report["runtime"]["seconds"]:.1f} seconds; production unchanged.')
    return report
