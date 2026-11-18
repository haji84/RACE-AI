/* Invented data only. Long-data probes never produce screenshots or traces. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {chromium}=require('playwright'),root=path.resolve(__dirname,'../web');
const raw=fs.readFileSync(path.join(root,'data/example-synthetic-forecast-audit.json')),fixture=JSON.parse(raw);
let browser,server;
(async()=>{
 server=http.createServer((req,res)=>{
  const name=new URL(req.url,'http://local').pathname,file=path.resolve(root,'.'+(name==='/'?'/index.html':name));
  if(req.method!=='GET'||!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.statusCode=404;return res.end();}
  res.setHeader('Content-Type',{'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.webp':'image/webp'}[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 for(const width of [320,390,1440,1920]){
  const height=width<600?844:1000,context=await browser.newContext({viewport:{width,height}}),page=await context.newPage(),errors=[];
  await context.route('**/*',r=>new URL(r.request().url()).origin===origin?r.continue():r.abort());
  page.on('pageerror',e=>errors.push(e.name));page.setDefaultTimeout(7000);
  await page.clock.install({time:new Date('2030-01-01T00:30:00Z')});await page.goto(origin+'/');
  assert.deepEqual(await page.evaluate(()=>({width:innerWidth,height:innerHeight})),{width,height});
  const nav=async name=>page.locator('[data-page="'+name+'"]').filter({visible:true}).first().click();
  const load=async data=>{
   await page.evaluate(()=>document.querySelector('#file-message').textContent='');
   await page.locator('#race-file').setInputFiles({name:'invented-control-check.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(data))});
   await page.waitForFunction(()=>document.querySelector('#file-message').textContent.length>0);
   assert.match(await page.locator('#file-message').textContent(),/端末内で読み込みました/);
   await page.locator('#selected-date').fill('2030-01-01');await page.locator('#selected-date').dispatchEvent('change');
  };
  await load(fixture);await nav('picks');await page.locator('#copy-top8').click();await page.locator('#equal-allocate').click();
  assert.equal(await page.locator('.ticket-row').count(),8);
  const row=await page.locator('.ticket-row').first().boundingBox();assert.ok(row.height<=82,`${width}px ticket editor row is unnecessarily tall: ${row.height}`);
  assert.equal(await page.locator('.ticket-row .tag').first().isVisible(),true,'saved/manual candidate origin remains visible');
  assert.ok((await page.locator('.ticket-amount').first().boundingBox()).height>=44,'amount remains a usable touch target');
  assert.ok((await page.locator('[data-delete-ticket]').first().boundingBox()).height>=44);
  const combo=await page.locator('.ticket-row .combo').first().boundingBox(),amount=await page.locator('.ticket-amount').first().boundingBox();
  assert.ok(combo.x+combo.width<=amount.x,'ticket combination must not overlap the editable amount');
  await page.locator('.ticket-amount').first().fill('10000000');await page.locator('.ticket-amount').first().press('Tab');
  assert.equal(await page.locator('.ticket-amount').first().inputValue(),'10000000');
  // Inspect native text bounds without screenshot, trace or DOM export. The
  // outer input's scrollWidth does not reveal clipping inside its editor.
  const nativeAmountBounds=async()=>{
   const cdp=await context.newCDPSession(page);
   try{
    const element=await cdp.send('Runtime.evaluate',{expression:'document.querySelector(".ticket-amount")'});
    const dom=await cdp.send('DOM.describeNode',{objectId:element.result.objectId,depth:-1,pierce:true});
    const walk=n=>[n,...[...(n.children||[]),...(n.shadowRoots||[])].flatMap(walk)];
    const viewport=walk(dom.node).find(n=>n.attributes?.some((v,i,a)=>i%2===0&&v==='id'&&a[i+1]==='editing-view-port'));
    assert.ok(viewport,'native numeric editing viewport is inspected');
    const editor=walk(viewport).find(n=>n.nodeName==='DIV'&&!n.attributes?.some((v,i,a)=>i%2===0&&v==='id'&&a[i+1]));
    assert.ok(editor,'native numeric text editor exists within its viewport');
    const remote=await cdp.send('DOM.resolveNode',{backendNodeId:editor.backendNodeId});
    const native=await cdp.send('Runtime.callFunctionOn',{objectId:remote.object.objectId,functionDeclaration:'function(){return {client:this.clientWidth,scroll:this.scrollWidth}}',returnByValue:true});
    assert.ok(native.result.value.scroll<=native.result.value.client,`${width}px maximum candidate amount clips: ${JSON.stringify(native.result.value)}`);
    return native.result.value;
   }finally{await cdp.detach();}
  };
  const maximumAmount=await nativeAmountBounds();
  await page.locator('.ticket-amount').first().fill('200');await page.locator('.ticket-amount').first().press('Tab');
  // Native macOS Safari keeps a scrollbar gutter even at a 320px window.
  // Inspect visible lane descendants: the grid item's own box can be narrow
  // while its third lane still paints underneath the amount editor.
  await page.evaluate(()=>document.documentElement.style.scrollbarGutter='stable');
  const gutterPixels=await page.evaluate(()=>innerWidth-document.documentElement.getBoundingClientRect().width);
  assert.ok(gutterPixels>0,'the narrow-window check must reserve an actual native scrollbar gutter');
  const visibleLanes=await page.locator('.ticket-row .combo').first().locator('.lane').evaluateAll(lanes=>lanes.map(e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width};}));
  const amountWithGutter=await page.locator('.ticket-amount').first().boundingBox();
  assert.equal(visibleLanes.length,3);
  assert.ok(visibleLanes.every(lane=>lane.right<=amountWithGutter.x-2),`${width}px visible ticket numbers overlap the amount editor with a native scrollbar: ${JSON.stringify({visibleLanes,amountWithGutter})}`);
  assert.ok(visibleLanes.every(lane=>lane.width>=22),'all three ticket numbers remain legible');
  await page.evaluate(()=>document.documentElement.style.removeProperty('scrollbar-gutter'));
  assert.match(await page.locator('#allocation-summary').innerText(),/1,900円/);await page.locator('#confirm-candidates').click();
  assert.match(await page.locator('#confirmation-state').innerText(),/候補確定済み.*実購入ではありません/);
  assert.equal(await page.locator('#record-purchase').isDisabled(),true);
  await page.locator('#reopen-candidates').click();assert.match(await page.locator('#confirmation-state').innerText(),/編集中/);
  await page.locator('[data-delete-ticket]').first().click();assert.equal(await page.locator('.ticket-row').count(),7);
  await page.locator('[data-sport="horse"]').click();await page.locator('#race-budget').fill('10000000');await page.locator('#race-budget').press('Tab');
  for(const [id,value] of [['#lane-first','18'],['#lane-second','17'],['#lane-third','16']])await page.locator(id).selectOption(value);
  await page.locator('#ticket-amount').fill('10000000');await page.locator('#ticket-form button[type="submit"]').click();
  assert.equal(await page.locator('.ticket-row').count(),1);assert.match(await page.locator('.ticket-row .tag').innerText(),/手入力/);
  const manualCombo=await page.locator('.ticket-row .combo').boundingBox(),manualAmount=await page.locator('.ticket-amount').boundingBox();
  assert.ok(manualCombo.x+manualCombo.width<=manualAmount.x,'two-digit manual combination remains separate from maximum amount');
  const manualText=await page.locator('.ticket-row .combo').innerText();for(const value of ['18','17','16'])assert.ok(manualText.includes(value));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await nativeAmountBounds();await page.locator('#confirm-candidates').click();assert.equal(await page.locator('#record-purchase').isDisabled(),true);
  await page.locator('[data-sport="boat"]').click();await page.locator('#race-budget').fill('2000');await page.locator('#race-budget').press('Tab');
  await nav('results');const coverage=await page.locator('#result-coverage').boundingBox(),list=await page.locator('#saved-results-table').boundingBox(),metrics=await page.locator('#saved-result-metrics').boundingBox();
  assert.ok(coverage.y<list.y&&list.y<metrics.y,'trust coverage and individual results precede the full metric grid');
  assert.match(await page.locator('#result-coverage').innerText(),/原本の時刻は変更せず、公式成績には加算しません/);
  assert.equal(await page.locator('#saved-result-metrics .metric').count(),8);
  const long=structuredClone(fixture),race=long.records[0],model='合成テスト専用の長いモデル名'.repeat(8),rationale='合成テスト専用の長い日本語根拠です。原本と表示値の区別を保持します。'.repeat(30),missing='合成テスト専用の長い未取得理由。原本の欠測を省略しません。'.repeat(20);
  race.venue='合成テスト専用の長い会場名'.repeat(8).slice(0,100);race.prediction={...race.prediction,model_id:model,model_version:'合成の長い版名'.repeat(6),stage:'P0',as_of:'2030-01-01T09:00:00+09:00',rationale};
  race.participants=Array.from({length:6},(_,i)=>({number:i+1,name:('合成テスト専用の長い選手名'+i).repeat(i?2:30)}));
  race.missing_reasons=[missing];race.source_provenance='合成テスト専用の長い出典表示です。'.repeat(20);
  race.comparison_predictions=[{...race.prediction,model_version:'合成の別の長い版名'.repeat(6),prediction_sha256:'c'.repeat(64),as_of:'2030-01-01T09:01:00+09:00',generated_at:'2030-01-01T09:01:00+09:00',persisted_at:'2030-01-01T09:06:00+09:00'}];
  const readable=async id=>{
   const select=page.locator(id);await select.focus();const selected=await select.locator('option:checked').textContent(),full=select.locator('..').locator('.selected-option-text');
   assert.equal(await full.isVisible(),true);assert.equal(await full.textContent(),selected);
   assert.ok((await full.boundingBox()).height>0);assert.equal(await full.evaluate(e=>e.scrollHeight<=e.clientHeight+1&&e.scrollWidth<=e.clientWidth+1),true,'focused selection text is not clipped');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  };
  const original=JSON.stringify(long);await load(long);await nav('picks');await readable('#ticket-race');await nav('results');await readable('#results-model');
  await nav('home');await page.locator('#home-races [data-open-race]').first().click();await readable('#detail-model-select');await readable('#prediction-select');
  await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');assert.equal(await page.locator('#prediction-select').inputValue(),'1');
  await page.keyboard.press('Escape');await page.keyboard.press('Tab');assert.notEqual(await page.evaluate(()=>document.activeElement.id),'prediction-select');
  assert.equal(await page.locator('.forecast-rationale').textContent(),rationale);
  assert.equal(await page.locator('.forecast-rationale').evaluate(e=>e.scrollHeight<=e.clientHeight+1),true,'long rationale remains in normal page flow');
  await page.locator('[data-detail-tab="participants"]').click();
  const name=page.locator('.racer-name').filter({hasText:race.participants[0].name}).first();
  assert.equal(await name.textContent(),race.participants[0].name);
  assert.equal(await name.evaluate(e=>e.scrollHeight<=e.clientHeight+1&&e.scrollWidth<=e.clientWidth+1),true,'long Japanese participant name stays readable');
  await nav('research');const audit=await page.locator('#research-race-audit').innerText();assert.ok(audit.includes(model));assert.ok(audit.includes(missing));assert.ok(audit.includes(race.source_provenance));
  assert.equal(await page.locator('.audit-codes').evaluate(e=>e.scrollHeight<=e.clientHeight+1&&e.scrollWidth<=e.clientWidth+1),true,'long missing reasons remain readable');
  await page.locator('[data-return-to-race]').click();assert.equal(await page.locator('#prediction-select').inputValue(),'1');
  assert.equal(JSON.stringify(long),original);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);
  console.log('PASS allocation/results/long controls '+JSON.stringify({width,height,ticket_row_height:Math.round(row.height),maximum_amount_native_bounds:maximumAmount,native_scrollbar_gutter_px:gutterPixels,minimum_ticket_lane_gap_px:Math.min(...visibleLanes.map(lane=>amountWithGutter.x-lane.right)),two_digit_manual_combo:true,trust_before_results:true,results_before_metrics:true}));await context.close();
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));});
