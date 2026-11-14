/* Invented saved-data startup, historical day and immutable variant selection. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const http=require('node:http'),{spawnSync}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),folder=fs.mkdtempSync(path.join(os.tmpdir(),'saved-pdca-ui-'));
let server,browser;
(async()=>{
  const py=spawnSync(process.env.RACE_AI_TEST_PYTHON||'python',['-c',`
from pathlib import Path
import sys,json
import race_ai
race_ai.__path__.extend(str(Path(reference)/'race_ai') for reference in ('pr64-reference','pr72-reference'))
from tests.test_boat_pdca_github_handoff import invented_research_state
from race_ai.saved_pdca_view import SavedPdcaService,export_view
root=Path(sys.argv[1]);state,_=invented_research_state(root)
view=SavedPdcaService(state).saved_projection()
(root/'view.json').write_text(json.dumps(view))
export_view(view,root/'view.html')
refs=dict(schema='RACE_AI_FORECAST_AUDIT_V1',dataset_status='REAL_REPORTED',records=[dict(
    race_id='20261106-03-01',sport='boat',venue='江戸川',race_no=1,event_date_jst='2026-11-06',
    cutoff_at='2026-11-06T10:00:00+09:00',scope='research',offering_status='UNKNOWN',source_provenance='UI_TEST_ONLY_INVENTED_RACE',
    source_sha256='a'*64,prediction=None,result=None,participants=[dict(number=i+1,registration_no=reg,name=name)
    for i,(reg,name) in enumerate([('3415','松井繁'),('3897','白井英治'),('3941','池田浩二'),('4238','毒島誠'),('4320','峰竜太'),('4444','桐生順平')])])])
export_view(refs,root/'profiles.html')
`,folder],{cwd:root,encoding:'utf8'});
  assert.equal(py.status,0,py.stderr);
  const original=JSON.parse(fs.readFileSync(path.join(folder,'view.json'))),requests=[],errors=[];
  server=http.createServer((req,res)=>{
    requests.push(req.method+' '+req.url);
    if(req.url==='/offline.html'){res.setHeader('Content-Type','text/html');return res.end(fs.readFileSync(path.join(folder,'view.html')));}
    if(req.url==='/profiles.html'){res.setHeader('Content-Type','text/html');return res.end(fs.readFileSync(path.join(folder,'profiles.html')));}
    if(req.url==='/api/forecast/saved'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(original));}
    const asset=req.url==='/'?'index.html':req.url.slice(1);
    if(!['index.html','app.js','product-data.js','ui-model.js','saved-performance.js','existing-model-catalog.js','forecast-audit-model.js','racer-portraits-data.js','racer-portraits.js','racer-profiles-data.js','racer-profiles.js','racer-daily.js','data/racer-daily.json','style.css'].includes(asset)){res.statusCode=404;return res.end();}
    let body=fs.readFileSync(path.join(root,'web',asset));
    if(asset==='index.html')body=Buffer.from(body.toString().replace('</head>','<meta name="race-ai-private-saved-view" content="/api/forecast/saved"></head>'));
    res.setHeader('Content-Type',asset.endsWith('.js')?'text/javascript':asset.endsWith('.css')?'text/css':'text/html');res.end(body);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:fs.existsSync('/usr/bin/chromium')?{executablePath:'/usr/bin/chromium'}:{}),args:['--no-sandbox']});
  const base='http://127.0.0.1:'+server.address().port;
  for(const target of [base+'/',base+'/offline.html']){
    const page=await browser.newPage({viewport:{width:390,height:844}});page.on('pageerror',e=>errors.push(e.message));
    await page.clock.install({time:new Date('2030-01-01T00:00:00Z')});
    await page.goto(target);
    await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('保存済み予想'),{},{timeout:5000});
    assert.equal(await page.evaluate(()=>globalThis.RaceRacerProfiles?.all.length),1669,'official reference data is available in ordinary and offline views');
    assert.equal(await page.evaluate(()=>typeof globalThis.RaceRacerDaily?.load),'function','daily reference API is available in ordinary and offline views');
    await page.locator('#selected-date').fill('2026-11-06');await page.locator('#selected-date').dispatchEvent('change');
    assert.equal(await page.locator('#selected-date').inputValue(),'2026-11-06');
    assert.equal(await page.locator('#page-races .race-card').count(),1);
    await page.locator('#page-races [data-open-race]').first().click();
    const select=page.locator('#prediction-select');
    assert.equal(await select.locator('option').count(),4);
    assert.match(await select.innerText(),/履歴なし/);assert.match(await select.innerText(),/履歴あり/);
    for(let i=0;i<4;i++){
      await select.selectOption(String(i));
      const p=[original.records[0].prediction,...original.records[0].comparison_predictions][i];
      const text=await page.locator('#detail-tab-content .forecast-panel .saved-tickets').innerText();
      for(const combo of p.ordered_top8)assert.ok(text.replace(/\s/g,'').includes(combo.join('−')));
    }
    await page.clock.fastForward(31000);
    assert.equal(await page.locator('#selected-date').inputValue(),'2026-11-06');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.close();
  }
  const offline=await browser.newPage({viewport:{width:390,height:844}}),offlineRequests=[];
  offline.on('request',req=>offlineRequests.push(req.url()));offline.on('pageerror',e=>errors.push(e.message));
  await offline.goto(base+'/profiles.html');
  await offline.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('保存済み予想'),{},{timeout:5000});
  await offline.locator('#selected-date').fill('2026-11-06');await offline.locator('#selected-date').dispatchEvent('change');
  await offline.locator('[data-page="races"]').filter({visible:true}).first().click();
  await offline.locator('[data-race-view="results"]').click();await offline.locator('#page-races [data-open-race]').first().click();
  await offline.locator('#detail-tab-content [data-open-participant="4320"]').first().click();
  assert.match(await offline.locator('#racer-reference').innerText(),/8\.05/);
  assert.equal(await offline.locator('#racer-reference .reference-course').count(),6);
  await offline.locator('[data-study-course="4"]').click();
  assert.match(await offline.locator('.reference-scenario').innerText(),/19走/);
  assert.deepEqual(offlineRequests.filter(url=>!url.startsWith('data:')),[base+'/profiles.html'],'offline athlete information, scripts and images need no network assets');
  await offline.close();
  assert.deepEqual(errors,[]);assert.equal(requests.some(x=>x.includes('generate')||x.includes('latest')||x.includes('/status')),false);
  console.log('PASS saved original automatic startup, past day, four exact variants, populated official offline profiles, private offline CSP and no generation');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));fs.rmSync(folder,{recursive:true,force:true});});
