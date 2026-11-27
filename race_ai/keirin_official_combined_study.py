"""Fit and verify one eight-component blend on ordered, witnessed race originals."""
from collections import Counter
from math import fsum
from subprocess import TimeoutExpired

from . import keirin_form_fall_shadow as shadow
from . import keirin_nationwide_auto_generator as model
from . import keirin_official_condition_scoring as scoring
from . import keirin_official_condition_trial as trial
from . import keirin_official_nationwide_records as records
from . import keirin_paired_measurement as paired
from .keirin_github_evidence_client import GitHubEvidenceClient
from .keirin_official_form_history import JST

SCHEMA = 'RACE_AI_KEIRIN_COMBINED_CHRONOLOGICAL_STUDY_V1'
WEIGHTS = (0.25, 0.5, 0.75)
FIXED_INDEX = 1
COMPONENTS = {model.MODEL_A, model.MODEL_B, model.EVIDENCE_A, model.EVIDENCE_B,
              trial.BASELINE, trial.CHALLENGER, *trial.FORM_MODELS}
MIN_RACES = 2
MAX_REQUESTED = 30
EVIDENCE_ERRORS = (ValueError, KeyError, TypeError, OSError, TimeoutExpired)


def _prepare(store, race_id, meta, private, *, generated_at, client, packet_cache, history_cache):
    payload = store.read(meta, private)
    records.need(payload['race_id'] == race_id and payload.get('condition_trial') is not None,
                 'STUDY_CONDITION_TRIAL_REQUIRED')
    original, packets = records.admit_original(store, payload, private, origin_client=client,
                                               packet_cache=packet_cache)
    snap, saved = original['snapshot'], original['baseline']
    cutoff = model.when(meta['cutoff_at'])
    origins = original['origin_receipts']
    records.need(model.when(saved['published_cutoff_at']) == cutoff < model.when(generated_at) and
                 original['conditioned'] is not None and origins['condition_origin'] is not None,
                 'STUDY_PRE_CUTOFF_INPUTS')
    records.need(max(model.when(original['conditioned_sealed_at']),
                     model.when(origins['condition_origin']['latest_server_evidence_at']))
                 <= cutoff - trial.WITNESS_MARGIN, 'STUDY_FORM_T15')
    pair, _, _ = records.replay_condition_pair(store, meta, payload, packets, origins['baseline_origin'],
                                               history_cache=history_cache)
    rebuilt = model.generate_A_B(snap, generated_at=saved['generated_at'])
    form = shadow.generate_shadow(snap, original['supplement'], baseline=rebuilt,
                                  generated_at=saved['generated_at'])
    records.need(rebuilt == saved and form == original['conditioned'], 'STUDY_ORIGINAL_CHANGED')
    forecasts = tuple(trial.build_combined(snap, rebuilt, pair, generated_at=generated_at,
                                           form_shadow=form, supplement=original['supplement'],
                                           current_weight=weight) for weight in WEIGHTS)
    records.need(all(forecast['scope'] == 'RETROSPECTIVE_RESEARCH' and not forecast['component_holds'] and
                     set(forecast['component_weights']) == COMPONENTS for forecast in forecasts),
                 'STUDY_EIGHT_COMPONENTS_REQUIRED')
    return forecasts


def _labels(store, private, race_ids, forecasts, *, observed_by=None):
    labels, holds = {}, Counter()
    for race_id in race_ids:
        meta = store.index['originals'][race_id]
        cutoff = model.when(meta['cutoff_at'])
        revisions = store.index['results'].get(race_id, [])
        result = next((item for item in reversed(revisions) if observed_by is None or
                       model.when(item['observed_at']) <= observed_by), None)
        if result is None:
            holds['RESULT_UNAVAILABLE_AT_BOUNDARY' if observed_by is not None else 'RESULT_UNAVAILABLE'] += 1
            continue
        try:
            _, saved, _ = records._replay_saved_result(store, meta, result, private)
            official = saved['official_result']
            records.need(official['race_id'] == race_id and model.when(official['official_cutoff_at']) == cutoff and
                         model.when(official['observed_at']) <= model.when(result['observed_at']), 'STUDY_RESULT_BINDING')
            cars = set(forecasts[race_id][FIXED_INDEX]['cars'])
            order = scoring._order(official, cars, cutoff)
        except EVIDENCE_ERRORS:
            holds['FINAL_ORDER_UNVERIFIED_OR_UNSUPPORTED'] += 1
            continue
        labels[race_id] = (order, result['evidence_sha256'])
    return labels, dict(holds)


def _score_holdout(store, forecasts, labels, fitted_idx):
    metrics = {key: [] for key in ('trifecta_top1', 'trifecta_top4', 'trifecta_top8', 'exacta_top2')}
    errors = [[], []]
    for race_id, (order, _) in labels.items():
        cutoff = model.when(store.index['originals'][race_id]['cutoff_at'])
        chosen = [forecasts[race_id][idx] for idx in (FIXED_INDEX, fitted_idx)]
        laws = {market: tuple(paired.distribution(doc, market) for doc in chosen)
                for market in ('trifectas', 'exactas')}
        for key in metrics:
            market, size = scoring.TICKET_BUDGETS[key]
            winner = order[:3 if market == 'trifectas' else 2]
            metrics[key].append(paired.observe_market(race_id, cutoff, size, laws[market], winner, None))
        for side, law in enumerate(laws['trifectas']):
            errors[side].append(paired.distribution_score(law, order[:3]))
    summaries = {key: paired.summarize_market(rows, key, detail=False) for key, rows in metrics.items()}
    for summary in summaries.values():
        summary['fixed'] = summary.pop(paired.ARMS[0])
        summary['fitted'] = summary.pop(paired.ARMS[1])
    return dict(hit_rates=summaries,
                trifecta_distribution={name: paired.average_scores(values)
                                       for name, values in zip(('fixed', 'fitted'), errors, strict=True)})


