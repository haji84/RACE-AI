"""Private dated-start projection for the existing Ride/HistoryBook authority.

Archive identities are reconciled with a newly captured registry. Neither that
registry nor unverified archive fetched clocks authenticate historical inputs.
This module does not fetch, decrypt, train, predict or change source databases.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from race_ai.keirin_note_view import _create, _private_root
from race_ai.keirin_official_rider_history import NON_NUMERIC, NUMERIC, _identities
from scripts import keirin_build_rider_dossiers as dossiers
from scripts.keirin_official_rider_history_readback import checked_receipt
from scripts.keirin_rider_profile_history import HistoryBook, Ride, ROLES, GRADES
from scripts.keirin_rider_profile_identity import name_key

SCHEMA = 'KEIRIN_RIDER_HISTORY_LEDGER_V1'
SCOPE = 'DERIVED_CURRENT_KNOWLEDGE_DATED_FINISH_PROJECTION'
MAX_BYTES = 16 * 1024 * 1024
COLUMNS = ['registration', 'race_id', 'car', 'finish', 'advertised_role', 'grade', 'source']
JST = ZoneInfo('Asia/Tokyo')
SHA = re.compile('[0-9a-f]{64}')
GIT_SHA = re.compile('[0-9a-f]{40}')
OFFICIAL_SCOPE = 'DERIVED_OFFICIAL_RESULT_PROJECTION_NOT_FORECAST_OR_SECOND_STATE_AUTHORITY'


class LedgerHold(ValueError):
    """Fixed, non-private validation codes."""


def _need(condition, code):
    if not condition:
        raise LedgerHold('RIDER_HISTORY_LEDGER_' + code)


def _hash(raw):
    return sha256(raw).hexdigest()


def _digest(value, pattern=SHA):
    return type(value) is str and pattern.fullmatch(value) is not None


def _pinned(raw, expected, code):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES and _digest(expected) and
          _hash(raw) == expected, code)
    return _json(raw)


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


def _official_result(rid, result, knowledge):
    _need(type(result) is dict and _digest(result.get('original_evidence_sha256')), 'OFFICIAL_PROVENANCE_INVALID')
    day = _race(rid)
    finishes = result.get('finishes')
    _need(type(finishes) is list and 5 <= len(finishes) <= 9 and all(type(row) is dict and
          set(row) == {'car', 'registration_id', 'status', 'place'} for row in finishes), 'OFFICIAL_FINISH_INVALID')
    identities = _identities(finishes, 'registration_id')
    places = Counter()
    for row in finishes:
        status, place = row['status'], row['place']
        _need(type(status) is str and ((status in NUMERIC and type(place) is int and 1 <= place <= len(finishes)) or
              (status in NON_NUMERIC and place is None)), 'OFFICIAL_FINISH_INVALID')
        if place is not None:
            places[place] += 1
    next_place = 1
    for place, count in sorted(places.items()):
        _need(place == next_place, 'OFFICIAL_FINISH_INVALID')
        next_place += count
    revisions = result.get('revisions')
    _need(type(revisions) is list and 1 <= len(revisions) <= 16, 'OFFICIAL_PROVENANCE_INVALID')
    previous = None
    seen = set()
    for proof in revisions:
        clocks = ('cutoff_at', 'source_updated_at', 'source_observed_at', 'sealed_at')
        hashes = ('evidence_sha256', 'source_sha256', 'cipher_sha256')
        _need(type(proof) is dict and set(proof) == set(clocks + hashes) and
              all(_digest(proof[key]) for key in hashes) and proof['evidence_sha256'] not in seen,
              'OFFICIAL_PROVENANCE_INVALID')
        cutoff, updated, observed, sealed = map(_instant, (proof[key] for key in clocks))
        _need(cutoff.astimezone(JST).date() == day and cutoff < updated <= observed <= sealed <= knowledge and
              (previous is None or (cutoff == previous[0] and updated >= previous[1] and
                                    observed >= previous[2] and sealed > previous[3])), 'OFFICIAL_CLOCK_INVALID')
        previous = (cutoff, updated, observed, sealed)
        seen.add(proof['evidence_sha256'])
    return identities, places


def _official_rows(rid, result, known):
    rows = {}
    for finish in result['finishes']:
        registration = finish['registration_id']
        if registration in known and finish['place'] is not None:
            role, grade = result['archive_context'].get(registration, (None, None))
            rows[registration, rid] = [registration, rid, finish['car'], finish['place'], role, grade, None]
    return rows


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
    official = document['official_revisions']
    _need(type(official) is dict and (not official or document['parent_ledger_sha256'] is not None),
          'OFFICIAL_PROVENANCE_INVALID')
    rows = document['rows']
    _need(type(rows) is list and len(rows) <= 500000, 'ROWS_INVALID')
    known = set(registrations)
    expected_official = {}
    for rid, result in official.items():
        _need(type(result) is dict and set(result) == {'original_evidence_sha256', 'revisions', 'finishes',
              'archive_commit', 'projection_sha256', 'projection_knowledge_as_of', 'archive_context'} and
              _digest(result['archive_commit'], GIT_SHA) and _digest(result['projection_sha256']) and
              _race(rid) < before, 'OFFICIAL_PROVENANCE_INVALID')
        source_knowledge = _instant(result['projection_knowledge_as_of'])
        _need(source_knowledge <= knowledge, 'OFFICIAL_CLOCK_INVALID')
        field, _ = _official_result(rid, result, source_knowledge)
        context = result['archive_context']
        _need(type(context) is dict and set(context) <= (known & set(field.values())) and all(
              type(pair) is list and len(pair) == 2 and pair[0] in (*ROLES, None) and pair[1] in (*GRADES, None)
              for pair in context.values()), 'OFFICIAL_PROVENANCE_INVALID')
        expected_official.update(_official_rows(rid, result, known))
    seen, slots = set(), set()
    previous = None
    for row in rows:
        _need(type(row) is list and len(row) == len(COLUMNS), 'ROW_INVALID')
        registration, rid, car, finish, role, grade, source_index = row
        race_day = _race(rid)
        _need(registration in known and race_day < before and race_day <= knowledge.astimezone(JST).date() and
              type(car) is int and 1 <= car <= 9 and type(finish) is int and 1 <= finish <= 9 and
              role in (*ROLES, None) and grade in (*GRADES, None), 'ROW_INVALID')
        key, slot = (registration, rid), (rid, car)
        if rid in official:
            _need(expected_official.pop(key, None) == row, 'OFFICIAL_ROW_MISMATCH')
        else:
            _need(type(source_index) is int and 0 <= source_index < len(sources), 'ROW_INVALID')
            source = sources[source_index]
            _need(source['included_start_day'] is not None and
                  _day(source['included_start_day']) <= race_day <= _day(source['included_end_day']), 'SOURCE_DATE_INVALID')
        ordering = (rid, registration)
        _need(key not in seen and slot not in slots and (previous is None or previous < ordering), 'DUPLICATE_OR_UNSORTED_ROW')
        seen.add(key)
        slots.add(slot)
        previous = ordering
    _need(not expected_official, 'OFFICIAL_ROW_MISMATCH')
    return rows


def _book(rows):
    return HistoryBook(Ride(rid, registration, finish, expected=None, role=role, grade=grade)
                       for registration, rid, _, finish, role, grade, _ in rows)


def _report(raw, document):
    rows = document['rows']
    days = [row[1][:8] for row in rows]
    official = document['official_revisions'].values()
    return dict(schema='KEIRIN_RIDER_HISTORY_LEDGER_REPORT_V1', ledger_sha256=_hash(raw),
                ledger_bytes=len(raw), numeric_finish_records=len(rows),
                riders_with_numeric_history=len({row[0] for row in rows}),
                registered_riders=len(document['registry_registrations']),
                history_start_day=date.fromisoformat(min(days)).isoformat() if days else None,
                history_end_day=date.fromisoformat(max(days)).isoformat() if days else None,
                as_of_exclusive=document['as_of_exclusive'], knowledge_as_of=document['knowledge_as_of'],
                registry_sha256=document['registry_sha256'], archive_manifest_sha256=document['archive_manifest_sha256'],
                archive_sha256s=[source['database_sha256'] for source in document['sources']],
                official_races=len(official), verified_official_revisions=sum(len(race['revisions']) for race in official),
                official_non_numeric_finishes=sum(row['place'] is None for race in official for row in race['finishes']),
                official_numeric_finishes_in_ledger=sum(row[-1] is None for row in rows),
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
    document = _pinned(raw, expected_sha256, 'LEDGER_PIN_MISMATCH')
    now, requested = _now(clock), _instant(knowledge_as_of)
    rows = _validate(document, now)
    _need(_instant(document['knowledge_as_of']) <= requested <= now, 'KNOWLEDGE_UNAVAILABLE')
    if target_race_id is not None:
        _need(_race(target_race_id) >= _day(document['as_of_exclusive']), 'TARGET_DAY_INVALID')
    if target_cutoff_at is not None:
        cutoff = _instant(target_cutoff_at)
        _need(target_race_id is not None and _race(target_race_id) == cutoff.astimezone(JST).date() and
              requested < cutoff, 'TARGET_CUTOFF_INVALID')
    return _book(rows), _report(raw, document)


def _checked_projection(official, now):
    _need(type(official) is dict and set(official) == {'schema', 'scope', 'receipt', 'replay', 'histories', 'races'} and
          official['schema'] == 'KEIRIN_OFFICIAL_RIDER_HISTORY_PRIVATE_V1' and official['scope'] == OFFICIAL_SCOPE,
          'OFFICIAL_PROJECTION_INVALID')
    receipt = checked_receipt(official['receipt'])
    source_day, target_day = map(_day, (receipt['source_day'], receipt['target_day']))
    knowledge = _instant(receipt['knowledge_as_of'])
    replay, races = official['replay'], official['races']
    _need(type(replay) is dict and type(races) is dict and type(official['histories']) is list and
          replay.get('schema') == 'KEIRIN_OFFICIAL_RIDER_HISTORY_REPLAY_V1' and
          replay.get('target_scope') == 'DAY_LEVEL_DOSSIER_NO_FORECAST_DEADLINE' and
          replay.get('source_day') == receipt['source_day'] and replay.get('target_day') == receipt['target_day'] and
          replay.get('index_commit') == receipt['archive_commit'] and
          all(replay.get(key) is False for key in ('historical_as_of_authenticated',
              'forecast_original_authenticated', 'predictive_model_changed', 'accuracy_improvement_proven')),
          'OFFICIAL_PROJECTION_INVALID')
    _need(source_day <= knowledge.astimezone(JST).date() <= target_day and
          _instant(replay.get('knowledge_as_of')) == knowledge <= _instant(replay.get('replayed_at')) <= now,
          'OFFICIAL_CLOCK_INVALID')
    _need(len(races) == receipt['expected_result_races'], 'OFFICIAL_COUNTS_INVALID')
    report = Counter()
    for rid, result in races.items():
        _need(_race(rid) == source_day and type(result) is dict and
              set(result) == {'original_evidence_sha256', 'revisions', 'finishes'}, 'OFFICIAL_PROVENANCE_INVALID')
        _, counts = _official_result(rid, result, knowledge)
        numeric = counts.total()
        report['numeric_finishes'] += numeric
        report['non_numeric_finishes'] += len(result['finishes']) - numeric
        report['tied_races'] += any(count > 1 for count in counts.values())
        report['verified_revisions'] += len(result['revisions'])
    report.update(dict(admitted_races=len(races), originals_by_as_of=receipt['expected_originals'],
                       no_result_by_as_of=receipt['expected_originals']-len(races)))
    report['held_races'] = 0
    _need(report['numeric_finishes'] > 0 and all(type(replay.get(key)) is int and replay[key] == value
          for key, value in report.items()), 'OFFICIAL_COUNTS_INVALID')
    return receipt, races


def _merge_race(current, result, prior_rows, knowledge):
    identities = {row['car']: row['registration_id'] for row in result['finishes']}
    _need(all(identities.get(car) == registration for registration, _, car, *_ in prior_rows),
          'OFFICIAL_IDENTITY_CONFLICT')
    if current is None:
        return {registration: [role, grade] for registration, _, _, _, role, grade, _ in prior_rows}

    previous_field = {row['car']: row['registration_id'] for row in current['finishes']}
    _need(identities == previous_field and result['original_evidence_sha256'] == current['original_evidence_sha256'],
          'OFFICIAL_IDENTITY_CONFLICT')
    _need(knowledge >= _instant(current['projection_knowledge_as_of']), 'OFFICIAL_CLOCK_REGRESSION')
    prior, received = current['revisions'], result['revisions']
    _need(received[:len(prior)] == prior, 'OFFICIAL_REVISION_CONFLICT')
    old_finishes = sorted(current['finishes'], key=lambda row: row['car'])
    new_finishes = sorted(result['finishes'], key=lambda row: row['car'])
    if received == prior:
        _need(old_finishes == new_finishes, 'OFFICIAL_REVISION_CONFLICT')
        return None
    if old_finishes != new_finishes:
        _need(_instant(received[-1]['source_updated_at']) > _instant(prior[-1]['source_updated_at']) and
              received[-1]['source_sha256'] != prior[-1]['source_sha256'], 'OFFICIAL_REVISION_CONFLICT')
    return current['archive_context']


def merge_official(ledger_raw, official_raw, *, expected_ledger_sha256, expected_official_sha256, clock=None):
    """Apply a pinned owner projection once while retaining prior ledger bytes and result revisions."""
    now = _now(clock)
    parent = _pinned(ledger_raw, expected_ledger_sha256, 'LEDGER_PIN_MISMATCH')
    rows = _validate(parent, now)
    receipt, incoming = _checked_projection(_pinned(official_raw, expected_official_sha256, 'OFFICIAL_PIN_MISMATCH'), now)
    before = max(parent['as_of_exclusive'], (_day(receipt['source_day']) + timedelta(days=1)).isoformat())
    knowledge = _instant(receipt['knowledge_as_of'])
    known = set(parent['registry_registrations'])
    official = dict(parent['official_revisions'])
    prior_rows = defaultdict(list)
    for row in rows:
        if row[1] in incoming:
            prior_rows[row[1]].append(row)

    replacements = {}
    for rid, result in incoming.items():
        context = _merge_race(official.get(rid), result, prior_rows[rid], knowledge)
        if context is not None:
            official[rid] = dict(result, archive_commit=receipt['archive_commit'], archive_context=context,
                                 projection_sha256=expected_official_sha256, projection_knowledge_as_of=knowledge.isoformat())
            replacements[rid] = _official_rows(rid, official[rid], known).values()
    if not replacements and before == parent['as_of_exclusive']:
        return ledger_raw, _report(ledger_raw, parent)
    updated_rows = [row for row in rows if row[1] not in replacements]
    for new_rows in replacements.values():
        updated_rows.extend(new_rows)
    updated_rows.sort(key=lambda row: (row[1], row[0]))
    document = dict(parent, rows=updated_rows, official_revisions=official, as_of_exclusive=before,
                    generated_at=now.isoformat(), knowledge_as_of=now.isoformat(),
                    parent_ledger_sha256=expected_ledger_sha256)
    _validate(document, now)
    raw = _encode(document)
    return raw, _report(raw, document)


def _read_private(path):
    _need(path.is_absolute(), 'PRIVATE_PATH_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as file:
        info = os.fstat(file.fileno())
        _need(stat.S_ISREG(info.st_mode) and info.st_mode & 0o077 == 0 and 0 < info.st_size <= MAX_BYTES,
              'PRIVATE_FILE_INVALID')
        raw = file.read(MAX_BYTES + 1)
    _need(len(raw) == info.st_size, 'PRIVATE_FILE_CHANGED')
    return raw


def write_private(directory, raw, expected_sha256):
    """Publish an immutable 0600 ledger by digest. An equal retry reuses the completed file."""
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES and _hash(raw) == expected_sha256, 'LEDGER_PIN_MISMATCH')
    directory = _private_root(directory)
    target = directory / f'{expected_sha256}.json'
    with TemporaryDirectory(dir=directory) as temporary:
        staged = Path(temporary) / 'ledger.json'
        _create(staged, raw)
        try:
            os.link(staged, target)
        except FileExistsError:
            _need(_read_private(target) == raw, 'OUTPUT_CONFLICT')
    return target


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise LedgerHold('RIDER_HISTORY_LEDGER_ARGUMENTS_INVALID')


def main(argv=None):
    parser = _Parser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest='command', required=True, parser_class=_Parser)
    build = commands.add_parser('build', allow_abbrev=False)
    build.add_argument('--database', action='append', type=Path, required=True)
    build.add_argument('--registry', type=Path, required=True)
    build.add_argument('--archive-manifest', type=Path, required=True)
    build.add_argument('--registry-sha256', required=True)
    build.add_argument('--archive-manifest-sha256', required=True)
    build.add_argument('--as-of-day', required=True)
    build.add_argument('--output-dir', type=Path, required=True)
    merge = commands.add_parser('merge-official', allow_abbrev=False)
    merge.add_argument('--official', type=Path, required=True)
    merge.add_argument('--official-sha256', required=True)
    merge.add_argument('--output-dir', type=Path, required=True)
    verify = commands.add_parser('verify', allow_abbrev=False)
    for command in (merge, verify):
        command.add_argument('--ledger', type=Path, required=True)
        command.add_argument('--ledger-sha256', required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == 'verify':
            now = _now(None)
            _, report = read_ledger(_read_private(args.ledger), expected_sha256=args.ledger_sha256,
                                    knowledge_as_of=now.isoformat(), clock=lambda: now)
        elif args.command == 'build':
            raw, report = build_ledger(args.database, _read_private(args.registry), _read_private(args.archive_manifest),
                expected_registry_sha256=args.registry_sha256, expected_manifest_sha256=args.archive_manifest_sha256,
                as_of_day=args.as_of_day)
        else:
            raw, report = merge_official(_read_private(args.ledger), _read_private(args.official),
                expected_ledger_sha256=args.ledger_sha256, expected_official_sha256=args.official_sha256)
        if args.command != 'verify':
            write_private(args.output_dir, raw, report['ledger_sha256'])
    except LedgerHold as error:
        print(json.dumps({'state': str(error)}))
        return 2
    except (ValueError, TypeError, OSError, KeyError, OverflowError, RecursionError, sqlite3.Error):
        print(json.dumps({'state': 'RIDER_HISTORY_LEDGER_INPUT_INVALID'}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
