"""Fail-closed audit of historical KEIRIN predicted-line composition.

Never infer line membership from finish order, prefecture, running style or
third-party mark/rank columns. Separate sourced lineup data from public results.
This script does NOT fetch websites or certify a source's pre-cutoff timestamp.
"""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re
from datetime import datetime

LINE_SHA = re.compile(r'^[a-f0-9]{64}$')
KEY_RE = re.compile(r'^2026\d{4}_\d{2}_\d{2}$')


def load_races(folder: Path) -> dict[str, dict]:
    out = {}
    for month in range(1, 12):
        path = folder / f'race_results_2026{month:02d}.csv'
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = csv.DictReader(stream)
            for row in rows:
                key = row['race_key']
                if not KEY_RE.fullmatch(key) or key in out:
                    raise ValueError(f'DUPLICATE_OR_INVALID_RACE_KEY:{key}')
                if not row['race_source_url'] or not row['result_source_url']:
                    raise ValueError(f'SOURCE_URL_MISSING:{key}')
                out[key] = row
    return out


def load_line_snapshots(path: Path | None) -> tuple[dict[str,dict], list[str]]:
    if path is None:
        return {}, []
    out = {}
    issues = []
    with path.open(encoding='utf-8', newline='') as stream:
        for lineno, raw in enumerate(stream, 1):
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
                key = obj['race_key']
                if key in out:
                    issues.append(f'DUPLICATE_SNAPSHOT:{key}:{lineno}')
                    continue
                out[key] = obj
            except (ValueError, KeyError, TypeError):
                issues.append(f'INVALID_SNAPSHOT_JSON:{lineno}')
    return out, issues


def classify(lines: list[list[int]], order: str, starters: list[int]) -> str:
    if not isinstance(lines, list) or not lines or any(not isinstance(line,list) or not line for line in lines):
        raise ValueError('INVALID_LINES')
    flattened = [n for line in lines for n in line]
    if any(type(n) is not int or not 1 <= n <= 9 for n in flattened):
        raise ValueError('INVALID_CAR_NUMBER')
    if len(flattened) != len(set(flattened)) or set(flattened) != set(starters):
        raise ValueError('LINE_STARTERS_MISMATCH')
    found = {n:group for group,line in enumerate(lines) for n in line}
    winners = [int(n) for n in order.split('-')]
    if len(winners) != 3 or len(set(winners)) != 3 or any(n not in found for n in winners):
        raise ValueError('INVALID_WINNING_ORDER')
    n = len(set(found[w] for w in winners))
    return ('SAME_LINE_3' if n == 1 else
            'SAME_LINE_2_PLUS_OTHER' if n == 2 else
            'THREE_DIFFERENT_LINES')


def validate_snapshot(record: dict, race: dict, source_dir: Path | None) -> tuple[str | None, str | None]:
    """Only independent original and semantic proof can enter formal cohort."""
    if record.get('race_key') != race['race_key']:
        return None, 'RACE_KEY_MISMATCH'
    try:
        starters = [int(x) for x in race['actual_starters'].split('-')]
        lines = record['lines']
        payouts = race['winning_orders'].split('|')
        classes = [classify(lines, order.strip(), starters) for order in payouts]
        if not classes:
            return None, 'NO_PAYOUT'
    except (KeyError, ValueError, TypeError):
        return None, 'INVALID_LINES_OR_PAYOUT'
    if not record.get('source_url', '').startswith('https://') or not record.get('captured_at'):
        return None, 'NO_LINE_SOURCE_URL_OR_CAPTURE_TIME'
    try:
        datetime.fromisoformat(record['captured_at'])
        if datetime.fromisoformat(record['captured_at']).tzinfo is None:
            return None, 'NAIVE_CAPTURE_TIME'
    except (ValueError, TypeError):
        return None, 'INVALID_CAPTURE_TIME'
    digest = record.get('source_sha256', '')
    if not LINE_SHA.fullmatch(str(digest)):
        return None, 'NO_VALID_SOURCE_SHA'
    # Hash strings without their source bytes are not sufficient evidence.
    source_path = source_dir / digest if source_dir else None
    if not source_path or not source_path.is_file() or source_path.is_symlink():
        return None, 'SOURCE_BYTES_NOT_AVAILABLE'
    if source_path.stat().st_size > 3_000_000:
        return None, 'SOURCE_OVERSIZE'
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != digest:
        return None, 'SOURCE_HASH_MISMATCH'
    if record.get('independent_line_review') != 'PASS':
        return None, 'INDEPENDENT_LINE_REVIEW_MISSING'
    if record.get('lineup_status') != 'PUBLISHED_PREDICTED_LINE':
        return None, 'PUBLISHED_PREDICTED_LINE_UNCONFIRMED'
    # Must store the distinction from a future race's frozen pre-cutoff P0.
    if record.get('temporal_status') not in ('HISTORICAL_RETROSPECTIVE','PRE_CUTOFF_ORIGINAL'):
        return None, 'TEMPORAL_STATUS_UNKNOWN'
    return '|'.join(classes), None


