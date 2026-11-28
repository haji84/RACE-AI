"""Developmental opponent-adjusted latent form learned from archived finishes.

On each JST date all comparisons use the previous day's rating state. Each
numeric finisher's earlier/later comparisons within a race update an Elo-like
log-odds score, weighted by opponent count, once the whole date has passed.
Earlier ratings and effective starts decay, and small samples shrink to zero.
The archive's composite identities and historical availability are unverified.
June alone chooses a fixed coefficient and temperature for a shift in the DT-R1
winner logits. July is the existing developmental month on 2,393 scorable races,
and no earlier freeze, production entrant, or August onward evaluation changes.
"""
import argparse
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from itertools import combinations, groupby, product
from math import exp, fsum, log
import os
from pathlib import Path
import subprocess
import time

import numpy as np

from scripts.keirin_dt_r1_future_shadow import MODEL_FILE_SHA, MODEL_SHA, load_frozen

from .boosted_first_study import (_features, _joint, _report_july, _score, EXPECTED_JULY,
                                 SPLITS, marginal, reweight_joint, softmax, validate_july)
from .data import IDENTITY_STATUS, PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from .frozen_followup import GEOMETRY, OLD_DATASET, ROOT, FeatureBuilder, check
from .historical_replay import digest_file
from .history_mix_study import prior_week
from .pipeline import _result_key, write_private_json
from .policy import digest


HALF_LIFE = 45.
SHRINK_STARTS = 8.
STEP = .65
BETAS = (0., .25, .5, 1.)
TEMPERATURES = (.9, 1., 1.1)
GRID = tuple(product(BETAS, TEMPERATURES))


def _identity(rider):
    key = rider.get('identity_key')
    if (rider.get('identity_usable') is True and rider.get('identity_status') == IDENTITY_STATUS
            and isinstance(key, str) and key):
        return key
    return None


def _finishers(row):
    if str(row.get('result_status', '')).upper() in ('CANCELLED', 'PENDING', 'MISSING'):
        return []
    names = {r['car']: _identity(r) for r in row['riders']}
    pairs = [(names[out.get('car')], out['rank']) for out in row['result_rows']
             if names.get(out.get('car')) and type(out.get('rank')) is int
             and 1 <= out['rank'] <= len(row['riders']) and not out.get('cancelled') and not out.get('absence')]
    if len({identity for identity, _ in pairs}) != len(pairs):
        return []
    return sorted(pairs, key=lambda item: (item[1], item[0]))


@dataclass(frozen=True)
class _Rating:
    score: float
    starts: float
    day: date


class PairStrength:
    def __init__(self):
        self._state = {}
        self.last_day = None
        self.pairs = self.races = 0

    def _decayed(self, identity, day):
        prior = self._state.get(identity)
        if prior is None:
            return 0., 0.
        age = (day - prior.day).days
        factor = 2. ** (-age / HALF_LIFE)
        return prior.score * factor, prior.starts * factor

    def strength(self, identity, day):
        check(self.last_day is None or self.last_day < day, 'RATING_REQUIRES_PRIOR_JST_DAY')
        score, starts = self._decayed(identity, day)
        return score * starts / (starts + SHRINK_STARTS)

    def update_day(self, day, rows):
        check(self.last_day is None or self.last_day < day, 'RATING_UPDATE_ASCENDING_JST_DAY')
        changes, starts = defaultdict(list), defaultdict(int)
        for row in rows:
            check(row['day'] == day.isoformat(), 'RATING_UPDATE_SINGLE_JST_DAY')
            ranked = _finishers(row)
            if len(ranked) < 2:
                continue
            strength = {identity: self.strength(identity, day) for identity, _ in ranked}
            weight = STEP / (len(ranked) - 1)
            admitted = set()
            for (ahead, place), (behind, other_place) in combinations(ranked, 2):
                if place == other_place:
                    continue
                expected = 1. / (1. + exp(strength[behind] - strength[ahead]))
                delta = weight * (1. - expected)
                changes[ahead].append(delta)
                changes[behind].append(-delta)
                admitted.update((ahead, behind))
                self.pairs += 1
            if admitted:
                self.races += 1
            for identity in admitted:
                starts[identity] += 1
        for identity, delta in changes.items():
            score, count = self._decayed(identity, day)
            self._state[identity] = _Rating(min(4., max(-4., score + fsum(delta))), count + starts[identity], day)
        self.last_day = day

    def receipt(self):
        return dict(races_with_admitted_pairs=self.races, ordered_pair_observations=self.pairs,
                    composite_identities_rated=len(self._state))


