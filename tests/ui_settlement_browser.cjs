/** Isolated local synthetic fixtures only. Never run seeded purchases against Preview. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {createRequire}=require('node:module');
const packages=process.env.RACE_AI_NODE_MODULES||'C:/Users/qq113/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const {chromium}=createRequire(path.join(packages,'package.json'))('playwright'),web=path.resolve(__dirname,'../web');
const DAY='2026-10-15',ID='20261015-18-01',SECOND='20261015-18-02',KEY='raceai.ledger.v1',AUDIT='raceai.result-audit.v1';
let mode='ready',programRevision=0,requests=[];
const race=id=>({race_id:id,closed_at:DAY+'T07:'+String(programRevision).padStart(2,'0')+':00+09:00',boats:Array.from({length:6},(_,i)=>({lane:i+1,racer_registration_id:String(1234+i),name:'合成選手'+(i+1)}))});
function canonical(v){return Array.isArray(v)?'['+v.map(canonical).join(',')+']':v&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);}
const digest=id=>{const value=race(id);value.closed_at=new Date(value.closed_at).toISOString().slice(0,19)+'.000000+00:00';return require('node:crypto').createHash('sha256').update(canonical(value)).digest('hex');};
const program=()=>({date_jst:DAY,first_observed_at:DAY+'T06:00:00+09:00',source_url:'https://example.org/synthetic',source_sha256:'a'.repeat(64),redistribution_authorized:true,test_data:'SYNTHETIC_ONLY_NOT_REAL_RACES',venues:[{venue:'18',races:[race(ID),race(SECOND)]}]});
function result(id){return {schema_version:1,race_id:id,date_jst:DAY,as_of:DAY+'T09:00:00+09:00',closed_at:race(id).closed_at,program_sha256:digest(id),status:'SETTLEMENT_PARTIAL',markets:[{race_id:id,status:'settled',confirmed:true,verified_market_types:['trifecta'],payouts:[{bet_type:'trifecta',combination:[1,2,3],payout_per_100_yen:mode==='corrected'?1600:1580}],refunds:[],special_payouts:[]}],excluded_market_types:['trio','exacta','quinella','quinella_place','win','place'],result_proof:{snapshot_id:(mode==='corrected'?'d':'b').repeat(64),source_url:'https://www.boatrace.jp/owpc/pc/race/raceresult?hd=20261015&jcd=18&rno='+Number(id.slice(-2)),source_sha256:'c'.repeat(64),captured_at:DAY+'T08:00:00+09:00',cloud_saved_at:DAY+'T08:02:00+09:00',status:'settled',finish_confirmed:true,financial_confirmed:false,top3:[1,2,3]},exclusion_reason:'OFFICIAL_MARKET_COVERAGE_INCOMPLETE'};}
const purchase=(id,race_id=ID,type='trifecta',combination=[1,2,3],amount=400,stamp=DAY+'T06:00:00+09:00')=>({id,race_id,purchased_at:stamp,bets:[{race_id,bet_type:type,combination,stake_yen:amount}]});
const seeded=[purchase('win'),purchase('miss',ID,'trifecta',[2,1,3]),purchase('pending',ID,'exacta',[1,2]),purchase('missing-program','20261015-18-03','win',[1],100),purchase('old','20261014-18-01','trifecta',[1,2,3],200,'2026-10-14T06:00:00+09:00')];
seeded[0].official_result=result(ID).markets[0];
const original=JSON.stringify(seeded);
const server=http.createServer((req,res)=>{
 res.setHeader('content-type','application/json');
 if(req.url==='/api/today'){res.end(JSON.stringify(program()));return;}
 if(req.url.startsWith('/api/settlement?')){
  const id=new URL(req.url,'http://localhost').searchParams.get('race_id');requests.push(id);const capturedMode=mode,value=result(id);
  if(mode==='wrong-race')value.race_id=SECOND;
  if(mode==='error'){res.statusCode=503;res.end('{"error":"SETTLEMENT_STORE_UNAVAILABLE"}');return;}
  if(mode==='pending')Object.assign(value,{status:'RESULT_NOT_OBTAINED',markets:[],result_proof:null,excluded_market_types:['trifecta','trio','exacta','quinella','quinella_place','win','place'],exclusion_reason:'OFFICIAL_RESULT_NOT_OBTAINED'});
  setTimeout(()=>res.end(JSON.stringify(value)),capturedMode==='slow'?500:0);return;
 }
 if(req.url.startsWith('/api/')){res.statusCode=404;res.end('{}');return;}
 const name=req.url.split('?')[0]==='/'?'index.html':req.url.split('?')[0].slice(1);
 if(!['index.html','style.css','app.js','ui-core.js','money.js','settlement.js','exhibition.js','original-exhibition.js','name-bound-exhibition.js'].includes(name)){res.statusCode=404;res.end();return;}
 res.setHeader('content-type',name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(path.join(web,name)));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true,channel:process.env.RACE_AI_BROWSER_CHANNEL||'msedge'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000},timezoneId:'Asia/Tokyo'}),page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));await context.addInitScript(({key,value})=>{if(!localStorage.getItem(key))localStorage.setItem(key,value);},{key:KEY,value:original});
  await page.clock.install({time:new Date(DAY+'T10:00:00+09:00')});const base='http://127.0.0.1:'+server.address().port;await page.goto(base);
  await page.waitForFunction(()=>document.querySelector('#feed-banner').dataset.state==='ready');
  assert.equal(await page.locator('#refresh-settlement').count(),1,'results need a fresh official reconciliation action');
  await page.waitForFunction(()=>document.querySelector('#settlement-status').dataset.state==='ready');
  assert.deepEqual([...new Set(requests)],[ID],'only relevant current-day recorded races with program may be fetched');
  assert.equal(await page.locator('#metric-spent').innerText(),'1,300円');assert.equal(await page.locator('#metric-roi').innerText(),'790%');assert.equal(await page.locator('#metric-hits').innerText(),'1 / 2');
  await page.locator('.desktop-nav [data-page="results"]').click();assert.equal(await page.locator('#result-total-stake').innerText(),'1,500円');assert.equal(await page.locator('#result-pending').innerText(),'700円');assert.equal(await page.locator('#result-payout').innerText(),'6,320円');assert.equal(await page.locator('#result-net').innerText(),'5,520円');
  assert.match(await page.locator('#results-history').innerText(),/過去日の照合は未対応/);assert.match(await page.locator('#results-history').innerText(),/当日の出走表が未取得/);assert.equal(await page.locator('#results-history a[href*="raceresult"]').count(),3);assert.equal(await page.evaluate(key=>localStorage.getItem(key),KEY),original,'settlement must not rewrite ledger');
  const audit=()=>page.evaluate(key=>JSON.parse(localStorage.getItem(key)||'[]'),AUDIT);assert.equal((await audit()).length,1);
  const refresh=async next=>{mode=next;await page.locator('#refresh-settlement').click();await page.waitForFunction(()=>document.querySelector('#settlement-status').dataset.state!=='loading');};
  await refresh('ready');assert.equal((await audit()).length,1,'repeat snapshot is idempotent');await refresh('corrected');assert.equal((await audit()).length,2);assert.equal(await page.locator('#result-payout').innerText(),'6,400円');
  await refresh('error');assert.equal(await page.locator('#result-payout').innerText(),'0円');assert.equal(await page.locator('#metric-roi').innerText(),'―');assert.match(await page.locator('#settlement-status').innerText(),/失敗/);
  mode='error';await page.reload();await page.waitForFunction(()=>document.querySelector('#settlement-status')?.dataset.state==='error');assert.equal(await page.locator('#metric-roi').innerText(),'―','audit must never restore confirmation');
  await page.locator('.desktop-nav [data-page="results"]').click();await refresh('wrong-race');assert.equal(await page.locator('#result-payout').innerText(),'0円');await refresh('pending');assert.equal(await page.locator('#result-pending').innerText(),'1,500円');
  await refresh('ready');mode='slow';await page.locator('#refresh-settlement').click();await page.locator('#race-date').fill('2026-10-14');await page.locator('#race-date').dispatchEvent('change');await new Promise(r=>setTimeout(r,650));assert.equal(await page.locator('#result-payout').innerText(),'0円','stale day response must not retain settlement');
  mode='ready';await page.locator('#race-date').fill(DAY);await page.locator('#race-date').dispatchEvent('change');await page.waitForFunction(()=>document.querySelector('#settlement-status').dataset.state==='ready');
  mode='slow';await page.locator('#refresh-settlement').click();programRevision=1;mode='pending';await page.locator('#refresh-feed').click();await page.waitForFunction(()=>document.querySelector('#settlement-status').dataset.state==='ready');await new Promise(r=>setTimeout(r,650));assert.equal(await page.locator('#result-payout').innerText(),'0円','stale program response must not replace new context');
  // Competing tabs each re-read and append under the shared local-state Web Lock.
  mode='ready';const second=await context.newPage();await second.clock.install({time:new Date(DAY+'T10:00:00+09:00')});await second.goto(base);await second.waitForFunction(()=>document.querySelector('#settlement-status').dataset.state==='ready');
  await second.evaluate(({key,record})=>{const rows=JSON.parse(localStorage.getItem(key));rows.push(record);localStorage.setItem(key,JSON.stringify(rows));},{key:KEY,record:purchase('second',SECOND,'trifecta',[1,2,3],100)});
  await page.waitForFunction(()=>document.querySelector('#result-total-stake').textContent==='1,600円');await page.waitForFunction(()=>document.querySelector('#settlement-status').dataset.state==='ready');
  await second.evaluate(()=>{navigator.locks.request('raceai.local-state.v1',()=>{window.held=true;return new Promise(resolve=>window.release=resolve);});});await second.waitForFunction(()=>window.held);
  mode='corrected';await page.locator('#refresh-settlement').click();await second.locator('.desktop-nav [data-page="results"]').click();await second.locator('#refresh-settlement').click();await second.evaluate(()=>window.release());
  await Promise.all([page,second].map(p=>p.waitForFunction(()=>document.querySelector('#settlement-status').dataset.state==='ready')));
  const history=await audit();assert.equal(history.filter(e=>e.race_id===SECOND).length,2,'both race histories survive concurrent tab updates');assert.equal(new Set(history.map(e=>e.race_id+':'+e.report.result_proof.snapshot_id+':'+e.report.closed_at)).size,history.length,'no duplicate correction snapshots');
  for(const width of [1440,768,390,320]){await page.setViewportSize({width,height:1000});const overflow=await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(n=>n.getBoundingClientRect().right>innerWidth||n.scrollWidth>n.clientWidth).map(n=>n.tagName+'#'+n.id+'.'+n.className+':'+n.getBoundingClientRect().right).slice(0,20));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'settlement overflow at '+width+': '+overflow.join(', '));}
  await page.clock.setSystemTime(new Date('2026-10-16T00:00:05+09:00'));await page.clock.runFor(30000);assert.equal(await page.locator('#metric-roi').innerText(),'―','JST rollover clears financial confirmation');assert.equal(await page.locator('#result-payout').innerText(),'0円');
  assert.deepEqual(errors,[]);console.log('PASS: fresh settlement, exact financial displays, current/history separation, immutable forged ledger, missing-market pending, audit idempotency/corrections, API failure/reload, race/day/program stale responses, competing tabs, four widths, JST rollover.');await context.close();
 }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
