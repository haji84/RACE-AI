"""Inspect and update public race forecast cards from an authorized repository chat."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import re
from unicodedata import normalize

from race_ai import keirin_official_public_source as official
from race_ai import keirin_public_forecasts as public
from race_ai import keirin_public_forecast_updates as updates
from race_ai.keirin_nationwide_auto_generator import VENUE
from scripts.keirin_capture_public_two_sources import MAX_BYTES, private_dir
from scripts.keirin_note_collect_inputs import _read
from scripts.keirin_official_day_pipeline import restore_private_snapshot_json
from scripts.keirin_publish_result_unread import _source


def tickets(text):
    value = normalize('NFKC', text).translate(str.maketrans({'→':'-', '−':'-', '、':','}))
    parts = re.split(r'[,\s]+', re.sub(r'\s*-\s*', '-', value.strip()))
    public.need(all(re.fullmatch(r'[1-9]-[1-9]-[1-9]', part) for part in parts), 'UPDATE_TICKET_FORMAT')
    return [[int(car) for car in part.split('-')] for part in parts]


def _day_id(race_id):
    public.need(type(race_id) is str and VENUE.fullmatch(race_id) and 1 <= int(race_id[-2:]) <= 12,
                'UPDATE_RACE_ID')
    return f'{race_id[:4]}-{race_id[4:6]}-{race_id[6:8]}'


def _find(document, race_id):
    return next((row for row in (document or {}).get('races', []) if row['race_id'] == race_id), None)


def _schedule(path, day):
    doc = restore_private_snapshot_json(public._json(_read(path, MAX_BYTES)))
    public.need(doc.get('day_jst') == day and official.reparse_day_schedule(doc), 'UPDATE_OFFICIAL_SCHEDULE')
    return {row['race_id']:row for row in doc['races']}


def _roster(race_id, state, schedule):
    row = _find(state['forecasts'], race_id)
    public.need(row is not None, 'UPDATE_UNREGISTERED_RACE')
    if schedule is not None:
        confirmed = schedule.get(race_id)
        public.need(confirmed is not None and confirmed['official_cutoff_at'] is not None, 'UPDATE_STARTERS_REQUIRED')
        return confirmed['official_cutoff_at'], sorted(rider['car'] for rider in confirmed['starters'])
    confirmed = _find(state['research'], race_id) or _find(state['updates'], race_id)
    public.need(confirmed is not None, 'UPDATE_STARTERS_REQUIRE_OFFICIAL_SCHEDULE')
    return confirmed['cutoff_at'], confirmed['starter_cars']


def _body(day, rows, at):
    return updates.checked(dict(schema=updates.SCHEMA, day=day, published_at=at, races=rows))


def _contested_rows(day, race_ids, state, schedule, root, now):
    from race_ai.keirin_result_unread_racecard import contested_hypotheses_from_card

    public.need(schedule is not None and all(_day_id(rid) == day for rid in race_ids), 'UPDATE_OFFICIAL_SCHEDULE')
    folder = private_dir(root)
    captured = public._json(_read(folder/'cards-observed.json', public.MAX_BYTES))
    net_path = folder/'net-observed.json'
    secondary = public._json(_read(net_path, public.MAX_BYTES)) if net_path.exists() else []
    primary = {row['race_id']:row['kdreams_receipt'] for row in captured}
    net = {row['race_id']:row['netkeirin_receipt'] for row in secondary}
    public.need(len(primary) == len(captured) and len(net) == len(secondary) and
                set(race_ids) <= primary.keys(), 'UPDATE_CAPTURE_RECEIPTS')
    output = []
    for race_id in race_ids:
        cutoff, cars = _roster(race_id, state, schedule)
        kdreams_raw, kdreams_url = _source(folder, primary[race_id], generated_at=now)
        net_raw, net_url = (_source(folder, net[race_id], generated_at=now)
                            if race_id in net else (None, None))
        cases = contested_hypotheses_from_card(race_id=race_id, kdreams_raw=kdreams_raw, kdreams_url=kdreams_url,
                                               netkeirin_raw=net_raw, netkeirin_url=net_url)
        public.need(all(sorted(car for group in case['line_groups'] for car in group) == cars for case in cases),
                    'UPDATE_CONTEST_ROSTER_MISMATCH')
        b = dict(kind='contested_lineup', registered_at=now.isoformat(), hypotheses=[
            dict(cars=case['cars'], tickets=case['tickets']['3t'][:public.LIMIT]) for case in cases])
        output.append(dict(race_id=race_id, cutoff_at=cutoff, starter_cars=cars, a=None, b=b))
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    inspect = commands.add_parser('inspect')
    inspect.add_argument('--race-id', required=True)
    register = commands.add_parser('register')
    register.add_argument('--race-id', required=True)
    register.add_argument('--schedule', type=Path)
    register.add_argument('--a', type=tickets)
    register.add_argument('--b', type=tickets)
    register.add_argument('--publish', action='store_true')
    contested = commands.add_parser('contested')
    contested.add_argument('--race-id', action='append', required=True)
    contested.add_argument('--schedule', required=True, type=Path)
    contested.add_argument('--capture-dir', required=True, type=Path)
    contested.add_argument('--publish', action='store_true')
    args = parser.parse_args(argv)

    race_ids = args.race_id if args.command == 'contested' else [args.race_id]
    day = _day_id(race_ids[0])
    store = public.PublicForecastGit(args.repo)
    head, state = updates.day_state(store, day)
    if args.command == 'inspect':
        race = {kind:_find(doc, race_ids[0]) for kind,doc in state.items()}
        public.need(race['forecasts'] is not None, 'UPDATE_UNREGISTERED_RACE')
        print(json.dumps(dict(commit=head, **race), ensure_ascii=False))
        return

    now = datetime.now(timezone.utc)
    schedule = _schedule(args.schedule, day) if args.schedule is not None else None
    if args.command == 'register':
        cutoff, cars = _roster(race_ids[0], state, schedule)
        selections = {name:dict(kind='chat', registered_at=now.isoformat(), tickets=values) if values else None
                      for name,values in [('a',args.a),('b',args.b)]}
        rows = [dict(race_id=race_ids[0], cutoff_at=cutoff, starter_cars=cars, **selections)]
    else:
        rows = _contested_rows(day, race_ids, state, schedule, args.capture_dir, now)
    body = _body(day, rows, datetime.now(timezone.utc).isoformat())
    if args.publish:
        report = updates.publish(args.repo, body, store=store, expected_head=head)
    else:
        report = dict(state='PUBLIC_FORECAST_UPDATE_PREVIEW', head=head, update=body)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
