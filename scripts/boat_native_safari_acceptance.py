"""Manual, source-free desktop Safari proof using existing authenticated saved views.

Application assets are verified against the deployed Pages manifest. Only the
HTML transport is changed to the app's existing private saved-view endpoint.
Keys remain in Python; Safari sees no owner link, token or encryption key.
"""
import argparse
import base64
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import mimetypes
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request


PAGES_SHA = 'f60308ef7443ca13b5ca23c4896e15ffc67b0427'
SOURCE_SHA = 'eff296f6d54ad4be297d93e32f1ee0d4592ad9e3'
CSP = ("default-src 'none';script-src 'self';style-src 'self';"
       "img-src 'self' data:;connect-src 'self';font-src 'none';"
       "form-action 'none';object-src 'none';base-uri 'none';frame-src 'none'")
MAX_ASSET = 16 * 1024 * 1024
REASONS = frozenset('''ASSET_HASH_MISMATCH ASSET_FILE_REJECTED ASSET_PATH_REJECTED
ASSET_MANIFEST_INVALID ASSET_INDEX_INVALID LIVE_PAGES_BYTES_DIFFER NATIVE_MACOS_REQUIRED
SAFARIDRIVER_REQUIRED SAFARIDRIVER_UNAVAILABLE SAFARI_CAPABILITIES_INVALID
SAFARI_WEBDRIVER_FAILED SAFARI_OPERATION_FAILED SAVED_CONTEXT_INVALID
MODEL_ORIGINAL_MISMATCH PRIVATE_NETWORK_BOUNDARY_FAILED SAVED_VIEW_UNAVAILABLE
APP_UI_CHECK_FAILED SOURCE_REVISION_MISMATCH VIEWPORT_INVALID'''.split())


class SafariHold(ValueError):
    """A fixed public failure code, never a driver error or private value."""


def need(value, reason):
    if not value:
        raise SafariHold(reason)


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def failure_report(error):
    reason = str(error) if isinstance(error, SafariHold) and str(error) in REASONS else 'SAFARI_OPERATION_FAILED'
    report={'status': 'NATIVE_SAFARI_ACCEPTANCE_HOLD', 'reason': reason}
    # A public checker line identifies the failing boundary without exporting
    # driver messages, DOM text, source records, owner URLs or credentials.
    for frame in traceback.extract_tb(error.__traceback__):
        if Path(frame.filename).resolve()==Path(__file__).resolve() and frame.name in {
            'main','read_authenticated_view','app_checks','open_race','select_day','click_page',
            'verify_model_choice','verify_private_boundary','load_public_assets','verify_live_assets'}:
            report.update(checker_function=frame.name,checker_line=frame.lineno)
    return report


def driver_environment(environment):
    return {key: environment[key] for key in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR')
            if key in environment}


def native_identity(capabilities):
    need(isinstance(capabilities, dict), 'SAFARI_CAPABILITIES_INVALID')
    browser, version, system = (capabilities.get(k) for k in ('browserName', 'browserVersion', 'platformName'))
    need(browser == 'Safari' and system == 'macOS' and isinstance(version, str)
         and re.fullmatch(r'[0-9][0-9A-Za-z.() _-]{0,63}', version), 'SAFARI_CAPABILITIES_INVALID')
    return {'browserName': browser, 'browserVersion': version, 'platformName': system}


def viewport_evidence(requested, actual):
    need(type(requested) is int and 320 <= requested <= 1920 and isinstance(actual, dict)
         and all(type(actual.get(k)) is int and 200 <= actual[k] <= 4096 for k in ('width', 'height')),
         'VIEWPORT_INVALID')
    return {'requested_width': requested, 'actual_inner_width': actual['width'],
            'actual_inner_height': actual['height'], 'requested_width_verified': actual['width'] == requested,
            'physical_iphone_verified': False}


