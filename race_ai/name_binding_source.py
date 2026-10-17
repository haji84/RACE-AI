"""One authorized bounded racelist GET; raw bytes never leave this collector."""
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
import re
from urllib import error

from .official_racelist_adapter import parse_official_racelist, MAX_BYTES
from .official_racelist_worker import fetch_racelist
from .official_update_worker import reviewed_scope
from .tokuyama_day_worker import FetchResponse, TIMEOUT
from web import race_contract as facts
from web.name_binding_contract import build_name_binding, _context


MARGIN = timedelta(seconds=120)


def utc_now():
    return datetime.now(timezone.utc)


def collect_name_binding(race, *, baseline_snapshot_id, b_program_sha256, review,
                         execute=False, transport=None, clock=utc_now):
    """Dry-run by default; actual clocks are read again after GET and parsing."""
    def stopped(status):
        return {'status':status}
    try:
        day, close, _ = facts._program(race)
        # Validate the complete unchanged B digest and pins before any GET.
        facts.program_digest(race)
        if any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)
               for value in (baseline_snapshot_id, b_program_sha256)):
            return stopped('PROGRAM_INVALID')
        url = facts._endpoint(race['race_id'], 'racelist')
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return stopped('PROGRAM_INVALID')
    try:
        start = facts._time(clock())
        if start.astimezone(facts.JST).date() != day:
            return stopped('DAY_INVALID')
    except (ValueError, TypeError, AttributeError, OverflowError):
        return stopped('DAY_INVALID')
    try:
        _context(race, baseline_snapshot_id, b_program_sha256, start)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError):
        return stopped('PROGRAM_INVALID')
    if start + MARGIN >= close:
        return stopped('CUTOFF_PASSED')
    try:
        reviewed_scope(review, day=day, venue=race['race_id'][9:11], kind='racelist', now=start)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return stopped('SOURCE_RIGHTS_BLOCKED')
    if execute is not True:
        return dict(status='DRY_RUN', race_id=race['race_id'], source_url=url,
            baseline_snapshot_id=baseline_snapshot_id, b_program_sha256=b_program_sha256)
    try:
        response = (transport or fetch_racelist)(url, timeout=TIMEOUT, max_bytes=MAX_BYTES)
    except (error.URLError, OSError, TimeoutError, HTTPException):
        return stopped('SOURCE_UNAVAILABLE')
    except (ValueError, TypeError, AttributeError):
        return stopped('SOURCE_INVALID')
    try:
        captured = facts._time(clock())
        if captured.astimezone(facts.JST).date() != day:
            return stopped('DAY_INVALID')
        if captured < start:
            return stopped('SOURCE_INVALID')
        if captured >= close:
            return stopped('CUTOFF_PASSED')
    except (ValueError, TypeError, AttributeError, OverflowError):
        return stopped('SOURCE_INVALID')
    if (not isinstance(response, FetchResponse) or type(response.status) is not int or response.status != 200
            or response.url != url or not isinstance(response.body, bytes) or not 1 <= len(response.body) <= MAX_BYTES
            or not isinstance(response.content_type, str)
            or response.content_type.split(';')[0].strip().lower() != 'text/html'):
        return stopped('SOURCE_INVALID')
    try:
        detail = parse_official_racelist(response.body, day=day, venue=race['race_id'][9:11],
            race_no=int(race['race_id'][-2:]), source_url=url, captured_at=facts.stamp(captured))
    except (ValueError, TypeError, AttributeError, KeyError, UnicodeError):
        return stopped('SOURCE_INVALID')
    try:
        generated = facts._time(clock())
        if generated.astimezone(facts.JST).date() != day:
            return stopped('DAY_INVALID')
        if generated < captured:
            return stopped('SOURCE_INVALID')
        if generated >= close:
            return stopped('CUTOFF_PASSED')
    except (ValueError, TypeError, AttributeError, OverflowError):
        return stopped('SOURCE_INVALID')
    try:
        snapshot = build_name_binding(detail, race, baseline_snapshot_id=baseline_snapshot_id,
            b_program_sha256=b_program_sha256, generated_at=generated, now=generated)
    except ValueError:
        return stopped('NAME_BINDING_INVALID')
    return {'status':'COLLECTED', 'snapshot':snapshot}
