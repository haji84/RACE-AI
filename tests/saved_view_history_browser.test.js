/* Fictional data, actual WebCrypto, pinned immutable Git history routing. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http');
const {spawnSync}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'saved-history-'));
let browser,server;
(async()=>{
 const py=spawnSync(process.env.RACE_AI_TEST_PYTHON||'python',['-c',`
import sys,json
from copy import deepcopy
from pathlib import Path
import race_ai
race_ai.__path__.extend(str(Path(reference)/'race_ai') for reference in ('pr64-reference','pr72-reference'))
from tests.test_boat_pdca_github_handoff import invented_research_state
from race_ai.boat_pdca_state import PdcaState,sha
from race_ai.boat_history_store import wire
from race_ai.saved_pages import build_site,_viewer
from race_ai.boat_pdca_projection import project_pdca
from race_ai import saved_view_feed as F,saved_view_history as H
p=Path(sys.argv[1]);s,_=invented_research_state(p);state=PdcaState(s)
try:seed=project_pdca(state);pin=state.content_sha256()
finally:state.close()
b=build_site(s,p/'public',p/'private',expected_source_sha256=pin);key,vid=_viewer(p/'private/viewer.json');anchor=F.originals_sha(seed)
seed['forecast_base_sha256']=anchor;seed['source_native_numeric_marker']=1.0;files={}
def store(result,commit):
 for name,raw in result['files'].items():
  target=p/'objects'/commit/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
 return H.bind_history_locators(result.get('days',result.get('locator')),commit)
def day(day):
 v=json.loads(json.dumps(seed).replace('2026-11-06',day).replace('20261106',day.replace('-','')))
 v['records'][0]['venue']='架空履歴場'+day;v['records'][0]['saved_prediction_evidence']={}
 v['records'][0].update(result=None,result_observations=[],result_observation_rejections=[],result_revisions=[])
 return v
def save(name,raw):
 ident=sha(raw);(p/(name+'.json')).write_bytes(raw);(p/(name+'-latest.json')).write_text(wire(dict(header=json.loads(raw)['header'],cipher_sha256=ident)))
 return ident
one=save('v4',F.encrypt_view(seed,key,view_id=vid,source_sha=pin,generation=1,previous=b['cipher_sha256']))
both=deepcopy(seed);both['records']+=day('2026-11-07')['records'];both['event_date_jst']=None
novdays=store(H.encrypt_day_chunks(both,key,view_id=vid),'b'*40)
nov=H.build_history(novdays,current_month='2026-11',forecast_sha256=anchor)
two=save('nov',H.encrypt_history_router(nov,key,view_id=vid,source_sha=pin,generation=2,previous=one))
bad=deepcopy(both);bad['records'][0]['comparison_predictions'].pop()
badindex=H.build_history(store(H.encrypt_day_chunks(bad,key,view_id=vid),'e'*40),current_month='2026-11',forecast_sha256=anchor)
save('omitted',H.encrypt_history_router(badindex,key,view_id=vid,source_sha=pin,generation=2,previous=one))
catalog=store(H.encrypt_catalog(nov,key,view_id=vid),'c'*40)
decdays=store(H.encrypt_day_chunks(day('2026-12-01'),key,view_id=vid),'d'*40)
dec=H.build_history(decdays,current_month='2026-12',forecast_sha256=anchor,previous_catalog=catalog)
three=save('dec',H.encrypt_history_router(dec,key,view_id=vid,source_sha=pin,generation=3,previous=two))
corrected=deepcopy(both);corrected['results_synced_at']='2026-12-01T00:01:00Z';corrected['records'][0]['missing_reasons'].append('SYNTHETIC_LATE_RESULT_REVISION')
revised_novdays=store(H.encrypt_day_chunks(corrected,key,view_id=vid),'f'*40)
corrected_nov=H.build_history(revised_novdays,current_month='2026-11',forecast_sha256=anchor)
revised_catalog=store(H.encrypt_catalog(corrected_nov,key,view_id=vid),'1'*40)
revised_dec=H.build_history(decdays,current_month='2026-12',forecast_sha256=anchor,previous_catalog=revised_catalog)
save('dec-revised',H.encrypt_history_router(revised_dec,key,view_id=vid,source_sha=pin,generation=4,previous=three))
corrected['records'][0]['comparison_predictions'].pop()
incomplete_nov=H.build_history(store(H.encrypt_day_chunks(corrected,key,view_id=vid),'2'*40),current_month='2026-11',forecast_sha256=anchor)
incomplete_catalog=store(H.encrypt_catalog(incomplete_nov,key,view_id=vid),'3'*40)
bad_dec=H.build_history(decdays,current_month='2026-12',forecast_sha256=anchor,previous_catalog=incomplete_catalog)
save('dec-omitted',H.encrypt_history_router(bad_dec,key,view_id=vid,source_sha=pin,generation=4,previous=three))
(p/'expected.json').write_text(wire(dict(catalog=catalog,revised_catalog=revised_catalog,novdays=novdays,revised_novdays=revised_novdays,decdays=decdays)))
`,dir],{cwd:root,encoding:'utf8'});assert.equal(py.status,0,py.stderr);
 const expected=JSON.parse(fs.readFileSync(path.join(dir,'expected.json'))),requests=[],errors=[];
 let active='v4',corruptCatalog=false,missingDay=false,migrationGate=null;
 server=http.createServer((req,res)=>{const name=new URL(req.url,'http://local').pathname.slice(1)||'index.html',file=path.join(dir,'public',name);if(!fs.existsSync(file)){res.statusCode=404;return res.end();}res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:390,height:844}});page.setDefaultTimeout(10000);page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>requests.push({url:request.url(),headers:request.headers()}));
 const routeSaved=async route=>{
  const pathname=new URL(route.request().url()).pathname,prefix='/haji84/RACE-AI/';let body;
  if(pathname===prefix+'state/boat-saved-view/latest.json')body=fs.readFileSync(path.join(dir,active+'-latest.json'));
  else if(pathname.startsWith(prefix+'state/boat-saved-view/views/')) {
   body=fs.readFileSync(path.join(dir,active+'.json'));
   if(migrationGate&&active==='nov'){const gate=migrationGate;migrationGate=null;gate.seen();await gate.release;}
  }
  else {
   assert.match(pathname,new RegExp('^'+prefix+'[a-f0-9]{40}/views/[a-f0-9]{64}\\.json$'));
   if(missingDay&&[expected.novdays,expected.revised_novdays].some(days=>pathname.includes(days['2026-11-07'].chunks[0].cipher_sha256)))return route.fulfill({status:404,headers:{'access-control-allow-origin':'*'},body:''});
   const file=path.join(dir,'objects',pathname.slice(prefix.length));assert.equal(fs.existsSync(file),true);body=fs.readFileSync(file);
   if(corruptCatalog&&(pathname.includes(expected.catalog.cipher_sha256)||pathname.includes(expected.revised_catalog.cipher_sha256)))body=Buffer.concat([body,Buffer.from(' ')]);
  }
  await route.fulfill({contentType:'application/json',headers:{'access-control-allow-origin':'*'},body});
 };
 await page.route('https://raw.githubusercontent.com/haji84/RACE-AI/**',routeSaved);
 const fragment=fs.readFileSync(path.join(dir,'private/owner-url.txt'),'utf8').trim().split('#')[1],key=JSON.parse(fs.readFileSync(path.join(dir,'private/viewer.json'))).key;
 await page.clock.install({time:new Date('2026-11-06T00:00:00Z')});await page.goto('http://127.0.0.1:'+server.address().port+'/#'+fragment);
 await page.waitForFunction(()=>document.querySelector('#saved-view-sync')?.dataset.generation==='1');
 await page.evaluate(()=>{const api=window.SavedViewCrypto;window.__historyChecks=0;window.__dateReads=[];window.SavedViewCrypto={...api,readLive:async(...args)=>{try{return await api.readLive(...args);}finally{window.__historyChecks++;}},readDay:async(...args)=>{try{const value=await api.readDay(...args);window.__dateReads.push([args[2],'success']);return value;}catch(error){window.__dateReads.push([args[2],'failed']);throw error;}}};});
 async function tick(){const before=await page.evaluate(()=>window.__historyChecks);await page.clock.fastForward(61000);await page.waitForFunction(before=>window.__historyChecks>before,before);}
 async function chooseDay(day){
  const count=await page.evaluate(()=>window.__dateReads.length);
  await page.evaluate(day=>{const input=document.querySelector('#selected-date');input.value=day;input.dispatchEvent(new Event('change',{bubbles:true}));document.activeElement?.blur();},day);
  await page.waitForFunction(({day,count})=>window.__dateReads.slice(count).some(value=>value[0]===day),{day,count});
 }
 await page.locator('[data-race-view="results"]').click();
 await page.locator('#page-races [data-open-race]').first().click();await page.locator('#prediction-select').selectOption('2');
 await page.locator('[data-page="picks"]').filter({visible:true}).first().click();await page.locator('#copy-top8').click();
 await page.locator('#ticket-list .ticket-amount').first().fill('200');await page.locator('#ticket-list .ticket-amount').first().dispatchEvent('change');
 await page.locator('[data-page="results"]').filter({visible:true}).first().click();await page.locator('#results-model').selectOption({index:2});const group=await page.locator('#results-model').inputValue();
 await page.locator('#simulation-budget').fill('5000');await page.locator('#simulation-budget').dispatchEvent('change');await page.locator('#result-coverage').click();
 active='omitted';await tick();assert.equal(await page.locator('#saved-view-sync').getAttribute('data-generation'),'1','an archive omitting an old forecast cannot replace the previous display');
 let releaseMigration,seenMigration;
 const heldMigration=new Promise(resolve=>{releaseMigration=resolve;}),migrationSeen=new Promise(resolve=>{seenMigration=resolve;});
 migrationGate={release:heldMigration,seen:seenMigration};active='nov';const pendingMigration=tick();await migrationSeen;
 await page.evaluate(()=>{
  window.__historyDateMismatches=[];
  window.__historyDateObserver=new MutationObserver(()=>{
   const status=document.querySelector('#saved-view-sync'),source=document.querySelector('#source-date').textContent.match(/^対象日：(\d{4}-\d{2}-\d{2})$/)?.[1];
   if(Number(status?.dataset.generation)>=2&&source&&(document.querySelector('#selected-date').value!==source||status.dataset.historyDay!==source))window.__historyDateMismatches.push([document.querySelector('#selected-date').value,source,status.dataset.historyDay]);
  });window.__historyDateObserver.observe(document.body,{childList:true,subtree:true,attributes:true});
  const input=document.querySelector('#selected-date');input.value='2026-11-07';input.dispatchEvent(new Event('change',{bubbles:true}));document.activeElement?.blur();
 });
 assert.match(await page.locator('#display-day').textContent(),/2026-11-07/,'a pending feed check preserves ordinary V4 date filtering');
 assert.equal(await page.locator('#saved-view-sync').getAttribute('data-generation'),'1');
 releaseMigration();await pendingMigration;await page.waitForFunction(()=>document.querySelector('#saved-view-sync')?.dataset.generation==='2');
 assert.deepEqual(await page.evaluate(()=>window.__historyDateMismatches),[],'a V5 result must never label one date with another date\'s races');
 await page.waitForFunction(()=>document.querySelector('#source-date').textContent==='対象日：2026-11-07');
 await page.evaluate(()=>window.__historyDateObserver.disconnect());
 assert.deepEqual(await page.evaluate(()=>window.__historyDateMismatches),[],'queued date adoption stays coherent through its final render');
 assert.equal(await page.locator('#selected-date').inputValue(),'2026-11-07');assert.equal(await page.locator('#saved-view-sync').getAttribute('data-history-day'),'2026-11-07');
 assert.equal(await page.locator('#simulation-budget').inputValue(),'5000');assert.equal(await page.locator('#results-model').inputValue(),group);
 await chooseDay('2026-11-06');await page.waitForFunction(()=>document.querySelector('#source-date').textContent==='対象日：2026-11-06');
 assert.equal(await page.locator('#selected-date').inputValue(),'2026-11-06');assert.equal(await page.locator('#simulation-budget').inputValue(),'5000');assert.equal(await page.locator('#results-model').inputValue(),group);
 active='dec';corruptCatalog=true;await tick();assert.equal(await page.locator('#saved-view-sync').getAttribute('data-generation'),'2');
 corruptCatalog=false;await tick();await page.waitForFunction(()=>document.querySelector('#saved-view-sync')?.dataset.generation==='3');
 active='dec-omitted';await tick();assert.equal(await page.locator('#saved-view-sync').getAttribute('data-generation'),'3','late archived correction cannot omit an original');
 active='dec-revised';await tick();await page.waitForFunction(()=>document.querySelector('#saved-view-sync')?.dataset.generation==='4');
 await chooseDay('2026-12-01');await page.waitForFunction(()=>document.querySelector('#source-date').textContent.includes('2026-12-01'));
 missingDay=true;await chooseDay('2026-11-07');await page.waitForFunction(()=>document.querySelector('#saved-view-sync').textContent.includes('前回取得'));
 assert.equal(await page.locator('#selected-date').inputValue(),'2026-12-01');assert.match(await page.locator('#source-date').textContent(),/2026-12-01/);
 missingDay=false;corruptCatalog=true;await chooseDay('2026-11-06');await page.waitForFunction(()=>document.querySelector('#saved-view-sync').textContent.includes('前回取得')).catch(async error=>{console.error({dateReads:await page.evaluate(()=>window.__dateReads),status:await page.locator('#saved-view-sync').textContent(),day:await page.locator('#selected-date').inputValue(),paths:requests.filter(request=>request.url.startsWith('https://raw.githubusercontent.com/')).slice(-8).map(request=>new URL(request.url).pathname)});throw error;});
 assert.equal(await page.locator('#selected-date').inputValue(),'2026-12-01');
 corruptCatalog=false;await chooseDay('2026-11-06');await page.waitForFunction(()=>document.querySelector('#source-date').textContent.includes('2026-11-06'));
 assert.equal(await page.locator('#results-model').inputValue(),group);assert.equal(await page.locator('#simulation-budget').inputValue(),'5000');
 await page.locator('[data-page="races"]').filter({visible:true}).first().click();await page.locator('[data-race-view="results"]').click();await page.locator('#page-races [data-open-race]').first().click();assert.equal(await page.locator('#prediction-select').inputValue(),'2');
 await page.locator('[data-page="picks"]').filter({visible:true}).first().click();assert.equal(await page.locator('#ticket-list .ticket-amount').count(),8);assert.equal(await page.locator('#ticket-list .ticket-amount').first().inputValue(),'200');
 assert.equal((await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).includes(key),false);assert.equal(requests.some(request=>JSON.stringify(request).includes(key)),false);assert.deepEqual(errors,[]);
 await page.locator('[data-page="settings"]').filter({visible:true}).first().click();await page.locator('#data-tools > summary').click();await page.locator('#clear-data').click();
 assert.equal(await page.locator('[data-result-refresh]').first().isDisabled(),true,'clearing the view must disable its result refresh control');
 assert.equal(await page.locator('#period-all').isDisabled(),false,'leaving history restores ordinary import period controls');
 // The static encrypted seed is older than the live feed. Opening the site on
 // November 7 must reveal that day's already-saved originals without a date edit.
 const current=await browser.newPage({viewport:{width:390,height:844}});
 current.on('pageerror',error=>errors.push(error.message));
 await current.route('https://raw.githubusercontent.com/haji84/RACE-AI/**',routeSaved);
 await current.clock.install({time:new Date('2026-11-07T00:00:00Z')});
 active='nov';
 await current.goto('http://127.0.0.1:'+server.address().port+'/#'+fragment);
 await current.waitForFunction(()=>document.querySelector('#saved-view-sync')?.dataset.generation==='2');
 assert.equal(await current.locator('#selected-date').inputValue(),'2026-11-07','initial live sync must display today instead of pinning the old seed day');
 assert.equal(await current.locator('#source-date').textContent(),'対象日：2026-11-07');
 assert.ok(await current.locator('#page-races [data-open-race]').count()>0,'today must expose the saved race cards');
 await current.locator('#selected-date').fill('2026-11-06');await current.locator('#selected-date').dispatchEvent('change');
 await current.waitForFunction(()=>document.querySelector('#source-date').textContent==='対象日：2026-11-06');
 await current.clock.fastForward(61000);
 assert.equal(await current.locator('#selected-date').inputValue(),'2026-11-06','automatic checks must preserve an explicitly selected historical date');
 await current.close();
 for(const scenario of ['late-publication','midnight']) {
  const live=await browser.newPage({viewport:{width:390,height:844}});
  live.on('pageerror',error=>errors.push(error.message));
  await live.route('https://raw.githubusercontent.com/haji84/RACE-AI/**',routeSaved);
  await live.clock.install({time:new Date(scenario==='midnight'?'2026-11-06T00:00:00Z':'2026-11-07T00:00:00Z')});
  active=scenario==='midnight'?'nov':'v4';
  await live.goto('http://127.0.0.1:'+server.address().port+'/#'+fragment);
  await live.waitForFunction(expected=>document.querySelector('#saved-view-sync')?.dataset.generation===expected,scenario==='midnight'?'2':'1');
  assert.equal(await live.locator('#selected-date').inputValue(),'2026-11-06','older saved forecasts remain visible while waiting for newer races');
  if(scenario==='late-publication')assert.ok(await live.locator('#page-races [data-open-race]').count()>0,'an older saved day remains explicitly selectable, never mislabeled as today');
  if(scenario==='midnight')await live.clock.setSystemTime(new Date('2026-11-07T00:00:00Z'));
  active='nov';await live.clock.fastForward(61000);
  await live.waitForFunction(()=>document.querySelector('#selected-date').value==='2026-11-07');
  await live.waitForFunction(()=>document.querySelector('#source-date').textContent==='対象日：2026-11-07');
  assert.equal(await live.locator('#source-date').textContent(),'対象日：2026-11-07',scenario+' must show today after synchronization');
  assert.ok(await live.locator('#page-races [data-open-race]').count()>0,scenario+' switches to the upcoming list');
  await live.close();
 }
 assert.deepEqual(errors,[]);
 console.log('PASS bounded owner history: V4->V5, two months, pinned encrypted archives/date selection, omitted originals/corrupt index/missing day held, model/budget/draft preserved, no key requests/storage');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));fs.rmSync(dir,{recursive:true,force:true});});
