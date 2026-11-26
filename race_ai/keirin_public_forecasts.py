"""Publish the public A/B shortlist without exporting an owner forecast original."""
from datetime import date, datetime
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re

from . import keirin_confidence as confidence
from . import keirin_nationwide_auto_generator as model
from . import keirin_nationwide_forecast_view as official
from . import keirin_note_feed as feed
from .keirin_nationwide_auto_generator import when
from .keirin_note_view import MAX_FILE, SCHEMA as NOTE_SCHEMA, _pairs, canonical

SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_FORECASTS_V1'
REFERENCE_SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_REFERENCE_FORECASTS_V1'
REF = 'state/keirin-public-forecasts'
PATH = re.compile(r'(?:forecasts|references)/20[0-9]{2}-[0-9]{2}-[0-9]{2}\.json')
LIMIT = 8
MAX_BYTES = 512 * 1024


def need(ok, code):
    if not ok:
        raise ValueError('KEIRIN_PUBLIC_' + code)


def _tickets(values):
    return (type(values) is list and 1 <= len(values) <= LIMIT and all(
        type(ticket) is list and len(ticket) == 3 and
        all(type(car) is int and 1 <= car <= 9 for car in ticket) and len(set(ticket)) == 3
        for ticket in values) and len({tuple(ticket) for ticket in values}) == len(values))


def checked(body):
    need(type(body) is dict and set(body) == {'schema','day','published_at','races'} and
         body['schema'] == SCHEMA, 'SCHEMA')
    day = body['day']
    need(type(day) is str and re.fullmatch(r'20[0-9]{2}-[0-9]{2}-[0-9]{2}', day) and
         date.fromisoformat(day).isoformat() == day, 'DAY')
    posted = when(body['published_at'])
    races = body['races']
    need(type(races) is list and 1 <= len(races) <= official.MAX_RACES, 'RACES')
    seen = set()
    for row in races:
        need(type(row) is dict and set(row) == {'race_id','cutoff_at','status','saved_at','a','b'}, 'ROW')
        rid = row['race_id']
        need(type(rid) is str and re.fullmatch(day.replace('-','') + r'[0-9]{4}', rid) and
             1 <= int(rid[-2:]) <= 12 and rid not in seen, 'RACE_ID')
        seen.add(rid)
        cutoff = when(row['cutoff_at']) if row['cutoff_at'] is not None else None
        if row['status'] == 'saved':
            saved = when(row['saved_at'])
            need(cutoff is not None and saved < cutoff and saved <= posted and
                 _tickets(row['a']) and _tickets(row['b']), 'SAVED_RACE')
        else:
            need(row['status'] == 'pending' and row['saved_at'] is None and
                 row['a'] == row['b'] == [], 'PENDING_RACE')
    return body


def project(doc, *, published_at):
    """Select only approved display fields from the full, independently admitted day."""
    official.checked_day(doc)
    need(doc['registry_available'] and doc['races'], 'REGISTERED_DAY_REQUIRED')
    need(isinstance(published_at, datetime) and published_at.utcoffset() is not None, 'PUBLICATION_CLOCK')
    races = []
    for row in sorted(doc['races'], key=lambda r:r['race_id']):
        original = row['original']
        saved = original is not None
        baseline = original['baseline'] if saved else None
        races.append(dict(race_id=row['race_id'], cutoff_at=row['cutoff_at'],
            status='saved' if saved else 'pending', saved_at=original['baseline_sealed_at'] if saved else None,
            a=[ticket.copy() for ticket in baseline['A']['ranked_tickets'][:LIMIT]] if saved else [],
            b=[ticket.copy() for ticket in baseline['B']['ranked_tickets'][:LIMIT]] if saved else []))
    return checked(dict(schema=SCHEMA, day=doc['day_jst'], published_at=published_at.isoformat(), races=races))


def _finite_float(text):
    value = float(text)
    need(isfinite(value), 'NONFINITE_JSON')
    return value


def _json(raw):
    return json.loads(raw, object_pairs_hook=_pairs, parse_float=_finite_float, parse_constant=_finite_float)


def checked_reference(body):
    need(type(body) is dict and set(body) == {'schema','day','published_at','races'} and
         body['schema'] == REFERENCE_SCHEMA, 'REFERENCE_SCHEMA')
    day = official._day(body['day'])
    posted = when(body['published_at'])
    races = body['races']
    need(type(races) is list and len(races) <= official.MAX_RACES, 'REFERENCE_RACES')
    for row in races:
        need(type(row) is dict and set(row) == {'race_id','cutoff_at','saved_at','a','b'} and
             type(row['race_id']) is str, 'REFERENCE_ROW')
        cutoff, saved = when(row['cutoff_at']), when(row['saved_at'])
        need(cutoff.astimezone(official.JST).date().isoformat() == day and
             saved < cutoff and saved <= posted and _tickets(row['a']) and _tickets(row['b']),
             'REFERENCE_RACE')
    official._ids([row['race_id'] for row in races], day)
    return body


