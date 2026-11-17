"""Invented inputs exercise the Safari adapter's privacy and identity boundaries."""
import copy
import hashlib
import io
import json
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
def driver_endpoint(capabilities):
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
                status = 200
            else:
                value = {'error': 'unknown error', 'message': 'fixture-secret-private-driver-error'}
                status = 500
            raw = json.dumps({'value': value}).encode()
            self.send_response(status)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

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


if __name__ == '__main__':
    unittest.main()
