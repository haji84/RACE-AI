/* Invented UI-only race; the six named portraits demonstrate identity, not an actual entry list. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {spawnSync} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '../web');
const entries = [['3415','松井繁'],['3897','白井英治'],['3941','池田浩二'],['4238','毒島誠'],['4320','峰竜太'],['4444','桐生順平']];
const fixture = {schema:'RACE_AI_FORECAST_AUDIT_V1', dataset_status:'REAL_REPORTED', records:[{
  race_id:'boat:2030-01-01:portrait-ui:1', sport:'boat', venue:'イラスト表示テスト（架空レース）', race_no:1,
  event_date_jst:'2030-01-01', cutoff_at:'2030-01-01T10:00:00+09:00', offering_status:'TRIFECTA_OFFERED',
  source_provenance:'ILLUSTRATION_UI_TEST_ONLY', source_sha256:'a'.repeat(64), scope:'research',
  prediction:null, result:null,
  participants:entries.map(([registration_no,name],i)=>({number:i+1, registration_no, name}))
}]};
let browser, server;
(async()=>{
  const requests = [], errors = [];
  const baseline = process.env.UI_PORTRAITS_BASELINE ? spawnSync('git',['show','HEAD:web/app.js'],{cwd:path.join(root,'..')}).stdout : null;
  server = http.createServer((req,res)=>{
    const relative = new URL(req.url,'http://localhost').pathname.replace(/^\/RACE-AI\//,'');
    const file = path.resolve(root, relative || 'index.html');
    if (!file.startsWith(root+path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {res.statusCode=404;return res.end();}
    res.setHeader('Content-Type', {'.js':'text/javascript','.css':'text/css','.html':'text/html','.json':'application/json','.webp':'image/webp'}[path.extname(file)] || 'application/octet-stream');
    res.end(baseline && relative==='app.js' ? baseline : fs.readFileSync(file));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base = process.env.PORTRAITS_DEPLOYED_URL || `http://127.0.0.1:${server.address().port}/RACE-AI/`;
  browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : fs.existsSync('/usr/bin/chromium') ? {executablePath:'/usr/bin/chromium'} : {}),args:['--no-sandbox']});
  const evidence = path.resolve(process.env.UI_PORTRAIT_EVIDENCE || 'artifacts/ui-portraits');
  fs.mkdirSync(evidence,{recursive:true});
  const load = async(page,data=fixture)=>{
    await page.evaluate(()=>document.getElementById('file-message').textContent='');
    await page.locator('#race-file').setInputFiles({name:'illustration-ui-test.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(data))});
    await page.waitForFunction(()=>document.querySelector('#file-message').textContent.length>0);
    await page.locator('[data-page="home"]').filter({visible:true}).first().click();
    await page.waitForFunction(()=>document.querySelector('#page-home .racer-card'));
  };
  for (const width of [320,390,1440]) {
    const context = await browser.newContext({viewport:{width,height:900}});
    const page = await context.newPage();
    page.on('request',r=>requests.push(r.url())); page.on('pageerror',e=>errors.push(e.message));
    await page.clock.install({time:new Date('2030-01-01T00:00:00Z')});
    await page.goto(base); await load(page);
    const home = '#page-home .racer-card img.racer-portrait';
    assert.equal(await page.locator(home).count(),6,'all six own illustrations must appear on the home card');
    for (const img of await page.locator(home).all()) await img.scrollIntoViewIfNeeded();
    await page.waitForFunction(selector=>[...document.querySelectorAll(selector)].every(img=>img.complete && img.naturalWidth>0),home);
    assert.deepEqual(await page.locator(home).evaluateAll(imgs=>imgs.map(img=>img.dataset.registration)), entries.map(e=>e[0]));
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:path.join(evidence,`home-${width}.png`),fullPage:true});
    await page.locator('[data-page="races"]').filter({visible:true}).first().click();
    assert.equal(await page.locator('#page-races img.racer-portrait').count(),6);
    await page.locator('#page-races [data-open-race]').first().click();
    assert.equal(await page.locator('#page-detail img.racer-portrait').count(),6);
    assert.equal(await page.locator('#page-detail .portrait-status').first().isVisible(),true,'illustration labels remain visible on narrow detail cards');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:path.join(evidence,`detail-${width}.png`),fullPage:true});
    await page.locator('[data-page="settings"]').filter({visible:true}).first().click();
    assert.match(await page.locator('#racer-portrait-gallery').innerText(),/現在6選手分/);
    await page.locator('#racer-portrait-gallery summary').click();
    assert.equal(await page.locator('#racer-portrait-gallery a').count(),6);
    assert.deepEqual(await page.locator('#racer-portrait-gallery a').evaluateAll(as=>as.map(a=>new URL(a.href).searchParams.get('toban'))),entries.map(e=>e[0]));
    if (width===390) {
      await page.route('**/assets/racer-portraits/boat-4238.webp',route=>route.abort());
      await page.reload(); await load(page);
      await page.locator('#page-home .racer-card').filter({hasText:'毒島誠'}).scrollIntoViewIfNeeded();
      await page.waitForFunction(()=>[...document.querySelectorAll('#page-home .portrait-status')].some(n=>n.textContent==='イラスト読込待ち'));
      assert.equal(await page.locator('#page-home img.racer-portrait').count(),5);
      assert.equal(await page.locator('#page-home .racer-card .racer-name').filter({hasText:'毒島誠'}).count(),1);
      await page.unroute('**/assets/racer-portraits/boat-4238.webp');
      const missing=structuredClone(fixture);
      missing.records[0].participants[4]={number:5,registration_no:'9999',name:'未作成の表示テスト'};
      missing.records[0].participants[5].name='別の選手名';
      await load(page,missing);
      assert.equal(await page.locator('#page-home img.racer-portrait').count(),4);
      assert.equal(await page.locator('#page-home .portrait-status').filter({hasText:'イラスト準備中'}).count(),2);
      const synthetic=structuredClone(fixture);synthetic.dataset_status='SYNTHETIC_ONLY';
      await load(page,synthetic);
      assert.equal(await page.locator('#page-home img.racer-portrait').count(),0);
    }
    await context.close();
    console.log(`PASS portrait cards ${width}px: six identities, home/list/detail, gallery and responsive layout`);
  }
  assert.equal(requests.some(url=>url.startsWith('https://www.boatrace.jp/')),false,'no official-photo requests from visitors');
  assert.deepEqual(errors,[]);
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));});
