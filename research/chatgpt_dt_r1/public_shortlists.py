"""Adaptive DT-R1 shortlists for the existing public race cards.

This projection publishes ranked car combinations and clocks. Full probability
distributions and authenticated forecast originals stay with their owners.
"""
from math import fsum
import re

from .policy import check_race_day, checked_cars, checked_day, checked_sha, clock, ticket_cap, validate_forecast


SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_DT_R1_V1'
MODEL = 'chatgpt-dt-r1'
# Model binding for this reviewed public selection policy.
MODEL_SHA = '5e022092a35c0258954090c6f3d0f8fa14f03f22511b28d6aa9183f5a38c381c'
POLICY = 'dt-r1-public-ranked-mass-v1'
COVERAGE_TARGET = .20
MAX_POINTS = 12
MAX_RACES = 300
REASONS = {'COVERAGE_REACHED', 'ODDS_CAP', 'MAX_POINTS'}
DAY_FIELDS = {'schema', 'day', 'model_id', 'model_sha256', 'policy', 'input_commit', 'published_at', 'races'}
RACE_FIELDS = {'race_id', 'cutoff_at', 'selected_at', 'source_at', 'starter_cars', 'tickets', 'reason'}
CLOCK_FORMAT = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
                          r'(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})')


def _need(ok, code):
    if not ok:
        raise ValueError('DT_R1_PUBLIC_' + code)


def _public_clock(value):
    _need(type(value) is str and CLOCK_FORMAT.fullmatch(value), 'CLOCK_FORMAT')
    return clock(value)


def _row(row, day, published):
    _need(type(row) is dict and set(row) == RACE_FIELDS, 'ROW')
    rid = row['race_id']
    _need(type(rid) is str and re.fullmatch(day.replace('-', '') + r'\d\d(?:0[1-9]|1[0-2])', rid),
          'RACE_ID')
    cutoff, at, source = (_public_clock(row[key]) for key in ('cutoff_at', 'selected_at', 'source_at'))
    check_race_day(day, row['cutoff_at'])
    _need(source < cutoff and source <= at <= published, 'CLOCK')
    cars = checked_cars(row['starter_cars'])
    _need(list(cars) == sorted(cars) and 3 <= len(cars) <= 9, 'STARTERS')
    tickets = row['tickets']
    _need(type(tickets) is list and 1 <= len(tickets) <= MAX_POINTS, 'TICKET_COUNT')
    ordered = tuple(checked_cars(ticket, 3) for ticket in tickets)
    _need(len(set(ordered)) == len(ordered) and all(set(ticket) <= set(cars) for ticket in ordered), 'TICKETS')
    reason = row['reason']
    _need(type(reason) is str and reason in REASONS, 'REASON')
    if reason == 'ODDS_CAP':
        _need(len(tickets) in (2, 4, 9), 'ODDS_CAP')
    elif reason == 'MAX_POINTS':
        n = len(cars)
        _need(len(tickets) == min(MAX_POINTS, n * (n-1) * (n-2)), 'MAX_POINTS')


def checked(packet):
    _need(type(packet) is dict and set(packet) == DAY_FIELDS and
          packet['schema'] == SCHEMA and packet['model_id'] == MODEL and
          packet['policy'] == POLICY, 'SCHEMA')
    day = checked_day(packet['day']).isoformat()
    _need(checked_sha(packet['model_sha256']) == MODEL_SHA, 'MODEL_PIN')
    _need(type(packet['input_commit']) is str and re.fullmatch('[a-f0-9]{40}', packet['input_commit']), 'INPUT_COMMIT')
    published = _public_clock(packet['published_at'])
    races = packet['races']
    _need(type(races) is list and 0 < len(races) <= MAX_RACES, 'RACES')
    for row in races:
        _row(row, day, published)
    _need(len({row['race_id'] for row in races}) == len(races), 'DUPLICATE_RACE')
    return packet


def _cap(odds, rid, anchor, cutoff, selected):
    if odds is None:
        return MAX_POINTS
    _need(odds.get('race_id') == rid and type(odds.get('quotes')) is dict, 'ODDS_RACE')
    observed, source = clock(odds['observed_at']), clock(odds['source_at'])
    if not source <= observed < cutoff or observed > selected:
        return MAX_POINTS
    quote = odds['quotes'].get('-'.join(map(str, anchor)))
    return ticket_cap(quote) if quote is not None else MAX_POINTS


def select(forecast, *, cutoff_at, source_at, selected_at, odds=None):
    """Select the fewest leading triples reaching the analysis coverage target."""
    f = validate_forecast(forecast)
    _need(f['model_id'] == MODEL and f['model_sha256'] == MODEL_SHA, 'MODEL_PIN')
    cutoff, selected = clock(cutoff_at), clock(selected_at)
    _need(f.get('cutoff_at') is None or clock(f['cutoff_at']) == cutoff, 'FORECAST_CUTOFF')
    _need(f.get('prediction_at') is None or clock(f['prediction_at']) <= selected, 'FORECAST_CLOCK')
    ranked = f['trifectas']
    cap = min(_cap(odds, f['race_id'], ranked[0]['cars'], cutoff, selected), len(ranked))
    reason = 'ODDS_CAP' if cap < min(MAX_POINTS, len(ranked)) else 'MAX_POINTS'
    count = cap
    for n in range(1, cap + 1):
        if fsum(item['probability'] for item in ranked[:n]) >= COVERAGE_TARGET:
            count, reason = n, 'COVERAGE_REACHED'
            break
    row = dict(race_id=f['race_id'], cutoff_at=cutoff_at, source_at=source_at,
               selected_at=selected_at, starter_cars=f['starters'],
               tickets=[item['cars'] for item in ranked[:count]], reason=reason)
    _row(row, f['day'], selected)
    return row


def project_day(day, *, model_sha256, input_commit, published_at, races):
    return checked(dict(schema=SCHEMA, day=day, model_id=MODEL, policy=POLICY,
        model_sha256=model_sha256, input_commit=input_commit, published_at=published_at,
        races=sorted(races, key=lambda row: row['race_id'])))
