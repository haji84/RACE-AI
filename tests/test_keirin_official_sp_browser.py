"""Invented public UI/browser fixtures; these tests never contact a provider."""
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import importlib
import importlib.util
import io
import json
from pathlib import Path
import re
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit

from race_ai import keirin_official_schedule as calendar
from tests.test_keirin_official_schedule import meeting, page as calendar_page, venue
from tests.test_keirin_official_sp_receipt import detail_data, html, list_data


MODULE = 'race_ai.keirin_official_sp_browser'
AT = datetime(2030, 1, 15, 2, tzinfo=timezone.utc)
URL = calendar.OFFICIAL_DOCUMENT


def calendar_html(venues=(98, 99)):
    groups = [venue(code, [meeting('2030-01-14', '2030-01-16', chr(65+i)*43)])
              for i, code in enumerate(venues)]
    raw = calendar_page(groups)
    return raw.replace(b'<div class="dispoff" id="invented_region">',
        b'<div class="accordion_menu" onclick="bopen(\'t_invented\')">Open</div>'
        b'<div class="dispoff" id="t_invented">')


def list_html(code=98, count=3):
    data = list_data()
    for group in data['SJ0301']['kaisaiDayList']:
        group['raceProgramList'] = group['raceProgramList'][:count]
    # The same published name in this invented calendar is intentional.
    data['SC0201']['C0201data']['joName'] = '架空会場'
    return html(data)


def render_list(raw):
    d = calendar._Document(); d.feed(raw.decode())
    from race_ai.keirin_official_sp_receipt import _embedded
    data = _embedded(d)
    parts = []
    for i, group in enumerate(data['SJ0301']['kaisaiDayList']):
        identifier = 'Nitiji_' + str(i+1)
        parts.append('<div id="' + identifier + '"><div class="divRaceNitiji">'
                     + group['strKaisaiNitijName'] + '</div><table>')
        for record in group['raceProgramList']:
            parts.append('<tr><td><button type="button"><span class="raceEveNamewid">'
                         + record['strRaceNo'] + '</span>' + record['strSyumokuName']
                         + '</button>')
            if record.get('strRaceLnk'):
                parts.append('<input type="hidden" value="' + record['strRaceLnk']
                             + '"><input type="hidden" value="' + record['strRaceLnkPrm']
                             + '"><input type="hidden" value="' + record.get('strRaceLnkKbn', '')
                             + '">')
            parts.append('</td></tr>')
        parts.append('</table></div>')
    buttons = ''.join('<button class="btn onbtn" onclick="location.href=\'#Nitiji_'
                      + str(i+1) + '\'">' + group['strKaisaiNitijName'] + '</button>'
                      for i, group in enumerate(data['SJ0301']['kaisaiDayList']))
    header = data['SC0201']['C0201data']
    return raw.decode().replace('</body>', '<span id="hhJoName">' + header['joName']
                               + '</span><span id="hhKaisaihi">' + header['txtEventDate']
                               + '</span><div id="setRaceNitiji">' + buttons
                               + '</div><div id="setRaceProgram">' + ''.join(parts)
                               + '</div></body>')


def detail_html(number, count=7):
    data = detail_data(count)
    header = data['SC0201']['C0201data']
    header['selRaceNo'] = number
    # One expired / too-close race and later, future races; clocks remain distinct.
    bet = '11:05' if number == 1 else '15:47'
    header.update(aftBetDate='20300115' + bet.replace(':', ''), aftBetTime=bet,
                  aftStartTime='11:08' if number == 1 else '15:50')
    return html(data)


class Request:
    def __init__(self, page, url, method='GET', post_data=None, navigation=True,
                 resource_type='document', redirected_from=None):
        self.frame = page.main_frame
        self.url, self.method, self.post_data = url, method, post_data
        self.resource_type, self.redirected_from = resource_type, redirected_from
        self.navigation = navigation
        self._browser = page.browser
        self._page = page

    def is_navigation_request(self):
        return self.navigation


class Response:
    def __init__(self, request, raw, status=200):
        self.request, self.url, self.status = request, request.url, status
        self.raw = raw
        self.headers = {'content-type': 'text/html; charset=utf-8'}
        if request.resource_type == 'xhr' and request._browser.resource_headers is not None:
            self.headers = request._browser.resource_headers

    def body(self):
        b = self.request._browser
        if self.request._page.closed:
            raise RuntimeError('RESPONSE_BODY_UNAVAILABLE_AFTER_PAGE_CLOSE')
        if b.prevent_callback_body_read and b.in_response_callback:
            raise RuntimeError('REENTRANT_RESPONSE_BODY_NOT_READY')
        return self.raw

    def finished(self):
        return None