def validate_context(context):
    need(isinstance(context, dict) and context.get('schema') == 'RACE_AI_PRIVATE_LIVE_SITE_CHECK_CONTEXT_V1'
         and context.get('stage') == 'P1', 'SAVED_CONTEXT_INVALID')
    for name in ('generation', 'minimum_results', 'day_races', 'native_group_count'):
        need(type(context.get(name)) is int and context[name] > 0, 'SAVED_CONTEXT_INVALID')
    need(context['day_races'] <= 288 and re.fullmatch(r'\d{4}-\d{2}-\d{2}', context.get('day', ''))
         and context['day'] <= context.get('current_day', ''), 'SAVED_CONTEXT_INVALID')
    probe = context.get('model_switch_probe')
    need(isinstance(probe, dict) and re.fullmatch(r'\d{8}-\d{2}-\d{2}', probe.get('race_id', ''))
         and probe['race_id'][:8] == context['day'].replace('-', '')
         and isinstance(probe.get('choices'), list) and len(probe['choices']) == 2, 'SAVED_CONTEXT_INVALID')
    for choice in probe['choices']:
        need(isinstance(choice, dict) and isinstance(choice.get('model_id'), str)
             and 0 < len(choice['model_id']) <= 256 and type(choice.get('index')) is int
             and 0 <= choice['index'] < 32768 and re.fullmatch('[a-f0-9]{64}', choice.get('tickets_sha256', '')),
             'SAVED_CONTEXT_INVALID')
    need(probe['choices'][0]['model_id'] != probe['choices'][1]['model_id'], 'SAVED_CONTEXT_INVALID')
    return {key: context[key] for key in ('schema', 'day', 'current_day', 'stage', 'generation',
            'minimum_results', 'day_races', 'native_group_count', 'native_groups', 'native_probe', 'model_switch_probe')}


def verify_model_choice(choice, detail):
    need(isinstance(detail, dict) and detail.get('model_id') == choice['model_id']
         and detail.get('index') == str(choice['index']) and isinstance(detail.get('tickets'), list)
         and sha(wire(detail['tickets']).encode()) == choice['tickets_sha256'], 'MODEL_ORIGINAL_MISMATCH')


def verify_private_boundary(snapshot, audit, secrets):
    need(isinstance(snapshot, dict) and isinstance(snapshot.get('privacy'), dict)
         and snapshot['privacy'].get('page_errors') == 0, 'PRIVATE_NETWORK_BOUNDARY_FAILED')
    rendered = wire(snapshot)
    need(not any(value in rendered for value in secrets if isinstance(value, str) and len(value) >= 8),
         'PRIVATE_NETWORK_BOUNDARY_FAILED')
    url = urllib.parse.urlsplit(snapshot.get('url', ''))
    need(url.scheme == 'http' and url.hostname == '127.0.0.1' and not url.username and not url.password
         and not url.query and (not url.fragment or re.fullmatch('[a-z-]+', url.fragment))
         and snapshot.get('session') == {} and snapshot.get('cookie') == '', 'PRIVATE_NETWORK_BOUNDARY_FAILED')
    local = snapshot.get('local')
    need(isinstance(local, dict) and set(local) <= {'race-ai-display-v1'}, 'PRIVATE_NETWORK_BOUNDARY_FAILED')
    if local:
        try:
            preferences = json.loads(local['race-ai-display-v1'])
            need(isinstance(preferences, dict) and set(preferences) <= {'budget', 'raceBudget', 'simulationBudget',
                 'simulationRaceBudget', 'maxPicks', 'sport', 'favoriteVenues'}, 'PRIVATE_NETWORK_BOUNDARY_FAILED')
            for name, value in preferences.items():
                if name == 'sport':
                    need(value in ('boat', 'keirin', 'autorace', 'horse'), 'PRIVATE_NETWORK_BOUNDARY_FAILED')
                elif name == 'favoriteVenues':
                    need(isinstance(value, list) and len(value) <= 64 and all(isinstance(v, str)
                         and len(v) <= 110 and re.match(r'^(boat|keirin|autorace|horse):', v) for v in value),
                         'PRIVATE_NETWORK_BOUNDARY_FAILED')
                else:
                    need(type(value) is int and 0 < value <= 10_000_000, 'PRIVATE_NETWORK_BOUNDARY_FAILED')
        except (ValueError, TypeError):
            raise SafariHold('PRIVATE_NETWORK_BOUNDARY_FAILED') from None
    need(audit.get('private_view_reads', 0) > 0 and audit.get('secret_in_request') is False
         and audit.get('non_read_requests') == audit.get('outbound_requests_permitted') == 0,
         'PRIVATE_NETWORK_BOUNDARY_FAILED')


