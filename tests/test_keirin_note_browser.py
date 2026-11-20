"""Real Chromium with invented note files; every request stays on loopback."""
import base64
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import re
import threading
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from race_ai.keirin_note_view import canonical


ROOT = Path(__file__).resolve().parents[1]
DAY = '2030-01-15'
RACE = '203001159801'
KDREAMS = 'https://keirin.kdreams.jp/fixture/racedetail/9820300115010001/'
NETKEIRIN = 'https://keirin.netkeiba.com/race/entry/?race_id=' + RACE


def source(value):
    text = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    raw = text.encode()
    return dict(text=text, bytes=len(raw), sha256=sha256(raw).hexdigest())


def packet(venue='架空会場'):
    """Complete source shapes with invented people, tickets and six phases."""
    phases = ['INITIAL', 'BELL', 'FINAL_HOME', 'FINAL_BACK', 'FOURTH_CORNER', 'GOAL']
    riders = [dict(number=n, name='架空選手' + str(n), score=80.0,
        S=n, H=n+1, B=n+2, nige=1, makuri=2, sashi=3, mark=4,
        win_rate=10.0, top3_rate=30.0, comment='架空のコメント',
        recent_meets=['架空開催・１着'],
        field_sources=dict(statistics=KDREAMS, H=NETKEIRIN, comment=KDREAMS))
        for n in (1, 2, 3)]
    rows = dict(races=[dict(race_id=RACE, venue=venue, race_no=1,
        race_title='架空の予選', deadline_time='12:00', start_time='12:05',
        riders=riders, lines=[[1, 2], [3]], source_url=KDREAMS)])
    original = [dict(race_id=RACE, headline='架空の分析', confidence='中位',
        analysis_created_at='2030-01-15T08:00:00+09:00',
        tickets=[dict(combo='1-2-3', role='本線'), dict(combo='3-2-1', role='波乱')],
        scenarios=[dict(id='invented-original', label='架空の展開',
            phases=['架空の' + phase for phase in phases], evidence=['架空の観測'])])]
    reference = [dict(input=dict(race_id=RACE, source_pages=[
        dict(kind='RACECARD', url=NETKEIRIN), dict(kind='LINE', url=KDREAMS)]),
        output=dict(race_id=RACE, generated_at='2030-01-15T08:01:00+09:00',
            A=dict(ranked_tickets=[[3, 1, 2]]),
            B=dict(ranked_tickets=[[2, 3, 1]], six_phase_scenarios=[dict(
                scenario_id='invented-six-phase', six_phases=[dict(phase=phase,
                    projected_order=[2, 3, 1], hypothesis_actions=['架空の動き'])
                    for phase in phases])]),
            C=dict(state='HOLD_NO_INDEPENDENT_HISTORICAL_FOLLOW_LABELS')))]
    return dict(schema='RACE_AI_KEIRIN_NOTE_VIEW_V1',
        formal_model_admission=False, production_weight_switch=False,
        source_commit='a'*40, imported_at='2030-01-15T00:00:00Z', dates=[DAY],
        files={f'data/{DAY}/races.json': source(rows),
               f'data/{DAY}/forecasts.json': source(original),
               f'data/{DAY}/reference_AB.json': source(reference)})


def encrypted(value):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    # Explicitly public fixture-only key; never valid for owner production data.
    key = bytes(range(32))
    plain = canonical(value)
    header = dict(schema='RACE_AI_SAVED_WEB_VIEW_V1',
                  source_content_sha256=sha256(plain).hexdigest())
    nonce = b'n'*12
    body = canonical(dict(header=header, nonce=base64.b64encode(nonce).decode(),
        ciphertext=base64.b64encode(AESGCM(key).encrypt(nonce, plain,
                                                      canonical(header))).decode())) + b'\n'
    return body, sha256(body).hexdigest(), base64.urlsafe_b64encode(key).decode().rstrip('=')


def result_observation(state='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL',
                       previous=None, at='2030-01-15T03:10:00Z'):
    matched = state == 'SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL'
    value = dict(schema='RACE_AI_KEIRIN_INDEPENDENT_SECONDARY_RESULT_MATCH_V1',
        race_id=RACE, state=state, winning_triple=[3, 1, 2] if matched else None,
        payout_per_100yen=5300 if matched else None,
        provider_receipts=[dict(provider=provider, source_bytes_sha256=str(n)*64,
            observed_at=at, source_url=url) for n, provider, url in (
            (1, 'Kdreams', KDREAMS+'?pageType=result'),
            (2, 'netkeirin', NETKEIRIN.replace('/entry/', '/result/')))],
        official_primary_result_authenticated=False,
        actual_organizer_cutoff_authenticated=False,
        qualifies_for_formal_settlement=False)
    fact = dict(value, provider_receipts=[dict(provider=r['provider'],
        source_url=r['source_url']) for r in value['provider_receipts']])
    return dict(value, captured_at=at,
        observation_sha256=sha256(canonical(fact)).hexdigest(),
        previous_observation_sha256=previous)


