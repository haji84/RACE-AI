"""Invented inputs exercise the Safari adapter's privacy and identity boundaries."""
import copy
import base64
import hashlib
import io
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import subprocess
import shlex
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from unittest.mock import patch

try:
    from scripts import boat_native_safari_acceptance as S
except ImportError:
    S = None


INDEX = b'''<!doctype html><html><head>
<meta name="race-ai-encrypted-saved-view" content="./views/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json">
<script defer src="./app.js?v=2d711642b726"></script></head><body></body></html>'''


def public_fixture(folder):
    assets = {'index.html': INDEX, 'app.js': b'x', 'style.css': b'body{}'}
    for name, raw in assets.items():
        (folder / name).write_bytes(raw)
    manifest = {'schema': 'RACE_AI_SAVED_PAGES_BUILD_V1',
                'forecast_sha256': 'a' * 64,
                'files': {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                          for name, raw in assets.items()}}
    (folder / 'site-build.json').write_text(json.dumps(manifest))
    return assets


def context_fixture():
    return {'schema': 'RACE_AI_PRIVATE_LIVE_SITE_CHECK_CONTEXT_V1',
            'owner_url': 'https://haji84.github.io/RACE-AI/#saved=' + 'a' * 64 + '.' + 'b' * 43,
            'day': '2030-04-01', 'current_day': '2030-04-01', 'stage': 'P1',
            'generation': 12, 'day_races': 1, 'minimum_results': 1,
            'native_group_count': 1, 'native_groups': [['invented-one', 'v1', None, None]],
            'native_probe': {'race_id': '20300401-01-01', 'index': 0,
                             'cutoff_at': '2030-04-01T01:00:00Z'},
            'model_switch_probe': {'race_id': '20300401-01-01',
                'cutoff_at': '2030-04-01T01:00:00Z', 'choices': [
                    {'model_id': 'invented-one', 'index': 0,
                     'tickets_sha256': '991b8297474b48ca3de040b694d02b2bb699f6ab83e0ae95e3724cdec5918cca'},
                    {'model_id': 'invented-two', 'index': 1,
                     'tickets_sha256': '2' * 64}]}}


