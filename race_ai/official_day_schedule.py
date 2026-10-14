"""Dated nationwide official index and source-bound venue availability.

An absent venue means no event only after a complete same-date authoritative
day listing has been verified. A timeout, empty page or missing table cannot
establish that status. Source collection is opt-in and rights-scoped.
"""
from datetime import date, datetime, timezone
import hashlib
import re
from urllib import error, request
from urllib.parse import parse_qs, urlsplit, urljoin

from .core import SourceError
from .official_racelist_adapter import Tree, HOST, JST, MAX_BYTES, identity, one
from .tokuyama_day_worker import FetchResponse, NoRedirects, TIMEOUT
from .venue_source_rights import decision_for

PATH = '/owpc/pc/race/index'
SOURCE_SCOPE = f'https://{HOST}{PATH}'


def endpoint(day):
    return f'{SOURCE_SCOPE}?hd={day:%Y%m%d}'


def parse_day_schedule(raw, *, day, source_url, observed_at):
    if source_url != endpoint(day) or not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES:
        raise SourceError('unexpected schedule source')
    observed = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
    if observed.tzinfo is None or observed.astimezone(JST).date() != day:
        raise SourceError('schedule observation day invalid')
    tree = Tree()
    tree.feed(raw.decode('utf-8'))
    if tree.invalid or any(n.tag in {'table', 'thead', 'tbody', 'tr', 'td', 'th'} for n in tree.stack):
        raise SourceError('schedule table malformed')
    frame = one(tree.root.find(css='contentsFrame1_inner'), 'schedule content frame')
    title = one(frame.find(css='title2_mainLabel'), 'dated schedule title')
    if title.text().strip() != f'{day.month}月{day.day}日のレース情報':
        raise SourceError('schedule title date mismatch')
    refresh = one(one(frame.find(css='btnGroup3_refreshBtn'), 'schedule refresh').find('a'), 'refresh URL')
    if urljoin(f'https://{HOST}', refresh.attrs.get('href', '')) != source_url:
        raise SourceError('schedule body year/date unverified')
    table = one(frame.find('table'), 'nationwide schedule table')
    headings = ' '.join(one(table.find('thead'), 'schedule header').text().split())
    if not all(label in headings for label in ('レース場', '進行状況', '開催期間/日次', 'レース別情報')):
        raise SourceError('schedule header mismatch')
    notes = one(frame.find(css='notes1'), 'completed schedule notes')
    if '締切予定時刻は締切5分前より赤く表示されます。' not in notes.text():
        raise SourceError('schedule completeness unverified')
    active = {}
    for body in table.find('tbody'):
        row = next(body.find('tr'), None)
        if row is None:
            raise SourceError('empty schedule row')
        images = [image for image in row.find('img') if re.fullmatch(r'/static_extra/pc/images/text_place1_[0-9]{2}\.png', image.attrs.get('src', ''))]
        image = one(images, 'venue identity image')
        code = image.attrs['src'][-6:-4]
        if code not in {f'{n:02d}' for n in range(1, 25)} or code in active:
            raise SourceError('invalid or duplicate scheduled venue')
        links = [link for link in row.find('a') if urlsplit(link.attrs.get('href', '')).path == '/owpc/pc/race/raceindex']
        link = one(links, 'dated meeting link')
        u = urlsplit(urljoin(f'https://{HOST}', link.attrs.get('href', '')))
        if u.scheme != 'https' or u.netloc != HOST or u.fragment or parse_qs(u.query) != {'jcd': [code], 'hd': [f'{day:%Y%m%d}']}:
            raise SourceError('schedule meeting date or venue mismatch')
        entries = [link for link in row.find('a') if urlsplit(link.attrs.get('href', '')).path == '/owpc/pc/race/racelist']
        entry = one(entries, 'dated entry link')
        hd, venue, number = identity(entry.attrs.get('href', ''))
        if (hd, venue) != (f'{day:%Y%m%d}', code):
            raise SourceError('schedule entry identity mismatch')
        active[code] = dict(meeting_title=link.text().strip(), current_race_no=number)
    # The observed official page lists active venues. An unexplained empty
    # table is not accepted as evidence that all twenty-four venues are closed.
    if not active:
        raise SourceError('empty nationwide schedule is unverified')
    digest = hashlib.sha256(raw).hexdigest()
    venues = []
    for code in (f'{n:02d}' for n in range(1, 25)):
        scheduled = code in active
        venues.append(dict(venue=code, status='SCHEDULED' if scheduled else 'NO_EVENT',
            no_event=not scheduled, schedule_verified=True,
            schedule_basis='LISTED_IN_COMPLETE_DAY_INDEX' if scheduled else 'NOT_LISTED_IN_COMPLETE_DAY_INDEX',
            schedule_source_url=source_url, schedule_source_sha256=digest,
            schedule_observed_at=observed_at, races=[], **active.get(code, {})))
    return dict(date_jst=day.isoformat(), source_url=source_url, source_sha256=digest,
                first_observed_at=observed_at, upstream_published_at=None,
                active_venues=sorted(active), venues=venues, schedule_verified=True,
                status='OFFICIAL_DAY_SCHEDULE_VERIFIED', redistribution_authorized=False)