def _winner_probabilities(first, strengths, beta, temperature):
    check(first.keys() == strengths.keys(), 'WINNER_STRENGTH_CAR_SUPPORT')
    cars = sorted(first)
    values = softmax([log(first[car]) + beta * strengths[car] for car in cars], temperature)
    return dict(zip(cars, values, strict=True))


def _first(joint):
    return {prefix[0]: p for prefix, p in marginal(joint, count=1).items()}


def adjust_joint(joint, strengths, beta, temperature):
    if beta == 0. and temperature == 1.:
        return joint
    return reweight_joint(joint, _winner_probabilities(_first(joint), strengths, beta, temperature))


def _contract():
    return dict(schema='DT_R1_RIDER_STRENGTH_CONTRACT_V1',
        archive_learning=['2025-10-01', 'strictly_earlier_jst_days'],
        identity_scope=IDENTITY_STATUS, official_registration_verified=False, pre_cutoff_time_verified=False,
        comparisons='same_race_valid_numeric_unequal_finishes_only',
        decay_half_life_days=HALF_LIFE, shrink_prior_effective_starts=SHRINK_STARTS,
        step_per_race=STEP, state_clip_log_odds=4.,
        winner_rule='softmax((log(frozen_seven_first)+beta*opponent_adjusted_score)/temperature)',
        fixed_conditionals='same_frozen_seven_day_DTR1_2nd_and_3rd',
        tune=SPLITS['june'], evaluation=SPLITS['july'], expected_july=EXPECTED_JULY,
        betas=BETAS, temperatures=TEMPERATURES,
        selection='june_winner_log_loss_then_lower_beta_then_temperature_nearer_one_then_lower_temperature',
        comparison_for_july=['frozen_seven_day', 'frozen_cold'], old_final_used=False,
        production_promoted=False, independent_accuracy_claim=False)


