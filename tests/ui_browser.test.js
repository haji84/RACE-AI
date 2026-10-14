/* Clearly synthetic test-only fixture, intercepted at the browser network boundary. */
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const assert=require('node:assert/strict');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const base=process.env.RACE_UI_TEST_URL||'http://127.0.0.1:8767';
const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const fixture={date_jst:today,first_observed_at:new Date().toISOString(),source_url:'https://example.test/synthetic-ui-test',source_sha256:'a'.repeat(64),redistribution_authorized:true,venues:[{venue:'16',races:[1,2].map((number)=>({race_id:today.replaceAll('-','')+'-16-0'+number,closed_at:number===1?'15:28':null,preview_available:number===1,boats:Array.from({length:6},(_,i)=>({lane:i+1,name:'検証専用 '+(i+1),racer_registration_id:String(4000+i),motor_no:i+1,average_st:i===0?0:null,display_time:i===0?6.8:null,preview_course:i+1}))}))},{venue:'18',races:[{race_id:today.replaceAll('-','')+'-18-01',closed_at:'14:00',boats:[{lane:1,racer_registration_id:'5000',motor_no:null}]}]}]};
(async()=>{
 let server;
 if(!process.env.RACE_UI_TEST_URL){server=http.createServer((req,res)=>{const file=path.join(__dirname,'../web',req.url==='/'?'index.html':req.url.split('?')[0]);try{const content=fs.readFileSync(file);res.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(content);}catch{res.statusCode=404;res.end('not found');}});await new Promise(resolve=>server.listen(8767,'127.0.0.1',resolve));}
 const launchOptions={headless:true,args:['--no-sandbox']};
 if(process.env.RACE_UI_CHROMIUM_PACKAGE){const bundled=(await import(process.env.RACE_UI_CHROMIUM_PACKAGE+'/build/index.js')).default;launchOptions.executablePath=await bundled.executablePath();launchOptions.args=bundled.args;}
 const browser=await chromium.launch(launchOptions);
 const context=await browser.newContext();
 for(const viewport of [{width:1440,height:1000},{width:390,height:844},{width:320,height:740}]){
  const page=await context.newPage();await page.setViewportSize(viewport);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/today',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(fixture)}));
  await page.goto(base);await page.getByText('児島 1R',{exact:true}).first().waitFor();
  assert.equal(await page.locator('#venue-filter option').count(),25);
  assert.equal(await page.locator('#venue-buttons button:disabled').count(),0);
  await page.evaluate(()=>document.querySelector('[data-page="races"]').click());
  await page.locator('#venue-filter').selectOption('01');assert.ok((await page.locator('#all-races').innerText()).includes('桐生のデータは未取得'));await page.locator('#clear-filters').click();
  assert.deepEqual(await page.locator('#max-picks option').allTextContents(),['8','16','24','32']);
  await page.evaluate(()=>document.querySelector('[data-page="home"]').click());
  assert.equal(await page.locator('#home-metrics').innerText().then(t=>t.includes('未集計')),true);
  await page.locator('.race-card').first().getByRole('button',{name:'レース詳細を見る →'}).click();
  await page.getByRole('button',{name:'直前情報',exact:true}).click();assert.ok((await page.locator('#race-detail').innerText()).includes('未取得'));
  await page.getByRole('button',{name:'モーター',exact:true}).click();
  await page.getByRole('button',{name:'水面・気象',exact:true}).click();
  await page.getByRole('button',{name:'AI予想・買い目',exact:true}).click();
  await page.getByRole('button',{name:'手入力の買い目を管理 →',exact:true}).click();
  await page.locator('#lane-second').selectOption('1');await page.locator('#ticket-form button').click();assert.ok((await page.locator('#ticket-message').innerText()).includes('異なる'));
  await page.locator('#lane-second').selectOption('3');await page.locator('#lane-third').selectOption('2');await page.locator('#ticket-amount').fill('700');await page.locator('#ticket-form button').click();
  assert.equal(await page.locator('.ticket-row').count(),1);
  assert.equal(await page.locator('#home-metrics .metric').nth(1).locator('strong').textContent(),'0円');
  await page.locator('#equal-allocate').click();assert.ok((await page.locator('#ticket-list').innerText()).includes('2,000円'));
  await page.locator('#record-purchase').click();assert.equal(await page.locator('.ticket-row').count(),0);
  await page.locator('#max-picks').selectOption('16');
  const combinations=[];for(let a=1;a<=6;a++)for(let b=1;b<=6;b++)for(let c=1;c<=6;c++)if(new Set([a,b,c]).size===3)combinations.push([a,b,c]);
  for(const lanes of combinations.slice(0,16)){await page.locator('#lane-first').selectOption(String(lanes[0]));await page.locator('#lane-second').selectOption(String(lanes[1]));await page.locator('#lane-third').selectOption(String(lanes[2]));await page.locator('#ticket-amount').fill('100');await page.locator('#ticket-form button').click();}
  assert.equal(await page.locator('.ticket-row').count(),16);await page.locator('#max-picks').selectOption('8');
  assert.equal(await page.locator('#record-purchase').isDisabled(),true,'lowered point limit must block recording');
  await page.locator('#record-purchase').dispatchEvent('click');assert.equal(await page.locator('.ticket-row').count(),16,'over-limit candidates remain editable, unrecorded');
  for(let i=0;i<16;i++)await page.locator('.ticket-row').first().getByRole('button',{name:'削除'}).click();

  await page.evaluate(()=>document.querySelector('[data-page="results"]').click());
  await page.locator('.settle-form input').fill('5000');await page.locator('.settle-form button').click();assert.ok((await page.locator('#result-metrics').innerText()).includes('250.0%'));
  await page.evaluate(()=>document.querySelector('[data-page="settings"]').click());await page.locator('#daily-budget').fill('15000');await page.locator('#settings-mode').selectOption('return');await page.locator('#settings-form button').click();assert.ok((await page.locator('#settings-message').innerText()).includes('反映'));
  await page.evaluate(()=>document.querySelector('[data-page="races"]').click());await page.locator('#race-search').fill('徳山');assert.equal(await page.locator('#all-races .race-card').count(),1);assert.ok((await page.locator('#all-races').innerText()).includes('未取得'));
  await page.locator('#clear-filters').click();await page.locator('#complete-filter').check();assert.equal(await page.locator('#all-races .race-card').count(),2);
  for(const name of ['home','races','detail','picks','results','research','settings']){
   await page.evaluate(name=>document.querySelector('[data-page="'+name+'"]')?.click(),name);if(name==='detail')await page.locator('#all-races .race-card').first().getByRole('button').click();
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'no document overflow '+viewport.width+' '+name);
   if(viewport.width!==320)await page.screenshot({path:'/tmp/race-ui-'+viewport.width+'-'+name+'.png',fullPage:true});
  }
  assert.deepEqual(errors,[]);await page.close();
 }
 const page=await context.newPage();await page.route('**/api/today',route=>route.fulfill({status:503,contentType:'application/json',body:'{}'}));await page.goto(base);await page.locator('#source-state').getByText('データ未取得',{exact:true}).waitFor();assert.ok((await page.locator('#home-races').innerText()).includes('待っています'));
 for(const [label,bad] of [['stale',{...fixture,date_jst:'2026-01-01'}],['unauthorized',{...fixture,redistribution_authorized:false}],['future',{...fixture,first_observed_at:new Date(Date.now()+3600000).toISOString()}],['badHash',{...fixture,source_sha256:'fake'}]]){await page.unroute('**/api/today');await page.route('**/api/today',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(bad)}));await page.reload();await page.locator('#source-state').getByText('データ未取得',{exact:true}).waitFor();assert.equal(await page.locator('#home-races .race-card').count(),0,label);}
 await page.locator('#race-file').setInputFiles({name:'stale.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({...fixture,date_jst:'2026-01-01',venues:fixture.venues.map(v=>({...v,races:v.races.map(r=>({...r,race_id:'20260101'+r.race_id.slice(8)}))}))}))});
 await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('対象日が本日ではありません'));
 assert.equal(await page.locator('#home-races .race-card').count(),0,'manual stale input must not become today');
 await page.unroute('**/api/today');await page.route('**/api/today',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(fixture)}));
 await page.evaluate(()=>{const read=File.prototype.text;File.prototype.text=function(){return new Promise(resolve=>setTimeout(()=>resolve(read.call(this)),200));};});
 await page.locator('#race-file').setInputFiles({name:'old-invalid.json',mimeType:'application/json',buffer:Buffer.from('{}')});
 await page.locator('#reload-feed').click();await page.getByText('配信許可フラグあり・原本未独立検証',{exact:true}).waitFor();
 await page.waitForTimeout(300);assert.equal(await page.locator('#home-races .race-card').count(),3,'late file rejection cannot erase newer delivery');
 await page.locator('#home-races .race-card').first().getByRole('button').click();await page.getByRole('button',{name:'このレースの買い目を入力 →'}).click();await page.locator('#ticket-form button').click();assert.equal(await page.locator('.ticket-row').count(),1);
 await page.locator('#record-purchase').click();await page.locator('#ticket-form button').click();
 await page.clock.setFixedTime(new Date(Date.now()+24*60*60*1000));await page.locator('#record-purchase').click();
 assert.equal(await page.locator('#home-races .race-card').count(),0,'yesterday feed must be removed on rollover');assert.ok((await page.locator('#ticket-message').innerText()).includes('日付が変わり'));
 assert.equal(await page.locator('#home-metrics .metric').nth(1).locator('strong').textContent(),'0円','today budget excludes yesterday records');
 await page.evaluate(()=>document.querySelector('[data-page="results"]').click());assert.equal(await page.locator('#result-metrics .metric').first().locator('strong').textContent(),'100円','session results preserve yesterday records');
 const autoPage=await context.newPage();let requests=0;await autoPage.clock.install({time:new Date()});await autoPage.route('**/api/today',route=>{requests++;return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(fixture)});});await autoPage.goto(base);await autoPage.locator('#home-races .race-card').first().waitFor();assert.equal(requests,1);await autoPage.clock.runFor(60_001);await autoPage.waitForFunction(()=>document.querySelector('#source-state').textContent.includes('配信許可'));assert.equal(requests,2,'visible interval refreshes same-origin feed');
 await autoPage.evaluate(()=>Object.defineProperty(document,'visibilityState',{value:'hidden',configurable:true}));await autoPage.clock.runFor(60_001);assert.equal(requests,2,'hidden page skips periodic requests');
 await autoPage.evaluate(()=>{Object.defineProperty(document,'visibilityState',{value:'visible',configurable:true});document.dispatchEvent(new Event('visibilitychange'));});await autoPage.waitForFunction(()=>document.querySelector('#source-state').textContent.includes('配信許可'));assert.equal(requests,3,'returning visible refreshes feed');

 await browser.close();if(server)await new Promise(resolve=>server.close(resolve));console.log('Browser flows passed: desktop 1440, phones 390/320, feed refusal guards');
})().catch(e=>{console.error(e);process.exit(1)});
