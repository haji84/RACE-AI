"""Private dated-start projection for the existing Ride/HistoryBook authority.

Archive identities are reconciled with a newly captured registry. Neither that
registry nor unverified archive fetched clocks authenticate historical inputs.
This module does not fetch, decrypt, train, predict or change source databases.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from scripts import keirin_build_rider_dossiers as dossiers
from scripts.keirin_rider_profile_history import HistoryBook, Ride, ROLES, GRADES
from scripts.keirin_rider_profile_identity import name_key

SCHEMA = 'KEIRIN_RIDER_HISTORY_LEDGER_V1'
SCOPE = 'DERIVED_CURRENT_KNOWLEDGE_DATED_FINISH_PROJECTION'
MAX_BYTES = 16 * 1024 * 1024
COLUMNS = ['registration', 'race_id', 'car', 'finish', 'advertised_role', 'grade', 'source']
JST = ZoneInfo('Asia/Tokyo')
SHA = re.compile('[0-9a-f]{64}')


class LedgerHold(ValueError):
    """Fixed, non-private validation codes."""


def _need(condition, code):
    if not condition:
        raise LedgerHold('RIDER_HISTORY_LEDGER_' + code)


def _hash(raw):
    return sha256(raw).hexdigest()


def _instant(value):
    _need(type(value) is str and len(value) <= 64, 'CLOCK_INVALID')
    at = datetime.fromisoformat(value.replace('Z', '+00:00'))
    _need(at.utcoffset() is not None, 'CLOCK_INVALID')
    return at.astimezone(timezone.utc)


def _now(clock):
    at = (clock or (lambda: datetime.now(timezone.utc)))()
    _need(isinstance(at, datetime) and at.utcoffset() is not None, 'CLOCK_INVALID')
    return at.astimezone(timezone.utc)


def _day(value):
    _need(type(value) is str and re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}', value), 'DAY_INVALID')
    return date.fromisoformat(value)


def _race(value):
    _need(type(value) is str and re.fullmatch(r'20[0-9]{10}', value) and
          value[8:10] != '00' and 1 <= int(value[-2:]) <= 12, 'RACE_INVALID')
    return date.fromisoformat(value[:8])


def _registration(value):
    return type(value) is str and re.fullmatch('[0-9]{6}', value) and value != '000000'


def _json(raw):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'SIZE_INVALID')
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, 'JSON_INVALID')
            result[key] = value
        return result
    def invalid(_):
        raise LedgerHold('RIDER_HISTORY_LEDGER_JSON_INVALID')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)


def _encode(document):
    raw = (json.dumps(document, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    _need(len(raw) <= MAX_BYTES, 'SIZE_INVALID')
    return raw


def _archive_source(source, before):
    fields = {'kind', 'database_sha256', 'bytes', 'manifest_verified', 'source_url',
              'included_start_day', 'included_end_day', 'fetched_at_min_raw', 'fetched_at_max_raw',
              'fetched_clock_authentication'}
    _need(type(source) is dict and set(source) == fields and source['kind'] == 'SQLITE_ARCHIVE' and
          type(source['database_sha256']) is str and SHA.fullmatch(source['database_sha256']) and
          type(source['bytes']) is int and 0 < source['bytes'] <= 2**31 and
          source['manifest_verified'] is True and source['fetched_clock_authentication'] ==
          'UNATTESTED_ARCHIVE_VALUE_NOT_PRE_CUTOFF_EVIDENCE', 'SOURCE_INVALID')
    address = urlsplit(source['source_url'])
    pieces = address.path.strip('/').split('/')
    _need(address.scheme == 'https' and address.netloc == 'raw.githubusercontent.com' and
          not address.query and not address.fragment and len(pieces) >= 4 and
          re.fullmatch('[0-9a-f]{40}', pieces[2]), 'SOURCE_INVALID')
    first, last = source['included_start_day'], source['included_end_day']
    _need((first is None and last is None) or
          (first is not None and last is not None and _day(first) <= _day(last) < before), 'SOURCE_DATE_INVALID')
    for field in ('fetched_at_min_raw', 'fetched_at_max_raw'):
        _need(source[field] is None or type(source[field]) is str and 0 < len(source[field]) <= 96,
              'SOURCE_INVALID')


def _validate(document, now):
    fields = {'schema', 'scope', 'generated_at', 'knowledge_as_of', 'as_of_exclusive',
              'base_as_of_exclusive', 'registry_sha256', 'archive_manifest_sha256',
              'registry_capture_started_at', 'identity_knowledge_as_of',
              'source_download_started_at', 'source_download_completed_at',
              'registry_registrations', 'sources', 'columns', 'rows', 'official_revisions',
              'parent_ledger_sha256', 'historical_as_of_authenticated',
              'advertised_roles_are_observed_race_positions', 'predictive_model_changed'}
    _need(type(document) is dict and set(document) == fields and document['schema'] == SCHEMA and
          document['scope'] == SCOPE and document['historical_as_of_authenticated'] is False and
          document['advertised_roles_are_observed_race_positions'] is False and
          document['predictive_model_changed'] is False and document['columns'] == COLUMNS, 'SCHEMA_INVALID')
    generated, knowledge = map(_instant, (document['generated_at'], document['knowledge_as_of']))
    identity_start, identity_end = map(_instant, (document['registry_capture_started_at'],
                                                document['identity_knowledge_as_of']))
    download_start, download_end = map(_instant, (document['source_download_started_at'],
                                                document['source_download_completed_at']))
    _need(identity_start <= identity_end <= knowledge <= generated <= now and
          download_start <= download_end <= knowledge, 'CLOCK_INVALID')
    before, base_before = map(_day, (document['as_of_exclusive'], document['base_as_of_exclusive']))
    _need(base_before <= before, 'DAY_INVALID')
    _need(all(type(document[key]) is str and SHA.fullmatch(document[key])
              for key in ('registry_sha256', 'archive_manifest_sha256')), 'SOURCE_PIN_INVALID')
    _need(document['parent_ledger_sha256'] is None or type(document['parent_ledger_sha256']) is str and
          SHA.fullmatch(document['parent_ledger_sha256']), 'SOURCE_PIN_INVALID')
    registrations = document['registry_registrations']
    _need(type(registrations) is list and 0 < len(registrations) <= 10000 and
          all(_registration(r) for r in registrations) and registrations == sorted(set(registrations)),
          'REGISTRY_INVALID')
    sources = document['sources']
    _need(type(sources) is list and 0 < len(sources) <= 20, 'SOURCE_INVALID')
    for source in sources:
        _archive_source(source, base_before)
    _need(len({s['database_sha256'] for s in sources}) == len(sources), 'SOURCE_INVALID')
    _need(document['official_revisions'] == {}, 'OFFICIAL_PROVENANCE_INVALID')
    rows = document['rows']
    _need(type(rows) is list and len(rows) <= 500000, 'ROWS_INVALID')
    known = set(registrations)
    seen, slots = set(), set()
    previous = None
    for row in rows:
        _need(type(row) is list and len(row) == len(COLUMNS), 'ROW_INVALID')
        registration, rid, car, finish, role, grade, source_index = row
        race_day = _race(rid)
        _need(registration in known and race_day < before and race_day <= knowledge.astimezone(JST).date() and
              type(car) is int and 1 <= car <= 9 and type(finish) is int and 1 <= finish <= 9 and
              role in (*ROLES, None) and grade in (*GRADES, None) and
              type(source_index) is int and 0 <= source_index < len(sources), 'ROW_INVALID')
        source = sources[source_index]
        _need(source['included_start_day'] is not None and
              _day(source['included_start_day']) <= race_day <= _day(source['included_end_day']), 'SOURCE_DATE_INVALID')
        key, slot = (registration, rid), (rid, car)
        ordering = (rid, registration)
        _need(key not in seen and slot not in slots and (previous is None or previous < ordering), 'DUPLICATE_OR_UNSORTED_ROW')
        seen.add(key)
        slots.add(slot)
        previous = ordering
    return rows


def _book(rows):
    return HistoryBook(Ride(rid, registration, finish, expected=None, role=role, grade=grade)
                       for registration, rid, _, finish, role, grade, _ in rows)


def _report(raw, document):
    rows = document['rows']
    days = [row[1][:8] for row in rows]
    return dict(schema='KEIRIN_RIDER_HISTORY_LEDGER_REPORT_V1', ledger_sha256=_hash(raw),
                ledger_bytes=len(raw), numeric_finish_records=len(rows),
                riders_with_numeric_history=len({row[0] for row in rows}),
                registered_riders=len(document['registry_registrations']),
                history_start_day=date.fromisoformat(min(days)).isoformat() if days else None,
                history_end_day=date.fromisoformat(max(days)).isoformat() if days else None,
                as_of_exclusive=document['as_of_exclusive'], knowledge_as_of=document['knowledge_as_of'],
                registry_sha256=document['registry_sha256'], archive_manifest_sha256=document['archive_manifest_sha256'],
                archive_sha256s=[source['database_sha256'] for source in document['sources']],
                historical_as_of_authenticated=False, predictive_model_changed=False)


def build_ledger(db_paths, registry_raw, manifest_raw, *, expected_registry_sha256,
                 expected_manifest_sha256, as_of_day, clock=None):
    """Derive dated starts using the existing immutable archive/identity loader."""
    _need(type(registry_raw) is bytes and _hash(registry_raw) == expected_registry_sha256 and
          type(manifest_raw) is bytes and _hash(manifest_raw) == expected_manifest_sha256, 'INPUT_PIN_MISMATCH')
    now = _now(clock)
    registry, manifest = _json(registry_raw), _json(manifest_raw)
    paths = [Path(path) for path in db_paths]
    book, index, summary = dossiers.load_archive_book(paths, registry, as_of_day,
        archive_manifest=manifest, clock=lambda: now)
    wanted = {(registration, rid): (finish, role, grade)
              for registration, starts in book.finishes.items() for rid, finish, role, grade in starts}
    origins = defaultdict(set)
    for number, path in enumerate(paths):
        for row in dossiers._rows(path, _day(as_of_day).strftime('%Y%m%d')):
            cohort = str(row['kyu'] or '').strip()
            if not cohort.isascii() or not cohort.isdigit():
                continue
            registration = index.bind((name_key(row['racer_name']), int(cohort), row['prefecture']))
            rid = dossiers.archive._race_id(row)
            key = (registration, rid)
            if (key in wanted and name_key(row['result_name']) == name_key(row['racer_name']) and
                    str(row['rank']) == str(wanted[key][0]) and row['is_incident'] == 0):
                origins[key].add((row['kumiban'], number))
        _need(dossiers.archive._fingerprint(path) ==
              (summary['archive_sources'][number]['database_sha256'], summary['archive_sources'][number]['bytes']),
              'DATABASE_CHANGED')
    rows = []
    for (registration, rid), (finish, role, grade) in wanted.items():
        candidates = origins[registration, rid]
        _need(candidates and len({car for car, _ in candidates}) == 1, 'BASE_IDENTITY_AMBIGUOUS')
        car, source_index = min(candidates)
        rows.append([registration, rid, car, finish, role, grade, source_index])
    rows.sort(key=lambda row: (row[1], row[0]))
    document = dict(schema=SCHEMA, scope=SCOPE, generated_at=now.isoformat(), knowledge_as_of=now.isoformat(),
        as_of_exclusive=as_of_day, base_as_of_exclusive=as_of_day,
        registry_sha256=expected_registry_sha256, archive_manifest_sha256=expected_manifest_sha256,
        registry_capture_started_at=registry['retrieval_started_at'], identity_knowledge_as_of=registry['retrieval_completed_at'],
        source_download_started_at=manifest['started_at'], source_download_completed_at=manifest['completed_at'],
        registry_registrations=sorted(person['registration'] for person in registry['riders']),
        sources=[dict(kind='SQLITE_ARCHIVE', **source) for source in summary['archive_sources']],
        columns=COLUMNS, rows=rows, official_revisions={}, parent_ledger_sha256=None,
        historical_as_of_authenticated=False, advertised_roles_are_observed_race_positions=False,
        predictive_model_changed=False)
    _validate(document, now)
    raw = _encode(document)
    return raw, _report(raw, document)


def read_ledger(raw, *, expected_sha256, knowledge_as_of, target_race_id=None,
                target_cutoff_at=None, clock=None):
    """Require an independent digest before parsing or reconstructing HistoryBook."""
    _need(type(raw) is bytes and type(expected_sha256) is str and SHA.fullmatch(expected_sha256) and
          0 < len(raw) <= MAX_BYTES and _hash(raw) == expected_sha256, 'LEDGER_PIN_MISMATCH')
    now, requested = _now(clock), _instant(knowledge_as_of)
    document = _json(raw)
    rows = _validate(document, now)
    _need(_instant(document['knowledge_as_of']) <= requested <= now, 'KNOWLEDGE_UNAVAILABLE')
    if target_race_id is not None:
        _need(_race(target_race_id) >= _day(document['as_of_exclusive']), 'TARGET_DAY_INVALID')
    if target_cutoff_at is not None:
        cutoff = _instant(target_cutoff_at)
        _need(target_race_id is not None and _race(target_race_id) == cutoff.astimezone(JST).date() and
              requested < cutoff, 'TARGET_CUTOFF_INVALID')
    return _book(rows), _report(raw, document)
