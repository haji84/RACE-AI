/* Invented rows and a controlled clock; no real racing/accuracy claims. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'../web'),folder=process.env.UI_LIFECYCLE_EVIDENCE||'/tmp/race-lifecycle-ui';
const top8=[[1,2,3],[1,3,2],[2,1,3],[2,3,1],[3,1,2],[3,2,1],[1,2,4],[1,3,4]];
function row(venue,code,no,cutoff,result=null){return {race_id:`20300101-${code}-${String(no).padStart(2,'0')}`,sport:'boat',venue,race_no:no,event_date_jst:'2030-01-01',cutoff_at:cutoff,scope:'synthetic',offering_status:'TRIFECTA_OFFERED',source_provenance:'INVENTED_UI_LIFECYCLE_ONLY',source_sha256:'a'.repeat(64),prediction:cutoff?{stage:'P0',model_id:'boat-observed-pairwise-factor-v1',model_version:'0.1.0-UNTRAINED',ordered_top8:top8,generated_at:'2030-01-01T08:00:00+09:00',input_sha256:'a'.repeat(64),prediction_sha256:'b'.repeat(64),persisted_at:'2030-01-01T08:00:00+09:00',as_of:'2030-01-01T08:00:00+09:00',cutoff_at:cutoff,odds_independent:true,rationale:'架空の予想根拠です。'}:null,no_forecast_reason:cutoff?null:'締切時刻未取得',result,participants:[]};}
const rows=[row('江戸川','03',1,'2030-01-01T09:50:00+09:00',{status:'final',winning_combinations:[[1,2,3]],payout_yen_per_100:1250,confirmed_at:'2030-01-01T09:55:00+09:00',observed_at:'2030-01-01T09:55:00+09:00',official:false}),row('江戸川','03',2,'2030-01-01T09:55:00+09:00'),row('江戸川','03',3,'2030-01-01T10:02:00+09:00'),row('びわこ','11',1,'2030-01-01T09:58:00+09:00',{status:'unsupported',winning_combinations:[],official:false}),row('びわこ','11',2,'2030-01-01T10:01:00+09:00'),row('びわこ','11',3,null),row('びわこ','11',4,'2030-01-01T11:00:00+09:00')];
const fixture={schema:'RACE_AI_FORECAST_AUDIT_V1',dataset_status:'SYNTHETIC_ONLY',records:rows};require('../web/product-data.js').parse(fixture);
let browser,server;
(async()=>{
  fs.mkdirSync(folder,{recursive:true});server=http.createServer((req,res)=>{const name=new URL(req.url,'http://local').pathname,file=path.resolve(root,'.'+(name==='/'?'/index.html':name));if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.statusCode=404;return res.end();}res.setHeader('Content-Type',{'.js':'text/javascript','.css':'text/css','.json':'application/json','.html':'text/html','.webp':'image/webp'}[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));});await new Promise(r=>server.listen(0,'127.0.0.1',r));
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
  for(const width of [320,390,1440]){
    const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(8000);await page.clock.install({time:new Date('2030-01-01T01:00:00Z')});await page.goto('http://127.0.0.1:'+server.address().port+'/');
    await page.locator('#selected-date').fill('2030-01-01');await page.locator('#selected-date').dispatchEvent('change');await page.locator('#race-file').setInputFiles({name:'invented-lifecycle.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture))});await page.locator('[data-page="races"]').filter({visible:true}).first().click();
    const list=page.locator('#all-races'),tab=view=>page.locator('[data-race-view="'+view+'"]');
    assert.equal(await tab('upcoming').getAttribute('aria-selected'),'true');assert.deepEqual(await list.locator('[data-open-race]').evaluateAll(nodes=>nodes.map(n=>n.dataset.openRace)),[rows[4].race_id,rows[2].race_id,rows[6].race_id]);
    assert.doesNotMatch(await list.innerText(),/結果待ち/,'races before their deadline must not be presented as missing results');
    await page.locator('[data-page="results"]').filter({visible:true}).first().click();
    const pendingMetric=page.locator('#saved-result-metrics .metric').filter({has:page.getByText('結果待ち',{exact:true})});
    assert.match(await pendingMetric.innerText(),/1レース/,'only the closed race with a missing result is counted as pending');
    const preRaceMetric=page.locator('#saved-result-metrics .metric').filter({has:page.getByText('レース前',{exact:true})});
    assert.match(await preRaceMetric.innerText(),/3レース/);
    assert.equal(await page.locator('#saved-results-table .result-mobile-card').count(),3,'result rows omit future and unknown-deadline races');
    await page.locator('#simulation-ledger-details>summary').click();
    const futureLedger=page.locator('#simulation-ledger tbody tr').filter({hasText:'びわこ 4R'});
    assert.match(await futureLedger.innerText(),/レース前/,'planned allocations for future races are not described as missing result money');
    await page.locator('#simulation-ledger-details>summary').click();
    await page.locator('[data-page="races"]').filter({visible:true}).first().click();
    const nextHeading=await list.locator('.race-card h3').first().boundingBox(),bottomNav=await page.locator('.bottom-nav').boundingBox();assert.ok(nextHeading.y>=0&&nextHeading.y+nextHeading.height<(bottomNav?.y||900),'the next race heading must be visible without scrolling past the venue choices: '+JSON.stringify({width,nextHeading,bottomNav}));
    await tab('upcoming').focus();await page.keyboard.press('ArrowRight');assert.equal(await tab('results').getAttribute('aria-selected'),'true');await page.keyboard.press('ArrowLeft');assert.equal(await tab('upcoming').getAttribute('aria-selected'),'true');
    await page.locator('#venue-buttons [data-venue="江戸川"]').click();assert.equal(await list.locator('[data-open-race]').count(),1);assert.match(await list.innerText(),/江戸川 3R/);
    await tab('results').click();assert.equal(await page.locator('#venue-filter').inputValue(),'江戸川');assert.equal(await list.locator('[data-open-race]').count(),2);
    const winner=list.locator('[data-race-id="'+rows[0].race_id+'"]');assert.match(await winner.innerText(),/的中/);assert.match(await winner.innerText(),/1,250/);assert.deepEqual(await winner.locator('.result-block .combo .lane').allTextContents(),['1','2','3']);
    const pending=list.locator('[data-race-id="'+rows[1].race_id+'"]');assert.match(await pending.innerText(),/結果待ち|結果の反映を待/);assert.doesNotMatch(await pending.locator('.saved-outcome').innerText(),/不的中/);
    await winner.locator('[data-open-prediction]').click();assert.match(await page.locator('#race-detail .forecast-rationale').innerText(),/架空の予想根拠/);await page.locator('.back-button[data-page="races"]').click();assert.equal(await tab('results').getAttribute('aria-selected'),'true');
    await tab('upcoming').click();await page.clock.fastForward(121000);assert.equal(await list.locator('[data-open-race]').count(),0);assert.match(await list.innerText(),/締切前のレースはありません/);
    await tab('results').click();const newlyClosed=list.locator('[data-race-id="'+rows[2].race_id+'"]');assert.match(await newlyClosed.innerText(),/結果待ち|結果の反映を待/);assert.doesNotMatch(await newlyClosed.locator('.saved-outcome').innerText(),/不的中/);
    await page.locator('#all-venues').click();await tab('upcoming').click();assert.equal(await list.locator('[data-open-race]').count(),1);assert.match(await list.innerText(),/びわこ 4R/);
    await tab('unknown').click();assert.match(await list.innerText(),/びわこ 3R/);assert.match(await list.innerText(),/締切.*未確認|締切.*未取得/);
    const ai=page.locator('[data-page="results"]').filter({visible:true}).first();assert.match(await ai.innerText(),/AI予想結果/);await ai.click();assert.equal(await page.locator('#page-title').innerText(),'AI予想結果');assert.match(await pendingMetric.innerText(),/3レース/,'newly closed races enter pending only after their deadlines');assert.equal(await page.locator('#simulation-budget').isVisible(),true);
    await page.locator('#selected-date').fill('2029-12-31');await page.locator('#selected-date').dispatchEvent('change');await page.locator('[data-page="races"]').filter({visible:true}).first().click();assert.equal(await tab('results').getAttribute('aria-selected'),'true');
    await page.locator('#selected-date').fill('2030-01-01');await page.locator('#selected-date').dispatchEvent('change');assert.equal(await tab('upcoming').getAttribute('aria-selected'),'true');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);await page.close();console.log('PASS race lifecycle '+width+'px: next cutoff first, venue results, pending not miss, automatic transition, rationale and AI results');
  }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));});