def _captured_references(note, day, ids):
    path = f'data/{day}/reference_AB.json'
    need(type(note.get('files')) is dict and path in note['files'], 'REFERENCE_FILE')
    file = note['files'][path]
    need(type(file) is dict and set(file) == {'text','bytes','sha256'} and
         type(file['text']) is str and type(file['bytes']) is int, 'REFERENCE_FILE')
    raw = file['text'].encode('utf-8')
    need(0 < len(raw) == file['bytes'] <= MAX_FILE and sha256(raw).hexdigest() == file['sha256'],
         'REFERENCE_FILE_SHA')
    rows = _json(raw)
    need(type(rows) is list and len(rows) == len(ids), 'REFERENCE_CAPTURED_IDS')
    captured = []
    for row in rows:
        need(type(row) is dict and type(row.get('input')) is dict and
             type(row['input'].get('race_id')) is str, 'REFERENCE_INPUT')
        captured.append(row['input']['race_id'])
    need(sorted(official._ids(captured, day)) == sorted(ids), 'REFERENCE_CAPTURED_IDS')
    return rows


def project_reference(note, entry, *, published_at):
    """Reduce a fresh research Note after its encrypted Git readback."""
    need(isinstance(published_at, datetime) and published_at.utcoffset() is not None, 'PUBLICATION_CLOCK')
    feed.checked_entry(entry)
    need(entry['kind'] == 'research' and len(entry['days']) == 1, 'REFERENCE_ENTRY')
    day = official._day(entry['days'][0])
    need(type(note) is dict and note.get('schema') == NOTE_SCHEMA and note.get('dates') == [day] and
         note.get('scope') == 'OWNER_MATCHED_SOURCE_RESEARCH_REFRESH' and note.get('source_site') is None and
         note.get('source_profile') == 'owner-imported-kdreams-netkeirin-20261120' and
         note.get('original_files_preserved') is True and
         all(note.get(field) is False for field in ('formal_model_admission', 'production_weight_switch',
             'actual_four_model_forecast_saved', 'wagers_placed')), 'REFERENCE_NOTE')
    commit = note.get('source_commit')
    need(type(commit) is str and re.fullmatch('[0-9a-f]{40}', commit) and
         sha256(canonical(note)).hexdigest() == entry['source_content_sha256'], 'REFERENCE_NOTE_BINDING')
    imported, saved = when(note['imported_at']), when(entry['created_at'])
    posted = when(published_at.isoformat())
    need(imported <= saved <= posted, 'REFERENCE_READBACK_CLOCK')
    ids = official._ids(entry['captured_race_ids'], day)
    references = _captured_references(note, day, ids)
    model_sha = sha256(Path(model.__file__).read_bytes()).hexdigest()
    races = []
    for row in references:
        need(row.get('status') == 'OWNER_RESEARCH_REFERENCE_NOT_FORMAL_SEALED_ORIGINAL' and
             row.get('independent_runner_readback') is False and row.get('model_source_commit') == commit and
             row.get('model_source_sha256') == model_sha, 'REFERENCE_MODEL_PROVENANCE')
        snapshot, baseline, assessment = row['input'], row['output'], row['confidence_assessment']
        confidence.checked_assessment(assessment, snapshot=snapshot, baseline=baseline)
        cutoff = when(snapshot['published_cutoff_at'])
        need(cutoff.astimezone(official.JST).date().isoformat() == day and
             when(assessment['assessed_at']) <= imported, 'REFERENCE_CAPTURE_CLOCK')
        if posted >= cutoff:
            continue
        cars = {rider['car'] for rider in snapshot['riders']}
        a, b = (official._tickets(baseline[name], cars)[:LIMIT] for name in ('A','B'))
        races.append(dict(race_id=snapshot['race_id'], cutoff_at=snapshot['published_cutoff_at'],
                          saved_at=entry['created_at'], a=[list(ticket) for ticket in a],
                          b=[list(ticket) for ticket in b]))
    return checked_reference(dict(schema=REFERENCE_SCHEMA, day=day, published_at=published_at.isoformat(),
        races=sorted(races, key=lambda row:row['race_id'])))


class PublicForecastGit(feed.NoteFeedGit):
    """Same canonical remote and compare-and-swap writer as the existing display."""
    ref = REF
    commit_message = b'Update public KEIRIN forecast shortlist\n'

    def read_previous(self, head, path):
        need(PATH.fullmatch(path), 'PATH')
        entry = self.run(['ls-tree','-r','--format=%(objectmode)',head,'--',path])
        if not entry:
            return None
        need(entry == b'100644\n', 'BLOB_MODE')
        size = int(self.run(['cat-file','-s',head+':'+path]))
        need(0 < size <= MAX_BYTES, 'BLOB_SIZE')
        raw = self.run(['show',head+':'+path])
        need(len(raw) == size, 'BLOB_READ')
        return raw


