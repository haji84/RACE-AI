"""Display-only starter identities from linked public Kdreams meeting pages."""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import re
from unicodedata import category, normalize
from urllib.parse import urljoin, urlsplit

from . import keirin_dossier_race_context as context
from . import keirin_result_unread_racecard as racecard


SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_REFERENCE_STARTERS_V1'
ORIGIN = 'https://keirin.kdreams.jp'
MEETING = re.compile(r'/([a-z0-9-]+)/racecard/([0-9]{2})(20[0-9]{6})([0-9]{2})00/')
TRACKING = re.compile(r'l-id=[A-Za-z0-9_-]{1,100}')
HEADINGS = ('予想','好気合','総評','枠番','車番','選手名','府県','年齢','期別','級班','脚質')
STYLES = frozenset(('逃','追','両'))


def _need(ok, reason):
    if not ok:
        raise ValueError('PUBLIC_MEETING_ROSTER_' + reason)


def _calendar_url(day):
    return ORIGIN + '/kaisai/' + context._day(day).replace('-', '/') + '/'


def _published_text(text, maximum):
    value = ' '.join(text.split())
    _need(0 < len(value) <= maximum and not any(category(c).startswith('C') or c in '<>' for c in value),
          'RIDER_TEXT')
    return value


def _identity(name, region, cohort):
    name = ''.join(normalize('NFKC', name).split())
    region = ''.join(normalize('NFKC', region).split())
    if region == '東京都' or (len(region) >= 3 and region.endswith(('県','府'))):
        region = region[:-1]
    return name, region, cohort


def registration_lookup(checked_profiles):
    """Index trusted name, prefecture, cohort and registration tuples without ambiguous assignments."""
    candidates, identities = defaultdict(set), defaultdict(set)
    for name, region, cohort, registration in checked_profiles:
        _need(type(name) is str and type(region) is str and type(cohort) is int and 1 <= cohort <= 998 and
              type(registration) is str and re.fullmatch(r'[0-9]{6}',registration) and registration != '000000',
              'IDENTITY_EVIDENCE')
        key = _identity(_published_text(name,80),_published_text(region,32),cohort)
        candidates[key].add(registration)
        identities[registration].add(key)
    unique = {}
    for key, values in candidates.items():
        if len(values) == 1:
            registration, = values
            if len(identities[registration]) == 1:
                unique[key] = registration
    return unique


def _meeting_on_day(path, day):
    match = MEETING.fullmatch(path)
    if not match:
        return None
    _, venue, beginning, index = match.groups()
    try:
        first = date(int(beginning[:4]),int(beginning[4:6]),int(beginning[6:]))
        actual = first + timedelta(days=int(index)-1)
    except (ValueError,OverflowError):
        return None
    return match if venue != '00' and 1 <= int(index) <= 7 and actual.isoformat() == day else None


def parse_calendar(raw, *, day):
    """Return clean public URLs actually linked by the selected day's calendar."""
    url = _calendar_url(day)
    document = racecard._document(raw,url)
    selected_date = date.fromisoformat(day)
    title = f'{selected_date.year}年{selected_date.month}月{selected_date.day}日開催一覧'
    _need(sum(racecard._compact(racecard._text(node)) in (title,'本日'+title)
              for node in document.select('h2')) == 1, 'CALENDAR_DATE')
    links = {}
    for anchor in document.select('a[href]'):
        source = urlsplit(urljoin(url,anchor['href']))
        if (source.scheme != 'https' or source.netloc != 'keirin.kdreams.jp' or source.fragment or
                source.query and not TRACKING.fullmatch(source.query)):
            continue
        meeting = _meeting_on_day(source.path,day)
        if meeting is None:
            continue
        venue = meeting[2]
        linked = ORIGIN + source.path
        _need(links.get(venue,linked) == linked, 'DUPLICATE_MEETING')
        links[venue] = linked
    _need(1 <= len(links) <= 32, 'MEETINGS')
    return links


