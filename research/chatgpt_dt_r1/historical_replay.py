"""Replay the released DT-R1 on the pinned January–October 2026 archives."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, timezone
import gzip
from hashlib import file_digest, sha256
from itertools import groupby
import json
from math import fsum
import os
from pathlib import Path
import re
import subprocess
import time

from .data import PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from .frozen_followup import (GEOMETRY, MODELS, OLD_DATASET, ROOT, FeatureBuilder,
                              augment_abilities, augment_agari, augment_features,
                              blind_target, check, VenueStore)
from .model import RankModel
from .pipeline import _result_key, forecast_row, summarize_predictions, write_private_json
from .public_shortlists import COVERAGE_TARGET, MAX_POINTS

MONTHS = tuple(f'2026-{month:02d}' for month in range(1, 11))
MODEL_FILE_SHA = 'dab8c7f014c41ac18e4fed1ae28ac9b36e994611d1fcf5992f8b06e31a4c618b'
REFERENCE_COMMIT = 'b7996aa5ede0d99cad3240beb55c31a53b3ff178'
REFERENCE_DIR = 'research/keirin/box_2026_01_01_to_11_18'


def digest_file(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def read_public_reference():
    def read(name):
        return subprocess.check_output(['git', 'show', f'{REFERENCE_COMMIT}:{REFERENCE_DIR}/{name}'])

    manifest = read('manifest.json')
    pins = {row['name']: row for row in json.loads(manifest)['files']}
    rows, files = {}, {}
    for month in MONTHS:
        name = f'race_results_{month.replace("-", "")}.csv'
        raw = read(name)
        pin = pins[name]
        check(len(raw) == pin['bytes'] and sha256(raw).hexdigest() == pin['sha256'],
              'PUBLIC_RESULT_FILE_PIN')
        month_rows = list(csv.DictReader(raw.decode().splitlines()))
        check(len(month_rows) == pin['rows'], 'PUBLIC_RESULT_FILE_COUNT')
        files[month] = {'sha256': pin['sha256'], 'rows': len(month_rows)}
        for item in month_rows:
            day = date.fromisoformat(item['date']).isoformat()
            venue, number = int(item['venue_code']), int(item['race_no'])
            rid = f'{day.replace("-", "")}{venue:02d}{number:02d}'
            cars = frozenset(map(int, re.findall('[0-9]+', item['actual_starters'])))
            orders = {tuple(map(int, re.findall('[0-9]+', value)))
                      for value in item['winning_orders'].split('|')}
            check(day[:7] == month and 1 <= venue <= 99 and 1 <= number <= 12 and rid not in rows and
                  3 <= len(cars) <= 9 and all(1 <= car <= 9 for car in cars) and
                  all(len(order) == len(set(order)) == 3 and set(order) <= cars for order in orders),
                  'PUBLIC_RESULT_ROW')
            rows[rid] = (cars, orders)
    return rows, {'commit': REFERENCE_COMMIT, 'manifest_sha256': sha256(manifest).hexdigest(), 'files': files}


def public_matches(archive, reference):
    matches, held = [], Counter()
    for row in archive:
        result = reference.get(row['race_id'])
        if result is None:
            held['no_public_result'] += 1
        elif result[0] != {rider['car'] for rider in row['riders']}:
            held['different_starters'] += 1
        elif len(result[1]) != 1:
            held['multiple_public_orders'] += 1
        elif (truth := _result_key(row)) is None:
            held['no_unique_archive_result'] += 1
        elif truth not in result[1]:
            held['different_order'] += 1
        else:
            matches.append(row)
    return matches, dict(held)


def replay(records, private, frozen, venue_store, at):
    builder, files = FeatureBuilder(), {}
    for month, month_rows in groupby(records, key=lambda row: row['day'][:7]):
        if month > MONTHS[-1]:
            break
        days = groupby(month_rows, key=lambda row: row['day'])
        if month < MONTHS[0]:
            for _, rows in days:
                builder.update_day(list(rows))
            continue
        target = private / (month + '.predictions.private.jsonl.gz')
        forecast_count = 0
        with target.open('xb') as raw:
            with gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=1, mtime=0) as out:
                for _, rows in days:
                    day = list(rows)
                    base = [builder.transform(blind_target(row)) for row in day]
                    context = augment_features(base, venue_store=venue_store, as_of=at,
                                               allow_current_geometry_assumption=True)
                    for row in augment_abilities(augment_agari(context)):
                        forecast = forecast_row(frozen, row)
                        out.write(json.dumps(forecast, separators=(',', ':'), allow_nan=False).encode() + b'\n')
                        forecast_count += 1
                    # This day's outcomes become history after all its inputs are projected.
                    builder.update_day(day)
            raw.flush()
            os.fsync(raw.fileno())
        files[month] = {'sha256': digest_file(target), 'count': forecast_count}
        print(f'FROZEN {month} {forecast_count}', flush=True)
    check(tuple(files) == MONTHS, 'MISSING_ARCHIVE_MONTH')
    return files


def rollup(groups):
    shared = ('registered', 'evaluable', 'predicted_evaluable')
    report = {key: sum(group[key] for group in groups) for key in shared}
    for key in ('not_evaluable', 'holds'):
        counts = Counter()
        for group in groups:
            counts.update(group[key])
        report[key] = dict(counts)
    n = report['evaluable']
    predicted = report['predicted_evaluable']
    report['prediction_coverage'] = predicted / n if n else None
    for market in ('trifecta', 'exacta'):
        report[market] = {}
        for k in groups[0][market]:
            hits = sum(group[market][k]['hits'] for group in groups)
            report[market][k] = dict(hits=hits, all_target_rate=hits / n if n else None,
                                     predicted_rate=hits / predicted if predicted else None)
    proper = [group['proper_scores'] for group in groups if group['proper_scores']['n']]
    report['proper_scores'] = {'n': predicted}
    for key in ('joint_top3_log_loss', 'exacta_log_loss', 'multiclass_brier'):
        report['proper_scores'][key] = (fsum(row[key] * row['n'] for row in proper) / predicted
                                         if predicted else None)
    return report


def probability_only(forecasts, matched):
    """Measure the existing mass threshold when no as-of odds are available."""
    by_id = {f['race_id']: f for f in forecasts if f['status'] == 'READY'}
    hits, points = 0, Counter()
    for row in matched:
        if (forecast := by_id.get(row['race_id'])) is None:
            continue
        ranking = forecast['trifectas'][:MAX_POINTS]
        orders = []
        for item in ranking:
            orders.append(tuple(item['cars']))
            if fsum(ticket['probability'] for ticket in ranking[:len(orders)]) >= COVERAGE_TARGET:
                break
        points[len(orders)] += 1
        hits += int(_result_key(row) in orders)
    return {'market': 'trifecta', 'coverage_target': COVERAGE_TARGET, 'max_points': MAX_POINTS,
            'pre_cutoff_odds_used': False, 'hits': hits, 'predicted_n': sum(points.values()),
            'points_distribution': dict(points)}


def score(records, private, files, reference):
    rows_by_month = {month: list(group) for month, group in
                     groupby(records, key=lambda row: row['day'][:7]) if month in MONTHS}
    published_by_month = {month: {rid for rid in reference if rid.startswith(month.replace('-', ''))}
                          for month in MONTHS}
    reports = {}
    for month, rows in rows_by_month.items():
        path = private / (month + '.predictions.private.jsonl.gz')
        check(digest_file(path) == files[month]['sha256'], 'FORECAST_FREEZE_PIN')
        with gzip.open(path, 'rt') as stream:
            forecasts = [json.loads(line) for line in stream]
        check([row['race_id'] for row in rows] == [f['race_id'] for f in forecasts] and
              len(rows) == files[month]['count'], 'FORECAST_PARTITION')
        matched, held = public_matches(rows, reference)
        active = published_by_month[month]
        ids = {row['race_id'] for row in rows}
        coverage = dict(archived_cards=len(rows), archived_days=len({row['day'] for row in rows}),
                        public_result_rows=len(active), public_result_days=len({rid[:8] for rid in active}),
                        public_without_archived_card=len(active - ids), crosschecked=len(matched), **held)
        check(len(rows) == len(matched) + sum(held.values()), 'COVERAGE_PARTITION')
        reports[month] = dict(coverage=coverage, archive_only=summarize_predictions(forecasts, rows),
                              crosschecked=summarize_predictions(forecasts, matched),
                              probability_only=probability_only(forecasts, matched))
        print(f'SCORED {month} {len(matched)}', flush=True)
    return reports


def evaluate(paths, private):
    clock = datetime.now(timezone.utc)
    begin = time.monotonic()
    model_path, model_sha = MODELS['five_abilities']
    frozen_bytes = (ROOT / model_path).read_bytes()
    check(sha256(frozen_bytes).hexdigest() == MODEL_FILE_SHA, 'FROZEN_MODEL_FILE_PIN')
    frozen = RankModel.from_dict(json.loads(frozen_bytes))
    check(frozen.to_dict()['model_sha256'] == model_sha, 'FROZEN_MODEL_PIN')
    for name, expected in frozen.fit_meta['source_code_sha256'].items():
        check(digest_file(ROOT / name) == expected, 'FROZEN_INFERENCE_CODE_PIN')
    geometry = (ROOT / 'fixtures' / 'venue_geometry.json').read_bytes()
    check(sha256(geometry).hexdigest() == frozen.fit_meta['context']['venue_file_sha256'] == GEOMETRY,
          'VENUE_PIN')
    check({path.name for path in paths} == PINNED_SOURCE_SHA256.keys() and len(paths) == 2, 'ARCHIVE_PAIR')
    records, audit = load_archives(paths)
    check(audit['dataset_sha256'] == OLD_DATASET and len(records) == 30713, 'ARCHIVE_DATASET_PIN')
    print(f'SOURCE_VERIFIED {len(records)} {audit["dataset_sha256"]}', flush=True)
    files = replay(records, private, frozen, VenueStore.from_records(json.loads(geometry)), clock.isoformat())
    freeze_at = datetime.now(timezone.utc).isoformat()
    write_private_json(private / 'forecast-freeze.json', dict(months=files, frozen_at=freeze_at))
    ref, reference_receipt = read_public_reference()
    reports = score(records, private, files, ref)
    totals = {name: rollup([row[name] for row in reports.values()])
              for name in ('archive_only', 'crosschecked')}
    coverage, points = Counter(), Counter()
    for row in reports.values():
        coverage.update(row['coverage'])
        points.update(row['probability_only']['points_distribution'])
    return dict(
        schema='DT_R1_HISTORICAL_REPLAY_V1', scope='RETROSPECTIVE_REUSED_ARCHIVE', start='2026-01-01',
        end='2026-10-31', code_base=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        replay_source_sha256=digest_file(Path(__file__)), started_at=clock.isoformat(),
        runtime_seconds=round(time.monotonic() - begin, 3), prediction_files_frozen_at=freeze_at,
        model=dict(id='chatgpt-dt-r1', model_sha256=model_sha, file_sha256=MODEL_FILE_SHA,
                   feature_count=len(frozen.feature_names), weights_fit_through=frozen.fit_meta['training_last_day'],
                   candidate_selection_and_temperature_through=frozen.fit_meta['temperature_calibration']['end_day'],
                   confidence_calibration_month='2026-08', confidence_audit_month='2026-09',
                   october_scope='SUBSET_OF_PREVIOUS_FINAL_TEST'),
        source=dict(archive_commit=SOURCE_COMMIT, archive_files=PINNED_SOURCE_SHA256,
                    archive_dataset_sha256=OLD_DATASET, venue_sha256=GEOMETRY,
                    public_results=reference_receipt),
        forecast_sha256_by_month={month: meta['sha256'] for month, meta in files.items()},
        overall=dict(coverage=dict(coverage), **totals),
        probability_only=dict(coverage_target=COVERAGE_TARGET, max_points=MAX_POINTS, pre_cutoff_odds_used=False,
                              hits=sum(row['probability_only']['hits'] for row in reports.values()),
                              predicted_n=sum(points.values()), points_distribution=dict(points)),
        by_month=reports, pre_cutoff_time_verified=False, production_promoted=False,
        private_forecasts_published=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('private', type=Path, help='New empty owner-only directory outside Git.')
    parser.add_argument('archives', type=Path, nargs=2)
    args = parser.parse_args()
    os.umask(0o077)
    private = args.private.resolve()
    check(private.is_dir() and not any(private.iterdir()) and not private.stat().st_mode & 0o077 and
          not any((parent / '.git').exists() for parent in (private, *private.parents)), 'PRIVATE_RUNNER_PATH')
    receipt = evaluate(args.archives, private)
    write_private_json(private / 'aggregate.json', receipt)
    print('AGGREGATE_SAVED', round(receipt['runtime_seconds'], 1), flush=True)


if __name__ == '__main__':
    main()
