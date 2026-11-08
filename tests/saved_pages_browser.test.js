/* Invented data: secret fragment never leaves browser, and real WebCrypto decrypts. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const http=require('node:http'),{spawnSync}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),folder=fs.mkdtempSync(path.join(os.tmpdir(),'saved-pages-'));
let browser,server;
(async()=>{
 const py=spawnSync(process.env.RACE_AI_TEST_PYTHON||'python',['-c',`
import sys,json
from pathlib import Path
import race_ai
race_ai.__path__.extend(str(Path(reference)/'race_ai') for reference in ('pr64-reference','pr72-reference'))
from tests.test_boat_pdca_github_handoff import invented_research_state
from race_ai.boat_pdca_state import PdcaState
from race_ai.saved_pages import build_site
r=Path(sys.argv[1]);p,_=invented_research_state(r);s=PdcaState(p)
try:pin=s.content_sha256()
finally:s.close()
build_site(p,r/'public',r/'private',expected_source_sha256=pin)
build_site(p,r/'updated-public',r/'updated-private',expected_source_sha256=pin,viewer_from=r/'private/viewer.json')
`,folder],{cwd:root,encoding:'utf8'});assert.equal(py.status,0,py.stderr);
 const secret=JSON.parse(fs.readFileSync(path.join(folder,'private/viewer.json'))),requests=[],errors=[];
 const fragment=fs.readFileSync(path.join(folder,'private/owner-url.txt'),'utf8').trim().split('#')[1];
 let tamper=false,activeRoot='public';
 server=http.createServer((req,res)=>{
  requests.push({url:req.url,method:req.method,referrer:req.headers.referer||''});
  const name=new URL(req.url,'http://localhost').pathname.replace(/^\/RACE-AI\//,'')||'index.html';
  if(!/^([a-z-]+\.(html|js|css)|views\/[a-f0-9]{64}\.json|data\/example-synthetic-forecast-audit\.json)$/.test(name)){res.statusCode=404;return res.end();}
  const file=path.join(folder,activeRoot,name);
  if(!fs.existsSync(file)){res.statusCode=404;return res.end();}
  res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':name.endsWith('.json')?'application/json':'text/html');
  let raw=fs.readFileSync(file);if(tamper&&name.startsWith('views/'))raw=Buffer.concat([raw,Buffer.from(' ')]);res.end(raw);
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port+'/RACE-AI/';
 browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:fs.existsSync('/usr/bin/chromium')?{executablePath:'/usr/bin/chromium'}:{}),args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:390,height:844}});page.on('pageerror',e=>errors.push(e.message));
 await page.clock.install({time:new Date('2030-01-01T00:00:00Z')});await page.goto(base+'#'+fragment);
 await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('保存済み予想'),{},{timeout:7000});
 assert.equal(await page.locator('#selected-date').inputValue(),'2030-01-01','cold open always starts with the local current day');
 assert.equal(await page.locator('#page-races .race-card').count(),0,'past forecasts must not appear as upcoming today');
 const openPastDay=async()=>{
  await page.locator('#selected-date').fill('2026-11-06');
  await page.locator('#selected-date').dispatchEvent('change');
  await page.waitForFunction(()=>document.querySelector('#selected-date').value==='2026-11-06'&&document.querySelectorAll('#page-races .race-card').length===1);
 };
 await openPastDay();
 assert.equal(await page.locator('.import-panel').isVisible(),false,'an automatically opened owner view must not ask for data files');
 assert.equal(await page.locator('#load-synthetic').isVisible(),false);
 for(const name of ['home','races','detail','picks','results','research','settings']){
  if(name==='detail'){await page.locator('[data-page="races"]').filter({visible:true}).first().click();await page.locator('[data-race-view="results"]').click();await page.locator('#page-races [data-open-race]').first().click();}
  else await page.locator(`[data-page="${name}"]`).filter({visible:true}).first().click();
  assert.equal(await page.locator('#page-'+name).isVisible(),true);
  assert.equal(new URL(page.url()).hash,'#'+fragment);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 }
 await page.locator('#page-settings a[href="#research"]').click();assert.equal(new URL(page.url()).hash,'#'+fragment);
 await page.locator('.brand').filter({visible:true}).first().click();assert.equal(new URL(page.url()).hash,'#'+fragment);
 await page.locator('.skip-link').focus();await page.keyboard.press('Enter');assert.equal(new URL(page.url()).hash,'#'+fragment);
 await page.reload();await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('保存済み予想'));
 assert.equal(await page.locator('#selected-date').inputValue(),'2030-01-01','reload must not pin past dates automatically');
 await openPastDay();
 await page.locator('#page-races [data-open-race]').first().click();assert.equal(await page.locator('#prediction-select option').count(),4);
 for(let i=0;i<4;i++)await page.locator('#prediction-select').selectOption(String(i));
 assert.equal((await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).includes(secret.key),false);
 assert.equal(requests.some(r=>(r.url+r.referrer).includes(secret.key)||r.method!=='GET'),false);
 assert.deepEqual(errors,[]);
 activeRoot='updated-public';await page.reload();
 await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('保存済み予想'));
 assert.equal(new URL(page.url()).hash,'#'+fragment,'original V1 owner link must open the updated V2 payload');
 assert.equal(await page.locator('#selected-date').inputValue(),'2030-01-01','new payload cold open must prioritize today');
 await openPastDay();
 assert.equal(await page.locator('#page-races .race-card').count(),1);
 for(const suffix of ['',fragment.replace(/\.[A-Za-z0-9_-]{43}$/,'.'+ 'A'.repeat(43)),fragment]){
  const before=requests.length;tamper=suffix===fragment;await page.goto(base+(suffix?'#'+suffix:''));
  await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('読めません')||document.querySelector('#file-message').textContent.includes('読み込めません'),{},{timeout:7000});
  assert.equal(await page.locator('#page-races .race-card').count(),0);
  assert.equal((await page.locator('#file-message').innerText()).includes(secret.key),false);
  assert.equal(await page.locator('.import-panel').isVisible(),false);
  assert.equal(await page.locator('#load-synthetic').isVisible(),false);
  if(!suffix){
   assert.match(await page.locator('#data-banner').innerText(),/閲覧用リンク/);
   assert.doesNotMatch(await page.locator('#home-races').innerText(),/JSON/);
   assert.equal(requests.slice(before).some(r=>r.url.includes('/views/')),false,'missing owner links must be explained before requesting encrypted race data');
  }
 }
 console.log('PASS encrypted Pages: actual WebCrypto, 7pages/reload/links, 4variants, past day, no key request/storage, tamper/wrong/missing key refused');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));fs.rmSync(folder,{recursive:true,force:true});});