def _roster_table(table, registrations):
    rows = racecard._table_rows(table)
    headings = [child for row in rows for child in row.find_all('th',recursive=False)]
    _need(tuple(racecard._compact(racecard._text(cell)) for cell in headings)
          in (HEADINGS, HEADINGS + ('誘導員',)), 'TABLE_HEADINGS')
    riders, seen = [], set()
    for row in rows:
        cells = row.find_all('td',recursive=False)
        if not cells:
            continue
        car = row.select_one(':scope > td.num')
        rider = row.select_one(':scope > td.rider')
        if car is None and rider is None:
            _need(any(racecard._compact(racecard._text(cell)) == '誘導員' for cell in
                      row.find_all('th',recursive=False)), 'NON_RIDER_ROW')
            continue
        _need(car is not None and rider is not None and
              len(cells) - cells.index(car) == 7 and cells.index(rider) == cells.index(car)+1, 'RIDER_CELLS')
        values = cells[cells.index(car):]
        classes = set(row.get('class', ()))
        if classes == {'missing'}:
            _need(all(not racecard._text(cell) for cell in values), 'PLACEHOLDER')
            continue
        raw_number = racecard._text(car)
        _need(racecard.CAR.fullmatch(raw_number) and raw_number not in seen, 'RIDER_NUMBER')
        seen.add(raw_number)
        if racecard._withdrawn(row,rider):
            continue
        active_class = 'n'+raw_number
        if classes == {active_class,'missing'}:
            caution = rider.select(':scope > span.caution')
            _need(len(caution) == 1 and racecard._text(caution[0]) == '(欠車)', 'RIDER_STATUS')
            continue
        _need(classes == {active_class}, 'RIDER_STATUS')
        name = _published_text(racecard._name(rider),80)
        region = _published_text(racecard._text(values[2]),32)
        term = racecard._text(values[4])
        _need(re.fullmatch(r'[0-9]{1,3}',term), 'RIDER_COHORT')
        cohort = int(term) if 1 <= int(term) <= 998 else None
        style = racecard._text(values[6])
        _need(style in STYLES, 'RIDER_STYLE')
        registration = registrations.get(_identity(name,region,cohort)) if cohort is not None else None
        _need(registration is None or (type(registration) is str and re.fullmatch(r'[0-9]{6}',registration) and
                                      registration != '000000'), 'REGISTRATION')
        riders.append(dict(number=int(raw_number),name=name,registration=registration,
                           region=region,style=style,cohort=cohort))
    registrations_seen = [r['registration'] for r in riders if r['registration'] is not None]
    # A published five-car programme can leave four runners after a confirmed withdrawal.
    _need(5 <= len(seen) <= 9 and 4 <= len(riders) and
          len(set(registrations_seen)) == len(registrations_seen), 'ROSTER')
    return sorted(riders,key=lambda rider:rider['number'])


def parse_meeting(raw, *, day, url, observed_at, registrations=None):
    """Bind each visible starter table to its exact linked race on the selected meeting day."""
    compact_day = context._day(day).replace('-','')
    _need(type(url) is str and url.startswith(ORIGIN+'/'), 'MEETING_URL')
    meeting = _meeting_on_day(url.removeprefix(ORIGIN),day)
    _need(meeting is not None, 'MEETING_URL')
    venue = meeting[2]
    source_at = context._aware(observed_at).isoformat()
    document = racecard._document(raw,url)
    listing = document.select('ul.racecard_list')
    _need(len(listing) == 1, 'RACE_LIST')
    detail_base = url.replace('/racecard/','/racedetail/').removesuffix('/')
    races = {}
    for row in listing[0].find_all('li',recursive=False):
        if row.get('class') == ['page-break'] and not row.get_text(strip=True) and not row.select('a,table'):
            continue
        link = row.select(':scope > p.race > a[href]')
        _need(len(link) == 1, 'DETAIL_LINK')
        candidate = link[0]
        year_race = candidate.select_one(':scope > span.num')
        _need(year_race is not None, 'DETAIL_NUMBER')
        label = re.fullmatch(r'([1-9]|1[0-2])R',racecard._text(year_race))
        _need(label is not None, 'DETAIL_NUMBER')
        number = int(label[1])
        _need(urljoin(url,candidate['href']) == f'{detail_base}{number:02d}/' and number not in races, 'DETAIL_LINK')
        tables = row.select('div.racecard_list_container > div.racecard_table > table')
        _need(len(tables) == 1, 'PUBLISHED_TABLE')
        races[number] = _roster_table(tables[0], registrations or {})
    _need(1 <= len(races) <= 12 and set(races) == set(range(1,len(races)+1)), 'RACE_SEQUENCE')
    digest = sha256(raw).hexdigest()
    return [dict(race_id=f'{compact_day}{venue}{number:02d}',source_at=source_at,source_url=url,
                 source_sha256=digest,riders=races[number]) for number in sorted(races)]


def collect_day(day, *, fetch=None, clock=None, registrations=None):
    """Fetch each linked meeting once with the existing bounded public HTML transport."""
    from scripts.keirin_capture_public_two_sources import fetch_once

    request = fetch_once if fetch is None else fetch
    now = (lambda: datetime.now(timezone.utc)) if clock is None else clock
    meetings = parse_calendar(request(_calendar_url(day)), day=day)
    rows = []
    for url in (meetings[venue] for venue in sorted(meetings)):
        raw = request(url)
        rows.extend(parse_meeting(raw,day=day,url=url,observed_at=now(),registrations=registrations))
    posted = context._aware(now())
    _need(all(context._aware(row['source_at']) <= posted for row in rows), 'PUBLICATION_CLOCK')
    return dict(schema=SCHEMA,day=day,published_at=posted.isoformat(),races=rows)
