"""Unused official November 2026 holdout from a single retained archive pin.

This is a later recomputation from evidence available by T−15, not a sealed
historical forecast. In particular the frozen model was built after these
races. Retain only matched arms and never use the postdated geometry sidecar.
"""
from collections import Counter
from datetime import timedelta
from hashlib import sha256
from math import fsum

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_nationwide_records as records
from scripts import keirin_dt_r1_future_settle as settlement
from scripts import keirin_dt_r1_future_shadow as shadow

from .boosted_first_study import _joint, _score, marginal, reweight_joint, softmax
from .history_mix_study import PROPER_METRICS, RANK_METRICS, mix_joint, paired_difference
from .official_history import OfficialHistory
from .policy import clock
from .venues import VenueStore


ARCHIVE_COMMIT = 'd030ed9e381cea00d3fe3f19bd4babb5bb38361e'
DAYS = tuple(f'2026-11-{day}' for day in range(23, 28))
ARMS = ('cold', 'warm', 'mix25', 'mix50')
RESIDUAL_ARCHIVE = '8b1dad9db21d33bc2419d59e1b5805825bf3a003'
RESIDUAL_DAYS = ('2026-11-21', '2026-11-22')
RESIDUAL_ARMS = ('warm', 'winner_residual')
RESIDUAL_FILE_SHA = '0611cf3b54aa1e7042dc062771087f73eb55f49aeb3a6f37d253e6c040b0a518'
RESIDUAL_PATH = ('research/chatgpt_dt_r1/evidence/20261128-engine-history-followup/'
                 'winner-residual-candidate.lgb.txt')
PROPER_MIN_RACES = 30
PROPER_MIN_DAYS = 3


class HoldoutError(ValueError):
    pass


def _need(valid, reason):
    if not valid:
        raise HoldoutError(reason)


def load_residual_candidate(repo, trained):
    import lightgbm

    from .boosted_first_study import LGB_VERSION
    from .features import retired_timing_feature

    raw = (repo / RESIDUAL_PATH).read_bytes()
    _need(sha256(raw).hexdigest() == RESIDUAL_FILE_SHA and lightgbm.__version__ == LGB_VERSION,
          'RESIDUAL_ARTIFACT_PIN')
    booster = lightgbm.Booster(model_str=raw.decode('utf-8'))
    keep = [i for i, name in enumerate(trained.feature_names) if not retired_timing_feature(name)]
    _need(booster.num_trees() == 40 and booster.feature_name() == [trained.feature_names[i] for i in keep],
          'RESIDUAL_FEATURE_SCHEMA')
    return booster, keep


def _adjust_residual(context, trained, row, joint):
    import numpy as np

    from .winner_residual_study import _offset

    booster, keep = context
    cars, offset = _offset(trained, row)
    actual = marginal(joint, count=1)
    _need(np.allclose(np.exp(offset), [actual[(car,)] for car in cars], atol=1e-12, rtol=0.),
          'RESIDUAL_FROZEN_FIRST_MARGINAL')
    correction = booster.predict(row['features'][:, keep], raw_score=True, num_threads=2)
    _need(correction.shape == offset.shape, 'RESIDUAL_SCORE_ROSTER')
    first = dict(zip(cars, softmax(offset + correction, 1.), strict=True))
    return reweight_joint(joint, first)


def _replay_pair(store, rid, meta, private, trained, client, cache, history, *, residual_context=None):
    cutoff = clock(meta['cutoff_at'])
    input_at = cutoff - timedelta(minutes=15)
    payload = store.read(meta, private)
    original, _ = records.admit_original(store, payload, private, origin_client=client, packet_cache=cache)
    _need(clock(original['snapshot']['published_cutoff_at']) == cutoff, 'OFFICIAL_CUTOFF_CHANGED')
    server_at = original['origin_receipts']['baseline_origin']['latest_server_evidence_at']
    _need(clock(server_at) <= input_at, 'OFFICIAL_ORIGIN_AFTER_T15')
    venues = VenueStore.from_records(())
    warm, warm_at, _ = shadow._candidate(store=store, payload=payload, original=original,
        trained=trained, venues=venues, private=private, client=client, cache=cache,
        clock=lambda: input_at, official_history=history)
    _need(warm['race_id'] == rid and clock(warm_at) == input_at, 'HOLDOUT_PAIRED_INPUT_CHANGED')
    _need(warm['feature_status'] == 'READY', 'HOLDOUT_FEATURES_UNVERIFIED')
    prior = warm['history_evidence']['official_support']['history_races']
    warm_law = _joint(trained, warm)
    if residual_context is not None:
        adjusted = _adjust_residual(residual_context, trained, warm, warm_law)
        return dict(history_races=prior, laws=dict(warm=warm_law, winner_residual=adjusted))
    cold, cold_at, _ = shadow._candidate(store=store, payload=payload, original=original,
        trained=trained, venues=venues, private=private, client=client, cache=cache,
        clock=lambda: input_at, official_history=None)
    _need(cold['race_id'] == rid and warm['input_sha256'] == cold['input_sha256'] and clock(cold_at) == input_at,
          'HOLDOUT_PAIRED_INPUT_CHANGED')
    _need(cold['feature_status'] == 'READY', 'HOLDOUT_FEATURES_UNVERIFIED')
    _need(cold['history_evidence']['official_support']['history_races'] == 0, 'HOLDOUT_COLD_HISTORY')
    cold_law = _joint(trained, cold)
    # Identical laws must stay bit-for-bit equal rather than acquire
    # artificial ordering differences from a redundant floating-point mix.
    if warm_law == cold_law:
        return dict(history_races=prior, laws=dict.fromkeys(ARMS, cold_law))
    return dict(history_races=prior, laws=dict(cold=cold_law, warm=warm_law,
        mix25=mix_joint(cold_law, warm_law, .25), mix50=mix_joint(cold_law, warm_law, .50)))


