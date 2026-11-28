"""Single-column sensitivity of the frozen DT-R1 on its old July tune set.

Drop each column's first/second/third coefficients alone. Standardization,
clipping, conditional pair terms and all other coefficients stay fixed.
Entirely inactive columns, and columns constant within every race after
scaling, leave the softmax invariant. Close market-ranking boundaries use the
native engine so floating-point perturbations cannot select a different tie
break. Archived identity and historical cutoff availability are unverified.
"""
import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from itertools import permutations
from math import fsum, log
import os
from pathlib import Path
import subprocess
import time

import numpy as np

from scripts.keirin_dt_r1_future_shadow import MODEL_FILE_SHA, MODEL_SHA, load_frozen

from .abilities import DISC_NAMES
from .boosted_first_study import _features, EXPECTED_JULY, SPLITS, validate_july, week_groups
from .data import PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from .frozen_followup import GEOMETRY, OLD_DATASET, ROOT, FeatureBuilder, check
from .historical_replay import digest_file
from .history_mix_study import BOOTSTRAP_N, BOOTSTRAP_SEED, METRICS, RANK_METRICS
from .pipeline import _result_key, write_private_json
from .policy import digest


RANK_EPSILON = 1e-12
SOFT_BUDGET_SECONDS = 205
REPRESENTATIVES = ('points', 'points_relative', 'win_rate', 'top2_rate', 'top3_rate', 'age',
    'gear_ratio', 'style_nige', 'line_known', 'line_leader', 'line_second', 'line_position_fraction',
    'line_predecessor_points_gap', 'line_strength_gap', 'history_form_last5', 'history_same_venue_form',
    'history_half_lap_mean', 'history_venue_half_lap_mean', 'history_agari_venue_relative', 'history_s_rate',
    'history_b_rate', 'history_rest_days_log', 'history_starts_7d', 'history_dt_recent_load_proxy',
    'history_dt_rival_pressure', 'history_dt_third_line_opportunity', 'history_dt_load_x_pressure',
    'context_venue_circumference_m', 'context_venue_straight_m', 'context_venue_cant_deg', *DISC_NAMES)


@dataclass
class RaceImpact:
    baseline: np.ndarray
    impacts: np.ndarray
    capable: np.ndarray
    fallbacks: int


def _masked_softmax(logits, allowed, temperature):
    shifted = np.where(allowed, logits / temperature, -np.inf)
    shifted -= shifted.max(axis=-1, keepdims=True)
    masses = np.exp(shifted)
    return masses / masses.sum(axis=-1, keepdims=True)


def _tickets(cars, size):
    order = sorted(range(len(cars)), key=cars.__getitem__)
    return np.array(list(permutations(order, size)), dtype=np.intp)


def batch_trials(model, row, allowed):
    cars, base, pairs = model._prepared(row)
    x = np.clip((row['features'] - model.mean) / model.scale, -12., 12.)
    capable = np.any(model.weights[:3] != 0., axis=0) & np.any(x != x[0], axis=0)
    selected = allowed[capable[allowed]]
    if selected.size == 0:
        return capable, selected, None, None
    individual = base[None, :, :3] - x[:, selected].T[:, :, None] * model.weights[:3, selected].T[:, None, :]
    prev = pairs.transpose(1, 0, 2)
    next2 = prev @ model.pair_weights[1]
    next3 = (prev[:, None] + prev[None, :]) @ model.pair_weights[2]
    different = ~np.eye(len(cars), dtype=bool)
    first = _masked_softmax(individual[:, :, 0], True, model.temperature)
    second = _masked_softmax(individual[:, None, :, 1] + next2[None], different, model.temperature)
    third = _masked_softmax(individual[:, None, None, :, 2] + next3[None],
                            different[:, None, :] & different[None, :, :], model.temperature)
    ex = first[:, :, None] * second
    tri = ex[:, :, :, None] * third
    return capable, selected, (_tickets(cars, 2), ex), (_tickets(cars, 3), tri)


def _position_vector(tickets, mass, truth, sizes):
    truth_position = np.flatnonzero(np.all(tickets == truth, axis=1))
    check(len(truth_position) == 1, 'UNIQUE_TICKET_REQUIRED')
    idx = truth_position.item()
    p = mass[:, idx]
    differences = mass - p[:, None]
    earlier = np.arange(len(tickets)) < idx
    ranks = np.sum((differences > 0.) | ((differences == 0.) & earlier), axis=1)
    strict = np.sum(differences > RANK_EPSILON, axis=1)
    possible = np.sum(differences >= -RANK_EPSILON, axis=1) - 1
    k = np.array(sizes)
    ambiguous = np.any((strict[:, None] < k) & (possible[:, None] >= k), axis=1)
    hit = ranks[:, None] < k
    proper = (-np.log(np.maximum(p, 1e-300)), 1. - 2. * p + np.square(mass).sum(axis=1))
    return hit, proper, ambiguous


