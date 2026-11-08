'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
const web=path.resolve(__dirname,'../web');
const top=[[1,2,3],[1,3,2],[1,2,4],[1,4,2],[2,1,3],[2,3,1],[3,1,2],[3,2,1]];
const p={model_id:'boat-observed-pairwise-factor-v1',model_version:'fixture-v1',stage:'P0',ordered_top8:top,
 prediction_sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),source_sha256:'c'.repeat(64),
 as_of:'2030-04-01T09:00:00+09:00',generated_at:'2030-04-01T09:00:01+09:00',persisted_at:'2030-04-01T09:01:00+09:00',
 cutoff_at:'2030-04-01T10:00:00+09:00',odds_independent:true};
const fixture={schema:'RACE_AI_PRIVATE_CYCLE_VIEW_V1',dataset_status:'SYNTHETIC_ONLY',event_date_jst:'2030-04-01',records:[{
 race_id:'20300401-01-01',sport:'boat',venue:'場コード01',race_no:1,event_date_jst:'2030-04-01',offering_status:'UNKNOWN',cutoff_at:p.cutoff_at,
 participants:[1,2,3,4].map(number=>({number,registration_no:String(4000+number),name:'架空選手'+number})),
 prediction:p,comparison_predictions:[{...p,stage:'P1',prediction_sha256:'d'.repeat(64),ordered_top8:[[2,1,3],[2,3,1]],rationale:'保存した理由：2号艇を先頭に置く別案。'}],
 result:null,result_observations:[],result_observation_rejections:[],result_revisions:[]} ]};
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 try{
  for(const width of [320,390,1440]){
   const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.setDefaultTimeout(8000);page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/*',async route=>{
    const url=new URL(route.request().url());assert.equal(url.origin,'https://forecast-explanation.test');
    const file=path.resolve(web,url.pathname==='/'?'index.html':url.pathname.slice(1));
    if(!file.startsWith(web+path.sep)||!fs.existsSync(file))return route.fulfill({status:404,body:''});
    return route.fulfill({contentType:{'.js':'text/javascript','.css':'text/css','.html':'text/html'}[path.extname(file)],body:fs.readFileSync(file)});
   });
   await page.clock.install({time:new Date('2030-04-01T00:30:00Z')});await page.goto('https://forecast-explanation.test/');
   await page.locator('#race-file').setInputFiles({name:'invented-explanation.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture))});
   await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('端末内で読み込みました'));
   await page.locator('#page-home [data-open-race]').first().click();
   assert.equal(await page.getByRole('heading',{name:'予想根拠',exact:true}).count(),1,'rationale must be visible even when the original did not contain a prose field');
   assert.equal(await page.getByRole('heading',{name:'展開予想',exact:true}).count(),1);
   assert.match(await page.locator('#forecast-rationale').innerText(),/比較.*8点/s);
   assert.match(await page.locator('#forecast-outlook').innerText(),/1号艇.*2号艇.*3号艇/s);
   assert.match(await page.locator('#forecast-alternative').innerText(),/2号艇.*1号艇.*3号艇/s);
   assert.match(await page.locator('#forecast-outlook-basis').innerText(),/保存買い目/);
   await page.locator('#prediction-select').selectOption('1');
   assert.equal(await page.locator('#forecast-rationale').innerText(),'保存した理由：2号艇を先頭に置く別案。');
   assert.match(await page.locator('#forecast-outlook').innerText(),/2号艇.*1号艇.*3号艇/s);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   assert.deepEqual(errors,[]);await page.close();
   console.log('PASS rationale and saved-ticket outlook '+width+'px: source prose preserved, main/alternative, model switching, no overflow');
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
