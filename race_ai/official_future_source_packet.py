"""Pure fresh-browser packing; no network, keys, model fit or external receipt.

The caller authenticates the baseline artifact and supplies its availability
boundary. Returned requests are converted once at the supplied real as_of;
later orchestration must preserve them instead of assigning a newer clock.
"""
import base64
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import re
from urllib.parse import urlsplit

from .actions_contract import digest, stamp
from . import manual_official_capture as capture
from .permissioned_source_delivery import read_json_bytes
from scripts.all_existing_model_source_packet_freeze import case_inputs, CELLS

PLAN = 'RACE_AI_OFFICIAL_FUTURE_BROWSER_PLAN_V1'
CAPTURE = 'RACE_AI_OFFICIAL_FUTURE_BROWSER_CAPTURE_V1'
INTENT = 'CAPTURE_FRESH_NATIVE_FUTURE_CARDS'
SCHEMA = 'RACE_AI_OFFICIAL_FUTURE_PACKET_BUILD_V1'
LIMIT = 24*1024*1024


def _need(ok, reason):
    if not ok:
        raise ValueError('FUTURE_SOURCE_PACKET_'+reason)


def _clock(value):
    if type(value) is str:
        value = stamp(value)
    _need(type(value) is datetime and value.utcoffset() is not None, 'AWARE_CLOCK')
    return value


