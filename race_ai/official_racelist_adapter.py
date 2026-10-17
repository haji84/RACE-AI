"""Offline official common-site race-list parser.

The supplied body must establish the date, venue and selected race in its
schedule and race tabs. A request URL or detached link alone is not proof.
No collection, source retention, permission grant or publication happens here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
import hashlib
import math
import re
import unicodedata
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from .core import SourceError

HOST = 'www.boatrace.jp'
PATH = '/owpc/pc/race/racelist'
JST = ZoneInfo('Asia/Tokyo')
MAX_BYTES = 1_000_000


def endpoint(day: date, venue: str, race_no: int) -> str:
    if not re.fullmatch(r'0[1-9]|1[0-9]|2[0-4]', venue) or type(race_no) is not int or not 1 <= race_no <= 12:
        raise SourceError('invalid race identity')
    return f'https://{HOST}{PATH}?rno={race_no}&jcd={venue}&hd={day:%Y%m%d}'


def identity(url: str, *, path: str = PATH) -> tuple[str, str, int]:
    u = urlsplit(urljoin(f'https://{HOST}', url))
    q = parse_qs(u.query, keep_blank_values=True)
    if (u.scheme != 'https' or u.netloc != HOST or u.path != path or u.fragment
            or set(q) != {'rno', 'jcd', 'hd'} or any(len(v) != 1 for v in q.values())
            or not re.fullmatch(r'[0-9]{8}', q['hd'][0])
            or not re.fullmatch(r'0[1-9]|1[0-9]|2[0-4]', q['jcd'][0])
            or not re.fullmatch(r'[1-9]|1[0-2]', q['rno'][0])):
        raise SourceError('unexpected race URL identity')
    return q['hd'][0], q['jcd'][0], int(q['rno'][0])


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def text(self):
        return unicodedata.normalize('NFKC', ''.join(
            child.text() if isinstance(child, Node) else child for child in self.children))

    def has(self, css):
        return css in self.attrs.get('class', '').split()

    def find(self, tag=None, css=None):
        for child in self.children:
            if isinstance(child, Node):
                if (tag is None or child.tag == tag) and (css is None or child.has(css)):
                    yield child
                yield from child.find(tag, css)


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('root')
        self.stack = [self.root]
        self.invalid = False

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag == 'br':
            self.stack[-1].children.append(' ')
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        structural = {'table', 'thead', 'tbody', 'tr', 'td', 'th'}
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                if any(n.tag in structural for n in self.stack[i + 1:]):
                    self.invalid = True
                del self.stack[i:]
                return
        if tag in structural:
            self.invalid = True

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def one(nodes, description):
    values = list(nodes)
    if len(values) != 1:
        raise SourceError(f'expected one {description}')
    return values[0]


def numeric_tokens(node, count, *, maximum):
    tokens = node.text().split()
    if len(tokens) != count:
        raise SourceError('invalid numeric cell layout')
    try:
        values = [None if token in {'-', '--', '―', '—'} else float(token) for token in tokens]
    except ValueError as exc:
        raise SourceError('invalid numeric cell') from exc
    if any(value is not None and (not math.isfinite(value) or not 0 <= value <= maximum) for value in values):
        raise SourceError('numeric cell out of range')
    return values


def parse_official_racelist(raw: bytes, *, day: date, venue: str, race_no: int,
                           source_url: str, captured_at: str) -> dict:
    expected = (f'{day:%Y%m%d}', venue, race_no)
    endpoint(day, venue, race_no)
    if identity(source_url) != expected:
        raise SourceError('requested race identity mismatch')
    try:
        captured = datetime.fromisoformat(captured_at.replace('Z', '+00:00'))
        if captured.tzinfo is None or captured.astimezone(JST).date() != day:
            raise ValueError()
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES:
            raise ValueError()
        html = raw.decode('utf-8')
    except (ValueError, AttributeError, UnicodeError) as exc:
        raise SourceError('invalid source body or capture timestamp') from exc
    tree = Tree()
    tree.feed(html)
    if tree.invalid or any(n.tag in {'table', 'thead', 'tbody', 'tr', 'td', 'th'} for n in tree.stack):
        raise SourceError('malformed source table')
    # A single content frame prevents detached current-day navigation from
    # being used to establish the identity of another table elsewhere.
    frame = one(tree.root.find(css='contentsFrame1_inner'), 'race content frame')
    detail = one(frame.find(css='is-tableFixed__3rdadd'), 'entry table wrapper')
    table = one(detail.find('table'), 'entry table')
    heading = one(table.find('thead'), 'entry header').text()
    if not all(label in heading for label in ('枠', 'ボートレーサー', '全国', '当地', 'モーター', 'ボート')):
        raise SourceError('entry table header mismatch')
    schedules = [t for t in frame.find('table') if '締切予定時刻' in t.text() and t is not table]
    schedule = one(schedules, 'dated closing schedule')
    header = one(schedule.find('thead'), 'schedule header')
    race_headers = list(header.find('th'))[1:]
    if len(race_headers) != 12:
        raise SourceError('incomplete race schedule')
    selected = []
    for n, cell in enumerate(race_headers, 1):
        link = one(cell.find('a'), 'race schedule link')
        if identity(link.attrs.get('href', '')) != (expected[0], venue, n) or link.text().strip() != f'{n}R':
            raise SourceError('body date, venue or race mismatch')
        if not cell.has('is-thColor2') and not cell.has('is-thColor3'):
            selected.append(n)
    if selected != [race_no]:
        raise SourceError('selected race mismatch')
    times = list(one(schedule.find('tbody'), 'schedule times').find('td'))
    if len(times) != 13 or times[0].text().strip() != '締切予定時刻':
        raise SourceError('closing schedule layout mismatch')
    closing = times[race_no].text().strip()
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', closing):
        raise SourceError('closing time invalid')
    tabs = one(frame.find(css='tab3'), 'race tabs')
    links = list(tabs.find('a'))
    if not links:
        raise SourceError('race tabs lack identity')
    for link in links:
        path = urlsplit(urljoin(f'https://{HOST}', link.attrs.get('href', ''))).path
        if path not in {f'/owpc/pc/race/{name}' for name in ('odds3t', 'beforeinfo', 'pcexpect', 'myexpect', 'raceresult')} or identity(link.attrs.get('href', ''), path=path) != expected:
            raise SourceError('race tab identity mismatch')
    rid = f'{day:%Y%m%d}-{venue}-{race_no:02d}'
    closed_at = f'{day.isoformat()}T{closing}:00+09:00'
    boats = []
    for body in table.find('tbody'):
        row = next(body.find('tr'), None)
        cells = [n for n in row.children if isinstance(n, Node) and n.tag == 'td'] if row else []
        if len(cells) < 8:
            raise SourceError('entry row incomplete')
        lane = cells[0].text().strip()
        if not re.fullmatch(r'[1-6]', lane) or not cells[0].has('is-boatColor' + lane):
            raise SourceError('lane identity mismatch')
        registration = re.match(r'^\s*([0-9]{4})\s*/', cells[2].text())
        if not registration:
            raise SourceError('registration missing')
        registration = registration.group(1)
        profiles = list(cells[1].find('a')) + list(cells[2].find('a'))
        if len(profiles) != 2:
            raise SourceError('racer profile evidence incomplete')
        for profile in profiles:
            u = urlsplit(urljoin(f'https://{HOST}', profile.attrs.get('href', '')))
            if (u.scheme != 'https' or u.netloc != HOST or u.path != '/owpc/pc/data/racersearch/profile'
                    or u.fragment or parse_qs(u.query) != {'toban': [registration]}):
                raise SourceError('racer profile registration conflict')
        name = profiles[1].text().strip()
        if not name or len(name) > 128:
            raise SourceError('racer name missing')
        allocation = []
        for cell in cells[6:8]:
            tokens = cell.text().split()
            if len(tokens) != 3 or not re.fullmatch(r'[1-9][0-9]{0,2}', tokens[0]):
                raise SourceError('allocation number invalid')
            numeric_tokens(Node('stats', children=[' '.join(tokens[1:])]), 2, maximum=100)
            allocation.append(int(tokens[0]))
        national = numeric_tokens(cells[4], 3, maximum=100)
        local = numeric_tokens(cells[5], 3, maximum=100)
        if any(value is not None and value > 10 for value in (national[0], local[0])):
            raise SourceError('win rate invalid')
        st = cells[3].text().split()
        if len(st) != 3 or not re.fullmatch(r'F[0-9]+', st[0]) or not re.fullmatch(r'L[0-9]+', st[1]):
            raise SourceError('ST layout mismatch')
        average_st = numeric_tokens(Node('st', children=[st[2]]), 1, maximum=1)[0]
        current_text = ''.join(cell.text() for cell in cells[:8])
        entry_status = 'withdrawn' if any(marker in current_text for marker in ('欠場', '欠艇')) else 'listed'
        boats.append(dict(race_id=rid, lane=int(lane), racer_registration_id=registration,
                          name=name, motor_no=allocation[0], boat_no=allocation[1],
                          average_st=average_st, national_win_rate=national[0],
                          local_win_rate=local[0], entry_status=entry_status, closed_at=closed_at,
                          verified_source=True, source_url=source_url, captured_at=captured_at))
    if len(boats) != 6 or {boat['lane'] for boat in boats} != set(range(1, 7)):
        raise SourceError('six distinct lanes required')
    for field in ('racer_registration_id', 'motor_no', 'boat_no'):
        if len({boat[field] for boat in boats}) != 6:
            raise SourceError('duplicate racer or allocation')
    return dict(date_jst=day.isoformat(), venue=venue, race_id=rid, closed_at=closed_at,
                boats=sorted(boats, key=lambda b: b['lane']), source_url=source_url,
                source_sha256=hashlib.sha256(raw).hexdigest(), first_observed_at=captured_at,
                redistribution_authorized=False, status='OFFICIAL_BODY_IDENTITY_VERIFIED')
