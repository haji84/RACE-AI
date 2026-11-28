"""Compare 7 and 30 prior JST days with the frozen DT-R1 on July archives."""
import argparse
from collections import Counter, deque
from datetime import date, datetime, timedelta, timezone
from itertools import groupby
from pathlib import Path
import os
import subprocess
import time

from scripts.keirin_dt_r1_future_shadow import MODEL_FILE_SHA, MODEL_SHA, load_frozen

from .boosted_first_study import EXPECTED_JULY, _features, _joint, validate_july
from .data import IDENTITY_STATUS, PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from .features import FeatureBuilder
from .frozen_followup import GEOMETRY, OLD_DATASET, OLD_N, ROOT, check
from .historical_replay import digest_file
from .history_mix_study import (BOOTSTRAP_N, BOOTSTRAP_SEED, EVAL_END, EVAL_START, METRICS,
                                _score, _summary, _sums, paired_difference)
from .pipeline import _result_key, write_private_json
from .policy import digest


WINDOWS = {'seven': 7, 'thirty': 30}


def history_projection(row):
    """Restrict archived priors to fields available from official final-order replay."""
    riders, outcomes = row['riders'], row['result_rows']
    size = len(riders)
    if (not row['field_supported'] or not 5 <= size <= 9 or len(outcomes) != size
            or {r['car'] for r in riders} != {r['car'] for r in outcomes}):
        return None
    results, places = [], Counter()
    for outcome in outcomes:
        rank, incident = outcome['rank'], bool(outcome['incident'])
        if outcome['cancelled'] or outcome['absence']:
            return None
        if type(rank) is int and 1 <= rank <= size:
            places[rank] += 1
        elif rank is not None or not incident:
            return None
        results.append(dict(car=outcome['car'], rank=rank, incident=incident))
    if not places:
        return None
    expected = 1
    for rank, count in sorted(places.items()):
        if rank != expected:
            return None
        expected += count
    race_class = 'L1' if row['race_class'] == 'L1' else 'UNKNOWN'
    return dict(day=row['day'], race_id=row['race_id'], riders=riders,
                venue_code=row['venue_code'], race_class=race_class, result_rows=results)


def prior_builder(earlier, day, width):
    builder = FeatureBuilder()
    for stamp, rows in earlier:
        if day - timedelta(days=width) <= stamp < day:
            builder.update_day(rows)
    return builder


def _coverage(featured, counts):
    for row in featured:
        history = row['history_evidence']['rider_evidence'].values()
        numeric = [item['numeric_finishes'] for item in history]
        counts['races_with_numeric_history'] += int(any(numeric))
        counts['rider_rows'] += len(numeric)
        counts['rider_rows_with_numeric_history'] += sum(number > 0 for number in numeric)
        counts['numeric_finish_exposures'] += sum(numeric)


def specification():
    return dict(schema='DT_R1_ARCHIVE_HISTORY_WINDOW_CONTRACT_V1', window_days=WINDOWS,
        window='inclusive old edge; strictly earlier JST dates',
        evaluation_days=[EVAL_START.isoformat(), EVAL_END.isoformat()],
        expected_common_scorable=EXPECTED_JULY, historical_projection=dict(
            normal_rank_layout=True, exact_roster_with_explicit_numeric_or_incident_status=True,
            class_values=['L1', 'UNKNOWN'], omitted=['agari', 'sb_mark', 'full_final_lap_time']),
        common_target='unchanged archived card after blinding results and archived weather',
        identity_scope=IDENTITY_STATUS, historical_availability_authenticated=False,
        official_registration_verified=False, projected_full_archive_coverage_is_upper_scope=True,
        fitting=False, parameter_selection=False, independent_validation=False,
        production_promoted=False, metrics=METRICS,
        paired_bootstrap=dict(unit='JST day', samples=BOOTSTRAP_N, seed=BOOTSTRAP_SEED))


