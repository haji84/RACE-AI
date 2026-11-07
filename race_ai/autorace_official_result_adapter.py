"""Pure official AUTO result replay against independently frozen inputs.

An independently retained official statement must identify the published
return as the amount per 100-yen ticket. It is copied without scaling by votes,
popularity or stakes. A literal normal-UI request, an earlier OtherRaceInfo response and
the resulting DOM bind the JSON endpoint to its exact case. Capture/source
authentication and private preservation belong to the caller.
"""
import base64
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from . import comprehensive_four_sport_models as native
from .autorace_official_sparse_adapter import _Document, _text, VENUES
from .manual_official_capture import _json, validate_source_pair


SCHEMA = 'RACE_AI_AUTORACE_OFFICIAL_RESULT_SOURCE_V1'
CONTEXT = 'RACE_AI_AUTORACE_OFFICIAL_RESULT_CONTEXT_V1'
JST = timezone(timedelta(hours=9))
MAX_BYTES = 2*1024*1024
UNIT_CONTEXT = 'RACE_AI_AUTORACE_OFFICIAL_RESULT_ARCHIVE_CONTEXT_V1'


def _need(ok, reason):
    if not ok:
        raise ValueError('AUTO_RESULT_'+reason)


def _clock(value):
    try:
        stamp = value if type(value) is datetime else datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(stamp.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
        return stamp
    except (TypeError, ValueError, AttributeError):
        raise ValueError('AUTO_RESULT_AWARE_CLOCK_REQUIRED') from None


def _number(value, low, high, *, text=False):
    if text and type(value) is str and re.fullmatch(r'[1-9][0-9]*', value):
        value = int(value)
    _need(type(value) is int and low <= value <= high, 'OBSERVED_INTEGER_REQUIRED')
    return value


def _day(value):
    _need(type(value) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), 'EXPLICIT_EVENT_DAY_REQUIRED')
    return date.fromisoformat(value)


def _decode(value):
    _need(type(value) is str and 0 < len(value) <= ((MAX_BYTES+2)//3)*4, 'BOUNDED_CAPTURE_REQUIRED')
    try:raw = base64.b64decode(value, validate=True)
    except (ValueError, UnicodeError):raise ValueError('AUTO_RESULT_CAPTURE_BASE64') from None
    _need(0 < len(raw) <= MAX_BYTES and base64.b64encode(raw).decode() == value, 'CAPTURE_BASE64')
    return raw


def _json_source(raw):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'BOUNDED_SOURCE_REQUIRED')
    value = _json(raw)
    _need(type(value) is dict and set(value) == {'result', 'errors', 'body'} and
          value['result'] == 'Success' and value['errors'] == [] and type(value['body']) is dict,
          'SUCCESSFUL_OFFICIAL_RESPONSE_REQUIRED')
    return value['body']


class _UnitText(HTMLParser):
    """Collect literal rendered-content candidates, excluding hidden markup."""
    _VOID = frozenset(('area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'))
    _HIDDEN = frozenset(('head','title','script','style','noscript','template','iframe','object','embed','defs'))
    _BLOCK = frozenset(('html','body','p','div','section','article','aside','li','ul','ol','table','td','th','tr',
                        'br','hr','blockquote','figure','figcaption','h1','h2','h3','h4','h5','h6'))

    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.stack, self.parts, self.nodes = [], [], 0
        self.feed(raw.decode('utf-8','strict'))

    def handle_starttag(self, tag, attrs):
        self.nodes += 1
        _need(self.nodes <= 50000 and len(self.stack) <= 128, 'UNIT_DOCUMENT_BOUND')
        attrs = dict(attrs); style = re.sub(r'\s+','',attrs.get('style','').lower())
        classes = set(attrs.get('class','').lower().split())
        hidden = (bool(self.stack and self.stack[-1][1]) or tag in self._HIDDEN or
            'hidden' in attrs or attrs.get('aria-hidden','').lower() == 'true' or
            'display:none' in style or 'visibility:hidden' in style or
            bool(classes & {'hidden','d-none','visually-hidden','sr-only'}))
        if tag in self._BLOCK:self.parts.append('\n')
        if tag not in self._VOID:self.stack.append((tag,hidden))

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1,-1,-1):
            if self.stack[index][0] == tag:
                self.stack = self.stack[:index]
                break
        if tag in self._BLOCK:self.parts.append('\n')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag,attrs)
        _need(tag in self._VOID or not self.stack[-1][1], 'AMBIGUOUS_SELF_CLOSED_HIDDEN_UNIT_CONTENT')
        self.handle_endtag(tag)

    def handle_data(self, value):
        if not self.stack or not self.stack[-1][1]:self.parts.append(value)


