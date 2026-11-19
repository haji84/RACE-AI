"""Pure, private parsing of already captured official SP HTML receipts.

No HTTP, JavaScript execution, storage, model inference or source admission.
Expected hashes and observation clocks come from the caller's capture record;
this module supplies neither a server attestation nor an HTTP status proof.
Returned names, registrations and published form references remain private.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from math import isfinite
import re
from unicodedata import normalize

from . import keirin_official_schedule as calendar

MAX_HTML_BYTES = calendar.MAX_HTML_BYTES
JST = timezone(timedelta(hours=9))
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_CLOCK = re.compile(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z')
_JS_SPACE_PATTERN = r'[\t\v\f \u00a0\ufeff\r\n\u2028\u2029\u1680\u2000-\u200a\u202f\u205f\u3000]'
_JS_SPACE = re.compile(_JS_SPACE_PATTERN)
_LINE_END = re.compile(r'[\r\n\u2028\u2029]')
_ASSIGN = re.compile(r'(?<![A-Za-z0-9_$.])jsonData\s*\[\s*([\x27\"])([A-Z][A-Z0-9]{2,9})\1\s*\]\s*=\s*'.replace(r'\s', _JS_SPACE_PATTERN))
_NAMESPACE_DECL = re.compile(r'var\s+jsonData\s*=\s*(?:\{\s*\}|\[\s*\])\s*;'.replace(r'\s', _JS_SPACE_PATTERN))
_ROUTING_DECL = re.compile((
    r'var\s+(CONTEXT_PATH|FSJ0305_parentID|FSJ0305_showingID|currentPath|'
    r'displayingId|displayingSyoriKbn|parentFuncId)\s*=\s*'
    r'(?:([\x27\"])[A-Za-z0-9_/-]{0,80}\2|[0-9]{1,3})\s*;').replace(r'\s', _JS_SPACE_PATTERN))
_ROW_FIELDS = frozenset(('strRaceNo', 'strSyumokuName', 'strArrow', 'strArrowName',
                         'strRaceLnk', 'strRaceLnkPrm', 'strRaceLnkKbn', 'strColorClass'))
_RIDER_FIELDS = frozenset(('syaban', 'sensyuRegistNo', 'sensyuName', 'huKen',
    'kyakusitu', 'kyuhan', 'prevKyuhan', 'heikinTokuten', 'backCnt', 'nigeCnt',
    'makuriCnt', 'sasiCnt', 'markCnt', 'syabanBgColorInfo', 'syabanCharColorInfo'))
_NOTE_FIELDS = frozenset(('ketujyouTuikaHojyu', 'ketujyouTuikaHojyuColorInfo'))
# Published table image/alt text is presentation, not a calibrated strength input.
_PRESENTATION_FIELDS = frozenset(('imgTyosiName', 'imgTyosiPath'))


class OfficialSPReceiptError(ValueError):
    """Fixed-code rejection; never includes private source data."""


def _need(condition, code):
    if not condition:
        raise OfficialSPReceiptError('KEIRIN_OFFICIAL_SP_' + code)


def _norm(value):
    return re.sub(r'\s+', '', normalize('NFKC', value))


def _day(value):
    _need(type(value) is str and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value), 'DAY_INVALID')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise OfficialSPReceiptError('KEIRIN_OFFICIAL_SP_DAY_INVALID') from None


def _aware(value):
    _need(isinstance(value, datetime) and value.utcoffset() is not None, 'OBSERVATION_CLOCK_INVALID')
    return value.astimezone(timezone.utc)


def _body(raw, expected_sha256):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_HTML_BYTES, 'BODY_BOUND')
    _need(type(expected_sha256) is str and _SHA.fullmatch(expected_sha256) is not None
          and sha256(raw).hexdigest() == expected_sha256, 'BODY_HASH_MISMATCH')
    try:
        text = raw.decode('utf-8', 'strict')
        document = calendar._Document()
        document.feed(text)
        document.close()
    except (UnicodeError, calendar.OfficialCalendarError, RecursionError):
        raise OfficialSPReceiptError('KEIRIN_OFFICIAL_SP_HTML_INVALID_OR_BOUND') from None
    for tag in ('html', 'body'):
        nodes = [node for node in document.nodes if node.tag == tag]
        _need(len(nodes) == 1 and nodes[0].closed, 'HTML_INCOMPLETE_OR_AMBIGUOUS')
    html_node = next(node for node in document.nodes if node.tag == 'html')
    parent = next(node for node in document.nodes if node.tag == 'body').parent
    while parent is not None and parent is not html_node:
        parent = parent.parent
    _need(parent is html_node, 'BODY_NOT_INSIDE_HTML')
    return document


def _pairs(items):
    result = {}
    for key, value in items:
        _need(key not in result, 'DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _nonfinite(_):
    raise OfficialSPReceiptError('KEIRIN_OFFICIAL_SP_NONFINITE_JSON')


def _finite_float(value):
    number = float(value)
    _need(isfinite(number), 'NONFINITE_JSON')
    return number


def _skip_comments_and_space(script, index):
    while index < len(script):
        if _JS_SPACE.fullmatch(script[index]) is not None:
            index += 1
        elif script.startswith('//', index):
            end = _LINE_END.search(script, index + 2)
            index = len(script) if end is None else end.end()
        elif script.startswith('/*', index):
            end = script.find('*/', index + 2)
            _need(end != -1, 'UNTERMINATED_SCRIPT_COMMENT')
            index = end + 2
        else:
            break
    return index


def _embedded(document):
    """Consume only the observed static data grammar; never interpret JS."""
    data, declarations = {}, set()
    decoder = json.JSONDecoder(object_pairs_hook=_pairs, parse_constant=_nonfinite,
                               parse_float=_finite_float)
    for node in document.nodes:
        if node.tag != 'script' or 'jsonData' not in calendar._text(node):
            continue
        ancestors, parent = set(), node.parent
        while parent is not None:
            ancestors.add(parent.tag)
            parent = parent.parent
        _need('html' in ancestors and bool({'body', 'head'} & ancestors),
              'JSON_SCRIPT_OUTSIDE_DOCUMENT')
        _need(node.closed and 'src' not in node.attrs, 'JSON_SCRIPT_INCOMPLETE_OR_EXTERNAL')
        script, index = calendar._text(node), 0
        while True:
            index = _skip_comments_and_space(script, index)
            if index == len(script):
                break
            declaration = _NAMESPACE_DECL.match(script, index)
            if declaration is not None:
                _need('jsonData' not in declarations and not data,
                      'GLOBAL_JSON_DECLARATION_REPEATED_OR_LATE')
                declarations.add('jsonData')
                index = declaration.end()
                continue
            routing = _ROUTING_DECL.match(script, index)
            if routing is not None:
                _need(routing[1] not in declarations, 'REPEATED_ROUTING_DECLARATION')
                declarations.add(routing[1])
                index = routing.end()
                continue
            assignment = _ASSIGN.match(script, index)
            _need(assignment is not None, 'UNRECOGNIZED_JSON_SCRIPT_STATEMENT')
            code = assignment[2]
            _need(code not in data and len(data) < 16, 'DUPLICATE_OR_EXCESS_JSON_DOCUMENT')
            try:
                value, end = decoder.raw_decode(script, assignment.end())
            except (ValueError, RecursionError):
                raise OfficialSPReceiptError('KEIRIN_OFFICIAL_SP_JSON_INVALID') from None
            end = _skip_comments_and_space(script, end)
            _need(type(value) is dict and script[end:end+1] == ';', 'JSON_BOUNDARY_OR_TYPE')
            data[code], index = value, end + 1
    return data


def _calendar_binding(receipt, expected_day, expected_venue_code, observed_at):
    _need(type(receipt) is dict and set(receipt) == {'raw_bytes', 'expected_sha256', 'observed_at'}, 'CALENDAR_RECEIPT_SCHEMA')
    _need(type(expected_venue_code) is int and 1 <= expected_venue_code <= 99, 'VENUE_CODE_INVALID')
    received = _aware(receipt['observed_at'])
    _need(received <= observed_at, 'CALENDAR_OBSERVED_AFTER_DOCUMENT')
    document = _body(receipt['raw_bytes'], receipt['expected_sha256'])
    try:
        parsed = calendar.parse_calendar(receipt['raw_bytes'], source_url=calendar.OFFICIAL_DOCUMENT,
            body_sha256=receipt['expected_sha256'], received_at=received, now=observed_at, http_status=200)
        projection = calendar.project_day(parsed, event_day=expected_day)
    except calendar.OfficialCalendarError:
        raise OfficialSPReceiptError('KEIRIN_OFFICIAL_SP_CALENDAR_BINDING_INVALID') from None
    candidates = [item for item in projection['calendar_meeting_candidates']
                  if item['venue_code'] == expected_venue_code]
    _need(len(candidates) == 1, 'CALENDAR_DAY_VENUE_NOT_UNIQUE')
    names = []
    for node in document.nodes:
        if node.tag != 'button':
            continue
        match = calendar._VENUE.fullmatch(calendar._attribute(node, 'onclick'))
        if match is not None and int(match[1]) == expected_venue_code:
            name = _norm(calendar._text(node))
            _need(bool(name) and len(name) <= 100, 'CALENDAR_VENUE_NAME_INVALID')
            names.append(name)
    _need(len(names) == 1, 'CALENDAR_VENUE_NAME_NOT_UNIQUE')
    return names[0], candidates[0]


def _prepare(raw, expected_day, expected_venue_code, observed_at, expected_sha256, calendar_receipt):
    day, observed = _day(expected_day), _aware(observed_at)
    document = _body(raw, expected_sha256)
    name, meeting = _calendar_binding(calendar_receipt, expected_day, expected_venue_code, observed)
    data = _embedded(document)
    header_doc = data.get('SC0201')
    _need(type(header_doc) is dict and type(header_doc.get('resultCd')) is int
          and header_doc['resultCd'] == 0 and type(header_doc.get('C0201data')) is dict, 'HEADER_UNAVAILABLE')
    header = header_doc['C0201data']
    _need(type(header.get('joName')) is str and _norm(header['joName']) == name, 'HEADER_CALENDAR_VENUE_MISMATCH')
    common = dict(source_sha256=expected_sha256, source_observed_at=observed.isoformat(),
        calendar_source_sha256=calendar_receipt['expected_sha256'],
        calendar_meeting_reference_sha256=meeting['navigation_reference_sha256'],
        event_date_jst=expected_day, venue_code=expected_venue_code,
        source_admission=False, model_input_admission=False, full_pr71_admission=False,
        all_nationwide_coverage_verified=False, full_active_eligibility_verified=False,
        missing_model_origins_preserved=True, model_generation=0, provider_http_requests=0,
        http_status_verified=False, private_only=True)
    return day, observed, data, header, common


def parse_race_list(raw_bytes, *, expected_day, expected_venue_code, observed_at,
                    expected_sha256, calendar_receipt):
    """Return actual dated identities and private references; admit no clocks."""
    day, observed, data, header, result = _prepare(raw_bytes, expected_day, expected_venue_code,
        observed_at, expected_sha256, calendar_receipt)
    listing = data.get('SJ0301')
    _need(type(listing) is dict and type(listing.get('resultCd')) is int
          and listing['resultCd'] == 0, 'RACE_LIST_UNAVAILABLE')
    groups = listing.get('kaisaiDayList')
    _need(type(groups) is list and 1 <= len(groups) <= 7, 'DAY_GROUP_BOUND')
    selected, labels = [], set()
    for group in groups:
        _need(type(group) is dict and type(group.get('strKaisaiNitijName')) is str, 'DAY_GROUP_SCHEMA')
        label = re.fullmatch(r'(?:初日|最終日|[2-9]日目)\(([0-9]{1,2})/([0-9]{1,2})\)', _norm(group['strKaisaiNitijName']))
        _need(label is not None, 'DAY_LABEL_INVALID')
        month_day = tuple(map(int, label.groups()))
        _need(month_day not in labels, 'DUPLICATE_DAY_GROUP')
        labels.add(month_day)
        if month_day == (day.month, day.day):
            selected.append(group)
    _need(len(selected) == 1, 'EXPECTED_DAY_GROUP_NOT_UNIQUE')
    rows = selected[0].get('raceProgramList')
    _need(type(rows) is list and 1 <= len(rows) <= 12, 'RACE_ROW_BOUND')
    races, references, seen = [], [], set()
    for row in rows:
        _need(type(row) is dict and set(row) == _ROW_FIELDS and
              all(type(value) is str and len(value) <= 512 for value in row.values()), 'RACE_ROW_SCHEMA')
        number = _norm(row['strRaceNo'])
        _need(re.fullmatch(r'[1-9]|1[0-2]', number) is not None and int(number) not in seen, 'RACE_NUMBER_INVALID_OR_DUPLICATE')
        number = int(number)
        seen.add(number)
        _need(row['strRaceLnk'] == '/sp/race' and row['strRaceLnkKbn'] in ('1', '2')
              and re.fullmatch(r'[A-Za-z0-9_-]{43}', row['strRaceLnkPrm']) is not None, 'RACE_REFERENCE_UNREVIEWED')
        races.append(dict(race_id=day.strftime('%Y%m%d')+f'{expected_venue_code:02d}{number:02d}',
                          venue_code=expected_venue_code, race_no=number))
        references.append(dict(race_no=number, path=row['strRaceLnk'],
            opaque_reference=row['strRaceLnkPrm'], link_kind=row['strRaceLnkKbn']))
    _need(seen == set(range(1, len(seen)+1)), 'RACE_UNIVERSE_HAS_GAPS')
    result.update(schema='RACE_AI_KEIRIN_OFFICIAL_SP_RACE_LIST_RECEIPT_V1',
        source_url='https://keirin.jp/sp/racelist', source_method='POST',
        race_count=len(races), header_clocks_admitted=False, official_cutoffs_verified=False,
        day_roster_manifest=dict(schema=calendar.DAY_ROSTER_SCHEMA, event_date_jst=expected_day,
            source_url='https://keirin.jp/sp/racelist', source_sha256=expected_sha256,
            captured_at=observed.isoformat(), races=sorted(races, key=lambda row: row['race_no'])),
        race_references=sorted(references, key=lambda row: row['race_no']))
    return result


def _clock(value, optional=False):
    if optional and value == '':
        return None
    _need(type(value) is str and _CLOCK.fullmatch(value) is not None, 'CLOCK_INVALID')
    return value


def parse_race_detail(raw_bytes, *, expected_day, expected_venue_code,
                      expected_race_number, observed_at, expected_sha256, calendar_receipt):
    """Preserve one exact selected race's official clocks and published roster."""
    day, observed, data, header, result = _prepare(raw_bytes, expected_day, expected_venue_code,
        observed_at, expected_sha256, calendar_receipt)
    _need(type(expected_race_number) is int and 1 <= expected_race_number <= 12
          and type(header.get('selRaceNo')) is int and header['selRaceNo'] == expected_race_number
          and header.get('txtEventDate') == day.strftime('%Y/%m/%d'), 'DETAIL_DAY_OR_RACE_MISMATCH')
    _need(type(header.get('flgRaceCancel')) is bool, 'CANCELLATION_TYPE_INVALID')
    bet, start = _clock(header.get('aftBetTime')), _clock(header.get('aftStartTime'))
    prior_bet, prior_start = _clock(header.get('bfrBetTime'), True), _clock(header.get('bfrStartTime'), True)
    stamp = header.get('aftBetDate')
    _need(type(stamp) is str and re.fullmatch(r'[0-9]{12}', stamp) is not None
          and stamp == day.strftime('%Y%m%d')+bet.replace(':', ''), 'OFFICIAL_CUTOFF_DATE_MISMATCH')
    cutoff = datetime.combine(day, datetime.strptime(bet, '%H:%M').time(), tzinfo=JST)
    start_at = datetime.combine(day, datetime.strptime(start, '%H:%M').time(), tzinfo=JST)
    _need(cutoff < start_at, 'CUTOFF_NOT_BEFORE_START')
    roster_doc = data.get('SJ0315')
    _need(type(roster_doc) is dict and type(roster_doc.get('resultCd')) is int
          and roster_doc['resultCd'] == 0 and roster_doc.get('syusouInfoExistFlg') == '1', 'ROSTER_UNAVAILABLE')
    source_rows = roster_doc.get('sensyuTypeInfo')
    _need(type(source_rows) is list and 1 <= len(source_rows) <= 9, 'ROSTER_ROW_BOUND')
    riders, cars, identifiers = [], set(), set()
    statuses = {'': 'UNSPECIFIED', '補充': 'SUPPLEMENTAL', '追加': 'ADDED', '欠場': 'WITHDRAWN'}
    for row in source_rows:
        _need(type(row) is dict
              and _RIDER_FIELDS <= set(row) <= _RIDER_FIELDS | _NOTE_FIELDS | _PRESENTATION_FIELDS
              and (not (_PRESENTATION_FIELDS & set(row)) or _PRESENTATION_FIELDS <= set(row))
              and all(type(value) is str and len(value) <= 160 for value in row.values()), 'ROSTER_ROW_SCHEMA')
        _need(re.fullmatch(r'[1-9]', row['syaban']) is not None and
              re.fullmatch(r'[0-9]{6}', row['sensyuRegistNo']) is not None and
              bool(row['sensyuName'].strip()), 'RIDER_IDENTITY_INVALID')
        car, identity = int(row['syaban']), row['sensyuRegistNo']
        _need(car not in cars and identity not in identifiers, 'DUPLICATE_RIDER_OR_CAR')
        cars.add(car);identifiers.add(identity)
        score = row['heikinTokuten']
        if score in ('', '-', '--'):
            score = None
        else:
            _need(re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', score) is not None, 'SCORE_FORMAT_INVALID')
            try:
                _need(Decimal(score).is_finite(), 'SCORE_NONFINITE')
            except InvalidOperation:
                raise OfficialSPReceiptError('KEIRIN_OFFICIAL_SP_SCORE_FORMAT_INVALID') from None
        note = row.get('ketujyouTuikaHojyu', '')
        riders.append(dict(car=car, registration_id=identity, name=row['sensyuName'],
            score_raw=score, entry_note_raw=note, entry_status=statuses.get(note, 'UNKNOWN'),
            statistics_raw={key: row[key] for key in ('backCnt', 'nigeCnt', 'makuriCnt', 'sasiCnt', 'markCnt')}))
    withdrawals = sum(row['entry_status'] == 'WITHDRAWN' for row in riders)
    unknown = sum(row['entry_status'] == 'UNKNOWN' for row in riders)
    result.update(schema='RACE_AI_KEIRIN_OFFICIAL_SP_RACE_DETAIL_RECEIPT_V1',
        source_url='https://keirin.jp/sp/race', source_method='POST',
        race_id=day.strftime('%Y%m%d')+f'{expected_venue_code:02d}{expected_race_number:02d}',
        race_no=expected_race_number, official_cutoff_at=cutoff.isoformat(), start_at=start_at.isoformat(),
        prior_betting_cutoff_clock=prior_bet, prior_start_clock=prior_start,
        observed_before_official_cutoff=observed < cutoff, race_cancelled=header['flgRaceCancel'],
        riders=sorted(riders, key=lambda row: row['car']), withdrawal_count=withdrawals,
        unknown_entry_status_count=unknown, pr71_cardinality_supported=len(riders) in (7, 9),
        no_published_roster_exclusion_observed=not (header['flgRaceCancel'] or withdrawals or unknown))
    return result