def _paired_metrics(scores, arms=ARMS, *, baseline='cold'):
    paired_n = sum(d['warm']['n'] for d in scores.values())
    hits = {arm: dict(hits={metric: int(fsum(d[arm][metric] for d in scores.values()))
                           for metric in RANK_METRICS}) for arm in arms}
    if paired_n < PROPER_MIN_RACES or len(scores) < PROPER_MIN_DAYS:
        return hits, {}
    proper = {arm: {metric: fsum(d[arm][metric] for d in scores.values()) / paired_n
                    for metric in PROPER_METRICS} for arm in arms}
    differences = {arm: paired_difference(scores, arm, baseline) for arm in arms if arm != baseline}
    return hits, {'proper_scores': proper, f'paired_difference_from_{baseline}': differences}


def _prefetch_targets(store, ids, *, results=False):
    if not results:
        return records.prefetch_original_sources(store, ids)
    folder = f'{records.ROOT}/{store.day}'
    paths = set()
    for rid in ids:
        versions = store.index['results'].get(rid, ())
        if versions:
            paths.add(f"{folder}/{versions[-1]['evidence_sha256']}.sealed.json")
    try:
        return archive.prefetch_pinned_blobs(store.repo, store.head, paths,
                                             (folder, f'{archive.ROOT}/{store.day}'))
    except archive.GitCipherArchiveError:
        return 'BOUNDED_LAZY_READ_FALLBACK'


