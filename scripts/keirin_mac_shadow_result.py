"""Settle one frozen local shadow forecast using the existing official parser and scorer."""

from datetime import timedelta
from hashlib import sha256
from math import fsum
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from race_ai import keirin_comparison_snapshot as snapshot
from race_ai import keirin_official_public_source as official
from race_ai import keirin_secondary_result_consensus as consensus
from race_ai.keirin_github_evidence_client import NoRedirect
from race_ai.keirin_joint_finish import _distribution
from race_ai.keirin_note_view import _private_root
from scripts.keirin_forward_score import confirmed_order, unique_races
from scripts.keirin_joint_forward_score import _ticket_event
from scripts.keirin_line_version_study import write_private
from scripts.keirin_official_day_pipeline import private_snapshot_json, restore_private_snapshot_json
from scripts.keirin_public_site_results import validate_roster

FIELDS = {'original_path', 'original_sha256', 'schedule_path', 'schedule_sha256'}
MAX_RECEIPT_BYTES = 32 * 1024 * 1024
MAX_POLLS = 4
POLL_INTERVAL = timedelta(minutes=15)
POLL_WINDOW = timedelta(hours=2)
GITHUB_REF = 'git/ref/heads/state/keirin-public-results'
GITHUB_API = 'https://api.github.com/repos/haji84/RACE-AI/'
GIT_SHA = re.compile(r'[0-9a-f]{40}')
PUBLIC_SOURCE_HOLD = 'HOLD_OFFICIAL_AUTOMATED_SOURCE_NOT_ENABLED'


def _read(path, limit, digest=None):
    path = Path(path)
    snapshot._private(path.parent)
    if path.lstat().st_mode & 0o077:
        raise ValueError('SHADOW_INPUT_NOT_PRIVATE')
    raw = snapshot._read_regular(path, limit)
    if digest is not None and sha256(raw).hexdigest() != digest:
        raise ValueError('SHADOW_INPUT_DIGEST_MISMATCH')
    return snapshot._json(raw, 'SHADOW_JSON_INVALID')


def _inputs(request, now):
    pins = _read(request, 4096)
    if (type(pins) is not dict or set(pins) != FIELDS
            or not all(snapshot._digest(pins[key]) for key in ('original_sha256', 'schedule_sha256'))):
        raise ValueError('SHADOW_REQUEST_INVALID')
    original = _read(pins['original_path'], 512 * 1024, pins['original_sha256'])
    schedule = restore_private_snapshot_json(_read(pins['schedule_path'], MAX_RECEIPT_BYTES, pins['schedule_sha256']))
    rid = original['race_id']
    official._race(rid)
    if (original['schema'] != 'KEIRIN_MAC_PROSPECTIVE_SHADOW_V1' or original['scope'] != 'PROSPECTIVE_RESEARCH'
            or original['production_model_switched'] is not False or not official.reparse_day_schedule(schedule)):
        raise ValueError('SHADOW_INPUT_SCHEMA_OR_SCHEDULE')
    race = next((row for row in schedule['races'] if row['race_id'] == rid), None)
    if race is None:
        raise ValueError('SHADOW_RACE_NOT_REGISTERED')
    generated = official._aware(original['generated_at'])
    cutoff = official._aware(race['official_cutoff_at'])
    start = official._aware(race['start_at'])
    score_cutoff = official._aware(original['score_cutoff_at'])
    if (official._aware(original['official_cutoff_at']) != cutoff or not
            official._aware(race['source_observed_at']) <= generated <= now or not
            generated < score_cutoff <= cutoff < start):
        raise ValueError('SHADOW_TIMING_INVALID')
    evidence = original['input']
    bound = evidence['input']
    registered = {row['car']: row['registration_id'] for row in race['starters']}
    riders = bound['riders']
    if (bound['race_id'] != rid or evidence['official_schedule_sha256'] != pins['schedule_sha256']
            or evidence['official_venue_source_sha256'] != race['source_sha256']
            or any(type(row['car']) is not int for row in riders)
            or len(riders) != len(registered) or len(set(registered.values())) != len(registered)
            or {row['car']: row['athlete_id'] for row in riders} != registered):
        raise ValueError('SHADOW_ROSTER_NOT_BOUND')
    challenger = original['selected_arm']
    forecasts = original['forecasts']
    if type(challenger) is not str or challenger == 'saved' or set(forecasts) != {'saved', challenger}:
        raise ValueError('SHADOW_COMPARISON_INVALID')
    books = {}
    for label, arm in (('saved', 'saved'), ('challenger', challenger)):
        rows = forecasts[arm]['trifecta']
        if any(type(order) is not list or any(type(car) is not int for car in order) for order, _ in rows):
            raise ValueError('SHADOW_TRIFECTA_ORDER_INVALID')
        book = {tuple(order): probability for order, probability in rows}
        if len(book) != len(rows):
            raise ValueError('SHADOW_DUPLICATE_TRIFECTA_ORDER')
        _, books[label] = _distribution(registered, book)
    pin = {key: pins[key] for key in ('original_sha256', 'schedule_sha256')}
    return schedule, race, start, score_cutoff, tuple(registered), books, pin


