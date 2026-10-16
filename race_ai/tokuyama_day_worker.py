"""Bounded, explicitly authorized Tokuyama day collection, without publication.

The configured rights registry is supplied by an independently reviewed worker
operator. An index alone stays partial: registration IDs and motors require
the existing verified-detail join. This module writes no source or output files,
uploads nothing, and never grants factual redistribution rights.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import re
import unicodedata
from urllib import error, parse, request
from zoneinfo import ZoneInfo

from .core import SourceError
from .venue_detail_join import join_verified_details
from .venue_source_rights import RightsRecord, decision_for
from .venue_tokuyama_adapter import TableParser, parse_tokuyama_race_index

HOST = 'www.boatrace-tokuyama.jp'
SOURCE_SCOPE = f'https://{HOST}/modules/raceinfo/?page=index_raceindex'
MAX_BYTES = 1_000_000
TIMEOUT = 10
JST = ZoneInfo('Asia/Tokyo')


def endpoint(day: date) -> str:
    return f'https://{HOST}/modules/raceinfo/?page=index_raceindex&targetday={day:%Y%m%d}'


@dataclass(frozen=True)
class FetchResponse:
    body: bytes
    url: str
    status: int
    content_type: str


class NoRedirects(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceError('redirect rejected')


def fetch_index(url: str, *, timeout: int = TIMEOUT,
                max_bytes: int = MAX_BYTES) -> FetchResponse:
    """One bounded GET; called only after ingestion approval by the collector."""
    u = parse.urlsplit(url)
    q = parse.parse_qs(u.query)
    if (u.scheme != 'https' or u.netloc != HOST or u.path != '/modules/raceinfo/'
            or set(q) != {'page', 'targetday'} or q.get('page') != ['index_raceindex']):
        raise SourceError('unexpected source endpoint')
    try:
        target_day = datetime.strptime(q['targetday'][0], '%Y%m%d').date()
    except (ValueError, KeyError, IndexError) as exc:
        raise SourceError('invalid source date') from exc
    if url != endpoint(target_day) or timeout != TIMEOUT or max_bytes != MAX_BYTES:
        raise SourceError('unexpected fetch bounds')
    opener = request.build_opener(NoRedirects)
    req = request.Request(url, headers={
        'User-Agent': 'RACE-AI-authorized-day-worker/0.13 (one-page)',
        'Accept': 'text/html',
    })
    with opener.open(req, timeout=timeout) as response:
        return FetchResponse(response.read(max_bytes + 1), response.geturl(),
                             response.status, response.headers.get('Content-Type', ''))


class RaceLinks(TableParser):
    """Bind each parsed race row to the dated link in its first cell.

    Use the index parser's exact table/row/cell boundaries. Links in navigation
    or racer cells cannot establish the identity of the parsed race header.
    """
    def __init__(self):
        super().__init__()
        self.races = []
        self.row_links = []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag == 'tr':
            self.row_links = []
        if (tag != 'a' or self.table is None or self.row is None
                or self.row or self.cell is None):
            return
        href = dict(attrs).get('href', '')
        u = parse.urlsplit(href)
        if (u.scheme != 'https' or u.netloc != 'www.boatrace.jp'
                or u.path != '/owpc/pc/race/racelist'):
            return
        q = parse.parse_qs(u.query)
        if set(q) != {'hd', 'jcd', 'rno'} or any(len(v) != 1 for v in q.values()):
            return
        if q['jcd'] == ['18'] and q['rno'][0].isdigit():
            self.row_links.append((q['hd'][0], int(q['rno'][0])))

    def handle_endtag(self, tag):
        if tag == 'tr' and self.table is not None and self.row:
            label = unicodedata.normalize('NFKC', self.row[0]).strip()
            if len(self.row) == 7 and re.fullmatch(r'(?:[1-9]|1[0-2])R', label):
                self.races.append((int(label[:-1]), tuple(self.row_links)))
        super().handle_endtag(tag)


def collect_tokuyama_day(day: date, *, rights: list[RightsRecord],
                         now: datetime | None = None, transport=None,
                         details: list[dict] | None = None) -> dict:
    """Collect one current-day index or return an explicit failure/partial state.

    An allowed ingestion record must match this exact source URL or SOURCE_SCOPE
    (the fixed race-index page across dates); records for
    media or publication do not authorize the GET. ``details`` are separately
    acquired, independently verified, same-day race/lane records. They cannot
    authorize this source or publication. No response here is a public feed.
    """
    supplied_clock = now is not None
    now = now or datetime.now(timezone.utc)
    url = endpoint(day)
    report = dict(date_jst=day.isoformat(), source_url=url,
                  redistribution_authorized=False)
    def stopped(status):
        return {**report, 'status': status}

    if now.tzinfo is None or now.astimezone(JST).date() != day:
        return stopped('DAY_INVALID')
    try:
        if decision_for(rights, '18', 'facts_ingest') != 'allowed':
            return stopped('SOURCE_RIGHTS_BLOCKED')
        record = next(r for r in rights if r.venue_code == '18' and r.purpose == 'facts_ingest')
        reviewed = datetime.fromisoformat(record.reviewed_at.replace('Z', '+00:00'))
        if record.source_url not in (url, SOURCE_SCOPE) or reviewed > now:
            return stopped('SOURCE_RIGHTS_BLOCKED')
    except (ValueError, TypeError, AttributeError, StopIteration):
        return stopped('SOURCE_RIGHTS_BLOCKED')

    try:
        response = (transport or fetch_index)(url, timeout=TIMEOUT, max_bytes=MAX_BYTES)
    except (error.URLError, TimeoutError, OSError):
        return stopped('SOURCE_UNAVAILABLE')
    except SourceError:
        return stopped('SOURCE_INVALID')
    if (not isinstance(response, FetchResponse) or response.status != 200
            or response.url != url or not isinstance(response.body, bytes)
            or len(response.body) > MAX_BYTES
            or not isinstance(response.content_type, str)
            or response.content_type.split(';')[0].strip().lower() != 'text/html'):
        return stopped('SOURCE_INVALID')
    observed = now if supplied_clock else datetime.now(timezone.utc)
    if observed.astimezone(JST).date() != day:
        return stopped('DAY_INVALID')
    report.update(source_sha256=hashlib.sha256(response.body).hexdigest(),
                  first_observed_at=observed.astimezone(timezone.utc).isoformat(),
                  upstream_published_at=None)
    try:
        html = response.body.decode('utf-8')
        index = parse_tokuyama_race_index(html, day=day, source_url=url)
        expected = {f'{day:%Y%m%d}-18-{n:02d}' for n in range(1, 13)}
        if len(index['races']) != 12 or {r['race_id'] for r in index['races']} != expected:
            return stopped('SOURCE_INVALID')
        links = RaceLinks()
        links.feed(html)
        expected_links = [(n, ((f'{day:%Y%m%d}', n),)) for n in range(1, 13)]
        if sorted(links.races) != expected_links:
            return stopped('SOURCE_DATE_UNVERIFIED')
    except (UnicodeError, SourceError, ValueError):
        return stopped('SOURCE_INVALID')
    report['race_count'] = 12
    if details is None:
        return {**report, 'status': 'PARTIAL_INDEX_DETAILS_REQUIRED',
                'partial_index': index,
                'missing_fields': ['racer_registration_id', 'motor_no', 'closed_at']}
    try:
        for row in details:
            captured = datetime.fromisoformat(row['captured_at'].replace('Z', '+00:00'))
            if captured.tzinfo is None or captured > now or captured.astimezone(JST).date() != day:
                raise SourceError('detail timestamp invalid')
        joined = join_verified_details(index, details, day=day)
        for race in joined['races']:
            for field in ('racer_registration_id', 'motor_no'):
                if len({boat[field] for boat in race['boats']}) != 6:
                    raise SourceError('duplicate racer or motor in a single race')
    except (SourceError, ValueError, TypeError, KeyError, AttributeError):
        return stopped('DETAILS_INVALID')
    races = [{**race, 'closed_at': None, 'preview_available': False,
              'result_available': False} for race in joined['races']]
    snapshot = {**report, 'provider': 'TOKUYAMA_OFFICIAL_INDEX_WITH_VERIFIED_DETAILS',
                'status': 'NORMALIZED_REQUIRES_PUBLICATION_APPROVAL',
                'venues': [{'venue': '18', 'races': races}], 'races': 12,
                'complete_six_boat_races': 12,
                'current_motor_cycle_known': False,
                'original_exhibition_supported': False,
                'official_result_verified': False}
    return {**report, 'status': snapshot['status'], 'snapshot': snapshot}
