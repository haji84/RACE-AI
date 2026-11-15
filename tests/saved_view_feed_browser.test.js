'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http');
const {spawnSync}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'saved-feed-'));
let browser,server;
(async()=>{
 const py=spawnSync(process.env.RACE_AI_TEST_PYTHON||'python',['-c',`
import sys,json
from pathlib import Path
from tests.test_boat_pdca_github_handoff import invented_research_state
from tests.test_boat_pdca_state import result
from race_ai.boat_pdca_state import PdcaState,sha
from race_ai.saved_pages import build_site,_viewer
from race_ai.boat_pdca_projection import project_pdca
from race_ai import saved_view_feed as F
p=Path(sys.argv[1]);s,pair=invented_research_state(p);state=PdcaState(s);view=project_pdca(state);pin=state.content_sha256();state.close()
b=build_site(s,p/'public',p/'private',expected_source_sha256=pin);key,vid=_viewer(p/'private/viewer.json')
# A V1 seed's view id is its cipher hash; feed V3 keeps the same original URL.
previous=b['cipher_sha256']
for gen,status in [(1,'PENDING'),(2,'AVAILABLE')]:
 o=result(pair);o['captured_at']=f'2026-11-06T11:{40+gen}:00+09:00'
 if status=='PENDING':o.update(status=status,data=None)
 view=F.update_view(view,[o],synced_at=f'2026-11-06T03:{gen:02}:00Z')
 view['records'][0]['live_boat_observation']=dict(schema='RACE_AI_LIVE_BOAT_OBSERVATION_V1',state='SOURCE_WAIT',checked_at=f'2026-11-06T03:{gen:02}:00Z',context=None,forecast_inputs_used=False)
 raw=F.encrypt_view(view,key,view_id=vid,source_sha=pin,generation=gen,previous=previous);ident=sha(raw)
 (p/f'feed{gen}.json').write_bytes(raw);(p/f'latest{gen}.json').write_text(json.dumps(dict(header=json.loads(raw)['header'],cipher_sha256=ident)))
 previous=ident
`,dir],{cwd:root,encoding:'utf8'});assert.equal(py.status,0,py.stderr);
 let generation=1,tamper=false,offline=false;const requests=[],errors=[];
 server=http.createServer((req,res)=>{const name=new URL(req.url,'http://local').pathname.slice(1)||'index.html';const p=path.join(dir,'public',name);
  if(!fs.existsSync(p)){res.statusCode=404;res.end();return;}res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(p));});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 browser=await chromium.launch({headless:true,executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:390,height:844}});page.on('pageerror',e=>errors.push(e.message));
 page.setDefaultTimeout(7000);
 page.on('request',r=>requests.push({url:r.url(),headers:r.headers()}));
 await page.route('https://raw.githubusercontent.com/haji84/RACE-AI/state/boat-saved-view/**',async route=>{
  if(offline)return route.abort();const url=new URL(route.request().url()),manifest=url.pathname.endsWith('/latest.json');
  let body=fs.readFileSync(path.join(dir,`${manifest?'latest':'feed'}${generation}.json`));if(tamper&&!manifest)body=Buffer.concat([body,Buffer.from(' ')]);
  await route.fulfill({contentType:'application/json',headers:{'access-control-allow-origin':'*'},body});});
 const fragment=fs.readFileSync(path.join(dir,'private/owner-url.txt'),'utf8').trim().split('#')[1];
 const key=JSON.parse(fs.readFileSync(path.join(dir,'private/viewer.json'))).key;
 await page.clock.install({time:new Date('2026-11-06T04:00:00Z')});await page.goto('http://127.0.0.1:'+server.address().port+'/#'+fragment);
 await page.waitForFunction(()=>document.querySelector('#file-message').textContent.includes('保存済み予想'));
 await page.waitForFunction(()=>document.querySelector('#saved-view-sync')?.dataset.generation==='1',{},{timeout:6000}).catch(async e=>{console.error(await page.locator('#saved-view-sync').textContent(),requests.map(r=>new URL(r.url).hostname),errors);throw e;});
 await page.locator('[data-page="races"]').filter({visible:true}).first().click();await page.locator('[data-race-view="results"]').click();
 await page.locator('#page-races [data-open-race]').first().click();await page.locator('#prediction-select').selectOption('2');
 await page.locator('[data-page="picks"]').filter({visible:true}).first().click();
 await page.locator('#copy-top8').click();
 const amounts=await page.locator('#ticket-list .ticket-amount').count();assert.equal(amounts,8);
 await page.locator('[data-page="results"]').filter({visible:true}).first().click();
 assert.match(await page.locator('#saved-result-metrics').innerText(),/結果待ち\s*1レース/);
 await page.locator('#simulation-budget').fill('5000');await page.locator('#simulation-budget').dispatchEvent('change');await page.locator('#result-coverage').click();
 await page.locator('#simulation-budget').focus();
 generation=2;tamper=true;await page.clock.fastForward(61000);
 await page.waitForFunction(()=>document.querySelector('#saved-view-sync').textContent.includes('前回取得'));
 assert.equal(await page.locator('#saved-view-sync').getAttribute('data-generation'),'1');
 tamper=false;await page.clock.fastForward(61000);
 await page.waitForFunction(()=>document.querySelector('#saved-view-sync')?.dataset.generation==='2');
 assert.match(await page.locator('#saved-result-metrics').innerText(),/取得結果\s*1レース/);
 assert.equal(await page.locator('#simulation-budget').inputValue(),'5000');
 assert.equal(await page.locator('#simulation-budget').evaluate(el=>el===document.activeElement),true,'result refresh must preserve an active budget edit');
 await page.locator('[data-page="races"]').filter({visible:true}).first().click();await page.locator('#page-races [data-open-race]').first().click();
 assert.equal(await page.locator('#prediction-select').inputValue(),'2');
 await page.locator('[data-page="picks"]').filter({visible:true}).first().click();assert.equal(await page.locator('#ticket-list .ticket-amount').count(),8);
 generation=1;await page.clock.fastForward(61000);assert.equal(await page.locator('#saved-view-sync').getAttribute('data-generation'),'2');
 generation=2;offline=true;await page.clock.fastForward(61000);assert.match(await page.locator('#saved-result-metrics').innerText(),/取得結果\s*1レース/);
 assert.equal((await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).includes(key),false);
 assert.equal(requests.some(r=>JSON.stringify(r).includes(key)),false);assert.deepEqual(errors,[]);
 console.log('PASS live encrypted feed: two updates, latest pending/final, budget retained, rollback/offline retained, no key requests/storage');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(r=>server.close(r));fs.rmSync(dir,{recursive:true,force:true});});