def run_holdout(work, *, owner_private_pem, trained, client, now, day=None, earlier_batch=False, progress=None,
                residual_context=None):
    """Read from a protected caller's fixed official state Git fetch."""
    _need(day is None or day in DAYS, 'HOLDOUT_DAY_OUTSIDE_FIXED_PERIOD')
    _need(day is None or not earlier_batch, 'HOLDOUT_BATCH_AND_DAY_CONFLICT')
    residual = residual_context is not None
    _need(not residual or (day is None and not earlier_batch), 'RESIDUAL_FIXED_PERIOD_REQUIRED')
    _need(trained.to_dict()['model_sha256'] == shadow.MODEL_SHA and
          trained.fit_meta['parameter_information_end_day'] == '2026-07-31', 'HOLDOUT_FROZEN_MODEL_BINDING')
    fixed_days, pin, arms = (RESIDUAL_DAYS, RESIDUAL_ARCHIVE, RESIDUAL_ARMS) if residual else (DAYS, ARCHIVE_COMMIT, ARMS)
    chosen_days = fixed_days[:-1] if earlier_batch else fixed_days
    if day is not None:
        chosen_days = (day,)
    stores, registries, paired = {}, {}, {}
    holds, by_day, cache = Counter(), {}, {}
    day_holds = {}
    history = None

    # Freeze every calculable pair before any target result is opened for scoring.
    # The existing prior-day history adapter may use earlier days as features.
    for target_day in chosen_days:
        store = records.RecordStore(work, target_day, index_commit=pin)
        _need(store.head == pin and store.day == target_day, 'HOLDOUT_ARCHIVE_PIN')
        stores[target_day] = store
        registry = settlement._load_registry(store, owner_private_pem)
        ids = registry['registered_race_ids']
        _need(len(set(ids)) == len(ids) and all(rid[:8] == target_day.replace('-', '') for rid in ids),
              'HOLDOUT_REGISTRY_BINDING')
        registries[target_day] = registry
        prefetch = _prefetch_targets(store, ids)
        if progress is not None:
            progress('ORIGINALS_PREFETCH', target_day, prefetch)
        guard = Counter()
        history = OfficialHistory(store, owner_private_pem) if history is None else history.for_day(store)
        replay_options = {'residual_context': residual_context} if residual else {}
        for rid in ids:
            meta = store.index['originals'].get(rid)
            if meta is None:
                guard['SAVED_ORIGINAL_MISSING'] += 1
                continue
            try:
                paired[rid] = _replay_pair(store, rid, meta, owner_private_pem, trained, client, cache, history,
                                           **replay_options)
            except HoldoutError as error:
                guard[str(error)] += 1
            except Exception as error:
                guard[shadow._source_failure('SOURCE_OR_FEATURE_REPLAY_UNVERIFIED', error)] += 1
        holds.update(guard)
        day_holds[target_day] = dict(guard)
        if progress is not None:
            progress('FORECASTS_REPLAYED', target_day, len(ids) - sum(guard.values()))

    result_states, result_holds = Counter(), Counter()
    official_scorable, scores = 0, {}
    for target_day in chosen_days:
        rows = {arm: [] for arm in arms}
        held, states = Counter(), Counter()
        t15_pairs = history_pairs = scorable = 0
        store, registry = stores[target_day], registries[target_day]
        prefetch = _prefetch_targets(store, registry['registered_race_ids'], results=True)
        if progress is not None:
            progress('RESULTS_PREFETCH', target_day, prefetch)
        for rid in registry['registered_race_ids']:
            pair = paired.get(rid)
            if pair is not None:
                t15_pairs += 1
                history_pairs += int(bool(pair['history_races']))
            result = settlement._result_row(store, rid, owner_private_pem, store.index['originals'].get(rid), now())
            _need(result['race_id'] == rid and result['day'] == target_day, 'HOLDOUT_RESULT_BINDING')
            states[result['result_status']] += 1
            if 'result_hold_reason' in result:
                held[result['result_hold_reason']] += 1
            if result['result_status'] != 'VERIFIED_NORMAL':
                continue
            scorable += 1
            if pair is not None:
                for arm in arms:
                    rows[arm].append(_score(pair['laws'][arm], tuple(result['top3'])))
        n = len(rows['warm'])
        if n:
            scores[target_day] = {arm: dict(n=n, **{metric: fsum(values)
                for metric, values in zip(RANK_METRICS + PROPER_METRICS, zip(*rows[arm]), strict=True)})
                for arm in arms}
        registered = len(registry['registered_race_ids'])
        _need(registered == t15_pairs + sum(day_holds[target_day].values()), 'HOLDOUT_FORECAST_DENOMINATOR')
        by_day[target_day] = dict(registered_races=registered, original_pairs_at_t15=t15_pairs,
            original_pairs_with_prior_history=history_pairs, original_holds=day_holds[target_day],
            day_inventory_complete=registry['day_inventory_complete'], missing_venues=len(registry['missing_venues']),
            official_scorable_races=scorable, common_scorable_races=n, result_states=dict(states))
        official_scorable += scorable
        result_states.update(states)
        result_holds.update(held)
        if progress is not None:
            progress('RESULTS_REPLAYED', target_day, n)

    common = sum(d['common_scorable_races'] for d in by_day.values())
    metrics, optional = _paired_metrics(scores, arms, baseline='warm' if residual else 'cold')
    if residual:
        optional['winner_residual_file_sha256'] = RESIDUAL_FILE_SHA
    else:
        optional['fixed_warm_mixture_weights'] = [.25, .50]
    return dict(schema='DT_R1_SAVED_OFFICIAL_HOLDOUT_V1', fixed_period=list(fixed_days), evaluated_days=list(chosen_days),
        state='OFFICIAL_HOLDOUT_SCORED' if common else 'HOLD_NO_OFFICIAL_HOLDOUT_COMMON_RESULT',
        archive_commit=pin, model_sha256=shadow.MODEL_SHA,
        registered_races=sum(d['registered_races'] for d in by_day.values()),
        original_pairs_at_t15=len(paired), source_holds=dict(holds), result_states=dict(result_states),
        result_replay_holds=dict(result_holds), official_scorable_races=official_scorable,
        official_scorable_without_t15_pair=official_scorable - common, common_scorable_races=common,
        pairs_without_scorable_result=len(paired) - common, metrics=metrics, by_day=by_day,
        scope='AFTER_THE_FACT_OFFICIAL_UNUSED_PERIOD', prospectively_sealed=False,
        venue_geometry='OMITTED_POSTDATED_SIDECAR', target_clock='INDEPENDENT_GITHUB_ORIGIN_BY_T15',
        history_clock='EARLIER_OFFICIAL_RESULT_OBSERVATION_AND_ARCHIVE_SEAL_BY_T15',
        parameter_selection_run=False, production_promoted=False,
        **optional)