def validate_payout_unit_capture(value, *, now, source_rights_ref):
    """Replay an explicit official statement of the displayed payout unit.

    A minimum purchase of 100 yen is insufficient. This pure check grants no
    source permission, performs no OCR and authenticates no capture by itself.
    """
    now = _clock(now)
    _need(type(value) is dict and set(value) == {'raw_base64','metadata'}, 'PAYOUT_UNIT_CAPTURE_REQUIRED')
    raw = _decode(value['raw_base64']); metadata = value['metadata']
    _need(type(metadata) is dict, 'PAYOUT_UNIT_METADATA_REQUIRED')
    url = metadata.get('source_url'); validate_source_pair(url,source_rights_ref)
    parsed = urlsplit(url)
    _need(parsed.hostname in ('autorace.jp','www.autorace.jp') and metadata.get('final_url') == url and
          metadata.get('status') == 200 and type(metadata.get('byte_count')) is int and
          metadata['byte_count'] == len(raw) and metadata.get('source_sha256') == sha256(raw).hexdigest(),
          'PAYOUT_UNIT_HTTP_BINDING')
    captured = _clock(metadata.get('response_received_at'))
    _need(_clock(metadata.get('fetched_at')) <= captured <= now, 'PAYOUT_UNIT_CAPTURE_CLOCK')
    headers = metadata.get('headers')
    _need(type(headers) is dict, 'PAYOUT_UNIT_MIME')
    kinds = [v.lower().split(';',1)[0].strip() for k,v in headers.items() if str(k).lower() == 'content-type' and type(v) is str]
    _need(len(kinds) == 1 and kinds[0] in ('text/html','application/xhtml+xml','text/plain','image/svg+xml'), 'PAYOUT_UNIT_MIME')
    segments = [_text(value) for value in re.split(r'[。\r\n!！]+',''.join(_UnitText(raw).parts))]
    payout = r'(?:払戻金額|払い戻し金額|払戻し金額|払戻金|払い戻し金|払戻し金|払戻額|払い戻し額|配当金)'
    denominator = r'(?<![\d,.+\-])100円(?:券|の投票|投票)?(?:1枚)?(?:に対する|あたり|当たり|当り|につき)'
    subject = r'は[、,]?(?:すべて|全て|いずれも)?'
    forward = r'(?:※)?'+payout+subject+denominator+r'(?:の)?金額(?:です|となります|になります)'
    reverse = r'(?:※)?'+denominator+r'の'+payout+r'(?:を表示します|を表示しています|です|となります)'
    _need(any(re.fullmatch(forward,value) is not None or re.fullmatch(reverse,value) is not None
              for value in segments), 'EXPLICIT_PUBLISHED_PAYOUT_UNIT_REQUIRED')
    return dict(source_ref=url,source_sha256=metadata['source_sha256'],captured_at=metadata['response_received_at'],
                basis='EXPLICIT_OFFICIAL_PUBLISHED_PAYOUT_PER_100_YEN')


def _http(raw, metadata, endpoint, now, rights):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES and type(metadata) is dict, 'SOURCE_METADATA_REQUIRED')
    url = metadata.get('source_url'); validate_source_pair(url, rights)
    parsed = urlsplit(url)
    _need(parsed.hostname in ('autorace.jp', 'www.autorace.jp') and parsed.path == '/race_info/'+endpoint and
          not parsed.query and metadata.get('final_url') == url and metadata.get('status') == 200 and
          type(metadata.get('byte_count')) is int and metadata['byte_count'] == len(raw) and
          metadata.get('source_sha256') == sha256(raw).hexdigest() and
          metadata.get('ui_capture_kind') == 'NORMAL_BROWSER_UI' and metadata.get('http_method') == 'POST',
          'OFFICIAL_HTTP_BINDING')
    headers = metadata.get('headers')
    _need(type(headers) is dict and any(str(k).lower() == 'content-type' and
          type(v) is str and v.lower().split(';', 1)[0].strip() == 'application/json' for k,v in headers.items()),
          'JSON_RESPONSE_MIME_REQUIRED')
    capture = _clock(metadata.get('response_received_at'))
    _need(_clock(metadata.get('fetched_at')) <= capture <= now, 'ACTUAL_CAPTURE_CLOCK')
    _need(type(metadata.get('request_content_type')) is str and
          metadata['request_content_type'].lower().split(';', 1)[0].strip() == 'application/json', 'JSON_REQUEST_MIME_REQUIRED')
    return capture, parsed


