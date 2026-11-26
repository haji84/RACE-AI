"""Publish timestamped quotes for actual public forecast candidates."""
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import re

from race_ai import keirin_public_forecast_odds as odds
from race_ai import keirin_public_forecast_updates as updates
from race_ai import keirin_public_forecasts as public
from race_ai.keirin_nationwide_auto_generator import when
from scripts.keirin_capture_public_two_sources import MAX_BYTES, _write_once, private_dir
from scripts.keirin_note_collect_inputs import _read
from scripts.keirin_official_day_pipeline import restore_private_snapshot_json
from scripts.keirin_publish_result_unread import _source
from race_ai.keirin_official_public_source import reparse_day_schedule


HANDOFF_SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_ODDS_HANDOFF_V1'
HANDOFF_FILE = 'admitted-cards.json'


def _displayed_tickets(state):
    displayed = {}
    for lane in ('forecasts','references','research','updates'):
        for row in (state[lane] or {}).get('races', []):
            keys = displayed.setdefault(row['race_id'], set())
            for name in ('a','b'):
                arm = row[name]
                if type(arm) is dict:
                    tickets = arm.get('tickets') or [ticket for case in arm.get('hypotheses', [])
                                                     for ticket in case['tickets']]
                else:
                    tickets = arm or []
                keys.update('-'.join(map(str,ticket)) for ticket in tickets)
    return displayed


def _starter_cars(cars):
    return (type(cars) is list and 5 <= len(cars) <= 9 and
            all(type(car) is int and 1 <= car <= 9 for car in cars) and cars == sorted(set(cars)))


def _reason(error):
    reason = str(error)
    return reason if re.fullmatch('[A-Z_0-9]{1,100}', reason) else 'ODDS_SOURCE_INVALID'


def stage_reference_handoff(source, note, entry, target):
    """Copy only already captured Kdreams bytes from the encrypted-readback stage."""
    source, target = private_dir(source), private_dir(target)
    day, = entry['days']
    saved = when(entry['created_at'])
    public.need(entry['kind'] == 'research' and note['dates'] == [day] and
                sha256(public.canonical(note)).hexdigest() == entry['source_content_sha256'], 'ODDS_NOTE_BINDING')
    references = public._captured_references(note, day, entry['captured_race_ids'])
    manifest = public._json(note['files'][f'data/{day}/manifest.json']['text'])
    links, observations = manifest['source_manifest']['races'], manifest['source_receipts']
    urls = {row['race_id']: row['kdreams_url'] for row in links}
    receipts = {row['url']: row for row in observations}
    public.need(len(urls) == len(links) and len(receipts) == len(observations),'ODDS_ADMITTED_RECEIPT_DUPLICATE')
    public.need(not any(target.iterdir()), 'ODDS_PRIVATE_HANDOFF_ALREADY_PRESENT')
    raw_dir = target / 'raw'
    raw_dir.mkdir(mode=0o700)
    cards, issues = [], Counter()
    for row in references:
        try:
            snap = row['input']
            rid = snap['race_id']
            captured = snap['cutoff_source']
            receipt = receipts[urls[rid]]
            public.need(all(captured[field] == receipt[field] for field in ('url','bytes_sha256','captured_at')) and
                        when(receipt['captured_at']) < when(snap['published_cutoff_at']), 'ODDS_ADMITTED_RECEIPT')
            cars = sorted(rider['car'] for rider in snap['riders'])
            public.need(_starter_cars(cars), 'ODDS_STARTER_ROSTER')
            raw, url = _source(source, receipt, generated_at=saved)
            odds._source_url(rid, url)
            _write_once(raw_dir/(receipt['bytes_sha256']+'.html'), raw)
            cards.append(dict(race_id=rid, starter_cars=cars, kdreams_receipt=receipt))
        except (ValueError, KeyError, TypeError, OSError) as error:
            issues[_reason(error)] += 1
    if cards:
        payload = dict(schema=HANDOFF_SCHEMA, day=day, races=cards)
        _write_once(target/HANDOFF_FILE, public.canonical(payload)+b'\n')
    return dict(state='PUBLIC_ODDS_HANDOFF_STAGED' if cards else 'HOLD_PUBLIC_ODDS_HANDOFF',
                staged_races=len(cards), held=dict(issues))


def _quote_rows(day, registry, cards, tickets, *, now, issues):
    quotes = []
    for rid,(root,receipt,starters) in sorted(cards.items()):
        if not tickets.get(rid):
            continue
        try:
            html,url = _source(root,receipt,generated_at=now)
            row = odds.parse_racecard(html,race_id=rid,url=url,starters=starters,
                                      observed_at=receipt['captured_at'],wanted=tickets[rid])
            if row['quotes']:
                quotes.append(row)
            else:
                issues['NO_NUMERIC_MARKET_QUOTE'] += 1
        except (ValueError,KeyError,TypeError,OSError) as error:
            issues[_reason(error)] += 1
    body = odds.checked(dict(schema=odds.SCHEMA,day=day,published_at=now.isoformat(),races=quotes)) if quotes else None
    summary = dict(registered=len(registry), source_cards=len(cards), races_with_odds=len(quotes),
                   quotes=sum(len(row['quotes']) for row in quotes), held=dict(issues))
    return body,summary


