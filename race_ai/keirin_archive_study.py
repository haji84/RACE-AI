"""Bounded, read-only admission of archived KEIRIN SQLite study records.

These are retrospective records. A fetched clock is retained verbatim and is
never a claim that a source or a forecast existed before the race cutoff.
The returned examples contain private-use source data; only the aggregate
report is suitable for a public research receipt.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path
import json
import re
import sqlite3
import stat
import time
from unicodedata import normalize

from .keirin_public_two_source_normalizer import _mark


SCOPE = 'RETROSPECTIVE_ARCHIVE_NO_PRE_CUTOFF_ATTESTATION'
MAX_DATABASES = 8
MAX_DATABASE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_ROWS = 1_200_000
MAX_RACES = 100_000
TABLE_FIELDS = {
    'races': ('race_date', 'venue_code', 'rno', 'is_girls', 'fetched_at'),
    'entries': ('race_date', 'venue_code', 'rno', 'kumiban', 'racer_name', 'kyu',
                'racer_class', 'kyaku_shitsu', 'keisoku_tokuten',
                'recent_win_rate', 'recent_2rentai_rate', 'recent_3rentai_rate',
                'forecast_mark'),
    'line_predictions': ('race_date', 'venue_code', 'rno', 'kumiban', 'line_no',
                         'position_in_line', 'line_size', 'role'),
    'results': ('race_date', 'venue_code', 'rno', 'kumiban', 'rank',
                'is_incident', 'racer_name'),
    'payouts': ('race_date', 'venue_code', 'rno', 'bet_type', 'combination', 'payout'),
}
METRICS = (('keisoku_tokuten', 'competition_points', 150),
           ('recent_win_rate', 'win_rate', 100),
           ('recent_2rentai_rate', 'top2_rate', 100),
           ('recent_3rentai_rate', 'top3_rate', 100))
STYLES = {'逃': 'NIGE', '両': 'ALLROUND', '追': 'MARK'}
CLASSES = frozenset(('SS', 'S1', 'S2', 'A1', 'A2', 'A3', 'L1'))


class _Held(ValueError):
    """Only fixed, non-sensitive reason codes leave admission helpers."""


def _need(condition, reason):
    if not condition:
        raise _Held(reason)


def _day(value):
    if type(value) is not str or re.fullmatch(r'[0-9]{8}', value) is None:
        raise ValueError('Invalid calendar date.')
    return datetime.strptime(value, '%Y%m%d').strftime('%Y%m%d')


def _race_id(row):
    try:
        day = _day(row['race_date'])
    except (ValueError, TypeError):
        raise _Held('INVALID_RACE_IDENTITY') from None
    venue, number = row['venue_code'], row['rno']
    _need(type(venue) is str and re.fullmatch(r'[0-9]{1,2}', venue)
          and 1 <= int(venue) <= 99 and type(number) is int and 1 <= number <= 12,
          'INVALID_RACE_IDENTITY')
    return day + venue.zfill(2) + f'{number:02d}'


def _key(row):
    return tuple(row[field] for field in ('race_date', 'venue_code', 'rno'))


def _fingerprint(path):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or not 16 <= info.st_size <= MAX_DATABASE_BYTES:
            raise ValueError('ARCHIVE_DATABASE_FILE_INVALID')
        for suffix in ('-wal', '-journal'):
            sidecar = Path(str(path) + suffix)
            if sidecar.exists() and sidecar.stat().st_size:
                raise ValueError('ARCHIVE_UNCHECKPOINTED_DATABASE')
        digest = sha256()
        with path.open('rb') as stream:
            if stream.read(16) != b'SQLite format 3\0':
                raise ValueError('ARCHIVE_SQLITE_HEADER_INVALID')
            stream.seek(0)
            while block := stream.read(1024 * 1024):
                digest.update(block)
        return digest.hexdigest(), info.st_size
    except OSError:
        raise ValueError('ARCHIVE_DATABASE_UNAVAILABLE') from None


def _read_tables(path, start, end):
    """Read a stable standalone snapshot without creating SQLite sidecars."""
    deadline = time.monotonic() + 30
    ticks = 0

    def bounded_query():
        nonlocal ticks
        ticks += 1
        return int(ticks > 25_000 or time.monotonic() > deadline)

    try:
        connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1',
                                     uri=True, timeout=3)
        try:
            connection.row_factory = sqlite3.Row
            connection.set_progress_handler(bounded_query, 10_000)
            connection.execute('PRAGMA trusted_schema=OFF')
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            tables = {row['name']: row['sql'] for row in connection.execute(
                "SELECT name,sql FROM sqlite_schema WHERE type='table'")}
            for table, fields in TABLE_FIELDS.items():
                if table not in tables or 'virtual table' in (tables[table] or '').lower():
                    raise ValueError('ARCHIVE_REQUIRED_TABLE_MISSING')
                columns = {row['name'] for row in connection.execute(f'PRAGMA table_info({table})')}
                if not set(fields) <= columns:
                    raise ValueError('ARCHIVE_REQUIRED_COLUMN_MISSING')
                count = connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                if count > (MAX_RACES if table == 'races' else MAX_ROWS):
                    raise ValueError('ARCHIVE_ROW_LIMIT_EXCEEDED')
            if [tuple(row) for row in connection.execute('PRAGMA quick_check')] != [('ok',)]:
                raise ValueError('ARCHIVE_SQLITE_INTEGRITY_FAILED')
            result = {}
            for table, fields in TABLE_FIELDS.items():
                sql = f'SELECT {",".join(fields)} FROM {table}'
                parameters = ()
                if table != 'races':
                    sql += ' WHERE race_date >= ? AND race_date <= ?'
                    parameters = (start, end)
                result[table] = [dict(row) for row in connection.execute(sql, parameters)]
            return result
        finally:
            connection.close()
    except sqlite3.Error:
        raise ValueError('ARCHIVE_SQLITE_READ_REJECTED') from None


def _identity(value):
    _need(type(value) is str and 0 < len(value) <= 200, 'RESULT_STARTER_IDENTITY_MISMATCH')
    result = re.sub(r'\s+', '', normalize('NFKC', value))
    _need(bool(result), 'RESULT_STARTER_IDENTITY_MISMATCH')
    return result


def _riders(entries):
    cars = [row['kumiban'] for row in entries]
    _need(5 <= len(cars) <= 9 and all(type(car) is int and 1 <= car <= 9 for car in cars)
          and len(set(cars)) == len(cars), 'INVALID_STARTER_SET')
    riders = []
    for entry in sorted(entries, key=lambda row: row['kumiban']):
        term = entry['kyu']
        _need(term is None or type(term) is str and len(term) <= 50, 'INVALID_RIDER_TERM')
        _need('欠車' not in (term or ''), 'ABSENT_ENTRY')
        _need(entry['racer_class'] in CLASSES, 'INVALID_RIDER_CLASS')
        _need(entry['kyaku_shitsu'] in STYLES, 'INVALID_RIDER_STYLE')
        rider = {'car': entry['kumiban']}
        for source, target, maximum in METRICS:
            value = entry[source]
            _need(value is not None, 'MISSING_RIDER_METRIC')
            _need(type(value) in (int, float) and isfinite(value) and 0 <= value <= maximum,
                  'INVALID_RIDER_METRIC')
            rider[target] = value
        _need(rider['win_rate'] <= rider['top2_rate'] <= rider['top3_rate'],
              'INCONSISTENT_FINISH_RATES')
        mark = entry['forecast_mark']
        _need(type(mark) is str and len(mark) <= 30, 'INVALID_SOURCE_MARK')
        try:
            rider['mark_rank'] = _mark(normalize('NFKC', mark), len(cars))
        except ValueError:
            raise _Held('INVALID_SOURCE_MARK') from None
        rider.update(style=STYLES[entry['kyaku_shitsu']], **{'class': entry['racer_class']})
        riders.append(rider)
    return riders


def _lines(rows, cars, is_girls):
    if not rows:
        _need(is_girls == 1, 'MISSING_PUBLISHED_LINES')
        return [[car] for car in sorted(cars)], True
    line_cars = [row['kumiban'] for row in rows]
    _need(len(line_cars) == len(cars) and set(line_cars) == set(cars),
          'LINE_STARTER_SET_MISMATCH')
    groups = defaultdict(list)
    for row in rows:
        group, position = row['line_no'], row['position_in_line']
        _need(type(group) is int and 1 <= group <= 9 and type(position) is int
              and 1 <= position <= 9, 'INVALID_LINE_POSITION')
        role = row['role']
        _need(role is None or type(role) is str and len(role) <= 50, 'INVALID_LINE_POSITION')
        _need('競' not in (role or ''), 'CONTESTED_LINE_POSITION')
        groups[group].append(row)
    result = []
    for _, line in sorted(groups.items()):
        positions = [row['position_in_line'] for row in line]
        _need(len(set(positions)) == len(positions), 'CONTESTED_LINE_POSITION')
        _need(set(positions) == set(range(1, len(line) + 1)), 'LINE_POSITION_GAP')
        _need(all(type(row['line_size']) is int and row['line_size'] == len(line) for row in line),
              'LINE_SIZE_MISMATCH')
        result.append([row['kumiban'] for row in sorted(line, key=lambda row: row['position_in_line'])])
    return result, False


def _finish(results, entries):
    cars = {row['kumiban'] for row in entries}
    _need(len(results) == len(cars) and {row['kumiban'] for row in results} == cars,
          'INCOMPLETE_OR_SPECIAL_RESULT')
    ordered = {}
    identities = {row['kumiban']: _identity(row['racer_name']) for row in entries}
    for row in results:
        rank = row['rank']
        _need(row['is_incident'] == 0 and type(row['is_incident']) is int
              and type(rank) in (int, str) and re.fullmatch(r'[1-9]', str(rank)),
              'INCOMPLETE_OR_SPECIAL_RESULT')
        rank = int(rank)
        _need(rank not in ordered, 'INCOMPLETE_OR_SPECIAL_RESULT')
        _need(_identity(row['racer_name']) == identities[row['kumiban']],
              'RESULT_STARTER_IDENTITY_MISMATCH')
        ordered[rank] = row['kumiban']
    _need(set(ordered) == set(range(1, len(cars) + 1)), 'INCOMPLETE_OR_SPECIAL_RESULT')
    return [ordered[rank] for rank in range(1, len(cars) + 1)]


def _outcomes(payouts, finish):
    result = {}
    for market, length, kind in (('2車単', 2, '2t'), ('3連単', 3, '3t')):
        rows = [row for row in payouts if row['bet_type'] == market]
        _need(len(rows) == 1, 'NONUNIQUE_OR_INVALID_PAYOUT')
        row = rows[0]
        raw = row['combination']
        _need(type(raw) is str and len(raw) <= 20 and type(row['payout']) is int
              and row['payout'] > 0, 'NONUNIQUE_OR_INVALID_PAYOUT')
        raw = normalize('NFKC', raw).strip()
        _need(re.fullmatch(r'[1-9](?:-[1-9]){' + str(length - 1) + '}', raw),
              'NONUNIQUE_OR_INVALID_PAYOUT')
        order = [int(car) for car in raw.split('-')]
        _need(len(set(order)) == length, 'NONUNIQUE_OR_INVALID_PAYOUT')
        _need(order == finish[:length], 'PAYOUT_FINISH_MISMATCH')
        result[kind] = [order]
    return result


def _example(race, rows, digest, rid):
    _need(type(race['is_girls']) is int and race['is_girls'] in (0, 1),
          'INVALID_COMPETITION_FLAG')
    fetched = race['fetched_at']
    _need(type(fetched) is str and 0 < len(fetched) <= 64, 'MISSING_ARCHIVE_FETCH_CLOCK')
    try:
        datetime.fromisoformat(fetched.replace('Z', '+00:00'))
    except ValueError:
        raise _Held('INVALID_ARCHIVE_FETCH_CLOCK') from None
    riders = _riders(rows['entries'])
    lines, singleton = _lines(rows['line_predictions'], [rider['car'] for rider in riders],
                              race['is_girls'])
    finish = _finish(rows['results'], rows['entries'])
    outcomes = _outcomes(rows['payouts'], finish)
    return {
        'cohort': 'archived_replay',
        'input': {'race_id': rid, 'riders': riders, 'line_groups': lines},
        'outcomes': outcomes, 'finish_order': finish,
        'source': {'database_sha256': digest, 'fetched_at': fetched, 'scope': SCOPE},
    }, singleton


def load_databases(paths, *, start_day='20251001', end_day='20261122', excluded_race_ids=()):
    """Return chronological strict study examples and an aggregate admission report.

    Duplicate revisions are admitted only when the full input and labels agree.
    Any invalid or conflicting revision holds that race across all supplied DBs.
    This function never fetches a provider, trains a model, or publishes records.
    """
    try:
        start, end = _day(start_day), _day(end_day)
        if start > end:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('ARCHIVE_DATE_WINDOW_INVALID') from None
    if isinstance(paths, (str, bytes, Path)):
        raise ValueError('ARCHIVE_DATABASE_PATH_LIST_REQUIRED')
    paths = list(paths)
    if not 1 <= len(paths) <= MAX_DATABASES:
        raise ValueError('ARCHIVE_DATABASE_COUNT_INVALID')
    excluded = set(excluded_race_ids)
    if not all(type(rid) is str and re.fullmatch(r'20[0-9]{10}', rid) for rid in excluded):
        raise ValueError('ARCHIVE_EXCLUSION_ID_INVALID')
    report = {
        'schema': 'KEIRIN_ARCHIVE_STUDY_ADMISSION_V1', 'scope': SCOPE,
        'data_use': 'PRIVATE_LOCAL_RESEARCH_NO_REDISTRIBUTION_GRANT',
        'source_attribution': 'Caller-supplied archive bytes; retain upstream attribution and usage terms.',
        'start_day': start, 'end_day': end, 'sources': [], 'races_scanned': 0,
        'in_window_count': 0, 'outside_window_count': 0, 'excluded_count': 0,
        'examples_loaded': 0, 'held_by_reason': {}, 'duplicate_same_count': 0,
        'duplicate_conflict_count': 0, 'girls_singleton_count': 0,
        'girls_missing_line_policy': 'Only actual is_girls=1 with no published line rows uses singleton cars.',
    }
    revisions = defaultdict(list)
    holds = Counter()
    total_bytes = 0
    for supplied in paths:
        path = Path(supplied)
        digest, size = _fingerprint(path)
        total_bytes += size
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError('ARCHIVE_TOTAL_SIZE_LIMIT_EXCEEDED')
        tables = _read_tables(path, start, end)
        if _fingerprint(path) != (digest, size):
            raise ValueError('ARCHIVE_SOURCE_CHANGED_DURING_READ')
        report['sources'].append({'database_sha256': digest, 'bytes': size, 'scope': SCOPE,
                                  'races_scanned': len(tables['races'])})
        grouped = {}
        for table in TABLE_FIELDS:
            if table == 'races':
                continue
            grouped[table] = defaultdict(list)
            for row in tables[table]:
                grouped[table][_key(row)].append(row)
        for race in tables['races']:
            report['races_scanned'] += 1
            try:
                rid = _race_id(race)
            except _Held as exc:
                holds[str(exc)] += 1
                continue
            if not start <= rid[:8] <= end:
                report['outside_window_count'] += 1
                continue
            report['in_window_count'] += 1
            if rid in excluded:
                report['excluded_count'] += 1
                continue
            rows = {table: by_key[_key(race)] for table, by_key in grouped.items()}
            try:
                example, singleton = _example(race, rows, digest, rid)
                revisions[rid].append((example, singleton, None))
            except _Held as exc:
                revisions[rid].append((None, False, str(exc)))
    examples = []
    for rid, versions in sorted(revisions.items()):
        if len(versions) == 1 and versions[0][2] is not None:
            holds[versions[0][2]] += 1
            continue
        fingerprints = {
            json.dumps({key: example[key] for key in ('input', 'outcomes', 'finish_order')},
                       ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
            for example, _, error in versions if error is None
        }
        if any(error is not None for _, _, error in versions) or len(fingerprints) != 1:
            holds['DUPLICATE_RACE_CONFLICT'] += 1
            report['duplicate_conflict_count'] += 1
            continue
        example, singleton, _ = versions[0]
        examples.append(example)
        report['duplicate_same_count'] += len(versions) - 1
        report['girls_singleton_count'] += int(singleton)
    report['examples_loaded'] = len(examples)
    report['held_by_reason'] = dict(sorted(holds.items()))
    return examples, report
