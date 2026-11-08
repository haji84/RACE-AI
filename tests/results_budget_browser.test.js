/* Invented saved originals: observed results and editable daily simulation. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const http=require('node:http'),{spawnSync}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),folder=fs.mkdtempSync(path.join(os.tmpdir(),'results-budget-'));
let server,browser;
async function checkUnverifiedOfficialMetrics(page){
 const details=page.locator('#result-data-details'),open=await details.evaluate(element=>element.open);
 if(!open)await details.locator(':scope > summary').click();
 assert.equal(await page.locator('#result-metrics').isVisible(),true);
 assert.match(await page.locator('#result-metrics').innerText(),/未検証/);
 if(!open)await details.locator(':scope > summary').click();
}
(async()=>{
 const py=spawnSync(process.env.RACE_AI_TEST_PYTHON||'python',['-c',`
from pathlib import Path
import sys,json
import race_ai
race_ai.__path__.extend(str(Path(reference)/'race_ai') for reference in ('pr64-reference','pr72-reference'))
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
from tests.test_saved_result_sync import packet
from race_ai.saved_result_sync import retain_batch
import hashlib
def retain_source(raw,at):
 raw=raw.replace(b'20300401',b'20261106').replace(b'jcd=01',b'jcd=17')
 meta=dict(source_url='https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=17&hd=20261106',captured_at=at,source_sha256=hashlib.sha256(raw).hexdigest(),http_status=200)
 journal=PdcaState(p);retain_batch(journal,[],[dict(raw=raw,receipt=meta)]);journal.close()
retain_source(packet(cancel=True,finish=False),'2026-11-06T03:30:00Z')
export_view(SavedPdcaService(p).saved_projection(),r/'cancelled.html')
retain_source(packet(),'2026-11-06T03:31:00Z')
export_view(SavedPdcaService(p).saved_projection(),r/'reference.html')
`,folder],{cwd:root,encoding:'utf8'});assert.equal(py.status,0,py.stderr);
 const original=JSON.parse(fs.readFileSync(path.join(folder,'expected.json')));
 server=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');const name=['/multi.html','/no-forecast.html','/cancelled.html','/reference.html'].includes(req.url)?req.url.slice(1):'view.html';res.end(fs.readFileSync(path.join(folder,name)));});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:fs.existsSync('/usr/bin/chromium')?{executablePath:'/usr/bin/chromium'}:{}),args:['--no-sandbox']});
 for(const width of [390,1440]){
  const page=await browser.newPage({viewport:{width,height:1000}}),errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push({method:r.method(),url:r.url()}));
  await page.goto('http://127.0.0.1:'+server.address().port+'/');
  await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('保存済み予想'));
  // This fixture is a saved historical day, not the current-day landing view.
  await page.locator('#selected-date').fill(original.records[0].event_date_jst);
  await page.locator('#selected-date').dispatchEvent('change');
  assert.equal(await page.locator('#page-races .saved-outcome').count(),2);
  await page.locator('#race-filters>summary').click();
  await page.locator('#status-filter').selectOption('HIT');assert.equal(await page.locator('#all-races .saved-outcome').count(),1);
  await page.locator('#status-filter').selectOption('PREDICTION_UNVERIFIED');assert.equal(await page.locator('#all-races .saved-outcome').count(),0,'neither the observed hit nor the pending race is held for comparison');
  await page.locator('#status-filter').selectOption('all');
  await page.locator('[data-page="results"]').filter({visible:true}).first().click();
  await page.locator('#simulation-budget').waitFor();assert.equal(await page.locator('#simulation-budget').inputValue(),'10000');
  assert.equal(await page.locator('#results-model option').count(),4);
  assert.equal(await page.locator('#saved-results-table tbody tr').count(),2);
  assert.match(await page.locator('#saved-results-table').innerText(),/的中/);
  assert.match(await page.locator('#saved-results-table').innerText(),/結果待ち/);
  const savedRate=page.locator('#saved-result-metrics .metric').filter({hasText:'保存Top8的中率'});
  assert.equal(await savedRate.count(),1);assert.match(await savedRate.innerText(),/100\.0%/);assert.match(await savedRate.innerText(),/1 \/ 1/);
  const boughtRate=page.locator('#simulation-metrics .metric').filter({hasText:'購入予定分の的中率'});
  assert.equal(await boughtRate.count(),1);assert.match(await boughtRate.innerText(),/100\.0%/);
  assert.match(await page.locator('#simulation-comparison thead').innerText(),/的中率/);
  assert.match(await page.locator('#simulation-comparison thead').innerText(),/確定分回収率/);
  assert.match(await page.locator('#simulation-metrics').innerText(),/1,600円/);
  assert.match(await page.locator('#simulation-metrics').innerText(),/800円/);
  assert.match(await page.locator('#simulation-metrics').innerText(),/未確定/);
  const budget=page.locator('#simulation-budget');await budget.fill('1000');await budget.press('Tab');
  assert.equal(await budget.inputValue(),'1000');assert.match(await page.locator('#simulation-metrics').innerText(),/200円/);
  assert.match(await page.locator('#simulation-metrics').innerText(),/400円/);
  const raceBudget=page.locator('#simulation-race-budget');assert.equal(await raceBudget.inputValue(),'800');
  await raceBudget.selectOption('1000');
  assert.match(await page.locator('#simulation-rule').innerText(),/モデル間の支持/);
  assert.match(await page.locator('#simulation-metrics').innerText(),/1,000円/);
  assert.equal(await page.locator('#simulation-comparison tbody tr').count(),8);
  await page.locator('#simulation-ledger-details > summary').click();
  const allocation=page.locator('#simulation-ledger tbody tr').first().locator('details');await allocation.locator('summary').click();
  assert.match(await allocation.innerText(),/支持モデル/);assert.match(await allocation.innerText(),/履歴安定/);
  await raceBudget.selectOption('800');
  await budget.fill('700');await budget.press('Tab');
  assert.match(await boughtRate.innerText(),/算出対象なし/);assert.match(await savedRate.innerText(),/100\.0%/);
  await budget.fill('1000');await budget.press('Tab');
  await budget.fill('50');await budget.press('Tab');assert.equal(await budget.inputValue(),'1000');
  assert.match(await page.locator('#simulation-message').innerText(),/100円/);
  await checkUnverifiedOfficialMetrics(page);
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
  // This fixture is a saved historical day, not the current-day landing view.
  await page.locator('#selected-date').fill(original.records[0].event_date_jst);
  await page.locator('#selected-date').dispatchEvent('change');
  await page.locator('[data-page="results"]').filter({visible:true}).first().click();
  assert.match(await page.locator('#saved-results-table').innerText(),/1,230円/);assert.match(await page.locator('#saved-results-table').innerText(),/4,560円/);
  assert.match(await page.locator('#simulation-metrics').innerText(),/5,790円/);
  await page.locator('#saved-results-table button').filter({visible:true}).first().click();assert.match(await page.locator('#race-detail').innerText(),/4,560円/);
  await page.goto('http://127.0.0.1:'+server.address().port+'/no-forecast.html');
  await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('保存済み予想'));
  // This fixture is a saved historical day, not the current-day landing view.
  await page.locator('#selected-date').fill(original.records[0].event_date_jst);
  await page.locator('#selected-date').dispatchEvent('change');
  await page.locator('[data-page="results"]').filter({visible:true}).first().click();
  assert.equal(await page.locator('#saved-results-table tbody tr').count(),1);
  assert.match(await page.locator('#result-coverage').innerText(),/対象 1レース/);
  assert.match(await page.locator('#saved-results-table').innerText(),/未予想/);
  assert.match(await savedRate.innerText(),/算出対象なし/);
  await page.goto('http://127.0.0.1:'+server.address().port+'/cancelled.html');
  await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('保存済み予想'));
  // This fixture is a saved historical day, not the current-day landing view.
  await page.locator('#selected-date').fill(original.records[0].event_date_jst);
  await page.locator('#selected-date').dispatchEvent('change');
  await page.locator('[data-page="results"]').filter({visible:true}).first().click();
  assert.match(await page.locator('#saved-results-table').innerText(),/中止・返還/);
  assert.match(await page.locator('#simulation-metrics').innerText(),/返還 800円/);
  assert.match(await page.locator('#result-coverage').innerText(),/最終同期/);
  await page.goto('http://127.0.0.1:'+server.address().port+'/reference.html');
  await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('保存済み予想'));
  // This fixture is a saved historical day, not the current-day landing view.
  await page.locator('#selected-date').fill(original.records[0].event_date_jst);
  await page.locator('#selected-date').dispatchEvent('change');
  await page.locator('[data-page="results"]').filter({visible:true}).first().click();
  assert.match(await page.locator('#saved-results-table').innerText(),/参考照合/);
  const referenceCard=page.locator('#saved-results-table .result-mobile-card').filter({hasText:'宮島 1R'});
  const referenceRow=page.locator('#saved-results-table .result-list-table tbody tr').filter({hasText:'宮島 1R'});
  const visibleReference=width<600?referenceCard:referenceRow;
  assert.equal(await visibleReference.count(),1);assert.equal(await visibleReference.isVisible(),true);
  assert.match(await visibleReference.innerText(),/締切変更を照合済み（参考）/);
  // The ordinary list presents the short explanation. Exact original clocks
  // remain in the immutable embedded data, rather than becoming new UI text.
  const referenceData=await page.evaluate(()=>JSON.parse(document.querySelector('#race-ai-private-saved-data').textContent));
  const referenceRecord=referenceData.records.find(record=>record.race_id===original.records[0].race_id);
  assert.equal(referenceRecord.cutoff_at,'2026-11-06T10:59:00+09:00');
  assert.equal(referenceRecord.result.cutoff_reference.original_cutoff_at,'2026-11-06T10:59:00+09:00');
  assert.equal(referenceRecord.result.cutoff_reference.result_schedule_cutoff_at,'2026-11-06T11:00:00+09:00');
  assert.equal(referenceRecord.result.cutoff_reference.offset_seconds,60);
  assert.deepEqual(referenceData.records.map(record=>({race_id:record.race_id,prediction:record.prediction,
    comparison_predictions:record.comparison_predictions})),original.records.map(record=>({race_id:record.race_id,
    prediction:record.prediction,comparison_predictions:record.comparison_predictions})));
  assert.match(await page.locator('#result-coverage').innerText(),/締切差の参考照合 1/);
  await checkUnverifiedOfficialMetrics(page);await page.close();
 }
 console.log('PASS results + editable daily budget: observed hit/pending,4models,10k→1k,unknown money,originals/formal gates unchanged,mobile/desktop');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));fs.rmSync(folder,{recursive:true,force:true});});
