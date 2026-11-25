'use strict';
// Invented riders and source bindings; all browser traffic stays on loopback.
const { describe, test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { createHash } = require('node:crypto');
let chromium;
try { ({ chromium } = require('playwright')); } catch {}
if(!chromium&&process.env.RACE_AI_NODE_PLAYWRIGHT)({chromium}=require(process.env.RACE_AI_NODE_PLAYWRIGHT));
if(!chromium&&process.env.RACE_AI_REQUIRE_RIDER_BROWSER==='1')throw new Error('Rider browser checks require the installed Playwright driver.');
const ROOT = path.resolve(__dirname, '..'), DAY = '2030-01-15', RACE = '203001159801';
const SOURCE_TIME = DAY + 'T01:00:00Z', PACKET_SHA = 'c'.repeat(64);
const source = value => { const text = JSON.stringify(value); return { text, bytes: Buffer.byteLength(text),
  sha256: createHash('sha256').update(text).digest('hex') }; };

function packet() {
  const row = { race_id: RACE, venue: '架空会場', race_no: 1, deadline_time: '12:00', start_time: '12:05',
    riders: [1, 2, 3].map(number => ({ number, name: '架空選手' + number, score: 80 + number,
      style: '追込', S: number, H: number + 1, B: number + 2, win_rate: 10, top2_rate: 20,
      top3_rate: 30, comment: '架空の本人コメント', recent_meets: ['架空の過去開催'],
      field_sources: { statistics: 'https://keirin.kdreams.jp/test/' } })), lines: [[1, 2], [3]],
    source_url: 'https://keirin.kdreams.jp/test/', fetched_at: SOURCE_TIME };
  const normal = { race_id: RACE, analysis_created_at: SOURCE_TIME, confidence: '高', scenarios: [],
    headline: '架空の保存分析', tickets: [{ combo: '1-2-3', role: '本線' }, { combo: '3-2-1', role: '押さえ' }] };
  return { schema: 'RACE_AI_KEIRIN_NOTE_VIEW_V1', formal_model_admission: false, production_weight_switch: false,
    source_commit: 'a'.repeat(40), imported_at: SOURCE_TIME, dates: [DAY], files: {
      ['data/' + DAY + '/races.json']: source({ races: [row] }),
      ['data/' + DAY + '/forecasts.json']: source([normal]),
      ['data/' + DAY + '/two_car_forecasts.json']: source([{ ...normal, tickets: [{ combo: '1-2', role: '本線' }] }]),
      ['data/' + DAY + '/three_car_rollover_forecasts.json']: source([{ ...normal, tickets: [normal.tickets[0]] }]) } };
}

function projection(version = 'fixture-v1') {
  return { schema: 'RACE_AI_KEIRIN_JOINT_PROJECTION_V1', race_id: RACE, cars: [1, 2, 3],
    generated_at: DAY + 'T01:01:00Z', cutoff_at: DAY + 'T03:00:00Z', source_as_of: SOURCE_TIME,
    source_forecast_generated_at: SOURCE_TIME, model_id: 'invented-comparison-B', model_version: version,
    input_sha256: 'b'.repeat(64), source_packet_sha256: PACKET_SHA, source_joint_sha256: 'd'.repeat(64),
    scope: 'PROSPECTIVE_RESEARCH', premise: 'ALL_FINISH_NO_TIES', calibration_status: 'UNVALIDATED',
    riders: [1, 2, 3].map(car => ({ car, name: '架空選手' + car, registration: null,
      rank_probabilities: [1 / 3, 1 / 3, 1 / 3], top2_probability: 2 / 3, top3_probability: 1,
      outside_top3_probability: 0, most_likely_rank: 1, expected_rank: 2 })),
    ranked_markets: { '3t': [{ order: [1, 2, 3], probability: 1 / 6 }],
      '2t': [{ order: [1, 2], probability: 1 / 6 }] } };
}

describe('rider cards in the GitHub note view', { skip: !chromium }, () => {
  let browser;
  before(async () => { browser = await chromium.launch({ headless: true,
    executablePath: process.env.RACE_AI_TEST_CHROMIUM || (fs.existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined),
    args: ['--no-sandbox'] }); });
  after(async () => { await browser?.close(); });

  async function open(t, options = {}) {
    const components = ['keirin-note-source/staking.js', 'keirin-note-source/staking_flexible.js',
      'keirin-note-source/rollover.js', 'confidence.js', 'keirin-joint-forecast.js', 'keirin-rider-history.js',
      'keirin-note-model.js', 'keirin-note-feed.js'];
    const script = 'window.RaceNoteInitialFragment=location.hash;\n' + components.map(name =>
      fs.readFileSync(path.join(ROOT, 'web', name), 'utf8')).join('\n') +
      '\nObject.assign(window.RaceKeirinNoteFeed,window.__noteFeedOverride);\n' +
      fs.readFileSync(path.join(ROOT, 'web/keirin-note-view.js'), 'utf8');
    const html = '<!doctype html><html><head><meta charset="utf-8"><meta name="referrer" content="no-referrer">' +
      '<meta http-equiv="Content-Security-Policy" content="default-src \'none\';script-src \'self\';style-src \'self\';connect-src \'self\';img-src \'self\' data:;base-uri \'none\';form-action \'none\'">' +
      '<link rel="stylesheet" href="/style.css"><script defer src="/note.js"></script></head><body><main><div id="data-banner"></div></main></body></html>';
    const assets = new Map([['/', [html, 'text/html']], ['/note.js', [script, 'text/javascript']],
      ['/style.css', [fs.readFileSync(path.join(ROOT, 'web/race-style-core.css'), 'utf8') + '\n' +
        fs.readFileSync(path.join(ROOT, 'web/keirin-note.css'), 'utf8'), 'text/css']]]);
    const server = http.createServer((request, response) => {
      const asset = assets.get(new URL(request.url, 'http://localhost').pathname);
      response.writeHead(asset ? 200 : 404, { 'content-type': (asset?.[1] || 'text/plain') + '; charset=utf-8' });
      response.end(asset?.[0] || 'not found');
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const origin = 'http://127.0.0.1:' + server.address().port;
    let context, page;
    const external = [], errors = [], violations = [];
    t.after(async () => {
      try {
        assert.deepEqual(external, []); assert.deepEqual(errors, []);
        if (page && !page.isClosed()) violations.push(...await page.evaluate('window.__riderCspViolations||[]'));
        assert.deepEqual(violations, []);
      } finally {
        await context?.close();
        server.closeAllConnections();
        await new Promise(resolve => server.close(resolve));
      }
    });
    context = await browser.newContext({ viewport: { width: options.width || 390, height: 844 } });
    page = await context.newPage();
    page.setDefaultTimeout(5000);
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      if (route.request().url().startsWith(origin + '/')) return route.continue();
      external.push(route.request().url()); return route.abort();
    });
    await page.addInitScript(({ value, forecasts, options, race, day, sourceTime, packetSha }) => {
      document.addEventListener('securitypolicyviolation', event => {
        (window.__riderCspViolations ||= []).push(event.violatedDirective);
      });
      window.__riderPhase = 0;
      window.__noteFeedOverride = { createSession: async () => ({ refresh: async () => {
        const data = await window.RaceKeirinNote.openPacket(value), row = data.days.get(day)[0];
        const phase = window.__riderPhase;
        if (options.state !== 'missing') {
          row.jointForecast = structuredClone(forecasts[phase]);
          row.jointForecastBindings = { race_id: race, cars: [1, 2, 3],
            source_packet_sha256: packetSha, source_forecast_generated_at: sourceTime,
            cutoff_at: day+'T03:00:00Z', source_as_of: sourceTime };
          if (options.state === 'missing_binding') delete row.jointForecastBindings;
          if (options.state === 'wrong_hash') row.jointForecastBindings.source_packet_sha256 = 'f'.repeat(64);
          if (options.state === 'wrong_race') row.jointForecastBindings.race_id = '203001159802';
          if (options.state === 'wrong_cars') row.jointForecastBindings.cars = [1, 2, 4];
          if (options.state === 'wrong_cutoff') row.jointForecast.cutoff_at = row.jointForecastBindings.cutoff_at = day+'T04:00:00Z';
        }
        if (options.nationwide) row.nationwideOnly = true;
        if (options.comparison) row.comparisonRiders = [1, 2, 3].map(car => ({ car, name: '架空選手'+car,
          racer_class: 'S1', style: 'NIGE', competition_points: 100+car, recent_form_score: .123,
          top2_rate: 45.6, top3_rate: 67.8, h_count: 8, b_count: 9 }));
        if (phase) row.riders[2].comment = '更新された架空コメント';
        data.feed = { revision: String(phase), checkedAt: sourceTime, providerDenied: false };
        return data;
      }, close() {} }) };
    }, { value: packet(), forecasts: [projection(), projection('fixture-v2')], options,
      race: RACE, day: DAY, sourceTime: SOURCE_TIME, packetSha: PACKET_SHA });
    await page.goto(origin + '/#notefeed=' + 'Q'.repeat(160), { waitUntil: 'domcontentloaded' });
    try {
      await page.locator('#kn-status').filter({ hasText: /端末内で開きました|保存データの更新を確認しました/ }).waitFor();
    } catch (error) {
      throw new Error('Invented feed did not load: ' + await page.locator('#kn-status').textContent() +
        ' / ' + await page.evaluate('String(window.__riderFeedError||"no feed error")'));
    }
    return page;
  }

  test('a rider name opens checked probabilities and switching, Escape and return preserve controls', async t => {
    const page = await open(t);
    assert.equal(await page.locator('.kn-rider-list button').count(), 3);
    await page.locator('[data-budget]').selectOption('3000');
    await page.locator('.kn-ticket input').nth(1).uncheck();
    await page.getByRole('button', { name: '検討リストに追加', exact: true }).click();
    const before = await page.locator('.kn-budget').innerText();
    await page.locator('.kn-rider-list [data-rider-car="1"]').click();
    const modal = page.locator('#kn-rider-details');
    await modal.waitFor({ state: 'visible' });
    assert.equal(await modal.locator('meter').count(), 3);
    assert.match(await modal.innerText(), /66\.7%/);
    assert.match(await modal.innerText(), /比較B.*旧買い目|保存済みの旧買い目/);
    assert.match(await modal.innerText(), /番手|先頭/);
    await modal.locator('#kn-rider-select').selectOption('2');
    assert.equal(await modal.locator('#kn-rider-heading').innerText(), '2番 架空選手2');
    await page.keyboard.press('Escape');
    await modal.waitFor({ state: 'hidden' });
    assert.equal(await page.locator('#keirin-note-dialog').evaluate(element => element.open), true);
    assert.equal(await page.evaluate('document.querySelector(".kn-host").shadowRoot.activeElement.dataset.riderCar'), '1');
    assert.equal(await page.locator('.kn-budget').innerText(), before);
    assert.equal(await page.locator('[data-budget]').inputValue(), '3000');
    assert.equal(await page.locator('.kn-ticket input').nth(1).isChecked(), false);
    assert.equal(await page.getByRole('button', { name: '検討リストから外す', exact: true }).count(), 1);
    await page.locator('#kn-market').selectOption('2t');
    assert.equal(await page.locator('.kn-ticket').count(), 1);
    await page.locator('#kn-market').selectOption('3t');
    await page.locator('[data-prediction="rollover"]').click();
    assert.equal(await page.locator('.kn-ticket').count(), 1);
    await page.locator('.kn-rollover summary').click();
    await page.locator('#kn-return-one').fill('3500');
    assert.equal(await page.locator('#kn-return-one').inputValue(), '3500');
    assert.match(await page.locator('#kn-roll-result').innerText(), /次の候補/);
    await page.locator('[data-prediction="flexible"]').click();
    await page.locator('#kn-confidence').selectOption('high_plus');
    assert.equal(await page.locator('.kn-race').count(), 1);
  });

  test('unavailable or unbound probabilities stay held while actual roster facts remain accessible', async t => {
    for (const state of ['missing', 'missing_binding', 'wrong_hash', 'wrong_race', 'wrong_cars', 'wrong_cutoff']) {
      const page = await open(t, { state });
      assert.equal(await page.locator('.kn-rider-list button').count(), 3);
      await page.locator('.kn-rider-list [data-rider-car="1"]').click();
      const modal = page.locator('#kn-rider-details');
      assert.equal(await modal.locator('meter').count(), 0, state);
      assert.match(await modal.innerText(), state === 'missing' ? /着順確率.*未取得/ : /表示.*保留/, state);
      assert.match(await modal.innerText(), /81/);
      await modal.getByText('コメント・近況・出典', { exact: true }).click();
      assert.match(await modal.innerText(), /架空の本人コメント/);
      await modal.getByText('戦術・能力の資料', { exact: true }).click();
      assert.equal(await modal.locator('[data-rider-ability]').count(), 6);
      assert.equal(await modal.locator('[data-rider-ability]').filter({ hasText: '未取得' }).count(), 6);
      await modal.getByRole('button', { name: '閉じる', exact: true }).click();
      await page.locator('#kn-clear').click();
      assert.equal(await modal.locator('meter').count(), 0);
    }
  });

  test('nationwide rows expose every rider and an open card refreshes without losing its selection or return focus', async t => {
    const page = await open(t, { nationwide: true });
    assert.equal(await page.locator('.kn-national-race .kn-rider-list button').count(), 3);
    await page.locator('.kn-rider-list [data-rider-car="3"]').click();
    const modal = page.locator('#kn-rider-details');
    await page.evaluate('window.__riderPhase=1;document.dispatchEvent(new Event("visibilitychange"))');
    await page.waitForFunction(() => document.querySelector('.kn-host').shadowRoot.querySelector('#kn-rider-facts').textContent.includes('fixture-v2'));
    assert.equal(await modal.locator('#kn-rider-select').inputValue(), '3');
    await modal.getByText('コメント・近況・出典', { exact: true }).click();
    assert.match(await modal.innerText(), /更新された架空コメント/);
    for (const width of [320, 390, 1440]) {
      await page.setViewportSize({ width, height: 844 });
      assert.equal(await modal.evaluate(element => element.scrollWidth <= element.clientWidth + 1), true);
    }
    await modal.getByRole('button', { name: '閉じる', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.kn-host').shadowRoot.activeElement?.dataset.riderCar === '3');
    assert.equal(await page.evaluate('document.querySelector(".kn-host").shadowRoot.activeElement.dataset.riderCar'), '3');
  });

  test('long and recent observed finishes open independently of a joint forecast',async t=>{
    const page=await open(t,{state:'missing'});
    const {fixture,file,prefix}=require('./keirin_rider_history_fixture.cjs');
    const v=fixture();
    v.packet.files[prefix+'rider_histories.json']=file(v.raw);
    await page.locator('#kn-file').setInputFiles({name:'invented-history.json',mimeType:'application/json',
      buffer:Buffer.from(JSON.stringify(v.packet))});
    const first=page.locator('.kn-rider-list button').filter({hasText:'架空1'});
    await first.click();
    const modal=page.locator('#kn-rider-details');
    await modal.getByText('長期・直近の着順履歴',{exact:true}).click();
    const details=modal.locator('.kn-rider-history');
    assert.equal(await details.locator('tbody tr').count(),11);
    assert.match(await details.innerText(),/2走/);
    assert.match(await details.innerText(),/締切後/);
    await modal.locator('#kn-rider-select').selectOption('2');
    await modal.getByText('長期・直近の着順履歴',{exact:true}).click();
    assert.match(await details.innerText(),/0走/);
    assert.doesNotMatch(await details.innerText(),/0\.0%/);
  });

  test('fresh comparison input statistics retain their own source time and do not replace saved roster statistics', async t => {
    const page=await open(t,{comparison:true});
    await page.locator('.kn-rider-list [data-rider-car="1"]').click();
    const fresh=page.locator('#kn-rider-details .kn-comparison-input');
    assert.equal(await fresh.count(),1);
    const text=await fresh.innerText();
    for(const expected of ['比較Bの入力資料','S1','逃げ','101','12.3%','45.6%','67.8%'])assert.ok(text.includes(expected),expected);
    assert.equal(await fresh.locator('time').getAttribute('datetime'),SOURCE_TIME);
    assert.match(await page.locator('#kn-rider-details .kn-rider-source-stats').innerText(),/81/);
    await page.locator('#kn-rider-details [data-rider-close]').click();
    await page.locator('.kn-rider-list [data-rider-car="2"]').click();
    assert.match(await fresh.innerText(),/102/);
  });
});
