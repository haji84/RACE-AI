/* Local synthetic interaction evidence; never a claim of real-race accuracy. */
'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..', 'web');
const output = path.resolve(process.env.UI_EVIDENCE_DIR || 'artifacts/ui-browser');
const fixture = JSON.parse(fs.readFileSync(path.join(root, 'data/example-synthetic-forecast-audit.json')));
fixture.records.forEach((r, i) => {
  r.event_date_jst = '2030-01-01';
  r.stage = 'P0';
  r.participants = Array.from({ length: [6,7,8,12][i] }, (_, n) => ({number:n+1, name:`架空テスト${n+1}`}));
  if (r.prediction) r.prediction.stage = 'P0';
  for (const p of r.comparison_predictions || []) p.stage = 'P1';
});
let browser, server;
const errors = [], requests = [], checks = [];
const mark = name => { checks.push(name); console.log('PASS', name); };
async function main() {
  fs.mkdirSync(output, {recursive:true});
  server = http.createServer((req,res) => {
    const name = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    const file = path.resolve(root, '.' + (name === '/' ? '/index.html' : name));
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) {res.writeHead(404);return res.end();}
    const type = {'.html':'text/html','.css':'text/css','.js':'text/javascript','.json':'application/json'}[path.extname(file)] || 'application/octet-stream';
    res.writeHead(200, {'Content-Type':type});fs.createReadStream(file).pipe(res);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base = `http://127.0.0.1:${server.address().port}/`;
  browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {}), args:['--no-sandbox']});
  for (const width of [320,390,1440,1920]) {
    const context = await browser.newContext({viewport:{width,height:width<600?844:1080}, deviceScaleFactor:1});
    await context.tracing.start({screenshots:true,snapshots:true});
    const page = await context.newPage();
    page.on('pageerror', e=>errors.push(e.message));
    page.on('request', req=>requests.push(req.url()));
    await page.clock.install({time:new Date('2030-01-01T00:30:00Z')});
    await page.goto(base);
    await page.locator('#source-state').waitFor();
    assert.match(await page.locator('#source-state').innerText(), /未取得|未読込|未接続/);
    assert.equal(await page.locator('#page-home .race-card').count(),0);
    await page.locator('[data-page="research"]').filter({visible:true}).first().click();
    assert.equal(await page.locator('#all-model-coverage tbody tr[data-model-id]').count(),16,'empty data must not hide any registered model family');
    await page.locator('[data-page="home"]').filter({visible:true}).first().click();
    mark(`${width}: honest empty startup`);
    await page.locator('#race-file').setInputFiles({name:'synthetic.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture))});
    await page.waitForFunction(()=>document.querySelector('#source-state').textContent.includes('合成'));
    for (const sport of ['boat','keirin','autorace','horse']) {
      await page.locator(`[data-sport="${sport}"]`).first().click();
      assert.equal(await page.locator('#page-home .race-card').count(),1,`${sport} saved race remains visible, including missing forecasts`);
      const title=await page.locator('#page-home .race-card').innerText();
      assert.match(title, new RegExp({boat:'ボート',keirin:'競輪',autorace:'オート',horse:'競馬'}[sport]));
    }
    await page.locator('[data-sport="boat"]').first().click();
    const nav = async name => page.locator(`[data-page="${name}"]`).filter({visible:true}).first().click();
    await nav('races');
    await page.locator('#race-search').fill('not-present');
    assert.equal(await page.locator('#page-races .race-card').count(),0);
    await page.locator('#race-search').fill('');
    assert.ok(await page.locator('#page-races .race-card').count()>0);
    await page.locator('#period-filter').selectOption('week');
    assert.equal(await page.locator('#page-races .race-card').count(),1);
    await page.locator('#status-filter').selectOption('HIT');
    assert.equal(await page.locator('#page-races .race-card').count(),0,'synthetic match cannot be official HIT');
    await page.locator('#status-filter').selectOption('all');
    await page.locator('#period-filter').selectOption('day');
    mark(`${width}: local import, four sports and search`);
    for (const name of ['home','races','detail','picks','results','research','settings']) {
      if (name==='detail') {
        await nav('races');
        await page.locator('#page-races [data-open-race]').first().click();
      } else await nav(name);
      await page.locator(`#page-${name}`).waitFor({state:'visible'});
      if(name==='research') assert.equal(await page.locator('#all-model-coverage tbody tr[data-model-id]').count(),16,'all-model research coverage includes unavailable and inapplicable families');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false,`${width} ${name} overflow`);
      await page.screenshot({path:path.join(output,`${width}-${name}.png`),fullPage:true});
    }
    mark(`${width}: seven-page navigation and no horizontal overflow`);
    await nav('results');
    assert.match(await page.locator('#result-metrics').innerText(), /未検証/);
    assert.ok(!(await page.locator('#result-metrics').innerText()).includes('100%'),'synthetic hits cannot become official metrics');
    await nav('races');await page.locator('#page-races [data-open-race]').first().click();
    for(const tab of ['outlook','participants','preview','analysis','history']) {
      await page.locator(`[data-detail-tab="${tab}"]`).click();
      assert.equal(await page.locator(`[data-detail-tab="${tab}"]`).getAttribute('aria-selected'),'true');
    }
    const options=await page.locator('#prediction-select option').count();
    assert.ok(options>=2,'saved comparison model selectable');
    await page.locator('#prediction-select').selectOption({index:1});
    await page.locator('#prediction-select').selectOption({index:0});
    assert.ok((await page.locator('#race-detail').innerText()).includes(fixture.records[0].prediction.prediction_sha256),'original prediction SHA displayed');
    mark(`${width}: detail tabs and saved model/stage switching`);
    await nav('picks');
    await page.locator('#race-budget').fill('2000');
    await page.locator('#ticket-form button[type="submit"]').click();
    assert.ok(await page.locator('.ticket-row').count()>0,'manual candidate added');
    await page.locator('.ticket-amount').first().fill('200');
    await page.locator('.ticket-amount').first().dispatchEvent('change');
    await page.locator('#confirm-candidates').click();
    assert.match(await page.locator('#ticket-message').innerText(),/候補|確認/);
    assert.match(await page.locator('#allocation-summary').innerText(),/200/);
    await page.locator('[data-delete-ticket]').first().click();
    assert.equal(await page.locator('.ticket-row').count(),0);
    mark(`${width}: editable candidates, confirm and delete`);
    await nav('settings');
    const storage=await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}));
    assert.ok(!storage.includes(fixture.records[0].prediction.prediction_sha256),'private forecast not automatically persisted');
    await page.clock.setFixedTime(new Date('2030-01-01T15:30:00Z'));
    await nav('races');
    await page.locator('#selected-date').fill('2030-01-01');
    await page.locator('#selected-date').dispatchEvent('change');
    assert.ok(await page.locator('#page-races .race-card').count()>0,'historical saved data retained across JST midnight');
    await page.locator('#race-file').setInputFiles({name:'invalid.json',mimeType:'application/json',buffer:Buffer.from('{}')});
    await page.waitForFunction(()=>document.querySelector('#file-message').textContent.length>0);
    assert.ok(await page.locator('#page-races .race-card').count()>0,'bad import preserves loaded records');
    await page.keyboard.press('Tab');
    assert.notEqual(await page.evaluate(()=>document.activeElement.tagName),'BODY');
    mark(`${width}: midnight history, rejected import and keyboard`);
    const longFixture=structuredClone(fixture);
    longFixture.records[0].venue='長い会場名'.repeat(15);
    longFixture.records[0].participants[0].name='長い選手名'.repeat(40);
    await page.locator('#race-file').setInputFiles({name:'long-labels.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(longFixture))});
    await page.waitForFunction(label=>document.querySelector('#page-races').textContent.includes(label),longFixture.records[0].venue);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false,'bounded long input cannot overflow');
    if (process.env.UI_JOURNAL_EXPORT && width===390) {
      const generated=JSON.parse(fs.readFileSync(process.env.UI_JOURNAL_EXPORT,'utf8'));
      await page.locator('#race-file').setInputFiles({name:'engine-journal.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(generated))});
      const saved=generated.records.find(r=>r.sport==='boat' && r.prediction);
      await page.waitForFunction(()=>document.querySelector('#page-races').textContent.includes('fixture'));
      await page.locator('#page-races [data-open-race]').first().click();
      assert.ok((await page.locator('#race-detail').innerText()).includes(saved.prediction.prediction_sha256),'actual engine saved SHA is displayed unchanged');
      await page.locator('[data-detail-tab="history"]').click();
      assert.ok((await page.locator('#race-detail').innerText()).includes('改訂'));
      assert.equal(generated.records.find(r=>r.race_id===saved.race_id).result_revisions.length,2);
      mark('existing four-sport engine -> saved SQLite -> read-only projection -> browser, unchanged SHA and separate revisions');
    }
    await context.tracing.stop({path:path.join(output,`${width}-interaction.zip`)});
    await context.close();
  }
  assert.deepEqual(errors,[],'no page errors');
  assert.ok(requests.every(url=>url.startsWith(base)),'no external source requests');
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({scope:'SYNTHETIC_ONLY',checks,errors,source_requests:0,widths:[320,390,1440,1920]},null,2));
  await browser.close();browser=null;await new Promise(resolve=>server.close(resolve));server=null;
}
main().catch(async error=>{console.error(error);if(browser)await browser.close();if(server)server.close();process.exitCode=1;});
