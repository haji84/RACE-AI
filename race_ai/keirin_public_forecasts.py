"""Publish the public A/B shortlist without exporting an owner forecast original."""
from datetime import date, datetime
import json
import re

from . import keirin_nationwide_forecast_view as official
from . import keirin_note_feed as feed
from .keirin_nationwide_auto_generator import when
from .keirin_note_view import canonical

SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_FORECASTS_V1'
REF = 'state/keirin-public-forecasts'
PATH = re.compile(r'forecasts/20[0-9]{2}-[0-9]{2}-[0-9]{2}\.json')
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
    raw = canonical(checked(body))+b'\n'
    need(len(raw) <= MAX_BYTES, 'BLOB_SIZE')
    commit = store.commit({path:raw},parent)
    comparison = [parent,commit] if parent else ['--root',commit]
    need(store.run(['diff-tree','--no-commit-id','--name-only','-r',*comparison]).decode().splitlines() == [path],
         'ONLY_PUBLIC_FORECAST_PATH')
    store.push(commit,parent)
    need(store.read_previous(commit,path) == raw, 'PUBLICATION_READBACK')
    return _receipt('PUBLIC_FORECASTS_UPDATED',body,commit)


def _receipt(state, body, commit):
    return dict(state=state, day_jst=body['day'], published_races=sum(row['status']=='saved' for row in body['races']),
                registered_races=len(body['races']), published_at=body['published_at'], commit=commit)