def run(store, private, race_ids, *, holdout_from, clock, freeze):
    """Write candidates before opening training labels and fitted model before opening holdout labels."""
    started_at = clock()
    records.need(holdout_from.astimezone(JST).date().isoformat() == store.day and holdout_from < started_at and
                 2 * MIN_RACES <= len(race_ids) <= MAX_REQUESTED and len(set(race_ids)) == len(race_ids) and
                 all(model.VENUE.fullmatch(rid) and rid[:8] == store.day.replace('-', '') for rid in race_ids),
                 'STUDY_COHORT_SCOPE')
    train_until = holdout_from - trial.WITNESS_MARGIN
    report = dict(schema=SCHEMA, day_jst=store.day, scope='RETROSPECTIVE_RESEARCH', source_requests=0,
                  archive_index_commit=store.head, archive_index_sha256=model.digest(store.index),
                  requested_cohort_sha256=model.digest(sorted(race_ids)),
                  holdout_from=holdout_from.isoformat(), training_results_observed_by=train_until.isoformat(),
                  candidate_current_weights=list(WEIGHTS), coverage=dict(requested=len(race_ids)))
    client, packet_cache, history_cache = GitHubEvidenceClient(), {}, {}
    forecasts, train_ids, holdout_ids = {}, [], []
    holds = Counter()
    for race_id in sorted(race_ids):
        meta = store.index['originals'].get(race_id)
        if meta is None:
            holds['ORIGINAL_UNAVAILABLE'] += 1
            continue
        try:
            forecasts[race_id] = _prepare(store, race_id, meta, private, generated_at=started_at.isoformat(),
                                         client=client, packet_cache=packet_cache, history_cache=history_cache)
        except EVIDENCE_ERRORS:
            holds[client.stopped_reason or 'EIGHT_COMPONENT_ORIGINAL_UNVERIFIED'] += 1
            continue
        group = train_ids if model.when(meta['cutoff_at']) < holdout_from else holdout_ids
        group.append(race_id)

    report['coverage'].update(training_forecasts=len(train_ids), holdout_forecasts=len(holdout_ids),
                              forecast_holds=dict(holds))
    at = clock().isoformat()
    report['candidate_freeze'] = freeze('candidates', dict(
        day_jst=store.day, observed_at=at, safe_report=report, schema=SCHEMA,
        original_evidence_sha256={rid: store.index['originals'][rid]['evidence_sha256'] for rid in forecasts},
        training_race_ids=train_ids, holdout_race_ids=holdout_ids, forecasts=forecasts,
    ))
    training, holds = _labels(store, private, train_ids, forecasts, observed_by=train_until)
    report['coverage'].update(training_results=len(training), training_holds=holds)
    if len(training) < MIN_RACES or len(holdout_ids) < MIN_RACES:
        report['state'] = 'HOLD_INSUFFICIENT_CHRONOLOGICAL_COHORT'
        return report
    losses = [fsum(paired.distribution_score(paired.distribution(forecasts[rid][idx], 'trifectas'),
                                            order[:3])[1] for rid, (order, _) in training.items()) / len(training)
              for idx in range(len(WEIGHTS))]
    best = min(range(len(WEIGHTS)), key=lambda idx: (losses[idx], abs(WEIGHTS[idx] - WEIGHTS[FIXED_INDEX]), idx))
    spec = dict(model_id=trial.COMBINED_MODEL, current_weight=WEIGHTS[best],
                component_weights=forecasts[train_ids[0]][best]['component_weights'],
                objective='MEAN_ORDERED_TRIFECTA_LOG_LOSS',
                training_log_loss={str(weight): loss for weight, loss in zip(WEIGHTS, losses, strict=True)},
                training_cohort_sha256=model.digest(sorted(training)),
                holdout_forecast_cohort_sha256=model.digest(sorted(holdout_ids)))
    report['model'] = spec
    report['model_freeze'] = freeze('model', dict(
        day_jst=store.day, observed_at=clock().isoformat(), safe_report=report, schema=SCHEMA,
        training_result_sha256={rid: result_sha for rid, (_, result_sha) in training.items()},
        holdout_forecast_sha256={rid: model.digest(forecasts[rid][best]) for rid in holdout_ids},
    ))

    holdout, holds = _labels(store, private, holdout_ids, forecasts)
    report['coverage'].update(holdout_results=len(holdout), holdout_holds=holds)
    report['holdout_scored_cohort_sha256'] = model.digest(sorted(holdout))
    report['holdout'] = _score_holdout(store, forecasts, holdout, best)
    report['state'] = 'HISTORICAL_STUDY_MEASURED' if len(holdout) >= MIN_RACES else 'HOLD_INSUFFICIENT_LATER_RESULTS'
    return report