def evaluate(paths, private):
    start = time.monotonic()
    at = datetime.now(timezone.utc).isoformat()
    contract = specification()
    source = dict(commit=SOURCE_COMMIT, files=PINNED_SOURCE_SHA256, dataset_sha256=OLD_DATASET)
    model = dict(id='chatgpt-dt-r1', sha256=MODEL_SHA, file_sha256=MODEL_FILE_SHA,
                 common_venue_file_sha256=GEOMETRY, current_geometry_assumption=True,
                 existing_frozen_selection_overlaps_july=True)
    run = dict(contract=contract, contract_sha256=digest(contract),
               study_sha256=digest_file(Path(__file__)), started_at=at, source=source, model=model,
               code_base=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())
    write_private_json(private / 'contract.json', run)
    print('CONTRACT_SAVED', run['contract_sha256'], run['study_sha256'], flush=True)

    frozen, venues = load_frozen(ROOT.parents[1])
    check(len(paths) == 2 and {p.name for p in paths} == PINNED_SOURCE_SHA256.keys(), 'ARCHIVE_PAIR')
    data, audit = load_archives(paths)
    check(len(data) == OLD_N and audit['dataset_sha256'] == OLD_DATASET, 'ARCHIVE_DATASET_PIN')
    expected = [row['race_id'] for row in data
                if EVAL_START.isoformat() <= row['day'] <= EVAL_END.isoformat() and _result_key(row) is not None]
    recent = deque()
    coverage = {name: Counter() for name in WINDOWS}
    scores, admitted = {}, []
    cards = 0
    widest = timedelta(days=max(WINDOWS.values()))
    for stamp, group in groupby(data, key=lambda row: row['day']):
        day = date.fromisoformat(stamp)
        if day > EVAL_END:
            break
        if day < EVAL_START - widest:
            continue
        while recent and recent[0][0] < day - widest:
            recent.popleft()
        rows = list(group)
        if day >= EVAL_START:
            cards += len(rows)
            eligible = [(row, truth) for row in rows if (truth := _result_key(row)) is not None]
            if eligible:
                targets, truths = zip(*eligible, strict=True)
                admitted.extend(row['race_id'] for row in targets)
                scores[stamp] = {}
                for name, days in WINDOWS.items():
                    featured = _features(targets, prior_builder(recent, day, days), frozen, venues, at)
                    _coverage(featured, coverage[name])
                    scores[stamp][name] = _sums([_score(_joint(frozen, row), truth)
                                                 for row, truth in zip(featured, truths, strict=True)])
        projected = [history for row in rows if (history := history_projection(row)) is not None]
        recent.append((day, projected))
    validate_july(expected, admitted)
    return dict(schema='DT_R1_ARCHIVE_HISTORY_WINDOW_STUDY_V1', **run,
        runtime_seconds=round(time.monotonic() - start, 3), production_promoted=False,
        model_feature_count=len(frozen.feature_names), july=dict(days=len(scores), cards=cards,
            excluded_without_unique_trifecta=cards - len(admitted), common_scorable=len(admitted),
            common_cohort_sha256=digest(sorted(admitted)), coverage=coverage, metrics=_summary(scores),
            thirty_minus_seven=paired_difference(scores, 'thirty', 'seven')))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('private', type=Path, help='An empty, owner-only directory outside the repository.')
    cli.add_argument('archives', nargs=2, type=Path)
    args = cli.parse_args()
    os.umask(0o077)
    private = args.private.resolve()
    check(private.is_dir() and not any(private.iterdir()) and not private.stat().st_mode & 0o077
          and not any((parent / '.git').exists() for parent in (private, *private.parents)), 'PRIVATE_RUNNER_PATH')
    receipt = evaluate(args.archives, private)
    write_private_json(private / 'aggregate.json', receipt)
    print('AGGREGATE_SAVED', receipt['runtime_seconds'], flush=True)


if __name__ == '__main__':
    main()
