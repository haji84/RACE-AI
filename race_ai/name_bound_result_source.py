"""One bounded official result attempt using an independent name projection.

Only normalized facts leave this worker. Its SQLite memory receipt is explicitly
nondurable; callers must independently measure their subsequent storage clocks.
"""
from datetime import datetime, timezone
from http.client import HTTPException
import sqlite3
from urllib import error

from .official_update_worker import fetch_update, reviewed_scope
from .official_race_updates import parse_update
from .official_racelist_adapter import MAX_BYTES
from . import official_observation_store as memory
from .tokuyama_day_worker import FetchResponse
from web import race_contract as facts
from web.name_bound_result import result_context, build_name_bound_result


def utc_now():
    return datetime.now(timezone.utc)


class _Stop(ValueError):
    pass


def collect_name_bound_result(race, forecast, *, parents_read_at, facts_review,
        execute=False, transport=None, clock=utc_now):
    """Validate before fetching, never retry, and count thrown attempts too."""
    count = 0

    def stopped(status):
        return dict(status=status, official_source_requests=count)

    if execute is not True:
        return stopped('DRY_RUN')
    try:
        day, close, _ = facts._program(race)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return stopped('INPUT_INVALID')
    previous = None

    def tick():
        nonlocal previous
        try:
            measured = facts._time(clock())
        except (ValueError, TypeError, AttributeError, OverflowError):
            raise _Stop('DAY_INVALID' if previous is None else 'SOURCE_INVALID')
        if measured.astimezone(facts.JST).date() != day:
            raise _Stop('DAY_INVALID')
        if previous is not None and measured < previous:
            raise _Stop('SOURCE_INVALID')
        if measured < close:
            raise _Stop('CUTOFF_NOT_REACHED')
        previous = measured
        return measured

    try:
        start = tick()
        try:
            _, _, _, projected, _ = result_context(race, forecast, start)
            parents = facts._time(parents_read_at)
            if not (close <= parents <= start and parents.astimezone(facts.JST).date() == day):
                raise ValueError('parents clock')
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError):
            return stopped('INPUT_INVALID')
        try:
            if facts_review.get('evidence_reference') != 'user-confirmation-2026-10-15-official-facts':
                raise ValueError('review reference')
            reviewed_scope(facts_review, day=day, venue=race['race_id'][9:11], kind='raceresult', now=start)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            return stopped('RIGHTS_BLOCKED')
        tick()
        url = facts._endpoint(race['race_id'], 'raceresult')
        count += 1
        try:
            response = (transport or fetch_update)(url, timeout=10, max_bytes=MAX_BYTES)
        except (error.URLError, OSError, TimeoutError, HTTPException):
            raise _Stop('SOURCE_UNAVAILABLE')
        except (ValueError, TypeError, AttributeError):
            raise _Stop('SOURCE_INVALID')
        captured = tick()
        if (not isinstance(response, FetchResponse) or type(response.status) is not int or response.status != 200
                or response.url != url or not isinstance(response.body, bytes) or not 0 < len(response.body) <= MAX_BYTES
                or not isinstance(response.content_type, str) or response.content_type.split(';')[0].strip().lower() != 'text/html'):
            raise _Stop('SOURCE_INVALID')
        observation = parse_update(response.body, kind='raceresult', day=day, venue=race['race_id'][9:11],
            race_no=int(race['race_id'][-2:]), source_url=url, captured_at=facts.stamp(captured), entries=projected['boats'])
        del response
        observation['rights_review'] = facts_review['evidence_reference']
        with sqlite3.connect(':memory:') as db:
            memory.setup_store(db)
            memory.save_observation(db, observation)
            checked_at = tick()
            record = memory.latest_observation(db, race['race_id'], 'raceresult', as_of=checked_at)
        if record is None:
            raise _Stop('SOURCE_INVALID')
        facts.validate_record(record, projected, checked_at, require_same_day=True)
        if (record['status'] != 'AVAILABLE' or not isinstance(record['data'], dict)
                or not record['data'].get('results')):
            raise _Stop('RESULT_PENDING')
        generated = tick()
        packet = build_name_bound_result(record, race, forecast,
            parents_read_at=parents, generated_at=generated, now=generated)
        return dict(status='COLLECTED', official_source_requests=count, snapshot=packet)
    except _Stop as exc:
        return stopped(str(exc))
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError, sqlite3.Error):
        return stopped('SOURCE_INVALID')
