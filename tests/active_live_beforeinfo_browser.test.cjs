'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright'),{activeFixture}=require('./active_live_beforeinfo_fixture.cjs');
const web=path.resolve(__dirname,'../web');
test('three, five and six source-bound previews preserve saved rationale and ticket order',async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 try{for(const [lanes,savedLanes] of [[[1,3,6],[1,3,6]],[[1,2,3,4,5],[1,2,3,4,5]],[[1,2,3,4,5,6],[1,2,3,4,5,6]],[[1,2,3,4,5],[1,2,3,4,5,6]]]){
  const page=await browser.newPage({viewport:{width:390,height:900}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());assert.equal(url.origin,'https://active-context.test');
   const name=url.pathname==='/'?'index.html':url.pathname.slice(1),file=path.resolve(web,name);
   if(!file.startsWith(web+path.sep)||!fs.existsSync(file))return route.fulfill({status:404,body:''});
   await route.fulfill({body:fs.readFileSync(file),contentType:{'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json'}[path.extname(file)]});
  });
  await page.clock.install({time:new Date('2030-04-01T10:00:00Z')});await page.goto('https://active-context.test/');
  const data=activeFixture(lanes,{savedLanes}),row=data.records[0],tickets=structuredClone(row.prediction.ordered_top8);
  await page.locator('#race-file').setInputFiles({name:'invented-active.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(data))});
  await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('端末内で読み込みました'));
  await page.locator('#page-home [data-open-race]').first().click();
  await page.locator('[data-detail-tab="preview"]').click();
  assert.equal(await page.locator('#live-beforeinfo .preview-boat').count(),lanes.length);
  assert.match(await page.locator('#live-beforeinfo').innerText(),/6\.82/);
  assert.deepEqual(await page.locator('#live-beforeinfo .preview-person .lane').allTextContents(),lanes.map(String));
  await page.locator('[data-detail-tab="outlook"]').click();
  assert.equal(await page.locator('#forecast-rationale').innerText(),row.prediction.rationale);
  const rendered=await page.locator('#detail-tab-content .saved-ticket .combo').evaluateAll(nodes=>nodes.map(n=>[...n.querySelectorAll('.lane')].map(e=>Number(e.textContent))));
  assert.deepEqual(rendered,tickets);assert.deepEqual(errors,[]);
  await page.close();
 }}finally{await browser.close();}
});