def native_metrics(model, row, truth):
    markets = model.distribution(row)
    result = {}
    hits, losses, briers = [], [], []
    for name, actual, sizes in (('trifectas', truth, (1, 2, 4)), ('exactas', truth[:2], (1, 2))):
        entries = markets[name]
        actual_index = next(i for i, t in enumerate(entries) if tuple(t['cars']) == actual)
        p = entries[actual_index]['probability']
        result[name] = dict(zip(sizes, (actual_index < k for k in sizes), strict=True))
        losses.append(-log(max(p, 1e-300)))
        briers.append(1. - 2. * p + fsum(t['probability'] ** 2 for t in entries))
    tri, ex = result['trifectas'], result['exactas']
    hits = (tri[1], ex[1], tri[2], tri[4], ex[2])
    return np.array((*hits, *losses, *briers), dtype=float)


def profile_race(model, row, truth, allowed):
    full = native_metrics(model, row, truth)
    capable, selected, ex, tri = batch_trials(model, row, allowed)
    impacts = np.zeros((len(model.feature_names), len(METRICS)))
    if not selected.size:
        return RaceImpact(full, impacts, capable, 0)
    cars = [r['car'] for r in row['riders']]
    order = tuple(cars.index(car) for car in truth)
    ex_tickets, ex_mass = ex
    tri_tickets, tri_mass = tri
    a, b = ex_tickets.T
    ex_hit, (ex_loss, ex_brier), ex_near = _position_vector(ex_tickets, ex_mass[:, a, b], order[:2], (1, 2))
    a, b, c = tri_tickets.T
    tri_hit, (tri_loss, tri_brier), tri_near = _position_vector(
        tri_tickets, tri_mass[:, a, b, c], order, (1, 2, 4))
    values = np.column_stack((tri_hit[:, 0], ex_hit[:, 0], tri_hit[:, 1], tri_hit[:, 2], ex_hit[:, 1],
                              tri_loss, ex_loss, tri_brier, ex_brier))
    near = np.flatnonzero(ex_near | tri_near)
    for v in near:
        weights = model.weights.copy()
        weights[:3, selected[v]] = 0.
        values[v] = native_metrics(replace(model, weights=weights), row, truth)
    impacts[selected] = values - full
    return RaceImpact(full, impacts, capable, len(near))


def _contract():
    return dict(schema='DT_R1_SINGLE_COLUMN_ABLATION_CONTRACT_V1', dates=SPLITS['july'], common_n=EXPECTED_JULY,
        history='strictly_earlier_seven_jst_days', intervention='single_column_first_second_third_weights_zero',
        ranking='native_probability_descending_then_car_tuple_ascending',
        native_boundary_guard=RANK_EPSILON, mathematically_invariant=['no_top3_weight', 'racewise_constant'],
        bootstrap=dict(unit='paired_jst_day', draws=BOOTSTRAP_N, seed=BOOTSTRAP_SEED),
        fallback=dict(soft_budget_seconds=SOFT_BUDGET_SECONDS, representative_features=REPRESENTATIVES),
        archived_availability_verified=False, official_identity_verified=False, prior_final_period_used=False,
        causal=False, refit=False, adoption_selected=False)


def _report(model, n, blocks, capable, finished):
    day_n = np.array([d[0] for d in blocks])
    samples = np.random.default_rng(BOOTSTRAP_SEED).integers(0, len(day_n), (BOOTSTRAP_N, len(day_n)))
    bootstrap_n = day_n[samples].sum(axis=1)
    daily = np.stack([d[1] for d in blocks])
    done = set(finished.tolist())
    measured, no_effect, deferred = {}, {}, []
    for i, name in enumerate(model.feature_names):
        if not capable[i]:
            no_effect[name] = 'INACTIVE_TOP3_COEFFICIENTS' if not np.any(model.weights[:3, i]) else (
                'CONSTANT_WITHIN_EACH_RACE_AFTER_SCALING')
        elif i not in done:
            deferred.append(name)
        else:
            changes = daily[:, i]
            delta = changes.sum(axis=0)
            intervals = np.quantile(changes[samples].sum(axis=1) / bootstrap_n[:, None], [.025, .975], axis=0).T
            measured[name] = dict(capable_races=int(capable[i]),
                difference={key: dict(delta_per_race=float(delta[j] / n), paired_day_ci95=intervals[j].tolist())
                            for j, key in enumerate(METRICS)},
                hit_delta={key: int(delta[j]) for j, key in enumerate(RANK_METRICS)})
    return dict(measured=measured, mathematically_no_effect=no_effect, deferred=deferred)


