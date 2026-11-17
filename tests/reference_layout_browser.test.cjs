/* Public invented fixture only; viewport evidence is not native iPhone acceptance. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../web'),raw=fs.readFileSync(path.join(root,'data/example-synthetic-forecast-audit.json'));
assert.equal(crypto.createHash('sha256').update(raw).digest('hex'),'b49654f4cbf5527131b38971e3504a52d5d9431ff62aa1c2dde4bc9bf96da00a');
const fixture=JSON.parse(raw);let server,browser;
(async()=>{
 server=http.createServer((req,res)=>{
  const name=new URL(req.url,'http://local').pathname,file=path.resolve(root,'.'+(name==='/'?'/index.html':name));
  if(req.method!=='GET'||!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.statusCode=404;return res.end();}
  res.setHeader('Content-Type',{'.js':'text/javascript','.css':'text/css','.json':'application/json','.html':'text/html','.webp':'image/webp'}[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 for(const width of [320,390,1440,1920]){
  const height=width<600?844:1000,context=await browser.newContext({viewport:{width,height}}),page=await context.newPage(),errors=[];
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  page.on('pageerror',e=>errors.push(e.name));page.setDefaultTimeout(7000);
  await page.clock.install({time:new Date('2030-01-01T00:30:00Z')});await page.goto(origin+'/');
  assert.deepEqual(await page.evaluate(()=>({width:innerWidth,height:innerHeight})),{width,height},'recorded evidence must use the requested viewport');
  await page.locator('#race-file').setInputFiles({name:'public-synthetic-layout.json',mimeType:'application/json',buffer:raw});
  await page.waitForFunction(()=>document.querySelector('#source-state').textContent.includes('合成'));
  await page.locator('#selected-date').fill(fixture.event_date_jst);await page.locator('#selected-date').dispatchEvent('change');
  const nav=async name=>page.locator('[data-page="'+name+'"]').filter({visible:true}).first().click();
  const visibleBottom=async()=>await page.locator('.bottom-nav').isVisible()?(await page.locator('.bottom-nav').boundingBox()).y:height;
  const shown=async(selector,label)=>{
   const box=await page.locator(selector).first().boundingBox(),bottom=await visibleBottom();
   assert.ok(box.y>=0&&box.y+box.height<=bottom-8,`${width}px ${label} must be above the fixed navigation: ${JSON.stringify({box,bottom})}`);
   return {top:Math.round(box.y),bottom:Math.round(box.y+box.height),available_bottom:Math.round(bottom)};
  };
  const bounds={width,height};await nav('home');bounds.home=await shown('#home-races .race-card h3','first home race heading');
  await nav('races');await page.locator('[data-race-view="results"]').click();await page.evaluate(()=>scrollTo(0,0));
  bounds.races=await shown('#all-races .race-card h3','first listed race heading');
  await page.locator('#race-browse-options').click();assert.equal(await page.locator('#race-model-select').evaluate(e=>e===document.activeElement),true,'relocated controls have a direct keyboard-accessible route');
  assert.match(await page.locator('#venue-buttons').innerText(),/未取得/,'missing venue states are retained');
  const other=await page.locator('#race-model-select option').filter({hasText:'未保存'}).first().getAttribute('value');
  await page.locator('#race-model-select').selectOption(other);assert.match(await page.locator('#all-races').innerText(),/保存された予想はありません/);
  await page.locator('#race-model-select').selectOption('');
  await page.locator('#all-races [data-open-race]').first().click();await page.evaluate(()=>scrollTo(0,0));
  bounds.detail=await shown('#detail-tab-content .forecast-panel .saved-ticket','first saved forecast ticket');
  assert.equal(await page.locator('#data-banner').isVisible(),true,'the synthetic warning remains visible');
  assert.equal(await page.locator('#data-banner').evaluate(e=>{const r=e.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return hit===e||e.contains(hit);}),true,'primary content must not cover the synthetic warning');
  assert.match(await page.locator('.race-result-summary').innerText(),/合成・的中/);
  assert.equal(await page.locator('#detail-model-select').inputValue(),'');
  assert.equal(await page.locator('#period-filter').isVisible(),true,'period controls remain available after primary detail content');
  await page.locator('#period-filter').selectOption('all');
  await page.locator('#page-detail .back-button').click();assert.equal(await page.locator('#period-filter').inputValue(),'all');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);
  console.log('PASS reference layout '+JSON.stringify(bounds));await context.close();
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));});
