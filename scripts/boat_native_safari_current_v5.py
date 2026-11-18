"""Bounded ciphertext replay of the unchanged deployed V5 browser reader.

The normal pinned Python F/H reader authenticates the source snapshot. These
transport bindings alone are not an AES or production-delivery proof.
"""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
from contextlib import redirect_stdout, redirect_stderr

_BASE = 'https://raw.githubusercontent.com/haji84/RACE-AI/'
_LATEST = _BASE + 'state/boat-saved-view/latest.json'
_ROUTER = _BASE + 'state/boat-saved-view/views/'
_V5 = 'RACE_AI_SAVED_WEB_HISTORY_V5'
_CATALOG = 'RACE_AI_SAVED_WEB_HISTORY_CATALOG_V1'
_DAY = 'RACE_AI_SAVED_WEB_HISTORY_DAY_V1'


def _need(value, api, reason='CURRENT_V5_REPLAY_INVALID'):
    if not value:
        raise api.SafariHold(reason)


def _hex(value, length=64):
    return type(value) is str and re.fullmatch('[a-f0-9]{' + str(length) + '}', value) is not None


def _json(raw, maximum, api):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, api)
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError('DUPLICATE')
            result[name] = value
        return result
    def nonfinite(value):
        raise ValueError('NONFINITE')
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('NONFINITE')
        return number
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
        parse_constant=nonfinite, parse_float=finite_float)


def _day(value, api):
    _need(type(value) is str and re.fullmatch(r'\d{4}-\d\d-\d\d', value) is not None, api)
    from datetime import date
    _need(date.fromisoformat(value).isoformat() == value, api)
    return value


