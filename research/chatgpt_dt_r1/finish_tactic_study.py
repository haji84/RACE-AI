"""Development-only DT-R1 mixture using the archived race-level finish tactic."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import fsum, log
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import unicodedata

from scripts.keirin_dt_r1_future_shadow import MODEL_FILE_SHA, MODEL_SHA, load_frozen

from .boosted_first_study import EXPECTED_JULY, _features, _joint, marginal, reweight_joint, validate_july, week_groups
from .data import (IDENTITY_STATUS, PINNED_SOURCE_SHA256, SOURCE_COMMIT, _race_identity,
                   _verify_file, load_archives)
from .features import FeatureBuilder
from .frozen_followup import GEOMETRY, OLD_DATASET, OLD_N, ROOT, check
from .historical_replay import digest_file
from .history_mix_study import (BOOTSTRAP_N, BOOTSTRAP_SEED, _score, _summary, _sums,
                                paired_difference)
from .pipeline import _result_key, write_private_json
from .policy import digest


PERIODS = dict(fit=('2026-01-01', '2026-05-31'), select=('2026-06-01', '2026-06-30'),
               july=('2026-07-01', '2026-07-31'))
CLASS_NAMES = ('逃', '捲', '差', 'マ')
CLASS_CODES = {text: i for i, aliases in enumerate(
    (('逃', '逃げ'), ('捲', '捲り', 'まくり'), ('差', '差し'), ('マ', 'マーク'))) for text in aliases}
CLASSES = tuple(range(len(CLASS_NAMES)))
STYLES = frozenset(('NIGE', 'RYO', 'OI', 'MAKURI', 'SASHI', 'JIZAI'))
STRENGTHS = (0., .25, .5, 1.)
FIELD_PRIOR = 50.
RIDER_PRIOR = 25.


def tactic_label(value):
    if value is None:
        return None, 'MISSING_MARK'
    if not isinstance(value, str):
        return None, 'UNKNOWN_MARK'
    value = unicodedata.normalize('NFKC', value).strip()
    if not value:
        return None, 'MISSING_MARK'
    mark = CLASS_CODES.get(value)
    return (mark, 'KNOWN') if mark is not None else (None, 'UNKNOWN_MARK')


def tactic_context(row):
    riders = row['riders']
    cars = [r['car'] for r in riders]
    roles = {}
    if row.get('lines_applicable') is False:
        state = 'LINE_NOT_APPLICABLE'
    elif row.get('lines_known') is not True:
        state = 'LINE_UNKNOWN'
    else:
        state = 'LINE_KNOWN'
        groups = row['line_groups']
        check(all(groups) and sorted(car for group in groups for car in group) == sorted(cars),
              'TACTIC_LINE_ROSTER')
        for group in groups:
            for i, car in enumerate(group):
                roles[car] = 'SINGLE' if len(group) == 1 else ('LEAD' if i == 0 else 'FOLLOW')
    field = state, min(len(row['line_groups']), 4) if roles else 0, min(len(cars), 7)
    return field, {r['car']: (r['style'] if r.get('style') in STYLES else 'UNKNOWN_STYLE',
                              roles.get(r['car'], state)) for r in riders}


def read_marks(path, period):
    path, _, _ = _verify_file(path, PINNED_SOURCE_SHA256)
    start, end = (stamp.replace('-', '') for stamp in period)
    labels = {}
    with sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        for row in db.execute('SELECT race_date, venue_code, rno, kimarite FROM races '
                              'WHERE race_date BETWEEN ? AND ? ORDER BY race_date, venue_code, rno', (start, end)):
            rid, _, _ = _race_identity(row)
            check(rid not in labels, 'TACTIC_MARK_DUPLICATE_RACE')
            labels[rid] = tactic_label(row['kimarite'])
    return labels


def _smooth(counts, parent, weight):
    total = sum(counts.values()) + weight
    return tuple((counts.get(i, 0) + weight * parent[i]) / total for i in CLASSES)


def _mark(labels, rid):
    return labels.get(rid, (None, 'MISSING_RACE_MARK'))


def _fit(records, labels):
    base, fields, winner_cases, coverage = Counter(), defaultdict(Counter), defaultdict(Counter), Counter()
    for row in records:
        coverage['cards'] += 1
        tactic, status = _mark(labels, row['race_id'])
        coverage[status] += 1
        truth = _result_key(row)
        if truth is None or tactic is None:
            continue
        field, riders = tactic_context(row)
        base[tactic] += 1
        fields[field][tactic] += 1
        winner_cases[field, riders[truth[0]]][tactic] += 1
        coverage['matched_labels_with_unique_trifecta'] += 1
    check(sum(base[i] > 0 for i in CLASSES) >= 2, 'TACTIC_CLASS_TRAINING_SUPPORT')
    frequency = _smooth(base, (1. / len(CLASSES),) * len(CLASSES), float(len(CLASSES)))
    field_laws = {key: _smooth(counts, frequency, FIELD_PRIOR) for key, counts in fields.items()}
    rider_laws = {key: _smooth(counts, field_laws[key[0]], RIDER_PRIOR) for key, counts in winner_cases.items()}
    return (frequency, field_laws, rider_laws), dict(
        counts=coverage, tactic_class_counts={CLASS_NAMES[i]: base[i] for i in CLASSES},
        classes_without_training_observations=[CLASS_NAMES[i] for i in CLASSES if not base[i]],
        field_buckets=len(fields), winner_buckets=len(winner_cases))


def _prediction(race, models):
    frequency, fields, winner_cases = models
    field, riders = tactic_context(race)
    current = fields.get(field, frequency)
    conditional = {car: winner_cases.get((field, role), current) for car, role in riders.items()}
    return current, conditional


def tactic_joint(base, conditionals, field, strength):
    """Match the mixture on tactics and keep frozen order conditional on winner."""
    check(0. <= strength <= 1., 'TACTIC_STRENGTH')
    first = {prefix[0]: mass for prefix, mass in marginal(base, count=1).items()}
    check(first.keys() == conditionals.keys(), 'TACTIC_WINNER_SUPPORT')
    implied = tuple(fsum(mass * conditionals[car][i] for car, mass in first.items()) for i in CLASSES)
    check(len(field) == len(CLASSES) and all(p > 0. for p in implied), 'TACTIC_CLASS_PROBABILITIES')
    if not strength:
        return base, implied, implied
    target = tuple((1. - strength) * implied[i] + strength * field[i] for i in CLASSES)
    factors = tuple(target[i] / implied[i] for i in CLASSES)
    revised_first = {car: mass * fsum(weight * p for weight, p in zip(factors, conditionals[car], strict=True))
                     for car, mass in first.items()}
    return reweight_joint(base, revised_first), target, implied


def _tactic_score(probabilities, actual):
    winner = max(CLASSES, key=lambda i: (probabilities[i], -i))
    return int(winner == actual), -log(probabilities[actual])


def _assess(records, period, labels, model, venues, at, tactic_models, strengths):
    racing, tactics, counts = {}, {}, Counter()
    admitted = []
    frequency = tactic_models[0]
    for day, rows, earlier in week_groups(records, *period):
        counts['cards'] += len(rows)
        legal = []
        for row in rows:
            mark, status = _mark(labels, row['race_id'])
            counts[status] += 1
            truth = _result_key(row)
            if truth is not None:
                legal.append((row, truth, mark))
        if not legal:
            continue
        cards, truths, marks = zip(*legal)
        history = FeatureBuilder()
        for _, prior in earlier:
            history.update_day(prior)
        features = _features(cards, history, model, venues, at)
        race_scores = {name: [] for name in strengths}
        tactic_scores = defaultdict(list)
        for race, truth, mark in zip(features, truths, marks, strict=True):
            admitted.append(race['race_id'])
            counts['scorable'] += 1
            baseline = _joint(model, race)
            field, conditional = _prediction(race, tactic_models)
            for name, alpha in strengths.items():
                joint, target, _ = tactic_joint(baseline, conditional, field, alpha)
                race_scores[name].append(_score(joint, truth))
                if mark is not None:
                    tactic_scores[name].append(_tactic_score(target, mark))
            if mark is not None:
                counts['scorable_with_tactic'] += 1
                tactic_scores['unconditional'].append(_tactic_score(frequency, mark))
        racing[day.isoformat()] = {name: _sums(scores) for name, scores in race_scores.items()}
        if tactic_scores:
            tactics[day.isoformat()] = {name: dict(n=len(scores), top1=sum(s[0] for s in scores),
                log_loss=fsum(s[1] for s in scores)) for name, scores in tactic_scores.items()}
    check(bool(racing) and bool(tactics), 'TACTIC_SCORING_EMPTY')
    return racing, tactics, counts, admitted


def _select(results):
    frozen = results[0.]['proper']
    allowed = [alpha for alpha in results if all(
        results[alpha]['proper'][metric] <= frozen[metric] for metric in ('tri_log_loss', 'ex_log_loss'))]
    return max(allowed, key=lambda alpha: (results[alpha]['hits']['tri1'], results[alpha]['hits']['ex1'], -alpha))


def _summarize_tactics(days):
    out = {}
    for name in next(iter(days.values())):
        count = sum(d[name]['n'] for d in days.values())
        hits = sum(d[name]['top1'] for d in days.values())
        out[name] = dict(n=count, top1_hits=hits, top1_rate=hits / count,
                         log_loss=fsum(d[name]['log_loss'] for d in days.values()) / count)
    return out


def contract():
    return dict(schema='DT_R1_ARCHIVED_FINISH_TACTIC_CONTRACT_V1', periods=PERIODS, prior_jst_days=7,
        identity_scope=IDENTITY_STATUS, pre_cutoff_time_verified=False, independent_validation=False,
        production_promoted=False, august_onward_used=False,
        label_scope='archived races.kimarite; not a verified first-place or intermediate-motion event',
        marks=dict(normalized=CLASS_NAMES, accepted=CLASS_CODES),
        field_context=['line state', 'line count capped at 4', 'field size capped at 7'],
        winner_context=['field context', 'archived pre-race style', 'published line lead/follow/single or missing state'],
        training_labels='normalizable race tactic and unique trifecta; label rows never become features',
        field_prior=FIELD_PRIOR, winner_prior=RIDER_PRIOR, strengths=STRENGTHS,
        selection_guard='June joint trifecta and marginal exacta log loss no worse than frozen',
        selection_order=['trifecta_top1', 'exacta_top1', 'smaller_strength'],
        tactic_control='unconditional pre-June four-label frequency with one pseudo-observation per class',
        unobserved_class='retain the prespecified pseudocount and report zero observed training support',
        coupled_forecast='condition on candidate winner, replace tactic mass by the fixed probability blend',
        exacta='exact prefix marginal of trifecta', later_places='retain same conditional on winner',
        original_frozen_training_overlaps_selection=True, original_frozen_temperature_overlaps_july=True,
        bootstrap=dict(unit='paired JST day', samples=BOOTSTRAP_N, seed=BOOTSTRAP_SEED))


def run(paths, private):
    since = time.monotonic()
    at = datetime.now(timezone.utc).isoformat()
    specification = contract()
    pins = dict(contract=specification, contract_sha256=digest(specification),
        study_sha256=digest_file(Path(__file__)),
        code_base=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        source=dict(commit=SOURCE_COMMIT, dataset_sha256=OLD_DATASET, files=PINNED_SOURCE_SHA256),
        model=dict(id='chatgpt-dt-r1', sha256=MODEL_SHA, file_sha256=MODEL_FILE_SHA,
                   historical_geometry_assumption_sha256=GEOMETRY), started_at=at)
    write_private_json(private / 'contract.json', pins)
    print('CONTRACT_SAVED', pins['contract_sha256'], flush=True)
    check(len(paths) == 2 and {p.name for p in paths} == PINNED_SOURCE_SHA256.keys(), 'ARCHIVE_PAIR')
    mark_source = next(path for path in paths if path.name == 'keirin.db')
    records, audit = load_archives(paths)
    check(len(records) == OLD_N and audit['dataset_sha256'] == OLD_DATASET, 'ARCHIVE_DATASET_PIN')
    model, venues = load_frozen(ROOT.parents[1])
    start, end = PERIODS['fit']
    trained, fit = _fit((row for row in records if start <= row['day'] <= end),
                        read_marks(mark_source, PERIODS['fit']))
    weights = digest([trained[0], sorted(trained[1].items()), sorted(trained[2].items())])
    print('FIT_COUNT', fit['counts']['matched_labels_with_unique_trifecta'], flush=True)
    june_races, _, june_counts, _ = _assess(records, PERIODS['select'],
        read_marks(mark_source, PERIODS['select']), model, venues, at, trained, {v: v for v in STRENGTHS})
    june = _summary(june_races)
    alpha = _select(june)
    selected = dict(strength=alpha, tactic_weights_sha256=weights)
    write_private_json(private / 'parameters.json', dict(contract_sha256=pins['contract_sha256'], **selected))
    print('SELECTION_FROZEN', alpha, flush=True)
    july_races, tactic_days, july_counts, admitted = _assess(records, PERIODS['july'],
        read_marks(mark_source, PERIODS['july']), model, venues, at, trained,
        dict(frozen=0., full_tactic=1., candidate=alpha))
    expected = [row['race_id'] for row in records if PERIODS['july'][0] <= row['day'] <= PERIODS['july'][1]
                and _result_key(row) is not None]
    validate_july(expected, admitted)
    report = dict(schema='DT_R1_ARCHIVED_FINISH_TACTIC_STUDY_V1', **pins,
        runtime_seconds=round(time.monotonic() - since, 3), production_promoted=False, fit=fit, selected=selected,
        june=dict(counts=june_counts, days=len(june_races), grid=[dict(strength=v, **june[v]) for v in STRENGTHS]),
        july=dict(counts=july_counts, days=len(july_races), common_scorable=EXPECTED_JULY,
            racing_metrics=_summary(july_races),
            racing_paired_candidate_minus_frozen=paired_difference(july_races, 'candidate', 'frozen'),
            tactic_metrics=_summarize_tactics(tactic_days),
            tactic_paired_full_minus_frequency=paired_difference(tactic_days, 'full_tactic', 'unconditional',
                                                                 metrics=('top1', 'log_loss'))))
    write_private_json(private / 'aggregate.json', report)
    print('AGGREGATE_SAVED', report['runtime_seconds'], flush=True)


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