class Route:
    def __init__(self, page, request, raw, status):
        self.page, self.request, self.raw, self.status = page, request, raw, status
        self.aborted = False

    def abort(self):
        self.aborted = True
        self.page.browser.blocked += 1

    def continue_(self):
        b = self.page.browser
        b.sent.append(self.request)
        if self.status is None:
            raise RuntimeError('INVENTED_PRIVATE_TRANSPORT_FAILURE')
        response = Response(self.request, self.raw, self.status)
        if b.hold_resource_responses and not self.request.navigation:
            b.held_resources.append(response)
            return None
        b.in_response_callback = True
        try:
            self.page.emit('response', response)
            self.page.context.emit('response', response)
        finally:
            b.in_response_callback = False
        return None


def descendants(node):
    yield from calendar._descendants(node)


class Locator:
    def __init__(self, page, nodes):
        self.page, self.nodes = page, nodes

    def count(self):
        return len(self.nodes)

    def nth(self, i):
        return Locator(self.page, self.nodes[i:i+1])

    @property
    def first(self):
        return self.nth(0)

    def locator(self, selector):
        if selector == '..':
            return Locator(self.page, [n.parent for n in self.nodes])
        if selector in ('xpath=ancestor::tr', 'xpath=ancestor::tr[1]'):
            rows = []
            for n in self.nodes:
                p = n.parent
                while p is not None and p.tag != 'tr': p = p.parent
                if p: rows.append(p)
            return Locator(self.page, rows)
        return self.page.select(selector, [x for n in self.nodes for x in descendants(n)])

    def get_attribute(self, key, **_):
        return self.nodes[0].attrs.get(key)

    def input_value(self, **_):
        return self.get_attribute('value')

    def text_content(self, **_):
        if (self.page.browser.late_analytics and self.nodes
                and 'divRaceNitiji' in self.nodes[0].attrs.get('class', '').split()):
            self.page.browser.late_analytics = False
            self.page.transmit('/sp/ana', b'/* invented late public response */',
                               navigation=False, resource_type='xhr')
        return calendar._text(self.nodes[0])

    def all_text_contents(self):
        return [calendar._text(n) for n in self.nodes]

    def is_visible(self):
        if not self.nodes: return False
        p = self.nodes[0]
        while p:
            if 'dispoff' in p.attrs.get('class', '').split(): return False
            p = p.parent
        return True

    def wait_for(self, **_):
        if not self.is_visible(): raise RuntimeError('NOT_VISIBLE')

    def click(self, **kwargs):
        if kwargs.get('force'): raise AssertionError('FORCED_CLICK_FORBIDDEN')
        if not self.is_visible(): raise RuntimeError('NOT_VISIBLE')
        self.page.click(self.nodes[0])