def _preserve(path, document):
    try:
        write_private(path, document)
    except FileExistsError:
        if _read(path, MAX_RECEIPT_BYTES) != document:
            raise ValueError('SHADOW_SAVED_EVIDENCE_CONFLICT') from None


def _score(state, receipt, schedule, race, starters, books):
    evidence = receipt['provenance']['schedule_evidence']
    if (receipt['race_id'] != race['race_id'] or receipt['state'] != 'OFFICIAL_FINAL'
            or evidence != official._schedule_evidence(schedule, race['race_id'])
            or not official.reparse_race_result(receipt)):
        raise ValueError('SHADOW_OFFICIAL_RECEIPT_UNBOUND')
    result = receipt['result']
    payload = official._payload(official._index(receipt['snapshots'])[result['source_url']])
    finishes = payload['tyakujyunItemSubData']
    if {row['tyaku'] for row in finishes} != {str(i) for i in range(1, len(starters) + 1)}:
        return {'state': 'HOLD_SHADOW_FINISH_NOT_SCORABLE'}
    order = [int(row['syaban']) for row in sorted(finishes, key=lambda row: int(row['tyaku']))]

    from scripts.keirin_accuracy_study import score_distribution

    scores = {}
    for label, book in books.items():
        metrics = score_distribution(starters, book, order)
        scores[label] = {key: metrics[key] for key in ('top4_3t', 'top2_2t')}
    report = dict(state='SHADOW_RESULT_SCORED', scope='OFFICIAL_COMPLETE_FINISH_RESEARCH',
                  scores=scores, official_observed_at=result['observed_at'],
                  official_source_sha256=result['source_sha256'])
    _preserve(state / 'aggregate-score.json', report)
    return report


def _claim_poll(state, now, limit, interval):
    previous = sorted(state.glob('poll-*.json'))
    if len(previous) >= limit:
        return 'HOLD_SHADOW_POLL_LIMIT', len(previous)
    if previous and now < official._aware(_read(previous[-1], 4096)['at']) + interval:
        return 'WAITING_FOR_OFFICIAL_POLL_INTERVAL', len(previous)
    sequence = len(previous) + 1
    try:
        write_private(state / f'poll-{sequence:02}.json', {'at': now.isoformat()})
    except FileExistsError:
        return 'WAITING_FOR_OFFICIAL_POLL_INTERVAL', sequence
    return None, sequence


def _public_github_json(path, *, raw=False):
    url = GITHUB_API + path
    accept = 'application/vnd.github.raw+json' if raw else 'application/vnd.github+json'
    request = Request(url, headers={'Accept': accept, 'User-Agent': 'RACE-AI-KEIRIN-Mac/1.0'})
    with build_opener(NoRedirect()).open(request, timeout=12) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('SHADOW_PUBLIC_GITHUB_RESPONSE_INVALID')
        data = response.read(MAX_RECEIPT_BYTES + 1)
    if len(data) > MAX_RECEIPT_BYTES:
        raise ValueError('SHADOW_PUBLIC_EVIDENCE_TOO_LARGE')
    return snapshot._json(data, 'SHADOW_PUBLIC_GITHUB_JSON_INVALID')


