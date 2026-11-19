"""Connect EXISTING owner-approved capture and PR103 history inputs privately.

This is acquisition/orchestration, not a predictor, a source licence, or a new
scheduler. Incomplete and research-only derived inputs NEVER enter pre/ and
NEVER create an empty production AES generation. Only aggregate counts leave
the temporary inbox. Existing independently licensed feeds keep precedence.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections import OrderedDict
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import argparse
import json
import os
import re
import time

from scripts.keirin_runtime_selection import nationwide_ab_selected

PROFILE = 'owner-approved-winticket-keirinjp-20261109'
SCHEMA = 'RACE_AI_KEIRIN_CLOUD_OWNER_SOURCE_CONNECTION_V1'
SOURCE_PATH = re.compile(r'^/keirin/[a-z][a-z0-9-]{2,30}/racecard/(\d{8})(\d{2})/([1-3])/([1-9]|1[0-2])$')
JST = ZoneInfo('Asia/Tokyo')
MARGIN = timedelta(seconds=390)
# Reuse only past-result pages inside one run; never changing live pages.
PAST_RESULT_PATH = re.compile(
    r'^/keirin/[a-z][a-z0-9-]{2,30}/raceresult/[0-9]{10}/[1-3]/(?:[1-9]|1[0-2])$')
PAST_CACHE_MAX_BYTES = 24 * 1024 * 1024
PAST_CACHE_ENTRY_MAX_BYTES = 2 * 1024 * 1024
OFFICIAL_STATES = frozenset({
    'OFFICIAL_SP_PARTIAL_INPUT_CAPTURED', 'HOLD_OFFICIAL_SP_BUDGET',
    'HOLD_OFFICIAL_SP_DENIED', 'HOLD_OFFICIAL_SP_NO_CURRENT_MEETINGS',
    'HOLD_OFFICIAL_SP_SOURCE_LAYOUT', 'HOLD_OFFICIAL_SP_TRANSPORT',
    'HOLD_OFFICIAL_SP_LOCAL_RUNTIME',
})


def _official_collector():
    """Find new input readers after pinned model code, without shadowing it."""
    import race_ai
    main_package = str(Path(__file__).resolve().parents[1] / 'race_ai')
    if main_package not in race_ai.__path__:
        race_ai.__path__.append(main_package)
    from race_ai.keirin_official_sp_browser import collect_official_sp
    return collect_official_sp


def _official_owner_inputs(root, *, capture, clock, monotonic, budget_seconds):
    """Map actual official acquisition counts; never expose raw input values."""
    day = instant(clock()).astimezone(JST).date().isoformat()
    result = dict(schema=SCHEMA, date_jst=day,
        state='OWNER_ATTESTED_SOURCE_ACQUISITION_ONLY',
        source_provider='KEIRIN_JP_PUBLIC_SP', source_day_schedule_race_count=None,
        source_capture_held=True, invalid_partial_records=0,
        expired_or_too_close=0, history_races_processed=0, history_races_held=0,
        history_races_deferred=0, races=[], new_pre_race_inputs=0,
        actual_four_model_forecast_saved=False, owner_automated_use_attested=True,
        provider_machine_rights_independently_verified=False,
        permanent_encrypted_storage_claimed=False,
        source_values_or_rider_names_publicly_logged=False,
        public_page_requests=0, provider_denial_stopped_requests=False,
        provider_denial_http_status_counts={'HTTP_403': 0, 'HTTP_429': 0, 'UNKNOWN': 0},
        work_budget_exhausted=False, historical_pages_reused_without_new_GET=0,
        historical_page_cache_bytes=0, model_B_missing_family_slot_totals={},
        winticket_requests=0)
    if nationwide_ab_selected():
        result['state'] = 'LEGACY_PR71_SUPERSEDED_BY_NATIONWIDE_AB'
        return result
    capture_invoked = False
    try:
        collector = capture or _official_collector()
        capture_invoked = True
        collected = collector(root, clock=clock,
            monotonic=monotonic, budget_seconds=budget_seconds)
        need(type(collected) is dict and collected.get('state') in OFFICIAL_STATES,
             'OFFICIAL_SOURCE_REPORT_INVALID')
        need(collected.get('source_admission') is False and
             collected.get('model_input_admission') is False and
             type(collected.get('new_forecasts')) is int and collected['new_forecasts'] == 0 and
             type(collected.get('winticket_requests')) is int and collected['winticket_requests'] == 0,
             'OFFICIAL_PARTIAL_SOURCE_CANNOT_PROMOTE_OR_RETRY')
        safe = {'state': collected['state']}
        count_fields = ('calendar_meetings_observed', 'race_lists_verified',
            'details_verified', 'riders_verified', 'future_detail_count',
            'expired_detail_count', 'navigation_request_count',
            'resource_request_count', 'unknown_transmitted_status_count',
            'blocked_before_send', 'private_source_files_saved')
        for name in count_fields:
            value = collected.get(name)
            need(type(value) is int and value >= 0, 'OFFICIAL_COUNT_INVALID')
            safe[name] = value
        for name in ('day_venue_count', 'day_race_count'):
            value = collected.get(name)
            need(value is None or type(value) is int and value >= 0,
                 'OFFICIAL_DENOMINATOR_INVALID')
            safe[name] = value
        for name in ('provider_denied', 'budget_exhausted'):
            need(type(collected.get(name)) is bool, 'OFFICIAL_STATE_TYPE_INVALID')
            safe[name] = collected[name]
        statuses = collected.get('http_status_counts')
        need(type(statuses) is dict and all(type(k) is str and
            re.fullmatch('[1-5][0-9]{2}', k) and type(v) is int and v >= 0
            for k, v in statuses.items()), 'OFFICIAL_HTTP_COUNTS_INVALID')
        safe['http_status_counts'] = dict(sorted(statuses.items()))
        denials = collected.get('provider_denial_http_status_counts')
        need(type(denials) is dict and set(denials) == {'HTTP_403', 'HTTP_429', 'UNKNOWN'} and
             all(type(v) is int and v >= 0 for v in denials.values()), 'OFFICIAL_DENIAL_COUNTS_INVALID')
        need(not any(statuses.get(code, 0) for code in ('401', '403', '407', '429')) or
             safe['provider_denied'], 'OFFICIAL_DENIAL_STATE_INCONSISTENT')
        need(safe['state'] != 'OFFICIAL_SP_PARTIAL_INPUT_CAPTURED' or
             not (safe['provider_denied'] or safe['budget_exhausted']),
             'OFFICIAL_SUCCESS_STATE_INCONSISTENT')
        need(sum(statuses.values()) + safe['unknown_transmitted_status_count'] ==
             safe['navigation_request_count'] + safe['resource_request_count'],
             'OFFICIAL_TRANSMITTED_STATUS_ACCOUNTING_INVALID')
        need(safe['future_detail_count'] + safe['expired_detail_count'] <= safe['details_verified'] and
             safe['riders_verified'] <= 9 * safe['details_verified'], 'OFFICIAL_DETAIL_COUNT_INVALID')
        safe.update(source_admission=False, model_input_admission=False, new_forecasts=0,
                    winticket_requests=0, provider_denial_http_status_counts=dict(denials))
        result.update(official_sp_acquisition=safe,
            source_day_schedule_race_count=safe['day_race_count'],
            source_capture_held=safe['state'] != 'OFFICIAL_SP_PARTIAL_INPUT_CAPTURED',
            public_page_requests=safe['navigation_request_count'] + safe['resource_request_count'],
            public_page_request_count_scope='ALL_TRANSMITTED_BROWSER_REQUESTS',
            provider_denial_stopped_requests=safe['provider_denied'],
            provider_denial_http_status_counts=dict(denials),
            work_budget_exhausted=safe['budget_exhausted'],
            expired_or_too_close=safe['expired_detail_count'])
    except (ValueError, OSError, RuntimeError, ImportError, KeyError, TypeError):
        if capture_invoked:
            result['public_page_requests'] = None
            result['provider_denial_stopped_requests'] = None
            result['provider_denial_http_status_counts'] = {
                'HTTP_403': None, 'HTTP_429': None, 'UNKNOWN': None}
            result['winticket_requests'] = None
        result['official_sp_acquisition'] = dict(state='HOLD_OFFICIAL_SP_LOCAL_RUNTIME',
            source_admission=False, model_input_admission=False, new_forecasts=0,
            winticket_requests=None if capture_invoked else 0)
    need(not (root / 'pre').exists(), 'OWNER_PARTIAL_SOURCE_PROMOTION_FORBIDDEN')
    return result


def need(ok, reason):
    """Reject an unmet boundary without including private source values."""
    if not ok:
        raise ValueError(reason)


def instant(value):
    """Normalize an explicit timezone-aware source or runtime clock to UTC."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    need(isinstance(value, datetime) and value.utcoffset() is not None,
         'AWARE_SOURCE_CLOCK_REQUIRED')
    return value.astimezone(timezone.utc)


