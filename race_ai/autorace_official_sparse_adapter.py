"""Pure normal-browser AUTO source conversion into existing native inputs.

Prior normal top-three finish fractions are explicitly observed proxies in
the existing optional 3/10-race fields. No latent rating, past field size,
unobserved trial, new coefficient, provider request or save receipt is made.
The caller authenticates and privately preserves the original capture.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
from unicodedata import normalize
from urllib.parse import urlsplit

from .actions_contract import digest
from . import comprehensive_four_sport_models as native
from .autorace_ab_pdca import PHASES
from .autorace_personal_baseline import SOURCE_SCHEMA, MODEL_ID as PERSONAL, predict_personal
from .four_sport_learning import LEARNED_ID, forecast as ranker_forecast
from .four_sport_model_suite import ALL_MODELS
from .manual_official_capture import _json, validate_source_pair


JST = timezone(timedelta(hours=9))
MAX_BYTES = 2*1024*1024
VENUES = frozenset(('kawaguchi', 'isesaki', 'hamamatsu', 'iizuka', 'sanyou'))
CELLS = tuple('autorace/'+mid for mid in (PERSONAL, *ALL_MODELS, LEARNED_ID))
SCHEMA = 'RACE_AI_AUTORACE_OFFICIAL_NATIVE_INPUTS_V1'


def _need(ok, reason):
    if not ok:
        raise ValueError('AUTO_SPARSE_'+reason)


def _clock(value):
    try:
        instant = value if type(value) is datetime else datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(instant.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
        return instant
    except (TypeError, ValueError, AttributeError):
        raise ValueError('AUTO_SPARSE_AWARE_CLOCK_REQUIRED') from None


def _day(value):
    _need(type(value) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), 'DATE_REQUIRED')
    return date.fromisoformat(value)


def _integer(value, low, high):
    _need(type(value) is int and low <= value <= high, 'OBSERVED_INTEGER_REQUIRED')
    return value


def _text(value):
    return re.sub(r'\s+', '', normalize('NFKC', value))


class _Document(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.parts, self.tables, self.table, self.skipped = [], [], None, 0
        self.feed(raw.decode('utf-8', 'strict'))

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skipped += 1
        if not self.skipped and tag == 'table' and 'race-infoTable' in dict(attrs).get('class', '').split():
            _need(self.table is None, 'NESTED_RACE_TABLE')
            self.table = []

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.skipped = max(0, self.skipped-1)
        if tag == 'table' and self.table is not None:
            self.tables.append(_text(' '.join(self.table))); self.table = None

    def handle_data(self, value):
        if not self.skipped:
            self.parts.append(value)
            if self.table is not None:
                self.table.append(value)


def _json_body(raw):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'BOUNDED_SOURCE_REQUIRED')
    value = _json(raw)
    _need(type(value) is dict and set(value) == {'result', 'errors', 'body'} and
          value['result'] == 'Success' and value['errors'] == [] and type(value['body']) is dict,
          'SUCCESSFUL_SOURCE_BODY_REQUIRED')
    return value['body']


def _proof(entry, rights):
    return dict(source_ref=entry['url'], source_rights_ref=rights,
                source_sha256=entry['source_sha256'], captured_at=entry['body_captured_at'],
                published_at=None, evidence_basis='HTTP_BODY_SHA256')


def _sources(program_raw, race_raw, dom_raw, metadata, now, rights, request_bodies):
    _need(type(metadata) is dict and metadata.get('schema') == 'RACE_AI_PRIVATE_OFFICIAL_BROWSER_PROBE_V1' and
          metadata.get('ui_capture_kind') == 'NORMAL_BROWSER_UI' and metadata.get('stopped_host') is False,
          'NORMAL_UI_CAPTURE_REQUIRED')
    root = metadata.get('source_url'); validate_source_pair(root, rights)
    parsed = urlsplit(root)
    _need(parsed.hostname in ('autorace.jp', 'www.autorace.jp') and not parsed.query and
          parsed.path.startswith('/race_info/Live/') and
          parsed.path.removeprefix('/race_info/Live/') in VENUES, 'OFFICIAL_LIVE_SOURCE_REQUIRED')
    started, completed = _clock(metadata.get('started_at')), _clock(metadata.get('captured_at'))
    _need(started <= completed <= now, 'CAPTURE_COMPLETION_CLOCK')
    ledger = metadata.get('ledger')
    _need(type(ledger) is list and 1 <= len(ledger) <= 256 and all(type(e) is dict for e in ledger),
          'BOUNDED_NETWORK_LEDGER_REQUIRED')
    _need(not any(e.get('status') in (401, 403, 429) for e in ledger), 'HOST_DENIAL_CAPTURE_REJECTED')
    _need(type(request_bodies) is dict and len(request_bodies) <= 32, 'EXACT_REQUEST_BYTES_REQUIRED')
    documents, proofs, requests, request_hashes = [], [], [], {}
    for suffix, raw in (('Program', program_raw), ('OtherRaceInfo', race_raw)):
        body = _json_body(raw)
        url = parsed._replace(path='/race_info/'+suffix).geturl()
        members = [e for e in ledger if e.get('url') == url and e.get('method') == 'POST' and
                   e.get('source_sha256') == sha256(raw).hexdigest()]
        _need(members, 'RESPONSE_NETWORK_BINDING')
        entry = max(members, key=lambda e: _clock(e.get('body_captured_at')))
        _need(entry.get('status') == 200 and entry.get('resource_type') in ('xhr', 'fetch') and
              type(entry.get('byte_count')) is int and entry['byte_count'] == len(raw) and
              type(entry.get('content_type')) is str and
              entry['content_type'].lower().split(';', 1)[0] == 'application/json' and
              type(entry.get('request_content_type')) is str and
              entry['request_content_type'].lower().split(';', 1)[0] == 'application/json', 'RESPONSE_METADATA')
        _need(started <= _clock(entry.get('request_started_at')) <= _clock(entry.get('response_received_at')) <=
              _clock(entry.get('body_captured_at')) <= completed, 'SOURCE_COMPLETION_CLOCK')
        request_sha = entry.get('request_body_sha256'); request_raw = request_bodies.get(request_sha)
        _need(type(request_raw) is bytes and 0 < len(request_raw) <= 16384 and
              sha256(request_raw).hexdigest() == request_sha, 'EXACT_REQUEST_BYTES_REQUIRED')
        request = _json(request_raw)
        _need(type(request) is dict and set(request) == {'placeCode', 'raceDate', 'raceNo'}, 'NORMAL_UI_REQUEST_SCHEMA')
        _integer(request['placeCode'], 1, 20); _integer(request['raceNo'], 1, 12); _day(request['raceDate'])
        documents.append(body); proofs.append(_proof(entry, rights)); requests.append(request)
        request_hashes[suffix] = request_sha
    _need(requests[0] == requests[1], 'REQUEST_CASE_MISMATCH')
    expected_final = root+'/Program/'+requests[0]['raceDate']+'_'+str(requests[0]['raceNo'])+'/program'
    _need(metadata.get('final_url') in (root, expected_final), 'NORMAL_UI_FINAL_CASE_URL_MISMATCH')
    dom = metadata.get('rendered_dom')
    _need(type(dom_raw) is bytes and 0 < len(dom_raw) <= MAX_BYTES and type(dom) is dict and
          dom.get('byte_count') == len(dom_raw) and dom.get('source_sha256') == sha256(dom_raw).hexdigest(),
          'RENDERED_DOM_BYTES_MISMATCH')
    proofs.append(dict(source_ref=root, source_rights_ref=rights, source_sha256=dom['source_sha256'],
        captured_at=metadata['captured_at'], published_at=None, evidence_basis='NORMAL_BROWSER_RENDERED_DOM_SHA256'))
    return documents[0], documents[1], _Document(dom_raw), proofs, requests[0], parsed.path.split('/')[-1], request_hashes


def _race(info, document, request, venue, now):
    _integer(info.get('placeCode'), 1, 20); _integer(info.get('raceNo'), 1, 12)
    _need(info.get('placeKey') == venue and info.get('placeCode') == request['placeCode'] and
          info.get('raceNo') == request['raceNo'], 'RACE_BODY_REQUEST_MISMATCH')
    first, last = _day(info.get('periodStartDate')), _day(info.get('periodEndDate'))
    number = _integer(info.get('paragraphday'), 1, 14)
    event = first+timedelta(days=number-1)
    _need(first <= event <= last and event.isoformat() == request['raceDate'] and
          event == now.astimezone(JST).date(), 'RACE_DAY_BINDING')
    def when(name):
        value = info.get(name)
        _need(type(value) is str and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value), 'ACTUAL_SALES_AND_START_REQUIRED')
        return datetime.combine(event, datetime.strptime(value, '%H:%M').time(), JST)
    cutoff, start = when('telvoteTime'), when('raceStartTime')
    _need(now+timedelta(minutes=2) < cutoff < start, 'PRE_CUTOFF_MARGIN_REQUIRED')
    metres = _integer(info.get('distance'), 100, 10000)
    text = _text(' '.join(document.parts))
    _need(type(info.get('placeName')) is str and _text(info['placeName']) in text and
          f'{event.year}年' in text and f'第{number}日目' in text and
          '投票締切'+info['telvoteTime'] in text and '発走予定'+info['raceStartTime'] in text,
          'RENDERED_RACE_CLOCK_OR_VENUE_MISMATCH')
    matching = [t for t in document.tables if re.search(r'(?<!\d)'+f'{event.month}月{event.day}日', t) and
                re.search(r'(?<!\d)'+str(request['raceNo'])+r'R', t) and
                re.search(r'(?<!\d)'+str(metres)+'m', t) and '{{' not in t]
    _need(len(matching) == 1, 'RENDERED_RACE_DAY_NUMBER_MISMATCH')
    return dict(race_id=f'autorace:{event.isoformat()}:{venue}:{request["raceNo"]}', sport='autorace',
        venue=venue, event_date_jst=event.isoformat(), sales_cutoff_at=cutoff.isoformat(), as_of=now.isoformat(),
        distance_m=metres, surface='track', race_kind='OFFICIAL_PROGRAM_ONLY', race_revision=1), text


def _window(rows, limit, event):
    _need(type(rows) is list and len(rows) <= limit, 'BOUNDED_PRIOR_HISTORY_REQUIRED')
    facts, normal, seen, previous = [], [], set(), None
    for row in rows:
        _need(type(row) is dict, 'PRIOR_HISTORY_SCHEMA')
        day = _day(row.get('raceDate'))
        _need(day < event and (previous is None or day <= previous), 'STRICT_PRIOR_HISTORY_DATE_REQUIRED')
        previous = day
        race_no = _integer(row.get('raceNo'), 1, 12)
        _need(row.get('placeKey') in VENUES and type(row.get('placeCode')) is int, 'PRIOR_RACE_IDENTITY_REQUIRED')
        identity = (day.isoformat(), row['placeKey'], race_no)
        _need(identity not in seen, 'DUPLICATE_PRIOR_RACE'); seen.add(identity)
        order = row.get('order')
        finish = int(order) if type(order) is int or type(order) is str and re.fullmatch(r'[1-8]', order) else None
        ordinary = (finish is not None and 1 <= finish <= 8 and
                    row.get('accidentName') in (None, '') and row.get('materializedName') in (None, ''))
        if ordinary:normal.append(finish)
        facts.append(dict(event_date_jst=day.isoformat(), venue=row['placeKey'], race_no=race_no,
                          finish_position=finish if ordinary else None, normal=ordinary))
    return dict(source_rows=len(rows), normal_rows=len(normal), excluded_rows=len(rows)-len(normal),
        top3_events=sum(order <= 3 for order in normal), facts=facts,
        basis='OBSERVED_PRIOR_NORMAL_TOP3_FINISH_FRACTION_PROXY'), normal


def _convert(program_raw, race_raw, dom_raw, metadata, *, now, source_rights_ref, request_bodies, baseline_ranker):
    now = _clock(now)
    program, info, document, evidence, request, venue, request_hashes = _sources(
        program_raw, race_raw, dom_raw, metadata, now, source_rights_ref, request_bodies)
    race, text = _race(info, document, request, venue, now)
    scope = metadata.get('scope')
    _need(scope in ('SYNTHETIC_ONLY', 'OWNER_PERSONAL_OFFICIAL_SOURCE_PROBE', 'OPERATOR_SUPPLIED_RESEARCH'), 'CAPTURE_SCOPE')
    scope = native.SYNTHETIC if scope == native.SYNTHETIC else native.RESEARCH
    players = program.get('playerList')
    _need(type(players) is list and 3 <= len(players) <= 8, 'CURRENT_ROSTER_REQUIRED')
    ids, cars, names = set(), set(), set()
    participants, drivers, lineage = [], [], []
    personal_ok, shared_ok, trial_present = True, True, 0
    allowed = set(native.COMMON_REQUIRED+native.SPORT_REQUIRED['autorace']+native.SPORT_OPTIONAL['autorace'])
    for player in players:
        _need(type(player) is dict and player.get('retireFlag') in (0, '0', None) and
              player.get('absent') in (None, '', 0, '0'), 'UNCONFIRMED_CURRENT_ROSTER')
        car = _integer(player.get('carNo'), 1, 8)
        code = player.get('playerCode')
        _need(type(code) in (int, str) and type(code) is not bool and re.fullmatch(r'[0-9]{2,10}', str(code)) and
              int(code) > 0, 'STABLE_REGISTERED_DRIVER_ID_REQUIRED')
        code = str(code); name = player.get('playerName')
        _need(type(name) is str and 0 < len(name) <= 100 and _text(name) and _text(name) in text and
              car not in cars and code not in ids and _text(name) not in names, 'RENDERED_ROSTER_IDENTITY_MISMATCH')
        cars.add(car); ids.add(code); names.add(_text(name))
        handicap = _integer(player.get('handicap'), 0, 200)
        _need(handicap % 10 == 0, 'OBSERVED_HANDICAP_REQUIRED')
        trial_present += player.get('trialRunTime') not in (None, '')
        windows, normal_windows, features = {}, {}, {}
        for length in (3, 10):
            group = program.get(f'latest{length}List')
            _need(type(group) is dict and code in group, 'PARTICIPANT_BOUND_HISTORY_REQUIRED')
            window, normal = _window(group[code], length, _day(race['event_date_jst']))
            windows[str(length)] = window; normal_windows[length] = normal
            if window['source_rows'] == length and normal:
                features[f'recent_form_{length}race'] = dict(
                    value=window['top3_events']/len(normal), sample_n=len(normal),
                    transform_id=f'official-prior-normal-top3-finish-fraction-last{length}-v1',
                    **{k:v for k,v in evidence[0].items() if k != 'evidence_basis'})
        _need(windows['3']['facts'] == windows['10']['facts'][:len(windows['3']['facts'])], 'PRIOR_WINDOW_PREFIX_MISMATCH')
        personal_ok &= 3 <= len(normal_windows[10]) <= 10
        shared_ok &= bool(features)
        drivers.append(dict(car_no=car, handicap_m=handicap, recent_finishes=normal_windows[10],
                            trial_seconds=None, trial_observed_at=None))
        participants.append(dict(number=car, identity=code, draw=car, style='unknown', group_id=None,
            features=features, missing={key:'NOT_AVAILABLE' for key in sorted(allowed-set(features))}))
        lineage.append(dict(car_no=car, player_id=code, windows=windows))
    for length in (3, 10):
        _need(set(program[f'latest{length}List']) == ids, 'HISTORY_ROSTER_BINDING')
    audit = dict(schema='RACE_AI_AUTORACE_OFFICIAL_SOURCE_LINEAGE_V1', race_id=race['race_id'],
        event_date_jst=race['event_date_jst'], as_of=now.isoformat(), source_completion_at=metadata['captured_at'],
        sales_cutoff_at=race['sales_cutoff_at'], race_start_at=info['raceStartTime'],
        exact_request_body_sha256=request_hashes,
        source_evidence=deepcopy(evidence), participants=lineage,
        draw_semantics='SOURCE_CURRENT_CAR_NUMBER_NO_RENUMBERING',
        race_revision_semantics='LOCAL_CAPTURE_VERSION_ONE_NOT_OFFICIAL_REVISION',
        provider_model_training_permission_confirmed=False)
    states = {cell:dict(state='HOLD', reason='INSUFFICIENT_OBSERVED_NORMAL_HISTORY') for cell in CELLS}
    requests = []
    def payload(snapshot, **extra):
        return dict(snapshot=snapshot, scope=scope, source_evidence=deepcopy(evidence),
                    adapter_lineage=deepcopy(audit), source_audit_sha256=digest(audit), **extra)
    if personal_ok and not trial_present:
        snapshot = dict(schema=SOURCE_SCHEMA, entry_kind='USER_OBSERVED_MANUAL', race=dict(
            race_id=race['race_id'], venue=race['venue'], race_no=request['raceNo'], event_date_jst=race['event_date_jst'],
            sales_cutoff_at=race['sales_cutoff_at'], as_of_at=now.isoformat(), phase=PHASES[0],
            source_url=evidence[0]['source_ref'], source_captured_at=evidence[0]['captured_at']),
            drivers=sorted(drivers, key=lambda d:d['car_no']))
        predict_personal(snapshot, generated_at=now.isoformat())
        personal = payload(snapshot)
        personal['registered_roster'] = dict(schema='RACE_AI_REGISTERED_NATIVE_ROSTER_V1', sport='autorace',
            race_id=race['race_id'], as_of=now.isoformat(), roster={str(p['number']):p['identity'] for p in participants},
            native_input_sha256=digest(snapshot), **{k:v for k,v in evidence[0].items() if k not in ('published_at', 'evidence_basis')})
        requests.append(dict(cell_key='autorace/'+PERSONAL, native_payload=personal))
        states['autorace/'+PERSONAL] = dict(state='READY', reason='OBSERVED_PRE_TRIAL_NATIVE_INPUT')
    if shared_ok:
        snapshot = dict(schema=native.SCHEMA_SPARSE, scope=scope, race=race,
            participants=sorted(participants, key=lambda p:p['number']), environment={},
            environment_missing={key:'NOT_AVAILABLE' for key in native.ENV_COMMON+native.ENV_SPORT['autorace']})
        native.validate(snapshot, allow_source=lambda ref,right,purpose: purpose == 'analysis' and
                        (ref,right) in {(e['source_ref'],e['source_rights_ref']) for e in evidence})
        for mid in (*ALL_MODELS, LEARNED_ID):
            native_payload = payload(deepcopy(snapshot), stage='P0')
            if mid == LEARNED_ID and baseline_ranker is not None:
                ranker_forecast(snapshot, baseline_ranker, allow_source=lambda *_:True)
                native_payload['learned_model'] = deepcopy(baseline_ranker)
            requests.append(dict(cell_key='autorace/'+mid, native_payload=native_payload))
            states['autorace/'+mid] = dict(state='READY', reason='OBSERVED_SPARSE_NATIVE_INPUT')
    return dict(schema=SCHEMA, state='READY' if requests else 'HOLD', requests=requests, model_states=states,
        phase_states={PHASES[0]:states['autorace/'+PERSONAL], PHASES[1]:dict(state='HOLD', reason=
            'CURRENT_TRIAL_NOT_OBSERVED' if not trial_present else 'POST_TRIAL_NOT_BUILT_BY_PRE_TRIAL_ADAPTER')},
        race_id=race['race_id'], cutoff_at=race['sales_cutoff_at'], source_audit=audit, source_audit_sha256=digest(audit),
        source_refs=sorted({(e['source_ref'],e['source_rights_ref']) for e in evidence}),
        summary=dict(participants=len(players), native_input_requests=len(requests), current_trial_values_present=trial_present,
            ranker_baseline_supplied=baseline_ranker is not None),
        independent_pre_cutoff_receipt_verified=False, provider_model_training_permission_confirmed=False,
        source_requests=0, production_promoted=False)


def build_requests(program_raw, race_info_raw, rendered_dom, capture_metadata, *, now,
                   source_rights_ref, request_bodies, baseline_ranker=None):
    """Return existing native-input requests or HOLD, with no storage or network.

    ``request_bodies`` maps actual normal-UI POST body SHA256 to original bytes.
    A body hash alone cannot establish the requested case. A ranker capsule
    without ``baseline_ranker`` preserves inputs only; it creates no model or
    forecast. The caller owns owner authorization and independent preservation.
    """
    try:
        return _convert(program_raw, race_info_raw, rendered_dom, capture_metadata, now=now,
            source_rights_ref=source_rights_ref, request_bodies=request_bodies, baseline_ranker=baseline_ranker)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError) as exc:
        reason = str(exc) if re.fullmatch(r'AUTO_SPARSE_[A-Z_]{1,100}', str(exc)) else 'AUTO_SPARSE_INPUT_REJECTED'
        return dict(schema=SCHEMA, state='HOLD', reasons=[reason], requests=[],
            model_states={cell:dict(state='HOLD', reason=reason) for cell in CELLS},
            phase_states={phase:dict(state='HOLD', reason=reason) for phase in PHASES},
            independent_pre_cutoff_receipt_verified=False, provider_model_training_permission_confirmed=False,
            source_requests=0, production_promoted=False)
