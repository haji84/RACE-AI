"""Publish a hash-pinned archive of aggregate rider finishes and observations."""
import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
from subprocess import TimeoutExpired

from race_ai import keirin_public_forecasts as public
from scripts.keirin_publish_dossier_conditions import _commit

SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_RIDER_HISTORY_ARCHIVE_V1'
SHA = re.compile('[0-9a-f]{64}')
REG = re.compile('[0-9]{6}')
VENUE = re.compile('[1-9][0-9]')
TECHNIQUES = {'escape', 'makuri', 'difference', 'mark'}
REQUIRED = {'schema','start_day','end_day','numeric_finishes','source_sha256s','riders'}
VENUE_PERIOD = {'venue_start_day','venue_end_day'}
OBSERVATION_PERIOD = {'observations_start_day','observations_end_day'}
RIDER_FIELDS = {'registration','counts','venues'}


def _require(condition):
    if not condition:
        raise ValueError('PUBLIC_RIDER_HISTORY_ARCHIVE_INVALID')


def _date(value):
    _require(type(value) is str)
    parsed = date.fromisoformat(value)
    _require(parsed.isoformat() == value)
    return parsed


def _numbers(values, length):
    return (type(values) is list and len(values) == length and
            all(type(value) is int and value >= 0 for value in values))


def checked_archive(doc):
    _require(type(doc) is dict and REQUIRED <= doc.keys() <= REQUIRED | VENUE_PERIOD | OBSERVATION_PERIOD and
             doc['schema'] == SCHEMA)
    first, last = _date(doc['start_day']), _date(doc['end_day'])
    _require(first <= last)
    for prefix, fields in (('venue', VENUE_PERIOD), ('observations', OBSERVATION_PERIOD)):
        if fields & doc.keys():
            _require(fields <= doc.keys() and first <= _date(doc[prefix+'_start_day']) <=
                     _date(doc[prefix+'_end_day']) <= last)
    hashes, riders = doc['source_sha256s'], doc['riders']
    _require(type(hashes) is list and 1 <= len(hashes) <= 100 and
             all(type(value) is str and SHA.fullmatch(value) for value in hashes) and len(set(hashes)) == len(hashes))
    _require(type(riders) is list and 1 <= len(riders) <= 5000)
    ids, finishes = [], 0
    for rider in riders:
        _require(type(rider) is dict and RIDER_FIELDS <= rider.keys() <= RIDER_FIELDS | {'agari','techniques'})
        registration, counts, venues = rider['registration'], rider['counts'], rider['venues']
        _require(type(registration) is str and REG.fullmatch(registration) and registration != '000000' and
                 _numbers(counts, 9) and sum(counts) > 0 and type(venues) is dict)
        total = sum(counts)
        venue_finishes = 0
        for code, sample in venues.items():
            _require(VENUE.fullmatch(code) and _numbers(sample, 2) and sample[1] > 0 and sample[0] <= sample[1])
            venue_finishes += sample[1]
        _require(venue_finishes <= total)
        if 'agari' in rider:
            values = rider['agari']
            _require(OBSERVATION_PERIOD <= doc.keys() and _numbers(values, 3))
            runs, comparisons, slower_score = values
            _require(0 < runs <= total and runs <= comparisons <= 8 * runs and slower_score <= 2 * comparisons)
        if 'techniques' in rider:
            methods = rider['techniques']
            _require(OBSERVATION_PERIOD <= doc.keys() and type(methods) is dict and
                     methods and methods.keys() <= TECHNIQUES and
                     all(type(value) is int and value >= 0 for value in methods.values()) and
                     0 < sum(methods.values()) <= counts[0] + counts[1])
        ids.append(registration)
        finishes += total
    _require(ids == sorted(set(ids)) and type(doc['numeric_finishes']) is int and doc['numeric_finishes'] == finishes)
    return doc


def publish(store, raw, expected_sha256):
    _require(type(raw) is bytes and 0 < len(raw) <= public.RIDER_ARCHIVE_MAX and
             sha256(raw).hexdigest() == expected_sha256)
    checked_archive(public._json(raw))
    path = public.RIDER_ARCHIVE_PATH
    for attempt in range(2):
        parent = store.head()
        _require(bool(parent))
        store.fetch(parent)
        prior = store.read_previous(parent, path)
        if prior is not None:
            _require(prior == raw)
            return parent
        try:
            return _commit(store, parent, {path:raw})
        except (ValueError, TimeoutExpired):
            if attempt or store.head() == parent:
                raise
    raise ValueError('PUBLIC_RIDER_HISTORY_ARCHIVE_CONCURRENT')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    _require(args.archive.is_file() and not args.archive.is_symlink() and
             args.archive.stat().st_size <= public.RIDER_ARCHIVE_MAX)
    raw = args.archive.read_bytes()
    commit = publish(public.PublicForecastGit(args.repo), raw, args.sha256)
    print(json.dumps(dict(commit=commit, archive_sha256=args.sha256, bytes=len(raw))))


if __name__ == '__main__':
    main()