def _body(raw, view_id, anchor, api):
    value = _json(raw, 12 * 1024 * 1024, api)
    _need(type(value) is dict and set(value) == {'header', 'nonce', 'ciphertext'}, api)
    header = value['header']
    _need(type(header) is dict and header.get('view_id') == view_id
        and header.get('forecast_sha256') == anchor, api)
    schema = header.get('schema')
    fields = {'schema', 'view_id', 'forecast_sha256'}
    if schema == _V5:
        fields |= {'source_content_sha256', 'generation', 'previous_cipher_sha256', 'history_index_sha256'}
        _need(type(header.get('generation')) is int and 1 <= header['generation'] <= 999999, api)
    elif schema == _CATALOG:
        fields.add('history_index_sha256')
    else:
        _need(schema == _DAY, api)
        fields |= {'day', 'part', 'forecast_inventory_sha256'}
        _day(header.get('day'), api)
        _need(type(header.get('part')) is int and 0 <= header['part'] < 64, api)
    _need(set(header) == fields, api)
    for name in fields - {'schema', 'generation', 'day', 'part'}:
        _need(_hex(header[name]), api)
    for name, minimum, maximum in (('nonce', 12, 12), ('ciphertext', 16,
            8 * 1024 * 1024 + 16 if schema == _DAY else 512 * 1024 + 16)):
        encoded = value[name]
        _need(type(encoded) is str and 0 < len(encoded) <= 4 * ((maximum + 2) // 3), api)
        decoded = base64.b64decode(encoded, validate=True)
        _need(minimum <= len(decoded) <= maximum
            and base64.b64encode(decoded).decode('ascii') == encoded, api)
    return header


class CurrentV5Replay:
    __slots__ = ('_snapshot', '_cipher', '_latest', '_items', '_context', '_routes',
                 '_view_id', '_anchor', '_total')

    def __init__(self, snapshot, cipher, latest, items, context, routes, view_id, anchor, total):
        for name, value in (('_snapshot', snapshot), ('_cipher', cipher), ('_latest', latest),
                ('_items', items), ('_context', context), ('_routes', routes),
                ('_view_id', view_id), ('_anchor', anchor), ('_total', total)):
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        raise AttributeError('IMMUTABLE_CURRENT_V5_REPLAY')

    @property
    def snapshot_sha(self):
        return self._snapshot

    @property
    def cipher_sha256(self):
        return self._cipher

    def __repr__(self):
        return 'CurrentV5Replay()'


def build_current_v5_replay(*, snapshot_sha, latest_raw, ciphertexts, context,
        view_id, forecast_sha256, secrets=(), now=None, _api):
    a = _api
    try:
        _need(_hex(snapshot_sha, 40) and _hex(view_id) and _hex(forecast_sha256), a)
        _need(type(ciphertexts) is dict and bool(ciphertexts)
            and type(a.MAX_CURRENT_V5_FILES) is int and 0 < a.MAX_CURRENT_V5_FILES <= 512
            and type(a.MAX_CURRENT_V5_BYTES) is int and 0 < a.MAX_CURRENT_V5_BYTES <= 256 * 1024 * 1024
            and len(ciphertexts) + 1 <= a.MAX_CURRENT_V5_FILES, a)
        _need(type(latest_raw) is bytes and all(type(raw) is bytes for raw in ciphertexts.values()), a)
        total = len(latest_raw) + sum(len(raw) for raw in ciphertexts.values())
        _need(total <= a.MAX_CURRENT_V5_BYTES, a)
        manifest = _json(latest_raw, 4096, a)
        _need(type(manifest) is dict and set(manifest) == {'header', 'cipher_sha256'}
            and _hex(manifest.get('cipher_sha256')), a)
        checked = a.validate_context(deepcopy(context))
        checked = _json(a.wire(checked).encode('utf-8'), 4 * 1024 * 1024, a)
        clock = datetime.now(timezone.utc) if now is None else now
        _need(isinstance(clock, datetime) and clock.utcoffset() is not None, a)
        today = clock.astimezone(timezone(timedelta(hours=9))).date().isoformat()
        _need(_day(checked['day'], a) == checked['current_day'] == today, a)
        current_url = _ROUTER + manifest['cipher_sha256'] + '.json'
        _need(current_url in ciphertexts, a)
        routes = [(_LATEST, '/_acceptance/current-v5/manifest.json')]
        items = []
        for ordinal, (url, raw) in enumerate(ciphertexts.items()):
            _need(type(url) is str and bool(raw), a)
            match = re.fullmatch(re.escape(_BASE) +
                r'(?:state/boat-saved-view|[a-f0-9]{40})/views/([a-f0-9]{64})\.json', url)
            _need(match is not None and hashlib.sha256(raw).hexdigest() == match[1], a)
            if url.startswith(_ROUTER):
                _need(url == current_url, a)
            header = _body(raw, view_id, forecast_sha256, a)
            if url == current_url:
                _need(header == manifest['header'] and header['schema'] == _V5
                    and header['generation'] == checked['generation'], a)
            path = '/_acceptance/current-v5/cipher-' + str(ordinal) + '-' + match[1] + '.json'
            routes.append((url, path))
            items.append((url, raw))
        material = (latest_raw, a.wire(checked).encode('utf-8'), *(raw for _, raw in items))
        for secret in secrets:
            if type(secret) is str and len(secret) >= 8:
                _need(not any(secret.encode('utf-8') in raw for raw in material), a)
        return CurrentV5Replay(snapshot_sha, manifest['cipher_sha256'], latest_raw,
            tuple(items), a.wire(checked).encode('utf-8'), tuple(routes),
            view_id, forecast_sha256, total)
    except a.SafariHold:
        raise
    except Exception:
        raise a.SafariHold('CURRENT_V5_REPLAY_INVALID') from None


def current_v5_replay_route(replay, logical_url, *, _api):
    a = _api
    _need(type(replay) is CurrentV5Replay and type(logical_url) is str, a)
    if logical_url == _LATEST or re.fullmatch(re.escape(_LATEST) + r'\?check=[0-9]{1,20}', logical_url):
        return replay._routes[0][1]
    for url, path in replay._routes[1:]:
        if logical_url == url:
            return path
    raise a.SafariHold('CURRENT_V5_REPLAY_INVALID')


def current_v5_payload(replay, path):
    if type(replay) is not CurrentV5Replay:
        return None
    if path == replay._routes[0][1]:
        return replay._latest, 'manifest'
    items = dict(replay._items)
    for url, route in replay._routes[1:]:
        if path == route:
            return items[url], 'cipher'
    return None


def current_v5_replay_script(replay, *, _api):
    _need(type(replay) is CurrentV5Replay, _api)
    mapping = json.dumps(dict(replay._routes), separators=(',', ':'), ensure_ascii=True)
    script = r'''(()=>{"use strict";
const routes=__ROUTES__,latest="https://raw.githubusercontent.com/haji84/RACE-AI/state/boat-saved-view/latest.json";
const originalFetch=globalThis.fetch.bind(globalThis),origin=location.origin;
const privacy=globalThis.__raceSafariPrivacy||(globalThis.__raceSafariPrivacy={external_blocked:0,csp_blocked:0,page_errors:0,aes_successes:0});
const viewer=/^#saved=[a-f0-9]{64}\.([A-Za-z0-9_-]{43})$/.exec(location.hash||"")?.[1];
function denied(){privacy.external_blocked=(privacy.external_blocked||0)+1;throw new TypeError("blocked");}
function route(text){
 if(typeof text!=="string")return denied();
 if(text===latest||text.startsWith(latest+"?check=")&&/^[0-9]{1,20}$/.test(text.slice(latest.length+7)))return routes[latest];
 if(Object.hasOwn(routes,text))return routes[text];return denied();
}
function allowed(input,options){
 const request=typeof Request!=="undefined"&&input instanceof Request?input:null;
 const raw=typeof input==="string"?input:input instanceof URL?input.href:request?.url;
 if(typeof raw!=="string")return denied();
 const method=String(options?.method??request?.method??"GET").toUpperCase();
 const body=options?.body!==undefined?options.body:request?.body;
 const headers=new Headers(options?.headers??request?.headers);
 const secretText=raw+JSON.stringify([...headers])+String(body??"");
 if(!["GET","HEAD"].includes(method)||body!=null||headers.has("authorization")||headers.has("proxy-authorization")||
    viewer&&secretText.includes(viewer))return denied();
 const url=new URL(raw,location.href);
 if(url.hash||url.username||url.password)return denied();
 return {raw,url,method,headers};
}
function facade(response,logical){
 return new Proxy(response,{get(target,key){
  if(key==="url")return logical;
  if(key==="clone")return ()=>facade(target.clone(),logical);
  const value=Reflect.get(target,key,target);return typeof value==="function"?value.bind(target):value;
 }});
}
globalThis.fetch=async(input,options)=>{
 const checked=allowed(input,options);
 if(checked.url.origin===origin)return originalFetch(input,options);
 const path=route(checked.raw),local=new URL(path,location.href).href;
 const response=await originalFetch(local,{method:checked.method,headers:checked.headers,
   credentials:"omit",cache:"no-store",redirect:"error",referrerPolicy:"no-referrer",
   signal:options?.signal});
 if(response.redirected||response.url&&response.url!==local)return denied();
 return facade(response,checked.raw);
};
const oldOpen=XMLHttpRequest.prototype.open,oldHeader=XMLHttpRequest.prototype.setRequestHeader,oldSend=XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.open=function(method,url,...args){
 const checked=allowed(String(url),{method});if(checked.url.origin!==origin)return denied();
 return oldOpen.call(this,method,url,...args);
};
XMLHttpRequest.prototype.setRequestHeader=function(name,value){
 if(/^(?:proxy-)?authorization$/i.test(String(name))||viewer&&(String(name)+String(value)).includes(viewer))return denied();
 return oldHeader.call(this,name,value);
};
XMLHttpRequest.prototype.send=function(body){if(body!=null)return denied();return oldSend.call(this,body);};
navigator.sendBeacon=()=>{privacy.external_blocked=(privacy.external_blocked||0)+1;return false;};
globalThis.WebSocket=globalThis.EventSource=function(){return denied();};
let saved;
function observed(api){
 if(!api||typeof api.readLive!=="function")return api;
 return Object.freeze({...api,readLive:async(...args)=>{
  const result=await api.readLive(...args),h=result?.header;
  if(h?.schema==="RACE_AI_SAVED_WEB_HISTORY_V5"&&Number.isSafeInteger(h.generation)&&h.generation>0&&
     /^[a-f0-9]{64}$/.test(result.cipherSha||"")&&/^\d{4}-\d\d-\d\d$/.test(result.history?.day||"")){
   const prior=privacy.current_v5?.v5_read_live_successes;
   privacy.current_v5={schema:h.schema,generation:h.generation,cipher_sha256:result.cipherSha,
     history_day:result.history.day,v5_read_live_successes:Number.isSafeInteger(prior)&&prior>0?prior+1:1};
  }
  return result;
 }});
}
const initial=globalThis.SavedViewCrypto;
Object.defineProperty(globalThis,"SavedViewCrypto",{configurable:false,enumerable:true,get:()=>saved,set:value=>{saved=observed(value);}});
if(initial)saved=observed(initial);
})();'''
    return script.replace('__ROUTES__', mapping).encode('utf-8')



_CURRENT_V5_DIAGNOSTIC_BOOLS = (
    'native_p1_verified', 'native_groups_match', 'result_metrics_parsed',
    'probe_fields_match', 'schema_matches', 'generation_matches', 'cipher_matches',
    'history_day_matches', 'selected_day_matches', 'source_day_matches',
    'model_choices_match', 'secret_in_request')
_CURRENT_V5_DIAGNOSTIC_COUNTS = {
    'expected_results': 288, 'observed_results': 288,
    'expected_native_p1_groups': 32768, 'observed_native_p1_groups': 32768,
    'expected_model_choices': 32768, 'observed_model_choices': 32768,
    'v5_read_live_successes': 1000000, 'aes_successes': 1000000,
    'private_view_reads': 1000000, 'encrypted_seed_reads': 1000000,
    'current_v5_manifest_reads': 1000000, 'current_v5_cipher_reads': 1000000,
    'non_read_requests': 1000000, 'outbound_requests_permitted': 1000000}


def current_v5_diagnostic(value):
    """Project only known strict primitive facts; absence is never zero/false."""
    source = value if type(value) is dict else {}
    result = {name: source.get(name) if type(source.get(name)) is bool else None
              for name in _CURRENT_V5_DIAGNOSTIC_BOOLS}
    for name, maximum in _CURRENT_V5_DIAGNOSTIC_COUNTS.items():
        observed = source.get(name)
        result[name] = (observed if type(observed) is int
                        and 0 <= observed <= maximum else None)
    return result


def _current_v5_facts(context, probe, audit, api):
    expected = context if type(context) is dict else {}
    observed = probe if type(probe) is dict else {}
    counters = audit if type(audit) is dict else {}
    choices = (expected.get('model_switch_probe') or {}).get('choices')
    details = observed.get('model_choices')
    fields = {'schema', 'generation', 'cipher_sha256', 'history_day', 'selected_day',
        'source_day', 'v5_read_live_successes', 'aes_successes', 'results',
        'native_p1_groups', 'model_choices'}
    values = dict(expected_results=expected.get('minimum_results'),
        observed_results=observed.get('results'),
        expected_native_p1_groups=expected.get('native_group_count'),
        observed_native_p1_groups=observed.get('native_p1_groups'),
        expected_model_choices=len(choices) if type(choices) is list else None,
        observed_model_choices=len(details) if type(details) is list else None,
        v5_read_live_successes=observed.get('v5_read_live_successes'),
        aes_successes=observed.get('aes_successes'),
        probe_fields_match=set(observed) == fields if type(probe) is dict else None,
        schema_matches=observed['schema'] == _V5 if type(observed.get('schema')) is str else None,
        generation_matches=observed['generation'] == expected.get('generation')
            if type(observed.get('generation')) is int else None)
    for name in ('history_day', 'selected_day', 'source_day'):
        raw = observed.get(name)
        values[name + '_matches'] = (raw == expected.get('day')
            if type(raw) is str and re.fullmatch(r'\d{4}-\d\d-\d\d', raw) is not None else None)
    expected_groups, observed_groups = expected.get('native_group_count'), observed.get('native_p1_groups')
    if type(expected_groups) is int and type(observed_groups) is int:
        values['native_groups_match'] = expected_groups == observed_groups
    if type(details) is list and type(choices) is list:
        matched = len(details) == len(choices) == 2
        if matched:
            try:
                for choice, detail in zip(choices, details):
                    if type(detail) is not dict or set(detail) != {'model_id', 'index', 'tickets'}:
                        matched = False
                        break
                    api.verify_model_choice(choice, detail)
            except Exception:
                matched = False
        values['model_choices_match'] = matched
    for name in ('private_view_reads', 'encrypted_seed_reads', 'current_v5_manifest_reads',
                 'current_v5_cipher_reads', 'non_read_requests', 'outbound_requests_permitted',
                 'secret_in_request'):
        values[name] = counters.get(name)
    return current_v5_diagnostic(values)


def verify_current_v5_evidence(replay, probe, audit, *, _api):
    a = _api
    phase = 'verify_probe'
    diagnostic = current_v5_diagnostic(None)
    try:
        _need(type(replay) is CurrentV5Replay and type(probe) is dict and type(audit) is dict, a,
            'CURRENT_V5_EVIDENCE_INVALID')
        context = _json(replay._context, 4 * 1024 * 1024, a) if type(replay) is CurrentV5Replay else {}
        diagnostic = _current_v5_facts(context, probe, audit, a)
        if type(probe) is dict and _hex(probe.get('cipher_sha256')):
            diagnostic['cipher_matches'] = probe['cipher_sha256'] == replay.cipher_sha256
        fields = {'schema', 'generation', 'cipher_sha256', 'history_day', 'selected_day',
            'source_day', 'v5_read_live_successes', 'aes_successes', 'results',
            'native_p1_groups', 'model_choices'}
        _need(set(probe) == fields and probe['schema'] == _V5
            and type(probe['generation']) is int and probe['generation'] == context['generation']
            and probe['cipher_sha256'] == replay.cipher_sha256
            and all(probe[name] == context['day'] for name in ('history_day', 'selected_day', 'source_day')), a,
            'CURRENT_V5_EVIDENCE_INVALID')
        _need(all(type(probe[name]) is int and probe[name] > 0 for name in
            ('v5_read_live_successes', 'aes_successes', 'results', 'native_p1_groups'))
            and probe['results'] == context['minimum_results']
            and probe['native_p1_groups'] == context['native_group_count'], a, 'CURRENT_V5_EVIDENCE_INVALID')
        phase = 'comparison_originals'
        details = probe['model_choices']
        _need(type(details) is list and len(details) == 2, a, 'CURRENT_V5_EVIDENCE_INVALID')
        for choice, detail in zip(context['model_switch_probe']['choices'], details):
            _need(type(detail) is dict and set(detail) == {'model_id', 'index', 'tickets'}, a,
                'CURRENT_V5_EVIDENCE_INVALID')
            a.verify_model_choice(choice, detail)
        phase = 'private_boundary'
        _need(all(type(audit.get(name)) is int and audit[name] > 0 for name in
            ('encrypted_seed_reads', 'current_v5_manifest_reads', 'current_v5_cipher_reads'))
            and all(type(audit.get(name)) is int and audit[name] == 0 for name in
            ('private_view_reads', 'non_read_requests', 'outbound_requests_permitted'))
            and audit.get('secret_in_request') is False, a, 'CURRENT_V5_EVIDENCE_INVALID')
        return dict(status='ENCRYPTED_CURRENT_V5_SAFARI_VERIFIED',
            transport='LOOPBACK_IMMUTABLE_V5_CIPHERTEXT_REPLAY',
            current_v5_live_continuation_verified=True, current_day_verified=True, browser_aes_verified=True,
            snapshot_sha=replay.snapshot_sha, cipher_sha256=replay.cipher_sha256,
            authenticated_generation=context['generation'], saved_day=context['day'],
            authenticated_results=context['minimum_results'],
            authenticated_native_p1_groups=context['native_group_count'],
            same_current_model_original_comparisons=2, ciphertext_files=len(replay._items),
            ciphertext_bytes=replay._total, plaintext_endpoint_reads=0,
            outbound_browser_requests_permitted=0, real_screenshots_or_traces_exported=0,
            account_login_verified=False, physical_iphone_verified=False)
    except a.CurrentV5EvidenceHold:
        raise
    except a.SafariHold as error:
        if str(error) == 'CURRENT_V5_EVIDENCE_INVALID':
            raise a.CurrentV5EvidenceHold(phase, diagnostic) from None
        raise
    except Exception:
        raise a.CurrentV5EvidenceHold(phase, diagnostic) from None


class _CurrentV5SnapshotReader:
    def __init__(self, git, snapshot_sha, *, _api):
        self._api = _api
        _need(_hex(snapshot_sha, 40), _api)
        self._git = git
        self._snapshot = snapshot_sha
        self._records = {}
        self._remaining = _api.MAX_CURRENT_V5_BYTES
        self._files = _api.MAX_CURRENT_V5_FILES
        _need(type(self._remaining) is int and 0 < self._remaining <= 256 * 1024 * 1024
            and type(self._files) is int and 0 < self._files <= 512, _api)
        self.ref = 'state/boat-saved-view'
        self._saved_history_context = None

    def head(self):
        return self._snapshot

    def _path(self, commit, path):
        _need(_hex(commit, 40) and type(path) is str and
            (commit == self._snapshot and path == 'latest.json' or
             re.fullmatch(r'views/[a-f0-9]{64}\.json', path) is not None), self._api)

    def fetch(self, commit):
        _need(_hex(commit, 40), self._api)
        return self._git.fetch(commit)

    def exists(self, commit, path):
        self._path(commit, path)
        return self._git.exists(commit, path)

    def read(self, commit, path, limit):
        self._path(commit, path)
        key = (commit, path)
        _need(type(limit) is int and limit > 0 and self._remaining > 0
            and (key in self._records or len(self._records) < self._files), self._api)
        maximum = min(limit, self._remaining, 4096 if path == 'latest.json' else 12 * 1024 * 1024)
        raw = self._git.read(commit, path, maximum)
        _need(type(raw) is bytes and 0 < len(raw) <= maximum, self._api)
        if path != 'latest.json':
            _need(hashlib.sha256(raw).hexdigest() == path[6:-5], self._api)
        _need(key not in self._records or self._records[key] == raw, self._api)
        self._remaining -= len(raw)
        self._records[key] = raw
        return raw

    def validate_tree(self, commit):
        _need(commit == self._snapshot, self._api)
        def regular(path):
            raw = self._git._run(['ls-tree', commit, '--', path])
            _need(type(raw) is bytes and len(raw) <= 4096 and re.fullmatch(
                rb'100644 blob [a-f0-9]{40}\t' + re.escape(path.encode()) + rb'\n?', raw) is not None, self._api)
        regular('latest.json')
        manifest = _json(self.read(commit, 'latest.json', 4096), 4096, self._api)
        _need(type(manifest) is dict and set(manifest) == {'header', 'cipher_sha256'}
            and _hex(manifest['cipher_sha256']), self._api)
        regular('views/' + manifest['cipher_sha256'] + '.json')


def read_current_v5_replay(source_root, seed, *, _api):
    """Freeze one head and use only the existing pinned source F/H authentication."""
    a = _api
    try:
        source_root = Path(source_root).resolve()
        actual = a.subprocess.check_output(['git', '-C', str(source_root), 'rev-parse', 'HEAD'],
            timeout=10, stderr=a.subprocess.DEVNULL).decode().strip()
        _need(actual == a.SOURCE_SHA, a)
        a.subprocess.run(['git', '-C', str(source_root), 'diff', '--quiet', 'HEAD', '--',
            'race_ai', 'scripts', 'audit/state/boat-saved-view-input.json'],
            check=True, timeout=10, stdout=a.subprocess.DEVNULL, stderr=a.subprocess.DEVNULL)
        a.sys.path.insert(0, str(source_root))
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            from scripts import boat_saved_site_context as contexts
            from scripts import boat_saved_view_feed as publisher
            from scripts import boat_private_original_vault as vault
            from race_ai import saved_view_history as history
            from race_ai.racer_daily_handoff import _DailyFilteredFetch
            for module, relative in ((contexts, 'scripts/boat_saved_site_context.py'),
                    (publisher, 'scripts/boat_saved_view_feed.py'),
                    (vault, 'scripts/boat_private_original_vault.py'),
                    (history, 'race_ai/saved_view_history.py')):
                _need(Path(module.__file__).resolve() == source_root / relative, a)
            _need(_DailyFilteredFetch.__module__ == 'race_ai.racer_daily_handoff', a)
            root = vault._environment(source_root)
            _need(root == source_root, a)
            config_path = source_root / 'audit/state/boat-saved-view-input.json'
            _need(config_path.is_file() and not config_path.is_symlink()
                and 0 < config_path.stat().st_size <= 8192, a)
            config = publisher._json(config_path.read_bytes(), 8192)
            _need(type(config) is dict and set(config) ==
                {'schema', 'bootstrap', 'bootstrap_sha256', 'catchup_artifact_id', 'catchup_sha256'}
                and config['schema'] == 'RACE_AI_SAVED_VIEW_INPUT_V1', a)
            raw = base64.b64decode(config['bootstrap'], validate=True)
            _need(publisher.sha(raw) == config['bootstrap_sha256'], a)
            publisher.git_auth()
            bootstrap = publisher.F.open_bootstrap(raw)
            class ReadOnlyGit(_DailyFilteredFetch, publisher.F.FeedRepository):
                def commit(self, *args, **kwargs):
                    raise a.SafariHold('CURRENT_V5_REPLAY_INVALID')
                def commit_snapshot(self, *args, **kwargs):
                    raise a.SafariHold('CURRENT_V5_REPLAY_INVALID')
                def push(self, *args, **kwargs):
                    raise a.SafariHold('CURRENT_V5_REPLAY_INVALID')
            git = ReadOnlyGit(root)
            snapshot = git.head()
            _need(_hex(snapshot, 40), a)
            reader = _CurrentV5SnapshotReader(git, snapshot, _api=a)
            now = datetime.now(timezone.utc)
            today = now.astimezone(contexts.JST).date().isoformat()
            parent, ident, generation, current_view = publisher.F.current_view(
                reader, bootstrap, day=today)
            _need(parent == snapshot and current_view.get('event_date_jst') == today
                and all(row.get('event_date_jst') == today for row in current_view['records']), a)
            context = a.validate_context(contexts.build_context(
                bootstrap, current_view, generation, now=now, event_day=today))
            # Existing browser continuation compares retained seed originals.
            # Authenticate each required catalog/day with unchanged H routines,
            # retaining only its encrypted read bytes, never exporting plaintext.
            retained = reader._saved_history_context
            _need(type(retained) is dict and type(retained.get('index')) is dict, a)
            read = publisher.F._history_reader(reader)
            def catalog(locator):
                return history.decrypt_catalog(read(locator), bootstrap['key'],
                    view_id=bootstrap['view_id'])
            for index in history._indexes(retained['index'], catalog):
                for descriptor in index['days'].values():
                    history.decrypt_day_chunks(descriptor, read, bootstrap['key'],
                        view_id=bootstrap['view_id'], forecast_sha256=bootstrap['forecast_sha256'])
            _, original_seed = publisher.F.decrypt_view(seed['raw'], bootstrap['key'],
                view_id=bootstrap['view_id'])
            _need(publisher.F.forecast_anchor(original_seed) == bootstrap['forecast_sha256'], a)
            latest = reader._records.get((snapshot, 'latest.json'))
            _need(type(latest) is bytes, a)
            manifest = _json(latest, 4096, a)
            _need(manifest['cipher_sha256'] == ident and manifest['header']['generation'] == generation, a)
            ciphertexts = {}
            for (commit, path), body in reader._records.items():
                if path == 'latest.json':
                    continue
                logical = (_ROUTER + ident + '.json' if
                    commit == snapshot and path == 'views/' + ident + '.json' else _BASE + commit + '/' + path)
                ciphertexts[logical] = body
            secrets = tuple(value for value in (a.os.environ.get('RACE_AI_STATE_KEY'),
                a.os.environ.get('GH_TOKEN'), a.os.environ.get('GITHUB_TOKEN')) if type(value) is str)
            replay = build_current_v5_replay(snapshot_sha=snapshot, latest_raw=latest,
                ciphertexts=ciphertexts, context=context, view_id=bootstrap['view_id'],
                forecast_sha256=bootstrap['forecast_sha256'], secrets=secrets, now=now, _api=a)
        return replay
    except a.SafariHold:
        raise
    except Exception:
        raise a.SafariHold('CURRENT_V5_REPLAY_INVALID') from None


def current_v5_probe_script():
    """Observe selected state and the independent authenticated source-day label."""
    return r'''const crumb=globalThis.__raceSafariPrivacy?.current_v5;
        const text=document.querySelector('#source-date')?.textContent||'';
        const days=Array.from(new Set(text.match(/\d{4}-\d\d-\d\d/g)||[]));
        return {schema:crumb?.schema,generation:crumb?.generation,cipher_sha256:crumb?.cipher_sha256,
            history_day:crumb?.history_day,selected_day:document.querySelector('#selected-date')?.value,
            source_day:days.length===1?days[0]:null,
            v5_read_live_successes:crumb?.v5_read_live_successes,
            aes_successes:globalThis.__raceSafariPrivacy?.aes_successes};'''


def current_v5_checks(assets, seed, private, replay, secrets, *, _api):
    """Report only after actual native Safari AES/day/model probes and cleanup."""
    a = _api
    _need(type(replay) is CurrentV5Replay and type(private) is dict, a)
    fragment = private.get('fragment')
    _need(type(fragment) is str and re.fullmatch(
        r'#saved=' + re.escape(replay._view_id) + r'\.[A-Za-z0-9_-]{43}', fragment) is not None, a)
    context = _json(replay._context, 4 * 1024 * 1024, a)
    diagnostic = _current_v5_facts(context, None, None, a)
    phase = 'native_p1_detail'
    site = None

    def final_diagnostic(value):
        # Called only after both context managers have completed their cleanup.
        try:
            final_audit = current_v5_diagnostic(site.audit)
        except Exception:
            final_audit = current_v5_diagnostic(None)
        result = current_v5_diagnostic(value)
        for name in ('private_view_reads', 'encrypted_seed_reads',
                     'current_v5_manifest_reads', 'current_v5_cipher_reads',
                     'non_read_requests', 'outbound_requests_permitted',
                     'secret_in_request'):
            result[name] = final_audit[name]
        return result

    try:
        with a.LoopbackSite(assets, None, encrypted_seed=seed, current_v5=replay, secrets=secrets) as site:
            diagnostic.update({name: value for name, value in
                _current_v5_facts(context, None, site.audit, a).items() if value is not None})
            with a.apple_driver() as (driver, identity):
                a.native_identity(identity)
                driver.command('POST', '/url', {'url': site.url + fragment})
                driver.wait('''return globalThis.__raceSafariPrivacy?.current_v5?.v5_read_live_successes>0
                    && globalThis.__raceSafariPrivacy.current_v5.history_day===arguments[0]
                    && document.querySelector('#saved-view-sync')?.dataset.historyDay===arguments[0]
                    && document.querySelector('#selected-date')?.value===arguments[0];''',
                    context['day'], timeout=90)
                native = context['native_probe']
                a.open_saved_race(driver, native)
                driver.select('#prediction-select', native['index'])
                native_verified = driver.script('''return document.querySelector('#prediction-select')?.selectedOptions[0]?.textContent.startsWith('P1 ')
                    && document.querySelector('#detail-tab-content .forecast-panel')?.dataset.nativeDispatch==='true';''')
                diagnostic['native_p1_verified'] = native_verified if type(native_verified) is bool else None
                _need(native_verified, a, 'CURRENT_V5_EVIDENCE_INVALID')
                phase = 'comparison_originals'
                a.open_saved_race(driver, context['model_switch_probe'])
                driver.click('[data-detail-tab="outlook"]')
                choices = []
                for choice in context['model_switch_probe']['choices']:
                    driver.select('#prediction-select', choice['index'])
                    driver.select('#detail-model-select', choice['model_id'])
                    detail = a.seed_detail(driver)
                    choices.append(detail)
                    diagnostic['observed_model_choices'] = len(choices)
                    diagnostic['model_choices_match'] = False
                    a.verify_model_choice(choice, detail)
                diagnostic['model_choices_match'] = True
                phase = 'result_groups'
                a.click_saved_page(driver, 'results')
                values = driver.script('return Array.from(document.querySelectorAll("#results-model option"),e=>e.value)')
                groups = set()
                for value in values:
                    try:
                        fields = json.loads(value)
                        if type(fields) is list and len(fields) >= 6 and fields[1:3] == ['boat', 'P1']:
                            groups.add(a.wire((fields[3:7] + [None])[:4]))
                    except (TypeError, ValueError):
                        pass
                groups_match = all(a.wire(group) in groups for group in context['native_groups'])
                diagnostic.update(observed_native_p1_groups=len(groups), native_groups_match=groups_match)
                _need(groups_match, a, 'CURRENT_V5_EVIDENCE_INVALID')
                phase = 'result_metrics'
                metrics = driver.script('return document.querySelector("#saved-result-metrics")?.textContent')
                result_count = re.search(r'取得結果\s*(\d+)レース', metrics or '')
                diagnostic['result_metrics_parsed'] = result_count is not None
                diagnostic['observed_results'] = int(result_count[1]) if result_count is not None else None
                _need(result_count is not None, a, 'CURRENT_V5_EVIDENCE_INVALID')
                phase = 'verify_probe'
                observed = driver.script(a.current_v5_probe_script())
                _need(type(observed) is dict, a, 'CURRENT_V5_EVIDENCE_INVALID')
                observed.update(results=int(result_count[1]), native_p1_groups=len(groups), model_choices=choices)
                diagnostic.update({name: value for name, value in
                    _current_v5_facts(context, observed, site.audit, a).items() if value is not None})
                if _hex(observed.get('cipher_sha256')):
                    diagnostic['cipher_matches'] = observed['cipher_sha256'] == replay.cipher_sha256
                phase = 'private_boundary'
                snapshot = a.browser_snapshot(driver)
                a.verify_private_boundary(snapshot, site.audit, secrets, fragment=fragment, encrypted=True)
                phase = 'verify_probe'
                report = verify_current_v5_evidence(replay, observed, site.audit, _api=a)
        phase = 'current_day_recheck'
        _need(datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9))).date().isoformat()
            == context['day'], a, 'CURRENT_V5_EVIDENCE_INVALID')
        return report
    except a.CurrentV5EvidenceHold as error:
        combined = dict(diagnostic)
        combined.update({name: value for name, value in
            current_v5_diagnostic(error.diagnostic).items() if value is not None})
        raise a.CurrentV5EvidenceHold(error.phase, final_diagnostic(combined)) from None
    except a.SafariHold as error:
        if str(error) == 'CURRENT_V5_EVIDENCE_INVALID':
            raise a.CurrentV5EvidenceHold(phase, final_diagnostic(diagnostic)) from None
        raise
