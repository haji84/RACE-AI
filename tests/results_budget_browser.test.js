/* Invented saved originals: observed results and editable daily simulation. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const http=require('node:http'),{spawnSync}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),folder=fs.mkdtempSync(path.join(os.tmpdir(),'results-budget-'));
let server,browser;
(async()=>{
 const py=spawnSync(process.env.RACE_AI_TEST_PYTHON||'python',['-c',`
from pathlib import Path
import sys,json
from tests.test_boat_pdca_github_handoff import invented_research_state
from tests.test_boat_history_comparison import current,NOW
from race_ai.boat_history_comparison import prepare_pair,freeze_pair
from race_ai.boat_history_store import HistoryStore,instant
from race_ai.boat_pdca_state import PdcaState
from race_ai.saved_pdca_view import SavedPdcaService,export_view
r=Path(sys.argv[1]);p,_=invented_research_state(r)
h=HistoryStore(r/'history.sqlite');snap=current();snap['race_id']='boat:2026-11-06:boatrace-jcd-17:2'
snap['sales_cutoff_at']='2026-11-06T11:01:00+09:00'
pair=prepare_pair(snap,h,NOW);h.close();freeze_pair(pair,r/'second.json',clock=lambda:instant(NOW))
s=PdcaState(p);s.retain_pair(r/'second.json');s.close()
view=SavedPdcaService(p).saved_projection()
view['records'][0]['result'].update(winning_combinations=[view['records'][0]['prediction']['ordered_top8'][0]],payout_yen_per_100=1200)
view['records'][0]['result_observations']=[]
export_view(view,r/'view.html')
(r/'expected.json').write_text(json.dumps(view))
from copy import deepcopy
multi=deepcopy(view);winning=multi['records'][0]['prediction']['ordered_top8'][:2]
multi['records'][0]['result'].update(winning_combinations=winning,payout_yen_per_100=99999,payouts=[{'bet_type':'trifecta','combination':winning[0],'payout_per_100_yen':1230},{'bet_type':'trifecta','combination':winning[1],'payout_per_100_yen':4560}])
export_view(multi,r/'multi.html')
missing=deepcopy(view);missing['records']=missing['records'][:1];missing['records'][0].update(prediction=None,comparison_predictions=[])
export_view(missing,r/'no-forecast.html')
overflow=deepcopy(view)
for record in overflow['records']:
 record['result']=deepcopy(view['records'][0]['result']);record['result'].update(winning_combinations=[record['prediction']['ordered_top8'][0]],payout_yen_per_100=9007199254740991)
 record['result_observations']=[]
(r/'overflow.json').write_text(json.dumps(overflow))
`,folder],{cwd:root,encoding:'utf8'});assert.equal(py.status,0,py.stderr);
 const original=JSON.parse(fs.readFileSync(path.join(folder,'expected.json')));
 server=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');const name=['/multi.html','/no-forecast.html'].includes(req.url)?req.url.slice(1):'view.html';res.end(fs.readFileSync(path.join(folder,name)));});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:fs.existsSync('/usr/bin/chromium')?{executablePath:'/usr/bin/chromium'}:{}),args:['--no-sandbox']});
 for(const width of [390,1440]){
  const page=await browser.newPage({viewport:{width,height:1000}}),errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push({method:r.method(),url:r.url()}));
  await page.goto('http://127.0.0.1:'+server.address().port+'/');
  await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('保存済み予想'));
  assert.equal(await page.locator('#page-races .saved-outcome').count(),2);
  await page.locator('#status-filter').selectOption('HIT');assert.equal(await page.locator('#all-races .saved-outcome').count(),1);
  await page.locator('#status-filter').selectOption('PREDICTION_UNVERIFIED');assert.equal(await page.locator('#all-races .saved-outcome').count(),2);
  await page.locator('#status-filter').selectOption('all');
  await page.locator('[data-page="results"]').filter({visible:true}).first().click();
  await page.locator('#simulation-budget').waitFor();assert.equal(await page.locator('#simulation-budget').inputValue(),'10000');
  assert.equal(await page.locator('#results-model option').count(),4);
  assert.equal(await page.locator('#saved-results-table tbody tr').count(),2);
  assert.match(await page.locator('#saved-results-table').innerText(),/的中/);
  assert.match(await page.locator('#saved-results-table').innerText(),/結果待ち/);
  assert.match(await page.locator('#simulation-metrics').innerText(),/1,600円/);
  assert.match(await page.locator('#simulation-metrics').innerText(),/800円/);
  assert.match(await page.locator('#simulation-metrics').innerText(),/未確定/);
  const budget=page.locator('#simulation-budget');await budget.fill('1000');await budget.press('Tab');
  assert.equal(await budget.inputValue(),'1000');assert.match(await page.locator('#simulation-metrics').innerText(),/200円/);
  assert.match(await page.locator('#simulation-metrics').innerText(),/400円/);
  await budget.fill('50');await budget.press('Tab');assert.equal(await budget.inputValue(),'1000');
  assert.match(await page.locator('#simulation-message').innerText(),/100円/);
  assert.match(await page.locator('#result-metrics').innerText(),/未検証/);
  const data=await page.evaluate(()=>JSON.parse(document.querySelector('#race-ai-private-saved-data').textContent));
  assert.deepEqual(data,original);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  assert.equal(requests.some(r=>r.method!=='GET'),false);assert.deepEqual(errors,[]);
  assert.ok(await page.locator('#simulation-comparison tbody tr').count()>0);
  await page.locator('#race-file').setInputFiles({name:'invented-overflow.json',mimeType:'application/json',buffer:fs.readFileSync(path.join(folder,'overflow.json'))});
  await page.waitForFunction(()=>document.querySelector('#simulation-message').textContent.includes('試算できない'));
  assert.equal(await page.locator('#simulation-comparison tbody tr').count(),0);
  assert.equal(await page.locator('#simulation-ledger tbody tr').count(),0);
  assert.equal(await page.locator('#saved-results-table tbody tr').count(),2);
  await page.goto('http://127.0.0.1:'+server.address().port+'/multi.html');
  await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('保存済み予想'));
  await page.locator('[data-page="results"]').filter({visible:true}).first().click();
  assert.match(await page.locator('#saved-results-table').innerText(),/1,230円/);assert.match(await page.locator('#saved-results-table').innerText(),/4,560円/);
  assert.match(await page.locator('#simulation-metrics').innerText(),/5,790円/);
  await page.locator('#saved-results-table button').first().click();assert.match(await page.locator('#race-detail').innerText(),/4,560円/);
  await page.goto('http://127.0.0.1:'+server.address().port+'/no-forecast.html');
  await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('保存済み予想'));
  await page.locator('[data-page="results"]').filter({visible:true}).first().click();
  assert.equal(await page.locator('#saved-results-table tbody tr').count(),1);
  assert.match(await page.locator('#result-coverage').innerText(),/対象 1レース/);
  assert.match(await page.locator('#saved-results-table').innerText(),/未予想/);await page.close();
 }
 console.log('PASS results + editable daily budget: observed hit/pending,4models,10k→1k,unknown money,originals/formal gates unchanged,mobile/desktop');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));fs.rmSync(folder,{recursive:true,force:true});});
