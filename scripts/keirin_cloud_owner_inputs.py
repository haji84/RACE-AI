"""Connect EXISTING owner-approved capture and PR103 history inputs privately.

This is acquisition/orchestration, not a predictor, a source licence, or a new
scheduler. Incomplete and research-only derived inputs NEVER enter pre/ and
NEVER create an empty production AES generation. Only aggregate counts leave
the temporary inbox. Existing independently licensed feeds keep precedence.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import argparse
import json
import os
import re
import time

PROFILE = 'owner-approved-winticket-keirinjp-20261109'
SCHEMA = 'RACE_AI_KEIRIN_CLOUD_OWNER_SOURCE_CONNECTION_V1'
SOURCE_PATH = re.compile(r'^/keirin/[a-z][a-z0-9-]{2,30}/racecard/(\d{8})(\d{2})/([1-3])/([1-9]|1[0-2])$')
JST = ZoneInfo('Asia/Tokyo')
MARGIN = timedelta(seconds=390)


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def instant(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    need(isinstance(value, datetime) and value.utcoffset() is not None,
         'AWARE_SOURCE_CLOCK_REQUIRED')
    return value.astimezone(timezone.utc)


class SourceSession:
    """Stop real requests after provider denial or the current job's budget."""
    def __init__(self, fetch, *, monotonic, budget_seconds):
        self.fetch, self.monotonic = fetch, monotonic
        self.deadline = monotonic() + budget_seconds
        self.host_denied = False
        self.budget_exhausted = False
        self.requests = 0

    def available(self):
        if self.monotonic() >= self.deadline:
            self.budget_exhausted = True
        return not (self.host_denied or self.budget_exhausted)

    def __call__(self, url):
        need(self.available(), 'OWNER_SOURCE_SESSION_STOPPED')
        u = urlsplit(url)
        need(u.scheme == 'https' and not u.username and not u.password and
             u.port in (None, 443) and u.hostname in {
                 'winticket.jp', 'www.winticket.jp', 'keirin.jp', 'www.keirin.jp'},
             'OWNER_APPROVED_SOURCE_HOST_REQUIRED')
        self.requests += 1
        try:
            return self.fetch(url)
        except (ValueError, OSError) as exc:
            # Never include an arbitrary provider exception/URL in public logs.
            if any(x in str(exc).upper() for x in ('BLOCKED', 'RATE_LIMIT', '403', '429')):
                self.host_denied = True
            raise


def _private_root(inbox):
    p = Path(inbox).expanduser()
    need(p.is_absolute() and p.is_dir() and not p.is_symlink(),
         'PRIVATE_EXISTING_INBOX_REQUIRED')
    root = p.resolve()
    workspace = os.getenv('GITHUB_WORKSPACE')
    if workspace:
        need(not root.is_relative_to(Path(workspace).resolve()),
             'SOURCE_INBOX_MUST_BE_OUTSIDE_CHECKOUT')
    return root


def _card(path, day):
    need(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 2_000_000,
         'PRIVATE_PARTIAL_CARD_UNSAFE')
    raw = path.read_bytes()
    need(path.stem == sha256(raw).hexdigest(), 'PRIVATE_PARTIAL_CARD_SHA_CHANGED')
    data = json.loads(raw)
    need(type(data) is dict and type(data.get('race_id')) is str and
         re.fullmatch(r'20\d{10}', data['race_id']) and
         data['race_id'][:8] == day.replace('-', ''), 'WRONG_DAY_PARTIAL_CARD')
    url = urlsplit(data.get('source_url', ''))
    need(url.scheme == 'https' and url.hostname in ('winticket.jp', 'www.winticket.jp') and
         not url.username and not url.password and url.port in (None, 443) and
         not url.query and not url.fragment, 'PARTIAL_CARD_SOURCE_NOT_APPROVED')
    match = SOURCE_PATH.fullmatch(url.path)
    need(match is not None, 'PARTIAL_CARD_SOURCE_PATH_INVALID')
    start, venue, meeting_day, number = match.groups()
    event = datetime.strptime(start, '%Y%m%d') + timedelta(days=int(meeting_day)-1)
    expected = event.strftime('%Y%m%d') + venue + f'{int(number):02d}'
    need(expected == data['race_id'], 'PARTIAL_CARD_SOURCE_RACE_MISMATCH')
    n = len(data.get('riders', []))
    need(n in (7, 9), 'PARTIAL_CARD_SEVEN_OR_NINE_REQUIRED')
    captured = instant(data['source_capture_at_utc'])
    cutoff = instant(data['source_published_cutoff_at_utc'])
    need(captured < cutoff, 'PARTIAL_CARD_NOT_PRE_CUTOFF')
    return data, captured, cutoff, n


def _safe_result(report, rid, n):
    need(type(report) is dict and report.get('race_id') == rid and
         report.get('actual_four_model_forecast_saved') is False and
         report.get('full_model_input_admitted') is False,
         'PARTIAL_ACQUISITION_CANNOT_PROMOTE_A_FORECAST')
    total = 12*n+9
    need(report.get('required_model_slots') == total, 'EXISTING_INPUT_UNIVERSE_CHANGED')
    result = {'race_id':rid, 'state':'PARTIAL_INPUT_ONLY', 'required_model_slots':total}
    for letter in ('A', 'B'):
        observed = report.get(f'observed_or_derived_model_{letter}_slots')
        missing = report.get(f'remaining_model_{letter}_slots')
        need(type(observed) is int and type(missing) is int and
             0 <= observed <= total and observed+missing == total,
             'PARTIAL_INPUT_COUNT_INCONSISTENT')
        result[f'observed_or_derived_model_{letter}_slots'] = observed
        result[f'remaining_model_{letter}_slots'] = missing
    result['private_partial_readback_verified'] = (
        report.get('existing_private_partial_input_staged') is True and
        report.get('private_candidate_replay_verified') is True)
    result['full_model_input_admitted'] = False
    return result