def with_results(value, observations):
    value['files'][f'data/{DAY}/research_results.json'] = source(dict(
        schema='RACE_AI_KEIRIN_NOTE_RESEARCH_RESULTS_V1', day_jst=DAY,
        observations=observations))
    return value


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'Playwright is optional')
class NoteBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.runtime = sync_playwright().start()
        try:
            cls.browser = cls.runtime.chromium.launch(headless=True, args=['--no-sandbox'],
                executable_path=os.getenv('RACE_AI_TEST_CHROMIUM'))
        except Exception:
            cls.runtime.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.runtime.stop()

    def setUp(self):
        self.request_started = threading.Event()
        self.release_response = threading.Event()
        self.release_response.set()
        self.requests, self.external, self.errors = [], [], []
        self.cipher, self.identity, self.key = encrypted(packet())
        self.served_cipher = self.cipher
        html = ('<!doctype html><html><head><meta name="referrer" content="no-referrer">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\';'
            'script-src \'self\';style-src \'self\';connect-src \'self\';img-src \'self\' data:;'
            'form-action \'none\';base-uri \'none\'">'
            '<link rel="stylesheet" href="./style.css"><script defer src="./note.js"></script>'
            '</head><body><main><div id="data-banner">架空の保存画面</div></main></body></html>').encode()
        components = ['keirin-note-source/staking.js', 'keirin-note-source/staking_flexible.js',
                      'keirin-note-source/rollover.js', 'keirin-note-model.js', 'keirin-note-feed.js']
        bundle = (b'window.RaceNoteInitialFragment=location.hash;\n' + b'\n'.join(
            (ROOT/'web'/name).read_bytes() for name in components) +
            b'\nObject.assign(window.RaceKeirinNoteFeed,window.__noteFeedOverride||{});\n' +
            (ROOT/'web/keirin-note-view.js').read_bytes())
        styles = (ROOT/'web/race-style-core.css').read_bytes() + b'\n' + (
            ROOT/'web/keirin-note.css').read_bytes()
        assets = {'/': (html, 'text/html; charset=utf-8'),
                  '/note.js': (bundle, 'text/javascript; charset=utf-8'),
                  '/style.css': (styles, 'text/css; charset=utf-8')}
        self.assets = assets
        state = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = urlsplit(self.path).path
                state.requests.append((self.path, self.headers.get('Referer', '')))
                if path == '/views/' + state.identity + '.json':
                    state.request_started.set()
                    state.release_response.wait(10)
                    raw, mime = state.served_cipher, 'application/json'
                elif path in state.assets:
                    raw, mime = state.assets[path]
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.context = self.browser.new_context(viewport=dict(width=390, height=844))
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.route(re.compile(r'^(?!' + re.escape(self.base) + r'/)'), self.route)
        self.page.add_init_script('''
          const nativeFetch=window.fetch;
          window.__noteAborted=0;window.__noteDecoded=0;
          window.fetch=(...args)=>nativeFetch(...args).catch(error=>{
            if(error.name==='AbortError')window.__noteAborted++;throw error;
          });
        ''')

    def stop_server(self):
        self.release_response.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def route(self, route):
        if urlsplit(route.request.url).netloc != urlsplit(self.base).netloc:
            self.external.append(route.request.url)
            route.abort()
        else:
            route.continue_()

    def open(self, key=None):
        self.page.goto(self.base + '/#note=' + self.identity + '.' + (key or self.key),
                       wait_until='domcontentloaded')

    def loaded(self):
        self.page.locator('#kn-status').filter(has_text=re.compile(
            r'端末内で開きました|保存データの更新を確認しました')).wait_for()

    def watch_decryption(self):
        self.page.evaluate('''() => {
          const decode=window.RaceKeirinNote.openCipher;
          window.RaceKeirinNote.openCipher=async(...args)=>{
            try{return await decode(...args);}finally{window.__noteDecoded++;}
          };
        }''')

    def await_old_load(self):
        self.release_response.set()
        self.page.wait_for_function('() => window.__noteAborted>0 || window.__noteDecoded>0')

    def test_reference_six_phases_provenance_and_mobile_dialog_are_usable(self):
        self.open()
        self.loaded()
        self.page.locator('#kn-variant').select_option('B')
        self.page.get_by_text('展開と根拠・6局面を読む', exact=True).click()
        scenario = self.page.locator('.kn-scenario')
        self.assertEqual(scenario.locator('li').count(), 6)
        self.assertIn('2 → 3 → 1', scenario.inner_text())
        self.assertIn('架空の動き', scenario.inner_text())
        self.assertGreater(self.page.locator('a[href="' + NETKEIRIN + '"]').count(), 0)
        self.page.get_by_text('選手の数字・コメント・近況', exact=True).click()
        self.assertIn('H', self.page.locator('.kn-field-provenance').first.inner_text())
        for width in (390, 1440):
            self.page.set_viewport_size(dict(width=width, height=844))
            geometry = self.page.evaluate('''() => {
              const dialog=document.querySelector('#keirin-note-dialog'),host=dialog.querySelector('.kn-host'),r=host.shadowRoot;
              const footer=r.querySelector('.kn-selection').getBoundingClientRect(),scroll=r.querySelector('.kn-scroll');
              return {dialog:dialog.getBoundingClientRect().height,host:host.getBoundingClientRect().height,
                footerBottom:footer.bottom,footerTop:footer.top,viewport:innerHeight,
                scrollHeight:scroll.clientHeight,overflow:scroll.scrollHeight>scroll.clientHeight,
                wide:document.documentElement.scrollWidth>innerWidth};
            }''')
            self.assertGreater(geometry['host'], geometry['dialog'] * .9)
            self.assertGreater(geometry['scrollHeight'], 100)
            self.assertLessEqual(geometry['footerBottom'], geometry['viewport'])
            self.assertGreater(geometry['footerTop'], 0)
            self.assertTrue(geometry['overflow'])
            self.assertFalse(geometry['wide'])
        self.assertEqual(self.external, [])
        self.assertEqual(self.errors, [])
        self.assertFalse(any(self.key in (path + referrer) for path, referrer in self.requests))
        storage = self.page.evaluate('JSON.stringify({...localStorage,...sessionStorage})')
        self.assertNotIn(self.key, storage)
        self.assertNotIn('架空選手', storage)

    def test_wrong_key_and_tampered_cipher_never_show_forecasts(self):
        for key, tamper in [('A'*43, False), (self.key, True)]:
            with self.subTest(tamper=tamper):
                self.served_cipher = self.cipher + (b' ' if tamper else b'')
                self.open(key)
                self.page.locator('#kn-status').filter(has_text='開けませんでした').wait_for()
                self.assertEqual(self.page.locator('.kn-race').count(), 0)
                self.assertEqual(self.page.locator('#kn-days button').count(), 0)
        self.assertEqual(self.external, [])

    def test_clear_cancels_a_delayed_owner_link_load(self):
        self.release_response.clear()
        self.open()
        self.assertTrue(self.request_started.wait(2))
        self.watch_decryption()
        self.page.locator('#kn-clear').click()
        self.await_old_load()
        self.assertEqual(self.page.locator('.kn-race').count(), 0)
        self.assertIn('消去しました', self.page.locator('#kn-status').inner_text())
        self.assertEqual(urlsplit(self.page.url).fragment, '')
        self.assertEqual(self.external, [])

    def test_new_file_import_wins_over_an_older_delayed_file(self):
        self.page.goto(self.base, wait_until='domcontentloaded')
        self.page.locator('#keirin-note-open').click()
        self.page.evaluate('''() => {
          const open=window.RaceKeirinNote.openPacket;
          let first=true;
          window.RaceKeirinNote.openPacket=async packet=>{
            const older=first;
            if(older){first=false;await new Promise(resolve=>window.__releaseOldImport=resolve);}
            const result=await open(packet);
            if(older)window.__oldImportCompleted=true;
            return result;
          };
        }''')
        field = self.page.locator('#kn-file')
        field.set_input_files(dict(name='older-invented.json', mimeType='application/json',
                                   buffer=canonical(packet('古い架空会場'))))
        self.page.wait_for_function('() => typeof window.__releaseOldImport==="function"')
        field.set_input_files(dict(name='newer-invented.json', mimeType='application/json',
                                   buffer=canonical(packet('新しい架空会場'))))
        self.loaded()
        self.assertIn('新しい架空会場', self.page.locator('.kn-race h2').inner_text())
        self.assertEqual(field.input_value(), '')
        self.page.evaluate('window.__releaseOldImport()')
        self.page.wait_for_function('() => window.__oldImportCompleted===true')
        self.assertIn('新しい架空会場', self.page.locator('.kn-race h2').inner_text())
        self.assertEqual(self.external, [])
        self.assertEqual(self.errors, [])

    def test_clear_invalidates_a_delayed_independent_feed_decode(self):
        fixture = json.dumps(packet(), ensure_ascii=False)
        self.page.add_init_script('''
          window.__noteFeedOverride={createSession:null,open:async(key,{signal,onStatus})=>{
            window.__feedStarted=true;
            onStatus?.('synthetic status');
            await new Promise(resolve=>window.__releaseFeed=resolve);
            const value=await window.RaceKeirinNote.openPacket(''' + fixture + ''');
            window.__feedCompleted=true;
            return value;
          }};
        ''')
        self.page.goto(self.base + '/#notefeed=' + 'Q'*160, wait_until='domcontentloaded')
        self.assertTrue(self.page.evaluate('window.__feedStarted===true'))
        self.page.locator('#kn-clear').click()
        self.page.evaluate('window.__releaseFeed()')
        self.page.wait_for_function('() => window.__feedCompleted===true')
        self.assertEqual(self.page.locator('.kn-race').count(), 0)
        self.assertIn('消去しました', self.page.locator('#kn-status').inner_text())
        self.assertEqual(urlsplit(self.page.url).fragment, '')
        self.assertEqual(self.external, [])

    def test_reference_only_day_opens_available_research_instead_of_empty_analysis(self):
        self.page.goto(self.base, wait_until='domcontentloaded')
        self.page.locator('#keirin-note-open').click()
        value = packet()
        del value['files'][f'data/{DAY}/forecasts.json']
        self.page.locator('#kn-file').set_input_files(dict(name='research-only-invented.json',
            mimeType='application/json', buffer=canonical(value)))
        self.loaded()
        self.assertEqual(self.page.locator('#kn-variant').input_value(), 'A')
        self.assertEqual(self.page.locator('#kn-market').input_value(), '3t')
        self.assertEqual(self.page.locator('.kn-ticket').count(), 1)
        self.assertIn('参考A', self.page.locator('.kn-badges').inner_text())
        self.assertEqual(self.external, [])

    def test_bound_reference_results_show_exact_points_and_conditional_research_at_all_widths(self):
        value = with_results(packet(), [result_observation()])
        value['files'][f'data/{DAY}/settlement.json'] = source([
            dict(race_id=RACE, winning_combo='1-2-3', status='MISS', net_yen=-200)])
        self.cipher, self.identity, self.key = encrypted(value)
        self.served_cipher = self.cipher
        self.open()
        self.loaded()
        result = self.page.locator('.kn-research-result')
        self.assertEqual(result.get_attribute('data-result-state'),
                         'SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL')
        self.assertIn('参考A · 1点', result.inner_text())
        self.assertIn('5,200円', result.inner_text())
        self.assertIn('参考B · 1点', result.inner_text())
        self.assertIn('-100円', result.inner_text())
        self.assertIn('条件付きの研究比較', result.inner_text())
        self.assertIn('提供サイトの保存分析の照合',
                      self.page.locator('.kn-race .kn-result').first.inner_text())
        self.assertNotIn('Hit@8', result.inner_text())
        for width in (320, 390, 1440):
            self.page.set_viewport_size(dict(width=width, height=844))
            self.assertFalse(self.page.evaluate(
                'document.documentElement.scrollWidth>innerWidth'))
            self.assertIn('同じレースでA/Bを比較できる数 1 / 1',
                          self.page.locator('#kn-research-summary').inner_text())
        self.assertEqual(self.errors, [])
        self.assertEqual(self.external, [])
        self.assertFalse(any(self.key in path+referrer for path, referrer in self.requests))

    def test_latest_disagreement_holds_current_comparison_and_preserves_result_history(self):
        first = result_observation()
        held = result_observation('HOLD_SECONDARY_RESULT_DISAGREEMENT',
            first['observation_sha256'], '2030-01-15T03:20:00Z')
        self.cipher, self.identity, self.key = encrypted(with_results(packet(), [first, held]))
        self.served_cipher = self.cipher
        self.open()
        self.loaded()
        result = self.page.locator('.kn-research-result')
        self.assertEqual(result.get_attribute('data-result-state'), held['state'])
        self.assertIn('出典間の相違で保留', result.inner_text())
        self.assertIn('参考A · 1点 · 未判定', result.inner_text())
        result.get_by_text('結果の改訂履歴・出典', exact=True).click()
        self.assertEqual(result.locator('[data-result-revision]').count(), 2)
        self.assertGreater(result.locator('a[href="'+NETKEIRIN.replace('/entry/', '/result/')+'"]').count(), 0)
        self.assertIn('同じレースでA/Bを比較できる数 0 / 1',
                      self.page.locator('#kn-research-summary').inner_text())
        self.assertEqual(self.errors, [])

    def test_result_only_packet_displays_saved_results_without_inventing_predictions(self):
        value = packet()
        value['files'] = {}
        self.cipher, self.identity, self.key = encrypted(with_results(value, [result_observation()]))
        self.served_cipher = self.cipher
        self.open()
        self.loaded()
        self.assertEqual(self.page.locator('.kn-race').count(), 0)
        self.assertIn('保存結果 1件 · 予想未読込 1件',
                      self.page.locator('#kn-research-summary').inner_text())
        self.assertIn('二つの掲載元が一致',
                      self.page.locator('#kn-result-only').inner_text())
        self.assertEqual(self.errors, [])

    def test_two_car_saved_analysis_shows_hit_without_borrowing_trifecta_payout(self):
        value = with_results(packet(), [result_observation()])
        value['files'][f'data/{DAY}/two_car_forecasts.json'] = source([
            dict(race_id=RACE, analysis_created_at='2030-01-15T08:01:00+09:00',
                 tickets=[dict(combo='3-1', role='本線')])])
        self.cipher, self.identity, self.key = encrypted(value)
        self.served_cipher = self.cipher
        self.open()
        self.loaded()
        self.page.locator('#kn-market').select_option('2t')
        self.page.locator('#kn-variant').select_option('original')
        selected = self.page.locator('.kn-selected-comparison')
        self.assertEqual(selected.count(), 1)
        self.assertIn('2車単・保存分析 · 1点 · 的中', selected.inner_text())
        self.assertIn('払戻 未確認', selected.inner_text())
        self.assertNotIn('5,300円', selected.inner_text())
        self.assertEqual(self.errors, [])

    def test_real_feed_crypto_keeps_each_reference_version_bound_in_the_result_display(self):
        from race_ai import keirin_note_feed as api
        original = packet()
        fresh = packet()
        del fresh['files'][f'data/{DAY}/forecasts.json']
        references = json.loads(fresh['files'][f'data/{DAY}/reference_AB.json']['text'])
        references[0]['output']['A']['ranked_tickets'] = [[2, 3, 1]]
        fresh['files'][f'data/{DAY}/reference_AB.json'] = source(references)
        delta = packet()
        delta['files'] = {}
        observation = result_observation()
        with_results(delta, [observation])
        with TemporaryDirectory() as tmp:
            cap = api.create_recipient(Path(tmp)/'fixture-only-owner')
            key = Path(cap['private_key']).read_text().strip()
            snapshots = [api.seal_snapshot(value, cap['public'], kind=kind)
                for value, kind in ((original, 'import'), (fresh, 'research'), (delta, 'results'))]
            index = None
            for snapshot in snapshots:
                index = api.append_index(index, cap['public'], entry=snapshot['entry'])
            index = api.append_index(index, cap['public'], result_checks={RACE:dict(
                checked_at=observation['captured_at'], digest=observation['observation_sha256'],
                status='MATCHED')})
        components = ['keirin-note-source/staking.js', 'keirin-note-source/staking_flexible.js',
            'keirin-note-source/rollover.js', 'keirin-note-model.js', 'keirin-note-feed.js',
            'keirin-note-view.js']
        self.assets['/note.js'] = (b'window.RaceNoteInitialFragment=location.hash;\n'+b'\n'.join(
            (ROOT/'web'/name).read_bytes() for name in components), 'text/javascript; charset=utf-8')
        html, mime = self.assets['/']
        self.assets['/'] = (html.replace(b"connect-src 'self';", b"connect-src 'self' https://raw.githubusercontent.com;"), mime)
        base = 'https://raw.githubusercontent.com/haji84/RACE-AI/state/keirin-note-view/'
        responses = {base+'index.json': canonical(index)}
        responses.update({base+'views/'+s['entry']['cipher_sha256']+'.json':s['cipher']
                          for s in snapshots})
        fixture_requests = []

        def serve(route):
            request = route.request
            fixture_requests.append((request.url, request.headers))
            route.fulfill(status=200, body=responses[request.url], headers={
                'content-type':'application/json', 'access-control-allow-origin':self.base})

        self.page.route(base+'**', serve)
        self.page.goto(self.base+'/#notefeed='+key, wait_until='domcontentloaded')
        self.loaded()
        result = self.page.locator('.kn-research-result')
        self.assertIn('参考A · 1点 · 不的中',
                      result.locator(':scope > .kn-reference-comparison').first.inner_text())
        result.get_by_text('参考予想の保存版・原本の照合', exact=True).click()
        versions = result.locator('details').last
        self.assertIn('参考予想の保存版 1', versions.inner_text())
        self.assertIn('参考A · 1点 · 的中', versions.inner_text())
        self.assertIn(snapshots[0]['entry']['cipher_sha256'], versions.inner_text())
        self.assertIn(snapshots[1]['entry']['cipher_sha256'], versions.inner_text())
        self.page.locator('#kn-variant').select_option('original')
        self.assertIn('1−2−3', ''.join(self.page.locator('.kn-tickets').inner_text().split()))
        self.assertEqual(len(fixture_requests), 4)
        self.assertFalse(any(key in url+json.dumps(headers) for url, headers in fixture_requests))
        self.assertEqual(self.external, [])
        self.assertEqual(self.errors, [])

    def test_open_feed_reflects_order_and_independent_arms_without_resetting_controls(self):
        updated = packet()
        result = dict(race_id=RACE, revision='b'*64,
            observed_at=DAY+'T04:00:00Z', authority='official',
            order_status='confirmed', payout_status='pending',
            winning_triples=['3-1-2'], payouts_100yen={},
            source_comparison=[dict(source_id='keirin_jp', state='matched'),
                dict(source_id='kdreams', state='matched'),
                dict(source_id='netkeirin', state='different')],
            diagnostics=[], arms={
                'A': dict(state='hit', points=1, stake_yen=None, return_yen=None),
                'B': dict(state='miss', points=1, stake_yen=None, return_yen=None),
                'C': dict(state='pending', points=None, stake_yen=None, return_yen=None),
                'adjusted_A': dict(state='pending', points=None, stake_yen=None, return_yen=None),
                'adjusted_B': dict(state='pending', points=None, stake_yen=None, return_yen=None)})
        updated['files'][f'data/{DAY}/result_updates.json'] = source(dict(
            schema='RACE_AI_KEIRIN_RESULT_UPDATES_V1',
            observed_at=DAY+'T04:01:00Z', races=[result]))
        fixtures = json.dumps([packet(), updated], ensure_ascii=False)
        self.page.add_init_script('''
          const realTimeout=window.setTimeout;
          window.setTimeout=(fn,delay,...args)=>{
            if(delay===30000){window.__noteIdle=true;window.__noteTick=()=>fn(...args);return 0;}
            return realTimeout(fn,delay,...args);
          };
          window.__noteRefreshes=0;window.__noteClosed=0;window.__noteAllowResult=false;
          window.__noteFeedOverride={createSession:async()=>({
            refresh:async()=>{
              window.__noteRefreshes++;window.__noteIdle=false;
              if(window.__noteFailNext){window.__noteFailNext=false;throw Error('invented refresh failure');}
              const updated=window.__noteAllowResult;
              const data=await window.RaceKeirinNote.openPacket(('''+fixtures+''')[updated?1:0]);
              data.feed={entries:updated?2:1,revision:updated?'b':'a',providerDenied:false,checkedAt:'2030-01-15T04:02:00Z'};
              return data;
            },close:()=>{window.__noteClosed++;}
          })};
        ''')
        self.page.goto(self.base+'/#notefeed='+'Q'*160, wait_until='domcontentloaded')
        self.loaded()
        self.page.locator('#kn-variant').select_option('B')
        self.page.locator('#kn-search').fill('架空会場')
        self.page.get_by_role('button', name='検討リストに追加', exact=True).click()
        self.page.wait_for_function('document.readyState === "complete" && window.__noteIdle === true')
        refreshes = self.page.evaluate('window.__noteRefreshes')
        self.page.evaluate('window.__noteAllowResult=true;window.__noteTick()')
        self.page.locator('[data-result-arm="A"] strong').wait_for()
        self.assertEqual(self.page.locator('[data-result-arm="A"] strong').inner_text(), '的中')
        self.assertEqual(self.page.locator('[data-result-arm="B"] strong').inner_text(), '不的中')
        self.assertIn('未照合', self.page.locator('[data-result-arm="C"]').inner_text())
        self.assertIn('配当確認中', self.page.locator('.kn-live-result').inner_text())
        self.assertNotIn('0円', self.page.locator('.kn-live-result').inner_text())
        comparison = self.page.locator('.kn-result-comparison').inner_text()
        self.assertIn('保存資料との照合：', comparison)
        self.assertIn('Kドリームス：一致', comparison)
        self.assertIn('netkeirin：相違あり', comparison)
        self.assertEqual(self.page.locator('#kn-variant').input_value(), 'B')
        self.assertEqual(self.page.locator('#kn-search').input_value(), '架空会場')
        self.assertEqual(self.page.get_by_role('button', name='検討リストから外す', exact=True).count(), 1)
        self.assertIn('表示確認', self.page.locator('#kn-provenance').inner_text())
        self.assertIn('結果確認', self.page.locator('#kn-provenance').inner_text())
        self.page.evaluate('window.__noteFailNext=true;window.__noteTick()')
        status = self.page.locator('#kn-status')
        status.filter(has_text='更新を確認できませんでした').wait_for()
        self.assertIn('kn-error', status.get_attribute('class'))
        self.assertEqual(self.page.locator('[data-result-arm="A"] strong').inner_text(), '的中')
        self.page.evaluate('window.__noteTick()')
        status.filter(has_text='保存データの更新を確認しました').wait_for()
        self.assertNotIn('kn-error', status.get_attribute('class') or '')
        self.assertEqual(self.page.locator('#kn-variant').input_value(), 'B')
        self.assertEqual(self.page.locator('#kn-search').input_value(), '架空会場')
        self.assertEqual(self.page.get_by_role('button', name='検討リストから外す', exact=True).count(), 1)
        self.page.locator('#kn-clear').click()
        self.page.evaluate('window.__noteTick()')
        self.assertEqual(self.page.evaluate('window.__noteRefreshes'), refreshes+3)
        self.assertEqual(self.page.evaluate('window.__noteClosed'), 1)
        self.assertEqual(self.page.locator('.kn-race').count(), 0)
        self.assertEqual(self.external, [])
        self.assertEqual(self.errors, [])

    def test_frozen_four_arm_lists_and_their_basis_remain_separate_from_imported_references(self):
        from tests.test_keirin_frozen_forecast_view import frozen_document, DAY as frozen_day, RACE as frozen_race
        frozen = frozen_document(); saved = frozen['races'][0]
        value = packet(); files = {}
        for path, entry in value['files'].items():
            raw = entry['text'].replace(DAY, frozen_day).replace(RACE, frozen_race)
            files[path.replace(DAY,frozen_day)] = source(json.loads(raw))
        value.update(dates=[frozen_day], files=files)
        value['files'][f'data/{frozen_day}/frozen_forecasts.json'] = source(frozen)
        winner = saved['baseline']['A']['ranked_tickets'][0]
        expected = {'A':saved['baseline']['A']['ranked_tickets'],
            'B':saved['baseline']['B']['ranked_tickets'],
            'adjusted_A':saved['conditioned']['A_research']['ranked_tickets'],
            'adjusted_B':saved['conditioned']['B_research']['ranked_tickets']}
        arms = {name:dict(state='hit' if winner in tickets else 'miss', points=len(tickets),
                         stake_yen=None, return_yen=None) for name,tickets in expected.items()}
        arms['C'] = dict(state='pending', points=None, stake_yen=None, return_yen=None)
        result = dict(race_id=frozen_race, revision='b'*64, observed_at=frozen_day+'T09:00:00Z',
            authority='official', order_status='confirmed', payout_status='pending',
            winning_triples=['-'.join(map(str,winner))], payouts_100yen={},
            source_comparison=[], diagnostics=[], arms=arms)
        value['files'][f'data/{frozen_day}/result_updates.json'] = source(dict(
            schema='RACE_AI_KEIRIN_RESULT_UPDATES_V1', observed_at=frozen_day+'T09:01:00Z', races=[result]))
        self.page.goto(self.base, wait_until='domcontentloaded')
        self.page.locator('#keirin-note-open').click()
        self.page.locator('#kn-file').set_input_files(dict(name='invented-frozen.json',
            mimeType='application/json', buffer=canonical(value)))
        self.loaded()
        self.assertIn('締切前に保存した予想', self.page.locator('.kn-live-result').inner_text())
        self.assertEqual(self.page.locator('#kn-file').input_value(), '')
        for name,tickets in expected.items():
            panel = self.page.locator(f'[data-result-arm="{name}"]')
            self.assertEqual(panel.locator(f'[data-frozen-arm="{name}"] li').count(), len(tickets))
            combos = panel.locator('[data-frozen-combo]').evaluate_all('(items)=>items.map(x=>x.dataset.frozenCombo)')
            self.assertEqual(combos, ['-'.join(map(str,t)) for t in tickets])
            self.assertIn(f'点数 {len(tickets)}点', panel.inner_text())
            self.assertIn('締切前の保存', panel.inner_text())
            self.assertEqual(panel.locator('strong').inner_text(), '的中' if winner in tickets else '不的中')
        self.assertIn('未作成', self.page.locator('[data-result-arm="C"]').inner_text())
        self.assertEqual(self.page.locator('[data-frozen-arm="C"]').count(), 0)
        self.page.locator('#kn-variant').select_option('A')
        self.assertEqual(self.page.locator('.kn-ticket').count(), 1)
        self.assertIn('3', self.page.locator('.kn-ticket .kn-combo').inner_text())
        b = self.page.locator('[data-result-arm="B"]')
        b.get_by_text('展開の見立て・根拠', exact=True).click()
        self.assertEqual(b.locator('.kn-frozen-scenario').count(), len(saved['baseline']['B']['six_phase_scenarios']))
        self.assertEqual(b.locator('.kn-frozen-scenario').first.locator('li').count(), 6)
        adjusted = self.page.locator('[data-result-arm="adjusted_A"]')
        adjusted.get_by_text('近況の補正・根拠', exact=True).click()
        self.assertIn('落車前後の差', adjusted.inner_text())
        self.assertIn('比較材料が不足', adjusted.inner_text())
        self.assertEqual(self.external, [])
        self.assertEqual(self.errors, [])

    def test_nationwide_baseline_cards_show_all_tickets_and_missing_arms_without_prior_import(self):
        from tests.test_keirin_nationwide_forecast_view import nationwide_document, DAY as day, RACE as race
        doc=nationwide_document(); saved=doc['races'][0]['original']
        doc['races'][1].update(race_id=day.replace('-','')+'9802',venue_code=98,cutoff_at=day+'T09:00:00+09:00')
        expected={'A':saved['baseline']['A']['ranked_tickets'],'B':saved['baseline']['B']['ranked_tickets']}
        winner=expected['A'][0]
        arms={name:dict(state='pending',points=None,stake_yen=None,return_yen=None)
              for name in ('A','B','C','adjusted_A','adjusted_B')}
        for name,tickets in expected.items():
            arms[name]=dict(state='hit' if winner in tickets else 'miss',points=len(tickets),stake_yen=None,return_yen=None)
        result=dict(race_id=race,revision='b'*64,observed_at=day+'T09:00:00Z',authority='official',
            order_status='confirmed',payout_status='pending',winning_triples=['-'.join(map(str,winner))],
            payouts_100yen={},source_comparison=[],diagnostics=[],arms=arms)
        value=dict(schema='RACE_AI_KEIRIN_NOTE_VIEW_V1',formal_model_admission=False,
            production_weight_switch=False,dates=[day],source_commit='a'*40,imported_at=doc['observed_at'],
            files={f'data/{day}/nationwide_forecasts.json':source(doc),f'data/{day}/result_updates.json':source(dict(
                schema='RACE_AI_KEIRIN_RESULT_UPDATES_V1',observed_at=result['observed_at'],races=[result]))})
        self.page.goto(self.base,wait_until='domcontentloaded'); self.page.locator('#keirin-note-open').click()
        self.page.locator('#kn-file').set_input_files(dict(name='invented-national.json',mimeType='application/json',buffer=canonical(value)))
        self.loaded(); self.assertEqual(self.page.locator('#kn-file').input_value(),'')
        self.assertEqual(self.page.locator('.kn-national-race').count(),3)
        self.assertIn('全3レースの保存状況',self.page.locator('#kn-nationwide-summary').inner_text())
        self.assertIn('A/B保存済み 1 / 3件',self.page.locator('#kn-nationwide-summary').inner_text())
        self.assertTrue(self.page.locator('#kn-variant').is_disabled())
        ready=self.page.locator(f'[data-note-race="{race}"]')
        for name,tickets in expected.items():
            arm=ready.locator(f'[data-result-arm="{name}"]')
            combos=arm.locator('[data-frozen-combo]').evaluate_all('(items)=>items.map(x=>x.dataset.frozenCombo)')
            self.assertEqual(combos,['-'.join(map(str,t)) for t in tickets])
            self.assertEqual(len(set(combos)),len(tickets))
            self.assertEqual(arm.locator('strong').inner_text(),'的中' if winner in tickets else '不的中')
        for name in ('adjusted_A','adjusted_B'):
            self.assertIn('補正の保存待ち',ready.locator(f'[data-result-arm="{name}"]').inner_text())
            self.assertEqual(ready.locator(f'[data-frozen-arm="{name}"]').count(),0)
        self.assertIn('未作成',ready.locator('[data-result-arm="C"]').inner_text())
        ready.get_by_text('展開の見立て・根拠',exact=True).click()
        self.assertEqual(ready.locator('.kn-frozen-scenario').count(),len(saved['baseline']['B']['six_phase_scenarios']))
        unsupported=self.page.locator('[data-nationwide-state="UNSUPPORTED_CLASS_OR_ROUND"]')
        self.assertIn('種別・勝ち上がり条件の確認待ち',unsupported.inner_text())
        pending=self.page.locator(f'[data-note-race="{day.replace("-","")}9903"]')
        self.assertEqual(pending.locator('[data-frozen-combo]').count(),0)
        self.assertNotIn('0点',pending.inner_text())
        self.page.get_by_role('button',name='開催コード 98',exact=True).click()
        self.assertEqual(self.page.locator('.kn-national-race').count(),1)
        self.page.get_by_role('button',name='締切順・全会場',exact=True).click()
        ids=self.page.locator('.kn-national-race').evaluate_all('(items)=>items.map(x=>x.dataset.noteRace)')
        self.assertEqual(ids,[day.replace('-','')+'9802',race,day.replace('-','')+'9903'])
        for width in (390,1280):
            self.page.set_viewport_size(dict(width=width,height=844))
            self.assertTrue(self.page.locator('.kn-scroll').evaluate('(el)=>el.scrollWidth<=el.clientWidth+1'))
        self.assertEqual(self.external,[]); self.assertEqual(self.errors,[])

    def test_single_national_delta_distinguishes_unread_originals_from_missing_predictions(self):
        from tests.test_keirin_nationwide_forecast_view import nationwide_document, DAY as day, RACE as race
        doc=nationwide_document(); doc.update(inventory_complete=False,missing_venues=[88]); doc['races'][0]['original']=None
        value=dict(schema='RACE_AI_KEIRIN_NOTE_VIEW_V1',formal_model_admission=False,
            production_weight_switch=False,dates=[day],source_commit='a'*40,imported_at=doc['observed_at'],
            files={f'data/{day}/nationwide_forecasts.json':source(doc)})
        self.page.goto(self.base,wait_until='domcontentloaded'); self.page.locator('#keirin-note-open').click()
        self.page.locator('#kn-file').set_input_files(dict(name='invented-delta.json',mimeType='application/json',buffer=canonical(value)))
        self.loaded(); panel=self.page.locator('#kn-nationwide-summary')
        self.assertIn('確認できた3レース',panel.inner_text()); self.assertIn('全国の対象総数はまだ確認中',panel.inner_text())
        self.assertIn('未読込のレースが 1件',panel.inner_text()); self.assertIn('未確認の開催コード：88',panel.inner_text())
        row=self.page.locator(f'[data-note-race="{race}"]')
        self.assertIn('保存原本の読込待ち',row.locator('[data-result-arm="A"]').inner_text())
        self.assertIn('保存原本の読込待ち',row.locator('[data-result-arm="B"]').inner_text())
        self.assertEqual(row.locator('[data-frozen-combo]').count(),0); self.assertNotIn('0点',row.inner_text())
        self.assertEqual(self.external,[]); self.assertEqual(self.errors,[])


if __name__ == '__main__':
    unittest.main()