class Page:
    def __init__(self, context):
        self.context, self.browser = context, context.browser
        self.main_frame = object()
        self.events = {}
        self.current = ''
        self.url = 'about:blank'
        self.closed = False
        self.venue = None
        self.last_response = None

    def on(self, event, fn):
        self.events.setdefault(event, []).append(fn)

    def emit(self, event, obj):
        for fn in self.events.get(event, ()): fn(obj)

    def set_default_timeout(self, timeout): pass
    def set_default_navigation_timeout(self, timeout): pass

    def parse(self):
        document = calendar._Document(); document.feed(self.current)
        return document

    def content(self):
        if self.browser.prevent_route_dom_read and self.browser.in_route:
            raise RuntimeError('NAVIGATING_DOCUMENT_UNAVAILABLE')
        return self.current

    def locator(self, selector):
        return self.select(selector, self.parse().nodes)

    def select(self, selector, nodes):
        if selector == '#setRaceProgram > div':
            return Locator(self, [n for n in nodes if n.tag == 'div' and n.parent
                                  and n.parent.attrs.get('id') == 'setRaceProgram'])
        if ' ' in selector and not selector.startswith('input['):
            head, tail = selector.split(' ', 1)
            first = self.select(head, nodes)
            return first.locator(tail)
        if selector.endswith(':visible'):
            return Locator(self, [n for n in self.select(selector[:-8], nodes).nodes
                                  if Locator(self, [n]).is_visible()])
        def match(n):
            if selector.startswith('#'): return n.attrs.get('id') == selector[1:]
            if selector.startswith('.'):
                return selector[1:] in n.attrs.get('class', '').split()
            m = re.fullmatch(r'([a-z]+)?\[([a-z]+)=["\']([^"\']*)["\']\]', selector)
            if m: return (not m[1] or n.tag == m[1]) and n.attrs.get(m[2]) == m[3]
            if '.' in selector:
                tag, cls = selector.split('.', 1)
                return n.tag == tag and cls in n.attrs.get('class', '').split()
            return n.tag == selector
        return Locator(self, [n for n in nodes if match(n)])

    def transmit(self, path, raw, *, method='GET', fields=None, status=200,
                 navigation=True, resource_type='document', redirected_from=None):
        url = path if path.startswith('https://') else 'https://keirin.jp' + path
        request = Request(self, url, method, urlencode(fields) if fields is not None else None,
                          navigation, resource_type, redirected_from)
        route = Route(self, request, raw, status)
        self.browser.in_route = True
        try:
            self.context.router(route)
        finally:
            self.browser.in_route = False
        if route.aborted: raise RuntimeError('BLOCKED')
        if navigation:
            self.url = url
            self.current = raw.decode(errors='replace')
        response = Response(request, raw, status)
        if navigation: self.last_response = response
        return response

    @contextmanager
    def expect_navigation(self, **_):
        result = SimpleNamespace(value=None)
        yield result
        result.value = self.last_response

    def goto(self, url, **_):
        b = self.browser
        response = self.transmit(url, b.calendar, status=b.calendar_status)
        if b.calendar_dom_mutation:
            self.current = b.calendar_dom_mutation(self.current)
        if b.resource:
            path, method, status = b.resource
            if b.resource_statuses:
                status = b.resource_statuses.pop(0)
            self.transmit(path, b.resource_raw, method=method,
                          navigation=False, resource_type=b.resource_type, status=status,
                          fields=b.resource_fields)
        for i in range(b.resources):
            self.transmit('/sp/static/invented-' + str(i) + '.js', b'// invented',
                          navigation=False, resource_type='script')
        return response

    def click(self, node):
        b = self.browser
        handler = node.attrs.get('onclick', '')
        b.clicks.append((node.tag, bool(handler.startswith('bopen('))))
        if handler.startswith('bopen('):
            self.current = self.current.replace('class="dispoff" id="t_invented"',
                                                'class="" id="t_invented"')
            return
        match = calendar._REFERENCE.fullmatch(handler)
        if match:
            self.venue = 98 + ord(match[1][0]) - ord('A')
            if b.before_post: b.before_post(self, 'list')
            fields = [('encp', match[1]), ('disp', 'SJ0301')]
            if b.post_mutation: fields = b.post_mutation('list', fields)
            self.transmit('/sp/racelist', b.lists.get(self.venue, list_html()),
                          method='POST', fields=fields, status=b.list_status)
            self.current = render_list(self.current.encode())
            if b.list_dom_mutation: self.current = b.list_dom_mutation(self.current)
            b.list_visits += 1
            if b.after_list: b.after_list(b)
            return
        if handler.startswith("location.href='#Nitiji_"):
            b.date_clicks += 1
            if b.after_date_click: b.after_date_click(self)
            return
        if node.tag == 'button' and any('raceEveNamewid' in n.attrs.get('class','').split()
                                        for n in descendants(node)):
            row = node.parent
            inputs = [n.attrs.get('value') for n in row.children if n.tag == 'input']
            number = int(next(calendar._text(n) for n in descendants(node)
                              if 'raceEveNamewid' in n.attrs.get('class','').split()))
            if b.before_post: b.before_post(self, 'detail')
            fields = [('encp', inputs[1]), ('disp', 'SJ0315')]
            if b.post_mutation: fields = b.post_mutation('detail', fields)
            self.transmit(inputs[0], b.details.get(number, detail_html(number)),
                          method='POST', fields=fields, status=b.detail_status)
            b.detail_visits += 1
            if b.final_detail_resource and b.detail_visits == b.final_detail_resource[0]:
                self.transmit('/sp/ana', b.final_detail_resource[1],
                              navigation=False, resource_type='xhr')
            if b.after_detail: b.after_detail(b)
            return
        raise AssertionError('UNREVIEWED_CLICK')

    def wait_for_load_state(self, **_): pass
    def close(self):
        if self.browser.release_resources_on_close:
            self.browser.release_held_resources()
        self.closed = True


class Context:
    def __init__(self, browser):
        self.browser, self.events = browser, {}
        self.router = None
        self.closed = False

    def route(self, pattern, fn):
        assert pattern == '**/*'; self.router = fn
    def route_web_socket(self, pattern, fn): pass
    def on(self, event, fn): self.events.setdefault(event, []).append(fn)
    def emit(self, event, obj):
        for fn in self.events.get(event, ()): fn(obj)
    def new_page(self):
        p = Page(self); self.browser.pages.append(p); self.emit('page', p); return p
    def close(self): self.closed = True


class Browser:
    def __init__(self, *, venues=(98, 99)):
        self.calendar = calendar_html(venues)
        self.calendar_status = self.list_status = self.detail_status = 200
        self.calendar_dom_mutation = self.list_dom_mutation = None
        self.before_post = self.post_mutation = self.after_detail = self.after_list = None
        self.after_date_click = None
        self.resource = None; self.resources = 0
        self.resource_type = 'script'
        self.resource_fields = self.resource_statuses = None
        self.resource_raw = b'/* invented public script */'
        self.resource_headers = None
        self.final_detail_resource = None
        self.hold_resource_responses = self.release_resources_on_close = False
        self.held_resources = []
        self.late_analytics = False
        self.lists, self.details = {}, {}
        self.sent, self.pages, self.clicks = [], [], []
        self.blocked = self.list_visits = self.detail_visits = self.date_clicks = 0
        self.closed = False
        self.context_options = None
        self.prevent_callback_body_read = self.in_response_callback = False
        self.prevent_route_dom_read = self.in_route = False

    def new_context(self, **kwargs):
        self.context_options = kwargs
        self.context = Context(self)
        return self.context

    def close(self): self.closed = True

    def release_held_resources(self):
        while self.held_resources:
            response = self.held_resources.pop(0)
            self.in_response_callback = True
            try:
                response.request._page.emit('response', response)
                self.context.emit('response', response)
            finally:
                self.in_response_callback = False


