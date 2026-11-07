import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const require=createRequire(import.meta.url),{chromium}=require('playwright');
const web=path.resolve(fileURLToPath(new URL('../web/',import.meta.url)));
const six=[[1,3,6],[1,6,3],[3,1,6],[3,6,1],[6,1,3],[6,3,1]];

function fixture(){
 const p={model_id:'fictional-model',model_version:'v1',stage:'P0',variant:'HISTORY_BASELINE',
  ordered_top8:structuredClone(six),ordered_candidates:structuredClone(six),prediction_sha256:'a'.repeat(64),
  input_sha256:'b'.repeat(64),source_sha256:'c'.repeat(64),as_of:'2030-04-01T09:00:00+09:00',
  generated_at:'2030-04-01T09:00:01+09:00',persisted_at:'2030-04-01T09:01:00+09:00',
  cutoff_at:'2030-04-01T10:00:00+09:00',odds_independent:true};
 const row={race_id:'20300401-01-01',sport:'boat',venue:'合成場',race_no:1,event_date_jst:'2030-04-01',
  offering_status:'UNKNOWN',cutoff_at:p.cutoff_at,saved_cutoff_variants:[p.cutoff_at],
  participants:[{number:1,registration_no:'4201',name:'合成アルファ'},{number:3,registration_no:'4203',name:'合成ベータ'},{number:6,registration_no:'4206',name:null}],
  prediction:p,comparison_predictions:[],result:null,result_observations:[],result_observation_rejections:[],result_revisions:[]};
 return {schema:'RACE_AI_PRIVATE_CYCLE_VIEW_V1',dataset_status:'SYNTHETIC_ONLY',event_date_jst:'2030-04-01',records:[row]};
}

async function withSite(data,run){
 const browser=await chromium.launch({headless:true,args:['--no-sandbox'],executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium'});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());assert.equal(url.origin,'https://saved-model-names.test');
   const file=path.resolve(web,url.pathname==='/'?'index.html':url.pathname.slice(1));
   if(!file.startsWith(web+path.sep)||!existsSync(file))return route.fulfill({status:404,body:''});
   await route.fulfill({status:200,contentType:{'.html':'text/html','.js':'text/javascript','.css':'text/css'}[path.extname(file)],body:readFileSync(file)});
  });
  await page.clock.install({time:new Date('2030-04-01T00:30:00Z')});await page.goto('https://saved-model-names.test/');
  await page.locator('#race-file').setInputFiles({name:'fictional-saved-union.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(data))});
  await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('端末内で読み込みました'));
  await page.locator('#page-home [data-open-race]').first().click();
  await run(page);assert.deepEqual(errors,[]);
 }finally{await browser.close();}
}

test('racer cards and observation tables prefer registration-bound names and retain honest unknowns',async()=>{
 const data=fixture(),r=data.records[0];
 r.boat_observation_context={forecast_inputs_used:false,beforeinfo:{schema:'RACE_AI_BOAT_OBSERVATION_CONTEXT_V1',kind:'beforeinfo',race_id:r.race_id,
  status:'PARSED',roster_binding_status:'VERIFIED',forecast_ready:false,source_cutoff_at:r.cutoff_at,
  source:{source_url:'https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=1&jcd=01&hd=20300401',sha256:'d'.repeat(64),captured_at:'2030-04-01T09:10:00+09:00'},
  participants:[{lane:1,registration_number:'4201',name:null,bodyweight_kg:52},{lane:3,registration_number:'4999',name:null},{lane:6,registration_number:'4206',name:null}]}};
 await withSite(data,async page=>{
  const cards=page.locator('#detail-tab-content .racer-card');assert.equal(await cards.count(),3);
  assert.match(await cards.nth(0).innerText(),/合成アルファ/);assert.match(await cards.nth(2).innerText(),/名前 未取得/);
  const numbers=await cards.locator('.racer-avatar .lane').allTextContents();assert.deepEqual(numbers.map(s=>s.trim()),['1','3','6']);
  await page.locator('[data-detail-tab="preview"]').click();
  const rows=page.locator('#boat-context-beforeinfo table').first().locator('tbody tr');
  assert.match(await rows.nth(0).innerText(),/合成アルファ.*4201/s);
  assert.match(await rows.nth(1).innerText(),/名前 未取得.*4999/s);
  assert.doesNotMatch(await rows.nth(1).innerText(),/合成ベータ/,'physical lane does not supply another registration name');
  assert.match(await rows.nth(2).innerText(),/名前 未取得.*4206/s);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 });
});