def load_public_assets(root):
    root = Path(root).resolve()
    try:
        manifest_path = root / 'site-build.json'
        need(manifest_path.is_file() and not manifest_path.is_symlink()
             and manifest_path.stat().st_size <= 1024 * 1024, 'ASSET_MANIFEST_INVALID')
        manifest = json.loads(manifest_path.read_bytes())
        need(manifest.get('schema') == 'RACE_AI_SAVED_PAGES_BUILD_V1'
             and isinstance(manifest.get('files'), dict), 'ASSET_MANIFEST_INVALID')
        assets = {}
        for name, expected in manifest['files'].items():
            need(isinstance(name, str) and re.fullmatch('[A-Za-z0-9_./-]{1,200}', name)
                 and not name.startswith('/') and all(part not in ('', '.', '..') for part in name.split('/')),
                 'ASSET_PATH_REJECTED')
            if name == '.nojekyll' or name.startswith('views/'):
                continue  # No encrypted view or fixture forecast endpoint is needed by this transport.
            need(Path(name).suffix in ('.html', '.js', '.css', '.json', '.webp', '.png', '.svg'), 'ASSET_PATH_REJECTED')
            path = root / name
            need(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents))
                 and path.stat().st_size <= MAX_ASSET, 'ASSET_FILE_REJECTED')
            body = path.read_bytes()
            need(expected == {'bytes': len(body), 'sha256': sha(body)}, 'ASSET_HASH_MISMATCH')
            assets[name] = body
        need('index.html' in assets and 'app.js' in assets, 'ASSET_MANIFEST_INVALID')
        return assets
    except (OSError, ValueError, TypeError, KeyError) as error:
        if isinstance(error, SafariHold):
            raise
        raise SafariHold('ASSET_MANIFEST_INVALID') from None


def private_index(index):
    try:
        text = index.decode('utf-8')
        text, count = re.subn(r'<meta name="race-ai-encrypted-saved-view" content="\./views/[a-f0-9]{64}\.json">',
                             '<meta name="race-ai-private-saved-view" content="/api/forecast/saved">', text)
        need(count == 1 and text.count('<head>') == 1, 'ASSET_INDEX_INVALID')
        text = re.sub(r'<meta http-equiv="Content-Security-Policy" content="[^"]*">', '', text)
        return text.replace('<head>', '<head><script src="/_acceptance/privacy.js"></script>', 1).encode()
    except UnicodeError:
        raise SafariHold('ASSET_INDEX_INVALID') from None


PRIVACY_SCRIPT = b'''"use strict";
globalThis.__raceSafariPrivacy={external_blocked:0,csp_blocked:0,page_errors:0};
addEventListener('securitypolicyviolation',()=>{__raceSafariPrivacy.csp_blocked++});
addEventListener('error',e=>{if(e.target===window)__raceSafariPrivacy.page_errors++});
const originalFetch=globalThis.fetch.bind(globalThis);
globalThis.fetch=(input,options)=>{
 const url=new URL(typeof input==='string'||input instanceof URL?input:input.url,location.href);
 if(url.origin!==location.origin){__raceSafariPrivacy.external_blocked++;return Promise.reject(new TypeError('blocked'));}
 return originalFetch(input,options);
};
const originalOpen=XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open=function(method,url,...args){
 if(new URL(url,location.href).origin!==location.origin){__raceSafariPrivacy.external_blocked++;throw new TypeError('blocked');}
 return originalOpen.call(this,method,url,...args);
};
navigator.sendBeacon=()=>{__raceSafariPrivacy.external_blocked++;return false};
globalThis.WebSocket=globalThis.EventSource=function(){__raceSafariPrivacy.external_blocked++;throw new TypeError('blocked')};
'''