class OfficialSPBrowserTests(unittest.TestCase):
    def api(self):
        self.assertTrue(importlib.util.find_spec(MODULE) is not None, 'BROWSER_COLLECTOR_MISSING')
        return importlib.import_module(MODULE)

    @contextmanager
    def collect(self, browser=None, **kwargs):
        api = self.api()
        browser = browser or Browser()
        with tempfile.TemporaryDirectory(prefix='official-sp-private-') as tmp:
            inbox = Path(tmp) / 'inbox'
            output = io.StringIO()
            with redirect_stdout(output):
                result = api.collect_official_sp(inbox, clock=lambda: AT,
                    browser_factory=lambda: browser, **kwargs)
            self.assertEqual(output.getvalue(), '')
            self.assertIn(result['state'], api.SAFE_STATES)
            self.assertFalse(result['source_admission'])
            self.assertFalse(result['model_input_admission'])
            self.assertEqual(result['new_forecasts'], 0)
            self.assertEqual(result['winticket_requests'], 0)
            self.assertIs(type(result.get('blocked_before_send')), int)
            self.assertGreaterEqual(result['blocked_before_send'], 0)
            self.assertEqual(set(result['provider_denial_http_status_counts']),
                             {'HTTP_403', 'HTTP_429', 'UNKNOWN'})
            if hasattr(browser, 'context'):
                self.assertTrue(browser.context.closed)
                self.assertTrue(browser.closed)
                self.assertTrue(all(p.closed for p in browser.pages))
                self.assertEqual(browser.context_options,
                                 {'service_workers': 'block', 'accept_downloads': False})
            yield result, inbox, browser

    def test_full_serial_public_flow_counts_actual_raw_records_and_never_admits(self):
        b = Browser(); b.details[2] = detail_html(2, 9)
        with self.collect(b) as (out, inbox, b):
            self.assertEqual(out['state'], 'OFFICIAL_SP_PARTIAL_INPUT_CAPTURED')
            self.assertEqual((out['calendar_meetings_observed'], out['day_venue_count'],
                              out['day_race_count'], out['race_lists_verified']), (2, 2, 6, 2))
            self.assertEqual((out['details_verified'], out['riders_verified']), (6, 46))
            self.assertEqual((out['future_detail_count'], out['expired_detail_count']), (4, 2))
            self.assertEqual(out['unknown_transmitted_status_count'], 0)
            self.assertFalse(out['provider_denied'])
            self.assertEqual(out['blocked_before_send'], 0)
            self.assertEqual(out['provider_denial_http_status_counts'],
                             {'HTTP_403': 0, 'HTTP_429': 0, 'UNKNOWN': 0})
            self.assertEqual(out['navigation_request_count'], len(b.sent))
            self.assertEqual(out['http_status_counts'], {'200': len(b.sent)})
            self.assertGreaterEqual(b.date_clicks, 6)
            self.assertTrue(any(expander for _, expander in b.clicks))
            self.assertTrue(inbox.is_dir())

    def future_placeholder_list(self):
        data = list_data()
        future = deepcopy(data['SJ0301']['kaisaiDayList'][-1])
        future['strKaisaiNitijName'] = '最終日(1/16)'
        for i, row in enumerate(future['raceProgramList']):
            row.pop('strRaceLnkKbn')
            if i:
                row['strRaceLnk'] = row['strRaceLnkPrm'] = ''
        data['SJ0301']['kaisaiDayList'].append(future)
        return html(data)

    def test_future_placeholder_rows_do_not_block_strict_current_day_capture(self):
        b = Browser(venues=(98,)); b.lists[98] = self.future_placeholder_list()
        with self.collect(b) as (out, _, b):
            self.assertEqual(out['state'], 'OFFICIAL_SP_PARTIAL_INPUT_CAPTURED')
            self.assertEqual((out['day_race_count'], out['details_verified'], out['riders_verified']),
                             (3, 3, 21))
            self.assertEqual(b.detail_visits, 3)

    def test_current_day_and_all_date_label_guards_remain_strict_with_future_placeholders(self):
        changes = [lambda t: t.replace('value="'+'B'*43+'"', 'value="'+'Z'*43+'"'),
                   lambda t: t.replace('2日目(1/15)</div>', '2日目(1/16)</div>'),
                   lambda t: t.replace('value="1"', 'value="2"'),
                   lambda t: t.replace('最終日(1/16)</div>', '最終日(1/17)</div>')]
        for change in changes:
            b = Browser(venues=(98,)); b.lists[98] = self.future_placeholder_list()
            b.list_dom_mutation = change
            with self.collect(b) as (out, _, b):
                self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT')
                self.assertEqual(out['details_verified'], 0)
                self.assertEqual(b.detail_visits, 0)

    def test_private_create_only_hash_files_preserve_notes_and_expose_only_counts(self):
        with self.collect(Browser(venues=(98,))) as (out, inbox, _):
            self.assertEqual(stat.S_IMODE(inbox.stat().st_mode), 0o700)
            files = list(inbox.iterdir())
            self.assertEqual(out['private_source_files_saved'], len(files))
            self.assertGreater(len(files), 3)
            self.assertTrue(all(stat.S_IMODE(f.stat().st_mode) == 0o600 for f in files))
            self.assertTrue(all(re.fullmatch(r'[0-9a-f]{64}\.(?:bin|json)', f.name) for f in files))
            parsed = [json.loads(f.read_bytes()) for f in files if f.suffix == '.json']
            details = [d for d in parsed if d.get('schema', '').endswith('DETAIL_RECEIPT_V1')]
            self.assertEqual(len(details), 3)
            self.assertTrue(all(d['riders'][1]['entry_note_raw'] == '補充' for d in details))
            report = json.dumps(out, ensure_ascii=False)
            for private in ('架空会場', '架空選手', 'A'*43, 'B'*43, '/sp/', str(inbox)):
                self.assertNotIn(private, report)

    def test_each_denied_resource_stops_before_any_later_source_navigation(self):
        for status in (401, 403, 407, 429):
            b = Browser(); b.resource = ('/sp/static/public.js', 'GET', status)
            with self.subTest(status=status), self.collect(b) as (out, _, b):
                self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_DENIED')
                self.assertTrue(out['provider_denied'])
                denials = {'HTTP_403': 0, 'HTTP_429': 0, 'UNKNOWN': 0}
                denials['HTTP_' + str(status) if status in (403, 429) else 'UNKNOWN'] = 1
                self.assertEqual(out['provider_denial_http_status_counts'], denials)
                self.assertEqual(out['http_status_counts'], {'200': 1, str(status): 1})
                self.assertEqual((out['navigation_request_count'], out['resource_request_count']), (1, 1))
                self.assertEqual(b.list_visits, 0)
                self.assertIsNone(out['day_race_count'])

    def test_unknown_transmitted_status_is_not_http_zero_or_provider_denial(self):
        b = Browser(); b.calendar_status = None
        with self.collect(b) as (out, _, _):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_TRANSPORT')
            self.assertEqual(out['navigation_request_count'], 1)
            self.assertEqual(out['unknown_transmitted_status_count'], 1)
            self.assertEqual(out['http_status_counts'], {})
            self.assertFalse(out['provider_denied'])
            self.assertEqual(out['blocked_before_send'], 0)
            self.assertEqual(out['provider_denial_http_status_counts'],
                             {'HTTP_403': 0, 'HTTP_429': 0, 'UNKNOWN': 0})

    def test_blocked_before_send_mutation_is_not_a_transmitted_http_request(self):
        b = Browser(); b.resource = ('/sp/json', 'POST', 200)
        with self.collect(b) as (out, _, b):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT')
            self.assertEqual(out['navigation_request_count'], 1)
            self.assertEqual(out['resource_request_count'], 0)
            self.assertEqual(out['http_status_counts'], {'200': 1})
            self.assertEqual(out['unknown_transmitted_status_count'], 0)
            self.assertEqual(out['blocked_before_send'], 1)
            self.assertEqual(b.blocked, 1)

    def test_exact_page_generated_analytics_get_does_not_block_public_controls(self):
        b = Browser(venues=(98,)); b.resource = ('/sp/ana', 'GET', 200)
        b.resource_type = 'xhr'
        with self.collect(b) as (out, _, b):
            self.assertEqual(out['state'], 'OFFICIAL_SP_PARTIAL_INPUT_CAPTURED')
            self.assertEqual(out['details_verified'], 3)
            self.assertEqual(out['race_lists_verified'], 1)
            self.assertEqual(out['blocked_before_send'], 0)
            self.assertEqual(out['resource_request_count'], 4)
            self.assertEqual(out['http_status_counts'], {'200': len(b.sent)})

    def test_later_analytics_denial_preserves_prefix_and_stops_detail_navigation(self):
        b = Browser(venues=(98,)); b.resource = ('/sp/ana', 'GET', 200)
        b.resource_type = 'xhr'; b.resource_statuses = [200, 403]
        with self.collect(b) as (out, _, b):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_DENIED')
            self.assertTrue(out['provider_denied'])
            self.assertEqual(out['race_lists_verified'], 1)
            self.assertEqual(out['day_race_count'], 3)
            self.assertEqual(out['details_verified'], 0)
            self.assertEqual(out['navigation_request_count'], 3)
            self.assertEqual(out['resource_request_count'], 2)
            self.assertEqual(out['http_status_counts'], {'200': 4, '403': 1})
            self.assertEqual(out['provider_denial_http_status_counts'],
                             {'HTTP_403': 1, 'HTTP_429': 0, 'UNKNOWN': 0})
            self.assertEqual(b.detail_visits, 0)

    def test_late_received_analytics_body_is_drained_before_its_page_closes(self):
        b = Browser(venues=(98,)); b.late_analytics = True
        with self.collect(b) as (out, _, b):
            self.assertEqual(out['state'], 'OFFICIAL_SP_PARTIAL_INPUT_CAPTURED')
            self.assertEqual(out['details_verified'], 3)
            self.assertEqual(out['resource_request_count'], 1)
            self.assertEqual(out['http_status_counts'], {'200': len(b.sent)})
            self.assertEqual(out['unknown_transmitted_status_count'], 0)

    def test_non_html_analytics_challenge_stops_before_public_controls(self):
        b = Browser(venues=(98,)); b.resource = ('/sp/ana', 'GET', 200)
        b.resource_type = 'xhr'; b.resource_headers = {'content-type': 'application/json'}
        b.resource_raw = b'{"captcha":"verify your browser"}'
        with self.collect(b) as (out, _, b):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT')
            self.assertEqual(out['http_status_counts'], {'200': 2})
            self.assertEqual(out['details_verified'], 0)
            self.assertEqual(out['unknown_transmitted_status_count'], 0)
            self.assertFalse(out['provider_denied'])
            self.assertEqual(b.list_visits, 0)

    def test_non_html_analytics_body_retains_the_individual_response_bound(self):
        b = Browser(venues=(98,)); b.resource = ('/sp/ana', 'GET', 200)
        b.resource_type = 'xhr'
        b.resource_headers = {'content-type': 'application/octet-stream'}
        b.resource_raw = b'x' * (calendar.MAX_HTML_BYTES + 1)
        with self.collect(b) as (out, _, b):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT')
            self.assertEqual(out['http_status_counts'], {'200': 2})
            self.assertEqual(out['details_verified'], 0)
            self.assertEqual(out['unknown_transmitted_status_count'], 0)
            self.assertEqual(b.list_visits, 0)

    def test_non_html_analytics_checks_cover_other_accepted_success_statuses(self):
        bodies = [b'{"captcha":"verify your browser"}',
                  b'x' * (calendar.MAX_HTML_BYTES + 1)]
        for status in (201, 202, 206):
            for raw in bodies:
                b = Browser(venues=(98,)); b.resource = ('/sp/ana', 'GET', status)
                b.resource_type = 'xhr'; b.resource_headers = {'content-type': 'application/json'}
                b.resource_raw = raw
                with self.subTest(status=status, oversized=len(raw)>calendar.MAX_HTML_BYTES), self.collect(b) as (out, _, b):
                    self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT')
                    self.assertEqual(out['http_status_counts'], {'200': 1, str(status): 1})
                    self.assertEqual(out['details_verified'], 0)
                    self.assertEqual(b.list_visits, 0)

    def test_final_received_analytics_body_is_drained_while_its_page_remains_open(self):
        b = Browser(venues=(98,)); b.hold_resource_responses = True
        b.final_detail_resource = (3, b'{"captcha":"verify your browser"}')
        b.resource_headers = {'content-type': 'application/json'}
        def clock_tick():
            b.release_held_resources()
            return 0
        with self.collect(b, monotonic=clock_tick) as (out, _, b):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT')
            self.assertEqual((out['details_verified'], out['riders_verified']), (3, 21))
            self.assertEqual(out['http_status_counts'], {'200': 12})
            self.assertEqual(out['unknown_transmitted_status_count'], 0)

    def test_final_body_arriving_during_close_is_held_without_inventing_unknown_http(self):
        b = Browser(venues=(98,)); b.hold_resource_responses = True
        b.final_detail_resource = (3, b'{"captcha":"verify your browser"}')
        b.resource_headers = {'content-type': 'application/json'}
        b.release_resources_on_close = True
        with self.collect(b) as (out, _, b):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_TRANSPORT')
            self.assertEqual((out['details_verified'], out['riders_verified']), (3, 21))
            self.assertEqual(out['http_status_counts'], {'200': 12})
            self.assertEqual(out['unknown_transmitted_status_count'], 0)
            self.assertFalse(out['provider_denied'])

    def test_final_unresolved_http_outcome_stays_unknown_when_page_closes(self):
        b = Browser(venues=(98,)); b.hold_resource_responses = True
        b.final_detail_resource = (3, b'{"captcha":"verify your browser"}')
        b.resource_headers = {'content-type': 'application/json'}
        with self.collect(b) as (out, _, b):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_TRANSPORT')
            self.assertEqual((out['details_verified'], out['riders_verified']), (3, 21))
            self.assertEqual(out['http_status_counts'], {'200': 11})
            self.assertEqual(out['unknown_transmitted_status_count'], 1)
            self.assertFalse(out['provider_denied'])

    def test_analytics_exception_rejects_every_unreviewed_request_variant(self):
        variants = [('/sp/ana?invented=1', 'GET', 'xhr', None),
                    ('/sp/ana#invented', 'GET', 'xhr', None),
                    ('https://attacker.invalid/sp/ana', 'GET', 'xhr', None),
                    ('https://www.keirin.jp/sp/ana', 'GET', 'xhr', None),
                    ('/sp/ana', 'GET', 'fetch', None),
                    ('/sp/ana', 'POST', 'xhr', None),
                    ('/sp/ana', 'GET', 'xhr', [('invented', '1')]),
                    ('/sp/ana/changed', 'GET', 'xhr', None),
                    ('/sp/json', 'GET', 'xhr', None)]
        for path, method, resource_type, fields in variants:
            b = Browser(venues=(98,)); b.resource = (path, method, 200)
            b.resource_type, b.resource_fields = resource_type, fields
            with self.subTest(method=method, resource_type=resource_type,
                              path_sha256=sha256(path.encode()).hexdigest()), self.collect(b) as (out, _, b):
                self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT')
                self.assertEqual(out['blocked_before_send'], 1)
                self.assertEqual(out['resource_request_count'], 0)
                self.assertEqual(out['http_status_counts'], {'200': 1})
                self.assertEqual(out['unknown_transmitted_status_count'], 0)
                self.assertEqual(b.list_visits, 0)

    def test_external_host_redirect_and_challenge_stop(self):
        for mode in ('external', 'redirect', 'challenge'):
            b = Browser()
            if mode == 'external': b.resource = ('https://attacker.invalid/public.js', 'GET', 200)
            if mode == 'redirect': b.calendar_status = 302
            if mode == 'challenge': b.calendar = b'<html><body>Just a moment... captcha</body></html>'
            with self.subTest(mode=mode), self.collect(b) as (out, _, b):
                self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT')
                self.assertEqual(b.list_visits, 0)
                self.assertFalse(out['provider_denied'])

    def test_changed_calendar_callback_rejects_before_post(self):
        b = Browser(); b.calendar_dom_mutation = lambda text: text.replace('A'*43, 'Z'*43)
        with self.collect(b) as (out, _, b):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT')
            self.assertEqual(out['navigation_request_count'], 1)
            self.assertEqual(b.list_visits, 0)

    def test_changed_post_token_or_disp_and_duplicate_fields_never_transmit(self):
        mutations = [lambda f: [('encp', 'Z'*43), f[1]],
                     lambda f: [f[0], ('disp', 'SJ0326')],
                     lambda f: f + [('encp', 'B'*43)]]
        for target in ('list', 'detail'):
            for mutation in mutations:
                b = Browser(venues=(98,))
                b.post_mutation = lambda kind, fields: mutation(fields) if kind == target else fields
                with self.subTest(target=target), self.collect(b) as (out, _, b):
                    self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT')
                    self.assertEqual(out['details_verified'], 0)
                    self.assertEqual(sum(r.url.endswith('/sp/race') for r in b.sent), 0)
                    self.assertGreater(b.blocked, 0)

    def test_changed_selected_row_or_day_rejects_before_detail_post(self):
        changes = [lambda t: t.replace('value="'+'B'*43+'"', 'value="'+'Z'*43+'"'),
                   lambda t: t.replace('2日目(1/15)</div>', '2日目(1/16)</div>'),
                   lambda t: t.replace('value="1"', 'value="2"')]
        for change in changes:
            b = Browser(venues=(98,)); b.list_dom_mutation = change
            with self.collect(b) as (out, _, b):
                self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT')
                self.assertEqual(out['details_verified'], 0)
                self.assertEqual(b.detail_visits, 0)

    def test_scope_changed_by_date_control_is_checked_again_before_race_click(self):
        b = Browser(venues=(98,))
        def changed(page):
            page.current = page.current.replace('2日目(1/15)</div>', '2日目(1/16)</div>')
        b.after_date_click = changed
        with self.collect(b) as (out, _, b):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT')
            self.assertEqual(out['details_verified'], 0)
            self.assertEqual(sum(r.url.endswith('/sp/race') for r in b.sent), 0)

    def test_changed_rendered_venue_or_header_date_rejects_before_detail_post(self):
        for change in (lambda t: t.replace('id="hhJoName">架空会場', 'id="hhJoName">別会場'),
                       lambda t: t.replace('id="hhKaisaihi">2030/01/14',
                                           'id="hhKaisaihi">2030/01/16')):
            b = Browser(venues=(98,)); b.list_dom_mutation = change
            with self.collect(b) as (out, _, b):
                self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT')
                self.assertEqual(out['details_verified'], 0)
                self.assertEqual(b.detail_visits, 0)

    def test_last_list_completed_at_budget_boundary_retains_verified_denominators(self):
        b = Browser(venues=(98,)); elapsed = [0]
        b.after_list = lambda _: elapsed.__setitem__(0, 250)
        with self.collect(b, monotonic=lambda: elapsed[0]) as (out, _, _):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_BUDGET')
            self.assertEqual(out['race_lists_verified'], 1)
            self.assertEqual(out['day_race_count'], 3)
            self.assertEqual(out['day_venue_count'], 1)
            self.assertEqual(out['details_verified'], 0)

    def test_injected_browser_does_not_import_playwright(self):
        real_import = __import__
        def offline_import(name, *args, **kwargs):
            if name.startswith('playwright'):
                raise AssertionError('PLAYWRIGHT_LAZY_IMPORT_REQUIRED')
            return real_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=offline_import):
            with self.collect(Browser(venues=(98,))) as (out, _, _):
                self.assertEqual(out['state'], 'OFFICIAL_SP_PARTIAL_INPUT_CAPTURED')

    def test_document_body_is_read_after_navigation_outside_reentrant_response_callback(self):
        b = Browser(venues=(98,)); b.prevent_callback_body_read = True
        with self.collect(b) as (out, _, _):
            self.assertEqual(out['state'], 'OFFICIAL_SP_PARTIAL_INPUT_CAPTURED')
            self.assertEqual(out['details_verified'], 3)

    def test_paused_navigation_route_never_reads_the_changing_document(self):
        b = Browser(venues=(98,)); b.prevent_route_dom_read = True
        with self.collect(b) as (out, _, _):
            self.assertEqual(out['state'], 'OFFICIAL_SP_PARTIAL_INPUT_CAPTURED')
            self.assertEqual(out['details_verified'], 3)

    def test_budget_keeps_verified_prefix_and_completed_day_list_count(self):
        b = Browser(venues=(98,)); elapsed = [0]
        b.after_detail = lambda _: elapsed.__setitem__(0, 250)
        with self.collect(b, monotonic=lambda: elapsed[0]) as (out, _, b):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_BUDGET')
            self.assertTrue(out['budget_exhausted'])
            self.assertEqual((out['day_race_count'], out['race_lists_verified'], out['details_verified']), (3, 1, 1))
            self.assertEqual(out['riders_verified'], 7)

    def test_budget_before_all_meeting_lists_keeps_unknown_denominators(self):
        b = Browser(); elapsed = [0]
        def advance(page, kind):
            if kind == 'list': elapsed[0] += 130
        b.before_post = advance
        with self.collect(b, monotonic=lambda: elapsed[0]) as (out, _, _):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_BUDGET')
            self.assertIsNone(out['day_race_count'])
            self.assertIsNone(out['day_venue_count'])
            self.assertEqual(out['details_verified'], 0)

    def test_no_legacy_diagnostic_total_request_cap_is_present(self):
        b = Browser(venues=(98,)); b.resources = 161
        with self.collect(b) as (out, _, _):
            self.assertEqual(out['state'], 'OFFICIAL_SP_PARTIAL_INPUT_CAPTURED')
            self.assertGreater(out['resource_request_count'], 160)
            self.assertEqual(out['details_verified'], 3)

    def test_existing_owner_budget_upper_bound_reaches_the_browser(self):
        with self.collect(Browser(venues=(98,)), budget_seconds=600) as (out, _, _):
            self.assertEqual(out['state'], 'OFFICIAL_SP_PARTIAL_INPUT_CAPTURED')
            self.assertEqual(out['details_verified'], 3)

    def test_invalid_raw_detail_preserves_list_prefix_without_inventing_records(self):
        b = Browser(venues=(98,)); b.details[3] = b'<html><body>Not a race</body></html>'
        with self.collect(b) as (out, _, _):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_SOURCE_LAYOUT')
            self.assertEqual(out['day_race_count'], 3)
            self.assertEqual(out['details_verified'], 0)

    def test_no_current_calendar_meetings_is_unknown_coverage(self):
        b = Browser(venues=(98,))
        b.calendar = calendar_page([venue(98, [meeting('2030-01-20', '2030-01-22')])])
        with self.collect(b) as (out, _, b):
            self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_NO_CURRENT_MEETINGS')
            self.assertIsNone(out['day_race_count'])
            self.assertIsNone(out['day_venue_count'])
            self.assertEqual(b.list_visits, 0)

    def test_checkout_or_symlink_or_nonprivate_existing_inbox_never_starts_browser(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            bad = parent/'bad'; bad.mkdir(mode=0o755); bad.chmod(0o755)
            link = parent/'link'; link.symlink_to(bad, target_is_directory=True)
            for inbox in (Path(__file__).resolve().parents[1]/'not-private-inbox', bad, link):
                calls = []
                out = api.collect_official_sp(inbox, clock=lambda: AT,
                    browser_factory=lambda: calls.append(True))
                self.assertEqual(out['state'], 'HOLD_OFFICIAL_SP_LOCAL_RUNTIME')
                self.assertEqual(out.get('blocked_before_send'), 0)
                self.assertEqual(out['provider_denial_http_status_counts'],
                                 {'HTTP_403': 0, 'HTTP_429': 0, 'UNKNOWN': 0})
                self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
