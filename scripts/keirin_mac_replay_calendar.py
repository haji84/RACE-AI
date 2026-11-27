"""Discover replay candidates from the existing published schedule and results."""
from collections import Counter
from datetime import date, timedelta
import os
import re
from selectors import DefaultSelector, EVENT_READ
import subprocess
from time import monotonic
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

from race_ai import keirin_comparison_snapshot as snapshot
from race_ai.keirin_official_public_source import _aware
from scripts import keirin_mac_shadow_result as published
from scripts.keirin_video_census import compact_id

JST = ZoneInfo('Asia/Tokyo')
FORECAST_REF = 'git/ref/heads/state/keirin-public-forecasts'
DAY_FILE = re.compile(r'(\d{4}-\d{2}-\d{2})\.json')
CANCELLED = {'SPECIAL_CANCELLED_REFUND_CONFIRMED', 'cancelled_refund'}
CONTENTS_ROUTE = re.compile(
    rf'contents/(?:rosters|(?:forecasts|rosters|results)/{DAY_FILE.pattern})\?ref={published.GIT_SHA.pattern}')
HTTP_STATUS = re.compile(rb'HTTP/(?:1\.[01]|2(?:\.0)?|3(?:\.0)?) ([1-5][0-9]{2})(?: [^\r\n]*)?')
GITHUB_TIMEOUT = 12
MAX_HEADER_BYTES = 16 * 1024


def _gh_response(command):
    env = os.environ.copy()
    for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN', 'GH_DEBUG'):
        env.pop(name, None)
    env.update(GH_PROMPT_DISABLED='1', GH_NO_UPDATE_NOTIFIER='1')
    limit = published.MAX_RECEIPT_BYTES + MAX_HEADER_BYTES
    deadline = monotonic() + GITHUB_TIMEOUT
    body = bytearray()
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, env=env) as process, DefaultSelector() as selector:
        try:
            selector.register(process.stdout, EVENT_READ)
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise subprocess.TimeoutExpired(command, GITHUB_TIMEOUT)
                chunk = os.read(process.stdout.fileno(), min(65536, limit - len(body) + 1))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > limit:
                    raise ValueError('CALENDAR_GITHUB_RESPONSE_TOO_LARGE')
            return process.wait(timeout=max(0, deadline - monotonic())), bytes(body)
        finally:
            if process.poll() is None:
                process.kill()


def _github_json(path, *, raw=False):
    if path not in (FORECAST_REF, published.GITHUB_REF) and not CONTENTS_ROUTE.fullmatch(path):
        raise ValueError('CALENDAR_GITHUB_ROUTE_INVALID')
    url = published.GITHUB_API + path
    accept = 'application/vnd.github.raw+json' if raw else 'application/vnd.github+json'
    code, response = _gh_response([
        'gh', 'api', '--hostname', 'github.com', '--method', 'GET', '--include',
        '--header', f'Accept: {accept}', url.removeprefix('https://api.github.com'),
    ])
    parts = re.split(rb'\r?\n\r?\n', response, maxsplit=1)
    if len(parts) != 2:
        raise ValueError('CALENDAR_GITHUB_RESPONSE_INVALID')
    head, body = parts
    status_line = HTTP_STATUS.fullmatch(head.split(b'\n', 1)[0].rstrip(b'\r'))
    if status_line is None or len(head) > MAX_HEADER_BYTES:
        raise ValueError('CALENDAR_GITHUB_RESPONSE_INVALID')
    status = int(status_line[1])
    if status >= 400 and code == 1:
        raise HTTPError(url, status, 'CALENDAR_GITHUB_REQUEST_FAILED', None, None)
    if status != 200 or code != 0:
        raise ValueError('CALENDAR_GITHUB_RESPONSE_INVALID')
    if len(body) > published.MAX_RECEIPT_BYTES:
        raise ValueError('CALENDAR_GITHUB_RESPONSE_TOO_LARGE')
    return snapshot._json(body, 'CALENDAR_GITHUB_JSON_INVALID')


