"""Pinned, read-only historical inputs for the independent DT-R1 study.

These archives contain retrospectively collected secondary-source pages. Their
capture strings are preserved verbatim, without inventing a cutoff or timezone.
Every race is retained, including incomplete outcomes and unknown/contested lines.
No private names, source pages, database bytes, or keys belong in public reports.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import unicodedata


SOURCE_COMMIT = '2a1260fb0940ad11160b56a36f9c24cc4fb2f6d2'
PINNED_SOURCE_SHA256 = {
    'keirin.db': '1bdad22b9744c9c5563f7bb1af31875170a3e6b7f4b0dd73fba8f98d645d8fc4',
    'keirin_2026q4.db': 'd915560877493816b90df8bcd5e7bdef45557f57100b4cd40a3d017cd959334d',
}
PINNED_SOURCE_BYTES = {'keirin.db': 104706048, 'keirin_2026q4.db': 45436928}
MAX_DATABASE_BYTES = 256 * 1024 * 1024
IDENTITY_STATUS = 'UNRESOLVED_SOURCE_COMPOSITE'
REQUIRED_COLUMNS = {
    'races': {'race_date', 'venue_code', 'rno', 'race_type', 'grade', 'fetched_at'},
    'entries': {'race_date', 'venue_code', 'rno', 'kumiban', 'racer_name',
                'prefecture', 'kyu', 'racer_class', 'keisoku_tokuten'},
    'results': {'race_date', 'venue_code', 'rno', 'kumiban', 'rank'},
    'line_predictions': {'race_date', 'venue_code', 'rno', 'kumiban', 'line_no',
                         'position_in_line', 'line_size', 'role'},
}
INPUT_FIELDS = (
    'race_id', 'day', 'venue_code', 'race_class', 'race_type', 'meeting_grade',
    'field_size', 'field_supported', 'riders', 'line_groups', 'lines_known',
    'line_status', 'lines_applicable', 'published_line_groups',
)


class ArchiveError(ValueError):
    """Fixed reason codes only; exceptions never contain raw rider data."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def input_digest(record):
    """Hash normalized inputs only, not source-file hashes, results, or weather.

    The separate source_sha256 authenticates the complete archive bytes. Including
    that hash here would accidentally make this digest depend on target results.
    This is a semantic input digest, not a claim about original page byte hashes.
    """
    return sha256(_canonical({key: record.get(key) for key in INPUT_FIELDS})).hexdigest()


def _text(value):
    return unicodedata.normalize('NFKC', '' if value is None else str(value)).strip()


def _number(value, low=None, high=None, *, positive=False):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if (not math.isfinite(number) or (positive and number <= 0) or
            (low is not None and number < low) or (high is not None and number > high)):
        return None
    return number


def _integer(value):
    number = _number(value)
    return int(number) if number is not None and number.is_integer() else None


def _key(row):
    return str(row['race_date']), str(row['venue_code']), _integer(row['rno'])


def _race_identity(row):
    raw_day = str(row['race_date'])
    try:
        day = datetime.strptime(raw_day, '%Y%m%d').date()
    except (TypeError, ValueError):
        raise ArchiveError('INVALID_RACE_DAY') from None
    venue, number = _text(row['venue_code']).zfill(2), _integer(row['rno'])
    if day.strftime('%Y%m%d') != raw_day or not re.fullmatch(r'\d{2}', venue) or number is None or not 1 <= number <= 99:
        raise ArchiveError('INVALID_RACE_KEY')
    return raw_day + venue + f'{number:02d}', day.isoformat(), venue


def _class(riders):
    classes = {r['rider_class'] for r in riders}
    if not classes or classes == {''}:
        return 'UNKNOWN'
    if classes == {'L1'}:
        return 'L1'
    if classes <= {'SS', 'S1', 'S2'}:
        return 'S'
    if classes <= {'A1', 'A2'}:
        return 'A12'
    if classes == {'A3'}:
        return 'A3'
    return 'MIXED'


