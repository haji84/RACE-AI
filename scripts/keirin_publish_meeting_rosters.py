"""Publish checked Kdreams display rosters independently of forecast creation."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from subprocess import TimeoutExpired
from zoneinfo import ZoneInfo

from race_ai import keirin_dossier_race_context as context
from race_ai import keirin_github_provider_stop as stops
from race_ai import keirin_public_forecasts as public
from race_ai import keirin_public_meeting_roster as source
from scripts.keirin_capture_public_two_sources import SourceCaptureError
from scripts.keirin_daily_rider_update import BASE_SHA256
from scripts.keirin_publish_dossier_conditions import _commit

JST = ZoneInfo('Asia/Tokyo')
DIRECTORY_PATH = 'reference-starters/identity-directory.json'
DIRECTORY_SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_DISPLAY_IDENTITY_V1'
DIRECTORY_BASIS = 'VERIFIED_DIRECTORY_NAME_PREFECTURE'
RIDER_FIELDS = {'number','name','registration','region','style','cohort'}


def _need(condition, code):
    if not condition:
        raise ValueError('PUBLIC_MEETING_ROSTERS_' + code)


def _encode(doc):
    raw = public.canonical(doc) + b'\n'
    _need(len(raw) <= public.MAX_BYTES, 'SIZE')
    return raw


def directory_projection(raw):
    """Use only the independently staged official public directory with the exact pin."""
    _need(sha256(raw).hexdigest() == BASE_SHA256, 'DIRECTORY_SHA')
    directory = public._json(raw)
    _need(directory['schema'] == 'RACE_AI_KEIRIN_PUBLIC_RIDER_DIRECTORY_V1', 'DIRECTORY_SCHEMA')
    return dict(schema=DIRECTORY_SCHEMA, source_sha256=BASE_SHA256, as_of=directory['as_of'],
                riders=[{key:row[key] for key in ('name','region','registration')} for row in directory['riders']])


def directory_lookup(directory):
    _need(type(directory) is dict and set(directory) == {'schema','source_sha256','as_of','riders'} and
          directory['schema'] == DIRECTORY_SCHEMA and directory['source_sha256'] == BASE_SHA256 and
          type(directory['riders']) is list and 1 <= len(directory['riders']) <= 5000, 'DIRECTORY')
    context._day(directory['as_of'])
    identities, registrations = [], set()
    for row in directory['riders']:
        _need(type(row) is dict and set(row) == {'name','region','registration'}, 'DIRECTORY_ROW')
        name, region, registration = source._identity(source._published_text(row['name'],80),
            source._published_text(row['region'],32), row['registration'])
        _need(type(registration) is str and context.REGISTRATION.fullmatch(registration) and
              registration != '000000' and registration not in registrations, 'DIRECTORY_IDENTITY')
        registrations.add(registration)
        identities.append((name,region,registration))
    names = Counter(name for name,_,_ in identities)
    return {(name,region):registration for name,region,registration in identities if names[name] == 1}


def bind_directory(packet, lookup):
    races = []
    for row in packet['races']:
        riders = []
        reserved = {rider['registration'] for rider in row['riders'] if rider['registration']}
        candidates = {rider['number']:lookup.get(source._identity(rider['name'], rider['region'], rider['cohort'])[:2])
                      for rider in row['riders'] if rider['registration'] is None}
        counts = Counter(candidates.values())
        for rider in row['riders']:
            registration = candidates.get(rider['number'])
            if registration and counts[registration] == 1 and registration not in reserved:
                rider = dict(rider,registration=registration,registration_basis=DIRECTORY_BASIS)
            riders.append(rider)
        races.append(dict(row,riders=riders))
    return dict(packet,races=races)


def checked_packet(packet):
    _need(type(packet) is dict and set(packet) == {'schema','day','published_at','races'} and
          packet['schema'] == source.SCHEMA and type(packet['races']) is list and
          1 <= len(packet['races']) <= 300, 'PACKET')
    day, posted = context._day(packet['day']), context._aware(packet['published_at'])
    seen = set()
    for row in packet['races']:
        _need(type(row) is dict and set(row) == {'race_id','source_url','source_at','source_sha256','riders'} and
              context._race_day(row['race_id']) == day and row['race_id'] not in seen and
              type(row['source_url']) is str and row['source_url'].startswith(source.ORIGIN+'/') and
              type(row['source_sha256']) is str and context.SHA.fullmatch(row['source_sha256']) and
              context._aware(row['source_at']) <= posted and type(row['riders']) is list and
              1 <= len(row['riders']) <= 9, 'RACE')
        meeting = source._meeting_on_day(row['source_url'].removeprefix(source.ORIGIN),day)
        _need(meeting is not None and meeting[2] == row['race_id'][8:10], 'RACE_SOURCE')
        seen.add(row['race_id'])
        cars, registrations = set(), set()
        for rider in row['riders']:
            _need(type(rider) is dict and RIDER_FIELDS <= rider.keys() <= RIDER_FIELDS | {'registration_basis'} and
                  type(rider['number']) is int and 1 <= rider['number'] <= 9 and rider['number'] not in cars and
                  (rider['cohort'] is None or type(rider['cohort']) is int and 1 <= rider['cohort'] <= 998) and
                  rider['style'] in source.STYLES, 'RIDER')
            _need(rider['name'] == source._published_text(rider['name'],80) and
                  rider['region'] == source._published_text(rider['region'],32), 'RIDER_NAME')
            cars.add(rider['number'])
            registration = rider['registration']
            if registration is not None:
                _need(type(registration) is str and context.REGISTRATION.fullmatch(registration) and
                      registration != '000000' and registration not in registrations, 'RIDER_ID')
                registrations.add(registration)
            if 'registration_basis' in rider:
                _need(registration is not None and rider['registration_basis'] == DIRECTORY_BASIS, 'RIDER_BASIS')
    return packet


def _path(day):
    return f'reference-starters/{context._day(day)}.json'


def publish(store, packets, directory=None):
    checked = [checked_packet(packet) for packet in packets]
    _need(len({packet['day'] for packet in checked}) == len(checked), 'DUPLICATE_DAY')
    lookup = directory_lookup(directory) if directory else {}
    for attempt in range(2):
        parent = store.head()
        _need(bool(parent), 'PUBLIC_BRANCH')
        store.fetch(parent)
        files = {}
        if directory is not None:
            raw = _encode(directory)
            existing = store.read_previous(parent, DIRECTORY_PATH)
            _need(existing is None or existing == raw, 'DIRECTORY_CHANGED')
            if existing is None:
                files[DIRECTORY_PATH] = raw
        for packet in checked:
            path = _path(packet['day'])
            previous = store.read_previous(parent, path)
            if previous is not None:
                prior = checked_packet(public._json(previous))
                _need(prior['day'] == packet['day'] and context._aware(prior['published_at']) <=
                      context._aware(packet['published_at']), 'PUBLICATION_CLOCK')
            data = _encode(checked_packet(bind_directory(packet,lookup)))
            if previous != data:
                files[path] = data
        if not files:
            return parent
        try:
            return _commit(store,parent,files)
        except (ValueError,TimeoutExpired):
            if attempt or store.head() == parent:
                raise
    raise ValueError('PUBLIC_MEETING_ROSTERS_CONCURRENT')


def refresh(repo, day, *, now=None, collect=source.collect_day, store=None):
    """One meeting-list read per venue when existing today's published roster has gaps."""
    now = now or datetime.now(timezone.utc)
    _need(day == now.astimezone(JST).date().isoformat(), 'TODAY')
    store = store or public.PublicForecastGit(repo)
    head = store.head()
    _need(bool(head), 'PUBLIC_BRANCH')
    store.fetch(head)
    registry = store.read_previous(head, f'forecasts/{day}.json')
    directory = store.read_previous(head, DIRECTORY_PATH)
    if registry is None or directory is None:
        return {'state':'WAITING_FOR_PUBLISHED_REGISTRY', 'day':day}
    registered = {row['race_id'] for row in public.checked(public._json(registry))['races']}
    prior = store.read_previous(head, _path(day))
    if prior is not None:
        packet = checked_packet(public._json(prior))
        if registered <= {row['race_id'] for row in packet['races']}:
            return {'state':'ROSTERS_ALREADY_PUBLISHED', 'day':day, 'races':len(packet['races'])}
        if now - context._aware(packet['published_at']) < timedelta(hours=1):
            return {'state':'RECENT_PARTIAL_ROSTER', 'day':day, 'races':len(packet['races'])}
    if stops.read_for_observed_day(repo=repo, day=day) is not None:
        return {'state':'ROSTER_SOURCE_STOP', 'day':day}
    try:
        packet = collect(day)
    except SourceCaptureError as exc:
        code = str(exc) if str(exc) in stops.CODES else 'PUBLIC_PROVIDER_UNAVAILABLE_STOP'
        stops.record_denial(repo=repo, code=code, observed_at=datetime.now(timezone.utc).isoformat())
        return {'state':'ROSTER_SOURCE_STOP', 'day':day}
    revision = publish(store,[packet],public._json(directory))
    return {'state':'PUBLISHED_ROSTERS', 'day':day,'commit':revision,'races':len(packet['races'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--packet', action='append', type=Path)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--today', action='store_true')
    args = parser.parse_args()
    if args.today:
        _need(not args.packet and not args.directory, 'MODE')
        result = refresh(args.repo, datetime.now(JST).date().isoformat())
    else:
        _need(bool(args.packet) and args.directory is not None, 'PACKETS_REQUIRED')
        packets = [public._json(path.read_bytes()) for path in args.packet]
        directory = directory_projection(args.directory.read_bytes())
        revision = publish(public.PublicForecastGit(args.repo),packets,directory)
        result = dict(commit=revision,races={packet['day']:len(packet['races']) for packet in packets})
    print(json.dumps(result,sort_keys=True))


if __name__ == '__main__':
    main()
