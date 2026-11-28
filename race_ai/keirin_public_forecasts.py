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
RESEARCH_SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_RESULT_UNREAD_AB_V1'
REF = 'state/keirin-public-forecasts'
RIDER_ARCHIVE_PATH = 'rider-history/archive.json'
RIDER_ARCHIVE_MAX = 4 * 1024 * 1024
PATH = re.compile(r'(?:(?:forecasts|references|research|updates|details|odds|operations|starters|reference-starters|rider-history|rider-context|rider-context-secondary|rank-distributions|rider-conditions|rider-condition-results|rider-condition-archive|measurements|dt-r1)/'
                  r'20[0-9]{2}-[0-9]{2}-[0-9]{2}\.json|(?:rider-history|measurements)/latest\.json|rider-history/archive\.json|'
                  r'reference-starters/identity-directory\.json|measurements/(?:confidence|replay-confidence)-20[0-9]{2}-[0-9]{2}-[0-9]{2}\.json)')
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


def checked_research(body):
    need(type(body) is dict and set(body) == {'schema','day','published_at','races'} and
         body['schema'] == RESEARCH_SCHEMA, 'RESEARCH_SCHEMA')
    day = official._day(body['day'])
    posted = when(body['published_at'])
    races = body['races']
    need(type(races) is list and len(races) <= official.MAX_RACES, 'RESEARCH_RACES')
    for row in races:
        need(type(row) is dict and set(row) == {'race_id','cutoff_at','generated_at','starter_cars','a','b'},
             'RESEARCH_ROW')
        cutoff, generated = when(row['cutoff_at']), when(row['generated_at'])
        need(cutoff.astimezone(official.JST).date().isoformat() == day and generated <= posted, 'RESEARCH_CLOCK')
        cars = row['starter_cars']
        need(type(cars) is list and 5 <= len(cars) <= 9 and
             all(type(c) is int and 1 <= c <= 9 for c in cars) and cars == sorted(set(cars)), 'RESEARCH_STARTER_ROSTER')
        need((row['a'] or row['b']) and all(arm == [] or (_tickets(arm) and
             all(set(ticket) <= set(cars) for ticket in arm)) for arm in (row['a'], row['b'])), 'RESEARCH_TICKETS')
    official._ids([row['race_id'] for row in races], day)
    return body


def project_research_race(snapshot, scheduled, *, generated_at):
    """Use scoped racecard features and the independently observed starter set."""
    need(isinstance(generated_at, datetime) and generated_at.utcoffset() is not None, 'RESEARCH_CLOCK')
    need(type(snapshot) is dict and set(snapshot) == {'race_id','competition','line_groups','line_warnings','riders'} and
         snapshot['race_id'] == scheduled['race_id'] and snapshot['competition'] in model.CLASSES and
         type(snapshot['riders']) is list, 'RESULT_UNREAD_INPUT')
    fields = {'car','name','competition_points','mark_rank','style'}
    need(all(type(rider) is dict and set(rider) == fields for rider in snapshot['riders']), 'RESULT_UNREAD_INPUT')
    cars = sorted(rider['car'] for rider in snapshot['riders'])
    need(cars == sorted(rider['car'] for rider in scheduled['starters']) and
         5 <= len(cars) <= 9 and len(set(cars)) == len(cars), 'RESEARCH_STARTER_ROSTER')
    at = generated_at.isoformat()
    need(when(scheduled['source_observed_at']) <= when(at), 'RESEARCH_CLOCK')
    cutoff = scheduled['official_cutoff_at']
    need(cutoff is not None, 'RESEARCH_CUTOFF_UNKNOWN')
    forecast = model.generate_evidence_analysis(snapshot)
    a, b = (forecast[arm]['ranked_tickets'][:LIMIT] for arm in ('A','B'))
    need(a or b, 'RESEARCH_NO_SEPARATED_TICKETS')
    return dict(race_id=scheduled['race_id'], cutoff_at=cutoff, generated_at=at, starter_cars=cars, a=a, b=b)


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
        limit = 8 * 1024 * 1024 if path.startswith(('rider-conditions/', 'rider-condition-archive/')) else MAX_BYTES
        if path == RIDER_ARCHIVE_PATH:
            limit = RIDER_ARCHIVE_MAX
        need(0 < size <= limit, 'BLOB_SIZE')
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