def _request(encoded, metadata):
    raw = _decode(encoded)
    _need(len(raw) <= 16384 and metadata.get('request_body_sha256') == sha256(raw).hexdigest(),
          'ORIGINAL_REQUEST_BYTES_MISMATCH')
    value = _json(raw)
    _need(type(value) is dict and set(value) == {'placeCode', 'raceDate', 'raceNo'}, 'NORMAL_UI_REQUEST_SCHEMA')
    return dict(placeCode=_number(value['placeCode'], 1, 20), raceDate=_day(value['raceDate']).isoformat(),
                raceNo=_number(value['raceNo'], 1, 12, text=True))


def _race(info, request, capture):
    _need(info.get('placeKey') in VENUES and _number(info.get('placeCode'), 1, 20) == request['placeCode'] and
          _number(info.get('raceNo'), 1, 12, text=True) == request['raceNo'], 'RACE_REQUEST_BODY_MISMATCH')
    first, last = _day(info.get('periodStartDate')), _day(info.get('periodEndDate'))
    event = first+timedelta(days=_number(info.get('paragraphday'), 1, 14)-1)
    _need(first <= event <= last and event.isoformat() == request['raceDate'], 'RACE_EVENT_DAY_MISMATCH')
    def instant(name):
        value = info.get(name)
        _need(type(value) is str and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value), 'ACTUAL_SALES_AND_START_REQUIRED')
        return datetime.combine(event, datetime.strptime(value, '%H:%M').time(), JST)
    cutoff, start = instant('telvoteTime'), instant('raceStartTime')
    _need(cutoff < start and cutoff < capture, 'RESULT_NOT_AFTER_ACTUAL_CUTOFF')
    return dict(race_id=f'autorace:{event.isoformat()}:{info["placeKey"]}:{request["raceNo"]}',
        sport='autorace', venue=info['placeKey'], event_date_jst=event.isoformat(), race_no=request['raceNo'],
        sales_cutoff_at=cutoff.isoformat(), start_at=start.isoformat(),
        distance_m=_number(info.get('distance'),100,10000)), event


def _dom(value, race, info, host, capture, now, rights):
    _need(type(value) is dict and set(value) == {'raw_base64', 'metadata'}, 'RENDERED_DOM_CAPTURE_REQUIRED')
    raw = _decode(value['raw_base64']); metadata = value['metadata']
    _need(type(metadata) is dict and type(metadata.get('byte_count')) is int and metadata['byte_count'] == len(raw) and
          metadata.get('source_sha256') == sha256(raw).hexdigest(), 'RENDERED_DOM_BYTES_MISMATCH')
    root = 'https://'+host+'/race_info/Live/'+race['venue']
    validate_source_pair(metadata.get('source_url'), rights)
    _need(metadata['source_url'] == root and metadata.get('final_url') == root+'/RaceResult/'+
          race['event_date_jst']+'_'+str(race['race_no']), 'RENDERED_RESULT_CASE_URL_MISMATCH')
    _need(capture <= _clock(metadata.get('captured_at')) <= now, 'RENDERED_DOM_CLOCK')
    document = _Document(raw); text = _text(' '.join(document.parts)); event = _day(race['event_date_jst'])
    matches = [t for t in document.tables if re.search(r'(?<!\d)'+f'{event.month}月{event.day}日', t) and
               re.search(r'(?<!\d)'+str(race['race_no'])+'R', t) and
               re.search(r'(?<!\d)'+str(race['distance_m'])+'m', t) and '{{' not in t]
    _need(len(matches) == 1 and type(info.get('placeName')) is str and _text(info['placeName']) in text and
          f'{event.year}年' in text and '投票締切'+info['telvoteTime'] in text and
          '発走予定'+info['raceStartTime'] in text and 'レース結果' in text, 'RENDERED_RESULT_RACE_MISMATCH')
    return text


def _state(facts, status, reason, refunds=()):
    facts.update(status=status, reason=reason, ordered_top3=[], payout_per_100_yen=None,
                 refund_numbers=sorted(set(refunds)))
    return facts


