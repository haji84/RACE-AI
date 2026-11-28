"""Append estimates for exact seven-rider racecard A shortlists with replay evidence."""

from datetime import date
from math import isclose
import re

from . import keirin_public_forecasts as public
from .keirin_nationwide_auto_generator import digest, when
from .keirin_nationwide_forecast_view import JST, MAX_RACES, _day, _ids
from .keirin_paired_measurement import _wilson

SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_RACECARD_REPLAY_V1'
SCOPE = 'RETROSPECTIVE_REPLAY'
INTERVALS = ((0, .15), (.15, .25), (.25, .35), (.35, .60))
Z95 = 1.959963984540054


def _hex(value, length):
    return type(value) is str and re.fullmatch(r'[a-f0-9]{%d}' % length, value) is not None


def _in_band(value, lower, upper):
    return type(value) in (float, int) and lower <= value < upper


def checked(body):
    public.need(type(body) is dict and set(body) == {
        'schema', 'scope', 'day', 'assessed_at', 'forecast_commit', 'forecast_published_at', 'tree_sha256',
        'archive_sha256', 'replay_window', 'bins', 'races'
    } and body['schema'] == SCHEMA and body['scope'] == SCOPE, 'REPLAY_SCHEMA')
    day = _day(body['day'])
    assessed = when(body['assessed_at'])
    public.need(assessed.astimezone(JST).date().isoformat() == day and when(body['forecast_published_at']) <= assessed and
                _hex(body['forecast_commit'], 40) and _hex(body['tree_sha256'], 64) and
                _hex(body['archive_sha256'], 64), 'REPLAY_PROVENANCE')
    window = body['replay_window']
    public.need(type(window) is list and len(window) == 2, 'REPLAY_WINDOW')
    start, end = map(_day, window)
    public.need(start <= end < day, 'REPLAY_WINDOW')
    window_days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    public.need(type(body['bins']) is list and 1 <= len(body['bins']) <= len(INTERVALS), 'REPLAY_BINS')
    bands = set()
    for band in body['bins']:
        public.need(type(band) is dict and set(band) == {
            'lower', 'upper', 'n', 'hits', 'days', 'mean_probability', 'ci95'
        }, 'REPLAY_BIN')
        lower, upper = band['lower'], band['upper']
        n, hits, days = band['n'], band['hits'], band['days']
        public.need(type(lower) in (int, float) and type(upper) in (int, float) and
                    (lower, upper) in INTERVALS and (lower, upper) not in bands and
                    all(type(count) is int for count in (n, hits, days)) and
                    30 <= n <= MAX_RACES * days and 0 < hits <= n and
                    3 <= days <= min(window_days, n), 'REPLAY_SAMPLE')
        estimate, ci95 = band['mean_probability'], band['ci95']
        expected = _wilson(hits, n, Z95)
        public.need(_in_band(estimate, lower, upper) and abs(estimate - hits / n) <= .10 and
                    expected[0] <= estimate <= expected[1] and
                    type(ci95) is list and len(ci95) == 2 and
                    all(type(limit) in (int, float) and 0 <= limit <= 1 and
                        isclose(limit, actual, rel_tol=0, abs_tol=1e-12)
                        for limit, actual in zip(ci95, expected)), 'REPLAY_VALIDATION')
        bands.add((lower, upper))
    races = body['races']
    public.need(type(races) is list and 1 <= len(races) <= MAX_RACES, 'REPLAY_RACES')
    for row in races:
        public.need(type(row) is dict and set(row) == {'race_id', 'points', 'ticket_sha256', 'probability'} and
                    type(row['race_id']) is str and type(row['points']) is int and row['points'] == 8 and
                    _hex(row['ticket_sha256'], 64) and
                    any(_in_band(row['probability'], *band) for band in bands), 'REPLAY_RACE')
    _ids([row['race_id'] for row in races], day)
    return body


def _matching_research(store, commit, body):
    raw = store.read_previous(commit, 'research/' + body['day'] + '.json')
    public.need(raw is not None, 'REPLAY_ORIGINAL')
    research = public.checked_research(public._json(raw))
    posted, assessed = when(research['published_at']), when(body['assessed_at'])
    public.need(research['day'] == body['day'], 'REPLAY_ORIGINAL_DAY')
    if commit == body['forecast_commit']:
        public.need(posted == when(body['forecast_published_at']), 'REPLAY_ORIGINAL_CLOCK')
    originals = {row['race_id']: row for row in research['races']}
    for row in body['races']:
        original = originals.get(row['race_id'])
        public.need(original and when(original['generated_at']) <= assessed < when(original['cutoff_at']) and
                    len(original['starter_cars']) == 7 and original['b'] == [] and
                    len(original['a']) == row['points'] and digest(original['a']) == row['ticket_sha256'],
                    'REPLAY_ORIGINAL_MISMATCH')


def publish(repo, body, *, store=None):
    """Keep the original forecasts and the first published assessment immutable."""
    checked(body)
    store = store or public.PublicForecastGit(repo)
    parent = store.head()
    public.need(parent is not None, 'REPLAY_PUBLIC_STATE_REQUIRED')
    store.fetch(parent)
    forecast_commit = body['forecast_commit']
    store.run(['merge-base', '--is-ancestor', forecast_commit, parent])
    _matching_research(store, forecast_commit, body)
    if forecast_commit != parent:
        _matching_research(store, parent, body)
    path = 'measurements/replay-confidence-' + body['day'] + '.json'
    previous = store.read_previous(parent, path)
    if previous is not None:
        public.need(previous == public.canonical(body) + b'\n', 'REPLAY_ASSESSMENT_CHANGED')
        return {'state': 'PUBLIC_RACECARD_REPLAY_CURRENT', 'commit': parent}
    commit, raw = public._commit_projection(store, parent, path, body)
    public._push_projection(store, parent, path, commit, raw)
    return {'state': 'PUBLIC_RACECARD_REPLAY_PUBLISHED', 'commit': commit}
