'use strict';

const { after, before, describe, test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

let chromium;
try { ({ chromium } = require('playwright')); } catch {}
if (!chromium && process.env.RACE_AI_NODE_PLAYWRIGHT) {
  ({ chromium } = require(process.env.RACE_AI_NODE_PLAYWRIGHT));
}
if (!chromium && process.env.RACE_AI_REQUIRE_PUBLIC_BROWSER === '1') {
  throw new Error('Public forecast browser checks require Playwright.');
}

const WEB = path.join(__dirname, '..', 'web');
const BASE = 'https://raw.githubusercontent.com/haji84/RACE-AI/state/keirin-public-forecasts/forecasts/';
const TODAY = '2026-11-26';
const PAST = '2026-11-25';
const MISSING = '2026-11-24';
const INVALID = '2026-11-23';
const A = [[1, 2, 3], [1, 3, 2], [2, 1, 3], [2, 3, 1], [3, 1, 2], [3, 2, 1], [1, 4, 3], [1, 3, 4]];

function snapshot(day) {
  const raceDay = day.replaceAll('-', '');
  return {
    schema: 'RACE_AI_KEIRIN_PUBLIC_FORECASTS_V1', day, published_at: day + 'T12:35:00+09:00',
    races: [
      { race_id: raceDay + '2601', cutoff_at: day + 'T12:30:00+09:00', status: 'saved',
        saved_at: day + 'T12:25:13+09:00', a: A, b: A.slice().reverse() },
      { race_id: raceDay + '1102', cutoff_at: null, status: 'pending', saved_at: null, a: [], b: [] }
    ]
  };
}

describe('KEIRIN anonymous forecast page', { skip: !chromium }, () => {
  let browser;
  let server;
  let origin;
  before(async () => {
    const chrome = ['/usr/bin/chromium', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(fs.existsSync);
    browser = await chromium.launch({
      executablePath: process.env.RACE_AI_TEST_CHROMIUM || chrome,
      args: ['--no-sandbox']
    });
    server = http.createServer((request, response) => {
      const name = new URL(request.url, 'http://localhost').pathname.slice(1) || 'index.html';
      const suffix = path.extname(name);
      const type = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' }[suffix];
      if (!type || name !== path.basename(name) || !fs.existsSync(path.join(WEB, name))) {
        response.writeHead(404).end();
        return;
      }
      let body = fs.readFileSync(path.join(WEB, name), 'utf8');
      if (name === 'index.html') {
        // Match the production shell's encrypted mode using an invented endpoint.
        body = body.replace('</head>', '<meta name="race-ai-encrypted-saved-view" content="./unused.json"></head>');
      }
      response.writeHead(200, { 'content-type': type + '; charset=utf-8' }).end(body);
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    origin = 'http://127.0.0.1:' + server.address().port;
  });
  after(async () => {
    await browser?.close();
    if (server) await new Promise(resolve => server.close(resolve));
  });

  async function open(t, hash, serve) {
    const context = await browser.newContext({ viewport: { width: 360, height: 760 }, timezoneId: 'America/Los_Angeles' });
    const page = await context.newPage();
    const calls = [], errors = [];
    t.after(async () => {
      await context.close();
      assert.deepEqual(errors, []);
    });
    page.setDefaultTimeout(3000);
    page.on('pageerror', error => errors.push(error.message));
    await page.clock.setFixedTime(new Date('2026-11-26T04:00:00Z'));
    await page.route('**/*', async route => {
      const request = route.request(), url = request.url();
      if (url.startsWith(origin + '/')) return route.continue();
      if (!url.startsWith(BASE)) return route.abort();
      calls.push(url);
      const headers = await request.allHeaders();
      assert.equal(headers.authorization, undefined);
      assert.equal(headers.cookie, undefined);
      assert.equal(headers.referer, undefined);
      const result = await serve(url.slice(BASE.length, -5), route);
      if (result !== undefined) await route.fulfill({
        status: result === null ? 404 : 200, json: result,
        headers: { 'access-control-allow-origin': '*' }
      });
    });
    await page.goto(origin + '/' + hash);
    return { page, calls };
  }

  test('direct anonymous route shows JST coverage, tickets and separate clocks on mobile', async t => {
    const { page, calls } = await open(t, '#keirin-public', snapshot);
    await page.getByRole('heading', { name: '競輪の公開予想', exact: true }).waitFor();
    assert.equal(await page.getByLabel('対象日（JST）').inputValue(), TODAY);
    const races = page.locator('#keirin-public-races');
    await races.getByText('西武園 1R', { exact: true }).waitFor();
    assert.deepEqual(calls, [BASE + TODAY + '.json']);
    assert.match(await page.getByRole('status').filter({ visible: true }).innerText(), /1\s*\/\s*2\s*レース/);
    assert.match(await races.innerText(), /締切\s*12:30/);
    assert.match(await races.innerText(), /保存\s*12:25:13/);
    assert.match(await page.locator('#page-keirin-public').innerText(), /公開データ更新\s*2026\/11\/26\s*12:35:00/);
    assert.match(await races.innerText(), /函館 2R[\s\S]*未掲載/);
    assert.equal(await races.getByRole('listitem').count(), 16);
    assert.match(await races.getByRole('listitem').first().innerText(), /1.2.3/);
    assert.equal(await page.getByText('個人用 · 自動投票なし', { exact: true }).isVisible(), false);
    assert.equal(await page.getByRole('button', { name: '買い目' }).count(), 0);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    assert.equal(new URL(page.url()).hash, '#keirin-public');
  });

  test('the entry works on the existing shell and past dates distinguish saved, missing and invalid data', async t => {
    const { page, calls } = await open(t, '', day => {
      if (day === MISSING) return null;
      const saved = snapshot(day);
      if (day === PAST) saved.races[0].b = A.slice(0, 2);
      if (day === INVALID) saved.races[0].saved_at = saved.races[0].cutoff_at;
      return saved;
    });
    await page.getByRole('link', { name: '競輪の公開予想', exact: true }).click();
    await page.getByText('西武園 1R', { exact: true }).waitFor();
    assert.equal(new URL(page.url()).hash, '#keirin-public');
    const date = page.getByLabel('対象日（JST）');
    await date.fill(PAST);
    await page.getByText('2026/11/25 12:35:00', { exact: true }).waitFor();
    assert.equal(await page.locator('#keirin-public-races').getByRole('listitem').count(), 10);
    await date.fill(MISSING);
    await page.getByText('この日の公開予想は掲載されていません。', { exact: true }).waitFor();
    assert.equal(await page.getByText('西武園 1R', { exact: true }).count(), 0);
    await date.fill(INVALID);
    await page.getByText('公開データの形式を確認できません。', { exact: true }).waitFor();
    await date.fill('2026-11-27');
    await page.getByText('選択できる範囲の日付を入力してください。', { exact: true }).waitFor();
    assert.deepEqual(calls, [TODAY, PAST, MISSING, INVALID].map(day => BASE + day + '.json'));
    await page.goBack();
    await page.getByRole('heading', { name: '今日のレースを、確かなデータで。' }).waitFor();
    assert.equal(new URL(page.url()).hash, '');
  });

  test('a saved-view fragment stays private and survives a visit to the public page', async t => {
    const fragment = '#saved=' + 'a'.repeat(64) + '.' + 'x'.repeat(43);
    const { page, calls } = await open(t, fragment, snapshot);
    await page.getByRole('heading', { name: '今日のレースを、確かなデータで。' }).waitFor();
    assert.equal(await page.getByRole('heading', { name: '競輪の公開予想', exact: true }).count(), 0);
    assert.equal(new URL(page.url()).hash, fragment);
    assert.deepEqual(calls, []);
    await page.getByRole('link', { name: '競輪の公開予想', exact: true }).click();
    await page.getByText('西武園 1R', { exact: true }).waitFor();
    assert.equal(new URL(page.url()).hash, '#keirin-public');
    await page.goBack();
    await page.getByRole('heading', { name: '今日のレースを、確かなデータで。' }).waitFor();
    assert.equal(new URL(page.url()).hash, fragment);
    assert.deepEqual(calls, [BASE + TODAY + '.json']);
  });
});
