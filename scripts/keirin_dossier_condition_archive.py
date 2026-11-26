"""Build only public, retrospective grade/round counts from the two admitted archive files."""
import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import stat
import time
from unicodedata import normalize

from race_ai import keirin_dossier_conditions as conditions
from race_ai import keirin_public_forecasts as public
from scripts import keirin_rider_dossier_readback as readback

PINNED_ARCHIVES = {
    'keirin.db': ('1bdad22b9744c9c5563f7bb1af31875170a3e6b7f4b0dd73fba8f98d645d8fc4', 104706048),
    'keirin_2026q4.db': ('d915560877493816b90df8bcd5e7bdef45557f57100b4cd40a3d017cd959334d', 45436928),
}
DOCKET = Path(__file__).resolve().parent.parent / (
    'docs/evidence/keirin-live-accuracy-closure-20261125/rider-dossier-recovery.json')


def _need(ok, reason):
    if not ok:
        raise ValueError('DOSSIER_CONDITION_ARCHIVE_' + reason)


def _name(value):
    return ''.join(normalize('NFKC', value).split()) if isinstance(value, str) else ''


def _prefecture(value):
    value = _name(value)
    if value == '東京都' or (len(value) >= 3 and value.endswith(('県','府'))):
        return value[:-1]
    return value


def identity_lookup(people):
    """Use the existing dossier's name, cohort and prefecture identity rule."""
    exact = defaultdict(set)
    for row in people:
        reg, cohort = row['registration'], row['cohort']
        key = _name(row['name']), 999 if cohort is None else cohort, _prefecture(row['prefecture_or_country'])
        exact[key].add(reg)
    return {key: next(iter(values)) for key, values in exact.items() if len(values) == 1}


def matching_starts(path, first_day, last_day, lookup):
    """Use the previously reconciled date, venue, race, car and result-name join."""
    deadline = time.monotonic() + 60
    conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True, timeout=3)
    try:
        conn.set_progress_handler(lambda: time.monotonic() > deadline, 10000)
        conn.execute('PRAGMA trusted_schema=OFF')
        conn.execute('PRAGMA query_only=ON')
        _need(conn.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'DATABASE_INTEGRITY')
        query = '''SELECT e.race_date,e.venue_code,e.rno,e.kumiban,e.racer_name,e.kyu,e.prefecture,
                          r.racer_name,r.rank,r.is_incident,a.grade,a.race_type
                   FROM entries e JOIN results r USING(race_date,venue_code,rno,kumiban)
                   LEFT JOIN races a USING(race_date,venue_code,rno)
                   WHERE e.race_date BETWEEN ? AND ?
                   ORDER BY e.race_date,e.venue_code,e.rno,e.kumiban'''
        for day, venue, race, car, name, cohort, prefecture, result_name, rank, incident, grade, label in conn.execute(
                query, (first_day.replace('-', ''), last_day.replace('-', ''))):
            cohort = str(cohort or '').strip()
            if not (cohort.isascii() and cohort.isdigit() and _name(result_name) == _name(name)
                    and type(incident) is int and incident == 0 and re.fullmatch('[1-9]', str(rank))):
                continue
            reg = lookup.get((_name(name), int(cohort), _prefecture(prefecture)))
            if reg is None:
                continue
            if type(venue) is str and re.fullmatch(r'[0-9]{2}', venue):
                venue = int(venue)
            _need(all(type(value) is int and 1 <= value <= bound
                      for value, bound in ((venue, 99), (race, 12), (car, 9))), 'RESULT_IDENTITY')
            yield (day, venue, race, car), (
                reg, grade if grade in conditions.GRADES else None, conditions.round_stage(label), int(rank))
    finally:
        conn.close()


def _database_pin(path):
    expected, size = PINNED_ARCHIVES[path.name]
    info = path.lstat()
    _need(stat.S_ISREG(info.st_mode) and info.st_size == size, 'DATABASE_SIZE')
    with path.open('rb') as stream:
        observed = sha256()
        for block in iter(lambda:stream.read(1024 * 1024), b''):
            observed.update(block)
    _need(observed.hexdigest() == expected, 'DATABASE_SHA')
    return expected


def _restored_files(folder, docket):
    files = {}
    for name in readback.FILES:
        pin = docket['files'][name]
        raw = readback._read(folder / name, readback.MAX_EXPANDED)
        _need(len(raw) == pin['bytes'] and sha256(raw).hexdigest() == pin['sha256'], 'RESTORED_FILE_SHA')
        files[name] = readback._json(raw)
    return files


def build_archive(restored, databases):
    docket = readback._json(DOCKET.read_bytes())
    restored_files = _restored_files(restored, docket)
    _need(len(databases) == len(PINNED_ARCHIVES) and
          {path.name for path in databases} == PINNED_ARCHIVES.keys(), 'DATABASE_SET')
    first, last = docket['history_start_day'], docket['history_end_day']
    expected = {row['registration']: [row['finish_history']['periods']['all']['finish_counts'][str(place)]
                                      for place in range(1, 10)]
                for row in restored_files[readback.NATIONAL]['dossiers']}
    lookup = identity_lookup(restored_files[readback.REGISTRY]['riders'])
    slots, pins = {}, []
    for path in databases:
        pins.append(_database_pin(path))
        for key, observation in matching_starts(path, first, last, lookup):
            _need(slots.setdefault(key, observation) == observation, 'CONFLICTED_RESULT_SLOT')
        _database_pin(path)
    counts = defaultdict(lambda: [0] * 9)
    for reg, _, _, rank in slots.values():
        counts[reg][rank - 1] += 1
    _need(len(slots) == docket['numeric_finish_records'] and
          len(counts) == docket['riders_with_numeric_history'] and
          dict(counts) == {reg: row for reg, row in expected.items() if any(row)}, 'VERIFIED_HISTOGRAM_CHANGED')
    return conditions.archive_slice(start_day=first, end_day=last, archive_sha256s=pins,
        registry_sha256=docket['files'][readback.REGISTRY]['sha256'], observations=slots.values())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--restored', type=Path, required=True)
    parser.add_argument('--database', action='append', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        archive = build_archive(args.restored, args.database)
        body = public.canonical(archive) + b'\n'
        _need(len(body) <= conditions.MAX_BYTES, 'PUBLIC_SIZE')
        with args.output.open('xb') as stream:
            stream.write(body)
    except (ValueError, KeyError, TypeError, OSError, OverflowError, sqlite3.Error) as error:
        reason = str(error)
        print(json.dumps(dict(state='HOLD_DOSSIER_CONDITION_ARCHIVE', reason=reason
                             if re.fullmatch('DOSSIER_CONDITION_ARCHIVE_[A-Z_]+',reason) else 'INVALID_SOURCE')))
        return 2
    print(json.dumps(dict(state='DOSSIER_CONDITION_ARCHIVE_VERIFIED', sha256=sha256(body).hexdigest(),
        bytes=len(body), **{key:archive[key] for key in (
            'start_day','end_day','numeric_finishes','condition_matched_finishes')},
        matched_riders=len(archive['riders'])), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
