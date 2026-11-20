"""Read one future official GIRLS card without inventing missing model inputs.

The browser follows the existing public calendar/list controls and uses the
existing same-host, no-redirect, stop-on-denial collector. Only private source
bytes and source-bound roster facts are written. This is not an A/B adapter:
an absent marks column never becomes a fabricated UNMARKED source receipt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
import argparse
from hashlib import sha256
from html import unescape
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import time
from urllib.parse import urlencode

from . import keirin_official_schedule as calendar
from . import keirin_official_sp_browser as browser_source
from . import keirin_official_sp_receipt as receipt
from .keirin_public_two_source_normalizer import _mark


SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_CANARY_CARD_V1'
_TAB_SCRIPT_REQUIREMENTS = {
    '/sp/static/js/FSJ0315.js': (
        'wk0201Data=jsonData["SC0201"].C0201data;',
        'gPrmParaR=wk0201Data.encSelParaR;', 'para=gPrmParaR;',
        'update(dispId,para,sKbn);', 'wkObj["encp"]=para;',
        'wkSyoriKbn=displayingSyoriKbn;', 'wkObj["skbn"]=wkSyoriKbn;',
        'gReqPrmsObject[dispId]=wkObj;', "case'SJ0321':returnryController.JSON_REQ_ID;",
        'varreqID=getReqID(key);', 'Com.getRequestGet(reqID,gReqPrmsObject[key])'),
    '/sp/static/js/SJ0321_c.js': (
        'varryController={', 'JSON_REQ_ID:"JSJ041"',
        'Com.getRequestGet(ryController.JSON_REQ_ID,params)'),
    '/sp/static/js/commonJSON.js': (
        "location.protocol+'//'+location.host+'/'+$($('script[src$=\"commonJSON.js\"]')[0]).attr('src').split('/')[1]+'/json'",
        "type:'get'", 'getRequestGet:function(reqType,para){returncom.getRequestMain(reqType,para,true);}',
        'if(flgType){$.ajaxSetup(cfg.ajaxCfgG);}', 'params=para;',
        'params.type=reqType;', "$.ajax({data:params,dataType:'json'})"),
    '/sp/static/js/SJ0321_v.js': (
        'ryDataChecker(sensyuTypeInfo.yosoin)', 'ryDataChecker(sensyuTypeInfo.sensyuComment)',
        'functionryDataChecker(str){varret;if(str==undefined||str==null){ret="";}else{ret=str;}returnret;}'),
}


class CanaryCardError(ValueError):
    pass


def _need(ok, code):
    if not ok:
        raise CanaryCardError(code)


def _current_rows(raw, day):
    data = receipt._embedded(browser_source._document(raw))
    date = datetime.fromisoformat(day)
    groups = data['SJ0301']['kaisaiDayList']
    selected = []
    for group in groups:
        match = re.fullmatch(r'(?:初日|最終日|[2-9]日目)\(([0-9]{1,2})/([0-9]{1,2})\)',
                             receipt._norm(group['strKaisaiNitijName']))
        if match and tuple(map(int, match.groups())) == (date.month, date.day):
            selected.append(group['raceProgramList'])
    _need(len(selected) == 1, 'CURRENT_DAY_GROUP_REQUIRED')
    return selected[0]


def _girls_label(value):
    text = receipt._norm(value)
    return text.startswith('L級') or 'ガールズ' in text


def girls_candidates(raw_bytes, *, expected_day, expected_venue_code,
                     observed_at, expected_sha256, calendar_receipt):
    parsed = receipt.parse_race_list(raw_bytes, expected_day=expected_day,
        expected_venue_code=expected_venue_code, observed_at=observed_at,
        expected_sha256=expected_sha256, calendar_receipt=calendar_receipt)
    references = {row['race_no']: row for row in parsed['race_references']}
    return [dict(race_no=int(receipt._norm(row['strRaceNo'])),
                 race_class_raw=row['strSyumokuName'])
            for row in _current_rows(raw_bytes, expected_day)
            if _girls_label(row['strSyumokuName'])
            and references[int(receipt._norm(row['strRaceNo']))]['link_kind'] == '1']


def parse_canary_card(*, list_raw, detail_raw, expected_day, venue_code,
                      race_number, calendar_receipt, list_observed_at,
                      detail_observed_at, list_sha256, detail_sha256, now,
                      minimum_margin_seconds=390):
    candidates = girls_candidates(list_raw, expected_day=expected_day,
        expected_venue_code=venue_code, observed_at=list_observed_at,
        expected_sha256=list_sha256, calendar_receipt=calendar_receipt)
    chosen = [row for row in candidates if row['race_no'] == race_number]
    _need(len(chosen) == 1, 'GIRLS_CLASS_NOT_OBSERVED')
    parsed = receipt.parse_race_detail(detail_raw, expected_day=expected_day,
        expected_venue_code=venue_code, expected_race_number=race_number,
        observed_at=detail_observed_at, expected_sha256=detail_sha256,
        calendar_receipt=calendar_receipt)
    data = receipt._embedded(browser_source._document(detail_raw))
    rows = data['SJ0315']['sensyuTypeInfo']
    _need(all(receipt._norm(row['kyuhan']) in ('L1', 'L級1班') for row in rows),
          'GIRLS_ROSTER_NOT_OBSERVED')
    _need(parsed['no_published_roster_exclusion_observed'] and
          5 <= len(parsed['riders']) <= 9, 'ROSTER_EXCLUSION_UNRESOLVED')
    now = receipt._aware(now)
    list_at, detail_at = receipt._aware(list_observed_at), receipt._aware(detail_observed_at)
    _need(list_at <= detail_at <= now, 'SOURCE_CAPTURE_CLOCK_ORDER_INVALID')
    _need(type(minimum_margin_seconds) is int and 65 <= minimum_margin_seconds <= 86400,
          'CANARY_MARGIN_INVALID')
    cutoff = receipt._aware(datetime.fromisoformat(parsed['official_cutoff_at']))
    _need(now + timedelta(seconds=minimum_margin_seconds) <= cutoff,
          'FUTURE_CUTOFF_MARGIN_REQUIRED')
    sources = [
        dict(kind='CALENDAR', url=calendar.OFFICIAL_DOCUMENT,
             bytes_sha256=calendar_receipt['expected_sha256'],
             captured_at=receipt._aware(calendar_receipt['observed_at']).isoformat(), method='GET'),
        dict(kind='RACE_LIST', url='https://keirin.jp/sp/racelist',
             bytes_sha256=list_sha256, captured_at=list_at.isoformat(), method='POST'),
        dict(kind='RACECARD', url='https://keirin.jp/sp/race',
             bytes_sha256=detail_sha256, captured_at=detail_at.isoformat(), method='POST'),
    ]
    card = dict(schema=SCHEMA, race_id=parsed['race_id'],
        competition='GIRLS', race_class_raw=chosen[0]['race_class_raw'],
        round_stage_raw=chosen[0]['race_class_raw'],
        official_cutoff_at=parsed['official_cutoff_at'], start_at=parsed['start_at'],
        source_observed_at=parsed['source_observed_at'],
        source_sha256=detail_sha256, sources=sources, riders=parsed['riders'],
        model_generation=0, prediction_input_complete=False,
        missing_inputs=['MARKS_SOURCE_UNCONFIRMED', 'FOUR_MONTH_WIN_RATE_UNCONFIRMED',
                        'HOME_COUNT_UNCONFIRMED', 'PER_RIDER_HISTORY_NOT_JOINED'],
        no_mark_rank_fabricated=True, private_only=True)
    line = data.get('SJ0314', {})
    if line.get('resultCd') == 0 and isinstance(line.get('narabiyoso'), dict):
        narabi = line['narabiyoso']
        if (narabi.get('lineKeitai') == 'ライン無し' and
                narabi.get('lineKeitaiClass') == 'noline' and
                narabi.get('ryoikiFlg') == 'true' and narabi.get('errFlg') == 'false'):
            source_cars = [row.get('shaban') for row in narabi.get('shaban', [])]
            expected_cars = [str(row['car']) for row in card['riders']]
            _need(len(source_cars) == len(expected_cars) and set(source_cars) == set(expected_cars),
                  'PUBLISHED_NO_LINE_ROSTER_MISMATCH')
            card['line_prediction'] = dict(kind='NO_FIXED_LINE',
                groups=[[row['car']] for row in card['riders']],
                provider_raw=narabi.get('teikyo', ''), source_sha256=detail_sha256,
                source_field='SJ0314.narabiyoso', observed_at=detail_at.isoformat())
    if 'line_prediction' not in card:
        card['missing_inputs'].append('LINE_PREDICTION_UNCONFIRMED')
    return card


def derive_prediction_tab_request(detail_raw, scripts):
    """Derive only the observed public SJ0321 button request, without running JS.

    These checks deliberately fail on a changed source layout. They are not an
    API discovery mechanism and do not change the legacy browser's host guard.
    """
    document = browser_source._document(detail_raw)
    _need(any(node.tag == 'button' and node.attrs.get('onclick') == "btnClickOfFrame('SJ0321')"
              and '予想情報' in calendar._text(node) for node in document.nodes),
          'PUBLIC_PREDICTION_TAB_NOT_OBSERVED')
    linked = {node.attrs.get('src') for node in document.nodes if node.tag == 'script'}
    _need(set(_TAB_SCRIPT_REQUIREMENTS) <= linked and
          set(scripts) == set(_TAB_SCRIPT_REQUIREMENTS), 'PUBLIC_TAB_SCRIPTS_NOT_LINKED')
    for path, required in _TAB_SCRIPT_REQUIREMENTS.items():
        raw = scripts[path]
        _need(type(raw) is bytes and 0 < len(raw) <= calendar.MAX_HTML_BYTES,
              'PUBLIC_TAB_SCRIPT_INVALID')
        compact = re.sub(r'\s+', '', raw.decode('utf-8', 'strict'))
        _need(all(fragment in compact for fragment in required), 'PUBLIC_TAB_SCRIPT_CHANGED')
    inline = '\n'.join(calendar._text(node) for node in document.nodes
                       if node.tag == 'script' and 'src' not in node.attrs)
    modes = re.findall(r'\bvar\s+displayingSyoriKbn\s*=\s*([12])\s*;', inline)
    _need(modes == ['1'], 'PUBLIC_PREDICTION_MODE_NOT_OBSERVED')
    data = receipt._embedded(document)
    token = data['SC0201']['C0201data'].get('encSelParaR')
    _need(type(token) is str and re.fullmatch(r'[A-Za-z0-9_-]{64}', token) is not None,
          'PUBLIC_TAB_RACE_REFERENCE_INVALID')
    controller = scripts['/sp/static/js/SJ0321_c.js'].decode('utf-8', 'strict')
    request_types = re.findall(r'\bJSON_REQ_ID\s*:\s*"([A-Z0-9]+)"', controller)
    _need(request_types == ['JSJ041'], 'PUBLIC_TAB_REQUEST_TYPE_CHANGED')
    # commonJSON.js uses the linked script's first path component to select
    # the same-host /json endpoint; the exact public recipe is checked above.
    linked_common = '/sp/static/js/commonJSON.js'
    path = '/' + linked_common.split('/')[1] + '/json'
    fields = [('encp', token), ('skbn', modes[0]), ('type', request_types[0])]
    return dict(url='https://keirin.jp'+path+'?'+urlencode(fields),
        method='GET', path=path, control="btnClickOfFrame('SJ0321')",
        script_sha256={path: sha256(raw).hexdigest() for path, raw in scripts.items()})


def parse_prediction_tab(*, raw_bytes, expected_sha256, observed_at, now,
                         card, detail_raw, scripts, request_url,
                         minimum_margin_seconds=390):
    """Bind observed paper marks and comments to the exact current race roster."""
    _need(type(raw_bytes) is bytes and 0 < len(raw_bytes) <= calendar.MAX_HTML_BYTES and
          sha256(raw_bytes).hexdigest() == expected_sha256, 'PREDICTION_BYTES_SHA_MISMATCH')
    _need(sha256(detail_raw).hexdigest() == card['source_sha256'], 'PREDICTION_CARD_SHA_MISMATCH')
    request = derive_prediction_tab_request(detail_raw, scripts)
    _need(request_url == request['url'], 'PUBLIC_TAB_REQUEST_MISMATCH')
    observed, now = receipt._aware(observed_at), receipt._aware(now)
    card_at = receipt._aware(datetime.fromisoformat(card['source_observed_at']))
    cutoff = receipt._aware(datetime.fromisoformat(card['official_cutoff_at']))
    _need(card_at <= observed <= now, 'PREDICTION_CAPTURE_CLOCK_ORDER_INVALID')
    _need(type(minimum_margin_seconds) is int and 65 <= minimum_margin_seconds <= 86400,
          'CANARY_MARGIN_INVALID')
    _need(now + timedelta(seconds=minimum_margin_seconds) <= cutoff,
          'FUTURE_CUTOFF_MARGIN_REQUIRED')
    data = json.loads(raw_bytes.decode('utf-8', 'strict'), object_pairs_hook=receipt._pairs,
                      parse_constant=receipt._nonfinite, parse_float=receipt._finite_float)
    _need(type(data) is dict and type(data.get('resultCd')) is int and
          data['resultCd'] == 0 and data.get('syusouInfoExistFlg') == '1',
          'PUBLIC_PREDICTION_TABLE_UNAVAILABLE')
    _need(data.get('bKeirinjyoCd') == card['race_id'][8:10], 'PREDICTION_VENUE_MISMATCH')
    for field in ('yosoinMei', 'senComMei', 'lastUpdateTime'):
        _need(type(data.get(field)) is str and 0 < len(data[field]) <= 160,
              'PREDICTION_PROVIDER_OR_UPDATE_MISSING')
    update = unescape(data['lastUpdateTime']).strip()
    match = re.fullmatch(r'(20[0-9]{2}/[0-9]{2}/[0-9]{2} [0-9]{2}:[0-9]{2})\s*更新', update)
    _need(match is not None, 'PREDICTION_UPDATE_FORMAT_CHANGED')
    updated = datetime.strptime(match[1], '%Y/%m/%d %H:%M').replace(tzinfo=receipt.JST)
    _need(updated <= observed, 'PREDICTION_UPDATE_AFTER_CAPTURE')
    rows = data.get('sensyuTypeInfo')
    _need(type(rows) is list and len(rows) == len(card['riders']), 'PREDICTION_ROSTER_MISMATCH')
    expected = {row['car']: row for row in card['riders']}
    result, cars = [], set()
    for row in rows:
        _need(type(row) is dict and re.fullmatch(r'[1-9]', str(row.get('syaban', ''))) is not None,
              'PREDICTION_ROSTER_MISMATCH')
        car = int(row['syaban'])
        _need(car in expected and car not in cars and
              row.get('sensyuRegistNo') == expected[car]['registration_id'] and
              receipt._norm(row.get('sensyuName', '')) == receipt._norm(expected[car]['name']),
              'PREDICTION_ROSTER_MISMATCH')
        cars.add(car)
        _need(row.get('ketujyouTuikaHojyu', '') not in ('欠場', '欠車'),
              'PREDICTION_ROSTER_EXCLUSION_UNRESOLVED')
        mark = row.get('yosoin')
        _need(mark is None or (type(mark) is str and len(mark) <= 12), 'PREDICTION_MARK_INVALID')
        display_mark = '' if mark is None else unescape(mark)
        comment = row.get('sensyuComment')
        _need(comment is None or (type(comment) is str and len(comment) <= 2048),
              'PREDICTION_COMMENT_INVALID')
        result.append(dict(car=car, registration_id=expected[car]['registration_id'],
            mark_raw=display_mark, mark_rank=_mark(display_mark, len(rows)),
            mark_field_presence=('ABSENT_RENDERED_BLANK' if 'yosoin' not in row else
                                 'NULL_RENDERED_BLANK' if mark is None else 'PRESENT'),
            mark_source_sha256=expected_sha256,
            comment_raw='' if comment is None else comment,
            comment_source_sha256=expected_sha256,
            comment_timestamp_precision='PAGE_UPDATE_ONLY'))
    return dict(schema='RACE_AI_KEIRIN_OFFICIAL_PUBLIC_PREDICTION_TAB_V1',
        race_id=card['race_id'], riders=sorted(result, key=lambda row: row['car']),
        mark_provider_raw=data['yosoinMei'], comment_provider_raw=data['senComMei'],
        publisher_updated_at=updated.isoformat(), source_observed_at=observed.isoformat(),
        source_sha256=expected_sha256, request=request,
        marks_source_verified=True, independent_origin_attested=False, private_only=True)


class _CanaryCollector(browser_source._Collector):
    def __init__(self, *args, venue_code=None, race_number=None, minimum_margin_seconds=390):
        super().__init__(*args)
        self.venue_code, self.race_number = venue_code, race_number
        self.minimum_margin_seconds = minimum_margin_seconds
        self.canary_card = None
        self.last_detail = None
        self.candidate_count = 0

    def capture_document(self, response):
        doc = super().capture_document(response)
        if response.url == 'https://keirin.jp/sp/race':
            self.last_detail = doc
        return doc

    def run(self, browser):
        self.context = browser.new_context(service_workers='block', accept_downloads=False)
        self.context.route('**/*', self.route)
        self.context.route_web_socket('**/*', self.websocket)
        self.context.on('response', self.response)
        self.context.on('requestfailed', self.failed)
        self.context.on('page', self.extra_page)
        bound, projection = self.load_calendar()
        candidates = projection['calendar_meeting_candidates']
        candidates = [r for r in candidates if self.venue_code is None or r['venue_code'] == self.venue_code]
        first_navigation = True
        for candidate in candidates:
            if not first_navigation:
                bound, current = self.load_calendar()
                candidate = next(r for r in current['calendar_meeting_candidates']
                                 if r['venue_code'] == candidate['venue_code'])
            first_navigation = False
            parsed, listed = self.open_meeting(bound, candidate)
            self.out['race_lists_verified'] += 1
            girls = girls_candidates(listed['raw'], expected_day=self.day,
                expected_venue_code=candidate['venue_code'], observed_at=listed['observed_at'],
                expected_sha256=listed['expected_sha256'], calendar_receipt=bound)
            girls = [r for r in girls if self.race_number is None or r['race_no'] == self.race_number]
            self.candidate_count += len(girls)
            for index, target in enumerate(girls):
                if index:
                    bound, current = self.load_calendar()
                    candidate = next(r for r in current['calendar_meeting_candidates']
                                     if r['venue_code'] == candidate['venue_code'])
                    parsed, listed = self.open_meeting(bound, candidate)
                self.open_detail(parsed, listed, bound, target['race_no'])
                detail = self.last_detail
                _need(detail is not None, 'DETAIL_DOCUMENT_NOT_OBSERVED')
                try:
                    card = parse_canary_card(list_raw=listed['raw'], detail_raw=detail['raw'],
                        expected_day=self.day, venue_code=candidate['venue_code'],
                        race_number=target['race_no'], calendar_receipt=bound,
                        list_observed_at=listed['observed_at'], detail_observed_at=detail['observed_at'],
                        list_sha256=listed['expected_sha256'], detail_sha256=detail['expected_sha256'],
                        now=self.now(), minimum_margin_seconds=self.minimum_margin_seconds)
                except CanaryCardError as exc:
                    if str(exc) == 'FUTURE_CUTOFF_MARGIN_REQUIRED':
                        continue
                    raise
                self.settle_requests()
                self.canary_card = card
                self.inbox.json(card)
                return
        self.stop('HOLD_NO_ELIGIBLE_GIRLS_CARD')

    def report(self):
        report = super().report()
        report.update(canary_card_saved=self.canary_card is not None,
                      girls_candidates_observed=self.candidate_count,
                      prediction_input_complete=False,
                      marks_source_verified=False,
                      all_nationwide_coverage_verified=False)
        return report


def collect_canary_card(inbox, *, venue_code=None, race_number=None,
                        minimum_margin_seconds=390, budget_seconds=180,
                        browser_factory=None):
    """Normal public UI acquisition; raw documents stay outside the checkout."""
    _need(venue_code is None or (type(venue_code) is int and 1 <= venue_code <= 99),
          'VENUE_FILTER_INVALID')
    _need(race_number is None or (type(race_number) is int and 1 <= race_number <= 12),
          'RACE_FILTER_INVALID')
    _need(type(budget_seconds) in (int, float) and isfinite(budget_seconds) and
          1 <= budget_seconds <= 600, 'WORK_BUDGET_INVALID')
    _need(type(minimum_margin_seconds) is int and 65 <= minimum_margin_seconds <= 86400,
          'CANARY_MARGIN_INVALID')
    private = browser_source._Inbox(inbox)
    collector = _CanaryCollector(private, lambda: datetime.now(timezone.utc), time.monotonic,
        budget_seconds, venue_code=venue_code, race_number=race_number,
        minimum_margin_seconds=minimum_margin_seconds)
    runtime = browser = None
    try:
        if browser_factory is None:
            from playwright.sync_api import sync_playwright
            runtime = sync_playwright().start()
            browser = runtime.chromium.launch(headless=True)
        else:
            browser = browser_factory()
        collector.run(browser)
    except browser_source._Stop:
        collector.stop(browser_source._LAYOUT)
    except (ValueError, KeyError, StopIteration):
        collector.stop(browser_source._LAYOUT)
    except Exception as error:
        browser_source._log_collection_failure(error)
        collector.stop(browser_source._TRANSPORT)
    finally:
        collector.closing = True
        for handle in (collector.page, collector.context, browser):
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    collector.stop(browser_source._LOCAL)
        if runtime is not None:
            runtime.stop()
        private.close()
    return collector.report()


class _CurlPublicSession:
    """A normal public cookie session; no authentication, redirects or retries."""
    def __init__(self, folder, clock):
        self.temp = TemporaryDirectory(prefix='public-form-session-', dir=folder)
        self.root = Path(self.temp.name)
        self.clock = clock
        self.cookie = self.root / 'cookies.txt'
        fd = os.open(self.cookie, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)

    def request(self, url, fields=None, referer=None):
        body = self.root / 'response.bin'
        for path in (body,):
            path.touch(mode=0o600, exist_ok=True)
            path.chmod(0o600)
        command = ['curl', '--silent', '--show-error', '--max-time', '20',
                   '--max-filesize', str(calendar.MAX_HTML_BYTES),
                   '--proto', '=https', '--cookie', str(self.cookie),
                   '--cookie-jar', str(self.cookie), '--output', str(body),
                   '--write-out', '%{http_code}\n%{url_effective}\n']
        if fields is not None:
            command += ['--request', 'POST']
            for key, value in fields:
                command += ['--data-urlencode', key + '=' + value]
        if referer is not None:
            command += ['--referer', referer]
        done = subprocess.run(command + [url], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=25, check=False)
        at = self.clock()
        _need(done.returncode == 0, 'PUBLIC_FORM_TRANSPORT_FAILED')
        parts = done.stdout.decode('utf-8', 'strict').splitlines()
        _need(len(parts) == 2 and parts[0].isdigit(), 'PUBLIC_FORM_HTTP_RECEIPT_INVALID')
        raw = body.read_bytes()
        _need(len(raw) <= calendar.MAX_HTML_BYTES, 'PUBLIC_FORM_BODY_TOO_LARGE')
        return dict(status=int(parts[0]), url=parts[1], raw=raw, observed_at=at)

    def close(self):
        self.temp.cleanup()


def collect_canary_card_http(inbox, *, venue_code, race_number, request=None,
                             clock=None, minimum_margin_seconds=390,
                             include_prediction_tab=True):
    """Follow the form action/method displayed by the site's public JavaScript.

    The card needs seven ordinary requests; its public prediction tab adds five.
    Public session cookies stay in a
    private temporary directory and are removed. A refusal or error ends the
    operation without another request. Injected request is an offline test seam,
    never read from provider JSON or used to assert independent authentication.
    """
    _need(type(venue_code) is int and 1 <= venue_code <= 99 and
          type(race_number) is int and 1 <= race_number <= 12, 'CANARY_TARGET_INVALID')
    _need(type(include_prediction_tab) is bool, 'PUBLIC_TAB_OPTION_INVALID')
    clock = clock or (lambda: datetime.now(timezone.utc))
    private = browser_source._Inbox(inbox)
    transport = None
    report = dict(schema='RACE_AI_KEIRIN_OFFICIAL_CANARY_HTTP_COUNTS_V1',
                  state='HOLD_CANARY_SOURCE_INCOMPLETE', canary_card_saved=False,
                  requests=0, status_counts={}, prediction_input_complete=False,
                  new_forecasts=0, marks_source_verified=False,
                  all_nationwide_coverage_verified=False)
    script_receipts = []
    try:
        if request is None:
            transport = _CurlPublicSession(str(Path(inbox).absolute()), clock)
            request = transport.request

        def read(path, fields=None, referer=None, derived_tab_request=None):
            allowed = ('/sp/raceschedule', '/sp/racelist', '/sp/race',
                  '/sp/static/js/SJ0201.js', '/sp/static/js/commonSubmit.js',
                  '/sp/static/js/SJ0301_c.js', '/sp/static/js/SJ0301_v.js')
            if derived_tab_request is None:
                _need(path in allowed or path in _TAB_SCRIPT_REQUIREMENTS,
                      'PUBLIC_FORM_UNOBSERVED_ENDPOINT')
                url = 'https://keirin.jp' + path
            else:
                _need(path == '/sp/json' and fields is None and
                      derived_tab_request['method'] == 'GET' and
                      derived_tab_request['path'] == path and
                      derived_tab_request['url'].startswith('https://keirin.jp/sp/json?'),
                      'PUBLIC_FORM_UNOBSERVED_ENDPOINT')
                url = derived_tab_request['url']
            report['requests'] += 1
            response = request(url, fields, referer)
            status = response['status']
            report['status_counts'][str(status)] = report['status_counts'].get(str(status), 0) + 1
            _need(type(status) is int and status == 200, 'PROVIDER_HTTP_' + str(status))
            _need(response['url'] == url, 'PUBLIC_FORM_REDIRECT_REFUSED')
            raw = response['raw']
            _need(type(raw) is bytes and 0 < len(raw) <= calendar.MAX_HTML_BYTES,
                  'PUBLIC_FORM_BODY_INVALID')
            _need(browser_source._CHALLENGE.search(raw.decode('utf-8', 'replace')) is None,
                  'PUBLIC_FORM_CHALLENGE_REFUSED')
            at = receipt._aware(response['observed_at'])
            _need(at <= receipt._aware(clock()), 'PUBLIC_FORM_CAPTURE_CLOCK_INVALID')
            digest = sha256(raw).hexdigest()
            private.save(raw, '.bin')
            source = dict(schema='RACE_AI_KEIRIN_OFFICIAL_CANARY_HTTP_RECEIPT_V1',
                          url=url, method='POST' if fields is not None else 'GET',
                          status=status, bytes_sha256=digest, observed_at=at.isoformat(),
                          private_only=True)
            private.json(source)
            return dict(raw=raw, expected_sha256=digest, observed_at=at, source=source)

        def script(document, path, requirements):
            nodes = browser_source._document(document['raw']).nodes
            _need(any(n.tag == 'script' and n.attrs.get('src') == path for n in nodes),
                  'PUBLIC_FORM_SCRIPT_NOT_LINKED')
            data = read(path)
            compact = re.sub(r'\s+', '', data['raw'].decode('utf-8', 'strict'))
            _need(all(part in compact for part in requirements), 'PUBLIC_FORM_SCRIPT_CHANGED')
            script_receipts.append(data['source'])
            return data

        def save_card(card):
            private.json(card)
            report.update(state='OFFICIAL_FUTURE_CARD_CAPTURED_MODEL_INPUTS_INCOMPLETE',
                          canary_card_saved=True, rider_count=len(card['riders']),
                          card_sha256=sha256((json.dumps(card, ensure_ascii=False, sort_keys=True,
                                                         allow_nan=False)+'\n').encode()).hexdigest())

        cal = read('/sp/raceschedule')
        bound = dict(raw_bytes=cal['raw'], expected_sha256=cal['expected_sha256'],
                     observed_at=cal['observed_at'])
        parsed = calendar.parse_calendar(cal['raw'], source_url=calendar.OFFICIAL_DOCUMENT,
            body_sha256=cal['expected_sha256'], received_at=cal['observed_at'],
            now=clock(), http_status=200)
        day = receipt._aware(clock()).astimezone(receipt.JST).date().isoformat()
        projection = calendar.project_day(parsed, event_day=day)
        candidate = [row for row in projection['calendar_meeting_candidates']
                     if row['venue_code'] == venue_code]
        _need(len(candidate) == 1, 'CANARY_CURRENT_MEETING_NOT_OBSERVED')
        script(cal, '/sp/static/js/SJ0201.js',
               ('params["encp"]=encp;', 'params["disp"]="SJ0301";', 'commonSubmit.formPost(next,params,null);'))
        script(cal, '/sp/static/js/commonSubmit.js', ('.attr("method","post")',))
        nodes = [n for n in browser_source._document(cal['raw']).nodes if n.tag == 'table'
                 and sha256(calendar._attribute(n, 'onclick').encode()).hexdigest() ==
                 candidate[0]['navigation_reference_sha256']]
        _need(len(nodes) == 1, 'CANARY_CALENDAR_CONTROL_NOT_UNIQUE')
        match = calendar._REFERENCE.fullmatch(calendar._attribute(nodes[0], 'onclick'))
        _need(match is not None, 'CANARY_CALENDAR_CONTROL_CHANGED')
        listed = read('/sp/racelist', [('encp', match[1]), ('disp', 'SJ0301')], calendar.OFFICIAL_DOCUMENT)
        listing = receipt.parse_race_list(listed['raw'], expected_day=day,
            expected_venue_code=venue_code, observed_at=listed['observed_at'],
            expected_sha256=listed['expected_sha256'], calendar_receipt=bound)
        girls = girls_candidates(listed['raw'], expected_day=day,
            expected_venue_code=venue_code, observed_at=listed['observed_at'],
            expected_sha256=listed['expected_sha256'], calendar_receipt=bound)
        _need(any(row['race_no'] == race_number for row in girls), 'GIRLS_CLASS_NOT_OBSERVED')
        script(listed, '/sp/static/js/SJ0301_v.js',
               ('raceProgram.strRaceLnk', 'raceProgram.strRaceLnkPrm', 'raceProgram.strRaceLnkKbn'))
        script(listed, '/sp/static/js/SJ0301_c.js',
               ('varaction=$(children[1]).attr("value");',
                'params["encp"]=$(children[2]).attr("value");',
                'if(dispDI==1){dispDI="SJ0315";}', 'commonSubmit.formPost(action,params);'))
        reference = next(row for row in listing['race_references'] if row['race_no'] == race_number)
        _need(reference['path'] == '/sp/race' and reference['link_kind'] == '1',
              'CANARY_CARD_CONTROL_CHANGED')
        detail = read('/sp/race', [('encp', reference['opaque_reference']), ('disp', 'SJ0315')],
                      'https://keirin.jp/sp/racelist')
        card = parse_canary_card(list_raw=listed['raw'], detail_raw=detail['raw'],
            expected_day=day, venue_code=venue_code, race_number=race_number, calendar_receipt=bound,
            list_observed_at=listed['observed_at'], detail_observed_at=detail['observed_at'],
            list_sha256=listed['expected_sha256'], detail_sha256=detail['expected_sha256'],
            now=clock(), minimum_margin_seconds=minimum_margin_seconds)
        card['navigation_script_receipts'] = script_receipts
        card['navigation_method'] = 'PUBLIC_FORM_POST_OBSERVED_IN_LINKED_JAVASCRIPT'
        save_card(card)
        if include_prediction_tab:
            linked_scripts = {path: script(detail, path, requirements)['raw']
                              for path, requirements in _TAB_SCRIPT_REQUIREMENTS.items()}
            derived = derive_prediction_tab_request(detail['raw'], linked_scripts)
            prediction = read(derived['path'], referer='https://keirin.jp/sp/race',
                              derived_tab_request=derived)
            parsed_prediction = parse_prediction_tab(raw_bytes=prediction['raw'],
                expected_sha256=prediction['expected_sha256'], observed_at=prediction['observed_at'],
                now=clock(), card=card, detail_raw=detail['raw'], scripts=linked_scripts,
                request_url=derived['url'], minimum_margin_seconds=minimum_margin_seconds)
            private.json(parsed_prediction)
            by_car = {row['car']: row for row in parsed_prediction['riders']}
            for rider in card['riders']:
                rider.update(by_car[rider['car']])
            card['missing_inputs'].remove('MARKS_SOURCE_UNCONFIRMED')
            card['marks_source_verified'] = True
            card['mark_provider_raw'] = parsed_prediction['mark_provider_raw']
            card['comment_provider_raw'] = parsed_prediction['comment_provider_raw']
            card['prediction_tab_updated_at'] = parsed_prediction['publisher_updated_at']
            card['prediction_tab_observed_at'] = parsed_prediction['source_observed_at']
            card['sources'].append(dict(kind='PREDICTION_TAB', url=derived['url'],
                bytes_sha256=prediction['expected_sha256'], captured_at=prediction['observed_at'].isoformat(),
                method='GET', public_control=derived['control']))
            save_card(card)
            report['marks_source_verified'] = True
    except (ValueError, KeyError, TypeError, OSError, StopIteration, subprocess.TimeoutExpired) as exc:
        reason = str(exc)
        report['state'] = 'HOLD_' + reason if re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}', reason) else 'HOLD_PUBLIC_FORM_CAPTURE_INVALID'
    finally:
        if transport is not None:
            transport.close()
        private.close()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-dir', required=True)
    parser.add_argument('--venue-code', type=int)
    parser.add_argument('--race-number', type=int)
    parser.add_argument('--minimum-margin-seconds', type=int, default=390)
    parser.add_argument('--budget-seconds', type=int, default=180)
    args = parser.parse_args(argv)
    result = collect_canary_card(args.private_dir, venue_code=args.venue_code,
        race_number=args.race_number, minimum_margin_seconds=args.minimum_margin_seconds,
        budget_seconds=args.budget_seconds)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['canary_card_saved'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
