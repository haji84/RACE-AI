"""Discover recurring ordered-line motifs as a frozen DT-R1 archive residual."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import exp, fsum, log
import os
from pathlib import Path
import subprocess
import time

from scripts.keirin_dt_r1_future_shadow import MODEL_FILE_SHA, MODEL_SHA, load_frozen

from .boosted_first_study import EXPECTED_JULY, _features, _joint, validate_july, week_groups
from .data import IDENTITY_STATUS, PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from .features import FeatureBuilder
from .frozen_followup import GEOMETRY, OLD_DATASET, OLD_N, ROOT, check
from .historical_replay import digest_file
from .history_mix_study import (BOOTSTRAP_N, BOOTSTRAP_SEED, _score, _summary, _sums,
                                paired_difference)
from .pipeline import _result_key, write_private_json
from .policy import digest


PERIODS = dict(fit=('2026-03-01', '2026-05-31'), select=('2026-06-01', '2026-06-30'),
               july=('2026-07-01', '2026-07-31'))
EXPECTED_COVERAGE = 3.
SHRINKAGE = (10, 40)
STRENGTH = (.5, 1.)
BASELINE = (0, 0.)
GRID = (BASELINE,) + tuple((prior, strength) for prior in SHRINKAGE for strength in STRENGTH)
ORDERED_POSITIONS = ((0, 1), (0, 2), (1, 2))
GAP_RATIOS = (.85, .50)


def _line_state(row):
    cars = [r['car'] for r in row['riders']]
    if row.get('lines_applicable') is False:
        return 'LINE_NOT_APPLICABLE', {}
    if row.get('lines_known') is not True:
        return 'LINE_UNKNOWN', {}
    groups = row['line_groups']
    check(all(groups) and sorted(car for group in groups for car in group) == sorted(cars),
          'LINE_DISCOVERY_ROSTER')
    positions = {car: (group_id, place, len(group)) for group_id, group in enumerate(groups)
                 for place, car in enumerate(group)}
    return 'LINE_KNOWN', positions


def _relations(row):
    state, positions = _line_state(row)
    relation = {}
    cars = [r['car'] for r in row['riders']]
    for left in cars:
        for right in cars:
            if left == right:
                continue
            if not positions:
                relation[left, right] = (state, (-1, -1), (-1, -1))
                continue
            lg, lp, ln = positions[left]
            rg, rp, rn = positions[right]
            if lg != rg:
                kind = 'DIFFERENT_LINES'
            else:
                direction = 'FORWARD' if lp < rp else 'REVERSE'
                distance = 'ADJACENT' if abs(lp - rp) == 1 else 'SEPARATED'
                kind = f'SAME_{direction}_{distance}'
            relation[left, right] = (kind, (min(lp, 2), min(ln, 3)), (min(rp, 2), min(rn, 3)))
    return relation


def _gap_bucket(probability, best):
    near, middle = GAP_RATIOS
    return int(probability < near * best) + int(probability < middle * best)


def order_motifs(row, law):
    """Derive rank-position motifs from only the frozen law and current lines."""
    relations = _relations(row)
    first_two, first = defaultdict(float), defaultdict(float)
    best_third, best_second = defaultdict(float), defaultdict(float)
    for (a, b, c), mass in law.items():
        first_two[a, b] += mass
        best_third[a, b] = max(best_third[a, b], mass)
    for (a, b), mass in first_two.items():
        first[a] += mass
        best_second[a] = max(best_second[a], mass)
    best_first = max(first.values())
    first_gap = {a: _gap_bucket(mass, best_first) for a, mass in first.items()}
    second_gap = {pair: _gap_bucket(mass, best_second[pair[0]]) for pair, mass in first_two.items()}
    motifs = {}
    for ticket, mass in law.items():
        a, b, _ = ticket
        gaps = (first_gap[a], second_gap[a, b], _gap_bucket(mass, best_third[a, b]))
        motifs[ticket] = tuple((family, *relations[ticket[i], ticket[j]], gaps[i], gaps[j])
                               for family, (i, j) in enumerate(ORDERED_POSITIONS))
    return motifs


def adjusted_law(baseline, motifs, lifts, strength):
    if not strength:
        return baseline
    weighted = {ticket: mass * exp(strength * fsum(lifts.get(code, 0.) for code in motifs[ticket])
                                    / len(motifs[ticket])) for ticket, mass in baseline.items()}
    total = fsum(weighted.values())
    check(total > 0, 'LINE_DISCOVERY_MASS')
    return {ticket: mass / total for ticket, mass in weighted.items()}


def choose_candidate(report):
    baseline = report[BASELINE]['proper']
    guarded = [config for config, row in report.items()
               if all(row['proper'][metric] <= baseline[metric] for metric in ('tri_log_loss', 'ex_log_loss'))]
    return max(guarded, key=lambda config: (report[config]['hits']['tri1'],
        report[config]['hits']['ex1'], -config[1], config[0]))


def _cases(records, period, trained, venues, at):
    for day, rows, earlier in week_groups(records, *period):
        eligible = [(row, truth) for row in rows if (truth := _result_key(row)) is not None]
        if not eligible:
            yield day.isoformat(), len(rows), ()
            continue
        cards, truths = zip(*eligible)
        history = FeatureBuilder()
        for _, prior in earlier:
            history.update_day(prior)
        featured = _features(cards, history, trained, venues, at)

        def observed():
            for row, truth in zip(featured, truths, strict=True):
                base = _joint(trained, row)
                yield row, truth, base, order_motifs(row, base)

        yield day.isoformat(), len(rows), observed()


def _fit(days):
    observed, expected, coverage = Counter(), defaultdict(float), Counter()
    for _, registered, cases in days:
        coverage['cards'] += registered
        for row, truth, law, motifs in cases:
            coverage['scorable'] += 1
            coverage[_line_state(row)[0]] += 1
            for ticket, mass in law.items():
                for key in motifs[ticket]:
                    expected[key] += mass
            observed.update(motifs[truth])
    check(coverage['scorable'] > 0, 'LINE_DISCOVERY_FIT_EMPTY')
    retained = {key: count for key, count in expected.items() if count >= EXPECTED_COVERAGE}
    lifts = {prior: {key: log((observed[key] + prior) / (count + prior)) for key, count in retained.items()}
             for prior in SHRINKAGE}
    return lifts, dict(coverage=coverage, discovered_keys=len(retained), generated_keys=len(expected))


def _assess(days, policies, lifts):
    by_day, admitted, counts = {}, [], Counter()
    for date, registered, cases in days:
        counts['cards'] += registered
        stage = {name: [] for name in policies}
        for row, truth, baseline, motifs in cases:
            admitted.append(row['race_id'])
            counts['scorable'] += 1
            counts[_line_state(row)[0]] += 1
            base_score = _score(baseline, truth)
            for name, (prior, strength) in policies.items():
                scores = (_score(adjusted_law(baseline, motifs, lifts[prior], strength), truth)
                          if strength else base_score)
                stage[name].append(scores)
        if any(stage.values()):
            by_day[date] = {name: _sums(rows) for name, rows in stage.items()}
    check(bool(by_day), 'LINE_DISCOVERY_ASSESSMENT_EMPTY')
    return by_day, admitted, counts


def contract():
    return dict(schema='DT_R1_LINE_ORDER_DISCOVERY_CONTRACT_V1', periods=PERIODS, prior_jst_days=7,
        scopes=dict(identity=IDENTITY_STATUS, pre_cutoff_time_verified=False,
            original_frozen_training_overlaps_selection=True, original_frozen_temperature_overlaps_july=True,
            independent_validation=False, promotion=False, august_onward_used=False),
        config_grid=GRID, position_pairs_zero_based=ORDERED_POSITIONS, probability_gap_ratios=GAP_RATIOS,
        motif_fields=['ordered_positions', 'line_relation_and_direction', 'both_roles_and_line_sizes',
                      'both_relative_conditional_probability_buckets'],
        rank_gap='selected probability divided by maximum at that position with same ordered prefix',
        guard='June joint trifecta and marginal exacta log loss no worse than frozen',
        selection_order=['trifecta_top1', 'exacta_top1', 'smaller_strength', 'larger_prior'],
        fit_min_expected_count=EXPECTED_COVERAGE,
        lift='log((observed + prior) / (expected_frozen + prior))',
        joint_reweight='frozen mass times exp(strength times mean ordered-pair lifts); renormalize once',
        exacta='exact prefix marginal of reweighted trifecta',
        bootstrap=dict(unit='paired JST day', samples=BOOTSTRAP_N, seed=BOOTSTRAP_SEED))


def run(paths, private):
    since = time.monotonic()
    at = datetime.now(timezone.utc).isoformat()
    spec = contract()
    pins = dict(contract=spec, contract_sha256=digest(spec), study_sha256=digest_file(Path(__file__)),
        code_base=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        source=dict(commit=SOURCE_COMMIT, dataset_sha256=OLD_DATASET, files=PINNED_SOURCE_SHA256),
        model=dict(id='chatgpt-dt-r1', sha256=MODEL_SHA, file_sha256=MODEL_FILE_SHA,
                   historical_geometry_assumption_sha256=GEOMETRY), started_at=at)
    write_private_json(private / 'contract.json', pins)
    print('CONTRACT_SAVED', pins['contract_sha256'], flush=True)
    check(len(paths) == 2 and {p.name for p in paths} == PINNED_SOURCE_SHA256.keys(), 'ARCHIVE_PAIR')
    records, source_audit = load_archives(paths)
    check(len(records) == OLD_N and source_audit['dataset_sha256'] == OLD_DATASET, 'ARCHIVE_DATASET_PIN')
    trained, venues = load_frozen(ROOT.parents[1])

    def cases(period):
        return _cases(records, PERIODS[period], trained, venues, at)

    lifts, fit = _fit(cases('fit'))
    print('FIT_COUNT', fit['coverage']['scorable'], fit['discovered_keys'], flush=True)
    june_days, _, june_counts = _assess(cases('select'), {config: config for config in GRID}, lifts)
    june = _summary(june_days)
    config = choose_candidate(june)
    fitted_sha = {str(prior): digest(sorted(lifts[prior].items())) for prior in SHRINKAGE}
    selected = dict(prior_count=config[0], strength=config[1], weight_sha256=fitted_sha.get(str(config[0])))
    write_private_json(private / 'parameters.json', dict(contract_sha256=pins['contract_sha256'], **selected))
    print('SELECTION_FROZEN', config[0], config[1], flush=True)

    july_days, admitted, july_counts = _assess(cases('july'), {'frozen': BASELINE, 'candidate': config}, lifts)
    expected = [row['race_id'] for row in records if PERIODS['july'][0] <= row['day'] <= PERIODS['july'][1]
                and _result_key(row) is not None]
    validate_july(expected, admitted)
    write_private_json(private / 'aggregate.json', dict(schema='DT_R1_LINE_ORDER_DISCOVERY_STUDY_V1',
        **pins, runtime_seconds=round(time.monotonic() - since, 3), production_promoted=False,
        feature_count=len(trained.feature_names), fit=fit, fitted_weight_sha256=fitted_sha, selected=selected,
        june=dict(counts=june_counts, days=len(june_days), grid=[dict(prior=key[0], strength=key[1], **june[key])
            for key in GRID]),
        july=dict(counts=july_counts, days=len(july_days), common_scorable=EXPECTED_JULY,
                  common_cohort_sha256=digest(sorted(admitted)), metrics=_summary(july_days),
                  paired=paired_difference(july_days, 'candidate', 'frozen'))))
    print('AGGREGATE_SAVED', flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('private', type=Path)
    cli.add_argument('archives', nargs=2, type=Path)
    opts = cli.parse_args()
    os.umask(0o077)
    private = opts.private.resolve()
    check(private.is_dir() and not any(private.iterdir()) and not private.stat().st_mode & 0o077
          and not any((parent / '.git').exists() for parent in (private, *private.parents)), 'PRIVATE_RUNNER_PATH')
    run(opts.archives, private)


if __name__ == '__main__':
    main()
