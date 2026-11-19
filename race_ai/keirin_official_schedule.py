"""Pure parsing of the one existing official SP calendar document.

Calendar ranges are candidate meetings, never a daily race roster. Published
form references remain opaque: this module submits nothing and constructs no
race URL. No network, forecast, source-rights grant or production input occurs.
"""
from calendar import monthrange
from datetime import date, datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re


OFFICIAL_DOCUMENT = 'https://keirin.jp/sp/raceschedule'
CALENDAR_SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_CALENDAR_DOCUMENT_V1'
PROJECTION_SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_CALENDAR_DAY_PROJECTION_V1'
DAY_ROSTER_SCHEMA = 'RACE_AI_KEIRIN_NON_RAKUTEN_OWNER_DAY_ROSTER_V1'
MAX_HTML_BYTES = 8_000_000
MAX_NODES = 50_000
MAX_DEPTH = 64
MAX_MEETINGS = 200
_VOID = frozenset(('area', 'base', 'br', 'embed', 'hr', 'img', 'input', 'link',
                   'meta', 'param', 'source', 'track', 'wbr'))
_VENUE = re.compile(r"location\.href='/sp/jyosellinfo\?jocd=([0-9]{2})'")
_REFERENCE = re.compile(r"lnk\.formlnk\('/sp/racelist','([A-Za-z0-9_-]{43})'\)")
_PERIOD = re.compile(r'([0-9]{2})/([0-9]{2})\(([月火水木金土日])\)～'
                     r'([0-9]{2})/([0-9]{2})\(([月火水木金土日])\)')
_SHA = re.compile(r'[a-f0-9]{64}\Z')


class OfficialCalendarError(ValueError):
    pass


def _need(value, reason):
    if not value:
        raise OfficialCalendarError('KEIRIN_OFFICIAL_CALENDAR_' + reason)


def admit_official_document(source_url):
    """Exact observed document only; this is not permission to fetch a host."""
    _need(type(source_url) is str and source_url == OFFICIAL_DOCUMENT, 'SOURCE_NOT_EXACT')
    return source_url


class _Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent = tag, attrs, parent
        self.children, self.parts = [], []
        self.closed = tag in _VOID


class _Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node('root', {})
        self.stack, self.nodes = [self.root], []

    def handle_starttag(self, tag, attrs):
        _need(len(self.nodes) < MAX_NODES and len(self.stack) < MAX_DEPTH, 'DOCUMENT_BOUND')
        _need(len(attrs) <= 32 and len(attrs) == len(dict(attrs)) and
              all(value is None or len(value) <= 2048 for key, value in attrs), 'ATTRIBUTE_BOUND_OR_DUPLICATE')
        node = _Node(tag, dict(attrs), self.stack[-1])
        node.parent.children.append(node)
        node.parent.parts.append(node)
        self.nodes.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack[index].closed = True
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        self.stack[-1].parts.append(data)


def _class(node, value):
    return value in _attribute(node, 'class').split()


def _attribute(node, name):
    value = node.attrs.get(name)
    return value if type(value) is str else ''


def _descendants(node):
    for child in node.children:
        yield child
        yield from _descendants(child)


def _text(node):
    return ''.join(part if type(part) is str else _text(part) for part in node.parts)


def _day(value):
    _need(type(value) is str, 'DAY_INVALID')
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise OfficialCalendarError('KEIRIN_OFFICIAL_CALENDAR_DAY_INVALID') from None
    _need(parsed.isoformat() == value, 'DAY_INVALID')
    return parsed


def _period(text, year, month):
    match = _PERIOD.fullmatch(re.sub(r'\s+', '', text))
    _need(match is not None, 'PERIOD_NOT_EXPLICIT')
    sm, sd, sw, em, ed, ew = match.groups()
    first, last = date(year, month, 1), date(year, month, monthrange(year, month)[1])
    candidates = []
    for sy in (year - 1, year, year + 1):
        for ey in (year - 1, year, year + 1):
            try:
                start, end = date(sy, int(sm), int(sd)), date(ey, int(em), int(ed))
            except ValueError:
                continue
            if (0 <= (end - start).days <= 31 and start <= last and end >= first and
                    '月火水木金土日'[start.weekday()] == sw and '月火水木金土日'[end.weekday()] == ew):
                candidates.append((start, end))
    _need(len(candidates) == 1, 'PERIOD_YEAR_OR_WEEKDAY_AMBIGUOUS')
    return candidates[0]


