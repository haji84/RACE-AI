"""One official detail GET, gated by independently supplied ingestion rights.

The venue-index permission does not cover this common-site endpoint. No
default approval records, source originals, background jobs or uploads exist.
"""
from datetime import date, datetime, timezone
from urllib import error, request

from .core import SourceError
from .official_racelist_adapter import HOST, PATH, MAX_BYTES, JST, endpoint, identity, parse_official_racelist
from .tokuyama_day_worker import FetchResponse, NoRedirects, TIMEOUT
from .venue_source_rights import decision_for


def source_scope(venue: str) -> str:
    endpoint(date(2000, 1, 1), venue, 1)
    return f'https://{HOST}{PATH}?jcd={venue}'


def fetch_racelist(url, *, timeout=TIMEOUT, max_bytes=MAX_BYTES):
    hd, venue, number = identity(url)
    try:
        day = datetime.strptime(hd, '%Y%m%d').date()
    except ValueError as exc:
        raise SourceError('invalid detail date') from exc
    if url != endpoint(day, venue, number) or timeout != TIMEOUT or max_bytes != MAX_BYTES:
        raise SourceError('unexpected detail endpoint or fetch bounds')
    req = request.Request(url, headers={'User-Agent': 'RACE-AI-authorized-day-worker/0.14 (bounded-detail)', 'Accept': 'text/html'})
    with request.build_opener(NoRedirects).open(req, timeout=timeout) as response:
        return FetchResponse(response.read(max_bytes + 1), response.geturl(), response.status,
                             response.headers.get('Content-Type', ''))


def collect_official_racelist(day, venue, race_no, *, rights, now=None, transport=None):
    url = endpoint(day, venue, race_no)
    report = dict(date_jst=day.isoformat(), source_url=url, redistribution_authorized=False)
    def stopped(status):
        return {**report, 'status': status}
    supplied_clock = now is not None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.astimezone(JST).date() != day:
        return stopped('DAY_INVALID')
    try:
        if decision_for(rights, venue, 'facts_ingest') != 'allowed':
            return stopped('SOURCE_RIGHTS_BLOCKED')
        record = next(r for r in rights if r.venue_code == venue and r.purpose == 'facts_ingest')
        reviewed = datetime.fromisoformat(record.reviewed_at.replace('Z', '+00:00'))
        if record.source_url not in (url, source_scope(venue)) or reviewed > now:
            return stopped('SOURCE_RIGHTS_BLOCKED')
    except (ValueError, TypeError, AttributeError, StopIteration):
        return stopped('SOURCE_RIGHTS_BLOCKED')
    try:
        response = (transport or fetch_racelist)(url, timeout=TIMEOUT, max_bytes=MAX_BYTES)
    except (error.URLError, OSError, TimeoutError):
        return stopped('SOURCE_UNAVAILABLE')
    except SourceError:
        return stopped('SOURCE_INVALID')
    if (not isinstance(response, FetchResponse) or response.status != 200 or response.url != url
            or not isinstance(response.body, bytes) or len(response.body) > MAX_BYTES
            or not isinstance(response.content_type, str)
            or response.content_type.split(';')[0].strip().lower() != 'text/html'):
        return stopped('SOURCE_INVALID')
    observed = now if supplied_clock else datetime.now(timezone.utc)
    if observed.astimezone(JST).date() != day:
        return stopped('DAY_INVALID')
    try:
        detail = parse_official_racelist(response.body, day=day, venue=venue, race_no=race_no,
                                         source_url=url, captured_at=observed.isoformat())
    except (SourceError, TypeError, AttributeError):
        return stopped('SOURCE_INVALID')
    return {**report, 'status': detail['status'], 'detail': detail}