def fetch_schedule(url, *, timeout=TIMEOUT, max_bytes=MAX_BYTES):
    u = urlsplit(url)
    q = parse_qs(u.query)
    try:
        day = datetime.strptime(q['hd'][0], '%Y%m%d').date()
    except (KeyError, ValueError, IndexError) as exc:
        raise SourceError('schedule source date invalid') from exc
    if url != endpoint(day) or timeout != TIMEOUT or max_bytes != MAX_BYTES:
        raise SourceError('unexpected schedule fetch endpoint or bounds')
    req = request.Request(url, headers={'User-Agent': 'RACE-AI-authorized-day-worker/0.15 (one-schedule)', 'Accept': 'text/html'})
    with request.build_opener(NoRedirects).open(req, timeout=timeout) as response:
        return FetchResponse(response.read(max_bytes + 1), response.geturl(), response.status, response.headers.get('Content-Type', ''))


def collect_day_schedule(day, *, rights, execute=False, now=None, transport=None):
    report = dict(date_jst=day.isoformat(), source_url=endpoint(day), redistribution_authorized=False)
    if not execute:
        return {**report, 'status': 'DRY_RUN', 'network_requests': 0}
    supplied_clock = now is not None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.astimezone(JST).date() != day:
        return {**report, 'status': 'DAY_INVALID'}
    try:
        for code in (f'{n:02d}' for n in range(1, 25)):
            if decision_for(rights, code, 'facts_ingest') != 'allowed':
                raise ValueError()
            record = next(r for r in rights if r.venue_code == code and r.purpose == 'facts_ingest')
            if record.source_url not in (endpoint(day), SOURCE_SCOPE) or datetime.fromisoformat(record.reviewed_at.replace('Z', '+00:00')) > now:
                raise ValueError()
    except (ValueError, TypeError, AttributeError, StopIteration):
        return {**report, 'status': 'SOURCE_RIGHTS_BLOCKED'}
    try:
        response = (transport or fetch_schedule)(endpoint(day), timeout=TIMEOUT, max_bytes=MAX_BYTES)
        if (not isinstance(response, FetchResponse) or response.status != 200 or response.url != endpoint(day)
                or not isinstance(response.body, bytes) or len(response.body) > MAX_BYTES
                or not isinstance(response.content_type, str) or response.content_type.split(';')[0].lower().strip() != 'text/html'):
            raise SourceError('invalid schedule response')
        observed = now if supplied_clock else datetime.now(timezone.utc)
        return parse_day_schedule(response.body, day=day, source_url=endpoint(day), observed_at=observed.isoformat())
    except (error.URLError, OSError, TimeoutError):
        return {**report, 'status': 'SOURCE_UNAVAILABLE'}
    except (ValueError, UnicodeError, TypeError, AttributeError):
        return {**report, 'status': 'SOURCE_INVALID'}


def merge_schedule_programs(schedule, programs=None, *, errors=None):
    if schedule.get('status') != 'OFFICIAL_DAY_SCHEDULE_VERIFIED' or schedule.get('schedule_verified') is not True:
        raise SourceError('verified schedule required')
    errors = errors or {}
    if programs is not None and programs.get('date_jst') != schedule['date_jst']:
        raise SourceError('program and schedule day mismatch')
    known = {v['venue']: v for v in (programs or {}).get('venues', [])}
    if any(code not in schedule['active_venues'] for code in known) or len(known) != len((programs or {}).get('venues', [])):
        raise SourceError('program and schedule venue conflict')
    source_keys = ('source_url', 'source_sha256', 'first_observed_at')
    sources = [{key: schedule[key] for key in source_keys}]
    if programs:
        sources.append({key: programs[key] for key in source_keys})
    venues = []
    for venue in schedule['venues']:
        code = venue['venue']
        races = known.get(code, {}).get('races', [])
        if venue['no_event']:
            venues.append(venue)
            continue
        status = 'ERROR' if code in errors else ('READY' if len(races) == 12 else ('PARTIAL' if races else 'UNOBTAINED'))
        if programs:
            races = [{**race, 'program_source_url': programs['source_url'], 'program_source_sha256': programs['source_sha256'],
                      'program_observed_at': programs['first_observed_at']} for race in races]
        venues.append({**venue, 'status': status, 'races': races,
                       **({'source_error': errors[code]} if code in errors else {})})
    count = sum(len(v['races']) for v in venues)
    return {**schedule, 'venues': venues, 'sources': sources,
        'races': count, 'complete_six_boat_races': sum(len(r['boats']) == 6 for v in venues for r in v['races']),
        'last_observed_at': max((s['first_observed_at'] for s in sources), key=lambda value: datetime.fromisoformat(value.replace('Z', '+00:00'))),
        'status': 'NORMALIZED_REQUIRES_PUBLICATION_APPROVAL', 'provider': 'OFFICIAL_DAY_INDEX_AND_B_PROGRAM',
        'redistribution_authorized': False}