class SourceSession:
    """Stop real requests after provider denial or the current job's budget."""
    def __init__(self, fetch, *, monotonic, budget_seconds):
        """Bind a shared provider transport to one monotonic acquisition budget."""
        self.fetch, self.monotonic = fetch, monotonic
        self.deadline = monotonic() + budget_seconds
        self.host_denied = False
        self.provider_denial_http_status_counts = {'HTTP_403': 0, 'HTTP_429': 0, 'UNKNOWN': 0}
        self.budget_exhausted = False
        self.requests = 0
        self.historical_page_cache_hits = 0
        self.historical_page_cache_bytes = 0
        self._historical_cache = OrderedDict()

    def available(self):
        """Return false once the work budget or provider-denial circuit has closed."""
        if self.monotonic() >= self.deadline:
            self.budget_exhausted = True
        return not (self.host_denied or self.budget_exhausted)

    def __call__(self, url):
        """Fetch only an approved host and latch access denials for this cycle."""
        need(not nationwide_ab_selected(),
             'LEGACY_SOURCE_SUPERSEDED_BY_NATIONWIDE_AB')
        need(self.available(), 'OWNER_SOURCE_SESSION_STOPPED')
        u = urlsplit(url)
        need(u.scheme == 'https' and not u.username and not u.password and
             u.port in (None, 443) and u.hostname in {
                 'winticket.jp', 'www.winticket.jp', 'keirin.jp', 'www.keirin.jp'},
             'OWNER_APPROVED_SOURCE_HOST_REQUIRED')
        # Cache only already-completed historical result URLs.
        eligible = (u.hostname in {'winticket.jp', 'www.winticket.jp'}
                    and PAST_RESULT_PATH.fullmatch(u.path) is not None
                    and not u.query and not u.fragment)
        if eligible and url in self._historical_cache:
            body, digest = self._historical_cache.pop(url)
            need(sha256(body).hexdigest() == digest,
                 'CACHED_HISTORICAL_RESULT_CHANGED')
            self._historical_cache[url] = (body, digest)
            self.historical_page_cache_hits += 1
            return body
        self.requests += 1
        try:
            body = self.fetch(url)
        except (ValueError, OSError) as exc:
            # Never include an arbitrary provider exception/URL in public logs.
            if any(x in str(exc).upper() for x in ('BLOCKED', 'RATE_LIMIT', '403', '429')):
                self.host_denied = True
                # fe7 suppresses this immediate HTTPError context in its public
                # error text. Preserve only a fixed status count, never its data.
                context = exc.__context__
                status = getattr(context, 'code', None) if isinstance(context, HTTPError) else None
                kind = ({403: 'HTTP_403', 429: 'HTTP_429'}.get(status, 'UNKNOWN')
                        if type(status) is int else 'UNKNOWN')
                self.provider_denial_http_status_counts[kind] += 1
            raise
        if eligible and type(body) is bytes and 0 < len(body) <= PAST_CACHE_ENTRY_MAX_BYTES:
            while (self._historical_cache and
                   self.historical_page_cache_bytes + len(body) > PAST_CACHE_MAX_BYTES):
                _, (removed, _) = self._historical_cache.popitem(last=False)
                self.historical_page_cache_bytes -= len(removed)
            self._historical_cache[url] = (body, sha256(body).hexdigest())
            self.historical_page_cache_bytes += len(body)
        return body


