/** Local synthetic fixtures only: browser behavior, never real race performance. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {createRequire}=require('node:module'),{DAY,receipt,race,evaluation,excluded}=require('./ui_evaluation_fixture.cjs');
const packages=process.env.RACE_AI_NODE_MODULES||'C:/Users/qq113/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const {chromium}=createRequire(path.join(packages,'package.json'))('playwright'),web=path.resolve(__dirname,'../web');
let mode='ready',requests=[];
function program(){return {date_jst:DAY,first_observed_at:DAY+'T06:00:00+09:00',source_url:'https://example.org/synthetic',source_sha256:'a'.repeat(64),redistribution_authorized:true,test_data:'SYNTHETIC_ONLY_NOT_REAL_RACES',venues:[{venue:'18',races:[race(),race(1)]}]};}
function payload(index){
 if(mode==='missing-prediction')return excluded('PREDICTION_NOT_SAVED',index);
 if(mode==='pending'||mode==='before-close'){const value=excluded('RESULT_PENDING',index);if(mode==='before-close'){value.as_of=DAY+'T06:03:00+09:00';value.result_proof.captured_at=DAY+'T06:02:00+09:00';value.result_proof.cloud_saved_at=value.as_of;}return value;}
 if(mode==='missing-result')return excluded('RESULT_NOT_OBTAINED',index);
 if(mode==='unsupported')return excluded('RESULT_UNSUPPORTED',index);
 const value=evaluation(index);if(mode==='wrong-race')value.race_id='20261015-18-12';if(mode==='wrong-score')value.models[0].multiclass_brier=0.1;if(mode==='bad-phase')value.prediction_proof.cloud_saved_at=DAY+'T07:00:00+09:00';return value;
}
const server=http.createServer((req,res)=>{
 res.setHeader('content-type','application/json');
 if(req.url==='/api/today'){res.end(JSON.stringify(program()));return;}
 if(req.url.startsWith('/api/race?')){res.statusCode=404;res.end('{"error":"RACE_UPDATES_NOT_OBTAINED"}');return;}
 if(req.url.startsWith('/api/prediction?')){if(mode==='missing-prediction'){res.statusCode=404;res.end('{"error":"PREDICTION_NOT_OBTAINED"}');return;}if(mode==='prediction-error'){res.statusCode=503;res.end('{"error":"PREDICTION_UNAVAILABLE"}');return;}const id=new URL(req.url,'http://localhost').searchParams.get('race_id');res.end(JSON.stringify(receipt(id.endsWith('-02')?1:0)));return;}
 if(req.url.startsWith('/api/evaluation?')){
  const id=new URL(req.url,'http://localhost').searchParams.get('race_id');requests.push(id);
  if(mode==='error'){res.statusCode=503;res.end('{"error":"EVALUATION_UNAVAILABLE"}');return;}
  const value=payload(id.endsWith('-02')?1:0),delay=mode==='slow'&&id.endsWith('-01')?400:0;
  setTimeout(()=>res.end(JSON.stringify(value)),delay);return;
 }
 const name=req.url.split('?')[0]==='/'?'index.html':req.url.split('?')[0].slice(1);
 if(!['index.html','style.css','app.js','ui-core.js','money.js','settlement.js','exhibition.js','original-exhibition.js','name-bound-exhibition.js','name-bound-evaluation.js'].includes(name)){res.statusCode=404;res.end();return;}
 res.setHeader('content-type',name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(path.join(web,name)));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,channel:process.env.RACE_AI_BROWSER_CHANNEL||'msedge'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000},timezoneId:'Asia/Tokyo'}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.clock.install({time:new Date(DAY+'T10:00:00+09:00')});await page.goto('http://127.0.0.1:'+server.address().port);
  await page.waitForFunction(()=>document.querySelector('#feed-banner').dataset.state==='ready');assert.equal(requests.length,0);
  await page.locator('.desktop-nav [data-page="races"]').click();await page.locator('.race-card .outline-button').first().click();assert.equal(requests.length,0);
  await page.locator('[data-tab="prediction"]').click();await page.waitForFunction(()=>document.querySelector('.research-evaluation')?.dataset.state==='ready');
  assert.equal(requests.length,1);assert.equal(await page.locator('.evaluation-scores tbody tr').count(),2);assert.match(await page.locator('.evaluation-sample').innerText(),/共通1レース.*N=1/s);assert.match(await page.locator('.research-evaluation').innerText(),/小さい.*未検証/s);
  assert.match(await page.locator('.evaluation-outcome').innerText(),/1.*2.*3.*着順確定.*払戻・返還は確認中/s);assert.match(await page.locator('.evaluation-result-proof').innerText(),/結果取得.*クラウド保存/s);
  assert.equal(await page.locator('.research-evaluation button').count(),0);const count=requests.length;await page.locator('#prediction-model').selectOption('official-program-uniform-pl');assert.equal(requests.length,count);
  const refresh=async next=>{mode=next;const before=requests.length;await page.getByRole('button',{name:'研究予測を再確認',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.research-evaluation')?.dataset.state==='ready'||document.querySelector('.research-evaluation')?.dataset.state==='error');assert.equal(requests.length,before+1);};
  for(const state of ['pending','missing-result','unsupported','missing-prediction']){await refresh(state);assert.equal(await page.locator('.evaluation-scores').count(),0);assert.equal(await page.locator('.evaluation-sample').count(),0);assert.notEqual(await page.locator('.research-evaluation').innerText(),'');}
  await refresh('ready');for(const invalid of ['wrong-race','wrong-score','bad-phase','error','prediction-error']){await refresh(invalid);assert.equal(await page.locator('.research-evaluation').getAttribute('data-state'),'error');assert.equal(await page.locator('.evaluation-scores').count(),0);assert.equal(await page.locator('.evaluation-result-proof').count(),0);}
  mode='slow';const before=requests.length;await Promise.all([page.waitForResponse(r=>r.url().includes('/api/prediction?')),page.getByRole('button',{name:'研究予測を再確認',exact:true}).click()]);await page.waitForFunction(()=>document.querySelector('.research-evaluation')?.dataset.state==='loading');await page.locator('#race-select').selectOption('20261015-18-02');await page.waitForFunction(()=>document.querySelector('.research-evaluation')?.dataset.state==='ready');await new Promise(r=>setTimeout(r,500));assert.equal(requests.length,before+2);assert.equal(await page.locator('.research-evaluation').getAttribute('data-race-id'),'20261015-18-02');
  for(const width of [1440,768,390,320]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'evaluation overflow at'+width);}
  await page.clock.setSystemTime(new Date(DAY+'T06:03:00+09:00'));await refresh('before-close');assert.equal(await page.locator('.evaluation-scores').count(),0);assert.match(await page.locator('.research-evaluation').innerText(),/未確定/);assert.deepEqual(errors,[]);
  console.log('PASS: lazy selected-race evaluation; common N=1 scores and source/time proof; finish distinct from financial confirmation; missing/pending/unsupported no invented metrics; invalid/error clear; stale race guarded; before-close pending; four widths.');await context.close();
 }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