def run(paths, private):
    started = time.monotonic()
    at = datetime.now(timezone.utc).isoformat()
    model, venues = load_frozen(ROOT.parents[1])
    contract = _contract()
    source = digest_file(Path(__file__))
    base_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    contract_sha = digest(contract)
    write_private_json(private / 'contract.json', dict(contract=contract, contract_sha256=contract_sha,
        started_at=at, code_base=base_sha, script_sha256=source))
    check({p.name for p in paths} == PINNED_SOURCE_SHA256.keys() and len(paths) == 2, 'ARCHIVE_PAIR')
    data, audit = load_archives(paths)
    check(len(data) == 30713 and audit['dataset_sha256'] == OLD_DATASET, 'ARCHIVE_DATASET')
    cards = [r for r in data if SPLITS['july'][0] <= r['day'] <= SPLITS['july'][1]]
    expected = [r['race_id'] for r in cards if _result_key(r) is not None]
    validate_july(expected, expected)
    score_start = time.monotonic()
    allowed = np.arange(len(model.feature_names))
    representatives = np.array([i for i, n in enumerate(model.feature_names) if n in REPRESENTATIVES])
    capable = np.zeros(len(allowed), dtype=int)
    full = np.zeros(len(METRICS))
    blocks, seen, fallbacks, limited = [], [], 0, False
    for day, rows, earlier in week_groups(data, *SPLITS['july']):
        eligible = [(row, truth) for row in rows if (truth := _result_key(row)) is not None]
        if not eligible:
            continue
        kept, outcomes = zip(*eligible)
        builder = FeatureBuilder()
        for _, prior in earlier:
            builder.update_day(prior)
        features = _features(kept, builder, model, venues, at)
        delta = np.zeros((len(model.feature_names), len(METRICS)))
        for row, truth in zip(features, outcomes, strict=True):
            stat = profile_race(model, row, truth, allowed)
            full += stat.baseline
            capable += stat.capable
            delta += stat.impacts
            fallbacks += stat.fallbacks
            seen.append(row['race_id'])
        blocks.append((len(kept), delta))
        projected = (time.monotonic() - score_start) * EXPECTED_JULY / len(seen)
        if len(blocks) >= 3 and not limited and projected + score_start - started > SOFT_BUDGET_SECONDS:
            allowed, limited = representatives, True
        print('DAY_COMPARED', day.isoformat(), len(kept), flush=True)
    validate_july(expected, seen)
    baseline = dict(hits={key: int(full[i]) for i, key in enumerate(RANK_METRICS)},
                    proper={key: float(full[i] / EXPECTED_JULY) for i, key in enumerate(METRICS)
                            if i >= len(RANK_METRICS)})
    output = _report(model, EXPECTED_JULY, blocks, capable, allowed)
    return dict(schema='DT_R1_SINGLE_COLUMN_ABLATION_STUDY_V1', script_sha256=source, code_base=base_sha,
        runtime_seconds=round(time.monotonic() - started, 3), started_at=at, contract=contract,
        contract_sha256=contract_sha, native_rank_boundary_replays=fallbacks, budget_limited=limited,
        model=dict(sha256=MODEL_SHA, file_sha256=MODEL_FILE_SHA, feature_count=len(model.feature_names)),
        archive=dict(commit=SOURCE_COMMIT, dataset_sha256=OLD_DATASET, files=PINNED_SOURCE_SHA256,
                     retrospective_venue_geometry_sha256=GEOMETRY),
        july=dict(cards=len(cards), common_scorable=EXPECTED_JULY, days=len(blocks),
                  excluded_without_unique_trifecta=len(cards) - EXPECTED_JULY, cohort_sha256=digest(sorted(expected))),
        baseline=baseline, **output)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('private', type=Path)
    cli.add_argument('archives', type=Path, nargs=2)
    args = cli.parse_args()
    os.umask(0o077)
    directory = args.private.resolve()
    check(directory.is_dir() and not any(directory.iterdir()) and not directory.stat().st_mode & 0o077 and
          not any((parent / '.git').exists() for parent in (directory, *directory.parents)), 'PRIVATE_RUNNER_PATH')
    receipt = run(args.archives, directory)
    write_private_json(directory / 'aggregate.json', receipt)
    print('AGGREGATE_SAVED', receipt['runtime_seconds'], flush=True)


if __name__ == '__main__':
    main()
