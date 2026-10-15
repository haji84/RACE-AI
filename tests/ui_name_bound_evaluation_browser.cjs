/** Offline synthetic fixture/harness. Never accesses official sources. */
const numeric=require('./ui_name_bound_exhibition_fixture.json');
const NOW=Date.parse('2026-10-15T08:45:00+09:00');
const SCOPE='SAME_RACE_DIFFERENT_FEATURE_PHASES_NOT_EQUAL_INFORMATION_CUTOFF';
function fixture(){
 const forecast=structuredClone(numeric.envelope),race=structuredClone(numeric.race),s=forecast.receipt.snapshot,b=forecast.baseline;
 const selected=b.snapshot.models.find(m=>m.model_id===s.baseline_link.model_id);
 const report={schema_version:1,race_id:race.race_id,date_jst:'2026-10-15',as_of:'2026-10-15T08:45:00+09:00',closed_at:race.closed_at,status:'EVALUATED',research_only:true,validation_status:'UNVALIDATED',purchase_decision:'skip',purchase_recommendations:[],comparison_scope:SCOPE,physical_exhibition_timing_verified:false,common_race_ids:[race.race_id],models:[],
 forecast_proof:{request_id:forecast.receipt.request_id,snapshot_id:s.snapshot_id,envelope_sha256:'a'.repeat(64),baseline_request_id:b.request_id,baseline_snapshot_id:b.snapshot.snapshot_id,baseline_receipt_sha256:s.baseline_link.receipt_sha256,name_binding_request_id:forecast.name_binding.receipt.request_id,input_snapshot_id:forecast.inputs.snapshot_id,generated_at:s.generated_at,cloud_saved_at:forecast.receipt.cloud_saved_at,receipt_confirmed_at:forecast.finalization.receipt_confirmed_at},
 result_proof:{snapshot_id:'b'.repeat(64),source_url:'https://www.boatrace.jp/owpc/pc/race/raceresult?hd=20261015&jcd=18&rno=1',source_sha256:'c'.repeat(64),captured_at:'2026-10-15T08:44:00+09:00',cloud_saved_at:'2026-10-15T08:44:02+09:00',status:'settled',finish_confirmed:true,financial_confirmed:false,top3:[1,2,3],refund_boats:[],program_identity_sha256:s.validation_program_identity_sha256},exclusion_reason:null};
 report.models=[selected,...s.models].map((model,i)=>{const winner=model.triples.find(t=>t.combination.join()==='1,2,3').probability,receipt=i?forecast.receipt:b;return {model_id:model.model_id,model_version:model.model_version,phase:['B_ONLY_BASELINE','DISPLAY_V2','ORIGINAL_V2'][i],race_count:1,ticket_count:120,multiclass_brier:model.triples.reduce((total,t)=>total+(t.probability-(t.combination.join()==='1,2,3'?1:0))**2,0),log_loss:-Math.log(winner),winner_probability:winner,forecast_generated_at:receipt.snapshot.generated_at,forecast_cloud_saved_at:receipt.cloud_saved_at};});
 return {forecast,race,report,now:NOW};
}
module.exports={fixture,NOW,SCOPE};

