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
const generationCalls = [];
let failGeneration = false;
let generationOverride = null;
async function main() {
  fs.mkdirSync(output, {recursive:true});
  server = http.createServer((req,res) => {
    const parsedUrl = new URL(req.url, 'http://localhost');
    const name = decodeURIComponent(parsedUrl.pathname);
    if (name === '/api/forecast/status') {
      res.writeHead(200, {'Content-Type':'application/json'});
      return res.end(JSON.stringify({day_jst:'2030-01-01',nonce:'synthetic-ui-nonce',capabilities:{boat:{P0:true,P1:true},keirin:{P0:false,P1:false},autorace:{P0:false,P1:false},horse:{P0:false,P1:false}}}));
    }
    if (name === '/api/forecast/generate' && req.method === 'POST') {
      let body='';req.on('data',chunk=>body+=chunk);req.on('end',()=>{
        generationCalls.push({body:JSON.parse(body),nonce:req.headers['x-race-ai-nonce']});
        res.writeHead(failGeneration?422:200, {'Content-Type':'application/json'});
        if(failGeneration)return res.end(JSON.stringify({error:{code:'GENERATION_INPUT_UNAVAILABLE',message:'対象レース・予想時点・必要な実入力を確認してください。'}}));
        if(generationOverride)return res.end(JSON.stringify(generationOverride));
        return res.end(JSON.stringify({day_jst:'2030-01-01',view:fixture,summary:{generated:generationCalls.length%2?1:0,reused:generationCalls.length%2?0:1,missing:14}}));
      });return;
    }
    const file = path.resolve(root, '.' + (name === '/' ? '/index.html' : name));
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) {res.writeHead(404);return res.end();}
    const type = {'.html':'text/html','.css':'text/css','.js':'text/javascript','.json':'application/json'}[path.extname(file)] || 'application/octet-stream';
    res.writeHead(200, {'Content-Type':type});
    if(name==='/' && parsedUrl.searchParams.has('generation'))return res.end(fs.readFileSync(file,'utf8').replace('</head>','<meta name="race-ai-generation-api" content="/api/forecast"></head>'));
    fs.createReadStream(file).pipe(res);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base = `http://127.0.0.1:${server.address().port}/`;
  browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {}), args:['--no-sandbox']});
  for (const width of process.env.UI_GENERATION_ONLY?[]:[320,390,1440,1920]) {
    const context = await browser.newContext({viewport:{width,height:width<600?844:1080}, deviceScaleFactor:1});
    await context.tracing.start({screenshots:true,snapshots:true});
    const page = await context.newPage();
    page.on('pageerror', e=>errors.push(e.message));
    page.on('request', req=>requests.push(req.url()));
    const capture = async name => {
      await page.evaluate(()=>window.scrollTo({top:0,left:0,behavior:'instant'}));
      assert.equal(await page.locator('.topbar').evaluate(n=>n.getBoundingClientRect().top),0,'capture starts at page top');
      await page.screenshot({path:path.join(output,name),fullPage:true});
    };
    await page.clock.install({time:new Date('2030-01-01T00:30:00Z')});
    await page.goto(base);
    await page.locator('#source-state').waitFor();
    assert.equal(await page.locator('#forecast-generate').isDisabled(),true,'static viewer cannot pretend to generate');
    assert.match(await page.locator('#generation-message').innerText(),/ローカル予想サーバー/);
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
      await capture(`${width}-${name}.png`);
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
    if (process.env.UI_PRIVATE_CYCLE_EXPORT) {
      const savedView=JSON.parse(fs.readFileSync(process.env.UI_PRIVATE_CYCLE_EXPORT,'utf8'));
      assert.equal(savedView.dataset_status,'SYNTHETIC_ONLY','browser evidence must contain synthetic data only');
      const saved=savedView.records.find(r=>r.sport==='boat' && r.prediction);
      const variants=[saved.prediction,...saved.comparison_predictions];
      assert.ok(variants.some(p=>p.stage==='P0') && variants.some(p=>p.stage==='P1'));
      const learnedRace=savedView.records.find(r=>[r.prediction,...r.comparison_predictions].some(p=>p?.variant==='LEARNED_SHADOW'));
      assert.ok(learnedRace,'genuine saved native learned fixture is present');
      await page.clock.setFixedTime(new Date(saved.event_date_jst+'T00:30:00Z'));
      await page.locator('#race-file').setInputFiles({name:'saved-cycle-synthetic.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(savedView))});
      await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('端末内で読み込みました'));
      await nav('races');
      await page.locator('#selected-date').fill(saved.event_date_jst);
      await page.locator('#selected-date').dispatchEvent('change');
      await page.locator('#page-races [data-open-race]').first().click();
      assert.equal(await page.locator('#prediction-select option').count(),variants.length,'every saved baseline/P0/P1/learned variant selectable');
      await page.locator('[data-detail-tab="analysis"]').click();
      for (const [index,p] of variants.entries()) {
        await page.locator('#prediction-select').selectOption(String(index));
        const displayed=await page.locator('#race-detail .forecast-panel').first().locator('.saved-ticket .combo').evaluateAll(nodes=>nodes.map(n=>[...n.querySelectorAll('.lane')].map(x=>Number(x.textContent))));
        assert.deepEqual(displayed,p.ordered_top8,'saved original Top8 order unchanged');
        const detail=await page.locator('#race-detail').innerText();
        assert.ok(detail.includes(p.prediction_sha256) && detail.includes(p.original_json_sha256),'native SHA and member SHA preserved');
        if(p.model_version==null) assert.match(await page.locator('#prediction-select option:checked').innerText(),/未取得/);
      }
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false,'saved-cycle detail has no horizontal overflow');
      await capture(`${width}-saved-cycle-detail.png`);
      await page.locator('[data-detail-tab="history"]').click();
      assert.match(await page.locator('#result-observations').innerText(),/取得観測履歴（公式改訂番号なし）/);
      assert.equal(await page.locator('#result-observations details').count(),saved.result_observations.length);
      for (const details of await page.locator('#result-observations details').all()) await details.locator('summary').click();
      for (const observation of saved.result_observations) assert.ok((await page.locator('#result-observations').innerText()).includes(observation.source_sha256));
      const rawBodies=await page.locator('#result-observations [data-observation-raw]').allTextContents();
      assert.deepEqual(rawBodies,saved.result_observations.map(o=>JSON.stringify(o)),'full raw captures cannot be truncated');
      assert.match(await page.locator('#race-detail').innerText(),/結果確認 未取得/,'capture time must not become official confirmation time');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false,'raw observation history has no horizontal overflow');
      await capture(`${width}-saved-cycle-history.png`);
      await nav('results');
      assert.match(await page.locator('#result-metrics').innerText(),/未検証/);
      assert.ok(!(await page.locator('#result-metrics').innerText()).includes('100%'));
      const privateStorage=await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}));
      assert.ok(variants.every(p=>!privateStorage.includes(p.prediction_sha256)),'saved originals stay out of browser persistence');
      await nav('races');
      await page.locator(`#page-races [data-open-race="${learnedRace.race_id}"]`).click();
      const learnedVariants=[learnedRace.prediction,...learnedRace.comparison_predictions];
      await page.locator('[data-detail-tab="analysis"]').click();
      for (const [index,p] of learnedVariants.entries()) if(p.variant==='LEARNED_SHADOW') {
        await page.locator('#prediction-select').selectOption(String(index));
        assert.ok((await page.locator('#race-detail').innerText()).includes(p.prediction_sha256),'saved learned original hash selectable');
        assert.match(await page.locator('#prediction-select option:checked').innerText(),/LEARNED_SHADOW/);
        const displayed=await page.locator('#race-detail .forecast-panel').first().locator('.saved-ticket .combo').evaluateAll(nodes=>nodes.map(n=>[...n.querySelectorAll('.lane')].map(x=>Number(x.textContent))));
        assert.deepEqual(displayed,p.ordered_top8,'saved learned Top8 is never recomputed');
        const facts=await page.locator('#race-detail').innerText();
        for(const field of ['training_sha256','training_receipt_digest','baseline_model_sha256']) if(p[field]!=null)assert.ok(facts.includes(p[field]),`saved learned ${field} visible`);
      }
      mark(`${width}: sealed original ZIP -> private restore -> view -> browser, exact Top8/SHA, P1/learned selection and separate capture history`);
    }
    if (process.env.UI_DISPATCH_VIEWS && [390,1440].includes(width)) {
      const bundle=JSON.parse(fs.readFileSync(process.env.UI_DISPATCH_VIEWS,'utf8'));
      assert.equal(bundle.scope,'SYNTHETIC_ONLY');
      const families=new Set(),nativeHashes=new Set();
      for (const [number,view] of bundle.views.entries()) {
        assert.equal(view.dataset_status,'SYNTHETIC_ONLY');
        const saved=view.records.find(r=>r.prediction)||view.records[0];
        const variants=[saved.prediction,...saved.comparison_predictions].filter(Boolean);
        await page.locator('#clear-data').click();
        await page.clock.setFixedTime(new Date(saved.event_date_jst+'T00:30:00Z'));
        await page.locator('#race-file').setInputFiles({name:`native-synthetic-${number}.json`,mimeType:'application/json',buffer:Buffer.from(JSON.stringify(view))});
        await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('端末内で読み込みました'));
        await page.locator(`[data-sport="${saved.sport}"]`).first().click();await nav('races');
        await page.locator('#selected-date').fill(saved.event_date_jst);await page.locator('#selected-date').dispatchEvent('change');
        if(saved.prediction?.native_top8_available===false) {
          const card=page.locator('#page-races .race-card').filter({has:page.locator(`[data-open-race="${saved.race_id}"]`)});
          assert.match(await card.innerText(),/保存5点プラン/);
          assert.ok(!(await card.innerText()).includes('保存Top8'));
        }
        await page.locator(`#page-races [data-open-race="${saved.race_id}"]`).click();
        await page.locator('[data-detail-tab="analysis"]').click();
        assert.equal(await page.locator('#dispatch-slot-status tbody tr').count(),saved.dispatch_slots.length,'all native model states retained');
        for(const [index,p] of variants.entries()) {
          families.add(p.model_id);if(p.prediction_sha256)nativeHashes.add(p.prediction_sha256);
          await page.locator('#prediction-select').selectOption(String(index));
          const shown=await page.locator('#race-detail .forecast-panel').first().locator('.saved-ticket .combo').evaluateAll(nodes=>nodes.map(n=>[...n.querySelectorAll('.lane')].map(x=>Number(x.textContent))));
          assert.deepEqual(shown,p.ordered_top8,'all sixteen native families keep saved candidate order');
          assert.ok((await page.locator('#race-detail').innerText()).includes(p.output_sha256),'output hash displayed separately');
          if(p.prediction_sha256==null) assert.equal(await page.locator('#race-detail').evaluate(n=>[...n.querySelectorAll('dt')].find(x=>x.textContent==='予想SHA').nextElementSibling.textContent),'未取得');
          if(p.native_top8_available===false) assert.match(await page.locator('#race-detail').innerText(),/保存された5点プラン/);
          if(['A_PRE_TRIAL','B_POST_TRIAL'].includes(p.stage)) assert.match(await page.locator('#prediction-select option:checked').innerText(),/試走前|試走後/);
        }
        if(saved.venue==null||saved.race_no==null) {
          assert.match(await page.locator('#race-detail').innerText(),/開催場 未取得|レース番号 未取得/);
          assert.ok(!(await page.locator('#race-detail').innerText()).includes('nullR'));
        }
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false,'native model/slot content cannot overflow');
        const variant=variants.at(-1);
        if(saved.sport==='horse') await capture(`${width}-dispatch-horse.png`);
        if(variant?.stage==='A_PRE_TRIAL') await capture(`${width}-dispatch-autorace-A.png`);
        if(variant?.stage==='B_POST_TRIAL') await capture(`${width}-dispatch-autorace-B.png`);
        if(variant?.native_top8_available===false) await capture(`${width}-dispatch-seller.png`);
        if(!variants.length) await capture(`${width}-dispatch-missing-metadata.png`);
        if(number===bundle.views.length-2) await capture(`${width}-dispatch-private-readback.png`);
      }
      assert.equal(families.size,16,'every existing family actually imported and selectable');
      const storage=await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}));
      assert.ok([...nativeHashes].every(sha=>!storage.includes(sha)),'no native forecasts persisted in browser storage');
      mark(`${width}: sixteen native families and four-sport private SQLite restart -> browser, exact hashes/order, native trial phases, five-ticket plan and missing-input states`);
      const sourceView=bundle.source_observation_view;
      assert.equal(sourceView.dataset_status,'SYNTHETIC_ONLY');
      await page.locator('#clear-data').click();
      await page.clock.setFixedTime(new Date(sourceView.event_date_jst+'T00:30:00Z'));
      await page.locator('#race-file').setInputFiles({name:'source-observations-synthetic.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(sourceView))});
      await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('端末内で読み込みました'));
      await page.locator('#selected-date').fill(sourceView.event_date_jst);await page.locator('#selected-date').dispatchEvent('change');
      for(const sport of ['keirin','autorace','horse']) {
        await page.locator(`[data-sport="${sport}"]`).first().click();await nav('races');
        await page.locator('#page-races [data-open-race]').first().click();
        await page.locator('[data-detail-tab="analysis"]').click();
        assert.equal(await page.locator('#prediction-select').isDisabled(),true,'observed pages cannot become forecasts');
        assert.match(await page.locator('#race-detail').innerText(),/モデル入力・締切・予想・結果は未接続/);
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false,'observed source identifiers cannot overflow the detail title');
        await capture(`${width}-source-observation-${sport}.png`);
      }
      mark(`${width}: three nonboat source-observation pages remain unpredicted, exact source facts and no long-title overflow`);
    }
    await context.tracing.stop({path:path.join(output,`${width}-interaction.zip`)});
    await context.close();
  }
  assert.ok(requests.every(url=>!new URL(url).pathname.startsWith('/api/forecast')),'static viewer makes no generation API probe');
  for(const width of [390,1440]) {
    generationCalls.length=0;failGeneration=false;generationOverride=null;
    const context=await browser.newContext({viewport:{width,height:width<600?844:1080}});
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('request',req=>requests.push(req.url()));
    await page.clock.install({time:new Date('2030-01-01T00:30:00Z')});
    await page.goto(base+'?generation=1');
    await page.waitForFunction(()=>document.querySelector('#forecast-generate')?.disabled===false);
    assert.equal(generationCalls.length,0,'startup capability check must not generate a forecast');
    await page.locator('#forecast-stage').selectOption('P1');
    await page.locator('#forecast-generate').click();
    await page.waitForFunction(()=>document.querySelector('#generation-message').textContent.includes('新規 1'));
    assert.deepEqual(generationCalls[0],{body:{sport:'boat',stage:'P1'},nonce:'synthetic-ui-nonce'},'browser supplies no source grants, clock, model list or private path');
    assert.match(await page.locator('#source-state').innerText(),/合成/);
    await page.locator('[data-page="races"]').filter({visible:true}).first().click();
    await page.locator('#page-races [data-open-race]').first().click();
    assert.ok((await page.locator('#race-detail').innerText()).includes(fixture.records[0].prediction.prediction_sha256),'returned exact original hash appears in the app');
    await page.locator('#forecast-generate').click();
    await page.waitForFunction(()=>document.querySelector('#generation-message').textContent.includes('再利用 1'));
    await page.locator('[data-page="races"]').filter({visible:true}).first().click();
    await page.locator('#page-races [data-open-race]').first().click();
    assert.ok((await page.locator('#race-detail').innerText()).includes(fixture.records[0].prediction.prediction_sha256),'reuse shows the same original hash');
    const before=await page.locator('#race-detail').innerText();
    failGeneration=true;await page.locator('#forecast-generate').click();
    await page.waitForFunction(()=>document.querySelector('#generation-message').textContent.includes('前の表示データ'));
    assert.match(await page.locator('#generation-message').innerText(),/対象レース・予想時点・必要な実入力を確認してください。/,'actual server error code provides an actionable input message');
    assert.equal(await page.locator('#race-detail').innerText(),before,'generation failure retains the loaded original');
    failGeneration=false;
    for(const [day,viewDay] of [['2030-99-99','2030-01-01'],['2030-01-01','2030-01-02']]) {
      generationOverride={day_jst:day,view:{schema:'RACE_AI_PRIVATE_CYCLE_VIEW_V1',dataset_status:'SYNTHETIC_ONLY',event_date_jst:viewDay,records:[]},summary:{generated:0,reused:0,missing:0}};
      await page.locator('#forecast-generate').click();
      await page.waitForFunction(()=>document.querySelector('#generation-message').textContent.includes('応答を確認'));
      assert.equal(await page.locator('#race-detail').innerText(),before,'invalid response date must not clear the loaded original');
      assert.equal(await page.locator('#selected-date').inputValue(),'2030-01-01');
    }
    await page.locator('[data-sport="horse"]').first().click();
    assert.equal(await page.locator('#forecast-generate').isDisabled(),true);
    assert.match(await page.locator('#generation-message').innerText(),/実入力|入力/);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false,'generation controls must wrap on mobile');
    await page.screenshot({path:path.join(output,`${width}-generation-controls.png`),fullPage:true});
    mark(`${width}: explicit generation request, exact returned original, reuse message, invalid response retention and missing native inputs`);
    await context.close();
  }
  assert.deepEqual(errors,[],'no page errors');
  assert.ok(requests.every(url=>url.startsWith(base)),'no external source requests');
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({scope:'SYNTHETIC_ONLY',checks,errors,source_requests:0,widths:[320,390,1440,1920],dispatch_fixture_widths:process.env.UI_DISPATCH_VIEWS?[390,1440]:[],generation_fixture_widths:[390,1440],generation_native_execution_proven:false},null,2));
  await browser.close();browser=null;await new Promise(resolve=>server.close(resolve));server=null;
}
main().catch(async error=>{console.error(error);if(browser)await browser.close();if(server)server.close();process.exitCode=1;});