def audit(races: dict[str,dict], snapshots: dict[str,dict], source_dir: Path | None = None, input_issues=()) -> dict:
    failures = Counter()
    classes = Counter()
    category = {}
    verified = 0
    not_applicable = 0
    for key, race in sorted(races.items()):
        k = f"{len(race['actual_starters'].split('-'))}車_{race['gender']}"
        c = category.setdefault(k, {'total':0, 'verified':0, 'missing':0, 'invalid':0, 'not_applicable':0})
        c['total'] += 1
        if race['gender'] == 'ガールズ':
            not_applicable += 1
            c['not_applicable'] += 1
            continue
        item = snapshots.get(key)
        if item is None:
            failures['NO_LINE_SOURCE_SNAPSHOT'] += 1
            c['missing'] += 1
            continue
        outcome, err = validate_snapshot(item, race, source_dir)
        if err:
            failures[err] += 1
            c['invalid'] += 1
        else:
            verified += 1
            c['verified'] += 1
            classes.update(outcome.split('|'))
    extra = sorted(set(snapshots).difference(races))
    if extra:
        failures['SNAPSHOT_RACE_NOT_IN_REFERENCE'] += len(extra)
    if input_issues:
        failures['INVALID_OR_DUPLICATE_INPUT_SNAPSHOT'] += len(input_issues)
    total = len(races)
    assert sum(v['total'] for v in category.values()) == total
    assert all(v['verified']+v['missing']+v['invalid']+v['not_applicable']==v['total'] for v in category.values())
    return {'schema':'KEIRIN_NATIONWIDE_LINE_SOURCE_GATE_V1',
            'period':'2026-01-01/2026-11-18',
            'total_settled_races':total,
            'line_applicable_male_races':total-not_applicable,
            'not_applicable_girls_races':not_applicable,
            'formal_verified_races':verified,
            'unverified_line_applicable_races':total-not_applicable-verified,
            'formal_nationwide_verdict':'PASS' if verified==total-not_applicable and not extra and not input_issues else 'HOLD',
            'source_status_by_category':dict(sorted(category.items())),
            'failure_reasons':dict(failures.most_common()),
            'verified_payout_order_classes':dict(classes),
            'unattached_snapshot_keys':extra[:20],
            'assumptions':['published predicted line, not video-observed race formation',
                           'no reconstruction from region/style/finishing numbers',
                           'ties produce multiple possible 3-car winning order classes',
                           'retrospective sources and pre-cutoff originals remain distinct']}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--race-dir', required=True, type=Path)
    ap.add_argument('--line-snapshots-jsonl', type=Path)
    ap.add_argument('--source-bytes-dir', type=Path)
    ap.add_argument('--output-json', required=True, type=Path)
    args = ap.parse_args()
    races = load_races(args.race_dir)
    snaps, issues = load_line_snapshots(args.line_snapshots_jsonl)
    report = audit(races, snaps, args.source_bytes_dir, issues)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f"{report['formal_nationwide_verdict']} {report['formal_verified_races']}/{report['line_applicable_male_races']} line-applicable verified; girls excluded {report['not_applicable_girls_races']}")


if __name__ == '__main__':
    main()