def parse_official_result_source(raw, metadata, *, now, source_rights_ref):
    """Inspect private original source facts, without asserting a frozen pair."""
    now = _clock(now)
    capture, parsed = _http(raw, metadata, 'RaceResult', now, source_rights_ref)
    context = metadata.get('auto_result_context')
    _need(type(context) is dict and set(context) == {'schema','request_body_base64','race_info_capture','rendered_dom_capture'} and
          context['schema'] == CONTEXT, 'COMPLETE_SOURCE_CONTEXT_REQUIRED')
    request = _request(context['request_body_base64'], metadata)
    companion = context['race_info_capture']
    _need(type(companion) is dict and set(companion) == {'raw_base64','metadata','request_body_base64'}, 'RACE_INFO_CAPTURE_REQUIRED')
    info_raw = _decode(companion['raw_base64']); info_meta = companion['metadata']
    info_capture, info_url = _http(info_raw, info_meta, 'OtherRaceInfo', now, source_rights_ref)
    _need(info_url.hostname == parsed.hostname and info_capture <= capture and
          _request(companion['request_body_base64'], info_meta) == request, 'EARLIER_SAME_CASE_RACE_INFO_REQUIRED')
    info = _json_source(info_raw); race, _event = _race(info, request, capture)
    text = _dom(context['rendered_dom_capture'], race, info, parsed.hostname, capture, now, source_rights_ref)
    body = _json_source(raw)
    facts = dict(schema=SCHEMA, race=race, roster={}, finish_rows=[], captured_at=metadata['response_received_at'],
        published_at=None, source_ref=metadata['source_url'], source_sha256=metadata['source_sha256'],
        future_frozen_input_paired=False)
    refunds = body.get('refundInfo')
    _need(type(refunds) is dict, 'OFFICIAL_REFUND_INFO_REQUIRED')
    trifecta = refunds.get('rt3')
    _need(type(trifecta) is dict and type(trifecta.get('list')) is list and len(trifecta['list']) <= 16 and
          type(trifecta.get('typeName')) in (str,type(None)), 'TRIFECTA_SOURCE_SCHEMA')
    rows = body.get('raceResult')
    _need(rows is None or type(rows) is list and len(rows) <= 8, 'RESULT_ROWS_SCHEMA')
    identities, nonfinish, pending = set(), False, False
    for row in rows or []:
        _need(type(row) is dict, 'RESULT_ROW_SCHEMA')
        car = _number(row.get('carNo'),1,8); code = row.get('playerCode')
        _need(type(code) in (str,int) and type(code) is not bool and re.fullmatch(r'[0-9]{2,10}',str(code)) and
              int(code)>0 and str(car) not in facts['roster'] and str(code) not in identities, 'REGISTERED_DRIVER_ID_REQUIRED')
        code = str(code); facts['roster'][str(car)] = code; identities.add(code)
        value = row.get('order')
        if type(value) is int and 1 <= value <= 8 or type(value) is str and re.fullmatch(r'[1-8]',value):
            position = int(value)
        else:
            position = None; pending |= value in (None,'','-','--')
            nonfinish |= value not in (None,'','-','--')
        nonfinish |= row.get('accidentCode') not in (None,'',0,'0') or row.get('accidentName') not in (None,'') or row.get('retireFlag') not in (None,0,'0')
        name = row.get('playerName')
        _need(type(name) is str and 0 < len(name) <= 100 and _text(name) in text, 'RENDERED_REGISTERED_DRIVER_MISMATCH')
        facts['finish_rows'].append(dict(number=car, identity=code, finish=position))
    absent = refunds.get('absent')
    _need(type(absent) is list and len(absent) <= 8, 'REFUND_NUMBERS_SCHEMA')
    absent = [_number(value,1,8,text=True) for value in absent]
    _need(len(absent) == len(set(absent)), 'DUPLICATE_REFUND_NUMBER')
    typename = trifecta.get('typeName') or ''
    if any(word in typename for word in ('中止','不成立','取りやめ')):
        return _state(facts,'special','EXPLICIT_RACE_CANCELLATION',absent)
    if absent:
        return _state(facts,'special','EXPLICIT_RESULT_REFUND',absent)
    if nonfinish:
        return _state(facts,'special','NONFINISH_OR_ACCIDENT')
    if not rows or pending:
        return _state(facts,'pending','RESULT_PLACINGS_NOT_FINAL')
    _need(3 <= len(rows) <= 8, 'COMPLETE_RESULT_ROSTER_REQUIRED')
    ranks = [row['finish'] for row in facts['finish_rows']]
    if sorted(ranks) != list(range(1,len(rows)+1)):
        return _state(facts,'special','DEAD_HEAT_OR_NONUNIQUE_PLACINGS')
    code = trifecta.get('typeCode')
    if type(code) is int and code == 1:
        return _state(facts,'special','SPECIAL_TRIFECTA_PAYMENT')
    if type(code) is int and code == 5:
        return _state(facts,'special','NO_VOTE_TRIFECTA')
    if type(code) is not int or code != 0 or typename != '通常':
        return _state(facts,'special','SPECIAL_TRIFECTA_STATUS')
    payments = trifecta['list']
    if not payments:
        return _state(facts,'pending','TRIFECTA_PAYMENT_NOT_AVAILABLE')
    if len(payments) != 1:
        return _state(facts,'special','MULTIPLE_TRIFECTA_PAYMENTS')
    payment = payments[0]
    _need(type(payment) is dict, 'TRIFECTA_PAYMENT_SCHEMA')
    winning = [_number(payment.get(key),1,8) for key in ('1thCarNo','2thCarNo','3thCarNo')]
    amount = _number(payment.get('refund'),1,10**9)
    ordered = [row['number'] for row in sorted(facts['finish_rows'],key=lambda row:row['finish'])[:3]]
    _need(len(set(winning)) == 3 and winning == ordered, 'FINISH_TRIFECTA_CONFLICT')
    _need('3連単'+'-'.join(map(str,winning))+f'{amount:,}円' in text, 'RENDERED_TRIFECTA_PAYMENT_MISMATCH')
    unit_context = metadata.get('auto_result_archive_context')
    _need(type(unit_context) is dict and set(unit_context) == {'schema','payout_unit_capture'} and
          unit_context['schema'] == UNIT_CONTEXT, 'PAYOUT_UNIT_CAPTURE_REQUIRED')
    facts['payout_unit_basis'] = validate_payout_unit_capture(unit_context['payout_unit_capture'],
        now=now,source_rights_ref=source_rights_ref)
    facts.update(status='settled',reason='ORDINARY_SETTLED_RESULT',ordered_top3=ordered,
                 payout_per_100_yen=amount,refund_numbers=[])
    return facts


