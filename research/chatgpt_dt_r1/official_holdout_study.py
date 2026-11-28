"""Unused official November 2026 holdout from a single retained archive pin.

This is a later recomputation from evidence available by T−15, not a sealed
historical forecast. In particular the frozen model was built after these
races. Retain only matched arms and never use the postdated geometry sidecar.
"""
from collections import Counter
from datetime import timedelta
from math import fsum

from race_ai import keirin_official_nationwide_records as records
from scripts import keirin_dt_r1_future_settle as settlement
from scripts import keirin_dt_r1_future_shadow as shadow

from .boosted_first_study import _joint, _score
from .history_mix_study import PROPER_METRICS, RANK_METRICS, mix_joint, paired_difference
from .official_history import OfficialHistory
from .policy import clock
from .venues import VenueStore


ARCHIVE_COMMIT = 'd030ed9e381cea00d3fe3f19bd4babb5bb38361e'
DAYS = tuple(f'2026-11-{day}' for day in range(23, 28))
ARMS = ('cold', 'warm', 'mix25', 'mix50')
PROPER_MIN_RACES = 30
PROPER_MIN_DAYS = 3


class HoldoutError(ValueError):
    pass


def _need(valid, reason):
    if not valid:
        raise HoldoutError(reason)


def _replay_pair(store, rid, meta, private, trained, client, cache, history):
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
    cold, cold_at, _ = shadow._candidate(store=store, payload=payload, original=original,
        trained=trained, venues=venues, private=private, client=client, cache=cache,
        clock=lambda: input_at, official_history=None)
    _need(warm['race_id'] == cold['race_id'] == rid and warm['input_sha256'] == cold['input_sha256'] and
          clock(warm_at) == clock(cold_at) == input_at, 'HOLDOUT_PAIRED_INPUT_CHANGED')
    _need(warm['feature_status'] == cold['feature_status'] == 'READY', 'HOLDOUT_FEATURES_UNVERIFIED')
    prior = warm['history_evidence']['official_support']['history_races']
    _need(cold['history_evidence']['official_support']['history_races'] == 0, 'HOLDOUT_COLD_HISTORY')
    cold_law, warm_law = _joint(trained, cold), _joint(trained, warm)
    # Identical laws must stay bit-for-bit equal rather than acquire
    # artificial ordering differences from a redundant floating-point mix.
    if warm_law == cold_law:
        return dict(history_races=prior, laws=dict.fromkeys(ARMS, cold_law))
    return dict(history_races=prior, laws=dict(cold=cold_law, warm=warm_law,
        mix25=mix_joint(cold_law, warm_law, .25), mix50=mix_joint(cold_law, warm_law, .50)))


def _paired_metrics(scores):
    paired_n = sum(d['warm']['n'] for d in scores.values())
    hits = {arm: dict(hits={metric: int(fsum(d[arm][metric] for d in scores.values()))
                           for metric in RANK_METRICS}) for arm in ARMS}
    if paired_n < PROPER_MIN_RACES or len(scores) < PROPER_MIN_DAYS:
        return hits, {}
    proper = {arm: {metric: fsum(d[arm][metric] for d in scores.values()) / paired_n
                    for metric in PROPER_METRICS} for arm in ARMS}
    differences = {arm: paired_difference(scores, arm, 'cold') for arm in ARMS if arm != 'cold'}
    return hits, dict(proper_scores=proper, paired_difference_from_cold=differences)


