/* Invented race/forecast only, reproducing the reported phone audit clutter. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'../web'),folder=process.env.UI_RESULT_EVIDENCE||path.resolve(__dirname,'../artifacts/ui-browser/result-detail');
const p={stage:'P0',model_id:'boat-observed-pairwise-factor-v1',model_version:'0.1.0-UNTRAINED',ordered_top8:[[1,2,3],[1,3,2],[2,1,3],[2,3,1],[3,1,2],[3,2,1],[1,2,4],[1,3,4]],generated_at:'2026-11-07T01:10:00+09:00',persisted_at:'2026-11-07T01:11:00+09:00',cutoff_at:'2026-11-07T10:25:00+09:00',input_sha256:'a'.repeat(64),prediction_sha256:'b'.repeat(64),odds_independent:true,missing_reasons:['INDEPENDENT_RECEIPT_NOT_VERIFIED']};
p.rationale='架空の予想根拠：1コースの先行とモーター比較を評価。';
const later={...p,stage:'P1',rationale:'架空の予想根拠：展示の進入とスタートを評価。',input_sha256:'e'.repeat(64),missing_reasons:['SOURCE_SHA_NOT_SAVED']};
const r={race_id:'20261107-11-01',sport:'boat',venue:'びわこ',race_no:1,event_date_jst:'2026-11-07',cutoff_at:p.cutoff_at,scope:'research',offering_status:'TRIFECTA_OFFERED',source_provenance:'UI_TEST_ONLY_INVENTED_RACE_AND_FORECAST',source_sha256:'a'.repeat(64),prediction:p,comparison_predictions:[later],result:null,missing_reasons:['NO_SAVED_RESULT_OBSERVATION','PRIVATE_CYCLE_RESEARCH_VIEW_ONLY'],participants:Array.from({length:6},(_,i)=>({number:i+1,registration_no:String(4001+i),name:'架空選手'+(i+1)}))};
const second={...r,race_id:'20261107-11-02',race_no:2,prediction:{...p,rationale:'架空の2Rの予想根拠。'},comparison_predictions:[]};
const pack=row=>({schema:'RACE_AI_FORECAST_AUDIT_V1',dataset_status:'REAL_REPORTED',records:[row,second]});
require('../web/product-data.js').parse(pack(r));
let browser,server;
(async()=>{
 fs.mkdirSync(folder,{recursive:true});server=http.createServer((req,res)=>{const name=new URL(req.url,'http://local').pathname,file=path.resolve(root,'.'+(name==='/'?'/index.html':name));if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.statusCode=404;return res.end();}res.setHeader('Content-Type',{'.js':'text/javascript','.css':'text/css','.json':'application/json','.html':'text/html','.webp':'image/webp'}[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 for(const width of [320,390,1440]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(7000);await page.goto('http://127.0.0.1:'+server.address().port+'/');
  const load=async row=>{await page.locator('#selected-date').fill('2026-11-07');await page.locator('#selected-date').dispatchEvent('change');await page.locator('#race-file').setInputFiles({name:'invented-UI-check.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(pack(row)))});await page.locator('[data-page="races"]').filter({visible:true}).first().click();await page.locator('[data-race-view="results"]').click();await page.locator('#page-races [data-open-race]').first().click();};
  await load(r);const detail=page.locator('#race-detail'),text=await detail.innerText();
  assert.doesNotMatch(text,/boat-observed|UNTRAINED|NO_SAVED_RESULT|INDEPENDENT_RECEIPT|PRIVATE_CYCLE|予想SHA|研究\s*\/\s*監査|SAVED FORECAST/,'ordinary detail must put audit internals in research');
  const summary=detail.locator('.race-result-summary');assert.equal(await summary.isVisible(),true);assert.match(await summary.innerText(),/結果待ち/);
  const box=await detail.boundingBox(),resultBox=await summary.boundingBox();if(resultBox.y-box.y>=230){await page.screenshot({path:path.join(folder,'position-'+width+'.png'),fullPage:true});console.log(JSON.stringify({width,detail:box,result:resultBox}));}assert.ok(resultBox.y-box.y<230,'the result must be near the race heading');
  assert.ok((await page.locator('#prediction-select').innerText()).length<100);assert.equal(await detail.locator('.forecast-panel').count(),1);
  assert.equal(await detail.locator('.race-audit-details').count(),0,'verification details must leave the race screen');
  assert.equal(await detail.locator('.forecast-rationale').innerText(),p.rationale);assert.equal(await detail.getByRole('heading',{name:'予想根拠',exact:true}).isVisible(),true);
  for(const tab of ['analysis','history']){await page.locator('[data-detail-tab="'+tab+'"]').click();assert.doesNotMatch(await detail.innerText(),/boat-observed|UNTRAINED|NO_SAVED_RESULT|INDEPENDENT_RECEIPT|予想SHA/);}
  await page.locator('[data-page="research"]').filter({visible:true}).first().click();const research=page.locator('#research-race-audit');
  assert.equal(await research.isVisible(),true);assert.match(await research.innerText(),/びわこ 1R/);assert.match(await research.innerText(),/boat-observed|UNTRAINED/);assert.match(await research.innerText(),/NO_SAVED_RESULT_OBSERVATION/);assert.match(await research.innerText(),/予想SHA/);
  assert.equal(await research.locator('.race-audit-details').evaluate(n=>n.tagName),'SECTION');
  await page.locator('#research-prediction-select').selectOption('1');assert.match(await research.innerText(),/SOURCE_SHA_NOT_SAVED/);assert.ok((await research.innerText()).includes('e'.repeat(64)));
  await research.locator('[data-return-to-race]').click();assert.equal(await page.locator('#prediction-select').inputValue(),'1');assert.equal(await detail.locator('.forecast-rationale').innerText(),later.rationale);
  await page.locator('[data-page="research"]').filter({visible:true}).first().click();await page.locator('#research-race-select').selectOption(second.race_id);assert.match(await research.innerText(),/びわこ 2R/);
  await research.locator('[data-return-to-race]').click();assert.match(await detail.locator('.detail-title').innerText(),/びわこ 2R/);assert.equal(await detail.locator('.forecast-rationale').innerText(),second.prediction.rationale);

  await load({...r,result:{status:'final',winning_combinations:[[1,2,3]],payout_yen_per_100:1250,confirmed_at:'2026-11-07T10:40:00+09:00',observed_at:'2026-11-07T10:40:00+09:00',official:false,source_sha256:'c'.repeat(64)}});
  assert.match(await detail.locator('.race-result-summary').innerText(),/的中/);assert.match(await detail.locator('.race-result-summary').innerText(),/1,250/);
  await page.locator('[data-page="results"]').filter({visible:true}).first().click();
  if(width<640){assert.equal(await page.locator('#saved-results-table .result-mobile-card').count(),2);assert.match(await page.locator('#saved-results-table .result-mobile-card').first().innerText(),/的中/);}
  const results=await page.locator('#saved-results-table').boundingBox(),simulation=await page.locator('#simulation-title').boundingBox();assert.ok(results.y<simulation.y,'race outcomes must come before long budget comparisons');
  assert.doesNotMatch(await page.locator('#page-results').innerText(),/公式証拠がそろった対象|98%は未達|Hit@8_all/);
  await page.locator('[data-page="races"]').filter({visible:true}).first().click();await page.locator('[data-race-view="results"]').click();await page.locator('#page-races [data-open-race]').first().click();
  await load({...r,prediction:null,comparison_predictions:[],no_forecast_reason:'SOURCE_NOT_AUTHORIZED_FOR_TEST'});
  assert.doesNotMatch(await detail.innerText(),/SOURCE_NOT_AUTHORIZED_FOR_TEST/);assert.equal(await detail.locator('.forecast-rationale').count(),0);
  await page.locator('[data-page="research"]').filter({visible:true}).first().click();assert.match(await research.innerText(),/SOURCE_NOT_AUTHORIZED_FOR_TEST/);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);await page.screenshot({path:path.join(folder,'result-detail-'+width+'.png'),fullPage:true});await page.close();console.log('PASS compact result detail '+width+'px: pending/hit, readable model, research-only audit, retained rationale, race/model continuity and one forecast');
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));});