class LoopbackSite:
    """Known byte assets + one memory-only private route; no filesystem handler."""
    def __init__(self, assets, view, *, secrets=()):
        self.assets = dict(assets)
        self.assets['index.html'] = private_index(assets['index.html'])
        self.view = wire(view).encode()
        self.secrets = tuple(value for value in secrets if isinstance(value, str) and len(value) >= 8)
        need(not any(value.encode() in self.view or any(value.encode() in body for body in self.assets.values())
                     for value in self.secrets), 'PRIVATE_NETWORK_BOUNDARY_FAILED')
        self.audit = {'private_view_reads': 0, 'rejected_requests': 0, 'secret_in_request': False,
                      'non_read_requests': 0, 'outbound_requests_permitted': 0}

    def __enter__(self):
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.handle_read()

            def do_HEAD(self):
                self.handle_read(head=True)

            def do_POST(self):
                site.audit['non_read_requests'] += 1
                self.handle_read(reject_method=True)

            do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_POST

            def handle_read(self, head=False, reject_method=False):
                details = urllib.parse.unquote(self.path) + str(self.headers)
                if any(value in details for value in site.secrets):
                    site.audit['secret_in_request'] = True
                target = urllib.parse.urlsplit(self.path)
                valid_host = self.headers.get('Host') == site.origin.removeprefix('http://')
                valid_origin = self.headers.get('Origin') in (None, site.origin)
                status, body, mime = 200, b'', 'application/octet-stream'
                name = target.path.removeprefix('/') or 'index.html'
                query_ok = not target.query or (name in site.assets and name.endswith(('.js', '.css'))
                            and target.query == 'v=' + sha(site.assets[name])[:12])
                if reject_method:
                    status = 405
                elif not valid_host or not valid_origin or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                    status = 403
                elif not query_ok or target.fragment or self.headers.get('Content-Length') not in (None, '0'):
                    status = 400
                elif name == 'api/forecast/saved':
                    body, mime = site.view, 'application/json; charset=utf-8'
                    if not head:
                        site.audit['private_view_reads'] += 1
                elif name == '_acceptance/privacy.js':
                    body, mime = PRIVACY_SCRIPT, 'text/javascript; charset=utf-8'
                elif name in site.assets:
                    body = site.assets[name]
                    mime = 'text/javascript' if name.endswith('.js') else mimetypes.guess_type(name)[0] or mime
                elif name == 'favicon.ico':
                    status = 204
                elif name in ('api/forecast/status', 'api/racer-daily', 'api/racer-daily/status'):
                    status = 404  # Existing app treats absent generation/daily endpoints as unavailable.
                else:
                    status = 404
                if status >= 400:
                    body = b''
                    site.audit['rejected_requests'] += 1
                self.send_response(status)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Content-Security-Policy', CSP)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                if not head:
                    self.wfile.write(body)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.origin = 'http://127.0.0.1:' + str(self.server.server_port)
        self.url = self.origin + '/'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.view = b''


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise SafariHold('LIVE_PAGES_BYTES_DIFFER')


def verify_live_assets(assets):
    """Read only public executable bytes; credentials are never used by this client."""
    opener = urllib.request.build_opener(NoRedirect())
    checked = {}
    for name, body in assets.items():
        if not name.endswith(('.js', '.css', '.html')):
            continue
        url = 'https://haji84.github.io/RACE-AI/' + name + '?verify=' + PAGES_SHA
        request = urllib.request.Request(url, headers={'User-Agent': 'RACE-AI-native-Safari-acceptance/1',
                                                     'Cache-Control': 'no-cache'})
        try:
            with opener.open(request, timeout=24) as response:
                need(response.status == 200 and response.url == url and response.read(len(body) + 1) == body,
                     'LIVE_PAGES_BYTES_DIFFER')
        except (OSError, urllib.error.URLError):
            raise SafariHold('LIVE_PAGES_BYTES_DIFFER') from None
        checked[name] = sha(body)
    return checked


