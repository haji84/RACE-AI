"""Three bounded authorized sources for separate full-name numeric forecasts.

No raw HTML/TSV leaves this worker. Memory-store clocks are measured by the
existing store and never rewritten; durable input saves belong to the caller.
"""
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
import sqlite3
from urllib import error

from .official_update_worker import fetch_update, reviewed_scope
from .official_race_updates import parse_update
from . import official_observation_store as memory
from .tokuyama_day_worker import FetchResponse
from web import race_contract as facts
from web.name_bound_inputs import _context, build_name_bound_inputs
from web.original_exhibition_contract import parse_original, endpoint

MAX_BYTES = 1048576
MARGIN = timedelta(seconds=120)


def utc_now():return datetime.now(timezone.utc)


class _Stop(ValueError):pass


def collect_name_bound_inputs(race, baseline, binding, *, parents_read_at, facts_review,
        media_review, execute=False, transport_update=None, transport_original=None, clock=utc_now):
    """Dry-run makes no GET. Count each actual transport attempt, never retry."""
    count = 0
    def stopped(code):return dict(status=code, official_source_requests=count)
    if execute is not True:return stopped('DRY_RUN')
    try:
        day, close, _ = facts._program(race)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):return stopped('INPUT_INVALID')
    previous = None
    def tick(*, margin=False):
        nonlocal previous
        try:measured = facts._time(clock())
        except (ValueError, TypeError, AttributeError, OverflowError):raise _Stop('DAY_INVALID' if previous is None else 'SOURCE_INVALID')
        if measured.astimezone(facts.JST).date() != day:raise _Stop('DAY_INVALID')
        if previous is not None and measured < previous:raise _Stop('SOURCE_INVALID')
        if measured >= close or (margin and measured + MARGIN >= close):raise _Stop('CUTOFF_PASSED')
        previous = measured
        return measured
    try:
        start = tick(margin=True)
        try:
            _, _, _, projected, base_link, name_link = _context(race, baseline, binding, start)
            parents = facts._time(parents_read_at)
            if not (max(facts._time(base_link['cloud_saved_at']), facts._time(name_link['receipt_confirmed_at'])) <= parents <= start
                and parents.astimezone(facts.JST).date() == day):raise ValueError('parents')
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError):return stopped('INPUT_INVALID')
        try:
            if facts_review.get('evidence_reference') != 'user-confirmation-2026-10-15-official-facts':raise ValueError('review reference')
            reviewed_scope(facts_review, day=day, venue=race['race_id'][9:11], kind='beforeinfo', now=start)
            # Reuse the exact original numeric owner scope and bounded fetch.
            from scripts.collect_original_exhibition import _review, fetch_original
            _review(media_review, race, start)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):return stopped('RIGHTS_BLOCKED')
        def get(url, transport, timeout, types):
            nonlocal count
            tick(margin=True)
            count += 1
            try:response = transport(url, timeout=timeout, max_bytes=MAX_BYTES)
            except (error.URLError, OSError, TimeoutError, HTTPException):raise _Stop('SOURCE_UNAVAILABLE')
            except (ValueError, TypeError, AttributeError):raise _Stop('SOURCE_INVALID')
            captured = tick()
            if (not isinstance(response, FetchResponse) or type(response.status) is not int or response.status != 200
                or response.url != url or not isinstance(response.body, bytes) or not 0 < len(response.body) <= MAX_BYTES
                or not isinstance(response.content_type, str) or response.content_type.split(';')[0].strip().lower() not in types):
                raise _Stop('SOURCE_INVALID')
            return response.body, captured
        url = facts._endpoint(race['race_id'], 'beforeinfo')
        raw, captured = get(url, transport_update or fetch_update, 10, {'text/html'})
        observation = parse_update(raw, kind='beforeinfo', day=day, venue=race['race_id'][9:11],
            race_no=int(race['race_id'][-2:]), source_url=url, captured_at=facts.stamp(captured), entries=projected['boats'])
        del raw
        observation['rights_review'] = facts_review['evidence_reference']
        with sqlite3.connect(':memory:') as db:
            memory.setup_store(db)
            memory.save_observation(db, observation)
            checked_at = tick()
            record = memory.latest_observation(db, race['race_id'], 'beforeinfo', as_of=checked_at)
        if record is None:raise _Stop('SOURCE_INVALID')
        facts.validate_record(record, projected, checked_at, require_same_day=True)
        if (record['status'] != 'AVAILABLE' or record['data'] is None
            or any(b['display_time'] is None for b in record['data']['boats'])):raise _Stop('DISPLAY_PENDING')
        if not record['storage_eligible_pre_race']:raise _Stop('CUTOFF_PASSED')
        values = []; captures = []
        for component in ('original', 'standard'):
            raw, capture = get(endpoint(race['race_id'], component), transport_original or fetch_original,
                15, {'text/plain', 'application/octet-stream', 'text/tab-separated-values'})
            values.append(raw); captures.append(capture)
        parsed_at = tick()
        original = parse_original(values[0], values[1], race=projected,
            source_url=endpoint(race['race_id'], 'original'), captured_at=captures[0],
            companion_source_url=endpoint(race['race_id'], 'standard'), companion_captured_at=captures[1], now=parsed_at)
        del values, raw
        if original['status'] != 'AVAILABLE':raise _Stop('ORIGINAL_INCOMPLETE')
        generated = tick()
        packet = build_name_bound_inputs(record, original, race, baseline, binding,
            parents_read_at=parents, generated_at=generated, now=generated)
        return dict(status='COLLECTED', snapshot=packet, official_source_requests=count)
    except _Stop as exc:return stopped(str(exc))
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError, sqlite3.Error):
        return stopped('SOURCE_INVALID')