def parse_calendar(raw, *, source_url, body_sha256, received_at, now, http_status):
    """Bind exact bytes and actual receive clock; parse only published ranges."""
    admit_official_document(source_url)
    _need(type(http_status) is int and http_status == 200, 'HTTP_STATUS_NOT_OK')
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_HTML_BYTES, 'BODY_BOUND')
    _need(type(body_sha256) is str and _SHA.fullmatch(body_sha256) is not None and
          sha256(raw).hexdigest() == body_sha256, 'BODY_HASH_CHANGED')
    _need(isinstance(received_at, datetime) and received_at.utcoffset() is not None and
          isinstance(now, datetime) and now.utcoffset() is not None and received_at <= now,
          'ACTUAL_RECEIVE_CLOCK_INVALID')
    try:
        text = raw.decode('utf-8', errors='strict')
    except UnicodeDecodeError:
        raise OfficialCalendarError('KEIRIN_OFFICIAL_CALENDAR_CHARSET_UNVERIFIED') from None
    document = _Document()
    document.feed(text)
    document.close()
    controls = {}
    for name, pattern in (('dispYearData', r'20[0-9]{2}'), ('dispDayData', r'0[1-9]|1[0-2]')):
        found = [node for node in document.nodes if node.tag == 'input' and node.attrs.get('id') == name]
        _need(len(found) == 1 and re.fullmatch(pattern, _attribute(found[0], 'value')) is not None,
              'DISPLAYED_MONTH_NOT_EXPLICIT')
        controls[name] = int(found[0].attrs['value'])
    year, month = controls['dispYearData'], controls['dispDayData']
    headers, venues = {}, set()
    for node in document.nodes:
        if node.tag != 'div' or not _class(node, 'btn100p'):
            continue
        buttons = [child for child in _descendants(node) if child.tag == 'button']
        if len(buttons) != 1:
            continue
        match = _VENUE.fullmatch(_attribute(buttons[0], 'onclick'))
        if match is None:
            continue
        code = int(match[1])
        _need(buttons[0].closed and 1 <= code <= 99 and code not in venues, 'VENUE_HEADER_DUPLICATE_OR_INVALID')
        headers[id(node)] = code
        venues.add(code)
    tables = [node for node in document.nodes if node.tag == 'table' and _class(node, 'race_tbl')]
    _need(1 <= len(tables) <= MAX_MEETINGS and venues, 'NO_BOUNDED_CALENDAR_MEETINGS')
    meetings, references = [], set()
    for table in tables:
        _need(table.closed, 'MEETING_TABLE_INCOMPLETE')
        container = table.parent
        while container is not None and not (container.tag == 'div' and _class(container, 'dayDataDiv0201')):
            container = container.parent
        _need(container is not None and container.parent is not None, 'MEETING_VENUE_UNBOUND')
        siblings = container.parent.children
        index = siblings.index(container)
        header = siblings[index - 1] if index else None
        _need(header is not None and id(header) in headers, 'MEETING_VENUE_UNBOUND')
        periods = [node for node in _descendants(table) if node.tag == 'td' and _class(node, 'kikan')]
        _need(len(periods) == 1 and periods[0].closed, 'MEETING_PERIOD_MISSING_OR_DUPLICATE')
        start, end = _period(_text(periods[0]), year, month)
        reference = _attribute(table, 'onclick')
        _need(_REFERENCE.fullmatch(reference) is not None, 'MEETING_NAVIGATION_UNSUPPORTED')
        digest = sha256(reference.encode()).hexdigest()
        _need(digest not in references, 'MEETING_NAVIGATION_DUPLICATE')
        references.add(digest)
        meetings.append(dict(venue_code=headers[id(header)], start_date_jst=start.isoformat(),
            end_date_jst=end.isoformat(), navigation_reference_sha256=digest,
            navigation_kind='PUBLISHED_RACELIST_FORM_NOT_FOLLOWED', navigation_method_verified=False))
    meetings.sort(key=lambda row:(row['venue_code'], row['start_date_jst'], row['end_date_jst'],
                                 row['navigation_reference_sha256']))
    return dict(schema=CALENDAR_SCHEMA, source_url=source_url, source_sha256=body_sha256,
        captured_at=received_at.astimezone(timezone.utc).isoformat(), displayed_month=f'{year:04d}-{month:02d}',
        venue_codes=sorted(venues), meetings=meetings, upstream_publication_time_verified=False,
        individual_race_identities_verified=False, model_input_admission_allowed=False)