def run_holdout(work, *, owner_private_pem, trained, client, now, day=None):
    """Read from a protected caller's fixed official state Git fetch."""
    _need(day is None or day in DAYS, 'HOLDOUT_DAY_OUTSIDE_FIXED_PERIOD')
    _need(trained.to_dict()['model_sha256'] == shadow.MODEL_SHA and
          trained.fit_meta['parameter_information_end_day'] == '2026-07-31', 'HOLDOUT_FROZEN_MODEL_BINDING')
    chosen_days = DAYS if day is None else (day,)
    stores, registries, paired = {}, {}, {}
    holds, by_day, cache = Counter(), {}, {}
    day_holds = {}

    # Freeze every calculable pair before any target result is opened for scoring.
    # The existing prior-day history adapter may use earlier days as features.
    for target_day in chosen_days:
        store = records.RecordStore(work, target_day, index_commit=ARCHIVE_COMMIT)
        _need(store.head == ARCHIVE_COMMIT and store.day == target_day, 'HOLDOUT_ARCHIVE_PIN')
        stores[target_day] = store
        registry = settlement._load_registry(store, owner_private_pem)
        ids = registry['registered_race_ids']
        _need(len(set(ids)) == len(ids) and all(rid[:8] == target_day.replace('-', '') for rid in ids),
              'HOLDOUT_REGISTRY_BINDING')
        registries[target_day] = registry
        guard = Counter()
        history = OfficialHistory(store, owner_private_pem)
        for rid in ids:
            meta = store.index['originals'].get(rid)
            if meta is None:
                guard['SAVED_ORIGINAL_MISSING'] += 1
                continue
            try:
                paired[rid] = _replay_pair(store, rid, meta, owner_private_pem, trained, client, cache, history)
            except HoldoutError as error:
                guard[str(error)] += 1
            except Exception as error:
                guard[shadow._source_failure('SOURCE_OR_FEATURE_REPLAY_UNVERIFIED', error)] += 1
        holds.update(guard)
        day_holds[target_day] = dict(guard)

    result_states, result_holds = Counter(), Counter()
    official_scorable, scores = 0, {}
    for target_day in chosen_days:
        rows = {arm: [] for arm in ARMS}
        held, states = Counter(), Counter()
        t15_pairs = history_pairs = scorable = 0
        store, registry = stores[target_day], registries[target_day]
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
                for arm in ARMS:
                    rows[arm].append(_score(pair['laws'][arm], tuple(result['top3'])))
        n = len(rows['warm'])
        if n:
            scores[target_day] = {arm: dict(n=n, **{metric: fsum(values)
                for metric, values in zip(RANK_METRICS + PROPER_METRICS, zip(*rows[arm]), strict=True)})
                for arm in ARMS}
        registered = len(registry['registered_race_ids'])
        _need(registered == t15_pairs + sum(day_holds[target_day].values()), 'HOLDOUT_FORECAST_DENOMINATOR')
        by_day[target_day] = dict(registered_races=registered, original_pairs_at_t15=t15_pairs,
            original_pairs_with_prior_history=history_pairs, original_holds=day_holds[target_day],
            day_inventory_complete=registry['day_inventory_complete'], missing_venues=len(registry['missing_venues']),
            official_scorable_races=scorable, common_scorable_races=n, result_states=dict(states))
        official_scorable += scorable
        result_states.update(states)
        result_holds.update(held)

    common = sum(d['common_scorable_races'] for d in by_day.values())
    metrics, optional = _paired_metrics(scores)
    return dict(schema='DT_R1_SAVED_OFFICIAL_HOLDOUT_V1', fixed_period=list(DAYS), evaluated_days=list(chosen_days),
        state='OFFICIAL_HOLDOUT_SCORED' if common else 'HOLD_NO_OFFICIAL_HOLDOUT_COMMON_RESULT',
        archive_commit=ARCHIVE_COMMIT, model_sha256=shadow.MODEL_SHA,
        registered_races=sum(d['registered_races'] for d in by_day.values()),
        original_pairs_at_t15=len(paired), source_holds=dict(holds), result_states=dict(result_states),
        result_replay_holds=dict(result_holds), official_scorable_races=official_scorable,
        official_scorable_without_t15_pair=official_scorable - common, common_scorable_races=common,
        pairs_without_scorable_result=len(paired) - common, metrics=metrics, by_day=by_day,
        scope='AFTER_THE_FACT_OFFICIAL_UNUSED_PERIOD', prospectively_sealed=False,
        venue_geometry='OMITTED_POSTDATED_SIDECAR', target_clock='INDEPENDENT_GITHUB_ORIGIN_BY_T15',
        history_clock='EARLIER_OFFICIAL_RESULT_OBSERVATION_AND_ARCHIVE_SEAL_BY_T15',
        fixed_warm_mixture_weights=[.25, .50], parameter_selection_run=False, production_promoted=False,
        **optional)