def _rider(row):
    # Composite identities are explicitly unresolved. A prefecture change can
    # split one person; namesakes can still collide. Neither is an official ID.
    parts = [re.sub(r'\s+', '', _text(row.get(k))) for k in ('racer_name', 'kyu', 'prefecture')]
    complete = all(parts)
    identity = sha256(_canonical(parts)).hexdigest() if complete else None
    style = {'逃': 'NIGE', '両': 'RYO', '追': 'OI', '自在': 'JIZAI',
             '捲': 'MAKURI', '差': 'SASHI'}.get(_text(row.get('kyaku_shitsu')), 'UNKNOWN')
    rider = {
        'car': _integer(row.get('kumiban')),
        'identity_key': identity,
        'identity_status': IDENTITY_STATUS,
        'identity_usable': complete,
        'identity_collision': False,
        'identity_collision_risk': True,
        'rider_class': _text(row.get('racer_class')),
        'competition_points': _number(row.get('keisoku_tokuten'), 0, 150, positive=True),
        'age': _number(row.get('age'), 15, 100),
        'style': style,
        'gear_ratio': _number(row.get('gear_ratio'), 0, 10, positive=True),
    }
    for field, source in (('win_rate', 'recent_win_rate'), ('top2_rate', 'recent_2rentai_rate'),
                          ('top3_rate', 'recent_3rentai_rate')):
        value = _number(row.get(source), 0, 100)
        rider[field] = value / 100 if value is not None else None
    rider['missing_fields'] = [key for key in ('competition_points', 'age', 'gear_ratio',
                                              'win_rate', 'top2_rate', 'top3_rate') if rider[key] is None]
    return rider


def _lines(rows, riders, race_class):
    cars = {r['car'] for r in riders}
    grouped = defaultdict(list)
    seen = set()
    valid = bool(rows)
    contested = False
    for row in rows:
        car, line, position, size = (_integer(row.get(k)) for k in
                                     ('kumiban', 'line_no', 'position_in_line', 'line_size'))
        if car not in cars or car in seen or any(v is None or v < 1 for v in (line, position, size)):
            valid = False
        seen.add(car)
        grouped[line if line is not None else -1].append((position or -1, car, size))
        contested |= '競' in _text(row.get('role'))
    groups = []
    for _, members in sorted(grouped.items()):
        members.sort(key=lambda row: (row[0], row[1] if row[1] is not None else -1))
        valid &= [x[0] for x in members] == list(range(1, len(members) + 1))
        valid &= all(x[2] == len(members) for x in members)
        groups.append([x[1] for x in members if x[1] is not None])
    if not rows:
        status = 'MISSING'
    elif contested:
        status = 'CONTESTED'
    elif seen != cars:
        status = 'PARTIAL'
    elif not valid:
        status = 'INVALID'
    else:
        status = 'KNOWN'
    # L1 is recognized from class, never the defective archive gender flags.
    # Published order is retained, but is not asserted to be a cooperating line.
    applicable = race_class != 'L1'
    known = status == 'KNOWN' and applicable
    role_by_car = {_integer(r.get('kumiban')): _text(r.get('role')) for r in rows}
    for rider in riders:
        rider['published_line_role'] = role_by_car.get(rider['car']) or None
    return dict(line_groups=groups if known else [], published_line_groups=groups,
                lines_known=known, line_status=status, lines_applicable=applicable)


def _outcomes(rows, cars):
    result_rows = []
    for row in sorted(rows, key=lambda r: _integer(r.get('kumiban')) or -1):
        raw_rank = _text(row.get('rank'))
        rank = int(raw_rank) if re.fullmatch(r'[1-9]', raw_rank) else None
        result_rows.append({
            'car': _integer(row.get('kumiban')), 'rank': rank,
            'rank_raw': raw_rank,
            'absence': '欠' in raw_rank,
            'cancelled': '中止' in raw_rank or '不成立' in raw_rank,
            'incident': any(token in raw_rank for token in ('落', '失', '棄', '妨')),
            'half_lap_seconds': _number(row.get('agari'), 0, 120, positive=True),
            'final_lap_seconds': None,
            'sb_mark': _text(row.get('sb_mark')) if row.get('sb_mark') is not None else None,
            'source_available_at': row.get('fetched_at'),
        })
    numeric = [(r['rank'], r['car']) for r in result_rows if r['rank'] is not None and r['car'] in cars]
    rank_counts = Counter(rank for rank, _ in numeric)
    result_cars = [r['car'] for r in result_rows]
    roster_valid = len(result_cars) == len(set(result_cars)) and set(result_cars) <= cars
    complete = bool(cars) and roster_valid and set(result_cars) == cars and len(numeric) == len(cars)
    complete &= sorted(rank for rank, _ in numeric) == list(range(1, len(cars) + 1))
    finish = [car for _, car in sorted(numeric)] if complete else None
    top = [(rank, car) for rank, car in numeric if rank <= 3]
    top3 = ([car for _, car in sorted(top)] if roster_valid and len(top) == 3 and
            all(rank_counts.get(i) == 1 for i in (1, 2, 3)) and len({car for _, car in top}) == 3 else None)
    if not result_rows:
        status = 'MISSING'
    elif all(r['cancelled'] for r in result_rows):
        status = 'CANCELLED'
    elif any(n > 1 for n in rank_counts.values()):
        status = 'DEAD_HEAT'
    elif complete:
        status = 'COMPLETE'
    elif top3 is not None:
        status = 'PARTIAL_VALID_TOP3'
    elif any(r['absence'] or r['incident'] for r in result_rows):
        status = 'SPECIAL_OR_INCOMPLETE'
    else:
        status = 'INCOMPLETE'
    return dict(finish=finish, top3=top3, result_status=status, result_rows=result_rows)


