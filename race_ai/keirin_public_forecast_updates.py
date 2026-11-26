"""Retain versioned public chat forecasts and conditional contest selections."""
import re

from . import keirin_nationwide_forecast_view as nationwide
from . import keirin_public_forecasts as public
from .keirin_nationwide_auto_generator import when

SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_FORECAST_UPDATES_V1'
FIELDS = {'race_id','cutoff_at','starter_cars','a','b'}


def _legal_tickets(tickets, cars):
    return public._tickets(tickets) and all(set(ticket) <= cars for ticket in tickets)


def _check_contests(hypotheses, cars):
    public.need(type(hypotheses) is list and len(hypotheses) in (2,4), 'UPDATE_CONTEST_HYPOTHESES')
    slots = len(hypotheses) // 2
    cases = set()
    for hypothesis in hypotheses:
        public.need(type(hypothesis) is dict and set(hypothesis) == {'cars','tickets'}, 'UPDATE_CONTEST_CASE')
        winners = hypothesis['cars']
        public.need(type(winners) is list and len(winners) == slots and
                    all(type(car) is int and car in cars for car in winners) and len(set(winners)) == slots and
                    (hypothesis['tickets'] == [] or _legal_tickets(hypothesis['tickets'], cars)), 'UPDATE_CONTEST_CASE')
        cases.add(tuple(winners))
    contestants = [{case[index] for case in cases} for index in range(slots)]
    public.need(len(cases) == len(hypotheses) and all(len(pair) == 2 for pair in contestants) and
                len(set().union(*contestants)) == 2 * slots and any(case['tickets'] for case in hypotheses),
                'UPDATE_CONTEST_HYPOTHESES')


def checked(body):
    public.need(type(body) is dict and set(body) == {'schema','day','published_at','races'} and
                body['schema'] == SCHEMA, 'UPDATE_SCHEMA')
    day = nationwide._day(body['day'])
    published = when(body['published_at'])
    rows = body['races']
    public.need(type(rows) is list and 0 < len(rows) <= nationwide.MAX_RACES, 'UPDATE_RACES')
    for row in rows:
        public.need(type(row) is dict and set(row) == FIELDS and
                    when(row['cutoff_at']).astimezone(nationwide.JST).date().isoformat() == day, 'UPDATE_RACE')
        cars = row['starter_cars']
        public.need(type(cars) is list and 5 <= len(cars) <= 9 and
                    all(type(car) is int and 1 <= car <= 9 for car in cars) and cars == sorted(set(cars)), 'UPDATE_STARTERS')
        public.need(row['a'] is not None or row['b'] is not None, 'UPDATE_NO_CANDIDATES')
        for name in ('a','b'):
            arm = row[name]
            if arm is None:
                continue
            public.need(type(arm) is dict and when(arm.get('registered_at')) <= published, 'UPDATE_CLOCK')
            if arm.get('kind') == 'chat':
                public.need(set(arm) == {'kind','registered_at','tickets'} and _legal_tickets(arm['tickets'], set(cars)),
                            'UPDATE_CHAT_TICKETS')
            else:
                public.need(name == 'b' and arm.get('kind') == 'contested_lineup' and
                            set(arm) == {'kind','registered_at','hypotheses'}, 'UPDATE_ARM')
                _check_contests(arm['hypotheses'], set(cars))
    nationwide._ids([row['race_id'] for row in rows], day)
    return body


def day_state(store, day):
    """Read the public registry, generated references and latest additions at one Git head."""
    nationwide._day(day)
    head = store.head()
    public.need(head is not None, 'UPDATE_REGISTRY_REQUIRED')
    store.fetch(head)
    values = {}
    for directory, check in (('forecasts',public.checked), ('references',public.checked_reference),
                             ('research',public.checked_research), ('updates',checked)):
        raw = store.read_previous(head, f'{directory}/{day}.json')
        document = check(public._json(raw)) if raw is not None else None
        public.need(document is None or document['day'] == day, 'UPDATE_DAY')
        values[directory] = document
    public.need(values['forecasts'] is not None, 'UPDATE_REGISTRY_REQUIRED')
    return head, values


def _same_selection(before, after):
    return before is not None and all(before.get(key) == value for key,value in after.items() if key != 'registered_at')


def publish(repo, body, *, store=None, expected_head=None):
    """Apply explicit arm changes while retaining prior public Git revisions."""
    checked(body)
    day = body['day']
    store = store or public.PublicForecastGit(repo)
    head, state = day_state(store, day)
    public.need(expected_head is None or re.fullmatch(r'[0-9a-f]{40}', expected_head) and head == expected_head,
                'UPDATE_HEAD_CHANGED')
    registry = {row['race_id']:row for row in state['forecasts']['races']}
    research = {row['race_id']:row for row in (state['research'] or {}).get('races', [])}
    reference = {row['race_id'] for row in (state['references'] or {}).get('races', [])}
    existing = state['updates']
    rows = {row['race_id']:row for row in (existing or {}).get('races', [])}
    public.need(rows.keys() <= registry.keys(), 'UPDATE_UNREGISTERED_RACE')
    changed = 0
    for proposal in body['races']:
        rid = proposal['race_id']
        public.need(rid in registry, 'UPDATE_UNREGISTERED_RACE')
        known_cutoff = registry[rid]['cutoff_at'] or research.get(rid, {}).get('cutoff_at')
        public.need(known_cutoff is None or when(known_cutoff) == when(proposal['cutoff_at']), 'UPDATE_CUTOFF_MISMATCH')
        saved = rows.get(rid)
        known = research.get(rid) or saved
        public.need(known is None or known['starter_cars'] == proposal['starter_cars'], 'UPDATE_STARTER_MISMATCH')
        revised = dict(proposal)
        for name in ('a','b'):
            before = saved[name] if saved else None
            after = proposal[name]
            if after is None or _same_selection(before, after):
                revised[name] = before
                continue
            if after['kind'] == 'contested_lineup':
                public.need(rid not in reference and registry[rid]['status'] == 'pending' and
                            rid in research and not research[rid]['b'] and
                            (before is None or before['kind'] != 'chat'), 'UPDATE_CONTEST_B_ALREADY_PRESENT')
            public.need(before is None or when(before['registered_at']) <= when(after['registered_at']), 'UPDATE_CLOCK')
        if revised != saved:
            rows[rid] = revised
            changed += 1
    if not changed:
        return dict(state='PUBLIC_FORECAST_UPDATES_CURRENT', commit=head, day_jst=day, changed_races=0)
    public.need(existing is None or when(existing['published_at']) <= when(body['published_at']), 'UPDATE_CLOCK')
    merged = checked(dict(body, races=[rows[rid] for rid in sorted(rows)]))
    path = f'updates/{day}.json'
    commit, raw = public._commit_projection(store, head, path, merged)
    public._push_projection(store, head, path, commit, raw)
    return dict(state='PUBLIC_FORECAST_UPDATES_WRITTEN', commit=commit, day_jst=day, changed_races=changed)