def _previous_candidates(store, head, path, day, check):
    if head is None:
        return None
    store.fetch(head)
    raw = store.read_previous(head,path)
    if raw is None:
        return None
    prior = check(_json(raw))
    need(prior['day'] == day, 'PREVIOUS_DAY')
    return prior


def _candidates_receipt(state, body, commit):
    return dict(state=state, day_jst=body['day'], published_races=len(body['races']),
                published_at=body['published_at'], commit=commit)


def publish_reference(repo, body, *, store=None):
    """Append newly observed race IDs while retaining the first public candidates."""
    return _append_candidates(repo, checked_reference(body), 'references', checked_reference,
                              'PUBLIC_REFERENCE_FORECASTS', store)


def publish_research(repo, body, *, store=None):
    """Publish distinct result-unread candidates for registered gaps."""
    return _append_candidates(repo, checked_research(body), 'research', checked_research,
                              'PUBLIC_RESULT_UNREAD_FORECASTS', store)


def _append_candidates(repo, body, lane, check, state, store):
    if not body['races']:
        return _candidates_receipt(state+'_NO_ELIGIBLE_RACES', body, None)
    store = store or PublicForecastGit(repo)
    day = body['day']
    path = f'{lane}/{day}.json'
    parent = store.head()
    previous = _previous_candidates(store, parent, path, day, check)
    posted = when(body['published_at'])
    for attempt in range(2):
        prior = {row['race_id']:row for row in previous['races']} if previous else {}
        additions = {row['race_id']:row for row in body['races'] if row['race_id'] not in prior}
        if lane == 'research':
            registry_bytes = store.read_previous(parent, f'forecasts/{day}.json') if parent else None
            need(registry_bytes is not None, 'RESEARCH_REGISTRY_REQUIRED')
            registry = checked(_json(registry_bytes))
            registered = {row['race_id']:row for row in registry['races']}
            need(registry['day'] == day and (prior.keys() | additions.keys()) <= registered.keys(),
                 'RESEARCH_UNREGISTERED_RACE')
            reference_bytes = store.read_previous(parent, f'references/{day}.json')
            reference = checked_reference(_json(reference_bytes)) if reference_bytes else None
            need(reference is None or reference['day'] == day, 'PREVIOUS_DAY')
            backed = {row['race_id'] for row in reference['races']} if reference else set()
            additions = {rid:row for rid,row in additions.items() if rid not in backed and
                         registered[rid]['status'] == 'pending'}
        else:
            need(all(posted < when(row['cutoff_at']) for row in additions.values()), 'REFERENCE_READBACK_AFTER_CUTOFF')
        if not additions:
            return (_candidates_receipt(state+'_CURRENT', previous, parent) if previous else
                    _candidates_receipt(state+'_NO_ELIGIBLE_RACES', dict(body, races=[]), parent))
        by_race = {**prior, **additions}
        publication_at = body['published_at']
        if previous is not None and when(previous['published_at']) > posted:
            publication_at = previous['published_at']
        merged = check(dict(body, published_at=publication_at,
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
            previous = _previous_candidates(store, latest, path, day, check)
            pushed = code == 'KEIRIN_NOTE_FEED_REMOTE_READBACK'
            ancestor = commit if pushed else parent
            if ancestor is not None:
                store.run(['merge-base','--is-ancestor',ancestor,latest])
            required = by_race if pushed else prior
            retained = {row['race_id']:row for row in previous['races']} if previous else {}
            need(all(retained.get(rid) == row for rid,row in required.items()), 'REFERENCE_HISTORY_CHANGED')
            parent = latest
        else:
            return _candidates_receipt(state+'_UPDATED', merged, commit)


def _receipt(state, body, commit):
    return dict(state=state, day_jst=body['day'], published_races=sum(row['status']=='saved' for row in body['races']),
                registered_races=len(body['races']), published_at=body['published_at'], commit=commit)
