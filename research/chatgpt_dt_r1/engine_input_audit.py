"""Audit the frozen DT-R1 inputs on its fit/tune dates, with a paired history omission."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from itertools import groupby
import json
from pathlib import Path
import time

import numpy as np

from .data import PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from .features import FeatureBuilder, retired_timing_feature
from .frozen_followup import OLD_DATASET, augment_abilities, augment_agari, augment_features, blind_target, check
from .historical_replay import digest_file, rollup
from .pipeline import forecast_row, summarize_predictions, write_private_json
from scripts.keirin_dt_r1_future_shadow import MODEL_SHA, load_frozen

FIT_END = '2026-06-30'
TUNE_END = '2026-07-31'


class FeatureAudit:
    """Track emitted values independently of explicit source-availability markers."""

    def __init__(self, frozen):
        self.names = frozen.feature_names
        self.frozen = frozen
        n = len(self.names)
        index = {name: k for k, name in enumerate(self.names)}
        self.masks = {k: index[name + '_missing'] for k, name in enumerate(self.names)
                      if name + '_missing' in index}
        self.observations = 0
        self.races = 0
        self.nonzero = np.zeros(n, dtype=np.int64)
        self.varies = np.zeros(n, dtype=np.int64)
        self.sum = np.zeros(n)
        self.squares = np.zeros(n)
        self.within_logit_squares = np.zeros(n)
        self.hashes = [sha256() for _ in range(n)]
        self.marked_missing = Counter()

    def add(self, features):
        x = np.asarray(features, dtype='<f8').copy()
        check(x.shape[1] == len(self.names) and np.isfinite(x).all(), 'AUDIT_FEATURE_MATRIX')
        x[x == 0.] = 0.
        self.races += 1
        self.observations += len(x)
        self.nonzero += np.count_nonzero(x, axis=0)
        self.varies += np.ptp(x, axis=0) > 1e-12
        self.sum += x.sum(axis=0)
        self.squares += np.square(x).sum(axis=0)
        scaled = np.clip((x - self.frozen.mean) / self.frozen.scale, -12., 12.)
        self.within_logit_squares += np.square(scaled - scaled.mean(axis=0)).sum(axis=0)
        for hasher, column in zip(self.hashes, x.T, strict=True):
            hasher.update(column.tobytes())
        for k, marker in self.masks.items():
            self.marked_missing[k] += int(np.count_nonzero(x[:, marker]))

    def report(self):
        check(self.observations > 0, 'AUDIT_NO_ROWS')
        n = self.observations
        variance = np.maximum(0., self.squares / n - np.square(self.sum / n))
        scale = np.sqrt(self.within_logit_squares / n)
        weights = self.frozen.weights
        max_weight = np.max(np.abs(weights), axis=0)
        relative_effect = scale * np.sqrt(np.square(weights[:3, :]).mean(axis=0))
        duplicates = {}
        for name, h in zip(self.names, self.hashes, strict=True):
            duplicates.setdefault(h.hexdigest(), []).append(name)
        mask = self.frozen.fit_meta['feature_mask']
        repeated = {group[0]: group for group in duplicates.values() if len(group) > 1}
        columns = {
            name: dict(fit_mask=bool(mask[k]), near_zero_coefficient=bool(max_weight[k] < 1e-12),
                nonzero_values=int(self.nonzero[k]), races_varying=int(self.varies[k]),
                variance=float(variance[k]), within_race_top3_logit_rms=float(relative_effect[k]),
                emitted_values_sha256=self.hashes[k].hexdigest(), retired_timing=retired_timing_feature(name),
                explicit_missing_values=self.marked_missing[k] if k in self.masks else None)
            for k, name in enumerate(self.names)}
        return dict(races=self.races, rider_rows=n, columns=columns, duplicate_groups=repeated,
                    rows_missing_rule='explicit matching <feature>_missing marker; null when unavailable',
                    relative_effect_scope='frozen individual top3 logits before softmax; pair weights separate')


def block_intervals(daily):
    rng = np.random.default_rng(20261128)
    sample = rng.integers(0, len(daily), size=(2000, len(daily)))
    n = np.array([day['history']['evaluable'] for day in daily])
    totals = n[sample].sum(axis=1)
    check(totals.min() > 0, 'AUDIT_BOOTSTRAP_DENOMINATOR')
    out = {}
    for market, sizes in (('trifecta', (1, 2, 4, 9, 12)), ('exacta', (1, 2))):
        for size in sizes:
            k = str(size)
            delta = np.array([day['history'][market][k]['hits'] - day['no_history'][market][k]['hits']
                              for day in daily])
            lo, hi = np.percentile(100 * delta[sample].sum(axis=1) / totals, [2.5, 97.5])
            out[f'{market}_{k}'] = dict(hit_delta=int(delta.sum()), delta_pp=float(100 * delta.sum() / n.sum()),
                                        paired_day_bootstrap_95_pp=[float(lo), float(hi)])
    return out


def audit(paths):
    begin = time.monotonic()
    started = datetime.now(timezone.utc).isoformat()
    repo = Path(__file__).resolve().parents[2]
    model, venues = load_frozen(repo)
    check({p.name for p in paths} == PINNED_SOURCE_SHA256.keys(), 'AUDIT_ARCHIVE_PAIR')
    records, provenance = load_archives(paths)
    check(len(records) == 30713 and provenance['dataset_sha256'] == OLD_DATASET, 'AUDIT_ARCHIVE_PIN')
    check(model.fit_meta['training_last_day'] == FIT_END and
          model.fit_meta['temperature_calibration']['end_day'] == TUNE_END, 'AUDIT_MODEL_SPLITS')
    builder = FeatureBuilder()
    cold = FeatureBuilder()
    stats = {key: FeatureAudit(model) for key in ('fit', 'tune_history', 'tune_no_history')}
    daily = []
    analyzed_at = model.fit_meta['context']['analysis_at']

    def columns(base):
        context = augment_features(base, venue_store=venues, as_of=analyzed_at,
                                   allow_current_geometry_assumption=True)
        return augment_abilities(augment_agari(context))

    for day, group in groupby(records, key=lambda row: row['day']):
        if day > TUNE_END:
            break
        rows = list(group)
        blind = [blind_target(row) for row in rows]
        featured = columns([builder.transform(row) for row in blind])
        key = 'fit' if day <= FIT_END else 'tune_history'
        for row in featured:
            stats[key].add(row['features'])
        if key == 'tune_history':
            blank = columns([cold.transform(row) for row in blind])
            for row in blank:
                stats['tune_no_history'].add(row['features'])
            dated = dict(day=day)
            for arm, values in (('history', featured), ('no_history', blank)):
                dated[arm] = summarize_predictions([forecast_row(model, row) for row in values], rows)
            check(dated['history']['evaluable'] == dated['no_history']['evaluable'] ==
                  dated['history']['predicted_evaluable'] == dated['no_history']['predicted_evaluable'],
                  'AUDIT_PAIRED_DENOMINATOR')
            daily.append(dated)
        builder.update_day(rows)
        if day.endswith('-01'):
            print('AUDIT_OBSERVED', day, flush=True)
    check(stats['fit'].races == 20253 and stats['tune_history'].races == stats['tune_no_history'].races == 2416,
          'AUDIT_SPLIT_COUNTS')
    return dict(schema='DT_R1_ENGINE_INPUT_AUDIT_V1', scope='FIT_AND_TUNE_DIAGNOSTIC_RETROSPECTIVE',
        model_sha256=MODEL_SHA, source_commit=SOURCE_COMMIT, dataset_sha256=OLD_DATASET,
        audit_source_sha256=digest_file(Path(__file__)), started_at=started,
        runtime_seconds=time.monotonic() - begin,
        fits_through=FIT_END, tune_through=TUNE_END,
        feature_reports={key: value.report() for key, value in stats.items()},
        tune={arm: rollup([day[arm] for day in daily]) for arm in ('history', 'no_history')},
        comparison=block_intervals(daily), day_counts=len(daily),
        training_performed=False, original_final_period_used=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('archives', type=Path, nargs=2)
    args = parser.parse_args()
    check(not args.output.exists(), 'AUDIT_OUTPUT_EXISTS')
    report = audit(args.archives)
    write_private_json(args.output, report)
    print(json.dumps({'runtime_seconds': report['runtime_seconds'], 'comparison': report['comparison']}),
          flush=True)


if __name__ == '__main__':
    main()