def run(paths, private):
    started = time.monotonic()
    at = datetime.now(timezone.utc).isoformat()
    code = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    script = digest_file(Path(__file__))
    contract = _contract()
    contract_sha = digest(contract)
    write_private_json(private / 'contract.json', dict(contract=contract, contract_sha256=contract_sha,
                                                      script_sha256=script, code_base=code, started_at=at))
    frozen, venues = load_frozen(ROOT.parents[1])
    check({p.name for p in paths} == PINNED_SOURCE_SHA256.keys() and len(paths) == 2, 'ARCHIVE_PAIR')
    data, audit = load_archives(paths)
    check(audit['dataset_sha256'] == OLD_DATASET and len(data) == 30713, 'ARCHIVE_DATASET')
    july = [r for r in data if SPLITS['july'][0] <= r['day'] <= SPLITS['july'][1]]
    expected = [r['race_id'] for r in july if _result_key(r) is not None]
    validate_july(expected, expected)
    ratings, queue = PairStrength(), deque()
    selection_n, losses = 0, {item: [] for item in GRID}
    blocks, seen, chosen, july_strength_races = {}, [], None, 0
    for stamp, group in groupby(data, key=lambda r: r['day']):
        if stamp > SPLITS['july'][1]:
            break
        rows, day = list(group), date.fromisoformat(stamp)
        while queue and queue[0][0] < day - timedelta(days=7):
            queue.popleft()
        if stamp >= SPLITS['july'][0] and chosen is None:
            check(selection_n == 2244, 'JUNE_SCORABLE_DENOMINATOR')
            mean_losses = {item: fsum(v) / selection_n for item, v in losses.items()}
            chosen = min(GRID, key=lambda item: (mean_losses[item], item[0], abs(item[1] - 1.), item[1]))
            params = dict(schema='DT_R1_ARCHIVED_RIDER_STRENGTH_PARAMETERS_V1', contract_sha256=contract_sha,
                          frozen_model_sha256=MODEL_SHA, beta=chosen[0], temperature=chosen[1])
            params_sha = digest(params)
            frozen_at = datetime.now(timezone.utc).isoformat()
            before_july = ratings.receipt()
            write_private_json(private / 'parameters.json', dict(parameters=params, parameters_sha256=params_sha,
                                                                  frozen_at=frozen_at))
            print('JUNE_PARAMETERS_FROZEN', selection_n, params_sha, flush=True)
        if stamp >= SPLITS['june'][0]:
            eligible = [(row, truth) for row in rows if (truth := _result_key(row)) is not None]
            if eligible:
                kept, outcomes = zip(*eligible)
                recent_builder = FeatureBuilder()
                for prior in prior_week(queue, day):
                    recent_builder.update_day(prior)
                recent = _features(kept, recent_builder, frozen, venues, at)
                cold = _features(kept, FeatureBuilder(), frozen, venues, at) if chosen else None
                metrics = {name: [] for name in ('candidate', 'frozen_cold', 'frozen_seven')}
                for i, (row, truth) in enumerate(zip(recent, outcomes, strict=True)):
                    strengths = {r['car']: ratings.strength(_identity(r), day) for r in row['riders']}
                    base = _joint(frozen, row)
                    if chosen is None:
                        first = _first(base)
                        for beta, temp in GRID:
                            p = _winner_probabilities(first, strengths, beta, temp)[truth[0]]
                            losses[(beta, temp)].append(-log(max(p, 1e-300)))
                        selection_n += 1
                    else:
                        july_strength_races += int(any(strengths.values()))
                        seen.append(row['race_id'])
                        metrics['candidate'].append(_score(adjust_joint(base, strengths, *chosen), truth))
                        metrics['frozen_seven'].append(_score(base, truth))
                        metrics['frozen_cold'].append(_score(_joint(frozen, cold[i]), truth))
                if chosen:
                    blocks[stamp] = {name: (len(kept), np.sum(scores, axis=0)) for name, scores in metrics.items()}
        ratings.update_day(day, rows)
        queue.append((day, rows))
    validate_july(expected, seen)
    return dict(schema='DT_R1_RIDER_STRENGTH_STUDY_V1', code_base=code, script_sha256=script, started_at=at,
        runtime_seconds=round(time.monotonic() - started, 3), contract=contract, contract_sha256=contract_sha,
        parameter_sha256=params_sha, parameters=params, parameter_frozen_at=frozen_at,
        learning=dict(before_july=before_july, through_july=ratings.receipt(),
                      july_races_with_nonzero_adjustment_signal=july_strength_races),
        june=dict(scorable=selection_n, winner_log_loss=[
            dict(beta=beta, temperature=temp, log_loss=mean_losses[(beta, temp)]) for beta, temp in GRID]),
        july=dict(cards=len(july), exclusions=len(july) - EXPECTED_JULY, cohort_sha256=digest(sorted(expected)),
                  **_report_july(blocks)),
        archive=dict(commit=SOURCE_COMMIT, dataset_sha256=OLD_DATASET, files=PINNED_SOURCE_SHA256,
                     retrospective_venue_geometry_sha256=GEOMETRY),
        frozen_model=dict(sha256=MODEL_SHA, file_sha256=MODEL_FILE_SHA, feature_count=len(frozen.feature_names)))


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