def collect_owner_inputs(inbox, *, owner_auto_confirmed, capture=None, probe=None,
                         fetch=None, clock=None, monotonic=None, budget_seconds=240):
    """All eligible captured races in cutoff order, with no invented features."""
    need(owner_auto_confirmed is True, 'EXPLICIT_OWNER_AUTOMATIC_SCOPE_REQUIRED')
    root = _private_root(inbox)
    need(type(budget_seconds) in (int, float) and 1 <= budget_seconds <= 600,
         'SOURCE_WORK_TIME_BUDGET_INVALID')
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)
    if monotonic is None:
        monotonic = time.monotonic
    if capture is None:
        from scripts.keirin_github_owner_future_intake import owner_future_public_intake
        capture = owner_future_public_intake
    if probe is None:
        from scripts.keirin_prior_real_input_probe import probe as prior_probe
        probe = prior_probe
    if fetch is None:
        from race_ai.keirin_owner_public_page_fetch import network_page_once
        fetch = network_page_once
    now = instant(clock())
    day = now.astimezone(JST).date().isoformat()
    session = SourceSession(fetch, monotonic=monotonic, budget_seconds=budget_seconds)
    # Candidate acquisition is private-only; do not silently feed the model.
    need(not (root/'pre').exists(), 'OWNER_PARTIAL_SOURCE_CANNOT_SHARE_MODEL_PRE_QUEUE')
    out = {
        'schema':SCHEMA, 'date_jst':day,
        'state':'OWNER_ATTESTED_SOURCE_ACQUISITION_ONLY',
        'source_day_schedule_race_count':None,
        'source_capture_held':False, 'invalid_partial_records':0,
        'expired_or_too_close':0, 'history_races_processed':0,
        'history_races_held':0, 'history_races_deferred':0, 'races':[],
        'new_pre_race_inputs':0, 'actual_four_model_forecast_saved':False,
        'owner_automated_use_attested':True,
        'provider_machine_rights_independently_verified':False,
        'permanent_encrypted_storage_claimed':False,
        'source_values_or_rider_names_publicly_logged':False,
    }
    try:
        got = capture(root, fetch=session, clock=clock, lookahead_minutes=180, max_races=120)
        for key in ('source_day_schedule_race_count', 'future_7_or_9_source_linked_in_window',
                    'selected_in_this_cycle', 'private_partial_racecards_staged',
                    'private_full_odds_races_staged'):
            value = got.get(key)
            if type(value) is int and 0 <= value <= 10000:
                out[key] = value
    except (ValueError, OSError, KeyError, TypeError):
        out['source_capture_held'] = True
    folder = root/'winticket_racecard_partial'
    need(not folder.is_symlink(), 'PRIVATE_PARTIAL_FOLDER_SYMLINK')
    latest = {}
    paths = sorted(folder.glob('*.json')) if folder.is_dir() else []
    need(len(paths) <= 2500, 'PRIVATE_PARTIAL_FILE_RESOURCE_LIMIT')
    for path in paths:
        try:
            item, captured, cutoff, n = _card(path, day)
            need(captured <= instant(clock()), 'PARTIAL_CARD_CAPTURE_FROM_FUTURE')
            rid = item['race_id']
            if rid not in latest or captured > latest[rid][1]:
                latest[rid] = (item, captured, cutoff, n)
        except (ValueError, OSError, KeyError, TypeError):
            out['invalid_partial_records'] += 1
    ordered = sorted(latest.values(), key=lambda row:(row[2], row[0]['race_id']))
    for index, (item, captured, cutoff, n) in enumerate(ordered):
        if not session.available():
            out['history_races_deferred'] += len(ordered)-index
            break
        if instant(clock()) + MARGIN >= cutoff:
            out['expired_or_too_close'] += 1
            continue
        rid = item['race_id']
        private = root/'history-inputs'/rid
        need(not private.is_symlink() and not private.parent.is_symlink(),
             'PRIVATE_HISTORY_PATH_UNSAFE')
        private.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            report = probe(race_id=rid, racecard_url=item['source_url'], max_pages=100,
                fetch=session, clock=clock, private_evidence_dir=private,
                include_modelled_weather=True)
            need(instant(clock()) < cutoff, 'HISTORY_COLLECTION_CROSSED_CUTOFF')
            result = _safe_result(report, rid, n)
            out['races'].append(result)
            out['history_races_processed'] += 1
        except (ValueError, OSError, KeyError, TypeError):
            out['history_races_held'] += 1
    need(not (root/'pre').exists(), 'OWNER_PARTIAL_SOURCE_PROMOTION_FORBIDDEN')
    out['public_page_requests'] = session.requests
    out['provider_denial_stopped_requests'] = session.host_denied
    out['work_budget_exhausted'] = session.budget_exhausted
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inbox', required=True)
    parser.add_argument('--owner-automatic-fetch-confirmed', action='store_true')
    parser.add_argument('--budget-seconds', type=int, default=240)
    args = parser.parse_args(argv)
    try:
        report = collect_owner_inputs(args.inbox,
            owner_auto_confirmed=args.owner_automatic_fetch_confirmed,
            budget_seconds=args.budget_seconds)
        print(json.dumps(report, sort_keys=True, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError):
        print(json.dumps({'schema':SCHEMA, 'state':'OWNER_SOURCE_ACQUISITION_HOLD',
                          'actual_four_model_forecast_saved':False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