def _read_handoff(target):
    root = private_dir(target)
    payload = public._json(_read(root/HANDOFF_FILE, public.MAX_BYTES))
    public.need(type(payload) is dict and set(payload) == {'schema','day','races'} and
                payload['schema'] == HANDOFF_SCHEMA, 'ODDS_HANDOFF_SCHEMA')
    day = odds.nationwide._day(payload['day'])
    public.need(type(payload['races']) is list and 0 < len(payload['races']) <= odds.nationwide.MAX_RACES,
                'ODDS_HANDOFF_RACES')
    for row in payload['races']:
        public.need(type(row) is dict and set(row) == {'race_id','starter_cars','kdreams_receipt'} and
                    _starter_cars(row['starter_cars']), 'ODDS_HANDOFF_ROW')
    odds.nationwide._ids([row['race_id'] for row in payload['races']], day)
    return root,payload


def prepare_handoff(target, state, *, now):
    """Use admitted same-runner cards and quotes for independently published tickets."""
    root,payload = _read_handoff(target)
    day = payload['day']
    public.need(state['forecasts']['day'] == day, 'ODDS_HANDOFF_DAY_MISMATCH')
    registry = {row['race_id'] for row in state['forecasts']['races']}
    rosters = {}
    for lane in ('research','updates'):
        for row in (state[lane] or {}).get('races', []):
            rosters.setdefault(row['race_id'], []).append(row['starter_cars'])
    cards, issues = {}, Counter()
    for row in payload['races']:
        rid, cars = row['race_id'], row['starter_cars']
        if rid not in registry:
            issues['ODDS_NOT_IN_PUBLIC_REGISTRY'] += 1
        elif any(published != cars for published in rosters.get(rid, [])):
            issues['ODDS_PUBLISHED_STARTER_MISMATCH'] += 1
        else:
            cards[rid] = (root,row['kdreams_receipt'],cars)
    return _quote_rows(day,registry,cards,_displayed_tickets(state),now=now,issues=issues)


def prepare(schedule, captures, state, *, now):
    public.need(reparse_day_schedule(schedule), 'ODDS_OFFICIAL_SCHEDULE')
    day = schedule['day_jst']
    roster = {row['race_id']:[p['car'] for p in row['starters']] for row in schedule['races']}
    registry = {row['race_id'] for row in state['forecasts']['races']}
    cards = {}
    for capture in captures:
        root = private_dir(capture)
        rows = public._json(_read(root/'cards-observed.json',public.MAX_BYTES))
        public.need(type(rows) is list, 'ODDS_CAPTURE_ROWS')
        for row in rows:
            rid = row['race_id']
            public.need(rid in registry and rid in roster and rid not in cards, 'ODDS_CAPTURE_ID')
            cards[rid] = (root,row['kdreams_receipt'],roster[rid])
    body,summary = _quote_rows(day,registry,cards,_displayed_tickets(state),now=now,issues=Counter())
    public.need(body is not None, 'ODDS_RACES')
    return body,summary


def publish(store, head, body):
    path = f'odds/{body["day"]}.json'
    previous = store.read_previous(head,path)
    if previous is not None:
        prior = odds.checked(public._json(previous))
        public.need(prior['day'] == body['day'] and when(prior['published_at']) <= when(body['published_at']), 'ODDS_CLOCK')
        rows = {row['race_id']:row for row in prior['races']}
        for row in body['races']:
            saved = rows.get(row['race_id'])
            if saved is None or when(saved['source_at']) <= when(row['source_at']):
                rows[row['race_id']] = row
        body = odds.checked(dict(body,races=[rows[rid] for rid in sorted(rows)]))
        if body['races'] == prior['races']:
            return head
    commit,raw = public._commit_projection(store,head,path,body)
    public._push_projection(store,head,path,commit,raw)
    return commit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--schedule', type=Path)
    parser.add_argument('--capture-dir', action='append', type=Path)
    parser.add_argument('--handoff', type=Path)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args(argv)
    if args.handoff is not None:
        public.need(args.schedule is None and args.capture_dir is None, 'ODDS_HANDOFF_EXCLUSIVE')
        _,payload = _read_handoff(args.handoff)
        day = payload['day']
    else:
        public.need(args.schedule is not None and args.capture_dir, 'ODDS_EXPLICIT_CAPTURE_REQUIRED')
        schedule = restore_private_snapshot_json(public._json(_read(args.schedule,MAX_BYTES)))
        day = schedule['day_jst']
    store = public.PublicForecastGit(args.repo)
    head,state = updates.day_state(store,day)
    now = datetime.now(timezone.utc)
    body,summary = (prepare_handoff(args.handoff,state,now=now) if args.handoff is not None else
                    prepare(schedule,args.capture_dir,state,now=now))
    if body is not None and args.publish:
        summary['commit'] = publish(store,head,body)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