async function runBrowserHarness(){
 const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http'),{createRequire}=require('node:module');
 const packages=process.env.RACE_AI_NODE_MODULES||'C:/Users/qq113/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
 const {chromium}=createRequire(path.join(packages,'package.json'))('playwright'),web=path.resolve(__dirname,'../web'),ID=numeric.race.race_id,SECOND='20261015-18-02';
 let mode='ready',version='123499-1',requests=[],delays=[];
 const data=()=>{const f=fixture();f.forecast.receipt.request_id=version;f.forecast.finalization.request_id=version;f.report.forecast_proof.request_id=version;return f;};
 const feed=()=>({date_jst:'2026-10-15',first_observed_at:'2026-10-15T06:00:00+09:00',source_url:'https://example.org/synthetic',source_sha256:'a'.repeat(64),redistribution_authorized:true,test_data:'SYNTHETIC_ONLY_NOT_REAL_RACES',venues:[{venue:'18',races:[structuredClone(numeric.race),{...structuredClone(numeric.race),race_id:SECOND}]}]});
 const server=http.createServer((req,res)=>{
  res.setHeader('content-type','application/json');
  if(req.url==='/api/today'){res.end(JSON.stringify(feed()));return;}
  if(req.url.startsWith('/api/name-bound-exhibition?')){res.end(JSON.stringify(data().forecast));return;}
  if(req.url.startsWith('/api/name-bound-evaluation?')){
   requests.push(req.url);assert.equal(req.method,'GET');const query=new URL(req.url,'http://localhost').searchParams;assert.equal(query.get('forecast_request_id'),version);
   if(mode==='error'||mode==='missing'){res.statusCode=mode==='error'?503:404;res.end('{}');return;}
   const value=data().report;
   if(mode==='pending'){Object.assign(value,{status:'RESULT_PENDING',exclusion_reason:'OFFICIAL_RESULT_PENDING',models:[],common_race_ids:[]});Object.assign(value.result_proof,{status:'PENDING',finish_confirmed:false,top3:null});}
   if(mode==='no-result')Object.assign(value,{status:'RESULT_NOT_OBTAINED',exclusion_reason:'OFFICIAL_RESULT_NOT_OBTAINED',result_proof:null,models:[],common_race_ids:[]});
   if(mode==='tamper')value.models[0].log_loss+=.01;
   if(mode==='slow'){delays.push(()=>res.end(JSON.stringify(value)));return;}
   res.end(JSON.stringify(value));return;
  }
  if(req.url.startsWith('/api/prediction?')){res.end(JSON.stringify(data().forecast.baseline));return;}
  if(req.url.startsWith('/api/')){res.statusCode=404;res.end('{}');return;}
  const name=req.url.split('?')[0]==='/'?'index.html':req.url.split('?')[0].slice(1);
  if(!['index.html','style.css','app.js','ui-core.js','money.js','settlement.js','exhibition.js','original-exhibition.js','name-bound-exhibition.js','name-bound-evaluation.js'].includes(name)){res.statusCode=404;res.end();return;}
  res.setHeader('content-type',name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(path.join(web,name)));
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;
 try{
  browser=await chromium.launch({headless:true,channel:process.env.RACE_AI_BROWSER_CHANNEL||'msedge'});
  const context=await browser.newContext({viewport:{width:1440,height:1000},timezoneId:'Asia/Tokyo'}),page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));await page.clock.install({time:new Date(NOW)});
  await page.goto('http://127.0.0.1:'+server.address().port+'/#/detail/'+ID);await page.waitForFunction(()=>document.querySelector('#feed-banner').dataset.state==='ready');await page.locator('[data-tab="prediction"]').click();await page.locator('#load-name-bound-exhibition').waitFor();assert.equal(requests.length,0);assert.equal(await page.locator('#load-name-bound-evaluation').count(),0);
  const loadNumeric=async()=>{await page.locator('#load-name-bound-exhibition').click();await page.waitForFunction(()=>document.querySelector('.name-bound-comparison').dataset.state==='ready');};
  const evaluate=async next=>{mode=next;await page.locator('#load-name-bound-evaluation').click();await page.waitForFunction(()=>!['idle','loading'].includes(document.querySelector('.nb-evaluation').dataset.state));};
  await loadNumeric();assert.equal(requests.length,0);await evaluate('ready');assert.equal(await page.locator('.nb-evaluation-score').count(),3);assert.equal(await page.locator('.nb-probability').count(),240);
  for(const width of [1440,390]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'page overflow '+width);const scroll=page.locator('.nb-evaluation-content .table-scroll');assert.equal(await scroll.getAttribute('tabindex'),'0');await scroll.evaluate(element=>element.scrollLeft=element.scrollWidth);assert.ok(await scroll.evaluate(element=>element.clientWidth>=element.scrollWidth||element.scrollLeft>0));}
  for(const next of ['error','missing','tamper','pending','no-result']){await evaluate(next);assert.equal(await page.locator('.nb-probability').count(),240);assert.equal(await page.locator('.nb-evaluation-score').count(),0);}
  mode='slow';await page.locator('#load-name-bound-evaluation').click();await page.waitForFunction(()=>document.querySelector('.nb-evaluation').dataset.state==='loading');await page.locator('#race-select').selectOption(SECOND);await page.locator('#race-select').selectOption(ID);await loadNumeric();await evaluate('ready');delays.splice(0).forEach(done=>done());await page.waitForFunction(()=>document.querySelectorAll('.nb-evaluation-score').length===3);
  mode='slow';await page.locator('#load-name-bound-evaluation').click();await page.waitForFunction(()=>document.querySelector('.nb-evaluation').dataset.state==='loading');version='777-1';await loadNumeric();assert.equal(await page.locator('.nb-evaluation-score').count(),0);await evaluate('ready');delays.splice(0).forEach(done=>done());assert.match(await page.locator('.nb-evaluation-version').innerText(),/777-1/);
  mode='slow';await page.locator('#load-name-bound-evaluation').click();await page.clock.runFor(15001);await page.waitForFunction(()=>document.querySelector('.nb-evaluation').dataset.state==='error');assert.equal(await page.locator('.nb-probability').count(),240);delays.splice(0).forEach(done=>done());
  await page.clock.setSystemTime(new Date('2026-10-16T00:00:05+09:00'));await page.clock.runFor(30000);assert.equal(await page.locator('.nb-evaluation-score').count(),0);assert.equal(await page.locator('#load-name-bound-evaluation').count(),0);assert.equal(await page.evaluate(()=>localStorage.getItem('raceai.ledger.v1')),null);assert.deepEqual(errors,[]);
  console.log('PASS: offline explicit selected-forecast evaluation; 3 scores, 240 numeric rows retained; errors/pending/timeout; A-B-A/new version/day; 1440/390 horizontal access; no ledger writes.');await context.close();
 }finally{if(browser)await browser.close();server.close();}
}
if(require.main===module)runBrowserHarness().catch(error=>{console.error(error);process.exitCode=1;});