def _file(files, name, limit):
    _need(type(name) is str and re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*', name), 'FILE_NAME')
    raw = files.get(name)
    _need(type(raw) is bytes and 0 < len(raw) <= limit, 'ORIGINAL_FILE_REQUIRED')
    return raw


def _no_dynamic_replay(value):
    if type(value) is list:
        for child in value:
            _no_dynamic_replay(child)
    elif type(value) is dict:
        event = value.get('event', '')
        _need(type(event) is str, 'LEDGER_EVENT')
        _need('REPLAY' not in event or event == 'STATIC_CACHE_REPLAY', 'DYNAMIC_REPLAY_FORBIDDEN')
        forbidden = ('replayed_existing_public_document', 'initial_document_replayed', 'served_from_prior_capture_at',
            'served_from_identical_ui_request_at', 'browser_cache_replay', 'reused_original_source_directory', 'dynamic_cache')
        _need(not any(value.get(key) for key in forbidden), 'DYNAMIC_REPLAY_FORBIDDEN')
        for child in value.values():
            _no_dynamic_replay(child)


def _original_rows(index, files, available, now, expires=None):
    started, completed = _clock(index['started_at']), _clock(index['completed_at'])
    _need(available <= started <= completed == now and completed-started <= timedelta(seconds=85), 'CAPTURE_CLOCK')
    rows = index['responses']; ledger = index['ledger']
    _need(type(rows) is list and type(ledger) is list and len(ledger) <= 2048 and
          type(index['actual_request_count']) is int and 0 < len(rows) == index['actual_request_count'] <= index['maximum_requests'] <= 32 and
          index['minimum_spacing_ms'] == 825 and index['maximum_elapsed_ms'] == 85000 and index['request_timeout_ms'] == 12000, 'CAPTURE_BOUNDS')
    numbered = [row for row in ledger if 'sequence' in row]
    by_sequence = {row['sequence']: row for row in rows}
    _need(len(by_sequence) == len(rows) and [row['sequence'] for row in numbered] == list(range(1, len(rows)+1)) and
          all(by_sequence.get(row['sequence']) == row for row in numbered), 'ORIGINAL_LEDGER_JOIN')
    originals = {}; previous = None
    for row in numbered:
        fetched, body_at = _clock(row['request_started_at']), _clock(row['body_captured_at'])
        _need(expires is None or fetched < expires, 'SOURCE_AUTHORIZATION_EXPIRED')
        _need(started <= fetched <= _clock(row.get('headers_received_at', row['response_received_at'])) <=
              _clock(row['response_received_at']) == body_at <= completed and body_at-fetched <= timedelta(seconds=12), 'SOURCE_CLOCK')
        _need(previous is None or fetched-previous >= timedelta(milliseconds=825), 'REQUEST_SPACING')
        previous = fetched
        raw = _file(files, row['body_file'], capture.MAX_BYTES)
        meta = read_json_bytes(_file(files, row['metadata_file'], 65536))
        sport, _ = capture._url(row['url'])
        capture.validate_source_pair(row['url'], capture.official_rights_ref(sport))
        _need(row['status'] == meta['status'] == 200 and row['byte_count'] == meta['byte_count'] == len(raw) and
              row['source_sha256'] == meta['source_sha256'] == sha256(raw).hexdigest(), 'ORIGINAL_RESPONSE_BYTES')
        _need(meta['source_url'] == meta['final_url'] == row['url'] and
              meta['method'] == meta['http_method'] == row['method'] and meta['resource_type'] == row['resource_type'] and
              meta['fetched_at'] == row['request_started_at'] and meta['response_received_at'] == row['body_captured_at'], 'ORIGINAL_HTTP_JOIN')
        headers = meta['headers']
        mime = [v for k, v in headers.items() if k.lower() == 'content-type']
        _need(len(mime) == 1 and mime[0] == row['content_type'], 'ORIGINAL_MIME')
        request = None
        if row['method'] == 'POST':
            request = _file(files, row['request_body_file'], 16384)
            _need(row['request_body_sha256'] == meta['request_body_sha256'] == sha256(request).hexdigest() and
                  meta['request_body_file'] == row['request_body_file'] and
                  meta['request_content_type'] == row['request_content_type'], 'ORIGINAL_REQUEST_BYTES')
        else:
            _need(row['method'] == 'GET' and not any(key in row or key in meta for key in
                ('request_body_file', 'request_body_sha256', 'request_content_type')), 'READ_ONLY_METHOD')
        originals[row['sequence']] = (row, raw, request)
    return originals


def _static_replays(plan, index, originals, files):
    prior = plan.get('static_cache', [])
    _need(type(prior) is list and len(prior) <= 128, 'STATIC_BOUND')
    cache = [(item, index['started_at']) for item in prior]
    cache.extend((dict(raw_base64=base64.b64encode(raw).decode('ascii'),
        metadata=read_json_bytes(_file(files, entry['metadata_file'], 65536))), index['completed_at'])
        for entry, raw, _ in originals.values() if entry['resource_type'] in ('script', 'stylesheet'))
    used = 0
    for item, available_by in cache:
        meta = item['metadata']; raw = base64.b64decode(item['raw_base64'], validate=True)
        source = urlsplit(meta['source_url']); kind = meta['resource_type']
        capture._url(meta['source_url'])
        mime = [v for k, v in meta['headers'].items() if k.lower() == 'content-type']
        _need(kind in ('script', 'stylesheet') and meta['http_method'] == 'GET' and meta['status'] == 200 and
              meta['source_url'] == meta['final_url'] and source.path.lower().endswith('.js' if kind == 'script' else '.css') and
              re.search(r'analytics|tracker|banner', source.path, re.I) is None and len(mime) == 1 and
              re.match(r'^(?:application|text)/(?:javascript|x-javascript|ecmascript)(?:;|$)' if kind == 'script' else r'^text/css(?:;|$)', mime[0], re.I), 'STATIC_ONLY')
        _need(0 < len(raw) <= capture.MAX_BYTES and meta['byte_count'] == len(raw) and
              meta['source_sha256'] == sha256(raw).hexdigest() and
              _clock(meta['fetched_at']) <= _clock(meta['response_received_at']) <= _clock(available_by), 'STATIC_ORIGINAL_JOIN')
        used += len(raw)
        _need(used <= 16*1024*1024, 'STATIC_BOUND')
    for event in index['ledger']:
        if event.get('event') != 'STATIC_CACHE_REPLAY':
            continue
        matches = [item for item, _ in cache if item['metadata']['source_url'] == event.get('url') and
                   item['metadata']['response_received_at'] == event['original_captured_at']]
        _need(len(matches) == 1, 'STATIC_ORIGINAL_REQUIRED')
        item = matches[0]; meta = item['metadata']; raw = base64.b64decode(item['raw_base64'], validate=True)
        _need(_clock(index['started_at']) <= _clock(event['at']) <= _clock(index['completed_at']) and
              _clock(meta['response_received_at']) <= _clock(event['at']), 'STATIC_REPLAY_CLOCK')
        _need(meta['resource_type'] in ('script', 'stylesheet') and meta['http_method'] == event['method'] == 'GET' and
              event['resource_type'] == meta['resource_type'] and meta['source_url'] == meta['final_url'] and meta['status'] == 200 and
              meta['source_sha256'] == event['source_sha256'] == sha256(raw).hexdigest() and meta['byte_count'] == len(raw) and
              meta['response_received_at'] == event['original_captured_at'], 'STATIC_ORIGINAL_JOIN')


def _browser_source_projection(entries, original_ledger, originals, selected):
    """Bind every case entry, then expose only its selected HTTP originals.

    The adapters select by URL/hash. An otherwise real, unselected response
    with identical bytes must not override the explicitly chosen source role.
    """
    _need(type(entries) is list and 0 < len(entries) <= len(original_ledger), 'BROWSER_LEDGER_BOUND')
    cursor = 0; seen = set(); projection = []
    for entry in entries:
        _need(type(entry) is dict, 'BROWSER_LEDGER_ENTRY')
        fingerprint = digest(entry)
        if 'sequence' in entry:
            sequence = entry['sequence']
            _need(type(sequence) is int and sequence in originals and sequence not in seen and
                  fingerprint == digest(originals[sequence][0]), 'BROWSER_ORIGINAL_RESPONSE_JOIN')
            seen.add(sequence)
        while cursor < len(original_ledger) and original_ledger[cursor][0] != fingerprint:
            cursor += 1
        _need(cursor < len(original_ledger), 'BROWSER_ORIGINAL_LEDGER_PROJECTION')
        original = original_ledger[cursor][1]; cursor += 1
        if 'sequence' not in original or original['sequence'] in selected:
            projection.append(deepcopy(original))
    _need(selected <= seen, 'BROWSER_SELECTED_SOURCE_CLOSURE')
    return projection


def _pack_case(row, item, originals, original_ledger, files, available, now):
    sport = item['sport']; browser = deepcopy(row['browser_metadata']); dom = row['rendered_dom']
    _need(row['sport'] == sport and row['race_id'] == item['race_id'] and row['state'] == 'CAPTURED', 'EXACT_CAPTURED_CASE')
    _need(browser['source_url'] == item['ui_entry_url'] and browser['rendered_dom'] == dom and
          available <= _clock(browser['started_at']) <= _clock(dom['captured_at']) == _clock(browser['captured_at']) <= now, 'ORIGINAL_DOM_CLOCK')
    dom_raw = _file(files, dom['file'], capture.MAX_BYTES)
    _need(dom['byte_count'] == len(dom_raw) and dom['source_sha256'] == sha256(dom_raw).hexdigest(), 'ORIGINAL_DOM_BYTES')
    roles = row['responses']; expected = {'identity', 'program'} if sport == 'autorace' else {'racelist', 'racelive'}
    _need(type(roles) is list and len(roles) == 2 and {r['role'] for r in roles} == expected and
          len({r['sequence'] for r in roles}) == 2, 'EXACT_SOURCE_ROLES')
    selected = {r['role']: originals[r['sequence']] for r in roles}
    browser['ledger'] = _browser_source_projection(browser['ledger'], original_ledger, originals,
                                                  {r['sequence'] for r in roles})
    _need(all(source in browser['ledger'] and _clock(source['body_captured_at']) <= _clock(dom['captured_at'])
              for source, _, _ in selected.values()), 'DOM_SOURCE_CLOSURE')
    encode = lambda raw: base64.b64encode(raw).decode('ascii')
    if sport == 'autorace':
        program, identity = selected['program'], selected['identity']
        _need(all(request is not None for _, _, request in selected.values()), 'EXACT_REQUEST_REQUIRED')
        case = dict(sport=sport, program_raw_b64=encode(program[1]), race_info_raw_b64=encode(identity[1]),
            rendered_dom_b64=encode(dom_raw), capture_metadata=browser,
            request_bodies_b64={entry['request_body_sha256']: encode(request) for entry, _, request in selected.values()})
    else:
        case = dict(sport=sport, racelist_raw_b64=encode(selected['racelist'][1]), racelist_metadata=deepcopy(browser),
            racelive_raw_b64=encode(selected['racelive'][1]), racelive_metadata=deepcopy(browser),
            rendered_dom_b64=encode(dom_raw), browser_metadata=browser)
    converted = case_inputs(case, now=now)
    _need(converted.get('state') == 'READY' and {r['cell_key'] for r in converted['requests']} == CELLS[sport], 'NATIVE_CONTRACT_HOLD')
    _need(converted['race_id'] == item['race_id'] and _clock(converted['cutoff_at']) == _clock(item['cutoff_at']) and
          now+timedelta(minutes=10) < _clock(converted['cutoff_at']), 'NATIVE_CASE_OR_CUTOFF')
    return case, converted


def _build(plan, index, files, terms, as_of):
    now = _clock(as_of); day = now.astimezone(capture.JST).date().isoformat()
    _need(type(plan) is dict and set(plan) <= {'schema','intent','available_after','cases','request_budget','static_cache','not_after'} and
          plan['schema'] == PLAN and plan['intent'] == INTENT and type(plan['cases']) is list and 1 <= len(plan['cases']) <= 24, 'PLAN_SCHEMA')
    available = _clock(plan['available_after'])
    expires = _clock(plan['not_after']) if 'not_after' in plan else None
    budget = plan.get('request_budget', 32)
    _need(type(budget) is int and 1 <= budget <= 32 and index['maximum_requests'] == budget, 'PLAN_REQUEST_BUDGET')
    _need(index['schema'] == CAPTURE and index['intent'] == INTENT and index['available_after'] == plan['available_after'] and
          index['normal_ui_only'] is True and index['manual_api_requests'] == 0 and index['stop_reason'] == 'FINISHED' and
          index['stopped_host'] is False and index['formal_learning_or_pdca_claim'] is False and
          index['native_contracts_verified'] is False and index['independent_pre_cutoff_receipt_verified'] is False, 'CAPTURE_INTENT')
    _need(type(files) is dict and len(files) <= 256 and sum(len(raw) for raw in files.values()) <= LIMIT, 'FILES_BOUND')
    _no_dynamic_replay(plan); _no_dynamic_replay(index)
    originals = _original_rows(index, files, available, now, expires)
    _static_replays(plan, index, originals, files)
    original_ledger = [(digest(entry), entry) for entry in index['ledger']]
    rows = index['cases']; _need(type(rows) is list and len(rows) == len(plan['cases']), 'EXACT_CASE_COUNT')
    cases = []; requests = []; bindings = []; seen = set(); refs = set()
    for item in plan['cases']:
        sport = item['sport']; race = item['race_id']
        _need(sport in CELLS and item['expected_date'] == day and type(item['race_no']) is int and 1 <= item['race_no'] <= 12 and
              race == f"{sport}:{day}:{item['venue']}:{item['race_no']}" and race not in seen, 'PLAN_CASE_IDENTITY')
        seen.add(race)
        matches = [row for row in rows if row['race_id'] == race]
        _need(len(matches) == 1, 'EXACT_CAPTURED_CASE')
        case, converted = _pack_case(matches[0], item, originals, original_ledger, files, available, now)
        cases.append(case); requests.extend(converted['requests']); refs.update(pair[0] for pair in converted['source_refs'])
        bindings.append(dict(sport=sport, race_id=race, case_sha256=digest(case),
            native_input_count=len(converted['requests']), native_input_sha256=[digest(r['native_payload']) for r in converted['requests']]))
    all_urls = [url for record in terms['terms'] for url in record['source_urls']]
    capture._terms(terms, all_urls, day, now); _need(refs <= set(all_urls), 'TERMS_SOURCE_CLOSURE')
    packet = dict(schema='RACE_AI_OFFICIAL_SOURCE_PACKET_V1', execution_day=day, cases=cases, terms_manifest=deepcopy(terms))
    _need(len(capture._wire(packet)) <= LIMIT, 'PACKET_BOUND')
    return dict(schema=SCHEMA, state='READY_INPUTS_ONLY', packet=packet, requests=requests, fixed_as_of=now.isoformat(),
        case_bindings=bindings, native_contracts_verified=True, baseline_authenticated=False,
        independent_pre_cutoff_receipt_verified=False, forecast_created=False, source_requests=0)


def build_source_packet(plan, index, files, *, terms_manifest, as_of):
    """Pack unchanged original bytes and validate native inputs at fixed as_of.

    files is an in-memory map of the capture's original relative names to bytes.
    as_of must equal the capture index's original completed_at; replaying this
    builder cannot move the native observation clock to a later conversion.
    READY proves local input contracts only. The Actions caller must authenticate
    real baselines, seal these requests, then verify independent saved receipts.
    """
    try:
        return _build(plan, index, files, terms_manifest, as_of)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        reason = str(exc)
        if re.fullmatch(r'FUTURE_SOURCE_PACKET_[A-Z_]{1,100}', reason) is None:
            reason = 'FUTURE_SOURCE_PACKET_INPUT_REJECTED'
        return dict(schema=SCHEMA, state='HOLD', reasons=[reason], packet=None, requests=[],
            native_contracts_verified=False, baseline_authenticated=False,
            independent_pre_cutoff_receipt_verified=False, forecast_created=False, source_requests=0)
