/* Invented model originals only; no live sources or owner data. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http'),{chromium}=require('playwright');
const M=require('../web/product-data.js'),root=path.resolve(__dirname,'../web'),artifacts=process.env.UI_MODEL_EVIDENCE || path.resolve(__dirname,'../artifacts/ui-browser/model-switcher');
const LiveCheck=require('../scripts/boat_saved_site_check.cjs');
const A='boat-observed-pairwise-factor-v1',B='boat-observed-pairwise-start-v1';
const a=[[1,2,3],[1,3,2],[1,2,4],[1,4,2],[1,2,5],[1,5,2],[1,2,6],[1,6,2]],b=[[2,1,3],[2,3,1],[2,1,4],[2,4,1],[2,1,5],[2,5,1],[2,1,6],[2,6,1]];
function fixture(){
 const p={model_id:A,model_version:'1',stage:'P0',generated_at:'2030-01-01T07:00:00+09:00',as_of:'2030-01-01T07:00:00+09:00',persisted_at:'2030-01-01T07:01:00+09:00',cutoff_at:'2030-01-01T09:00:00+09:00',ordered_top8:a,prediction_sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),odds_independent:true,rationale:'A 朝の保存根拠'};
 const peer={...p,model_id:B,stage:'P1',ordered_top8:b,prediction_sha256:'c'.repeat(64),rationale:'B の保存根拠'};
 const later={...p,stage:'P1',as_of:'2030-01-01T08:00:00+09:00',generated_at:'2030-01-01T08:00:00+09:00',persisted_at:'2030-01-01T08:01:00+09:00',prediction_sha256:'d'.repeat(64),ordered_top8:[a[1],a[0],...a.slice(2)],rationale:'A 展示後の保存根拠'};
 const legacy={...p,model_id:undefined,model_version:'legacy',prediction_sha256:'9'.repeat(64),ordered_top8:[[3,2,1],...b.slice(1)],rationale:'モデル名未記録の保存根拠'};
 const r={race_id:'20300101-11-01',sport:'boat',venue:'びわこ',race_no:1,event_date_jst:'2030-01-01',cutoff_at:p.cutoff_at,scope:'research',offering_status:'TRIFECTA_OFFERED',source_provenance:'INVENTED_MODEL_SWITCH_TEST_ONLY',source_sha256:'e'.repeat(64),prediction:p,comparison_predictions:[peer,later,legacy,{...p,model_id:'seller-shadow-v1-20261104',prediction_sha256:'f'.repeat(64)}],result:{status:'final',winning_combinations:[[1,2,3]],payout_yen_per_100:1200,observed_at:'2030-01-01T09:05:00+09:00'},participants:Array.from({length:6},(_,i)=>({number:i+1,registration_no:String(4001+i),name:'架空選手'+(i+1)}))};
 return {schema:'RACE_AI_FORECAST_AUDIT_V1',dataset_status:'REAL_REPORTED',records:[r,{...r,race_id:'20300101-11-02',race_no:2,comparison_predictions:[]}]};
}
let browser,server;
(async()=>{
 const data=fixture();M.parse(data);const original=JSON.stringify(data);fs.mkdirSync(artifacts,{recursive:true});
 server=http.createServer((req,res)=>{const name=new URL(req.url,'http://local').pathname,file=path.resolve(root,'.'+(name==='/'?'/index.html':name));if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.statusCode=404;return res.end();}res.setHeader('Content-Type',{'.js':'text/javascript','.css':'text/css','.json':'application/json','.html':'text/html','.webp':'image/webp'}[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',args:['--no-sandbox']});
 for(const width of [320,390,1440]){
  const page=await browser.newPage({viewport:{width,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.name));page.setDefaultTimeout(7000);
  await page.clock.install({time:new Date('2030-01-01T01:00:00Z')});await page.goto('http://127.0.0.1:'+server.address().port+'/');
  await page.locator('#race-file').setInputFiles({name:'invented-models.json',mimeType:'application/json',buffer:Buffer.from(original)});
  await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('端末内で読み込みました'));
  const list=async()=>{await page.locator('[data-page="races"]').filter({visible:true}).first().click();await page.locator('[data-race-view="results"]').click();};
  const open=async rid=>{await page.locator('#page-races [data-open-race="'+rid+'"]').click();};
  await list();await page.locator('#race-model-select').selectOption(B);
  const filters=page.locator('#page-races details').filter({has:page.locator('#prediction-filter')});await filters.locator(':scope > summary').click();
  await page.locator('#prediction-filter').check();assert.equal(await page.locator('#page-races [data-open-race="20300101-11-02"]').count(),0);await page.locator('#prediction-filter').uncheck();
  await filters.locator(':scope > summary').click();
  await open('20300101-11-01');
  const panel=page.locator('#detail-tab-content .forecast-panel');
  assert.equal(await page.locator('#detail-model-select').inputValue(),B);assert.equal(await panel.getAttribute('data-model-id'),B);
  assert.deepEqual(await panel.locator('.saved-ticket .combo').first().locator('.lane').allTextContents(),['2','1','3']);assert.match(await panel.innerText(),/B の保存根拠/);
  assert.deepEqual(await panel.locator('.forecast-rationale-heading').allTextContents(),['予想根拠','展開予想']);await LiveCheck.assertRationaleHeading(page);
  await page.locator('#prediction-select').selectOption('2');assert.equal(await page.locator('#detail-model-select').inputValue(),A);assert.match(await panel.innerText(),/A 展示後の保存根拠/);
  await page.locator('#detail-model-select').selectOption(B);await page.locator('#detail-model-select').selectOption(A);assert.equal(await page.locator('#prediction-select').inputValue(),'2');
  await page.locator('[data-page="research"]').filter({visible:true}).first().click();assert.equal(await page.locator('#research-model-select').inputValue(),A);assert.equal(await page.locator('#research-prediction-select').inputValue(),'2');
  await page.locator('[data-return-to-race]').click();await page.locator('#detail-model-select').selectOption(B);await list();await open('20300101-11-02');
  assert.equal(await page.locator('#detail-model-select').inputValue(),B);assert.equal(await panel.locator('.saved-ticket').count(),0);assert.match(await panel.innerText(),/このモデル.*保存/);assert.equal(await page.locator('#prediction-select').inputValue(),'');
  await page.locator('#detail-model-select').selectOption(A);await list();await open('20300101-11-01');assert.equal(await page.locator('#prediction-select').inputValue(),'2');
  assert.equal(await page.locator('#detail-model-select option[value="seller-shadow-v1-20261104"]').count(),0);
  await page.locator('#prediction-select').selectOption('3');assert.equal(await page.locator('#prediction-select').inputValue(),'3');assert.match(await panel.innerText(),/モデル名未記録の保存根拠/);
  assert.deepEqual(await panel.locator('.saved-ticket .combo').first().locator('.lane').allTextContents(),['3','2','1']);
  await page.locator('#detail-model-select').selectOption(A);assert.equal(await page.locator('#prediction-select').inputValue(),'2');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);
  await page.screenshot({path:path.join(artifacts,'model-switcher-'+width+'.png'),fullPage:true});await page.close();
  console.log('PASS model selection '+width+'px: tickets/rationale, missing model, history, race/research continuity and retired model exclusion');
 }
 assert.equal(JSON.stringify(data),original);
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));});