def _public_score(receipt, day, race, score_cutoff, starters, books):
    roster, results = receipt['roster'], receipt['results']
    validate_roster(roster, consensus)
    checked = official._aware(results['checked_at'])
    if (roster['date'] != day or results['date'] != day or results['schema'] != 'KEIRIN_PUBLISHED_RESULTS_V1'
            or not GIT_SHA.fullmatch(receipt['commit']) or checked > official._aware(receipt['seen_at'])):
        raise ValueError('SHADOW_PUBLIC_RESULT_PROVENANCE')
    rid = race['race_id']
    row = unique_races(results).get(rid)
    if row is None or row['state'] != 'matched':
        return None
    roster_row = unique_races(roster)[rid]
    cutoff = roster_row['published_cutoff_at']
    if (official._aware(cutoff) not in (score_cutoff, official._aware(race['official_cutoff_at']))
            or {rider['number'] for rider in roster_row['observed_riders']} != set(starters)
            or official._aware(row['comparison']['observed_at']) < official._aware(race['start_at'])):
        raise ValueError('SHADOW_PUBLIC_RESULT_RACE_NOT_BOUND')
    winner = tuple(confirmed_order(row, cutoff, set(starters), checked))
    scores = {}
    for label, book in books.items():
        exacta = {pair: fsum(book[pair + (third,)] for third in starters if third not in pair)
                  for pair in {order[:2] for order in book}}
        scores[label] = dict(top4_3t=int(_ticket_event(book, winner, 4)[1]),
                             top2_2t=int(_ticket_event(exacta, winner[:2], 2)[1]))
    return dict(state='SHADOW_PUBLIC_PODIUM_SCORED', scope='TWO_SOURCE_MATCHED_PODIUM_ONLY',
                official_state=PUBLIC_SOURCE_HOLD, full_finish_verified=False,
                public_commit=receipt['commit'], scores=scores)


def _public_cycle(state, day, race, score_cutoff, starters, books, now, clock, get):
    state = _private_root(state / 'github-public')
    result_path = state / 'published-result.json'
    if result_path.exists():
        receipt = _read(result_path, MAX_RECEIPT_BYTES)
    else:
        if (state / 'provider-stop.json').exists():
            return dict(state='HOLD_GITHUB_PUBLIC_RESULT_REFUSAL', official_state=PUBLIC_SOURCE_HOLD)
        if now >= official._aware(race['start_at']) + timedelta(hours=24):
            return dict(state='HOLD_GITHUB_PUBLIC_POLL_EXPIRED', official_state=PUBLIC_SOURCE_HOLD)
        hold, _ = _claim_poll(state, now, 48, timedelta(minutes=30))
        if hold:
            return dict(state=hold.replace('OFFICIAL', 'GITHUB_PUBLIC'), official_state=PUBLIC_SOURCE_HOLD)
        try:
            revision = get(GITHUB_REF)['object']['sha']
            if not GIT_SHA.fullmatch(revision):
                raise ValueError('SHADOW_PUBLIC_COMMIT_INVALID')
            roster = get(f'contents/rosters/{day}.json?ref={revision}', raw=True)
            results = get(f'contents/results/{day}.json?ref={revision}', raw=True)
            receipt = dict(commit=revision, roster=roster, results=results,
                           seen_at=official._aware(clock()).isoformat())
        except HTTPError as error:
            if error.code in (401, 403, 407, 429):
                _preserve(state / 'provider-stop.json', {'at': now.isoformat()})
                return dict(state='HOLD_GITHUB_PUBLIC_RESULT_REFUSAL', official_state=PUBLIC_SOURCE_HOLD)
            if error.code == 404:
                return dict(state='WAITING_FOR_GITHUB_PUBLIC_RESULT', official_state=PUBLIC_SOURCE_HOLD)
            return dict(state='HOLD_GITHUB_PUBLIC_RESULT_UNAVAILABLE', official_state=PUBLIC_SOURCE_HOLD)
        except (URLError, TimeoutError):
            return dict(state='HOLD_GITHUB_PUBLIC_RESULT_UNAVAILABLE', official_state=PUBLIC_SOURCE_HOLD)
    result = _public_score(receipt, day, race, score_cutoff, starters, books)
    if result is None:
        return dict(state='WAITING_FOR_GITHUB_PUBLIC_RESULT', official_state=PUBLIC_SOURCE_HOLD)
    _preserve(result_path, receipt)
    _preserve(state / 'aggregate-score.json', result)
    return result


