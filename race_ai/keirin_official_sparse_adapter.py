"""Offline conversion of self-identifying normal-browser KEIRIN responses.

Only published win frequency and optional within-roster ordinal score rank are
observed features. Unknown history windows, sample sizes and environment stay
missing. This module performs no requests, storage, fitting or receipt issuance.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from unicodedata import normalize
from urllib.parse import urlsplit

from .actions_contract import digest
from . import comprehensive_four_sport_models as native
from .four_sport_learning import LEARNED_ID, forecast as ranker_forecast
from .four_sport_model_suite import ALL_MODELS
from .manual_official_capture import official_rights_ref, validate_source_pair


SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_NATIVE_INPUTS_V1'
CELLS = tuple('keirin/'+mid for mid in (*ALL_MODELS, LEARNED_ID))
JST = timezone(timedelta(hours=9))
MAX_BYTES = 2*1024*1024
HOSTS = frozenset(('keirin.jp', 'www.keirin.jp'))


def _need(ok, reason):
    if not ok:
        raise ValueError('KEIRIN_SPARSE_'+reason)


def _clock(value):
    try:
        instant = value if type(value) is datetime else datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(instant.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
        return instant
    except (TypeError, ValueError, AttributeError):
        raise ValueError('KEIRIN_SPARSE_AWARE_CLOCK_REQUIRED') from None


def _text(value):
    _need(type(value) is str, 'OBSERVED_TEXT_REQUIRED')
    return re.sub(r'\s+', '', normalize('NFKC', value))


def _integer(value, low, high):
    _need(type(value) is int or type(value) is str and re.fullmatch(r'[0-9]{1,6}', value),
          'OBSERVED_INTEGER_REQUIRED')
    result = int(value)
    _need(low <= result <= high, 'OBSERVED_INTEGER_REQUIRED')
    return result


def _identity(value):
    _need(type(value) is str and re.fullmatch(r'[0-9]{6}', value) and int(value) > 0,
          'STABLE_RIDER_ID_REQUIRED')
    return value


def _path(url, rights):
    validate_source_pair(url, rights)
    parsed = urlsplit(url)
    _need(parsed.hostname in HOSTS and not parsed.query, 'OFFICIAL_KEIRIN_URL_REQUIRED')
    return parsed.path


class _Scripts(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=False)
        _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'BOUNDED_HTML_REQUIRED')
        self.scripts, self.current = [], None
        self.feed(raw.decode('utf-8', 'strict'))
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            _need(self.current is None, 'SCRIPT_STRUCTURE')
            self.current = []

    def handle_endtag(self, tag):
        if tag == 'script' and self.current is not None:
            self.scripts.append(''.join(self.current))
            self.current = None

    def handle_data(self, value):
        if self.current is not None:
            self.current.append(value)


def _embedded(raw, keys):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            _need(key not in out, 'DUPLICATE_JSON_FIELD')
            out[key] = value
        return out
    decoder = json.JSONDecoder(object_pairs_hook=unique,
        parse_constant=lambda _: _need(False, 'NONFINITE_JSON'))
    scripts = _Scripts(raw).scripts
    out = {}
    for key in keys:
        pattern = re.compile(r'jsonData\[\s*[\'\"]'+re.escape(key)+r'[\'\"]\s*\]\s*=\s*')
        members = [(script, match.end()) for script in scripts for match in pattern.finditer(script)]
        _need(len(members) == 1, 'EXACT_EMBEDDED_JSON_REQUIRED')
        script, offset = members[0]
        value, end = decoder.raw_decode(script[offset:])
        _need(type(value) is dict and script[offset+end:].lstrip().startswith(';'), 'EMBEDDED_JSON_LITERAL_REQUIRED')
        out[key] = value
    return out


def _browser(metadata, now, rights):
    _need(type(metadata) is dict and metadata.get('schema') == 'RACE_AI_PRIVATE_OFFICIAL_BROWSER_PROBE_V1' and
          metadata.get('normal_ui_only') is True and metadata.get('undocumented_api_manually_called') is False and
          metadata.get('http_access_denied') is False and metadata.get('entire_host_stopped') is False and
          metadata.get('stop_reason') == 'FINISHED', 'NORMAL_UI_CAPTURE_REQUIRED')
    _need(_path(metadata.get('source_url'), rights) == '/pc/top', 'NORMAL_UI_TOP_REQUIRED')
    _need(type(metadata.get('network_host_allowlist')) is list and
          set(metadata['network_host_allowlist']) == HOSTS, 'OFFICIAL_HOST_GUARD_REQUIRED')
    started, completed = _clock(metadata.get('started_at')), _clock(metadata.get('captured_at'))
    _need(started <= completed <= now, 'CAPTURE_COMPLETION_CLOCK')
    ledger = metadata.get('ledger')
    _need(type(ledger) is list and 1 <= len(ledger) <= 2048 and all(type(e) is dict for e in ledger),
          'BOUNDED_LEDGER_REQUIRED')
    _need(not any(type(e.get('status')) is int and 400 <= e['status'] < 500 for e in ledger),
          'HOST_DENIAL_CAPTURE_REJECTED')
    for entry in ledger:
        if type(entry.get('status')) is int:
            validate_source_pair(entry.get('url'), rights)
            _need(urlsplit(entry['url']).hostname in HOSTS, 'OFFICIAL_KEIRIN_URL_REQUIRED')
        if entry.get('event') == 'NORMAL_SEMANTIC_UI_CLICK':
            _need(started <= _clock(entry.get('at')) <= completed, 'UI_CLICK_CLOCK')
            _path(entry.get('before'), rights)
            _path(entry.get('after'), rights)
    return ledger, started, completed


def _source(raw, metadata, path, now, rights):
    ledger, started, completed = _browser(metadata, now, rights)
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'BOUNDED_HTML_REQUIRED')
    members = [e for e in ledger if e.get('status') == 200 and e.get('source_sha256') == sha256(raw).hexdigest() and
               e.get('url') in tuple('https://'+host+path for host in HOSTS)]
    _need(members, 'SOURCE_RESPONSE_BINDING')
    entry = max(members, key=lambda e: _clock(e.get('body_captured_at')))
    _need(entry.get('method') == 'POST' and entry.get('status') == 200 and
          entry.get('resource_type') == 'document' and entry.get('byte_count') == len(raw) and
          type(entry.get('content_type')) is str and entry['content_type'].lower().startswith('text/html'),
          'NORMAL_UI_RESPONSE_REQUIRED')
    request, response, capture = (_clock(entry.get(key)) for key in
                                 ('request_started_at', 'response_received_at', 'body_captured_at'))
    _need(started <= request <= response <= capture <= completed <= now, 'SOURCE_CLOCK_ORDER')
    return dict(source_ref=entry['url'], source_rights_ref=rights, source_sha256=entry['source_sha256'],
        captured_at=entry['body_captured_at'], published_at=None, evidence_basis='NORMAL_UI_HTTP_RESPONSE_BODY_SHA256')


def _clicked(metadata, before, after, label, rights):
    return any(e.get('event') == 'NORMAL_SEMANTIC_UI_CLICK' and
        _path(e.get('before'), rights) == before and _path(e.get('after'), rights) == after and
        _text(e.get('label')).replace('\\n', '') == label for e in metadata['ledger'])


def _case(listing, live, now):
    selected = live['PC0201']['C0201data']
    listed = listing['PC0201']['C0201data']
    day = selected.get('selKaisai')
    _need(type(day) is str and re.fullmatch(r'[0-9]{8}', day), 'EXPLICIT_RACE_DAY_REQUIRED')
    day = date.fromisoformat(day[:4]+'-'+day[4:6]+'-'+day[6:])
    _need(now.astimezone(JST).date() == day and listed.get('selKaisai') == selected['selKaisai'] ==
          listing['PJ0305'].get('kaisaihi'), 'SOURCE_RACE_DAY_MISMATCH')
    venue = selected.get('selKjyoCd')
    _need(type(venue) is str and re.fullmatch(r'[0-9]{2}', venue) and int(venue) > 0 and
          listed.get('selKjyoCd') == venue == listing['PJ0305'].get('keirinCd') ==
          live['PJ0315'].get('bKeirinjyoCd'), 'SOURCE_VENUE_MISMATCH')
    number = _integer(selected.get('selRaceNo'), 1, 12)
    rows = listing['PJ0305'].get('rInfo')
    _need(type(rows) is list and 1 <= len(rows) <= 12 and all(type(v) is dict for v in rows), 'RACE_LIST_REQUIRED')
    matches = [v for v in rows if _integer(v.get('raceNo'), 1, 12) == number]
    _need(len(matches) == 1, 'SOURCE_RACE_NUMBER_MISMATCH')
    row = matches[0]
    for flag in ('flgRaceCancel', 'flgSectionCancel'):
        _need(selected.get(flag) in (None, False, 0), 'CURRENT_RACE_CANCELLED')
    detail = selected['C0201racedtl']
    _need(type(detail) is dict and detail.get('flgViewPut') is True, 'PUBLISHED_RACE_DETAIL_REQUIRED')
    for suffix, source in (('BetTime', 'denTime'), ('StartTime', 'stTime')):
        clock = row.get(source)
        _need(type(clock) is str and re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', clock) and
              detail.get('aft'+suffix) == clock == detail.get('bfr'+suffix), 'EXACT_PUBLISHED_CUTOFF_REQUIRED')
    def local(clock):
        return datetime.combine(day, datetime.strptime(clock, '%H:%M').time(), JST)
    cutoff, start = local(row['denTime']), local(row['stTime'])
    _need(now+timedelta(seconds=120) < cutoff < start, 'FUTURE_CUTOFF_MARGIN_REQUIRED')
    distance = _integer(detail.get('kyori'), 100, 10000)
    kind = detail.get('syumoku')
    _need(type(kind) is str and 0 < len(kind) <= 90, 'ACTUAL_RACE_KIND_REQUIRED')
    race = dict(race_id=f'keirin:{day.isoformat()}:keirin-jyo-{venue}:{number}', sport='keirin',
        venue='keirin-jyo-'+venue, event_date_jst=day.isoformat(), sales_cutoff_at=cutoff.isoformat(),
        as_of=now.isoformat(), distance_m=distance, surface='velodrome', race_kind=kind, race_revision=1)
    return race, row, detail, number, start.isoformat()


def _roster(listed, detailed, header):
    _need(type(listed) is list and 7 <= len(listed) <= 9 and type(detailed) is list and
          7 <= len(detailed) <= 9 and type(header) is list and 7 <= len(header) <= 9, 'CURRENT_ROSTER_REQUIRED')
    all_roster, active = {}, {}
    for rider in listed:
        _need(type(rider) is dict, 'CURRENT_ROSTER_REQUIRED')
        slot, identity = _integer(rider.get('syaban'), 1, 9), _identity(rider.get('senNo'))
        _need(slot not in all_roster and identity not in all_roster.values(), 'DUPLICATE_ROSTER_IDENTITY')
        all_roster[slot] = identity
        status = _text(rider.get('assen', ''))
        if '欠場' not in status and '取消' not in status:
            _need(status in ('', '(追加)', '(補充)', '追加', '補充'), 'UNKNOWN_PARTICIPATION_STATE')
            active[slot] = rider
    _need(len(active) in (7, 9), 'SEVEN_OR_NINE_ACTIVE_RIDERS_REQUIRED')
    sources = []
    for rows, slot_key, id_key in ((detailed, 'syaban', 'sensyuRegistNo'), (header, 'carNum', 'numPlayer')):
        by_slot = {}
        for rider in rows:
            _need(type(rider) is dict, 'CURRENT_ROSTER_REQUIRED')
            slot, identity = _integer(rider.get(slot_key), 1, 9), _identity(rider.get(id_key))
            _need(slot not in by_slot and all_roster.get(slot) == identity, 'SOURCE_ROSTER_MISMATCH')
            by_slot[slot] = rider
        _need(set(active) <= set(by_slot), 'ACTIVE_RIDER_DETAIL_MISSING')
        sources.append(by_slot)
    return active, sources[0]


def _number(value, *, optional=False, maximum=100):
    if optional and value in (None, '', '--', '-', '―', '－'):
        return None
    _need(type(value) in (str, int, float) and type(value) is not bool, 'OBSERVED_NUMERIC_REQUIRED')
    text = normalize('NFKC', str(value)).strip()
    _need(re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', text), 'OBSERVED_NUMERIC_REQUIRED')
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise ValueError('KEIRIN_SPARSE_OBSERVED_NUMERIC_REQUIRED') from None
    _need(number.is_finite() and 0 <= number <= maximum, 'OBSERVED_NUMERIC_RANGE')
    return number


def _convert(racelist_raw, racelist_metadata, racelive_raw, racelive_metadata, *, now,
             rendered_dom_bytes, browser_metadata, source_rights_ref, allow_source, baseline_ranker):
    now = _clock(now)
    browser = racelive_metadata if browser_metadata is None else browser_metadata
    evidence = [_source(racelist_raw, racelist_metadata, '/pc/racelist', now, source_rights_ref),
                _source(racelive_raw, racelive_metadata, '/pc/racelive', now, source_rights_ref)]
    _browser(browser, now, source_rights_ref)
    dom = browser.get('rendered_dom')
    _need(type(rendered_dom_bytes) is bytes and 0 < len(rendered_dom_bytes) <= MAX_BYTES and
          type(dom) is dict and dom.get('byte_count') == len(rendered_dom_bytes) and
          dom.get('source_sha256') == sha256(rendered_dom_bytes).hexdigest(), 'EXACT_RENDERED_DOM_REQUIRED')
    listing, live = _embedded(racelist_raw, ('PC0201', 'PJ0305')), _embedded(racelive_raw, ('PC0201', 'PJ0315'))
    _need(_embedded(rendered_dom_bytes, ('PC0201', 'PJ0315')) == live, 'RENDERED_SOURCE_CASE_MISMATCH')
    race, row, detail, number, start = _case(listing, live, now)
    _need(_clicked(racelist_metadata, '/pc/top', '/pc/racelist', '出走表一覧', source_rights_ref) and
          _clicked(browser, '/pc/racelist', '/pc/racelive', str(number)+'R', source_rights_ref),
          'NORMAL_UI_RACE_SELECTION_REQUIRED')
    active, detailed = _roster(row.get('sInfo'), live['PJ0315'].get('sensyuTypeInfo'), detail.get('C0201sensyu'))
    points = {slot:_number(detailed[slot].get('heikinTokuten'), optional=True, maximum=1000) for slot in active}
    points_complete = all(v is not None for v in points.values())
    allowed = set(native.COMMON_REQUIRED+native.SPORT_REQUIRED['keirin']+native.SPORT_OPTIONAL['keirin'])
    participants, lineage = [], []
    proof = {k:v for k,v in evidence[1].items() if k != 'evidence_basis'}
    for slot in sorted(active):
        rider = detailed[slot]
        win = _number(rider.get('syouritu'))
        features = dict(recent_win_form=dict(value=float(win/100), sample_n=None,
            transform_id='keirin-official-published-win-percent-divide100-v1', **proof))
        rank = None
        if points_complete:
            rank = (sum(value < points[slot] for value in points.values())+
                    .5*(sum(value == points[slot] for value in points.values())-1))/(len(active)-1)
            features['recent_points'] = dict(value=rank, sample_n=None,
                transform_id='keirin-official-current-roster-score-midrank-percentile-v1', **proof)
        source_style = rider.get('kyakusitu', '')
        style = {'追':'closer', '逃':'front', '両':'allround'}.get(_text(source_style), 'unknown')
        participants.append(dict(number=slot, identity=active[slot]['senNo'], draw=slot, style=style, group_id=None,
            features=features, missing={key:'NOT_AVAILABLE' for key in sorted(allowed-set(features))}))
        lineage.append(dict(number=slot, identity=active[slot]['senNo'], participation_annotation=active[slot].get('assen'),
            running_style=dict(source_field='PJ0315.sensyuTypeInfo.kyakusitu', source_value=source_style,
                native_category=style, transform='追=closer;逃=front;両=allround;other=unknown'),
            win_frequency=dict(source_field='PJ0315.sensyuTypeInfo.syouritu', source_unit='PERCENT',
                transform='observed_percent / 100', period_start=None, period_end=None, sample_n=None),
            points_rank=dict(source_field='PJ0315.sensyuTypeInfo.heikinTokuten', observed=points_complete,
                transform='(count(strictly_lower) + 0.5 * (count(equal) - 1)) / (active_roster_size - 1)',
                interpretation='WITHIN_CURRENT_ACTIVE_ROSTER_ORDINAL_MIDRANK_NOT_PROBABILITY',
                period_start=None, period_end=None, sample_n=None)))
    snapshot = dict(schema=native.SCHEMA_SPARSE, scope=native.RESEARCH, race=race, participants=participants,
        environment={}, environment_missing={key:'NOT_AVAILABLE' for key in native.ENV_COMMON+native.ENV_SPORT['keirin']})
    refs = sorted({(entry['source_ref'], entry['source_rights_ref']) for entry in evidence})
    def permission(ref, rights, purpose):
        return purpose == 'analysis' and (ref, rights) in refs and (allow_source is None or allow_source(ref, rights, purpose) is True)
    native.validate(snapshot, allow_source=permission)
    if baseline_ranker is not None:
        ranker_forecast(snapshot, baseline_ranker, allow_source=permission)
    audit = dict(schema='RACE_AI_KEIRIN_OFFICIAL_SOURCE_LINEAGE_V1', race_id=race['race_id'],
        event_date_jst=race['event_date_jst'], as_of=now.isoformat(), sales_cutoff_at=race['sales_cutoff_at'],
        race_start_at=start, source_evidence=deepcopy(evidence), rendered_dom_sha256=dom['source_sha256'],
        browser_metadata_sha256=digest(browser), racelist_metadata_sha256=digest(racelist_metadata),
        racelive_metadata_sha256=digest(racelive_metadata), request_body_retained=False,
        source_identity_basis='SELF_IDENTIFYING_RESPONSE_DAY_VENUE_RACE_AND_CROSS_SOURCE_ROSTER_CUTOFF',
        feature_lineage=lineage, draw_semantics='ACTUAL_CURRENT_CAR_NUMBER_NO_RENUMBERING',
        race_revision_semantics='LOCAL_CAPTURE_VERSION_ONE_NOT_OFFICIAL_REVISION',
        provider_model_training_permission_confirmed=False)
    requests = []
    for mid in (*ALL_MODELS, LEARNED_ID):
        payload = dict(snapshot=deepcopy(snapshot), scope=native.RESEARCH, stage='P0', source_evidence=deepcopy(evidence),
            adapter_lineage=deepcopy(audit), source_audit_sha256=digest(audit))
        if mid == LEARNED_ID and baseline_ranker is not None:
            payload['learned_model'] = deepcopy(baseline_ranker)
        requests.append(dict(cell_key='keirin/'+mid, native_payload=payload))
    return dict(schema=SCHEMA, state='READY', requests=requests, race=race, snapshot=snapshot,
        race_id=race['race_id'], cutoff_at=race['sales_cutoff_at'], source_evidence=evidence, source_refs=refs,
        feature_lineage=lineage, source_audit=audit, source_audit_sha256=digest(audit), reasons=[],
        model_states={cell:dict(state='READY', reason='OBSERVED_SPARSE_NATIVE_INPUT') for cell in CELLS},
        summary=dict(participants=len(participants), native_input_requests=len(requests), observed_win_frequency=len(participants),
            points_rank_included=points_complete, ranker_baseline_supplied=baseline_ranker is not None, forecasts_generated=0),
        independent_pre_cutoff_receipt_verified=False, provider_model_training_permission_confirmed=False,
        source_requests=0, production_promoted=False)


def build_native_inputs(racelist_raw, racelist_metadata, racelive_raw, racelive_metadata, *, now,
                        rendered_dom_bytes, browser_metadata=None,
                        source_rights_ref=official_rights_ref('keirin'), allow_source=None, baseline_ranker=None):
    """Return five existing native input capsules or HOLD, without network/storage.

    Exact response bytes are bound to normal-UI metadata, never called request
    bytes. Their hashes establish integrity, not an independent save receipt or
    provider training grant. A ranker input alone is not a fitted forecast.
    """
    try:
        return _convert(racelist_raw, racelist_metadata, racelive_raw, racelive_metadata, now=now,
            rendered_dom_bytes=rendered_dom_bytes, browser_metadata=browser_metadata,
            source_rights_ref=source_rights_ref, allow_source=allow_source, baseline_ranker=baseline_ranker)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError) as exc:
        reason = str(exc) if re.fullmatch(r'KEIRIN_SPARSE_[A-Z_]{1,100}', str(exc)) else 'KEIRIN_SPARSE_INPUT_REJECTED'
        return dict(schema=SCHEMA, state='HOLD', reasons=[reason], requests=[],
            model_states={cell:dict(state='HOLD', reason=reason) for cell in CELLS},
            independent_pre_cutoff_receipt_verified=False, provider_model_training_permission_confirmed=False,
            source_requests=0, production_promoted=False)
