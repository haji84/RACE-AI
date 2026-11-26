"""Publish timestamped quotes for actual public forecast candidates."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import re

from race_ai import keirin_public_forecast_odds as odds
from race_ai import keirin_public_forecast_updates as updates
from race_ai import keirin_public_forecasts as public
from race_ai.keirin_nationwide_auto_generator import when
from scripts.keirin_capture_public_two_sources import MAX_BYTES, private_dir
from scripts.keirin_note_collect_inputs import _read
from scripts.keirin_official_day_pipeline import restore_private_snapshot_json
from scripts.keirin_publish_result_unread import _source
from race_ai.keirin_official_public_source import reparse_day_schedule


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


def prepare(schedule, captures, state, *, now):
    public.need(reparse_day_schedule(schedule), 'ODDS_OFFICIAL_SCHEDULE')
    day = schedule['day_jst']
    roster = {row['race_id']:[p['car'] for p in row['starters']] for row in schedule['races']}
    registry = {row['race_id'] for row in state['forecasts']['races']}
    tickets = _displayed_tickets(state)
    cards = {}
    for capture in captures:
        root = private_dir(capture)
        rows = public._json(_read(root/'cards-observed.json',public.MAX_BYTES))
        public.need(type(rows) is list, 'ODDS_CAPTURE_ROWS')
        for row in rows:
            rid = row['race_id']
            public.need(rid in registry and rid in roster and rid not in cards, 'ODDS_CAPTURE_ID')
            cards[rid] = (root,row['kdreams_receipt'])
    quotes, issues = [], Counter()
    for rid,(root,receipt) in sorted(cards.items()):
        if not tickets.get(rid):
            continue
        try:
            html,url = _source(root,receipt,generated_at=now)
            row = odds.parse_racecard(html,race_id=rid,url=url,starters=roster[rid],
                                      observed_at=receipt['captured_at'],wanted=tickets[rid])
            if row['quotes']:
                quotes.append(row)
            else:
                issues['NO_NUMERIC_MARKET_QUOTE'] += 1
        except (ValueError,KeyError,TypeError,OSError) as error:
            reason = str(error)
            issues[reason if re.fullmatch('[A-Z_0-9]{1,100}',reason) else 'ODDS_SOURCE_INVALID'] += 1
    body = odds.checked(dict(schema=odds.SCHEMA,day=day,published_at=now.isoformat(),races=quotes))
    summary = dict(registered=len(registry), source_cards=len(cards), races_with_odds=len(quotes),
                   quotes=sum(len(row['quotes']) for row in quotes), held=dict(issues))
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
    parser.add_argument('--schedule', required=True, type=Path)
    parser.add_argument('--capture-dir', action='append', required=True, type=Path)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args(argv)
    schedule = restore_private_snapshot_json(public._json(_read(args.schedule,MAX_BYTES)))
    store = public.PublicForecastGit(args.repo)
    head,state = updates.day_state(store,schedule['day_jst'])
    body,summary = prepare(schedule,args.capture_dir,state,now=datetime.now(timezone.utc))
    if args.publish:
        summary['commit'] = publish(store,head,body)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
