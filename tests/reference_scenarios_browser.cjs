/* Public invented UI scenarios, assembled from the existing UI/lifecycle/preview
 * fixtures. No real roster, portrait, calibrated score, key or source request. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'../web');
const original=fs.readFileSync(path.join(root,'data/example-synthetic-forecast-audit.json'));
assert.equal(crypto.createHash('sha256').update(original).digest('hex'),'b49654f4cbf5527131b38971e3504a52d5d9431ff62aa1c2dde4bc9bf96da00a');
function fixture(){
 const view=JSON.parse(original);
 view.records.forEach((row,index)=>{
  row.event_date_jst='2030-01-01';row.scope='synthetic';row.result=null;row.result_revisions=[];
  row.participants=Array.from({length:[6,7,8,12][index]},(_,n)=>({number:n+1,name:`架空${n+1}`}));
  if(row.prediction)row.prediction.stage='P0';
  for(const p of row.comparison_predictions||[])p.stage='P1';
 });
 const boat=view.records[0];
 boat.venue='合成場';
 boat.participants.forEach((person,index)=>Object.assign(person,{motor_no:10+index,average_st:index===0?0:.15,preview_course:index+1}));
 Object.assign(boat.participants[0],{display_time:6.71,preview_st:'F.01',comment:'合成テスト専用の直前コメントです。'});
 boat.participants[1].preview_st=0;
 boat.weather={weather_label:'晴',air_temperature_c:12,wind_speed_mps:0,wave_height_cm:0,water_temperature_c:15};
 view.records.push({...structuredClone(boat),race_id:'synthetic:2030-01-01:boat:2',venue:'A合成テスト会場',race_no:2,cutoff_at:'2030-01-01T11:00:00+09:00',prediction:null,comparison_predictions:[],participants:[],no_forecast_reason:'合成テスト専用：保存予想・出走表は未取得です。'});
 return view;
}
async function shortMobileReview({browser,base}){
 const results=[],origin=new URL(base).origin;
 for(const [width,height]of [[640,360],[640,390],[760,390],[390,320],[320,568]]){
  const context=await browser.newContext({viewport:{width,height},hasTouch:true}),page=await context.newPage();
  try{
   await context.route('**/*',r=>new URL(r.request().url()).origin===origin?r.continue():r.abort());
   await page.clock.install({time:new Date('2030-01-01T00:30:00Z')});await page.goto(base);
   await page.locator('#race-file').setInputFiles({name:'public-short-viewport.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture()))});
   await page.waitForFunction(()=>document.querySelector('#source-state').textContent.includes('合成'));
   await page.locator('#selected-date').fill('2030-01-01');await page.locator('#selected-date').dispatchEvent('change');
   await page.locator('[data-page="picks"]').filter({visible:true}).first().click();await page.locator('#copy-top8').click();await page.locator('#equal-allocate').click();
   const fragment=new URL(page.url()).hash,candidates=await page.locator('#ticket-list').innerText();
   await page.locator('#review-allocation').click();
   const confirm=await page.locator('#confirm-candidates').boundingBox(),nav=await page.locator('.bottom-nav').boundingBox();
   const hit=await page.evaluate(({x,y})=>{const n=document.elementFromPoint(x,y);return {confirm:!!n?.closest('#confirm-candidates'),navigation:!!n?.closest('.bottom-nav')};},{x:confirm.x+confirm.width/2,y:confirm.y+confirm.height/2});
   // A raw coordinate click must succeed; locator.click() could scroll again
   // and hide the original navigation-overlap defect from the test.
   await page.mouse.click(confirm.x+confirm.width/2,confirm.y+confirm.height/2);
   assert.match(await page.locator('#confirmation-state').innerText(),/候補確定済み/,`${width}x${height} review must expose a clickable confirmation: ${JSON.stringify({confirm,nav,hit})}`);
   assert.ok(hit.confirm&&!hit.navigation&&confirm.y>=0&&confirm.y+confirm.height<=nav.y-8,'the entire confirmation target clears fixed navigation');
   assert.equal(new URL(page.url()).hash,fragment);assert.equal(await page.locator('#ticket-list').innerText(),candidates);assert.equal(await page.locator('#record-purchase').isDisabled(),true);
   results.push({width,height,confirm,nav_top:nav.y,coordinate_click_confirmed:true,fragment_and_candidates_preserved:true});
  }finally{await context.close();}
 }
 return results;
}
async function check({browser,base,output}){
 const view=fixture(),raw=Buffer.from(JSON.stringify(view)),before=JSON.stringify(view),origin=new URL(base).origin;
 const parsed=require('../web/product-data.js').parse(view);assert.ok(parsed.records.every(row=>row.scope==='synthetic'));
 const report={scope:'SYNTHETIC_ONLY',fixture_sha256:crypto.createHash('sha256').update(raw).digest('hex'),fixture_records:5,source_fixture_sha256:crypto.createHash('sha256').update(original).digest('hex'),asset_sha256:Object.fromEntries(['index.html','app.js','style.css'].map(name=>[name,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,name))).digest('hex')])),browser:'Chromium',platform:process.platform,browser_version:browser.version(),physical_iphone_verified:false,native_safari_verified:false,account_login_verified:false,widths:[],screenshots:[],external_requests:0};
 report.short_mobile_review=await shortMobileReview({browser,base});
 fs.mkdirSync(output,{recursive:true});
 for(const width of [320,390,1440,1920]){
  const height=width<600?844:1000,context=await browser.newContext({viewport:{width,height},hasTouch:width<600}),page=await context.newPage(),errors=[],requests=[];
  try{
   await context.route('**/*',route=>{if(new URL(route.request().url()).origin!==origin){report.external_requests++;return route.abort();}return route.continue();});
   page.on('pageerror',e=>errors.push(e.name));page.on('request',r=>requests.push(r.url()));page.setDefaultTimeout(7000);
   await page.clock.install({time:new Date('2030-01-01T00:30:00Z')});await page.goto(base);
   assert.deepEqual(await page.evaluate(()=>({width:innerWidth,height:innerHeight})),{width,height});
   await page.locator('#race-file').setInputFiles({name:'public-reference-scenarios.json',mimeType:'application/json',buffer:raw});
   await page.waitForFunction(()=>document.querySelector('#source-state').textContent.includes('合成'));
   await page.locator('#selected-date').fill('2030-01-01');await page.locator('#selected-date').dispatchEvent('change');
   const nav=async name=>page.locator('[data-page="'+name+'"]').filter({visible:true}).first().click();
   const capture=async(name,{viewport=false,keepScroll=false}={})=>{
    assert.match(await page.locator('#source-state').textContent(),/合成/);
    assert.match(await page.locator('#data-banner').textContent(),/架空.*実績には含みません/);
    assert.equal(await page.locator('img:visible').count(),0,'invented participants must not acquire real portraits');
    assert.equal(await page.locator('meta[name="race-ai-encrypted-saved-view"]').count(),0);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);assert.ok(requests.every(url=>new URL(url).origin===origin));
    if(!keepScroll)await page.evaluate(()=>scrollTo({top:0,left:0,behavior:'instant'}));
    if(!keepScroll)assert.equal(await page.locator('#data-banner').evaluate(e=>{const r=e.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return r.y>=0&&r.bottom<=innerHeight&&(hit===e||e.contains(hit));}),true,'the synthetic warning stays visible and unobscured');
    const nameOnDisk=`rich-${width}-${name}.png`,rawPng=await page.screenshot({path:path.join(output,nameOnDisk),fullPage:!viewport});
    report.screenshots.push({name:nameOnDisk,bytes:rawPng.length,sha256:crypto.createHash('sha256').update(rawPng).digest('hex')});
   };
   const geometry={width,height,sports:[]};
   for(const [index,sport]of ['boat','keirin','autorace','horse'].entries()){
    await page.locator('[data-sport="'+sport+'"]').click();await nav('races');
    assert.equal(await page.locator('[data-race-view="upcoming"]').getAttribute('aria-selected'),'true');
    assert.equal(await page.locator('#all-races .race-card').count(),sport==='boat'?2:1);
    const card=page.locator('#all-races [data-race-id="'+view.records[index].race_id+'"]');
    assert.equal(await card.locator('.racer-card').count(),[6,7,8,12][index]);
    geometry.sports.push({sport,entrants:[6,7,8,12][index],upcoming:sport==='boat'?2:1});
    if(sport==='boat'){
     geometry.boat_upcoming_card_height_px=Math.round((await card.boundingBox()).height);
     const maximum=width<600?280:220;
     assert.ok(geometry.boat_upcoming_card_height_px<=maximum,`${width}px normal six-person list cards must be at most ${maximum}px tall; actual ${geometry.boat_upcoming_card_height_px}px`);
     const primary=await card.locator('[data-open-race]').boundingBox();assert.ok(primary.width>=44&&primary.height>=44,'the compact card keeps a meaningful detail target');
     const identityBoxes=await card.locator('.racer-identity').evaluateAll(nodes=>nodes.map(e=>{const r=e.getBoundingClientRect();return {width:r.width,height:r.height};}));
     assert.ok(identityBoxes.every(r=>r.width>=44&&r.height>=44),`${width}px each participant identity stays a 44px touch target: ${JSON.stringify(identityBoxes)}`);
     if(width===320){
      await page.evaluate(()=>document.documentElement.style.scrollbarGutter='stable');
      const gutterTargets=await card.locator('.racer-identity').evaluateAll(nodes=>nodes.map(e=>({width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height})));
      assert.ok(gutterTargets.every(r=>r.width>=44&&r.height>=44),'participant targets remain usable with the native scrollbar gutter');
      assert.ok((await card.boundingBox()).height<=280);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.evaluate(()=>document.documentElement.style.removeProperty('scrollbar-gutter'));
     }
     assert.equal(await card.locator('.race-list-more').evaluate(e=>e.open),false,'secondary information is reachable without expanding every card');
     assert.equal(await card.locator('.race-card-footer .saved-ticket').count(),1,'the compact preview retains one original ticket and the full count');
     if(width<600){
      const tops=await card.locator('.racer-card').evaluateAll(nodes=>nodes.map(e=>e.getBoundingClientRect().top));
      assert.ok(tops.every(top=>Math.abs(top-tops[0])<1),`${width}px a six-person upcoming card must use one compact participant row: ${JSON.stringify(tops)}`);
      const avatarBounds=await card.locator('.racer-card').evaluateAll(nodes=>nodes.map(e=>{const cell=e.getBoundingClientRect(),avatar=e.querySelector('.avatar-silhouette').getBoundingClientRect();return {left:cell.left,right:cell.right,avatar_left:avatar.left,avatar_right:avatar.right};}));
      assert.ok(avatarBounds.every(b=>b.avatar_left>=b.left&&b.avatar_right<=b.right),`${width}px each neutral participant avatar fits its own compact cell: ${JSON.stringify(avatarBounds)}`);
     }else{
      assert.equal(await card.evaluate(e=>getComputedStyle(e).display),'grid');
      const head=await card.locator('.race-card-head').boundingBox(),people=await card.locator('.racer-grid').boundingBox(),tickets=await card.locator('.race-card-footer').boundingBox();
      assert.ok(head.x<people.x&&people.x<tickets.x,'desktop upcoming cards use information/participants/tickets columns');
     }
    }
    if([390,1440].includes(width)&&sport!=='boat')await capture(sport+'-upcoming');
   }
   await page.locator('[data-sport="boat"]').click();await nav('races');
   const card=()=>page.locator('#all-races [data-race-id="'+view.records[0].race_id+'"]');
   await card().locator('.race-list-more>summary').click();
   assert.match(await card().locator('.race-tags').innerText(),/合成テスト.*P0 朝版.*レース前/s,'the compact disclosure preserves the full source, stage and outcome states');
   const actionKeys=await card().locator('[data-race-tab]').evaluateAll(nodes=>nodes.map(e=>e.dataset.raceTab));assert.equal(actionKeys.length,4);
   for(const key of actionKeys){
    const more=card().locator('.race-list-more');if(!await more.evaluate(e=>e.open))await more.locator(':scope>summary').click();
    const action=card().locator('[data-race-tab="'+key+'"]');await action.evaluate(e=>e.scrollIntoView({block:'center'}));const box=await action.boundingBox();assert.ok(box.width>=44&&box.height>=44,'every retained information action remains a usable target');
    await action.click();assert.equal(await page.locator('[data-detail-tab="'+key+'"]').getAttribute('aria-selected'),'true');await page.locator('#page-detail .back-button').click();
   }
   const missing=page.locator('#all-races [data-race-id="'+view.records[4].race_id+'"]');await missing.locator('.race-list-more>summary').click();assert.match(await missing.innerText(),/保存予想・出走表は未取得/);await missing.locator('.race-list-more>summary').click();
   await card().locator('.race-list-more>summary').click();await card().locator('[data-race-tab="participants"]').focus();
   await page.clock.fastForward(60001);
   assert.equal(await card().locator('.race-list-more').evaluate(e=>e.open),true,'an unchanged-row minute refresh preserves the open information disclosure');
   assert.equal(await page.evaluate(()=>document.activeElement.dataset.raceTab),'participants','an unchanged-row refresh preserves the focused information action');
   await page.clock.fastForward(29*60000);
   assert.equal(await card().count(),0,'a race that has closed leaves the upcoming view');
   assert.equal(await page.locator('#all-races .race-list-more[open]').count(),0,'removed disclosure state must not transfer to another race');
   geometry.minute_refresh_state_preserved=true;geometry.closed_phase_row_not_restored=true;
   await page.clock.setFixedTime(new Date('2030-01-01T00:30:00Z'));await nav('races');
   await page.locator('#race-search').fill('架空6');assert.equal(await page.locator('#all-races .race-card').count(),1);await page.locator('#race-search').fill('');
   await page.locator('#race-filters>summary').click();await page.locator('#prediction-filter').check();assert.equal(await page.locator('#all-races .race-card').count(),1);await page.locator('#prediction-filter').uncheck();
   await page.locator('#race-sort').selectOption('venue');assert.equal(await page.locator('#all-races .race-card').first().getAttribute('data-race-id'),view.records[4].race_id);
   await page.locator('#race-sort').selectOption('time');assert.equal(await page.locator('#all-races .race-card').first().getAttribute('data-race-id'),view.records[0].race_id);await page.locator('#race-filters>summary').click();
   await capture('races');await nav('home');await capture('home');await nav('races');await page.locator('#all-races [data-open-race]').first().click();
   assert.equal(await page.locator('#detail-tab-content .forecast-panel .saved-ticket').count(),8);await capture('detail');
   await page.locator('[data-detail-tab="participants"]').click();assert.equal(await page.locator('#detail-tab-content .racer-card').count(),6);assert.match(await page.locator('#detail-tab-content').innerText(),/モーター.*10/s);await capture('participants');
   await page.locator('[data-detail-tab="preview"]').click();assert.equal(await page.locator('.preview-boat').count(),6);assert.match(await page.locator('.preview-boat').first().innerText(),/6\.71.*F\.01.*合成テスト専用/s);
   const weather=page.getByRole('region',{name:'保存された気象・水面'});assert.match(await weather.innerText(),/0 m\/s/);assert.match(await weather.innerText(),/0 cm/);await capture('preview');
   await nav('picks');await page.locator('#copy-top8').click();await page.locator('#equal-allocate').click();await page.evaluate(()=>scrollTo(0,0));
   assert.equal(await page.locator('.ticket-row').count(),8);geometry.summary_before_jump=await page.locator('.allocation-panel').boundingBox();
   if(width<600){
    const shortcut=page.locator('#review-allocation');assert.equal(await shortcut.count(),1,'mobile allocation needs a direct route to its total and confirmation, before the manual-entry form');
    assert.match(await shortcut.innerText(),/2,000円.*配分を確認/);const box=await shortcut.boundingBox(),bottom=await page.locator('.bottom-nav').boundingBox();assert.ok(box.y+box.height<bottom.y&&box.height>=44,'the allocation review route must be a visible touch target');geometry.summary_shortcut=box;
    await capture('picks');if(width===320)await shortcut.tap();else{await shortcut.focus();await page.keyboard.press('Enter');}
    const confirm=await page.locator('#confirm-candidates').boundingBox(),navBox=await page.locator('.bottom-nav').boundingBox();
    assert.ok(confirm.y>=0&&confirm.y+confirm.height<navBox.y,'jumping to the allocation summary leaves confirmation clear of the fixed navigation');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'allocation-review');
    assert.match(await page.locator('#allocation-summary').innerText(),/2,000円.*0円/s);
    assert.match(await page.locator('#confirmation-state').innerText(),/編集中/,'reviewing the total must not confirm candidates');
    geometry.confirm_after_jump=confirm;
    await capture('review',{viewport:true,keepScroll:true});
   }else await capture('picks');
   await page.locator('#confirm-candidates').click();assert.match(await page.locator('#confirmation-state').innerText(),/候補確定済み.*実購入ではありません/);assert.equal(await page.locator('#record-purchase').isDisabled(),true);
   if(width<600){await page.locator('.ticket-amount').first().fill('200');await page.locator('.ticket-amount').first().press('Tab');assert.match(await page.locator('#review-allocation').innerText(),/1,900円/);assert.match(await page.locator('#confirmation-state').innerText(),/編集中/);}
   assert.equal(JSON.stringify(view),before);assert.deepEqual(errors,[]);assert.equal(report.external_requests,0);report.widths.push(geometry);
   const verbose=structuredClone(view);verbose.records[0].venue='長い合成テスト会場'.repeat(6);verbose.records[0].participants[0].name='長い合成選手名'.repeat(12);
   await page.locator('#race-file').setInputFiles({name:'public-long-label-probe.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(verbose))});await nav('races');
   await page.waitForFunction(label=>document.querySelector('#all-races').textContent.includes(label),verbose.records[0].venue);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'long list labels remain inside the page');
   assert.equal(await card().locator('.race-title-button').textContent(),verbose.records[0].venue+' 1R');
   assert.equal(await card().locator('.racer-name').first().textContent(),verbose.records[0].participants[0].name);
   console.log('PASS richer reference coverage '+JSON.stringify({width,upcoming_sports:4,participant_counts:[6,7,8,12],boat_weather_motor_preview:true,mobile_summary_reachable:width<600}));
  }finally{await context.close();}
 }
 return report;
}
module.exports={fixture,check,shortMobileReview};
if(require.main===module){
 const http=require('node:http'),{chromium}=require('playwright');let browser,server;
 (async()=>{
  server=http.createServer((req,res)=>{const name=new URL(req.url,'http://local').pathname,file=path.resolve(root,'.'+(name==='/'?'/index.html':name));if(req.method!=='GET'||!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.statusCode=404;return res.end();}res.setHeader('Content-Type',{'.js':'text/javascript','.css':'text/css','.html':'text/html','.json':'application/json','.webp':'image/webp'}[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
  const output=path.resolve(process.env.UI_EVIDENCE_DIR||'artifacts/reference-scenarios'),report=await check({browser,base:'http://127.0.0.1:'+server.address().port+'/',output});fs.writeFileSync(path.join(output,'reference-scenarios.json'),JSON.stringify(report,null,2)+'\n');
 })().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));});
}