def parse_result(raw, metadata=None, *, frozen_native_payload, now, source_rights_ref):
    """Return the exact generic observation, after structural frozen pairing.

    A convenience packet is ``{'raw': actual_http_bytes, 'metadata': metadata}``.
    ``metadata.auto_result_context`` retains original request bytes, the earlier
    same-case OtherRaceInfo capture and the resulting DOM, all base64 encoded.
    The caller independently authenticates both native and result archives.
    """
    if metadata is None:
        _need(type(raw) is dict and set(raw) == {'raw','metadata'}, 'ORIGINAL_SOURCE_PACKET_REQUIRED')
        raw, metadata = raw['raw'], raw['metadata']
    now = _clock(now)
    facts = parse_official_result_source(raw,metadata,now=now,source_rights_ref=source_rights_ref)
    _need(type(frozen_native_payload) is dict and type(frozen_native_payload.get('snapshot')) is dict,
          'FROZEN_SHARED_NATIVE_INPUT_REQUIRED')
    snapshot = frozen_native_payload['snapshot']; race = snapshot.get('race')
    _need(type(race) is dict and race.get('sport') == 'autorace', 'FROZEN_AUTORACE_INPUT_REQUIRED')
    native.validate(snapshot,allow_source=lambda *_:True)
    _need(all(race.get(key) == facts['race'][key] for key in ('race_id','venue','event_date_jst')) and
          _clock(race.get('sales_cutoff_at')) == _clock(facts['race']['sales_cutoff_at']), 'FROZEN_RESULT_RACE_OR_CUTOFF_MISMATCH')
    _need(_clock(race.get('as_of')) < _clock(race['sales_cutoff_at']) < _clock(facts['captured_at']) <= now,
          'FROZEN_RESULT_CAPTURE_CLOCK')
    participants = snapshot['participants']
    expected = {str(p['number']):p['identity'] for p in participants}
    _need(len(expected) == len(participants) and len(set(expected.values())) == len(expected) and
          all(expected.get(car) == code for car,code in facts['roster'].items()) and
          all(str(car) in expected for car in facts['refund_numbers']), 'FROZEN_REGISTERED_ROSTER_MISMATCH')
    complete = facts['roster'] == expected
    _need(facts['status'] != 'settled' or complete, 'COMPLETE_FROZEN_RESULT_ROSTER_REQUIRED')
    return dict(race_id=race['race_id'],sport='autorace',status=facts['status'],reason=facts['reason'],
        ordered_top3=deepcopy(facts['ordered_top3']),roster=deepcopy(facts['roster']),identity_verified=complete,
        captured_at=facts['captured_at'],published_at=None,source_ref=facts['source_ref'],source_rights_ref=source_rights_ref,
        source_sha256=facts['source_sha256'],payout_per_100_yen=facts['payout_per_100_yen'],
        refund_numbers=deepcopy(facts['refund_numbers']),closed_at=race['sales_cutoff_at'])