def _private_root(inbox):
    """Require a temporary source inbox outside the public repository checkout."""
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
    """Validate a privately stored card by byte digest, race identity and cutoff."""
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
    """Export validated coverage counts, never source values or model admission."""
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
    # Field names are from the fixed 347/437 registry, not athlete data.
    # Record actual missing *source-family* counts without inventing values.
    groups = report.get('remaining_model_B_source_groups')
    if groups is not None:
        need(type(groups) is dict and len(groups) <= 40 and all(
             type(field) is str and
             re.fullmatch(r'(?:race/)?[a-z][a-z0-9_]*', field) and
             type(count) is int and 1 <= count <= (1 if field.startswith('race/') else n)
             for field, count in groups.items()) and
             sum(groups.values()) == result['remaining_model_B_slots'],
             'MODEL_B_MISSING_FAMILY_ACCOUNTING_INVALID')
        result['model_B_missing_source_family_slots'] = dict(sorted(groups.items()))
    result['private_partial_readback_verified'] = (
        report.get('existing_private_partial_input_staged') is True and
        report.get('private_candidate_replay_verified') is True)
    result['full_model_input_admitted'] = False
    return result


def collect_owner_inputs(inbox, *, owner_auto_confirmed, capture=None, probe=None,
                         fetch=None, clock=None, monotonic=None, budget_seconds=240,
                         official_capture=None):
    """All eligible captured races in cutoff order, with no invented features."""
    need(owner_auto_confirmed is True, 'EXPLICIT_OWNER_AUTOMATIC_SCOPE_REQUIRED')
    root = _private_root(inbox)
    need(not (root / 'pre').exists(), 'OWNER_PARTIAL_SOURCE_CANNOT_SHARE_MODEL_PRE_QUEUE')
    need(type(budget_seconds) in (int, float) and 1 <= budget_seconds <= 600,
         'SOURCE_WORK_TIME_BUDGET_INVALID')
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)
    if monotonic is None:
        monotonic = time.monotonic
    if capture is None and probe is None and fetch is None:
        return _official_owner_inputs(root, capture=official_capture, clock=clock,
            monotonic=monotonic, budget_seconds=budget_seconds)
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
    out['provider_denial_http_status_counts'] = dict(session.provider_denial_http_status_counts)
    out['work_budget_exhausted'] = session.budget_exhausted
    # Slot-level deficit totals are count-only and never source or rider
    # values. The same missing family can appear across several races.
    family_totals = {}
    for row in out['races']:
        for field, count in row.get('model_B_missing_source_family_slots', {}).items():
            family_totals[field] = family_totals.get(field, 0) + count
    out['model_B_missing_family_slot_totals'] = dict(
        sorted(family_totals.items(), key=lambda item: (-item[1], item[0])))
    out['historical_pages_reused_without_new_GET'] = session.historical_page_cache_hits
    out['historical_page_cache_bytes'] = session.historical_page_cache_bytes
    return out


def main(argv=None):
    """Run explicit owner-source acquisition and emit a sanitized status document."""
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