def _normalize(race, entries, lines, results, source_digest):
    race_id, day, venue = _race_identity(race)
    riders = [_rider(row) for row in sorted(entries, key=lambda r: _integer(r.get('kumiban')) or -1)]
    identities = Counter(r['identity_key'] for r in riders if r['identity_key'])
    for rider in riders:
        if rider['identity_key'] and identities[rider['identity_key']] > 1:
            rider['identity_usable'] = False
            rider['identity_collision'] = True
    cars = [r['car'] for r in riders]
    if len(set(cars)) != len(cars):
        raise ArchiveError('DUPLICATE_ENTRY_CAR')
    race_class = _class(riders)
    record = dict(
        race_id=race_id, day=day, venue_code=venue, race_class=race_class,
        race_type=_text(race.get('race_type')), meeting_grade=_text(race.get('grade')),
        field_size=len(riders), field_supported=3 <= len(riders) <= 9 and
        all(type(car) is int and 1 <= car <= 9 for car in cars), riders=riders,
        source_sha256=source_digest, source_sha256s=[source_digest], cohort='retrospective',
        source_available_at=race.get('fetched_at'), source_available_at_verified=False,
        pre_cutoff_authenticated=False, official_result_authenticated=False,
        identity_scope=IDENTITY_STATUS,
        archived_weather=dict(weather=race.get('weather'), wind_speed=_number(race.get('wind_speed')),
                              usable_as_same_race_input=False),
    )
    record.update(_lines(lines, riders, race_class))
    record.update(_outcomes(results, set(cars)))
    record['input_sha256'] = input_digest(record)
    return record


def _verify_file(path, pins):
    path = Path(path)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or not 16 <= info.st_size <= MAX_DATABASE_BYTES:
            raise ArchiveError('BOUNDED_REGULAR_DATABASE_REQUIRED')
        expected = pins.get(str(path), pins.get(str(path.resolve()), pins.get(path.name)))
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ArchiveError('SOURCE_SHA256_PIN_REQUIRED')
        digest = sha256()
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as source:
            header = source.read(16)
            digest.update(header)
            if header != b'SQLite format 3\0':
                raise ArchiveError('SQLITE_HEADER_INVALID')
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ArchiveError('SOURCE_SHA256_MISMATCH')
        if pins is PINNED_SOURCE_SHA256 and info.st_size != PINNED_SOURCE_BYTES[path.name]:
            raise ArchiveError('SOURCE_BYTES_MISMATCH')
        return path.resolve(), expected, info.st_size
    except OSError:
        raise ArchiveError('SOURCE_FILE_UNAVAILABLE') from None