class WebDriver:
    """The Apple W3C endpoint is loopback only; response errors are never exposed."""
    def __init__(self, port):
        need(type(port) is int and 1024 <= port <= 65535, 'SAFARI_WEBDRIVER_FAILED')
        self.base = 'http://127.0.0.1:' + str(port)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.session = None

    def call(self, method, path, body=None):
        need(isinstance(path, str) and path.startswith('/') and '?' not in path, 'SAFARI_WEBDRIVER_FAILED')
        request = urllib.request.Request(self.base + path,
            data=None if body is None else wire(body).encode(), method=method,
            headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=60) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                need(len(raw) <= 2 * 1024 * 1024, 'SAFARI_WEBDRIVER_FAILED')
                result = json.loads(raw)['value']
                need(not isinstance(result, dict) or 'error' not in result, 'SAFARI_WEBDRIVER_FAILED')
                return result
        except (OSError, ValueError, KeyError, urllib.error.URLError):
            raise SafariHold('SAFARI_WEBDRIVER_FAILED') from None

    def new_session(self):
        result = self.call('POST', '/session', {'capabilities': {'alwaysMatch': {
            'browserName': 'Safari', 'platformName': 'macOS'}}})
        need(isinstance(result, dict) and re.fullmatch('[A-Za-z0-9-]{1,100}', result.get('sessionId', '')),
             'SAFARI_WEBDRIVER_FAILED')
        self.session = result['sessionId']
        return native_identity(result.get('capabilities'))

    def command(self, method, suffix, body=None):
        need(self.session is not None, 'SAFARI_WEBDRIVER_FAILED')
        return self.call(method, '/session/' + self.session + suffix, body)

    def script(self, script, *args):
        return self.command('POST', '/execute/sync', {'script': script, 'args': list(args)})

    def wait(self, script, *args, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.script(script, *args)
            if value:
                return value
            time.sleep(0.15)
        raise SafariHold('APP_UI_CHECK_FAILED')

    def element(self, selector, visible=True):
        element = self.script('''return Array.from(document.querySelectorAll(arguments[0])).find(e=>
            !arguments[1] || (e.getClientRects().length && getComputedStyle(e).visibility!=='hidden')) || null;''',
                              selector, visible)
        need(isinstance(element, dict), 'APP_UI_CHECK_FAILED')
        ident = element.get('element-6066-11e4-a52e-4f735466cecf')
        need(isinstance(ident, str) and re.fullmatch('[A-Za-z0-9-]{1,160}', ident), 'APP_UI_CHECK_FAILED')
        return ident

    def click(self, selector, visible=True):
        self.command('POST', '/element/' + self.element(selector, visible) + '/click', {})

    def select(self, selector, value):
        self.click(selector + ' option[value=' + json.dumps(str(value)) + ']', visible=False)
        self.wait('return document.querySelector(arguments[0])?.value===arguments[1]', selector, str(value))

    def budget(self, value):
        element = self.element('#simulation-budget')
        self.command('POST', '/element/' + element + '/clear', {})
        self.command('POST', '/element/' + element + '/value', {'text': str(value) + '\ue004'})
        self.wait('return document.querySelector("#simulation-budget")?.value===arguments[0]', str(value))

    def close(self):
        if self.session is not None:
            try:
                self.command('DELETE', '')
            except SafariHold:
                pass
            self.session = None


@contextmanager
def apple_driver():
    need(platform.system() == 'Darwin', 'NATIVE_MACOS_REQUIRED')
    need(os.path.isfile('/usr/bin/safaridriver') and os.access('/usr/bin/safaridriver', os.X_OK), 'SAFARIDRIVER_REQUIRED')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    process = subprocess.Popen(['/usr/bin/safaridriver', '--port', str(port)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=driver_environment(os.environ))
    driver = WebDriver(port)
    try:
        ready = False
        for _ in range(100):
            need(process.poll() is None, 'SAFARIDRIVER_UNAVAILABLE')
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                    ready = True
                    break
            except OSError:
                time.sleep(0.1)
        need(ready, 'SAFARIDRIVER_UNAVAILABLE')
        identity = driver.new_session()
        yield driver, identity
    finally:
        driver.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def read_authenticated_view(source_root):
    """Existing read-only feed/AES/context code; no producer or model is invoked."""
    source_root = Path(source_root).resolve()
    result = subprocess.run(['git', '-C', str(source_root), 'rev-parse', 'HEAD'], capture_output=True, timeout=10)
    need(result.returncode == 0 and result.stdout.decode().strip() == SOURCE_SHA, 'SOURCE_REVISION_MISMATCH')
    sys.path.insert(0, str(source_root))
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        from scripts import boat_saved_site_context as context_module
        from scripts import boat_saved_view_feed as feed
        from scripts import boat_private_original_vault as vault
        repo = vault._environment(source_root)
        config = feed._json(feed._read(source_root / 'audit/state/boat-saved-view-input.json', 8192), 8192)
        raw = base64.b64decode(config['bootstrap'], validate=True)
        need(feed.sha(raw) == config['bootstrap_sha256'], 'SAVED_VIEW_UNAVAILABLE')
        bootstrap = feed.F.open_bootstrap(raw)
        git = feed.F.FeedRepository(repo)
        _, _, generation, view = feed.F.current_view(git, bootstrap)
        now = datetime.now(timezone.utc)
        today = now.astimezone(context_module.JST).date().isoformat()
        day = max((row['event_date_jst'] for row in view['records']
                   if row.get('sport') == 'boat' and row['event_date_jst'] <= today), default='')
        context = context_module.build_context(bootstrap, view, generation, now=now, event_day=day)
        # Preserve the independently derived context's counts/hashes while omitting its private URL.
        safe_context = validate_context(context)
        viewer_key = base64.urlsafe_b64encode(bootstrap['key']).decode().rstrip('=')
    return safe_context, view, viewer_key


def app_checks(driver, site, context, secrets):
    driver.command('POST', '/url', {'url': site.url})
    driver.wait('return document.querySelector("#file-message")?.textContent.includes("保存済み予想")', timeout=90)
    viewport_results, comparisons, native_views, result_views = [], 0, 0, 0
    probe = context['model_switch_probe']

    def click_page(page):
        driver.click('[data-page=' + json.dumps(page) + ']')
        driver.wait('return !document.querySelector(arguments[0])?.hidden', '#page-' + page)

    def select_day():
        driver.script('''const e=document.querySelector('#selected-date');e.value=arguments[0];
                         e.dispatchEvent(new Event('change',{bubbles:true}));''', context['day'])
        driver.wait('return document.querySelector("#display-day")?.textContent.includes(arguments[0])', context['day'])

    def open_race(item):
        click_page('races')
        if driver.script('return !!document.querySelector("#all-venues")?.getClientRects().length'):
            driver.click('#all-venues')
        phase = 'upcoming' if datetime.now(timezone.utc).timestamp() < datetime.fromisoformat(
            item['cutoff_at'].replace('Z', '+00:00')).timestamp() else 'results'
        driver.click('[data-race-view=' + json.dumps(phase) + ']')
        target = '#page-races [data-open-race=' + json.dumps(item['race_id']) + ']'
        for _ in range(5):
            if driver.script('return !!document.querySelector(arguments[0])', target):
                driver.click(target)
                return
            more = driver.script('''return Array.from(document.querySelectorAll('#page-races button'))
                                  .find(e=>e.textContent.includes('さらに60件表示'))?.outerHTML || '';''')
            need(more, 'APP_UI_CHECK_FAILED')
            # Use the actual visible pagination button through native Element Click.
            element = driver.script('''return Array.from(document.querySelectorAll('#page-races button'))
                                   .find(e=>e.textContent.includes('さらに60件表示'));''')
            ident = element.get('element-6066-11e4-a52e-4f735466cecf')
            need(isinstance(ident, str) and re.fullmatch('[A-Za-z0-9-]{1,160}', ident), 'APP_UI_CHECK_FAILED')
            driver.command('POST', '/element/' + ident + '/click', {})
        raise SafariHold('APP_UI_CHECK_FAILED')

    for width in (1440, 390):
        driver.command('POST', '/window/rect', {'width': width, 'height': 1000})
        actual = driver.script('return {width:innerWidth,height:innerHeight}')
        viewport_results.append(viewport_evidence(width, actual))
        select_day()
        native = context['native_probe']
        open_race(native)
        driver.select('#prediction-select', native['index'])
        need(driver.script('''return document.querySelector('#prediction-select').selectedOptions[0].textContent.startsWith('P1 ')
            && document.querySelector('#detail-tab-content .forecast-panel')?.dataset.nativeDispatch==='true';'''),
             'APP_UI_CHECK_FAILED')
        native_views += 1
        open_race(probe)
        driver.click('[data-detail-tab="outlook"]')
        for choice in probe['choices']:
            driver.select('#prediction-select', choice['index'])
        for choice in probe['choices']:
            driver.select('#detail-model-select', choice['model_id'])
            detail = driver.script('''const panel=document.querySelector('#detail-tab-content .forecast-panel');
                return {model_id:panel?.dataset.modelId,index:document.querySelector('#prediction-select')?.value,
                tickets:Array.from(panel.querySelectorAll('.saved-ticket .combo'),n=>
                Array.from(n.querySelectorAll('.lane'),e=>Number(e.textContent)))};''')
            verify_model_choice(choice, detail)
            comparisons += 1
        click_page('research')
        need(driver.script('return document.querySelector("#research-model-select")?.value===arguments[0]',
                           probe['choices'][1]['model_id']), 'APP_UI_CHECK_FAILED')
        driver.click('#research-race-audit [data-return-to-race]')
        need(driver.script('return document.querySelector("#detail-model-select")?.value===arguments[0]',
                           probe['choices'][1]['model_id']), 'APP_UI_CHECK_FAILED')
        click_page('results')
        values = driver.script('return Array.from(document.querySelectorAll("#results-model option"),e=>e.value)')
        groups = set()
        for value in values:
            try:
                fields = json.loads(value)
                if isinstance(fields, list) and len(fields) >= 6 and fields[1:3] == ['boat', 'P1']:
                    groups.add(wire((fields[3:7] + [None])[:4]))
            except (TypeError, ValueError):
                pass
        need(all(wire(group) in groups for group in context['native_groups']), 'APP_UI_CHECK_FAILED')
        metrics = driver.script('return document.querySelector("#saved-result-metrics")?.textContent')
        count = re.search(r'取得結果\s*(\d+)レース', metrics or '')
        need(count and int(count[1]) >= context['minimum_results'] and
             all(label in metrics for label in ('的中', '不的中', '結果待ち')), 'APP_UI_CHECK_FAILED')
        for budget in (10000, 5000):
            driver.budget(budget)
            driver.select('#simulation-race-budget', '1000')
            simulation = driver.script('return document.querySelector("#simulation-metrics")?.textContent')
            need(isinstance(simulation, str) and all(label in simulation for label in
                 ('確定分の収支', '確定分の回収率', '未確定購入額', '全体の収支'))
                 and '試算を表示できません' not in simulation, 'APP_UI_CHECK_FAILED')
        need(driver.script('return document.documentElement.scrollWidth<=innerWidth'), 'APP_UI_CHECK_FAILED')
        result_views += 1
    snapshot = driver.script('''return {url:location.href,local:{...localStorage},session:{...sessionStorage},
                                cookie:document.cookie,privacy:globalThis.__raceSafariPrivacy};''')
    verify_private_boundary(snapshot, site.audit, secrets)
    return {'desktop_viewports': viewport_results, 'model_switch_original_comparisons': comparisons,
            'native_p1_detail_views': native_views, 'result_budget_views': result_views,
            'external_requests_blocked_before_network': snapshot['privacy']['external_blocked'],
            'csp_violations_blocked': snapshot['privacy']['csp_blocked'],
            'private_view_reads': site.audit['private_view_reads'], 'key_in_requests_url_or_storage': False,
            'outbound_browser_requests_permitted': 0, 'official_source_requests': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--public-root', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        need(platform.system() == 'Darwin', 'NATIVE_MACOS_REQUIRED')
        assets = load_public_assets(args.public_root)
        hashes = verify_live_assets(assets)
        context, view, viewer_key = read_authenticated_view(args.source_root)
        secrets = tuple(value for value in (viewer_key, *(os.environ.get(k) for k in
            ('RACE_AI_STATE_KEY', 'GH_TOKEN', 'GITHUB_TOKEN'))) if value)
        with LoopbackSite(assets, view, secrets=secrets) as site:
            with apple_driver() as (driver, identity):
                checks = app_checks(driver, site, context, secrets)
        print(wire({'schema': 'RACE_AI_NATIVE_SAFARI_ACCEPTANCE_V1',
            'status': 'NATIVE_MACOS_SAFARI_SAVED_VIEW_VERIFIED', 'native_browser': identity,
            'verified_at': datetime.now(timezone.utc).isoformat(), 'pages_sha': PAGES_SHA,
            'read_only_source_sha': SOURCE_SHA, 'live_asset_sha256': hashes,
            'saved_day': context['day'], 'authenticated_generation': context['generation'],
            'authenticated_results': context['minimum_results'], 'authenticated_native_p1_groups': context['native_group_count'],
            **checks, 'transport': 'LOOPBACK_EXISTING_PRIVATE_SAVED_ENDPOINT',
            'browser_aes_and_owner_login_verified': False, 'physical_iphone_verified': False,
            'all_eight_reference_screens_visually_verified': False, 'plaintext_published': False,
            'forecast_or_result_mutation': False}))
        return 0
    except Exception as error:
        print(wire(failure_report(error)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