def seed_fixture(folder):
    """Invented ciphertext and independently specified stored expectations."""
    public_fixture(folder)
    envelope = {'header': {'schema': 'RACE_AI_SAVED_WEB_VIEW_V2',
        'view_id': 'a' * 64, 'source_content_sha256': 'c' * 64},
        'nonce': 'AAAAAAAAAAAAAAAA', 'ciphertext': 'A' * 24}
    raw = json.dumps(envelope).encode()
    ident = hashlib.sha256(raw).hexdigest()
    name = 'views/' + ident + '.json'
    (folder / 'views').mkdir()
    (folder / name).write_bytes(raw)
    index = INDEX.replace(b'a' * 64, ident.encode()).replace(b'</head>',
        b'<meta name="race-ai-saved-view-forecast-sha" content="' + b'c' * 64 + b'"></head>')
    (folder / 'index.html').write_bytes(index)
    manifest = json.loads((folder / 'site-build.json').read_bytes())
    manifest['forecast_sha256'] = 'c' * 64
    for path in ('index.html', name):
        body = (folder / path).read_bytes()
        manifest['files'][path] = {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
    (folder / 'site-build.json').write_text(json.dumps(manifest))
    view = {'schema': 'RACE_AI_PRIVATE_CYCLE_VIEW_V1', 'records': [{
        'sport': 'boat', 'race_id': '20300401-01-01', 'event_date_jst': '2030-04-01',
        'cutoff_at': '2030-04-01T01:00:00Z',
        'prediction': {'model_id': 'invented-one', 'ordered_top8': [[1, 2, 3]]},
        'comparison_predictions': [{'model_id': 'invented-two', 'ordered_top8': [[2, 1, 3]]}]}]}
    bootstrap = {'view_id': 'a' * 64, 'key': bytes(range(32)), 'forecast_sha256': 'c' * 64}
    return raw, view, bootstrap


class EncryptedSeedBoundaryTests(unittest.TestCase):
    def test_seed_must_match_referenced_path_manifest_and_forecast_anchor(self):
        self.assertTrue(callable(getattr(S, 'load_encrypted_seed', None)), 'encrypted seed loader is missing')
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            raw, _, _ = seed_fixture(root)
            seed = S.load_encrypted_seed(root)
            self.assertEqual(seed['raw'], raw)
            self.assertEqual(seed['cipher_sha256'], hashlib.sha256(raw).hexdigest())
            (root / seed['path']).write_bytes(raw + b' ')
            with self.assertRaisesRegex(S.SafariHold, 'ASSET_HASH_MISMATCH'):
                S.load_encrypted_seed(root)

    def test_same_seed_context_refuses_other_view_or_forecast_binding(self):
        self.assertTrue(callable(getattr(S, 'build_seed_context', None)), 'same-seed binding is missing')
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, view, bootstrap = seed_fixture(root)
            seed = S.load_encrypted_seed(root)
            context = S.build_seed_context(seed, bootstrap, view, 'c' * 64)
            self.assertEqual(context['probe']['choices'][0]['tickets_sha256'],
                '918c7b1214a69daef0c4287154715aa5658f9daa5691f6987ba76ed2c55bb267')
            self.assertEqual(context['day_races'], 1)
            self.assertNotIn(base64.urlsafe_b64encode(bootstrap['key']).decode().rstrip('='), json.dumps(context))
            for changed, anchor in [(dict(bootstrap, view_id='b' * 64), 'c' * 64),
                                    (bootstrap, 'd' * 64)]:
                with self.assertRaisesRegex(S.SafariHold, 'ENCRYPTED_SEED_INVALID'):
                    S.build_seed_context(seed, changed, view, anchor)

    def test_encrypted_loopback_never_serves_a_plaintext_forecast_endpoint(self):
        self.assertTrue(callable(getattr(S, 'load_encrypted_seed', None)), 'encrypted transport is missing')
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            raw, _, _ = seed_fixture(root)
            seed = S.load_encrypted_seed(root)
            with S.LoopbackSite(S.load_public_assets(root), None, encrypted_seed=seed) as site:
                with urllib.request.urlopen(site.url, timeout=3) as response:
                    index = response.read()
                    self.assertIn(b'race-ai-encrypted-saved-view', index)
                    self.assertNotIn(b'race-ai-private-saved-view', index)
                with urllib.request.urlopen(site.origin + '/' + seed['path'], timeout=3) as response:
                    self.assertEqual(response.read(), raw)
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(site.origin + '/api/forecast/saved', timeout=3)
                denied.exception.close()
                self.assertEqual(site.audit['private_view_reads'], 0)
                self.assertEqual(site.audit['encrypted_seed_reads'], 1)

    def test_fragment_capability_is_allowed_only_in_exact_expected_location(self):
        key = 'b' * 43
        fragment = '#saved=' + 'a' * 64 + '.' + key
        snapshot = {'url': 'http://127.0.0.1:1234/' + fragment, 'local': {}, 'session': {},
                    'cookie': '', 'privacy': {'page_errors': 0}}
        audit = {'private_view_reads': 0, 'encrypted_seed_reads': 1,
            'secret_in_request': False, 'non_read_requests': 0, 'outbound_requests_permitted': 0}
        try:
            S.verify_private_boundary(snapshot, audit, (key, 'fixture-owner-secret'),
                                     fragment=fragment, encrypted=True)
        except TypeError:
            self.fail('privacy boundary does not yet support the existing viewer fragment')
        for changed in [dict(snapshot, url=snapshot['url'].replace('a' * 64, 'c' * 64)),
                        dict(snapshot, cookie=key), dict(snapshot, session={'key': key}),
                        dict(snapshot, url=snapshot['url'] + '?secret=fixture-owner-secret')]:
            with self.assertRaises(S.SafariHold):
                S.verify_private_boundary(changed, audit, (key, 'fixture-owner-secret'),
                                         fragment=fragment, encrypted=True)
        with self.assertRaises(S.SafariHold):
            S.verify_private_boundary(snapshot, dict(audit, secret_in_request=True), (key,),
                                     fragment=fragment, encrypted=True)

    def test_synthetic_capture_requires_exact_public_fixture_not_just_a_synthetic_label(self):
        self.assertTrue(callable(getattr(S, 'synthetic_fixture', None)), 'synthetic screenshot gate is missing')
        invented = {'data/example-synthetic-forecast-audit.json': json.dumps({
            'schema': 'RACE_AI_FORECAST_AUDIT_V1', 'dataset_status': 'SYNTHETIC_ONLY',
            'records': [{'race_id': 'actual-private-record'}]}).encode()}
        with self.assertRaisesRegex(S.SafariHold, 'SYNTHETIC_FIXTURE_INVALID'):
            S.synthetic_fixture(invented)

    def test_screenshot_export_requires_synthetic_server_and_matching_live_fixture_identity(self):
        self.assertTrue(callable(getattr(S, 'save_synthetic_screenshot', None)), 'screenshot export gate is missing')
        # A caller cannot turn a private browser into an exportable one by
        # setting a flag or supplying a synthetic-looking filename.
        with tempfile.TemporaryDirectory() as name:
            with S.LoopbackSite({'index.html': INDEX}, {'records': []}) as site:
                with self.assertRaisesRegex(S.SafariHold, 'SYNTHETIC_SCREENSHOT_REJECTED'):
                    S.save_synthetic_screenshot(None, site, Path(name), 390, 'home')
            self.assertEqual(list(Path(name).iterdir()), [])

    def test_each_seed_refusal_fails_if_any_forecast_or_successful_decryption_appears(self):
        self.assertTrue(callable(getattr(S, 'verify_seed_outcome', None)), 'encrypted refusal assertions are missing')
        for kind in ('missing-key', 'wrong-key', 'wrong-view', 'modified-cipher'):
            with self.subTest(kind=kind):
                S.verify_seed_outcome(kind, {'refused': True, 'forecast_panels': 0,
                                            'race_cards': 0, 'aes_successes': 0})
                for changed in ({'refused': False}, {'forecast_panels': 1},
                                {'race_cards': 1}, {'aes_successes': 1}):
                    with self.assertRaises(S.SafariHold):
                        S.verify_seed_outcome(kind,
                            {**{'refused': True, 'forecast_panels': 0, 'race_cards': 0,
                                'aes_successes': 0}, **changed})

    def test_exact_requested_width_is_required_for_visual_evidence(self):
        self.assertTrue(callable(getattr(S, 'require_viewport', None)), 'strict visual viewport gate is missing')
        for requested in (320, 390, 1440, 1920):
            self.assertTrue(S.require_viewport(requested, {'width': requested, 'height': 844})['requested_width_verified'])
            with self.assertRaisesRegex(S.SafariHold, 'VIEWPORT_INVALID'):
                S.require_viewport(requested, {'width': requested + 1, 'height': 844})

    def test_viewer_credentials_are_blocked_before_same_origin_fetch_in_url_or_headers(self):
        program = r'''
const vm=require('node:vm'),fs=require('node:fs');let actual=0;
class XHR{open(){actual++}setRequestHeader(){actual++}send(){actual++}}
const key='b'.repeat(43),scope={URL,Headers,location:{href:'http://127.0.0.1:1234/',origin:'http://127.0.0.1:1234',hash:'#saved='+'a'.repeat(64)+'.'+key},
 XMLHttpRequest:XHR,navigator:{},TypeError,Promise,addEventListener(){},fetch:async()=>{actual++;return {ok:true}}};
scope.window=scope;vm.createContext(scope);vm.runInContext(fs.readFileSync(0,'utf8'),scope);
(async()=>{
 for(const [url,options] of [['/?key='+key,{}],['/?key='+'%62'.repeat(43),{}],['/',{headers:{Authorization:key}}],['/',{method:'POST',body:'x'}]])
  try{await scope.fetch(url,options)}catch{}
 await scope.fetch('/app.js');
 process.stdout.write(JSON.stringify({actual,blocked:scope.__raceSafariPrivacy.external_blocked}));
})().catch(()=>process.exitCode=2);
'''
        result = subprocess.run(['node', '-e', program], input=S.PRIVACY_SCRIPT,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'actual': 1, 'blocked': 4})

    def test_driver_closes_http_error_response_without_exposing_its_private_message(self):
        driver = S.WebDriver(1234)
        body = io.BytesIO(b'private-owner-sentinel')
        error = urllib.error.HTTPError('http://127.0.0.1:1234/session', 500,
                                      'private-owner-sentinel', {}, body)
        with patch.object(driver.opener, 'open', side_effect=error):
            with self.assertRaisesRegex(S.SafariHold, '^SAFARI_WEBDRIVER_FAILED$'):
                driver.call('POST', '/session', {})
        self.assertTrue(body.closed, 'error responses must release their sockets too')

    def test_synthetic_parser_guard_rejects_changed_input_and_real_scope_output(self):
        fixture = {'schema': 'RACE_AI_FORECAST_AUDIT_V1', 'dataset_status': 'SYNTHETIC_ONLY',
                   'records': [{'race_id': 'invented'}]}
        program = r'''
const vm=require('node:vm'),fs=require('node:fs');
const scope={__raceSafariPrivacy:{},Object,JSON,Error};vm.createContext(scope);
vm.runInContext(fs.readFileSync(0,'utf8'),scope);
scope.RaceProductData={parse:raw=>({...raw,records:raw.records.map(r=>({...r,scope:'synthetic'}))})};
const original={schema:'RACE_AI_FORECAST_AUDIT_V1',dataset_status:'SYNTHETIC_ONLY',records:[{race_id:'invented'}]};
scope.RaceProductData.parse(original);const accepted=scope.__raceSafariPrivacy.synthetic_fixture_verified;
let changed=false,real=false;
try{scope.RaceProductData.parse({...original,records:[{race_id:'private-record'}]})}catch{changed=true}
const afterChanged=scope.__raceSafariPrivacy.synthetic_fixture_verified;
scope.RaceProductData={parse:raw=>({...raw,records:raw.records.map(r=>({...r,scope:'official'}))})};
try{scope.RaceProductData.parse(original)}catch{real=true}
process.stdout.write(JSON.stringify({accepted,changed,afterChanged,real,final:scope.__raceSafariPrivacy.synthetic_fixture_verified}));
'''
        result = subprocess.run(['node', '-e', program], input=S.synthetic_guard(fixture),
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'accepted': True, 'changed': True,
            'afterChanged': False, 'real': True, 'final': False})

    def test_an_already_final_public_fixture_opens_results_even_with_a_future_cutoff(self):
        self.assertTrue(callable(getattr(S, 'open_saved_race', None)))
        clicked = []
        class Driver:
            def click(self, selector):
                clicked.append(selector)
            def wait(self, *args):
                return True
            def script(self, source, *args):
                return True
        S.open_saved_race(Driver(), {'race_id': 'synthetic:2030-01-01:boat:1',
            'cutoff_at': '2030-01-01T10:00:00+09:00', 'result': {'status': 'final'}})
        self.assertIn('[data-race-view="results"]', clicked)

    def test_artifact_gate_requires_all_measured_widths_and_no_real_capture_context(self):
        raw = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
        with tempfile.TemporaryDirectory() as name:
            # macOS temp roots may use /var -> /private/var. Canonicalize
            # this trusted fixture; production still rejects symlink paths.
            folder = Path(name).resolve()
            images = []
            for width in (320, 390, 1440, 1920):
                for page in ('home', 'races', 'detail', 'picks', 'results', 'research', 'settings'):
                    path = folder / (str(width) + '-' + page + '.png')
                    path.write_bytes(raw)
                    images.append({'name': path.name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
            report = {'schema': 'RACE_AI_SYNTHETIC_SAFARI_VISUAL_V1', 'dataset_status': 'SYNTHETIC_ONLY',
                'public_fixture_sha256': S.SYNTHETIC_SHA, 'screenshots': images,
                'real_data_context_used_for_capture': False, 'physical_iphone_verified': False,
                'all_eight_reference_screens_visually_verified': False,
                'viewports': [{'requested_width': w, 'actual_inner_width': w, 'actual_inner_height': 844,
                               'requested_width_verified': True, 'physical_iphone_verified': False}
                              for w in (320, 390, 1440, 1920)]}
            target = folder / 'synthetic-only.json'
            target.write_text(json.dumps(report))
            self.assertEqual(S.verify_synthetic_artifacts(folder)['screenshots'], 28)
            for changed in [dict(report, viewports=[]), dict(report, real_data_context_used_for_capture=True),
                            dict(report, viewports=[dict(v, actual_inner_width=500) for v in report['viewports']])]:
                target.write_text(json.dumps(changed))
                with self.assertRaisesRegex(S.SafariHold, 'SYNTHETIC_OUTPUT_REJECTED'):
                    S.verify_synthetic_artifacts(folder)
            target.write_text(json.dumps(report))
            (folder / '390-home.png').write_bytes(raw + b'private-image-metadata')
            with self.assertRaises(S.SafariHold):
                S.verify_synthetic_artifacts(folder)
            (folder / '390-home.png').write_bytes(raw)
            (folder / 'extra.png').write_bytes(raw)
            with self.assertRaises(S.SafariHold):
                S.verify_synthetic_artifacts(folder)

    def test_artifact_fixture_handles_a_symlinked_temp_parent_without_relaxing_the_gate(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            real_parent = root / 'private-var'
            real_parent.mkdir()
            alias = root / 'var'
            alias.symlink_to(real_parent, target_is_directory=True)
            (real_parent / 'synthetic-only.json').write_text('{}')
            # Production still refuses the unresolved alias before reading any
            # artifact metadata. Only this test's trusted temp fixture resolves.
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('symlink metadata was read')):
                with self.assertRaisesRegex(S.SafariHold, 'SYNTHETIC_OUTPUT_REJECTED'):
                    S.verify_synthetic_artifacts(alias)
            result = unittest.TestResult()
            with patch.object(tempfile, 'tempdir', str(alias)):
                EncryptedSeedBoundaryTests(
                    'test_artifact_gate_requires_all_measured_widths_and_no_real_capture_context').run(result)
            self.assertTrue(result.wasSuccessful(), str(result.errors + result.failures))


def acceptance_workflow_steps():
    """Read scalar step fields without requiring an extra YAML dependency."""
    path = Path(__file__).resolve().parents[1] / '.github/workflows/boat-owner-formal-live-pages-proof.yml'
    steps, current = [], None
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.startswith('      - '):
            current = {}
            steps.append(current)
            field = line[8:]
        elif current is not None and line.startswith('        ') and not line.startswith('         '):
            field = line[8:]
        elif current is not None and line.startswith('          ') and not line.startswith('           '):
            field=line.strip()
            if field.split(':',1)[0] not in ('python-version','ref','path','persist-credentials'):
                continue
        else:
            continue
        if ':' in field:
            name, value = field.split(':', 1)
            value=value.strip()
            if len(value)>=2 and value[0] in "'\"" and value[-1]==value[0]:
                value=value[1:-1]
            current[name] = value
    return steps


class NativeReaderSetupTests(unittest.TestCase):
    def test_authenticated_reader_has_pinned_parsers_before_private_context_import(self):
        steps=acceptance_workflow_steps()
        verify=next(i for i,s in enumerate(steps) if s.get('name')==
            'Verify real desktop Safari with authenticated originals and private loopback transport')
        expected={'.native-safari-source/pr64-reference':'761247bee0209e37b1af6b8885e92cad3e9260a5',
                  '.native-safari-source/pr72-reference':'7a432e5acc4d3495a0e82bd79726929e2f8085fe'}
        configured={}
        # Checkout uses flow mappings for scalar with-fields elsewhere; these
        # dependency steps deliberately use standard multiline with fields.
        for step in steps[:verify]:
            if step.get('path') in expected:
                configured[step['path']]=step.get('ref')
                self.assertEqual(step.get('persist-credentials'),'false')
        self.assertEqual(configured,expected,'private reader cannot import core without its pinned parser checkouts')


@contextmanager
def driver_endpoint(capabilities, *, session_reply=None, session_status=200):
    """The Mac-only dependency is replaced at its actual W3C HTTP boundary."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((self.path, body))
            if self.path == '/session':
                value = {'sessionId': 'fixture-session', 'capabilities': capabilities}
                status = session_status
            else:
                value = {'error': 'unknown error', 'message': 'fixture-secret-private-driver-error'}
                status = 500
            reply = session_reply if self.path == '/session' and session_reply is not None else {'value': value}
            raw = reply if isinstance(reply, bytes) else json.dumps(reply).encode()
            self.send_response(status)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except OSError:
                pass  # A bounded client may close an intentionally oversized reply.

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


class NativeSafariAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(S, 'native Safari acceptance adapter is not implemented')

    def test_session_creation_error_exposes_only_safe_protocol_fields(self):
        secret = 'fixture-private-key-never-print'
        private_url = 'https://private.invalid/#saved=' + secret
        message = ("Could not create a session: You must enable the 'Allow Remote Automation' "
                   "option in Safari's Develop menu to control Safari via WebDriver. " + private_url)
        reply = {'value': {'error': 'session not created', 'message': message,
                           'stacktrace': secret, 'private_params': {'key': secret}}}
        with driver_endpoint({}, session_reply=reply, session_status=500) as (port, _):
            try:
                S.WebDriver(port).new_session()
            except S.SafariHold as error:
                report = S.failure_report(error)
            else:
                self.fail('an HTTP session-creation error cannot create a browser session')
        self.assertEqual(report.get('webdriver_operation'), 'new_session')
        self.assertEqual(report.get('webdriver_http_status'), 500)
        self.assertEqual(report.get('webdriver_error_code'), 'session not created')
        self.assertIs(report.get('remote_automation_disabled_message_observed'), True)
        self.assertEqual(report.get('checker_function'), 'call')
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn('private.invalid', json.dumps(report))
        self.assertNotIn('message', {key for key in report if key != 'remote_automation_disabled_message_observed'})

    def test_unknown_error_codes_and_private_message_text_are_never_exported(self):
        for code, message in [('private-key-error', 'private-key-message'),
                              ('unknown error', "You must enable the 'Allow Remote Automation' option in Safari's Develop menu")]:
            with self.subTest(code=code):
                with driver_endpoint({}, session_reply={'value': {'error': code, 'message': message}},
                                     session_status=500) as (port, _):
                    with self.assertRaises(S.SafariHold) as caught:
                        S.WebDriver(port).new_session()
                report = S.failure_report(caught.exception)
                self.assertEqual(report.get('webdriver_http_status'), 500)
                self.assertEqual(report.get('webdriver_error_code'), 'unknown error' if code == 'unknown error' else None)
                self.assertIs(report.get('remote_automation_disabled_message_observed'), code == 'unknown error')
                self.assertNotIn('private-key', json.dumps(report))

    def test_duplicate_fields_and_nonfinite_json_cannot_create_a_session(self):
        value = {'sessionId': 'fixture-session', 'capabilities': {
            'browserName': 'Safari', 'browserVersion': '26.6', 'platformName': 'macOS'}}
        raw = json.dumps(value).encode()
        for reply in [b'{"value":' + raw + b',"value":' + raw + b'}',
                      b'{"value":' + raw[:-1] + b',"unused":NaN}}']:
            with self.subTest(reply_kind='duplicate' if reply.count(b'"value"') == 2 else 'nonfinite'):
                with driver_endpoint({}, session_reply=reply) as (port, _):
                    with self.assertRaises(S.SafariHold) as caught:
                        S.WebDriver(port).new_session()
                report = S.failure_report(caught.exception)
                self.assertEqual(report.get('webdriver_http_status'), 200)
                self.assertEqual(report.get('webdriver_operation'), 'new_session')

    def test_float_overflow_anywhere_in_a_session_response_is_fatal(self):
        value = {'sessionId': 'fixture-session', 'capabilities': {
            'browserName': 'Safari', 'browserVersion': '26.6', 'platformName': 'macOS'}}
        raw = json.dumps(value).encode()
        for token in (b'1e400', b'-1e400', b'{"nested":[1e400]}', b'{"nested":[-1e400]}'):
            with self.subTest(token=token):
                reply = b'{"value":' + raw[:-1] + b',"unused":' + token + b'}}'
                with driver_endpoint({}, session_reply=reply) as (port, _):
                    with self.assertRaises(S.SafariHold) as caught:
                        S.WebDriver(port).new_session()
                report = S.failure_report(caught.exception)
                self.assertEqual(report.get('webdriver_http_status'), 200)
                self.assertEqual(report.get('webdriver_operation'), 'new_session')

    def test_ordinary_finite_floats_in_a_session_response_remain_accepted(self):
        capabilities = {'browserName': 'Safari', 'browserVersion': '26.6', 'platformName': 'macOS'}
        reply = {'value': {'sessionId': 'fixture-session', 'capabilities': capabilities,
                           'unused': {'nested': [1.25, -2.5, 1e300, -1e300, 1e-300, -1e-300, -0.0]}}}
        with driver_endpoint({}, session_reply=reply) as (port, _):
            self.assertEqual(S.WebDriver(port).new_session(), capabilities)

    def test_oversized_http_error_is_fatal_without_extracting_its_message(self):
        reply = {'value': {'error': 'session not created', 'message': 'private-key-' * 8000}}
        with driver_endpoint({}, session_reply=reply, session_status=500) as (port, _):
            with self.assertRaises(S.SafariHold) as caught:
                S.WebDriver(port).new_session()
        report = S.failure_report(caught.exception)
        self.assertEqual(report.get('webdriver_http_status'), 500)
        self.assertIsNone(report.get('webdriver_error_code'))
        self.assertIs(report.get('remote_automation_disabled_message_observed'), False)
        self.assertNotIn('private-key', json.dumps(report))

    def test_malformed_oversized_and_error_success_responses_remain_fatal_and_private(self):
        replies = [b'null', b'[]', b'\xffprivate-key', {'wrong': 'private-key'},
            {'value': {'sessionId': 123, 'capabilities': {'private': 'private-key'}}},
            {'value': {'error': 'unknown error', 'message': 'private-key'}},
            b'{"value":"' + b'x' * (2 * 1024 * 1024) + b'private-key"}']
        for reply in replies:
            with self.subTest(kind=type(reply).__name__):
                with driver_endpoint({}, session_reply=reply) as (port, _):
                    with self.assertRaises(S.SafariHold) as caught:
                        S.WebDriver(port).new_session()
                report = S.failure_report(caught.exception)
                self.assertEqual(report.get('webdriver_operation'), 'new_session')
                self.assertEqual(report.get('webdriver_http_status'), 200)
                self.assertNotIn('private-key', json.dumps(report))

    def test_socket_failure_has_no_raw_exception_text_or_request_parameters(self):
        driver = S.WebDriver(1234)
        with patch.object(driver.opener, 'open', side_effect=urllib.error.URLError('https://private.invalid/private-key')):
            with self.assertRaises(S.SafariHold) as caught:
                driver.new_session()
        report = S.failure_report(caught.exception)
        self.assertEqual(report.get('webdriver_operation'), 'new_session')
        self.assertIsNone(report.get('webdriver_http_status'))
        self.assertIsNone(report.get('webdriver_error_code'))
        self.assertNotIn('private', json.dumps(report))

    def test_spoofed_diagnostic_fields_are_filtered_again_before_public_output(self):
        self.assertTrue(callable(getattr(S, 'DriverHold', None)), 'typed driver diagnostics are missing')
        error = S.DriverHold(operation='https://private.invalid/private-key', http_status=True,
                             w3c_error='private-key', remote_automation_disabled='private-key')
        report = S.failure_report(error)
        self.assertEqual(report.get('webdriver_operation'), 'unknown_command')
        self.assertIsNone(report.get('webdriver_http_status'))
        self.assertIsNone(report.get('webdriver_error_code'))
        self.assertIs(report.get('remote_automation_disabled_message_observed'), False)
        self.assertNotIn('private', json.dumps(report))

    def test_process_start_and_early_exit_report_only_the_startup_operation(self):
        for stage in ('start_driver', 'wait_for_driver'):
            with self.subTest(stage=stage), patch.object(S.platform, 'system', return_value='Darwin'), \
                    patch.object(S.os.path, 'isfile', return_value=True), \
                    patch.object(S.os, 'access', return_value=True), patch.object(S.subprocess, 'Popen') as start:
                if stage == 'start_driver':
                    start.side_effect = OSError('private-key https://private.invalid/')
                else:
                    start.return_value.poll.return_value = 1
                with self.assertRaises(S.SafariHold) as caught:
                    with S.apple_driver():
                        self.fail('failed startup cannot create a browser session')
                report = S.failure_report(caught.exception)
                self.assertEqual(report.get('webdriver_operation'), stage)
                self.assertEqual(report.get('reason'), 'SAFARIDRIVER_UNAVAILABLE')
                self.assertNotIn('private', json.dumps(report))

    def test_element_waits_for_a_delayed_visible_detail_control(self):
        driver = S.WebDriver(1234)
        ready = {'element-6066-11e4-a52e-4f735466cecf': 'visible-tab'}
        with patch.object(driver, 'script', side_effect=[None, ready]) as query:
            self.assertEqual(driver.element('[data-detail-tab="outlook"]'), 'visible-tab')
        self.assertEqual(query.call_count, 2)

    def test_native_click_scrolls_and_checks_the_hit_target_before_clicking(self):
        driver = S.WebDriver(1234)
        state = {'centered': False, 'hit_checked': False, 'clicked': False}

        def script(source, *args):
            if 'querySelectorAll' in source:
                return {'element-6066-11e4-a52e-4f735466cecf': 'race-button'}
            if 'scrollIntoView' in source:
                state['centered'] = True
                return None
            self.assertIn('elementFromPoint', source)
            state['hit_checked'] = True
            return state['centered']

        def command(method, suffix, body):
            self.assertTrue(state['centered'], 'a bottom-aligned click can hit the fixed mobile navigation')
            self.assertTrue(state['hit_checked'])
            self.assertEqual((method, suffix, body), ('POST', '/element/race-button/click', {}))
            state['clicked'] = True

        with patch.object(driver, 'script', side_effect=script), patch.object(driver, 'command', side_effect=command):
            driver.click('[data-open-race="invented-race"]')
        self.assertTrue(state['clicked'])

    def test_native_option_click_keeps_the_existing_select_protocol(self):
        driver = S.WebDriver(1234)
        with patch.object(driver, 'element', return_value='native-option'), \
                patch.object(driver, 'script', side_effect=AssertionError('closed native options have no hit rectangle')), \
                patch.object(driver, 'command') as native:
            driver.click('#prediction-select option[value="0"]', visible=False)
        native.assert_called_once_with('POST', '/element/native-option/click', {})

    def test_occluded_control_never_receives_a_native_click(self):
        driver = S.WebDriver(1234)
        with patch.object(driver, 'script'), patch.object(driver, 'wait', side_effect=S.AppHold({})), \
                patch.object(driver, 'command') as native:
            with self.assertRaises(S.AppHold):
                driver._click_visible_element('covered-race-button')
        native.assert_not_called()

    def test_ui_hold_reports_only_public_error_location_and_numeric_counts(self):
        report = S.failure_report(S.AppHold({'page_errors': 2, 'error_module': 'app.js',
            'error_line': 1234, 'visible_page': 'page-races', 'viewport_width': 500,
            'private': 'private-owner-sentinel', 'url': 'https://private-owner-sentinel/'}))
        self.assertEqual(report['reason'], 'APP_UI_CHECK_FAILED')
        self.assertEqual(report['ui_page_errors'], 2)
        self.assertEqual(report['ui_error_module'], 'app.js')
        self.assertEqual(report['ui_error_line'], 1234)
        self.assertEqual(report['ui_visible_page'], 'page-races')
        self.assertEqual(report['ui_viewport_width'], 500)
        self.assertNotIn('sentinel', json.dumps(report))
        other = S.failure_report(S.AppHold({'page_errors': True,
            'error_module': 'private-owner-sentinel', 'error_line': 'private-owner-sentinel',
            'visible_page': 'private-owner-sentinel', 'viewport_width': 10**20}))
        self.assertIsNone(other['ui_error_module'])
        self.assertIsNone(other['ui_visible_page'])
        self.assertIsNone(other['ui_viewport_width'])
        self.assertNotIn('sentinel', json.dumps(other))

    def test_native_budget_replacement_survives_app_rejecting_an_empty_change(self):
        # The deployed app restores the previous budget when change sees an
        # empty/invalid number. Native Element Clear can trigger that change.
        state = {'text': '10000', 'budget': 10000, 'meta': False, 'selected': False}

        def change():
            value = int(state['text'] or '0')
            if 100 <= value <= 10000000 and value % 100 == 0:
                state['budget'] = value
            state['text'] = str(state['budget'])

        def command(method, suffix, body=None):
            if suffix == '/execute/sync':
                if 'querySelectorAll' in body['script']:
                    return {'element-6066-11e4-a52e-4f735466cecf': 'budget-field'}
                if 'scrollIntoView' in body['script']:
                    return None
                if 'elementFromPoint' in body['script']:
                    return True
                return state['text'] == body['args'][0]
            if suffix.endswith('/click'):
                return None
            if suffix.endswith('/clear'):
                state['text'] = ''
                change()
                return None
            if suffix.endswith('/value'):
                # Do not assume Element Send Keys interprets a modifier chord
                # inside one text string; the real Mac retry still failed.
                for key in body['text']:
                    if key.isdigit():
                        state['text'] += key
                    elif key == '\ue004':
                        change()
                return None
            self.assertEqual(suffix, '/actions')
            keyboard, = body['actions']
            self.assertEqual(keyboard['type'], 'key')
            for event in keyboard['actions']:
                key = event['value']
                if key == '\ue03d':
                    state['meta'] = event['type'] == 'keyDown'
                elif event['type'] == 'keyUp':
                    continue
                elif key == 'a' and state['meta']:
                    state['selected'] = True
                elif key == '\ue004':
                    change()
                else:
                    self.assertFalse(state['meta'], 'release Command before typing the amount')
                    state['text'] = ('' if state['selected'] else state['text']) + key
                    state['selected'] = False

        driver = S.WebDriver(1234)
        with patch.object(driver, 'command', side_effect=command), \
                patch.object(S.time, 'monotonic', side_effect=[0, 0, 0, 0, 0, 0, 46]):
            driver.budget(5000)
        self.assertEqual((state['text'], state['budget']), ('5000', 5000))
        self.assertFalse(state['meta'])

    def test_budget_failure_diagnostic_cannot_export_arbitrary_control_text(self):
        error = S.BudgetHold(5000, {'value': 'private-owner-sentinel',
                                  'focused': 'private-owner-sentinel', 'valid': True,
                                  'private': 'secret-token-sentinel'})
        report = S.failure_report(error)
        self.assertEqual(report['reason'], 'NATIVE_BUDGET_INPUT_NOT_APPLIED')
        self.assertEqual(report['budget_target'], 5000)
        self.assertIsNone(report['budget_observed'])
        self.assertFalse(report['budget_field_focused'])
        self.assertTrue(report['budget_field_valid'])
        self.assertNotIn('sentinel', json.dumps(report))
        for observed, expected in [('5000', 5000), ('10000000', 10000000),
                                   ('99999999', None), ('123456789', None), ('', None),
                                   ('5e3', None), ('５０００', None), (5000, None)]:
            with self.subTest(observed=observed):
                safe = S.failure_report(S.BudgetHold(True, {'value': observed}))
                self.assertIsNone(safe['budget_target'])
                self.assertEqual(safe['budget_observed'], expected)

    def test_actual_ui_failure_reports_only_public_checker_location(self):
        class Driver:
            def command(self,*args):pass
            def wait(self,*args,**kwargs):raise S.SafariHold('APP_UI_CHECK_FAILED')
        class Site:
            url='http://127.0.0.1:1234/'
        try:
            S.app_checks(Driver(),Site(),{'private':'private-owner-sentinel'},('secret-token-sentinel',))
        except S.SafariHold as error:
            report=S.failure_report(error)
        self.assertEqual(report.get('checker_function'),'app_checks')
        self.assertIsInstance(report.get('checker_line'),int)
        self.assertNotIn('sentinel',json.dumps(report))

    def test_external_failure_cannot_supply_a_checker_location_or_private_message(self):
        external = compile("def app_checks():\n    raise ValueError('private-owner-sentinel')\napp_checks()",
                           '/private-owner-sentinel/browser.py', 'exec')
        try:
            exec(external, {})
        except ValueError as error:
            report = S.failure_report(error)
        self.assertEqual(report, {'status': 'NATIVE_SAFARI_ACCEPTANCE_HOLD',
                                  'reason': 'SAFARI_OPERATION_FAILED'})

    def test_native_workflow_pins_python_before_running_privacy_boundaries(self):
        steps = acceptance_workflow_steps()
        setup = [(index, step) for index, step in enumerate(steps)
                 if step.get('uses', '').startswith('actions/setup-python@')]
        tests = [(index, step) for index, step in enumerate(steps)
                 if shlex.split(step.get('run', ''))[:3] == ['python3', '-m', 'unittest']]
        self.assertEqual(len(setup), 1)
        self.assertEqual(len(tests), 1)
        setup_index, setup_step = setup[0]
        tests_index, tests_step = tests[0]
        self.assertLess(setup_index, tests_index,
                        'native privacy tests must use the pinned Python, not the macOS image default')
        self.assertEqual(setup_step['python-version'], '3.11')
        self.assertIn("inputs.browser == 'native-safari'", setup_step['if'])
        arguments = shlex.split(tests_step['run'])
        self.assertEqual(arguments[arguments.index('-p') + 1], 'test_boat_native_safari_acceptance.py')

    def test_missing_or_modified_manifest_asset_cannot_be_served(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            public_fixture(folder)
            result = S.load_public_assets(folder)
            self.assertEqual(result['app.js'], b'x')
            (folder / 'app.js').write_bytes(b'y')
            with self.assertRaisesRegex(S.SafariHold, 'ASSET_HASH_MISMATCH'):
                S.load_public_assets(folder)
            (folder / 'app.js').unlink()
            with self.assertRaisesRegex(S.SafariHold, 'ASSET_FILE_REJECTED'):
                S.load_public_assets(folder)

    def test_public_asset_symlinks_and_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            public_fixture(folder)
            (folder / 'app.js').unlink()
            (folder / 'app.js').symlink_to(folder / 'style.css')
            with self.assertRaisesRegex(S.SafariHold, 'ASSET_FILE_REJECTED'):
                S.load_public_assets(folder)
            doc = json.loads((folder / 'site-build.json').read_text())
            doc['files']['../outside.js'] = doc['files'].pop('app.js')
            (folder / 'site-build.json').write_text(json.dumps(doc))
            with self.assertRaisesRegex(S.SafariHold, 'ASSET_PATH_REJECTED'):
                S.load_public_assets(folder)

    def test_loopback_serves_existing_app_and_memory_view_under_strict_csp(self):
        private = {'records': [{'race_id': 'invented-only'}]}
        stream = io.StringIO()
        with redirect_stdout(stream), redirect_stderr(stream):
            with S.LoopbackSite({'index.html': INDEX, 'app.js': b'x'}, private,
                                secrets=('fixture-secret-never-print',)) as site:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(site.url, timeout=3) as response:
                    body = response.read()
                    self.assertIn(b'race-ai-private-saved-view', body)
                    self.assertNotIn(b'race-ai-encrypted-saved-view', body)
                    self.assertIn(b'./app.js?v=2d711642b726', body)
                    csp = response.headers['Content-Security-Policy']
                    self.assertIn("connect-src 'self'", csp)
                    self.assertNotIn('https:', csp)
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                with opener.open(site.origin + '/api/forecast/saved', timeout=3) as response:
                    self.assertEqual(json.load(response), private)
                self.assertEqual(site.audit['private_view_reads'], 1)
                self.assertFalse(site.audit['secret_in_request'])
        self.assertEqual(stream.getvalue(), '')

    def test_encryption_keys_cannot_enter_the_browser_even_inside_a_view_field(self):
        with self.assertRaisesRegex(S.SafariHold, 'PRIVATE_NETWORK_BOUNDARY_FAILED'):
            S.LoopbackSite({'index.html': INDEX}, {'records': [{'note': 'fixture-secret'}]},
                           secrets=('fixture-secret',))

    def test_loopback_rejects_unknown_query_mutation_and_foreign_origin_without_logging(self):
        stream = io.StringIO()
        with redirect_stdout(stream), redirect_stderr(stream):
            with S.LoopbackSite({'index.html': INDEX, 'app.js': b'x'}, {'records': []},
                                secrets=('fixture-secret-never-print',)) as site:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                cases = [
                    urllib.request.Request(site.origin + '/unknown'),
                    urllib.request.Request(site.origin + '/api/forecast/saved?key=fixture-secret-never-print'),
                    urllib.request.Request(site.origin + '/api/forecast/saved', data=b'private', method='POST'),
                    urllib.request.Request(site.origin + '/api/forecast/saved', headers={'Origin': 'https://foreign.invalid'}),
                    urllib.request.Request(site.origin + '/api/forecast/saved', headers={'Host': 'foreign.invalid'}),
                ]
                for request in cases:
                    with self.subTest(method=request.get_method(), origin=request.headers.get('Origin')):
                        with self.assertRaises(urllib.error.HTTPError) as caught:
                            opener.open(request, timeout=3)
                        self.assertIn(caught.exception.code, (400, 403, 404, 405))
                        self.assertNotIn(b'private', caught.exception.read())
                self.assertTrue(site.audit['secret_in_request'])
                self.assertEqual(site.audit['private_view_reads'], 0)
                self.assertEqual(site.audit['rejected_requests'], 5)
        self.assertEqual(stream.getvalue(), '')

    def test_only_real_native_macos_safari_capabilities_are_accepted(self):
        good = {'browserName': 'Safari', 'browserVersion': '26.6', 'platformName': 'macOS'}
        self.assertEqual(S.native_identity(good), good)
        for bad in [dict(good, browserName='webkit'), dict(good, browserName='chrome'),
                    dict(good, platformName='Linux'), dict(good, platformName='iOS'),
                    dict(good, browserVersion=''), dict(good, browserVersion='private\nsecret')]:
            with self.subTest(bad=bad):
                with self.assertRaises(S.SafariHold):
                    S.native_identity(bad)

    def test_w3c_session_requests_native_safari_and_sanitizes_actual_http_errors(self):
        capabilities = {'browserName': 'Safari', 'browserVersion': '26.6', 'platformName': 'macOS',
                        'unexpected_private_field': 'fixture-secret'}
        stream = io.StringIO()
        with redirect_stdout(stream), redirect_stderr(stream):
            with driver_endpoint(capabilities) as (port, requests):
                driver = S.WebDriver(port)
                self.assertEqual(driver.new_session(), {'browserName': 'Safari', 'browserVersion': '26.6',
                                                         'platformName': 'macOS'})
                self.assertEqual(requests[0], ('/session', {'capabilities': {'alwaysMatch': {
                    'browserName': 'Safari', 'platformName': 'macOS'}}}))
                with self.assertRaises(S.SafariHold) as caught:
                    driver.script('return document.title')
                self.assertEqual(S.failure_report(caught.exception)['reason'], 'SAFARI_WEBDRIVER_FAILED')
                self.assertNotIn('fixture-secret', str(caught.exception))
        self.assertEqual(stream.getvalue(), '')

    def test_w3c_driver_cannot_relabel_a_webkit_session_as_native_safari(self):
        with driver_endpoint({'browserName': 'webkit', 'browserVersion': '26.6',
                              'platformName': 'macOS'}) as (port, requests):
            with self.assertRaisesRegex(S.SafariHold, 'SAFARI_CAPABILITIES_INVALID'):
                S.WebDriver(port).new_session()
            self.assertEqual(len(requests), 1)

    def test_a_macos_minimum_window_width_does_not_become_a_390px_pass(self):
        result = S.viewport_evidence(390, {'width': 500, 'height': 780})
        self.assertFalse(result['requested_width_verified'])
        self.assertEqual(result['actual_inner_width'], 500)
        self.assertFalse(result['physical_iphone_verified'])
        self.assertTrue(S.viewport_evidence(390, {'width': 390, 'height': 780})['requested_width_verified'])

    def test_context_cannot_pass_without_real_p1_and_two_distinct_saved_models(self):
        good = context_fixture()
        public = S.validate_context(good)
        self.assertNotIn('owner_url', public)
        self.assertNotIn('b' * 43, json.dumps(public))
        for field, value in [('stage', 'P0'), ('minimum_results', 0), ('generation', 0),
                             ('model_switch_probe', None), ('native_group_count', 0)]:
            with self.subTest(field=field), self.assertRaises(S.SafariHold):
                S.validate_context(dict(good, **{field: value}))
        bad = copy.deepcopy(good)
        bad['model_switch_probe']['choices'][1]['model_id'] = 'invented-one'
        with self.assertRaises(S.SafariHold):
            S.validate_context(bad)

    def test_selected_model_must_match_its_saved_version_and_top8_hash(self):
        # SHA256 of the literal compact JSON [[1,2,3],[2,1,3]].
        choice = {'model_id': 'invented-one', 'index': 0,
                  'tickets_sha256': '991b8297474b48ca3de040b694d02b2bb699f6ab83e0ae95e3724cdec5918cca'}
        detail = {'model_id': 'invented-one', 'index': '0', 'tickets': [[1, 2, 3], [2, 1, 3]]}
        S.verify_model_choice(choice, detail)
        for changed in [dict(detail, model_id='invented-two'), dict(detail, index='1'),
                        dict(detail, tickets=[[1, 3, 2], [2, 1, 3]])]:
            with self.assertRaises(S.SafariHold):
                S.verify_model_choice(choice, changed)

    def test_driver_environment_drops_root_key_tokens_and_git_credentials(self):
        result = S.driver_environment({'PATH': '/usr/bin', 'HOME': '/Users/runner', 'LANG': 'en_US.UTF-8',
            'RACE_AI_STATE_KEY': 'never-pass', 'GH_TOKEN': 'never-pass', 'GITHUB_TOKEN': 'never-pass',
            'GIT_CONFIG_VALUE_0': 'never-pass', 'HTTPS_PROXY': 'https://secret.invalid'})
        self.assertEqual(result, {'PATH': '/usr/bin', 'HOME': '/Users/runner', 'LANG': 'en_US.UTF-8'})

    def test_browser_guard_blocks_external_fetch_xhr_beacon_and_websocket_before_network(self):
        program = r'''
const vm=require('node:vm'),fs=require('node:fs');let actual=0;
class XHR {open(){actual++}}
const scope={URL,location:{href:'http://127.0.0.1:1234/',origin:'http://127.0.0.1:1234'},
 XMLHttpRequest:XHR,navigator:{},TypeError,Promise,addEventListener(){},
 fetch:async()=>{actual++;return {ok:true}}};scope.window=scope;
vm.createContext(scope);vm.runInContext(fs.readFileSync(0,'utf8'),scope);
(async()=>{
 await scope.fetch('/app.js');
 try{await scope.fetch('https://foreign.invalid/private')}catch{}
 try{await scope.fetch(new URL('https://foreign.invalid/private'))}catch{}
 try{new scope.XMLHttpRequest().open('GET','https://foreign.invalid/private')}catch{}
 scope.navigator.sendBeacon('https://foreign.invalid/private','sensitive');
 try{new scope.WebSocket('wss://foreign.invalid/')}catch{}
 process.stdout.write(JSON.stringify({actual,blocked:scope.__raceSafariPrivacy.external_blocked}));
})().catch(()=>process.exitCode=2);
'''
        result = subprocess.run(['node', '-e', program], input=S.PRIVACY_SCRIPT,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'actual': 1, 'blocked': 5})

    def test_storage_and_location_cannot_hide_keys_or_forecast_payloads(self):
        audit = {'private_view_reads': 1, 'secret_in_request': False, 'non_read_requests': 0,
                 'outbound_requests_permitted': 0}
        snapshot = {'url': 'http://127.0.0.1:1234/#results', 'local': {
            'race-ai-display-v1': '{"budget":10000,"sport":"boat"}'}, 'session': {},
            'cookie': '', 'privacy': {'external_blocked': 1, 'csp_blocked': 0, 'page_errors': 0}}
        S.verify_private_boundary(snapshot, audit, ('fixture-secret',))
        cases = [dict(snapshot, url=snapshot['url'] + 'fixture-secret'),
                 dict(snapshot, cookie='key=fixture-secret'),
                 dict(snapshot, session={'records': 'private forecast'}),
                 dict(snapshot, local={'race-ai-display-v1': '{"forecasts":[1,2,3]}'}),
                 dict(snapshot, privacy={'page_errors': 1})]
        for changed in cases:
            with self.assertRaises(S.SafariHold):
                S.verify_private_boundary(changed, audit, ('fixture-secret',))
        with self.assertRaises(S.SafariHold):
            S.verify_private_boundary(snapshot, dict(audit, secret_in_request=True), ('fixture-secret',))

    def test_failures_emit_only_bounded_public_codes(self):
        raw = RuntimeError('private URL key forecast must never be printed')
        self.assertEqual(S.failure_report(raw), {'status': 'NATIVE_SAFARI_ACCEPTANCE_HOLD',
                                               'reason': 'SAFARI_OPERATION_FAILED'})
        self.assertEqual(S.failure_report(S.SafariHold('MODEL_ORIGINAL_MISMATCH'))['reason'],
                         'MODEL_ORIGINAL_MISMATCH')
        self.assertEqual(S.failure_report(S.SafariHold('private secret'))['reason'],
                         'SAFARI_OPERATION_FAILED')


@contextmanager
def candidate_fixture():
    """A local invented Git checkout exercises the real pin/byte admission."""
    with tempfile.TemporaryDirectory() as name:
        root = Path(name).resolve() / 'checkout'
        web = root / 'web'
        (web / 'data').mkdir(parents=True)
        fixture = {'schema': 'RACE_AI_FORECAST_AUDIT_V1', 'dataset_status': 'SYNTHETIC_ONLY',
            'event_date_jst': '2030-01-01', 'records': [
                {'race_id': ident, 'source_provenance': 'SYNTHETIC_ONLY'} for ident in S.SYNTHETIC_IDS]}
        assets = {'index.html': b'<html><head><script defer src="./app.js"></script></head><body></body></html>',
                  'app.js': b'/* invented public script */', 'style.css': b'body{}',
                  'other.html': b'<html>outside the seven-page capture</html>',
                  'data/other-forecast.json': b'{"records":["never a capture input"]}',
                  S.SYNTHETIC_PATH: json.dumps(fixture).encode()}
        for path, raw in assets.items():
            (web / path).write_bytes(raw)
        def git(*args):
            result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=True)
            return result.stdout.decode().strip()
        git('init', '-q')
        git('add', 'web')
        git('-c', 'user.name=Invented fixture', '-c', 'user.email=fixture@example.invalid',
            '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture')
        with patch.multiple(S, CANDIDATE_SHA=git('rev-parse', 'HEAD'),
                CANDIDATE_WEB_TREE=git('rev-parse', 'HEAD:web'),
                CANDIDATE_ASSET_SHA256={path: hashlib.sha256(assets[path]).hexdigest()
                                      for path in ('index.html', 'app.js', 'style.css')},
                SYNTHETIC_SHA=hashlib.sha256(assets[S.SYNTHETIC_PATH]).hexdigest()):
            yield root, assets, fixture


class CandidateSyntheticTests(unittest.TestCase):
    def test_candidate_pin_is_exact_reviewed_ui_not_a_runtime_or_model_pin(self):
        self.assertEqual(getattr(S, 'CANDIDATE_SHA', None), '598c80c89b5d6a1bca8dbbb16d091ef9e74bfb76')
        self.assertEqual(S.CANDIDATE_WEB_TREE, '23bddbad96d303cdd9699615ecfa6f99f7f82f61')
        self.assertEqual(S.CANDIDATE_ASSET_SHA256, {
            'index.html': '676a3537bb97f5826d2f1e7c01154a488e310a3d18bd25e9c8a50c33d9666c39',
            'app.js': '67742a37a42e46deb2e2de4dd65540f81227bbf8138e7606909e17c6c9104fa6',
            'style.css': 'c2dd9f1841e83b1359517edd2082830504bf5e5a65fe501cf44346ad50d38400'})
        self.assertEqual(S.PAGES_SHA, 'f60308ef7443ca13b5ca23c4896e15ffc67b0427')
        self.assertEqual(S.SOURCE_SHA, 'eff296f6d54ad4be297d93e32f1ee0d4592ad9e3')

    def test_candidate_loader_requires_pinned_clean_git_bytes_and_no_symlinks(self):
        self.assertTrue(callable(getattr(S, 'load_candidate_assets', None)))
        with candidate_fixture() as (root, assets, _):
            self.assertEqual(S.load_candidate_assets(root / 'web'),
                {key: value for key, value in assets.items() if key not in ('other.html', 'data/other-forecast.json')})
            with patch.object(S, 'CANDIDATE_SHA', '0' * 40):
                with self.assertRaises(S.SafariHold):
                    S.load_candidate_assets(root / 'web')
            with patch.object(S, 'CANDIDATE_WEB_TREE', '0' * 40):
                with self.assertRaises(S.SafariHold):
                    S.load_candidate_assets(root / 'web')
            (root / 'web/app.js').write_bytes(b'changed')
            with self.assertRaises(S.SafariHold):
                S.load_candidate_assets(root / 'web')
            (root / 'web/app.js').write_bytes(assets['app.js'])
            (root / 'web/unexpected.json').write_bytes(b'private-sentinel')
            with self.assertRaises(S.SafariHold):
                S.load_candidate_assets(root / 'web')
            (root / 'web/unexpected.json').unlink()
            (root / 'web/app.js').unlink()
            (root / 'web/app.js').symlink_to(root / 'web/style.css')
            with self.assertRaises(S.SafariHold):
                S.load_candidate_assets(root / 'web')

    def test_candidate_fixture_cannot_be_replaced_by_another_synthetic_dataset(self):
        with candidate_fixture() as (root, _, _):
            with patch.object(S, 'SYNTHETIC_SHA', '0' * 64):
                with self.assertRaisesRegex(S.SafariHold, 'SYNTHETIC_FIXTURE_INVALID'):
                    S.load_candidate_assets(root / 'web')

    def test_candidate_plain_index_adapter_only_serves_the_exact_public_fixture(self):
        with candidate_fixture() as (root, assets, fixture):
            loaded = S.load_candidate_assets(root / 'web')
            with S.LoopbackSite(loaded, fixture, synthetic=True, candidate_ui=True) as site:
                with urllib.request.urlopen(site.url, timeout=3) as response:
                    index = response.read()
                    self.assertIn(b'/_acceptance/privacy.js', index)
                    self.assertIn(b'race-ai-private-saved-view', index)
                    self.assertNotIn(b'race-ai-encrypted-saved-view', index)
                with urllib.request.urlopen(site.origin + '/api/forecast/saved', timeout=3) as response:
                    self.assertEqual(json.load(response), fixture)
                for blocked in ('other.html', 'data/other-forecast.json'):
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        urllib.request.urlopen(site.origin + '/' + blocked, timeout=3)
                    denied.exception.close()
            for options in ({'synthetic': False}, {'synthetic': True, 'secrets': ('private-sentinel',)}):
                with self.assertRaises(S.SafariHold):
                    S.LoopbackSite(assets, fixture, candidate_ui=True, **options)
            with self.assertRaises(S.SafariHold):
                S.LoopbackSite(assets, {'records': []}, synthetic=True, candidate_ui=True)
            with self.assertRaises(S.SafariHold):
                S.synthetic_candidate_index(INDEX)

    def test_candidate_mode_never_enters_any_authenticated_or_live_asset_loader(self):
        report = {'schema': 'fixture-only', 'screenshots': []}
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(S.platform, 'system', return_value='Darwin'), \
                patch.object(S, 'load_candidate_assets', return_value={}) as candidate, \
                patch.object(S, 'synthetic_visual_checks', return_value=report) as visual, \
                patch.object(S, 'load_public_assets', side_effect=AssertionError('private path')), \
                patch.object(S, 'verify_live_assets', side_effect=AssertionError('live path')), \
                patch.object(S, 'load_encrypted_seed', side_effect=AssertionError('cipher path')), \
                patch.object(S, 'read_authenticated_view', side_effect=AssertionError('owner path')), \
                redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(S.main(['--public-root', '/candidate/web', '--synthetic-only',
                                     '--candidate-ui', '--output', '/new-output']), 0)
        candidate.assert_called_once_with(Path('/candidate/web'))
        self.assertTrue(visual.call_args.kwargs['candidate_ui'])
        self.assertNotIn('/candidate/', output.getvalue())

    def test_candidate_process_refuses_all_extra_environment_and_private_arguments(self):
        for environment in ({'GH_TOKEN': 'private-sentinel'}, {'RACE_AI_STATE_KEY': 'private-sentinel'},
                            {'RACE_AI_VIEWER_KEY': 'private-sentinel'}, {'OWNER_URL': 'private-sentinel'}):
            output = io.StringIO()
            with self.subTest(environment=tuple(environment)), patch.dict(os.environ, environment, clear=True), \
                    patch.object(S, 'load_candidate_assets') as candidate, redirect_stdout(output), redirect_stderr(output):
                self.assertEqual(S.main(['--public-root', '/candidate/web', '--synthetic-only',
                                         '--candidate-ui', '--output', '/new-output']), 2)
            candidate.assert_not_called()
            self.assertNotIn('sentinel', output.getvalue())
        with patch.dict(os.environ, {}, clear=True), patch.object(S, 'load_candidate_assets') as candidate, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            for extra in ([], ['--synthetic-only', '--source-root', '/private-sentinel']):
                self.assertEqual(S.main(['--public-root', '/candidate/web', '--candidate-ui',
                                         '--output', '/new-output', *extra]), 2)
        candidate.assert_not_called()

    def test_candidate_screenshot_refuses_fragments_and_even_allowed_preference_storage(self):
        class Site:
            synthetic_fixture_sha256 = S.SYNTHETIC_SHA
            seed_path, candidate_ui, origin = None, True, 'http://127.0.0.1:1234'
            audit = {'private_view_reads': 1, 'secret_in_request': False,
                     'non_read_requests': 0, 'outbound_requests_permitted': 0}
        probe = {'origin': Site.origin, 'fragment': '#home', 'verified': True,
                 'fixture_sha256': S.SYNTHETIC_SHA, 'page_errors': 0, 'visible_page': 'page-home',
                 'width': 390, 'overflow': False, 'encrypted': False, 'synthetic_banner': True}
        snapshot = {'url': Site.origin + '/#home', 'local': {}, 'session': {}, 'cookie': '',
                    'privacy': {'page_errors': 0}}
        cases = [(dict(probe, fragment='#saved=' + 'a' * 64 + '.' + 'b' * 43), snapshot),
                 (probe, dict(snapshot, local={'race-ai-display-v1': '{"budget":10000}'})),
                 (probe, dict(snapshot, session={'viewer': 'private-sentinel'}))]
        with tempfile.TemporaryDirectory() as name:
            for first, second in cases:
                driver = unittest.mock.Mock()
                driver.script.side_effect = [first, second]
                with self.assertRaises(S.SafariHold):
                    S.save_synthetic_screenshot(driver, Site(), Path(name), 390, 'home')
                driver.command.assert_not_called()
            self.assertEqual(list(Path(name).iterdir()), [])

    def test_candidate_artifacts_require_exact_context_cleanup_identity_and_false_acceptance(self):
        raw = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name).resolve()
            images = []
            for width in S.VISUAL_WIDTHS:
                for page in S.VISUAL_PAGES:
                    path = folder / (str(width) + '-' + page + '.png');path.write_bytes(raw)
                    images.append({'name': path.name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
            report = {'schema': 'RACE_AI_SYNTHETIC_SAFARI_VISUAL_V2', 'dataset_status': 'SYNTHETIC_ONLY',
                'public_fixture_sha256': S.SYNTHETIC_SHA, 'screenshots': images,
                'candidate_source': S.candidate_identity(), 'synthetic_session_cleanup_verified': True,
                'native_browser': {'browserName': 'Safari', 'platformName': 'macOS', 'browserVersion': '26.1'},
                'real_data_context_used_for_capture': False, 'physical_iphone_verified': False,
                'all_eight_reference_screens_visually_verified': False, 'account_login_verified': False,
                'current_v5_live_continuation_verified': False, 'real_data_verified': False,
                'viewports': [S.require_viewport(w, {'width': w, 'height': 844}) for w in S.VISUAL_WIDTHS]}
            target = folder / 'synthetic-only.json'
            target.write_text(json.dumps(report))
            self.assertEqual(S.verify_synthetic_artifacts(folder, candidate_ui=True)['screenshots'], 28)
            for changed in [dict(report, candidate_source={}), dict(report, synthetic_session_cleanup_verified=False),
                    dict(report, account_login_verified=True), dict(report, current_v5_live_continuation_verified=True),
                    dict(report, real_data_verified=True), dict(report, physical_iphone_verified=True),
                    dict(report, native_browser={'browserName': 'webkit'}),
                    dict(report, viewports=[dict(v, actual_inner_width=500) for v in report['viewports']])]:
                target.write_text(json.dumps(changed))
                with self.assertRaises(S.SafariHold):
                    S.verify_synthetic_artifacts(folder, candidate_ui=True)
            target.write_text(json.dumps(report))
            (folder / 'private.html').write_bytes(b'private-sentinel')
            with self.assertRaises(S.SafariHold):
                S.verify_synthetic_artifacts(folder, candidate_ui=True)

    def test_candidate_report_is_written_only_after_its_fresh_session_closes(self):
        events = []
        class Driver:
            width = 320
            def command(self, method, suffix, body):
                if suffix == '/window/rect':
                    self.width = body['width']
            def wait(self, *args, **kwargs):
                return True
            def click(self, *args):
                pass
            def script(self, source):
                if 'Object.keys(localStorage)' in source:
                    return True
                if 'width:innerWidth' in source:
                    return {'width': self.width, 'height': 844}
        @contextmanager
        def browser():
            events.append('fresh_session')
            yield Driver(), {'browserName': 'Safari', 'platformName': 'macOS', 'browserVersion': '26.1'}
            events.append('closed_session')
        with candidate_fixture() as (root, assets, _), patch.dict(os.environ, {}, clear=True), \
                patch.object(S, 'apple_driver', side_effect=browser), \
                patch.object(S, 'select_saved_day'), patch.object(S, 'click_saved_page'), patch.object(S, 'open_saved_race'), \
                patch.object(S, 'save_synthetic_screenshot', side_effect=lambda d,s,f,w,p:
                    {'name': str(w)+'-'+p+'.png', 'bytes': 0, 'sha256': '0'*64}), \
                patch.object(S, 'verify_synthetic_artifacts') as verify:
            report = S.synthetic_visual_checks(assets, root.parent / 'output', candidate_ui=True)
            self.assertEqual(events, ['fresh_session', 'closed_session'])
            self.assertTrue((root.parent / 'output/synthetic-only.json').is_file())
            self.assertEqual(len(report['screenshots']), 28)
            self.assertEqual(report['candidate_source'], S.candidate_identity())
            self.assertIs(report['synthetic_session_cleanup_verified'], True)
            for key in ('account_login_verified', 'current_v5_live_continuation_verified', 'real_data_verified',
                        'physical_iphone_verified', 'all_eight_reference_screens_visually_verified'):
                self.assertIs(report[key], False)
            verify.assert_called_once_with(root.parent / 'output', candidate_ui=True)

    def test_existing_job_keeps_private_pins_and_captures_candidate_only_after_success(self):
        text = (Path(__file__).resolve().parents[1] / '.github/workflows/boat-owner-formal-live-pages-proof.yml').read_text()
        steps = acceptance_workflow_steps()
        private = next(i for i, step in enumerate(steps) if step.get('name') ==
            'Verify real desktop Safari with authenticated originals and private loopback transport')
        checkout = next(i for i, step in enumerate(steps) if step.get('path') == '.native-safari-ui-candidate')
        self.assertGreater(checkout, private)
        self.assertEqual(steps[checkout]['ref'], S.CANDIDATE_SHA)
        self.assertEqual(steps[checkout]['persist-credentials'], 'false')
        capture = text[text.index('      - name: Capture pinned UI candidate'):text.index('      - name: Retain only verified synthetic')]
        self.assertEqual(capture.count('env -i '), 2)
        self.assertIn('HOME="$HOME"', capture)
        self.assertNotIn('CODEX_HOME', capture)
        self.assertEqual(capture.count('--candidate-ui'), 2)
        self.assertNotIn('always()', capture)
        self.assertNotIn('        env:', capture)
        self.assertNotIn('GH_TOKEN', capture)
        self.assertIn('options: [current-http, native-safari]', text)
        self.assertIn('permissions:\n  contents: read', text)
        self.assertIn('&& 20 || 6', text)
        jobs = text.split('jobs:\n', 1)[1]
        self.assertEqual(len(__import__('re').findall(r'^  [A-Za-z_][A-Za-z_0-9]*:', jobs, __import__('re').M)), 1)
        self.assertIn('path: ${{ runner.temp }}/race-ai-ui-candidate-safari/*.png', text)
        self.assertNotIn('synthetic-only.json\n', text)


class SessionCleanupTests(unittest.TestCase):
    def test_session_close_requires_the_delete_acknowledgement(self):
        driver = S.WebDriver(1234);driver.session = 'invented-session'
        with patch.object(driver, 'command', return_value=None) as command:
            self.assertIs(driver.close(), True)
        command.assert_called_once_with('DELETE', '')
        driver.session = 'invented-session'
        with patch.object(driver, 'command', side_effect=S.DriverHold(operation='delete_session')):
            self.assertIs(driver.close(), False)
        driver.session = 'invented-session'
        with patch.object(driver, 'command', return_value={'unrecognized': 'private-owner-sentinel'}):
            self.assertIs(driver.close(), False)

    def test_failed_session_delete_still_reaps_driver_and_prevents_a_successful_context(self):
        process, driver = unittest.mock.Mock(), unittest.mock.Mock()
        process.poll.return_value = None;driver.close.return_value = False
        driver.new_session.return_value = {'browserName': 'Safari', 'platformName': 'macOS', 'browserVersion': '26.1'}
        with patch.object(S.platform, 'system', return_value='Darwin'), \
                patch.object(S.os.path, 'isfile', return_value=True), patch.object(S.os, 'access', return_value=True), \
                patch.object(S.subprocess, 'Popen', return_value=process), patch.object(S, 'WebDriver', return_value=driver), \
                patch.object(S.socket, 'create_connection'):
            with self.assertRaisesRegex(S.SafariHold, 'SAFARI_SESSION_CLEANUP_FAILED'):
                with S.apple_driver():
                    pass
        process.terminate.assert_called_once();process.wait.assert_called_once()

    def test_unexpected_close_failure_is_private_and_still_reaps_the_driver(self):
        process, driver = unittest.mock.Mock(), unittest.mock.Mock()
        process.poll.return_value = None
        driver.close.side_effect = RuntimeError('private-owner-sentinel')
        with patch.object(S.platform, 'system', return_value='Darwin'), \
                patch.object(S.os.path, 'isfile', return_value=True), patch.object(S.os, 'access', return_value=True), \
                patch.object(S.subprocess, 'Popen', return_value=process), patch.object(S, 'WebDriver', return_value=driver), \
                patch.object(S.socket, 'create_connection'):
            with self.assertRaisesRegex(S.SafariHold, 'SAFARI_SESSION_CLEANUP_FAILED'):
                with S.apple_driver():
                    pass
        process.terminate.assert_called_once();process.wait.assert_called_once()

    def test_private_cleanup_failure_cannot_report_success_or_start_capture(self):
        @contextmanager
        def failing_driver():
            yield object(), {}
            raise S.SafariHold('SAFARI_SESSION_CLEANUP_FAILED')
        @contextmanager
        def site(*args, **kwargs):
            yield object()
        output = io.StringIO()
        with patch.object(S.platform, 'system', return_value='Darwin'), \
                patch.object(S, 'load_public_assets', return_value={}), patch.object(S, 'verify_live_assets'), \
                patch.object(S, 'load_encrypted_seed'), patch.object(S, 'read_authenticated_view',
                    return_value=({}, {}, {'key': 'private-owner-sentinel'})), \
                patch.object(S, 'LoopbackSite', side_effect=site), patch.object(S, 'apple_driver', side_effect=failing_driver), \
                patch.object(S, 'app_checks'), patch.object(S, 'encrypted_seed_checks') as encrypted, \
                patch.object(S, 'synthetic_visual_checks') as visual, redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(S.main(['--public-root', '/public', '--source-root', '/reader']), 2)
        encrypted.assert_not_called();visual.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['reason'], 'SAFARI_SESSION_CLEANUP_FAILED')
        self.assertNotIn('sentinel', output.getvalue())


class SafeClickDiagnosticTests(unittest.TestCase):
    def driver(self, document):
        driver = S.WebDriver(1234)
        driver.session = 'invented-session'
        raw = document if isinstance(document, bytes) else json.dumps(document).encode()
        error = urllib.error.HTTPError('http://127.0.0.1:1234/invented', 400, 'invented', {}, io.BytesIO(raw))
        return driver, error

    def test_standard_invalid_element_state_is_recovered_without_its_private_message(self):
        driver, remote = self.driver({'value': {'error': 'invalid element state',
            'message': 'private-sentinel https://private.invalid/', 'stacktrace': 'private-sentinel'}})
        with patch.object(driver.opener, 'open', side_effect=remote):
            with self.assertRaises(S.DriverHold) as caught:
                driver.command('POST', '/element/invented-option/click', {})
        report = S.failure_report(caught.exception)
        self.assertEqual(report['webdriver_error_code'], 'invalid element state')
        self.assertEqual(report['webdriver_http_status'], 400)
        self.assertNotIn('sentinel', json.dumps(report))
        self.assertNotIn('https:', json.dumps(report))

    def test_error_only_projection_tolerates_metadata_but_success_schema_stays_strict(self):
        document = {'value': {'error': 'invalid argument', 'message': 'private-sentinel'},
                    'sessionId': 'private-sentinel', 'vendor': {'private-sentinel': [1, 2]}}
        raw = json.dumps(document).encode()
        driver, remote = self.driver(raw)
        with patch.object(driver.opener, 'open', side_effect=remote):
            with self.assertRaises(S.DriverHold) as caught:
                driver.command('POST', '/element/invented-option/click', {})
        report = S.failure_report(caught.exception)
        self.assertEqual(report['webdriver_error_code'], 'invalid argument')
        self.assertNotIn('sentinel', json.dumps(report))
        with self.assertRaises(ValueError):
            S.driver_value(raw, S.DRIVER_RESPONSE_LIMIT)
        # The same body in a200 response remains a command failure; it cannot
        # become a session or successful result through the error projection.
        with driver_endpoint({}, session_reply=raw) as (port, _):
            actual = S.WebDriver(port)
            with self.assertRaises(S.DriverHold):
                actual.new_session()
            self.assertIsNone(actual.session)

    def test_error_projection_rejects_malformed_duplicate_nonfinite_and_oversized_json(self):
        bodies = [b'{', b'{"value":{"error":"unknown error","error":"invalid argument"}}',
            b'{"value":{"error":"unknown error"},"private":{"n":NaN}}',
            b'{"value":{"error":"unknown error"},"private":{"n":1e9999}}',
            b'{"value":{"error":"unknown error"},"private":{"a":1,"a":2}}',
            b'{"error":"unknown error","message":"private-sentinel"}',
            b'{"value":{"error":"private-sentinel"}}',
            b'{"value":{"error":"unknown error"},"private":"' + b'x' * S.DRIVER_ERROR_LIMIT + b'"}']
        for body in bodies:
            with self.subTest(size=len(body)):
                driver, remote = self.driver(body)
                with patch.object(driver.opener, 'open', side_effect=remote):
                    with self.assertRaises(S.DriverHold) as caught:
                        driver.command('POST', '/element/invented-option/click', {})
                report = S.failure_report(caught.exception)
                self.assertIsNone(report['webdriver_error_code'])
                self.assertNotIn('sentinel', json.dumps(report))

    def test_native_option_failure_retains_public_callers_and_fixed_context_only(self):
        driver, remote = self.driver({'value': {'error': 'invalid element state', 'message': 'private-sentinel'}})
        S.ui_diagnostic(driver, 'latest_p1_private_transport', 'select_native_history', 1440)
        # Isolate the option HTTP failure; parent preparation and preconditions
        # have their own native-action fixture below.
        prepared = {'control_in_view': True, 'hit_target': True, 'focused': True}
        with patch.object(driver, 'element', return_value='invented-option'), \
                patch.object(driver.opener, 'open', side_effect=remote) as request, \
                patch.object(driver, '_select_probe', return_value=('invented-select', prepared)), \
                patch.object(driver, '_click_visible_element'), \
                patch.object(driver, 'script', side_effect=AssertionError('no native option rectangle')):
            try:
                driver.select('#private-sentinel', 'private-sentinel')
            except S.DriverHold as error:
                report = S.failure_report(error)
            else:
                self.fail('the HTTP400 command must fail')
        self.assertEqual([frame['function'] for frame in report['checker_callers']], ['select', 'click', 'command', 'call'])
        self.assertEqual(report['ui_stage'], 'latest_p1_private_transport')
        self.assertEqual(report['ui_action'], 'select_native_history')
        self.assertEqual(report['ui_verified_width'], 1440)
        self.assertEqual(report['ui_click_path'], 'native_option')
        self.assertIs(report['ui_hit_target_verified'], False)
        self.assertNotIn('sentinel', json.dumps(report))
        self.assertEqual(request.call_count, 1, 'diagnosis cannot retry the failed action')

    def test_visible_click_failure_records_existing_hit_check_without_new_browser_actions(self):
        driver, remote = self.driver({'value': {'error': 'invalid argument'}})
        S.ui_diagnostic(driver, 'latest_p1_private_transport', 'open_native_race', 390)
        with patch.object(driver, 'element', return_value='invented-button'), \
                patch.object(driver, 'script', return_value=None) as script, patch.object(driver, 'wait', return_value=True) as wait, \
                patch.object(driver.opener, 'open', side_effect=remote) as request:
            with self.assertRaises(S.DriverHold) as caught:
                driver.click('#private-sentinel')
        report = S.failure_report(caught.exception)
        self.assertEqual(report['ui_click_path'], 'visible_element')
        self.assertIs(report['ui_hit_target_verified'], True)
        self.assertEqual(report['ui_verified_width'], 390)
        self.assertEqual((script.call_count, wait.call_count, request.call_count), (1, 1, 1))
        self.assertNotIn('sentinel', json.dumps(report))

    def test_private_transport_assigns_the_stage_and_verified_width_at_the_action(self):
        driver, remote = self.driver({'value': {'error': 'invalid argument', 'message': 'private-sentinel'}})
        command = driver.command
        def response(method, suffix, body=None):
            return command(method, suffix, body) if suffix.endswith('/click') else None
        def script(source, *args):
            return {'width': 1440, 'height': 1000} if 'width:innerWidth' in source else None
        with patch.object(driver, 'command', side_effect=response), patch.object(driver, 'script', side_effect=script), \
                patch.object(driver, 'wait', return_value=True), patch.object(driver, 'element', return_value='invented-button'), \
                patch.object(S, 'select_saved_day'), patch.object(S, 'open_saved_race', side_effect=lambda d,r:d.click('#private-sentinel')), \
                patch.object(driver.opener, 'open', side_effect=remote):
            try:
                S.app_checks(driver, type('Site', (), {'url': 'http://127.0.0.1:1234/'})(), context_fixture(), ())
            except S.DriverHold as error:
                report = S.failure_report(error)
            else:
                self.fail('the HTTP400 command must fail')
        self.assertEqual(report['ui_stage'], 'latest_p1_private_transport')
        self.assertEqual(report['ui_action'], 'open_native_race')
        self.assertEqual(report['ui_verified_width'], 1440)
        self.assertIn('app_checks', [frame['function'] for frame in report['checker_callers']])
        self.assertNotIn('sentinel', json.dumps(report))

    def test_spoofed_context_and_unknown_fields_are_filtered_before_reporting(self):
        error = S.DriverHold(operation='element_click', http_status=400)
        error.ui_context = {'stage': 'private-sentinel', 'action': 'private-sentinel', 'width': True,
                            'click_path': 'private-sentinel', 'hit_target_verified': 'private-sentinel',
                            'selector': '#private-sentinel', 'value': 'private-sentinel'}
        report = S.failure_report(error)
        self.assertIsNone(report['ui_stage']);self.assertIsNone(report['ui_action'])
        self.assertIsNone(report['ui_verified_width']);self.assertIsNone(report['ui_click_path'])
        self.assertIs(report['ui_hit_target_verified'], False)
        self.assertNotIn('sentinel', json.dumps(report))

    def test_trusted_caller_stack_is_bounded_and_external_names_cannot_spoof_it(self):
        namespace = {'S': S}
        exec(compile('def select(n):\n if n: return select(n-1)\n raise S.DriverHold(operation="element_click")\n',
                     S.__file__, 'exec'), namespace)
        try:
            namespace['select'](40)
        except S.DriverHold as error:
            report = S.failure_report(error)
        self.assertEqual(len(report['checker_callers']), 12)
        self.assertTrue(all(frame['function'] == 'select' and type(frame['line']) is int and
                            1 <= frame['line'] <= 99999 for frame in report['checker_callers']))
        other = {'S': S}
        exec(compile('def select():\n raise S.DriverHold(operation="element_click")\n',
                     '/private-sentinel/select.py', 'exec'), other)
        try:
            other['select']()
        except S.DriverHold as error:
            external = S.failure_report(error)
        self.assertNotIn('checker_callers', external)
        self.assertNotIn('private-sentinel', json.dumps(external))


class NativeSelectFixture:
    """Standard interactability fixture using measured public f603 geometry.

    The b496 fixture's parent is892.69–938.69 at1440×1000, but995.58–1041.58
    at390×1000. Closed options have no rectangle at either width. This models
    the checker precondition gap, not a claim about the private Safari error.
    """
    def __init__(self, width=390, selected=False):
        self.driver = S.WebDriver(1234);self.driver.session = 'invented-session'
        self.width, self.selected = width, selected
        self.in_view, self.focused, self.hit = width == 1440, False, width == 1440
        self.control_id, self.calls, self.probes = 'invented-select', [], 0
        self.override, self.after_parent, self.option_error = {}, None, None
        self.after_option = None
        self.malformed = None

    def snapshot(self):
        self.probes += 1
        if self.malformed is not None:
            return self.malformed
        return {'control': {'element-6066-11e4-a52e-4f735466cecf': self.control_id},
            'control_count': 1, 'option_count': 3, 'target_count': 1,
            'control_is_select': True, 'control_connected': True, 'control_enabled': True,
            'control_visible': True, 'target_connected': True, 'target_enabled': True, 'target_visible': True,
            'selected_target': self.selected, 'control_in_view': self.in_view,
            'hit_target': self.hit, 'focused': self.focused, **self.override}

    def element(self, selector, visible=True):
        if ' option[' in selector:
            assert visible is False
            return 'invented-option'
        assert visible is True
        return self.control_id

    def script(self, source, *args):
        if 'native-select-preflight' in source:
            return self.snapshot()
        if 'scrollIntoView' in source:
            self.in_view = self.hit = True
            return None
        raise AssertionError('selection must use read-only preflight and existing native preparation')

    def wait(self, source, *args, **kwargs):
        if 'elementFromPoint' in source:
            if self.in_view and self.hit:
                return True
            raise S.AppHold({})
        if '?.value===arguments[1]' in source:
            if self.selected:
                return True
            raise S.AppHold({})
        raise AssertionError('unexpected selection wait')

    def command(self, method, suffix, body=None):
        assert method == 'POST' and body == {}
        if suffix == '/element/invented-select/click':
            self.calls.append('parent_click')
            assert self.in_view and self.hit
            self.focused = True
            if self.after_parent:
                self.after_parent(self)
            return None
        assert suffix == '/element/invented-option/click'
        self.calls.append('option_click')
        if not self.in_view or self.option_error:
            raise self.driver._diagnostic_error(S.DriverHold(operation='element_click', http_status=400))
        self.selected = True
        if self.after_option:
            self.after_option(self)

    @contextmanager
    def installed(self):
        with patch.object(self.driver, 'element', side_effect=self.element), \
                patch.object(self.driver, 'script', side_effect=self.script), \
                patch.object(self.driver, 'wait', side_effect=self.wait), \
                patch.object(self.driver, 'command', side_effect=self.command):
            yield self.driver


class NativeSelectPreparationTests(unittest.TestCase):
    def test_fixture_reproduces_the_unprepared_desktop_mobile_difference(self):
        for width in (1440, 390):
            fixture = NativeSelectFixture(width)
            with fixture.installed() as driver:
                if width == 1440:
                    driver.click('#prediction-select option[value="0"]', visible=False)
                    self.assertTrue(fixture.selected)
                else:
                    with self.assertRaises(S.DriverHold):
                        driver.click('#prediction-select option[value="0"]', visible=False)

    def test_selection_prepares_parent_and_keeps_requested_option_click_even_if_already_selected(self):
        for width in (1440, 390):
            for selected in (False, True):
                with self.subTest(width=width, selected=selected):
                    fixture = NativeSelectFixture(width, selected)
                    with fixture.installed() as driver:
                        driver.select('#prediction-select', '0')
                    self.assertEqual(fixture.calls, ['parent_click', 'option_click'])
                    self.assertTrue(fixture.selected)
                    self.assertGreaterEqual(fixture.probes, 3)

    def test_missing_ambiguous_hidden_disabled_or_disconnected_target_holds_before_clicks(self):
        cases = [{'control_count': 0}, {'control_count': 2}, {'control_is_select': False},
            {'control_connected': False}, {'control_enabled': False}, {'control_visible': False},
            {'target_count': 0}, {'target_count': 2}, {'target_connected': False}, {'target_enabled': False}, {'target_visible': False},
            {'target_count': True}, {'option_count': -1}]
        for changed in cases:
            with self.subTest(changed=tuple(changed)):
                fixture = NativeSelectFixture();fixture.override = changed
                with fixture.installed() as driver, self.assertRaises(S.SafariHold):
                    driver.select('#prediction-select', '0')
                self.assertEqual(fixture.calls, [])
        for malformed in ([], {}, {'private': 'private-sentinel'}):
            fixture = NativeSelectFixture();fixture.malformed = malformed
            with fixture.installed() as driver, self.assertRaises(S.SafariHold):
                driver.select('#prediction-select', '0')
            self.assertEqual(fixture.calls, [])

    def test_stale_unfocused_or_occluded_parent_holds_before_option_click(self):
        def stale(f):
            f.control_id = 'replacement-select'
        def unfocused(f):
            f.focused = False
        def occluded(f):
            f.hit = False
        for change in (stale, unfocused, occluded):
            fixture = NativeSelectFixture();fixture.after_parent = change
            with fixture.installed() as driver, self.assertRaises(S.SafariHold):
                driver.select('#prediction-select', '0')
            self.assertEqual(fixture.calls, ['parent_click'])

    def test_native_option_failure_is_fatal_once_with_only_safe_preflight_diagnostics(self):
        fixture = NativeSelectFixture();fixture.option_error = True
        with fixture.installed() as driver:
            S.ui_diagnostic(driver, 'latest_p1_private_transport', 'select_native_history', 390)
            try:
                driver.select('#prediction-select', '0')
            except S.DriverHold as error:
                report = S.failure_report(error)
            else:
                self.fail('native failure cannot be retried or waived')
        self.assertEqual(fixture.calls, ['parent_click', 'option_click'])
        self.assertEqual(report['ui_select_phase'], 'prepared')
        self.assertTrue(report['ui_select_preflight']['control_in_view'])
        self.assertTrue(report['ui_select_preflight']['focused'])
        self.assertTrue(report['ui_select_preflight']['same_control'])
        self.assertNotIn('invented-', json.dumps(report))

    def test_readback_cannot_be_waived_and_normal_change_rerender_is_allowed(self):
        fixture = NativeSelectFixture()
        fixture.after_option = lambda f:setattr(f, 'selected', False)
        with fixture.installed() as driver, self.assertRaises(S.SafariHold):
            driver.select('#prediction-select', '0')
        self.assertEqual(fixture.calls, ['parent_click', 'option_click'])
        rerender = NativeSelectFixture()
        rerender.after_option = lambda f:setattr(f, 'control_id', 'new-select-after-change')
        with rerender.installed() as driver:
            driver.select('#prediction-select', '0')
        self.assertEqual(rerender.calls, ['parent_click', 'option_click'])
        self.assertTrue(rerender.selected)

    def test_preflight_diagnostics_cannot_export_references_values_or_unknown_fields(self):
        error = S.SelectHold({'control': {'element-6066-11e4-a52e-4f735466cecf': 'private-sentinel'},
            'value': 'private-sentinel', 'selector': 'private-sentinel', 'option_count': True,
            'target_count': 10001, 'target_enabled': 'private-sentinel'})
        error.ui_context = {'select_phase': 'initial'}
        report = S.failure_report(error)
        self.assertNotIn('sentinel', json.dumps(report))
        self.assertIsNone(report['ui_select_preflight']['option_count'])
        self.assertIsNone(report['ui_select_preflight']['target_count'])


class ApiSyntheticEnvironmentRegressionTests(unittest.TestCase):
    """API recovery keeps the original native suite and checks private boundaries."""
    def test_all_original_allowed_environment_subsets_still_pass(self):
        allowed = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR')
        self.assertEqual(S.SYNTHETIC_ENVIRONMENT_KEYS, frozenset(allowed))
        for bits in range(1 << len(allowed)):
            environment = {key: 'public-os-value' for i, key in enumerate(allowed) if bits & (1 << i)}
            with self.subTest(bits=bits), patch.dict(os.environ, environment, clear=True):
                self.assertIsNone(S.require_synthetic_environment())

    def test_unknown_and_credential_keys_refuse_even_with_empty_values(self):
        sentinel = 'https://owner-private-sentinel.invalid/secret'
        for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'RACE_AI_STATE_KEY', 'UNLISTED_VIEWER_CAPABILITY'):
            for value in ('', sentinel):
                with self.subTest(key=key, empty=value == ''), patch.dict(os.environ, {key:value}, clear=True):
                    with self.assertRaises(S.SyntheticEnvironmentHold) as caught:
                        S.require_synthetic_environment()
                    report = S.failure_report(caught.exception)
                    self.assertEqual(report['unexpected_environment_key_count'], 1)
                    self.assertNotIn(key, json.dumps(report))
                    self.assertNotIn(sentinel, json.dumps(report))

    def test_known_os_presence_never_grants_permission_or_exposes_values(self):
        sentinel = 'private-os-value-sentinel'
        for key in S.SYNTHETIC_OS_ENVIRONMENT_KEYS:
            with self.subTest(key=key), patch.dict(os.environ, {'PATH':'public', key:sentinel}, clear=True):
                with self.assertRaises(S.SyntheticEnvironmentHold) as caught:
                    S.require_synthetic_environment()
                report = S.failure_report(caught.exception)
                self.assertEqual(report['reason'], 'SYNTHETIC_SCREENSHOT_REJECTED')
                self.assertEqual(report['environment_phase'], 'synthetic_environment_guard')
                self.assertEqual(report['unexpected_environment_key_count'], 1)
                flags = report['known_os_environment_key_present']
                self.assertEqual(set(flags), set(S.SYNTHETIC_OS_ENVIRONMENT_KEYS))
                self.assertTrue(flags[key])
                self.assertTrue(all(type(value) is bool for value in flags.values()))
                self.assertNotIn(sentinel, json.dumps(report))

    def test_report_counts_are_strict_bounded_integers(self):
        for value in (True, False, -1, 10001, 1.0, '1', None):
            with self.subTest(value=value):
                report = S.failure_report(S.SyntheticEnvironmentHold(value, {}))
                self.assertIsNone(report['unexpected_environment_key_count'])
        for value in (0, 1, 10000):
            report = S.failure_report(S.SyntheticEnvironmentHold(value, {}))
            self.assertEqual(report['unexpected_environment_key_count'], value)
        report = S.failure_report(S.SyntheticEnvironmentHold(1,
            {key:'private-flag-sentinel' for key in S.SYNTHETIC_OS_ENVIRONMENT_KEYS} |
            {'UNLISTED_PRIVATE_NAME':'private-flag-sentinel'}))
        self.assertNotIn('sentinel', json.dumps(report))
        self.assertNotIn('UNLISTED_PRIVATE_NAME', json.dumps(report))
        self.assertTrue(all(value is None for value in report['known_os_environment_key_present'].values()))

    def test_hostile_diagnostic_objects_are_not_coerced(self):
        class HostileInt(int):
            def __int__(self):
                raise AssertionError('private int must not be coerced')
            def __str__(self):
                raise AssertionError('private int must not be printed')
        class HostileFlags(dict):
            def get(self, *args):
                raise AssertionError('untrusted mapping must not be queried')
        report = S.failure_report(S.SyntheticEnvironmentHold(HostileInt(1), HostileFlags()))
        self.assertIsNone(report['unexpected_environment_key_count'])
        self.assertTrue(all(value is None for value in report['known_os_environment_key_present'].values()))

    def test_candidate_unknown_environment_stops_before_assets_or_browser(self):
        output = io.StringIO()
        with patch.dict(os.environ, {'UNLISTED_PRIVATE_NAME':'private-value-sentinel'}, clear=True), \
             patch.object(S, 'load_candidate_assets', side_effect=AssertionError('asset access forbidden')), \
             patch.object(S, 'apple_driver', side_effect=AssertionError('browser start forbidden')), \
             redirect_stdout(output):
            code = S.main(['--candidate-ui', '--synthetic-only', '--public-root', '/not-read',
                           '--output', '/not-created'])
        self.assertEqual(code, 2)
        report = json.loads(output.getvalue())
        self.assertEqual(report['status'], 'NATIVE_SAFARI_ACCEPTANCE_HOLD')
        self.assertEqual(report['reason'], 'SYNTHETIC_SCREENSHOT_REJECTED')
        self.assertEqual(report['unexpected_environment_key_count'], 1)
        self.assertNotIn('UNLISTED_PRIVATE_NAME', output.getvalue())
        self.assertNotIn('private-value-sentinel', output.getvalue())


class SyntheticEnvironmentDiagnosticTests(unittest.TestCase):
    ALLOWED = frozenset(('PATH', 'HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR'))
    KNOWN_OS = ('__CF_USER_TEXT_ENCODING', '__CFBundleIdentifier', '__PYVENV_LAUNCHER__',
                'VERSIONER_PYTHON_VERSION', 'VERSIONER_PYTHON_PREFER_32_BIT', 'PYTHONEXECUTABLE')

    def test_original_six_key_allowlist_and_all_subsets_still_pass_unchanged(self):
        self.assertEqual(S.SYNTHETIC_ENVIRONMENT_KEYS, self.ALLOWED)
        keys = sorted(self.ALLOWED)
        for bits in range(1 << len(keys)):
            environment = {key: 'invented-original-os-value' for i, key in enumerate(keys) if bits & (1 << i)}
            with patch.dict(os.environ, environment, clear=True):
                S.require_synthetic_environment()
                self.assertEqual(dict(os.environ), environment)

    def test_known_os_startup_keys_remain_refused_and_only_presence_is_reported(self):
        self.assertEqual(S.SYNTHETIC_OS_ENVIRONMENT_KEYS, self.KNOWN_OS)
        for key in self.KNOWN_OS:
            environment = {'HOME': '/invented-private-path', key: 'private-sentinel-value'}
            with self.subTest(key=key), patch.dict(os.environ, environment, clear=True):
                try:
                    S.require_synthetic_environment()
                except S.SafariHold as error:
                    report = S.failure_report(error)
                else:
                    self.fail('OS startup keys must not be allowed by diagnostic work')
                self.assertEqual(dict(os.environ), environment)
            self.assertEqual(report['reason'], 'SYNTHETIC_SCREENSHOT_REJECTED')
            self.assertEqual(report['environment_phase'], 'synthetic_environment_guard')
            self.assertEqual(report['unexpected_environment_key_count'], 1)
            self.assertIs(type(report['unexpected_environment_key_count']), int)
            self.assertEqual(report['known_os_environment_key_present'], {name: name == key for name in self.KNOWN_OS})
            self.assertNotIn('private-sentinel', json.dumps(report))
            self.assertNotIn('/invented-private-path', json.dumps(report))

    def test_unknown_names_and_credentials_are_counted_without_exporting_names_or_values(self):
        environments = [
            {'GH_TOKEN': 'private-sentinel', 'RACE_AI_STATE_KEY': 'private-sentinel'},
            {'PRIVATE_SENTINEL_UNKNOWN_NAME': 'private-sentinel', '__CF_USER_TEXT_ENCODING': ''},
            {'RACE_AI_VIEWER_KEY': '', 'GIT_CONFIG_VALUE_0': 'private-sentinel', 'OWNER_PRIVATE_URL': 'private-sentinel'}]
        for environment in environments:
            with patch.dict(os.environ, environment, clear=True):
                try:
                    S.require_synthetic_environment()
                except S.SafariHold as error:
                    report = S.failure_report(error)
                else:
                    self.fail('every unexpected key, including empty credentials, must HOLD')
                self.assertEqual(dict(os.environ), environment)
            self.assertEqual(report['unexpected_environment_key_count'], len(environment))
            rendered = json.dumps(report)
            for name, value in environment.items():
                if name not in self.KNOWN_OS:
                    self.assertNotIn(name, rendered)
                if value:
                    self.assertNotIn(value, rendered)
            self.assertEqual(report['known_os_environment_key_present'],
                             {name: name in environment for name in self.KNOWN_OS})

    def test_spoofed_count_flags_phase_and_extra_fields_cannot_escape_the_report(self):
        for count in (True, -1, 10001, 1.5, 'private-sentinel', None):
            error = S.SyntheticEnvironmentHold(1, {name: False for name in self.KNOWN_OS})
            error.unexpected_count = count
            error.known_os_keys = {name: 'private-sentinel' for name in self.KNOWN_OS}
            error.known_os_keys['PRIVATE_SENTINEL_UNKNOWN_NAME'] = 'private-sentinel'
            error.phase = 'private-sentinel'
            report = S.failure_report(error)
            self.assertIsNone(report['unexpected_environment_key_count'])
            self.assertEqual(report['known_os_environment_key_present'], {name: None for name in self.KNOWN_OS})
            self.assertEqual(report['environment_phase'], 'synthetic_environment_guard')
            self.assertNotIn('sentinel', json.dumps(report))
        for count in (0, 1, 10000):
            error = S.SyntheticEnvironmentHold(count, [])
            report = S.failure_report(error)
            self.assertEqual(report['unexpected_environment_key_count'], count)
            self.assertEqual(report['known_os_environment_key_present'], {name: None for name in self.KNOWN_OS})

    def test_main_guard_holds_before_assets_browser_or_artifact_operations_in_both_modes(self):
        commands = [
            ['--public-root', '/private-sentinel/web', '--synthetic-only', '--candidate-ui', '--output', '/private-sentinel/output'],
            ['--public-root', '/private-sentinel/web', '--candidate-ui', '--verify-synthetic-artifacts', '/private-sentinel/output']]
        for arguments in commands:
            output = io.StringIO()
            with patch.dict(os.environ, {'PRIVATE_SENTINEL_UNKNOWN_NAME': 'private-sentinel'}, clear=True), \
                    patch.object(S, 'load_candidate_assets') as assets, \
                    patch.object(S, 'synthetic_visual_checks') as capture, \
                    patch.object(S, 'verify_synthetic_artifacts') as artifacts, \
                    patch.object(S, 'apple_driver') as driver, \
                    patch.object(S, 'read_authenticated_view') as private, \
                    redirect_stdout(output), redirect_stderr(output):
                self.assertEqual(S.main(arguments), 2)
            for operation in (assets, capture, artifacts, driver, private):
                operation.assert_not_called()
            report = json.loads(output.getvalue())
            self.assertEqual(report['unexpected_environment_key_count'], 1)
            self.assertEqual(report['checker_function'], 'require_synthetic_environment')
            self.assertEqual([f['function'] for f in report['checker_callers']], ['main', 'require_synthetic_environment'])
            self.assertNotIn('sentinel', output.getvalue())

    def test_second_guard_precedes_output_folder_or_loopback_session(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name) / 'must-not-exist'
            with patch.dict(os.environ, {'PRIVATE_SENTINEL_UNKNOWN_NAME': ''}, clear=True), \
                    patch.object(S, 'LoopbackSite') as site, patch.object(S, 'apple_driver') as driver:
                try:
                    S.synthetic_visual_checks({}, output, candidate_ui=True)
                except S.SafariHold as error:
                    report = S.failure_report(error)
                else:
                    self.fail('second environment check must refuse unexpected keys')
            self.assertEqual(report['unexpected_environment_key_count'], 1)
            self.assertFalse(output.exists())
            site.assert_not_called();driver.assert_not_called()


if __name__ == '__main__':
    unittest.main()
