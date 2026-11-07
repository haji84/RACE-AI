/* Invented UI-only races: venue labels never attest to actual schedules or results. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../web');
const names=['桐生','戸田','江戸川','平和島','多摩川','浜名湖','蒲郡','常滑','津','三国','びわこ','住之江','尼崎','鳴門','丸亀','児島','宮島','徳山','下関','若松','芦屋','福岡','唐津','大村'];
const records=names.map((_,i)=>({race_id:`venue-ui-test:${i+1}`,sport:'boat',venue:'場コード'+String(i+1).padStart(2,'0'),race_no:1,
  event_date_jst:'2030-01-01',cutoff_at:'2030-01-01T10:00:00+09:00',offering_status:'TRIFECTA_OFFERED',scope:'synthetic',
  source_provenance:'VENUE_UI_TEST_ONLY',source_sha256:'a'.repeat(64),prediction:null,result:null,participants:[]}));
records.push({...records[0],race_id:'venue-ui-test:named',venue:'桐生',race_no:2});
records[23].result={status:'final',winning_combinations:[[1,2,3]],payout_yen_per_100:1500,official:false,
  confirmed_at:'2030-01-01T10:20:00+09:00',observed_at:'2030-01-01T10:21:00+09:00',source_sha256:'b'.repeat(64)};
const fixture={schema:'RACE_AI_FORECAST_AUDIT_V1',dataset_status:'SYNTHETIC_ONLY',records};
let server,browser;
(async()=>{
  const errors=[];
  server=http.createServer((req,res)=>{
    const relative=new URL(req.url,'http://localhost').pathname.replace(/^\/RACE-AI\//,'/');
    const file=path.resolve(root,'.'+(relative==='/'?'/index.html':relative));
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.statusCode=404;return res.end();}
    res.setHeader('Content-Type',{'.js':'text/javascript','.css':'text/css','.html':'text/html','.json':'application/json'}[path.extname(file)]||'application/octet-stream');
    res.end(fs.readFileSync(file));
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const base=process.env.VENUES_DEPLOYED_URL||`http://127.0.0.1:${server.address().port}/RACE-AI/`;
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:fs.existsSync('/usr/bin/chromium')?{executablePath:'/usr/bin/chromium'}:{}),args:['--no-sandbox']});
  const evidence=path.resolve(process.env.UI_VENUE_EVIDENCE||'artifacts/ui-venues');fs.mkdirSync(evidence,{recursive:true});
  for(const width of [320,390,1440]){
    const context=await browser.newContext({viewport:{width,height:900}}),page=await context.newPage();
    page.on('pageerror',e=>errors.push(e.message));
    await page.clock.install({time:new Date('2030-01-01T00:00:00Z')});
    await page.goto(base);
    await page.locator('#race-file').setInputFiles({name:'venue-ui-test.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture))});
    await page.waitForFunction(()=>document.querySelector('#file-message').textContent.length>0);
    const nav=name=>page.locator(`[data-page="${name}"]`).filter({visible:true}).first().click();
    await nav('home');
    assert.ok(await page.locator('#page-home .race-card h3').count()>0);
    assert.doesNotMatch((await page.locator('#page-home .race-card h3').allTextContents()).join(' '),/場コード/);
    await nav('races');
    assert.deepEqual((await page.locator('#all-races .race-card h3').allTextContents()).sort(),[...names.map(n=>n+' 1R'),'桐生 2R'].sort());
    assert.deepEqual((await page.locator('#venue-buttons button').allTextContents()).sort(),[...names].sort(),'coded and named imports share one venue button');
    assert.deepEqual((await page.locator('#venue-filter option').allTextContents()).slice(1).sort(),[...names].sort());
    await page.locator('#venue-filter').selectOption({label:'桐生'});
    assert.equal(await page.locator('#all-races .race-card').count(),2);
    await page.locator('#venue-buttons button').filter({hasText:/^大村$/}).click();
    assert.deepEqual(await page.locator('#all-races .race-card h3').allTextContents(),['大村 1R']);
    await page.screenshot({path:path.join(evidence,`venues-${width}.png`),fullPage:true});
    await page.locator('#venue-buttons button').filter({hasText:/^大村$/}).click();
    await page.locator('#race-search').fill('徳山');
    assert.deepEqual(await page.locator('#all-races .race-card h3').allTextContents(),['徳山 1R']);
    await page.locator('#race-search').fill('場コード18');
    assert.deepEqual(await page.locator('#all-races .race-card h3').allTextContents(),['徳山 1R']);
    await page.locator('#race-search').fill('大村');
    await page.locator('#all-races [data-open-race]').first().click();
    assert.equal(await page.locator('#race-detail .detail-title h2').innerText(),'大村 1R');
    await nav('picks');
    assert.doesNotMatch((await page.locator('#ticket-race option').allTextContents()).join(' '),/場コード/);
    await nav('results');
    assert.match(await page.locator('#official-results').innerText(),/大村 1R/);
    assert.doesNotMatch(await page.locator('#official-results').innerText(),/場コード/);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await context.close();
    console.log(`PASS venue names ${width}px: all 24 venues, mixed imports, filters, search, home, detail, picks and results`);
  }
  assert.deepEqual(errors,[]);
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));});
