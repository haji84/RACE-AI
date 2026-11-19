"""Ordinary, fail-closed public SP navigation and private partial receipts.

Only the default Playwright Chromium session is used.  The injectable factory
is a zero-argument callable returning a synchronous Playwright Browser (offline
tests use its public interface).  No caller-supplied transport, scripts, form
tokens, browser options, or URLs are accepted.  Returned values are fixed codes,
counts and hashes; provider documents and parsed records stay in the inbox.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import isfinite
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import parse_qsl, urlsplit

from . import keirin_official_schedule as calendar
from . import keirin_official_sp_receipt as receipt


SAFE_STATES = frozenset((
    'OFFICIAL_SP_PARTIAL_INPUT_CAPTURED', 'HOLD_OFFICIAL_SP_BUDGET',
    'HOLD_OFFICIAL_SP_DENIED', 'HOLD_OFFICIAL_SP_NO_CURRENT_MEETINGS',
    'HOLD_OFFICIAL_SP_SOURCE_LAYOUT', 'HOLD_OFFICIAL_SP_TRANSPORT',
    'HOLD_OFFICIAL_SP_LOCAL_RUNTIME',
))
_PARTIAL = 'OFFICIAL_SP_PARTIAL_INPUT_CAPTURED'
_BUDGET = 'HOLD_OFFICIAL_SP_BUDGET'
_DENIED = 'HOLD_OFFICIAL_SP_DENIED'
_LAYOUT = 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT'
_TRANSPORT = 'HOLD_OFFICIAL_SP_TRANSPORT'
_LOCAL = 'HOLD_OFFICIAL_SP_LOCAL_RUNTIME'
_DENIALS = frozenset((401, 403, 407, 429))
_CHALLENGE = re.compile(r'captcha|turnstile|challenge-platform|just a moment|'
                        r'browser[ ._-]?check|verify (?:you are|your browser)', re.I)
_PRIVATE_PATH = re.compile(r'(?:^|/)(?:login|signin|authentication|captcha|challenge|'
                           r'vote|voting|touhyou)(?:/|$)', re.I)


class _Stop(Exception):
    pass


def _hash(raw):
    return sha256(raw).hexdigest()


def _need(condition):
    if not condition:
        raise _Stop()


def _published_analytics(request):
    return (request.method == 'GET' and request.resource_type == 'xhr'
            and request.url == 'https://keirin.jp/sp/ana' and request.post_data in (None, ''))


def _document(raw):
    _need(type(raw) is bytes and 0 < len(raw) <= calendar.MAX_HTML_BYTES)
    text = raw.decode('utf-8', 'strict')
    _need(_CHALLENGE.search(text) is None)
    document = calendar._Document()
    document.feed(text)
    document.close()
    _need(not any(n.tag == 'base' or
              (n.tag == 'input' and n.attrs.get('type', '').lower() == 'password')
              for n in document.nodes))
    return document


class _Inbox:
    def __init__(self, value):
        self.fd = None
        self.saved = 0
        path = Path(value).absolute()
        # Do not resolve a symlink and silently trust its target.
        for parent in (path, *path.parents):
            _need(not parent.is_symlink())
            _need(not (parent / '.git').exists())
        checkout = Path(__file__).resolve().parents[1]
        _need(not path.is_relative_to(checkout))
        if not path.exists():
            path.mkdir(mode=0o700)
        info = path.lstat()
        _need(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
              and info.st_uid == os.geteuid())
        self.fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        held = os.fstat(self.fd)
        _need((held.st_dev, held.st_ino) == (info.st_dev, info.st_ino))

    def save(self, raw, extension):
        name = _hash(raw) + extension
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=self.fd)
        except FileExistsError:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                _need(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                      and info.st_uid == os.geteuid() and stream.read() == raw)
            return
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
        self.saved += 1

    def json(self, value):
        self.save((json.dumps(value, ensure_ascii=False, sort_keys=True,
                              allow_nan=False) + '\n').encode(), '.json')

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class _Collector:
    def __init__(self, inbox, clock, monotonic, budget_seconds):
        self.inbox, self.clock, self.monotonic = inbox, clock, monotonic
        self.started = monotonic()
        _need(type(self.started) in (int, float) and isfinite(self.started))
        self.deadline = self.started + budget_seconds
        self.day = self.now().astimezone(receipt.JST).date().isoformat()
        self.state = None
        self.page = self.context = None
        self.creating_page = self.closing = False
        self.armed = None
        self.records, self.pending_resources = {}, []
        self.out = dict(schema='RACE_AI_KEIRIN_OFFICIAL_SP_BROWSER_COUNTS_V1',
            state=_LOCAL, calendar_meetings_observed=0, day_venue_count=None,
            day_race_count=None, race_lists_verified=0, details_verified=0,
            riders_verified=0, future_detail_count=0, expired_detail_count=0,
            http_status_counts={}, navigation_request_count=0, resource_request_count=0,
            unknown_transmitted_status_count=0, blocked_before_send=0, provider_denied=False,
            provider_denial_http_status_counts={'HTTP_403': 0, 'HTTP_429': 0, 'UNKNOWN': 0},
            budget_exhausted=False,
            private_source_files_saved=0, source_sha256=None,
            source_admission=False, model_input_admission=False,
            new_forecasts=0, winticket_requests=0)

    def now(self):
        value = self.clock()
        _need(isinstance(value, datetime) and value.utcoffset() is not None)
        return value.astimezone(timezone.utc)

    def stop(self, state):
        if self.state is None or state == _DENIED:
            self.state = state

    def check(self):
        if self.state:
            raise _Stop()
        value = self.monotonic()
        _need(type(value) in (int, float) and isfinite(value) and value >= self.started)
        if value >= self.deadline:
            self.out['budget_exhausted'] = True
            self.stop(_BUDGET)
            raise _Stop()
        _need(self.now().astimezone(receipt.JST).date().isoformat() == self.day)

    def timeout(self):
        self.check()
        return max(1, min(20_000, int((self.deadline - self.monotonic()) * 1000)))

    def dom(self):
        return _document(self.page.content().encode('utf-8'))

    def route(self, route):
        req = route.request
        try:
            self.check()
            url = urlsplit(req.url)
            _need(url.scheme == 'https' and url.hostname in ('keirin.jp', 'www.keirin.jp')
                  and url.port is None and url.username is None and url.password is None
                  and _PRIVATE_PATH.search(url.path) is None and req.redirected_from is None)
            navigation = req.is_navigation_request()
            if navigation:
                _need(self.page is not None and req.frame == self.page.main_frame
                      and self.armed is not None and url.netloc == 'keirin.jp'
                      and not url.query and not url.fragment)
                path, method, opaque = self.armed
                _need(url.path == path and req.method == method)
                if method == 'POST':
                    body = req.post_data
                    _need(type(body) is str and len(body) <= 2048)
                    fields = parse_qsl(body, keep_blank_values=True, strict_parsing=True,
                                       encoding='utf-8', errors='strict', max_num_fields=3)
                    expected_disp = 'SJ0301' if path == '/sp/racelist' else 'SJ0315'
                    _need(fields == [('encp', opaque), ('disp', expected_disp)])
                    # This immutable snapshot came from the fresh public control.
                    # DOM reads here deadlock during Chromium's navigation commit.
                else:
                    _need(req.post_data in (None, ''))
                self.armed = None  # One actual navigation per fresh public click.
            else:
                # All three observed public documents issue this analytics GET
                # themselves. It grants no permission for JSON APIs or other XHR.
                _need(req.method == 'GET' and (req.resource_type not in
                      ('xhr', 'fetch', 'eventsource', 'websocket') or _published_analytics(req))
                      and url.path != '/sp/json')
            record = dict(request=req, navigation=navigation, status=None)
            self.records[id(req)] = record
            key = 'navigation_request_count' if navigation else 'resource_request_count'
            self.out[key] += 1
            try:
                route.continue_()
            except Exception:
                self.stop(_TRANSPORT)
        except Exception:
            if self.state is None:
                self.stop(_LAYOUT)
            self.out['blocked_before_send'] += 1
            try:
                route.abort()
            except Exception:
                self.stop(_TRANSPORT)

    def response(self, response):
        req = response.request
        record = self.records.get(id(req))
        if record is None:
            self.stop(_LAYOUT)
            return
        if record['status'] is not None:
            return
        status = response.status
        if type(status) is not int or not 100 <= status <= 599:
            self.stop(_TRANSPORT)
            return
        record['status'] = status
        key = str(status)
        counts = self.out['http_status_counts']
        counts[key] = counts.get(key, 0) + 1
        if status in _DENIALS:
            self.out['provider_denied'] = True
            denied = self.out['provider_denial_http_status_counts']
            denied['HTTP_' + key if status in (403, 429) else 'UNKNOWN'] += 1
            self.stop(_DENIED)
        elif 300 <= status < 400:
            self.stop(_LAYOUT)
        elif not 200 <= status < 300:
            self.stop(_TRANSPORT)
        if record['navigation'] and status != 200:
            self.stop(_TRANSPORT)
        # Status handling must stay synchronous: reading a body in this callback
        # yields to Playwright and can finish after the navigation's caller.
        headers = response.headers
        is_html = 'text/html' in headers.get('content-type', '').lower()
        if not record['navigation'] and (is_html or req.resource_type in ('script', 'stylesheet')
                                         or _published_analytics(req)):
            self.pending_resources.append(response)

    def response_body(self, response):
        length = response.headers.get('content-length')
        _need(length is None or (length.isascii() and length.isdigit()
                                and int(length) <= calendar.MAX_HTML_BYTES))
        raw = response.body()
        _need(type(raw) is bytes and len(raw) <= calendar.MAX_HTML_BYTES)
        _need(_CHALLENGE.search(raw.decode('utf-8', 'replace')) is None)
        return raw

    def drain_resources(self):
        while self.pending_resources:
            response = self.pending_resources.pop(0)
            if response.status == 200 or (_published_analytics(response.request)
                                           and 200 <= response.status < 300):
                self.response_body(response)

    def capture_document(self, response):
        _need(response is not None)
        record = self.records.get(id(response.request))
        _need(record is not None and record['navigation'])
        raw, observed = self.response_body(response), self.now()
        self.inbox.save(raw, '.bin')
        self.inbox.json(dict(schema='RACE_AI_KEIRIN_OFFICIAL_SP_HTTP_RECEIPT_V1',
            body_sha256=_hash(raw), body_bytes=len(raw), http_status=response.status,
            received_at=observed.isoformat(), source_url=response.url,
            source_method=response.request.method, private_only=True))
        return dict(raw=raw, observed_at=observed, status=response.status,
                    expected_sha256=_hash(raw))

    def new_page(self):
        self.check()
        if self.page:
            self.drain_resources()
            self.check()
            self.page.close()
        self.creating_page = True
        try:
            self.page = self.context.new_page()
        finally:
            self.creating_page = False
        self.page.set_default_timeout(self.timeout())
        self.page.set_default_navigation_timeout(self.timeout())
        self.page.on('dialog', self.dialog)
        self.page.on('download', lambda _: self.stop(_LAYOUT))
        return self.page

    def extra_page(self, page):
        if self.creating_page:
            self.page = page
        else:
            self.stop(_LAYOUT)
            page.close()

    def dialog(self, dialog):
        self.stop(_LAYOUT)
        dialog.dismiss()

    def websocket(self, socket):
        self.stop(_LAYOUT)
        socket.close()

    def failed(self, _):
        if not self.closing:
            self.stop(_TRANSPORT)

    def navigate(self, path, method, action, opaque=None, scope=None):
        self.check()
        _need(self.armed is None)
        self.drain_resources()
        if scope is not None:
            scope()
        self.armed = (path, method, opaque)
        with self.page.expect_navigation(wait_until='load', timeout=self.timeout()) as navigation:
            action()
        result = self.capture_document(navigation.value)
        self.drain_resources()
        if self.state:
            raise _Stop()
        _need(self.armed is None)
        _need(result['status'] == 200)
        _document(result['raw'])
        return result

    def load_calendar(self):
        page = self.new_page()
        doc = self.navigate('/sp/raceschedule', 'GET', lambda: page.goto(
            calendar.OFFICIAL_DOCUMENT, wait_until='load', timeout=self.timeout()))
        raw, observed = doc['raw'], doc['observed_at']
        parsed = calendar.parse_calendar(raw, source_url=calendar.OFFICIAL_DOCUMENT,
            body_sha256=doc['expected_sha256'], received_at=observed, now=self.now(), http_status=200)
        projection = calendar.project_day(parsed, event_day=self.day)
        self.inbox.json(parsed)
        self.inbox.json(projection)
        self.out['calendar_meetings_observed'] = len(parsed['meetings'])
        if self.out['source_sha256'] is None:
            self.out['source_sha256'] = doc['expected_sha256']
        bound = dict(raw_bytes=raw, expected_sha256=doc['expected_sha256'], observed_at=observed)
        return bound, projection

    def calendar_target(self, bound, candidate):
        digest = candidate['navigation_reference_sha256']
        original = _document(bound['raw_bytes'])
        fresh = self.dom()
        def find(document):
            matches = [n for n in document.nodes if n.tag == 'table'
                and calendar._class(n, 'race_tbl')
                and _hash(calendar._attribute(n, 'onclick').encode()) == digest]
            _need(len(matches) == 1)
            return matches[0]
        node, current = find(original), find(fresh)
        _need(calendar._attribute(node, 'onclick') == calendar._attribute(current, 'onclick'))
        token = calendar._REFERENCE.fullmatch(calendar._attribute(node, 'onclick'))
        _need(token is not None)
        # Bind the actual fresh table's enclosing venue/period as well as token.
        fresh_raw = self.page.content().encode()
        fresh_calendar = calendar.parse_calendar(fresh_raw,
            source_url=calendar.OFFICIAL_DOCUMENT,
            body_sha256=_hash(fresh_raw), received_at=bound['observed_at'],
            now=self.now(), http_status=200)
        _need([m for m in fresh_calendar['meetings']
               if m['navigation_reference_sha256'] == digest] == [candidate])
        tables = self.page.locator('table.race_tbl')
        locators = [tables.nth(i) for i in range(tables.count()) if
                    _hash((tables.nth(i).get_attribute('onclick') or '').encode()) == digest]
        _need(len(locators) == 1)
        return node, locators[0], token[1]

    def open_meeting(self, bound, candidate):
        node, target, opaque = self.calendar_target(bound, candidate)
        if not target.is_visible():
            parent = node.parent
            while parent and not (parent.tag == 'div' and parent.attrs.get('id')
                                  and calendar._class(parent, 'dispoff')):
                parent = parent.parent
            _need(parent is not None)
            region = parent.attrs['id']
            _need(re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,79}', region) is not None)
            document = _document(bound['raw_bytes'])
            controls = [n for n in document.nodes if n.tag == 'div'
                and calendar._class(n, 'accordion_menu')
                and re.search(r'\bbopen\(', calendar._attribute(n, 'onclick'))
                and re.search(r'[\x27\"]'+re.escape(region)+r'[\x27\"]',
                              calendar._attribute(n, 'onclick'))]
            _need(len(controls) == 1)
            handler = calendar._attribute(controls[0], 'onclick')
            expanders = self.page.locator('div.accordion_menu')
            exact = [expanders.nth(i) for i in range(expanders.count())
                     if expanders.nth(i).get_attribute('onclick') == handler]
            _need(len(exact) == 1)
            exact[0].click(timeout=self.timeout())
            # Locators are live; reacquire to also support rendered replacement.
            _, target, opaque = self.calendar_target(bound, candidate)
            target.wait_for(state='visible', timeout=self.timeout())
        _need(target.is_visible())
        def scope():
            _, latest, value = self.calendar_target(bound, candidate)
            _need(value == opaque and latest.is_visible())
        doc = self.navigate('/sp/racelist', 'POST', lambda: target.click(timeout=self.timeout()),
                            opaque, scope)
        parsed = receipt.parse_race_list(doc['raw'], expected_day=self.day,
            expected_venue_code=candidate['venue_code'], observed_at=doc['observed_at'],
            expected_sha256=doc['expected_sha256'], calendar_receipt=bound)
        self.verify_list_dom(parsed, doc, bound)
        self.inbox.json(parsed)
        return parsed, doc

    def verify_list_dom(self, parsed, doc, bound):
        raw = self.page.content().encode()
        current = receipt.parse_race_list(raw, expected_day=self.day,
            expected_venue_code=parsed['venue_code'], observed_at=doc['observed_at'],
            expected_sha256=_hash(raw), calendar_receipt=bound)
        _need(current['race_references'] == parsed['race_references']
              and current['day_roster_manifest']['races'] == parsed['day_roster_manifest']['races'])
        data = receipt._embedded(_document(doc['raw']))
        header = data['SC0201']['C0201data']
        for identifier, field in (('hhJoName', 'joName'), ('hhKaisaihi', 'txtEventDate')):
            visible_header = self.page.locator('#' + identifier)
            _need(visible_header.count() == 1 and
                  receipt._norm(visible_header.text_content() or '') == receipt._norm(header[field]))
        groups = data['SJ0301']['kaisaiDayList']
        rendered = self.page.locator('#setRaceProgram > div')
        _need(rendered.count() == len(groups))
        selected = None
        for i, group in enumerate(groups):
            dom = rendered.nth(i)
            label = dom.locator('.divRaceNitiji')
            _need(label.count() == 1 and receipt._norm(label.text_content() or '') ==
                  receipt._norm(group['strKaisaiNitijName']))
            buttons = dom.locator('button')
            rows = group['raceProgramList']
            _need(buttons.count() == len(rows))
            for j, record in enumerate(rows):
                button = buttons.nth(j)
                number = button.locator('.raceEveNamewid')
                _need(number.count() == 1 and receipt._norm(number.text_content() or '') ==
                      receipt._norm(record['strRaceNo']))
                parent = button.locator('..')
                inputs = parent.locator('input[type="hidden"]')
                _need(parent.locator('button').count() == 1 and inputs.count() == 3
                      and [inputs.nth(k).input_value() for k in range(3)] ==
                      [record['strRaceLnk'], record['strRaceLnkPrm'], record['strRaceLnkKbn']])
            day = datetime.fromisoformat(self.day)
            label_match = re.fullmatch(r'(?:初日|最終日|[2-9]日目)\(([0-9]{1,2})/([0-9]{1,2})\)',
                                      receipt._norm(group['strKaisaiNitijName']))
            _need(label_match is not None)
            if tuple(map(int, label_match.groups())) == (day.month, day.day):
                _need(selected is None)
                selected = i
        _need(selected is not None)
        return selected

    def open_detail(self, parsed, doc, bound, number):
        group_index = self.verify_list_dom(parsed, doc, bound)
        group = self.page.locator('#setRaceProgram > div').nth(group_index)
        reference = next(r for r in parsed['race_references'] if r['race_no'] == number)
        _need(reference['path'] == '/sp/race' and reference['link_kind'] == '1')
        group_id = group.get_attribute('id')
        _need(type(group_id) is str and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,79}', group_id))
        handler = "location.href='#" + group_id + "'"
        buttons = self.page.locator('button')
        date_buttons = [buttons.nth(i) for i in range(buttons.count())
                        if buttons.nth(i).get_attribute('onclick') == handler]
        _need(len(date_buttons) == 1 and date_buttons[0].is_visible())
        date_buttons[0].click(timeout=self.timeout())
        self.check()
        def selected_button():
            index = self.verify_list_dom(parsed, doc, bound)
            rows = self.page.locator('#setRaceProgram > div').nth(index).locator('button')
            exact = [rows.nth(i) for i in range(rows.count()) if
                receipt._norm(rows.nth(i).locator('.raceEveNamewid').text_content() or '') == str(number)]
            _need(len(exact) == 1 and exact[0].is_visible())
            inputs = exact[0].locator('..').locator('input[type="hidden"]')
            _need(inputs.count() == 3 and [inputs.nth(k).input_value() for k in range(3)] ==
                  ['/sp/race', reference['opaque_reference'], '1'])
            return exact[0]
        button = selected_button()
        detail = self.navigate('/sp/race', 'POST', lambda: button.click(timeout=self.timeout()),
                              reference['opaque_reference'], selected_button)
        result = receipt.parse_race_detail(detail['raw'], expected_day=self.day,
            expected_venue_code=parsed['venue_code'], expected_race_number=number,
            observed_at=detail['observed_at'], expected_sha256=detail['expected_sha256'],
            calendar_receipt=bound)
        self.inbox.json(result)
        self.out['details_verified'] += 1
        self.out['riders_verified'] += len(result['riders'])
        future = self.now() + timedelta(seconds=390) < datetime.fromisoformat(result['official_cutoff_at'])
        self.out['future_detail_count' if future else 'expired_detail_count'] += 1

    @staticmethod
    def meeting_scope(projection):
        return sorted((r['venue_code'], r['start_date_jst'], r['end_date_jst'])
                      for r in projection['calendar_meeting_candidates'])

    def run(self, browser):
        self.context = browser.new_context(service_workers='block', accept_downloads=False)
        self.context.route('**/*', self.route)
        self.context.route_web_socket('**/*', self.websocket)
        self.context.on('response', self.response)
        self.context.on('requestfailed', self.failed)
        self.context.on('page', self.extra_page)
        bound, projection = self.load_calendar()
        candidates = projection['calendar_meeting_candidates']
        if not candidates:
            self.stop('HOLD_OFFICIAL_SP_NO_CURRENT_MEETINGS')
            return
        original_scope = self.meeting_scope(projection)
        verified = {}
        for i, candidate in enumerate(candidates):
            if i:
                bound, current = self.load_calendar()
                _need(self.meeting_scope(current) == original_scope)
                candidate = next(r for r in current['calendar_meeting_candidates']
                                 if r['venue_code'] == candidate['venue_code'])
            parsed, _ = self.open_meeting(bound, candidate)
            _need(candidate['venue_code'] not in verified)
            verified[candidate['venue_code']] = parsed
            self.out['race_lists_verified'] += 1
        self.out['day_venue_count'] = len(verified)
        self.out['day_race_count'] = sum(row['race_count'] for row in verified.values())
        self.check()
        # Lists contain no per-race clocks. Later numbers are visited first, then
        # interleaved across venues, without inventing any pre-cutoff eligibility.
        pending = sorted(((r['race_no'], code) for code, row in verified.items()
                          for r in row['race_references']), key=lambda item: (-item[0], item[1]))
        for number, code in pending:
            self.check()
            bound, current = self.load_calendar()
            _need(self.meeting_scope(current) == original_scope)
            candidate = next(r for r in current['calendar_meeting_candidates'] if r['venue_code'] == code)
            parsed, doc = self.open_meeting(bound, candidate)
            if parsed['day_roster_manifest']['races'] != verified[code]['day_roster_manifest']['races']:
                self.out['day_venue_count'] = self.out['day_race_count'] = None
                raise _Stop()
            self.open_detail(parsed, doc, bound, number)
        self.check()

    def report(self):
        unknown = sum(record['status'] is None for record in self.records.values())
        self.out['unknown_transmitted_status_count'] = unknown
        if unknown and self.state is None:
            self.stop(_TRANSPORT)
        self.out['state'] = self.state or _PARTIAL
        self.out['private_source_files_saved'] = self.inbox.saved
        return self.out


def collect_official_sp(inbox, *, clock=None, monotonic=None, budget_seconds=240,
                        browser_factory=None):
    """Collect a budgeted, private partial prefix through published DOM clicks.

    `future_detail_count` requires actual now + 390 seconds before the official
    cutoff; `expired_detail_count` includes past and too-close cutoffs. Neither
    counter grants source/model admission. Day denominators stay null until all
    selected calendar meeting lists have been independently bound and verified.
    """
    private = collector = browser = runtime = None
    # Constructing an empty report must also work when the caller's clock/path
    # is invalid or Playwright is absent; no dependency is imported for fixtures.
    fallback = dict(schema='RACE_AI_KEIRIN_OFFICIAL_SP_BROWSER_COUNTS_V1', state=_LOCAL,
        calendar_meetings_observed=0, day_venue_count=None, day_race_count=None,
        race_lists_verified=0, details_verified=0, riders_verified=0,
        future_detail_count=0, expired_detail_count=0, http_status_counts={},
        navigation_request_count=0, resource_request_count=0,
        unknown_transmitted_status_count=0, blocked_before_send=0, provider_denied=False,
        provider_denial_http_status_counts={'HTTP_403': 0, 'HTTP_429': 0, 'UNKNOWN': 0},
        budget_exhausted=False,
        private_source_files_saved=0, source_sha256=None, source_admission=False,
        model_input_admission=False, new_forecasts=0, winticket_requests=0)
    try:
        _need(type(budget_seconds) in (int, float) and isfinite(budget_seconds)
              and 1 <= budget_seconds <= 600)
        private = _Inbox(inbox)
        collector = _Collector(private, clock or (lambda: datetime.now(timezone.utc)),
                               monotonic or time.monotonic, budget_seconds)
        if browser_factory is None:
            from playwright.sync_api import sync_playwright
            runtime = sync_playwright().start()
            browser = runtime.chromium.launch(headless=True)
        else:
            browser = browser_factory()
        try:
            collector.run(browser)
        except _Stop:
            collector.stop(_LAYOUT)
        except (calendar.OfficialCalendarError, receipt.OfficialSPReceiptError,
                UnicodeError, ValueError, KeyError, StopIteration):
            collector.stop(_LAYOUT)
        except Exception:
            collector.stop(_TRANSPORT)
    except Exception:
        if collector:
            collector.stop(_LOCAL)
    finally:
        if collector:
            collector.closing = True
            for handle in (collector.page, collector.context, browser):
                if handle is not None:
                    try:
                        handle.close()
                    except Exception:
                        collector.stop(_LOCAL)
        elif browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if runtime:
            try:
                runtime.stop()
            except Exception:
                if collector:
                    collector.stop(_LOCAL)
        if private:
            private.close()
    return collector.report() if collector else fallback