def project_day(calendar, *, event_day):
    """Partial interface for collect_owner_inputs; never emit an empty roster.

    The existing keirin_non_rakuten_day.read_saved_day_roster contract needs
    explicit race_id/venue_code/race_no rows. Its manifest stays None until
    an independently parsed individual-race document supplies those identities.
    This wrapper is not an input to keirin_daily_ledger.daily_run.
    """
    _need(type(calendar) is dict and calendar.get('schema') == CALENDAR_SCHEMA, 'PARSED_DOCUMENT_REQUIRED')
    admit_official_document(calendar.get('source_url'))
    day = _day(event_day)
    _need(type(calendar.get('displayed_month')) is str and
          calendar['displayed_month'] == event_day[:7], 'REQUESTED_MONTH_NOT_DISPLAYED')
    meetings = calendar.get('meetings')
    _need(type(meetings) is list and 1 <= len(meetings) <= MAX_MEETINGS, 'PARSED_MEETINGS_REQUIRED')
    candidates = [row for row in meetings if _day(row['start_date_jst']) <= day <= _day(row['end_date_jst'])]
    venues = sorted({row['venue_code'] for row in candidates})
    return dict(schema=PROJECTION_SCHEMA, state='HOLD_CALENDAR_ONLY_NO_INDIVIDUAL_RACE_IDENTITIES',
        event_date_jst=event_day, source_url=calendar['source_url'], source_sha256=calendar['source_sha256'],
        captured_at=calendar['captured_at'], displayed_month=calendar['displayed_month'],
        calendar_meetings_observed=len(meetings), calendar_venue_headers_observed=len(calendar['venue_codes']),
        calendar_meeting_candidates=candidates, calendar_meeting_candidate_count=len(candidates),
        calendar_venue_candidates=venues, calendar_venue_candidate_count=len(venues),
        calendar_period_inclusion_only=True, per_day_occurrence_independently_verified=False,
        target_day_roster_schema=DAY_ROSTER_SCHEMA, day_roster_manifest_ready=False, day_roster_manifest=None,
        missing_day_roster_fields=['race_id', 'race_no'], races=None, race_count=None,
        source_day_schedule_race_count=None, complete_national_coverage_verified=False,
        official_cutoffs_verified=False, model_features_available=False, full_347_437_audit_verified=False,
        provider_machine_rights_independently_verified=False, new_pre_race_inputs=0,
        actual_four_model_forecast_saved=False, provider_http_requests=0)


def safe_summary(projection):
    """Finite count-only output; source URL, form values and venue data stay private."""
    _need(type(projection) is dict and projection.get('schema') == PROJECTION_SCHEMA, 'PROJECTION_REQUIRED')
    counts = {}
    for key, limit in (('calendar_meetings_observed', MAX_MEETINGS),
                       ('calendar_venue_headers_observed', 99),
                       ('calendar_meeting_candidate_count', MAX_MEETINGS),
                       ('calendar_venue_candidate_count', 99)):
        value = projection.get(key)
        _need(type(value) is int and 0 <= value <= limit, 'COUNT_INVALID')
        counts[key] = value
    _need(counts['calendar_meeting_candidate_count'] <= counts['calendar_meetings_observed'] and
          counts['calendar_venue_candidate_count'] <= counts['calendar_meeting_candidate_count'] and
          counts['calendar_venue_candidate_count'] <= counts['calendar_venue_headers_observed'] and
          projection.get('race_count') is None and projection.get('day_roster_manifest') is None and
          projection.get('day_roster_manifest_ready') is False, 'CALENDAR_SCOPE_CHANGED')
    digest = projection.get('source_sha256')
    _need(type(digest) is str and _SHA.fullmatch(digest) is not None, 'BODY_HASH_CHANGED')
    return dict(schema='RACE_AI_KEIRIN_OFFICIAL_CALENDAR_COUNTS_V1',
        state='HOLD_CALENDAR_ONLY_NO_INDIVIDUAL_RACE_IDENTITIES', source_sha256=digest,
        calendar_meetings_observed=counts['calendar_meetings_observed'],
        calendar_venue_headers_observed=counts['calendar_venue_headers_observed'],
        calendar_meeting_candidates=counts['calendar_meeting_candidate_count'],
        calendar_venue_candidates=counts['calendar_venue_candidate_count'], individual_race_count=None,
        day_roster_manifest_ready=False, official_cutoffs_verified=False, full_347_437_audit_verified=False,
        new_pre_race_inputs=0, actual_four_model_forecast_saved=False, provider_http_requests=0)