def publish(repo, body, *, store=None):
    """Update only this day's public projection; saved public rows are immutable."""
    checked(body)
    store = store or PublicForecastGit(repo)
    parent = store.head()
    path = 'forecasts/'+body['day']+'.json'
    previous_bytes = None
    if parent is not None:
        store.fetch(parent)
        previous_bytes = store.read_previous(parent,path)
    if previous_bytes is not None:
        previous = checked(json.loads(previous_bytes))
        need(previous['day'] == body['day'], 'PREVIOUS_DAY')
        by_race = {row['race_id']:row for row in body['races']}
        for row in previous['races']:
            rid = row['race_id']
            need(rid in by_race, 'REGISTERED_RACES_SHRANK')
            if row['status'] != 'saved':
                continue
            if by_race[rid]['status'] == 'pending':
                by_race[rid] = row
            else:
                need(by_race[rid] == row, 'SAVED_PUBLIC_FORECAST_CHANGED')
        body = dict(body,races=[by_race[r['race_id']] for r in body['races']])
        if previous['races'] == body['races']:
            return _receipt('PUBLIC_FORECASTS_CURRENT',previous,parent)
        need(when(previous['published_at']) <= when(body['published_at']), 'PUBLICATION_CLOCK_BACKWARDS')
    commit, raw = _commit_projection(store, parent, path, checked(body))
    _push_projection(store, parent, path, commit, raw)
    return _receipt('PUBLIC_FORECASTS_UPDATED',body,commit)


def _commit_projection(store, parent, path, body):
    raw = canonical(body)+b'\n'
    need(len(raw) <= MAX_BYTES, 'BLOB_SIZE')
    commit = store.commit({path:raw},parent)
    comparison = [parent,commit] if parent else ['--root',commit]
    need(store.run(['diff-tree','--no-commit-id','--name-only','-r',*comparison]).decode().splitlines() == [path],
         'ONLY_PUBLIC_FORECAST_PATH')
    return commit, raw


def _push_projection(store, parent, path, commit, raw):
    store.push(commit,parent)
    need(store.read_previous(commit,path) == raw, 'PUBLICATION_READBACK')


def _previous_reference(store, head, path, day):
    if head is None:
        return None
    store.fetch(head)
    raw = store.read_previous(head,path)
    if raw is None:
        return None
    prior = checked_reference(_json(raw))
    need(prior['day'] == day, 'PREVIOUS_DAY')
    return prior


def _reference_receipt(state, body, commit):
    return dict(state=state, day_jst=body['day'], published_races=len(body['races']),
                published_at=body['published_at'], commit=commit)


def publish_reference(repo, body, *, store=None):
    """Append newly observed race IDs while retaining the first public candidates."""
    checked_reference(body)
    if not body['races']:
        return _reference_receipt('PUBLIC_REFERENCE_FORECASTS_NO_ELIGIBLE_RACES', body, None)
    store = store or PublicForecastGit(repo)
    day = body['day']
    path = f'references/{day}.json'
    parent = store.head()
    previous = _previous_reference(store, parent, path, day)
    posted = when(body['published_at'])
    for attempt in range(2):
        prior = {row['race_id']:row for row in previous['races']} if previous else {}
        additions = {row['race_id']:row for row in body['races'] if row['race_id'] not in prior}
        if not additions:
            return _reference_receipt('PUBLIC_REFERENCE_FORECASTS_CURRENT', previous, parent)
        need(all(posted < when(row['cutoff_at']) for row in additions.values()), 'REFERENCE_READBACK_AFTER_CUTOFF')
        by_race = {**prior, **additions}
        publication_at = body['published_at']
        if previous is not None and when(previous['published_at']) > posted:
            publication_at = previous['published_at']
        merged = checked_reference(dict(body, published_at=publication_at,
            races=[by_race[rid] for rid in sorted(by_race)]))
        commit, raw = _commit_projection(store, parent, path, merged)
        try:
            _push_projection(store, parent, path, commit, raw)
        except ValueError as error:
            code = str(error)
            if attempt or code not in ('KEIRIN_NOTE_FEED_CONCURRENT_UPDATE', 'KEIRIN_NOTE_FEED_REMOTE_READBACK'):
                raise
            latest = store.head()
            if latest is None or latest == parent:
                raise
            previous = _previous_reference(store, latest, path, day)
            pushed = code == 'KEIRIN_NOTE_FEED_REMOTE_READBACK'
            ancestor = commit if pushed else parent
            if ancestor is not None:
                store.run(['merge-base','--is-ancestor',ancestor,latest])
            required = by_race if pushed else prior
            retained = {row['race_id']:row for row in previous['races']} if previous else {}
            need(all(retained.get(rid) == row for rid,row in required.items()), 'REFERENCE_HISTORY_CHANGED')
            parent = latest
        else:
            return _reference_receipt('PUBLIC_REFERENCE_FORECASTS_UPDATED', merged, commit)


def _receipt(state, body, commit):
    return dict(state=state, day_jst=body['day'], published_races=sum(row['status']=='saved' for row in body['races']),
                registered_races=len(body['races']), published_at=body['published_at'], commit=commit)