test('all saved model groups and repeated originals remain selectable beside editable budgets',async()=>{
 const data=fixture(),r=data.records[0],p=r.prediction;
 r.comparison_predictions=[{...structuredClone(p),variant:'HISTORY_ADDED'},
  {...structuredClone(p),model_id:'fictional-model-b'},
  {...structuredClone(p),model_id:'fictional-model-b',variant:'HISTORY_ADDED'},
  {...structuredClone(p),model_id:'fictional-native',stage:'P1',variant:'NATIVE',model_version:null,source_code_commit:'9'.repeat(40),artifact_id:17,original_json_sha256:'d'.repeat(64)},
  {...structuredClone(p),as_of:'2030-04-01T09:00:01+09:00'}];
 await withSite(data,async page=>{
  assert.equal(await page.locator('#prediction-select option').count(),6);
  const labels=await page.locator('#prediction-select option').allTextContents();assert.equal(new Set(labels).size,6,'save clocks distinguish same-model originals');
  assert.match(labels[5],/09:00:01/,'the saved as-of distinguishes a repeated model original');
  await page.locator('#prediction-select').selectOption('4');
  const combos=await page.locator('#detail-tab-content .saved-ticket .combo').evaluateAll(nodes=>nodes.map(n=>[...n.querySelectorAll('.lane')].map(lane=>Number(lane.textContent))));
  assert.deepEqual(combos,six,'forecast combinations stay physical lane tickets');
  await page.locator('[data-page="settings"]').filter({visible:true}).first().click();
  await page.locator('#daily-budget').fill('2700');await page.locator('#settings-form button[type="submit"]').click();
  await page.locator('[data-page="results"]').filter({visible:true}).first().click();
  assert.equal(await page.locator('#results-model option').count(),5);
  assert.match((await page.locator('#results-model option').allTextContents()).join('\n'),/保存コード 9999999/,'missing model version is represented by the bound source commit');
  assert.match((await page.locator('#results-model option').allTextContents()).join('\n'),/複数原本/,'ambiguous same-model saves remain visible');
  const key=await page.locator('#results-model option').filter({hasText:'fictional-native'}).getAttribute('value');
  await page.locator('#results-model').selectOption(key);await page.locator('#simulation-budget').fill('1200');await page.locator('#simulation-budget').dispatchEvent('change');
  assert.match(await page.locator('#simulation-metrics').innerText(),/600/);
  assert.match(await page.locator('#simulation-rule').innerText(),/6点|6通り/,'six-ticket cost is explained');
  await page.locator('[data-page="races"]').filter({visible:true}).first().click();await page.locator('#page-races [data-open-race]').first().click();
  assert.equal(await page.locator('#prediction-select').inputValue(),'4','budget edits retain the saved model choice');
  await page.locator('[data-page="settings"]').filter({visible:true}).first().click();assert.equal(await page.locator('#daily-budget').inputValue(),'2700');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 });
});

test('reconciled cutoff variants stay visibly marked as reference results',async()=>{
 const data=fixture(),r=data.records[0],first=r.cutoff_at,second='2030-04-01T10:01:00+09:00';
 r.cutoff_at=null;r.saved_cutoff_variants=[first,second];r.comparison_predictions=[{...structuredClone(r.prediction),stage:'P1',cutoff_at:second}];
 r.result_observations=[{race_id:r.race_id,captured_at:'2030-04-01T11:00:00+09:00',closed_at:second,source_sha256:'f'.repeat(64),status:'AVAILABLE',body_identity_verified:true,
  data:{status:'settled',confirmed:true,finish_confirmed:true,top3:[1,3,6],payouts:[{bet_type:'trifecta',combination:[1,3,6],payout_per_100_yen:1200}],results:r.participants.map((p,i)=>({lane:p.number,racer_registration_id:p.registration_no,finish:i+1,finish_status:'FINISHED'}))}}];
 r.result={status:'final',winning_combinations:[[1,3,6]],payout_yen_per_100:1200,observed_at:'2030-04-01T11:00:00+09:00',source_sha256:'f'.repeat(64),official:false,
  cutoff_reconciliation:{basis:'RAW_OFFICIAL_RESULT_PER_ORIGINAL_CUTOFF',formal_eligible:false,original_cutoffs:[first,second],source_sha256:'f'.repeat(64),maximum_offset_seconds:60,roster_identity_verified:true,all_originals_saved_before_both:true}};
 r.result_observation_rejections=[{captured_at:r.result.observed_at,source_sha256:'f'.repeat(64),reason:'RESULT_AMBIGUOUS_FORECAST_CUTOFF'}];
 await withSite(data,async page=>{
  await page.locator('[data-page="results"]').filter({visible:true}).first().click();
  assert.match(await page.locator('#saved-results-table').innerText(),/参考照合/);
  assert.match(await page.locator('#result-coverage').innerText(),/締切差の参考照合 1/);
  assert.match(await page.locator('#saved-results-table').innerText(),/10:00.*10:01/s,'both exact original cutoff minutes remain visible');
 });
});