def run(root, request, *, clock, fetcher=None, public_fetcher=None):
    """Return a safe status; retain evidence only in the existing private Mac root."""
    if request is None:
        return {'state': 'SHADOW_NOT_CONFIGURED'}
    try:
        now = official._aware(clock())
        schedule, race, start, score_cutoff, starters, books, pin = _inputs(request, now)
    except (KeyError, OSError, TypeError, ValueError):
        return {'state': 'HOLD_SHADOW_INPUT_INVALID'}
    try:
        namespace = _private_root(Path(root) / 'keirin-mac-shadow-results')
        state = _private_root(namespace / race['race_id'])
        pins_path = state / 'request-pins.json'
        if now < score_cutoff:
            _preserve(pins_path, pin)
        elif not pins_path.is_file():
            return {'state': 'HOLD_SHADOW_PRE_CUTOFF_PIN_MISSING'}
        elif _read(pins_path, 4096) != pin:
            return {'state': 'HOLD_SHADOW_INPUT_CHANGED_AFTER_PIN'}
        if now < start:
            return {'state': 'WAITING_FOR_OFFICIAL_START', 'official_start_at': start.isoformat()}
        final_path = state / 'official-result.json'
        if final_path.exists():
            receipt = restore_private_snapshot_json(_read(final_path, MAX_RECEIPT_BYTES))
            return _score(state, receipt, schedule, race, starters, books)
        refused = namespace / 'official-provider-stop.json'
        if refused.exists():
            return {'state': 'HOLD_OFFICIAL_PROVIDER_REFUSAL'}
        if fetcher is None and os.environ.get('RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED') != 'true':
            try:
                return _public_cycle(state, schedule['day_jst'], race, score_cutoff, starters, books,
                                     now, clock, public_fetcher or _public_github_json)
            except (KeyError, OSError, TypeError, ValueError):
                return dict(state='HOLD_GITHUB_PUBLIC_RESULT_INVALID', official_state=PUBLIC_SOURCE_HOLD)
        if now >= start + POLL_WINDOW:
            return {'state': 'HOLD_SHADOW_POLL_EXPIRED'}
        hold, attempts = _claim_poll(state, now, MAX_POLLS, POLL_INTERVAL)
        if hold:
            return {'state': hold}

        try:
            receipt = official.fetch_race_result(race['race_id'], schedule=schedule, fetcher=fetcher, clock=clock)
        except official.OfficialSourceError as error:
            if isinstance(error, official.OfficialProviderStop) or str(error) in ('OFFICIAL_HTTP_401', 'OFFICIAL_HTTP_407'):
                _preserve(refused, {'at': now.isoformat(), 'scope': 'OFFICIAL_MAC_SHADOW'})
                return {'state': 'HOLD_OFFICIAL_PROVIDER_REFUSAL'}
            return {'state': 'HOLD_OFFICIAL_RESULT_SOURCE', 'polls': attempts}
        if not official.reparse_race_result(receipt):
            return {'state': 'HOLD_OFFICIAL_RESULT_UNVERIFIED'}
        if receipt['state'] != 'OFFICIAL_FINAL':
            return dict(state='WAITING_FOR_OFFICIAL_FINAL', official_state=receipt['state'], polls=attempts)
        _preserve(final_path, private_snapshot_json(receipt))
        return _score(state, receipt, schedule, race, starters, books)
    except (KeyError, OSError, TypeError, ValueError):
        return {'state': 'HOLD_SHADOW_EVIDENCE_INVALID'}