def load_archives(paths, *, expected_sha256=PINNED_SOURCE_SHA256):
    """Return ``(records, aggregate_audit)`` without dropping any race.

    Production research uses the two fixed hashes above. Tests or an explicitly
    pinned new archive may pass a mapping keyed by exact path or filename. SHA
    checks establish file integrity, not official results or pre-race availability.

    ``audit.dataset_manifest`` is the model-independent common-source manifest for
    a fair comparison. It binds complete source bytes and does not depend on any
    model's features or fitted parameters. The per-race ``input_sha256`` binds the
    shared normalized card; a model-specific feature digest is a separate object.
    """
    paths = list(paths)
    if not paths:
        raise ArchiveError('ARCHIVE_PATH_REQUIRED')
    records, comparisons, sources = {}, {}, []
    identical = 0
    for supplied in paths:
        path, digest, byte_count = _verify_file(supplied, expected_sha256)
        try:
            with sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True) as con:
                con.row_factory = sqlite3.Row
                con.execute('PRAGMA query_only=ON')
                con.execute('PRAGMA trusted_schema=OFF')
                if [tuple(x) for x in con.execute('PRAGMA quick_check')] != [('ok',)]:
                    raise ArchiveError('SQLITE_INTEGRITY_FAILED')
                for table, required in REQUIRED_COLUMNS.items():
                    kind = con.execute('SELECT type FROM sqlite_master WHERE name=?', (table,)).fetchone()
                    columns = {x[1] for x in con.execute('PRAGMA table_info(' + table + ')')}
                    if kind is None or kind[0] != 'table' or not required <= columns:
                        raise ArchiveError('ARCHIVE_SCHEMA_MISMATCH')
                indexes = {}
                counts = {}
                for table in ('entries', 'line_predictions', 'results'):
                    grouped = defaultdict(list)
                    for row in con.execute('SELECT * FROM ' + table):
                        grouped[_key(row)].append(dict(row))
                    indexes[table] = grouped
                    counts[table] = sum(map(len, grouped.values()))
                races = [dict(row) for row in con.execute('SELECT * FROM races ORDER BY race_date,venue_code,rno')]
                counts['races'] = len(races)
                keys = {_key(r) for r in races}
                orphan_rows = {table: sum(len(rows) for key, rows in grouped.items() if key not in keys)
                               for table, grouped in indexes.items()}
                for race in races:
                    key = _key(race)
                    record = _normalize(race, indexes['entries'].get(key, []),
                                        indexes['line_predictions'].get(key, []),
                                        indexes['results'].get(key, []), digest)
                    # A repeated race must agree in every normalized semantic and
                    # observation field; only archive container hashes may differ.
                    comparison = _canonical({k: v for k, v in record.items() if k not in
                                             ('source_sha256', 'source_sha256s')})
                    rid = record['race_id']
                    if rid in records:
                        if comparisons[rid] != comparison:
                            raise ArchiveError('CONFLICTING_DUPLICATE_RACE')
                        identical += 1
                        if digest not in records[rid]['source_sha256s']:
                            records[rid]['source_sha256s'].append(digest)
                    else:
                        records[rid], comparisons[rid] = record, comparison
                sources.append(dict(file=path.name, sha256=digest, bytes=byte_count,
                                    quick_check='ok', rows=counts, orphan_rows=orphan_rows))
                del indexes, races
        except sqlite3.Error:
            raise ArchiveError('SQLITE_READ_FAILED') from None
    ordered = sorted(records.values(), key=lambda r: (r['day'], r['race_id']))
    days = Counter(row['day'] for row in ordered)
    manifest = dict(
        schema='CHAT_DT_R1_COMMON_ARCHIVE_SOURCES_V1', cohort='retrospective',
        sources=sorted([dict(file=s['file'], sha256=s['sha256'], bytes=s['bytes'])
                        for s in sources], key=lambda s: (s['sha256'], s['file'])),
        raw_result_bytes_included_in_source_hash=True,
        model_features_included=False, pre_cutoff_attestation=False,
    )
    audit = dict(
        schema='CHAT_DT_R1_RETROSPECTIVE_ARCHIVE_AUDIT_V1', cohort='retrospective',
        dataset_manifest=manifest, dataset_sha256=sha256(_canonical(manifest)).hexdigest(),
        sources=sources, scanned_races=sum(s['rows']['races'] for s in sources),
        unique_races=len(ordered), identical_duplicates=identical, conflicting_duplicates=0,
        records_excluded=0, days=dict(sorted(days.items())), observed_days=len(days),
        first_day=min(days) if days else None, last_day=max(days) if days else None,
        fields=dict(Counter(str(r['field_size']) for r in ordered)),
        classes=dict(Counter(r['race_class'] for r in ordered)),
        line_statuses=dict(Counter(r['line_status'] for r in ordered)),
        result_statuses=dict(Counter(r['result_status'] for r in ordered)),
        usable_full_finish=sum(r['finish'] is not None for r in ordered),
        usable_top3=sum(r['top3'] is not None for r in ordered),
        unsupported_field_count=sum(not r['field_supported'] for r in ordered),
        missing_score_riders=sum(r['competition_points'] is None for row in ordered for r in row['riders']),
        unresolved_identity_riders=sum(len(row['riders']) for row in ordered),
        ambiguous_identity_riders=sum(not r['identity_usable'] for row in ordered for r in row['riders']),
        pre_cutoff_authenticated=False, official_results_authenticated=False,
        source_timezones_inferred=False, raw_names_returned=False,
        archive_gender_flags_used=False, whole_evaluation_retrospective=True,
    )
    return ordered, audit