def combine(day, forecast, roster, results, now):
    """Bind public podium evidence without recording it as an official full finish."""
    rows = {}

    def register(entry, cutoff, source):
        key = compact_id(entry['race_id'])
        if key[:8] != day.replace('-', ''):
            raise ValueError('Public replay calendar race date mismatch.')
        state = 'cutoff_unverified'
        if cutoff is not None:
            state = 'scheduled' if _aware(cutoff) > now else 'result_pending'
        rows[key] = dict(race_id=key, race_date=day, race_detail_url=source, state=state,
                         result_observed_at=None)

    if forecast is not None:
        if forecast['schema'] != 'RACE_AI_KEIRIN_PUBLIC_FORECASTS_V1' or forecast['day'] != day:
            raise ValueError('Public replay calendar schedule mismatch.')
        for entry in published.unique_races(forecast).values():
            register(entry, entry['cutoff_at'], None)
    if roster is None:
        if results is not None:
            raise ValueError('Public replay calendar results require their roster.')
        return list(rows.values())
    published.validate_roster(roster, published.consensus)
    if roster['date'] != day:
        raise ValueError('Public replay calendar roster date mismatch.')
    races = published.unique_races(roster)
    for entry in races.values():
        register(entry, entry['published_cutoff_at'], entry['source_url'])
    if results is None:
        return list(rows.values())
    stamped = _aware(results['checked_at'])
    if results['schema'] != 'KEIRIN_PUBLISHED_RESULTS_V1' or results['date'] != day or stamped > now:
        raise ValueError('Public replay calendar result provenance mismatch.')
    settled = published.unique_races(results)
    if not settled.keys() <= races.keys():
        raise ValueError('Public replay calendar has results outside its roster.')
    for key, outcome in settled.items():
        row = rows[compact_id(key)]
        roster_row = races[key]
        cutoff = roster_row['published_cutoff_at']
        if row['state'] == 'scheduled':
            continue
        if outcome['state'] == 'matched':
            players = {r['number'] for r in roster_row['observed_riders']}
            try:
                published.confirmed_order(outcome, cutoff, players, stamped)
            except (ValueError, KeyError, TypeError):
                row['state'] = 'result_held'
            else:
                row['state'] = 'ended_cross_source'
                row['result_observed_at'] = outcome['comparison']['observed_at']
        elif outcome.get('reason') in CANCELLED:
            row['state'] = 'cancelled'
        elif outcome['state'] == 'held':
            row['state'] = 'result_held'
    return list(rows.values())


def _head(get, path):
    payload = get(path)
    ref = payload['object']
    if (payload['ref'] != 'refs/' + path.removeprefix('git/ref/') or ref['type'] != 'commit'
            or not published.GIT_SHA.fullmatch(ref['sha'])):
        raise ValueError('Invalid public replay calendar Git ref.')
    return ref['sha']


def _read_day(get, folder, day, commit):
    path = f'contents/{folder}/{day}.json?ref={commit}'
    try:
        return get(path, raw=True)
    except HTTPError as error:
        if error.code == 404 and error.geturl() == published.GITHUB_API + path:
            return None
        raise


def refresh(db, now, *, get=_github_json):
    today = now.astimezone(JST).date()
    yesterday = today - timedelta(days=1)
    forecasts = _head(get, FORECAST_REF)
    results = _head(get, published.GITHUB_REF)
    listing = get(f'contents/rosters?ref={results}')
    older = sorted({date.fromisoformat(match[1]) for item in listing
                    if (match := DAY_FILE.fullmatch(item['name'])) and date.fromisoformat(match[1]) < yesterday})
    days = [today, yesterday]
    if older:
        slot = int(now.timestamp()) // 900  # same interval as the existing Mac launch agent
        days.append(older[slot % len(older)])
    rows = []
    coverage = {}
    for day in days:
        iso = day.isoformat()
        forecast = _read_day(get, 'forecasts', iso, forecasts) if day == today else None
        roster = _read_day(get, 'rosters', iso, results)
        settled = _read_day(get, 'results', iso, results) if roster is not None else None
        day_rows = combine(iso, forecast, roster, settled, now)
        coverage[iso] = dict(Counter(row['state'] for row in day_rows))
        rows.extend(dict(row, result_commit=results if row['result_observed_at'] else None)
                    for row in day_rows)
    with db:
        db.execute('BEGIN')
        db.execute('''CREATE TABLE IF NOT EXISTS replay_calendar (
                    id TEXT PRIMARY KEY, day TEXT NOT NULL, url TEXT, state TEXT NOT NULL)''')
        cols = {row[1] for row in db.execute('PRAGMA table_info(replay_calendar)')}
        if 'result_commit' not in cols:
            db.execute('ALTER TABLE replay_calendar ADD COLUMN result_commit TEXT')
            db.execute('ALTER TABLE replay_calendar ADD COLUMN result_observed_at TEXT')
        db.executemany('''INSERT INTO replay_calendar VALUES (:race_id, :race_date, :race_detail_url, :state,
                                                                :result_commit, :result_observed_at)
                          ON CONFLICT(id) DO UPDATE SET url=coalesce(excluded.url,replay_calendar.url),
                          state=excluded.state, result_commit=excluded.result_commit,
                          result_observed_at=excluded.result_observed_at
                          WHERE excluded.url IS NOT NULL OR replay_calendar.state NOT IN ('ended_cross_source','cancelled')''',
                       rows)
    return dict(state='REPLAY_CALENDAR_REFRESHED', days=coverage, forecast_commit=forecasts, result_commit=results)


def queue_state(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='replay_calendar'").fetchone():
        return [], set()
    cancelled = {key for key, in db.execute("SELECT id FROM replay_calendar WHERE state='cancelled'")}
    candidates = [dict(row) for row in db.execute('''
        SELECT id AS race_id,day AS race_date,url AS race_detail_url,result_commit,result_observed_at
        FROM replay_calendar WHERE state='ended_cross_source' AND result_commit IS NOT NULL AND url IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM media WHERE race=id AND kind IN ('clip','full'))
        ORDER BY id
    ''')]
    return candidates, cancelled
