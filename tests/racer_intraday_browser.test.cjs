/* Invented same-day race/results. No actual forecasts, provider requests or keys. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http'),{createHash}=require('node:crypto');
const {chromium}=require('playwright'),{liveFixture}=require('./racer_daily_fixture.cjs');
const root=path.resolve(__dirname,'../web'),folder=process.env.UI_INTRADAY_EVIDENCE||path.resolve(__dirname,'../artifacts/racer-intraday-browser');fs.mkdirSync(folder,{recursive:true});
const entries=[['4320','峰竜太'],['3897','白井英治'],['3941','池田浩二'],['4238','毒島誠'],['3415','松井繁'],['4444','桐生順平']];
const race={race_id:'20261107-01-02',sport:'boat',scope:'research',venue:'桐生',race_no:2,event_date_jst:'2026-11-07',cutoff_at:'2026-11-07T12:00:00+09:00',offering_status:'TRIFECTA_OFFERED',source_provenance:'UI_TEST_ONLY_INVENTED_FIRST_RESULT_AND_SECOND_START',source_sha256:'a'.repeat(64),observed_at:'2026-11-07T10:50:00+09:00',prediction:null,result:null,no_forecast_reason:'同日2走の画面テスト用の架空レース・成績です。',participants:entries.map(([registration_no,name],i)=>({number:i+1,registration_no,name}))};
let server,browser,data=liveFixture(),dataRequests=0,checked='2026-11-07T02:00:00Z';
(async()=>{
 server=http.createServer((req,res)=>{
  const name=new URL(req.url,'http://localhost').pathname.replace(/^\/RACE-AI\//,'/');
  if(name==='/data/racer-daily.json'){dataRequests++;res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(data));}
  if(name==='/data/racer-live-status.json'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({schema:'RACE_AI_RACER_STATISTICS_STATUS_V1',catalogue_sha256:createHash('sha256').update(JSON.stringify(data)).digest('hex'),catalogue_generated_at:data.generated_at,checked_at:checked,state:'READY'}));}
  const file=path.resolve(root,'.'+(name==='/'?'/index.html':name));if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.statusCode=404;return res.end();}
  res.setHeader('Content-Type',{'.js':'text/javascript','.css':'text/css','.html':'text/html','.json':'application/json','.webp':'image/webp'}[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));
 });await new Promise(r=>server.listen(0,'127.0.0.1',r));
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 for(const width of [320,390,1440]){
  data=liveFixture();checked=data.generated_at;const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.clock.install({time:new Date('2026-11-07T02:05:00Z')});await page.goto('http://127.0.0.1:'+server.address().port+'/RACE-AI/');
  await page.waitForFunction(()=>RaceRacerDaily.status==='READY');
  const load=async record=>{await page.locator('#selected-date').fill(record.event_date_jst);await page.locator('#selected-date').dispatchEvent('change');await page.locator('#race-file').setInputFiles({name:'same-day-invented.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({schema:'RACE_AI_FORECAST_AUDIT_V1',dataset_status:'REAL_REPORTED',records:[record]}))});await page.locator('#page-home [data-open-participant="4320"]').waitFor();await page.locator('#page-home [data-open-participant="4320"]').click();};
  await load(race);const card=page.locator('#racer-daily-reference');
  assert.match(await card.innerText(),/レースごと/);assert.match(await card.innerText(),/過去90日.*当日/s);
  assert.match(await card.locator('.daily-today-results').innerText(),/桐生\s*1R.*1着.*2コース/s);
  await card.locator('[data-daily-course="2"]').click();assert.match(await card.locator('.daily-scenario').innerText(),/21走/);
  const before=dataRequests;checked='2026-11-07T02:05:00Z';await page.evaluate(()=>RaceRacerDaily.load({refresh:true}));assert.equal(dataRequests,before);
  await page.screenshot({path:path.join(folder,'same-day-'+width+'.png'),fullPage:true});await page.keyboard.press('Escape');
  await load({...race,race_id:'20261107-01-01',race_no:1,cutoff_at:'2026-11-07T10:00:00+09:00'});
  await card.locator('[data-daily-course="2"]').click();assert.match(await card.locator('.daily-scenario').innerText(),/締切以降/);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);await page.close();
  console.log('PASS intraday '+width+'px: first-result record, explicit course, later/earlier cutoff and small unchanged poll');
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));});
