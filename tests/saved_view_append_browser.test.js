/* Fictional data and actual WebCrypto: append-only encrypted live view intake. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http');
const {spawnSync}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'saved-append-'));
let browser,server;
(async()=>{
 const py=spawnSync(process.env.RACE_AI_TEST_PYTHON||'python',['-c',`
import sys,json,os,base64
from copy import deepcopy
from pathlib import Path
import race_ai
race_ai.__path__.extend(str(Path(reference)/'race_ai') for reference in ('pr64-reference','pr72-reference'))
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from tests.test_boat_pdca_github_handoff import invented_research_state
from tests.test_boat_pdca_state import result
from race_ai.boat_pdca_state import PdcaState,sha
from race_ai.boat_history_store import wire
from race_ai.saved_pages import build_site,_viewer
from race_ai.boat_pdca_projection import project_pdca
from race_ai.boat_saved_model_view import saved_prediction_identity
from race_ai.actions_contract import digest
from race_ai import saved_view_feed as F
p=Path(sys.argv[1]);s,pair=invented_research_state(p);state=PdcaState(s)
try:seed=project_pdca(state);pin=state.content_sha256()
finally:state.close()
b=build_site(s,p/'public',p/'private',expected_source_sha256=pin);key,vid=_viewer(p/'private/viewer.json')
anchor=F.originals_sha(seed);rid=seed['records'][0]['race_id'];originals=[seed['records'][0]['prediction'],*seed['records'][0]['comparison_predictions']];target=deepcopy(originals[2])
def save(name,view,generation,previous,*,header_mutation=None):
 if 'forecast_base_sha256' not in view:
  raw=F.encrypt_view(view,key,view_id=vid,source_sha=pin,generation=generation,previous=previous)
 else:
  h=dict(schema=F.APPEND_FEED,source_content_sha256=pin,view_id=vid,forecast_sha256=anchor,generation=generation,previous_cipher_sha256=previous,forecast_inventory_sha256=F.inventory_sha(view))
  if header_mutation:header_mutation(h)
  nonce=os.urandom(12);cipher=AESGCM(key).encrypt(nonce,wire(view).encode(),wire(h).encode())
  raw=(wire(dict(header=h,nonce=base64.b64encode(nonce).decode(),ciphertext=base64.b64encode(cipher).decode()))+'\\n').encode()
 ident=sha(raw);(p/(name+'.json')).write_bytes(raw);(p/(name+'-latest.json')).write_text(wire(dict(header=json.loads(raw)['header'],cipher_sha256=ident)))
 return ident
pending=result(pair);pending.update(captured_at='2026-11-06T11:41:00+09:00',status='PENDING',data=None)
first=F.update_view(seed,[pending],synced_at='2026-11-06T03:01:00Z');one=save('v3',first,1,b['cipher_sha256'])
second=deepcopy(first);second['forecast_base_sha256']=anchor
native=deepcopy(originals[0]);native.update(model_id='synthetic-append-native',model_version=None,stage='P1',variant='NATIVE',source_code_commit='1'*40,artifact_id=601,prediction_sha256=digest({'synthetic':'native'}))
# Native saved candidate scores exercise Python's 1.0, -0.0 and exponent wire syntax.
scores=[0.0,1.0,1e-8,1e20,1.2345678901234567,-0.0]
native['candidates']=[dict(combination=deepcopy(t),score=scores[i%len(scores)]) for i,t in enumerate(native['ordered_candidates'])]
row=second['records'][0];row['prediction']=native;row['comparison_predictions']=[deepcopy(originals[i]) for i in (3,0,2,1)]
for i,person in enumerate(row['participants']):person['name']='架空追加選手'+str(i+1)
future=json.loads(json.dumps(deepcopy(row)).replace('2026-11-06','2026-11-07').replace('20261106','20261107'))
future['prediction']=deepcopy(future['prediction']);future['prediction'].update(model_id='synthetic-nextday-native',prediction_sha256=digest({'synthetic':'nextday'}))
future.update(comparison_predictions=[],result=None,result_observations=[],result_observation_rejections=[],result_revisions=[],venue='架空追加場')
second['records'].append(future);second['event_date_jst']=None;second['results_synced_at']='2026-11-06T03:02:00Z'
F.ensure_append_only(first,second);two=save('v4',second,2,one)
third=deepcopy(second);r=third['records'][0];new=deepcopy(native);new.update(model_id='synthetic-append-second',model_version='saved-test-v2',prediction_sha256=digest({'synthetic':'second'}))
saved=[r['prediction'],*r['comparison_predictions']];r['prediction']=new;r['comparison_predictions']=list(reversed(saved));third['results_synced_at']='2026-11-06T03:03:00Z'
F.ensure_append_only(second,third);three=save('v4-next',third,3,two)
wrong_base=deepcopy(third);wrong_base['forecast_base_sha256']='0'*64;save('bad-base',wrong_base,3,two)
save('bad-inventory',third,3,two,header_mutation=lambda h:h.update(forecast_inventory_sha256='f'*64))
removed=deepcopy(third);removed['records'][0]['comparison_predictions']=[q for q in removed['records'][0]['comparison_predictions'] if saved_prediction_identity(q)!=saved_prediction_identity(target)];save('removed',removed,3,two)
replaced=deepcopy(third);q=next(q for q in replaced['records'][0]['comparison_predictions'] if saved_prediction_identity(q)==saved_prediction_identity(target));q['ordered_top8']=list(reversed(q['ordered_top8']));q['ordered_candidates']=list(reversed(q['ordered_candidates']));save('replaced',replaced,3,two)
save('wrong-parent',third,3,two,header_mutation=lambda h:h.update(previous_cipher_sha256='0'*64))
indices=[]
for view in (second,third):
 r=view['records'][0];indices.append(next(i for i,q in enumerate([r['prediction'],*r['comparison_predictions']]) if saved_prediction_identity(q)==saved_prediction_identity(target)))
(p/'expected.json').write_text(wire(dict(race_id=rid,venue=seed['records'][0]['venue'],target=target,indices=indices)))
`,dir],{cwd:root,encoding:'utf8'});assert.equal(py.status,0,py.stderr);
 const expected=JSON.parse(fs.readFileSync(path.join(dir,'expected.json'))),requests=[],errors=[];
 let active='v3',tamper=false,offline=false;
 server=http.createServer((req,res)=>{const name=new URL(req.url,'http://local').pathname.slice(1)||'index.html',file=path.join(dir,'public',name);if(!fs.existsSync(file)){res.statusCode=404;return res.end();}res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:390,height:844}});page.setDefaultTimeout(9000);page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push({url:r.url(),headers:r.headers()}));
 await page.addInitScript(()=>{const original=JSON.parse;JSON.parse=function(source,reviver){return original(source,typeof reviver==='function'?function(key,value){return reviver.call(this,key,value);}:undefined);};});
 await page.route('https://raw.githubusercontent.com/haji84/RACE-AI/state/boat-saved-view/**',async route=>{
  if(offline)return route.abort();const manifest=new URL(route.request().url()).pathname.endsWith('/latest.json');
  let body=fs.readFileSync(path.join(dir,active+(manifest?'-latest':'')+'.json'));if(tamper&&!manifest)body=Buffer.concat([body,Buffer.from(' ')]);
  await route.fulfill({contentType:'application/json',headers:{'access-control-allow-origin':'*'},body});
 });
 const fragment=fs.readFileSync(path.join(dir,'private/owner-url.txt'),'utf8').trim().split('#')[1],key=JSON.parse(fs.readFileSync(path.join(dir,'private/viewer.json'))).key;
 await page.clock.install({time:new Date('2026-11-06T00:00:00Z')});await page.goto('http://127.0.0.1:'+server.address().port+'/#'+fragment);
 await page.waitForFunction(()=>document.querySelector('#saved-view-sync')?.dataset.generation==='1');
 await page.evaluate(()=>{const api=window.SavedViewCrypto;window.__savedFeedChecks=0;window.SavedViewCrypto={...api,readLive:async(...args)=>{try{return await api.readLive(...args);}finally{window.__savedFeedChecks++;}}};});
 async function tick(){const previous=await page.evaluate(()=>window.__savedFeedChecks);await page.clock.fastForward(61000);await page.waitForFunction(previous=>window.__savedFeedChecks>previous,previous);}
 await page.locator('#page-races [data-open-race]').first().click();await page.locator('#prediction-select').selectOption('2');
 await page.locator('[data-page="picks"]').filter({visible:true}).first().click();await page.locator('#copy-top8').click();
 await page.locator('#ticket-list .ticket-amount').first().fill('200');await page.locator('#ticket-list .ticket-amount').first().dispatchEvent('change');
 await page.locator('[data-page="settings"]').filter({visible:true}).first().click();await page.locator('#daily-budget').fill('6300');await page.locator('#settings-form button[type="submit"]').click();
 await page.locator('[data-page="races"]').filter({visible:true}).first().click();await page.locator('#race-search').fill(expected.venue);await page.locator('#race-filters > summary').click();await page.locator('#venue-filter').selectOption(expected.venue);await page.locator('#race-sort').selectOption('venue');
 await page.locator('[data-page="results"]').filter({visible:true}).first().click();await page.locator('#results-model').selectOption({index:2});
 const chosenGroup=await page.locator('#results-model').inputValue();await page.locator('#simulation-budget').fill('5000');await page.locator('#simulation-budget').dispatchEvent('change');await page.locator('#result-coverage').click();
 active='v4';await tick();await page.waitForFunction(()=>document.querySelector('#saved-view-sync')?.dataset.generation==='2');
 assert.equal(await page.locator('#selected-date').inputValue(),'2026-11-06');assert.equal(await page.locator('#simulation-budget').inputValue(),'5000');assert.equal(await page.locator('#results-model').inputValue(),chosenGroup);assert.equal(await page.locator('#results-model option').count(),5);
 assert.equal(await page.locator('#race-search').inputValue(),expected.venue);assert.equal(await page.locator('#venue-filter').inputValue(),expected.venue);assert.equal(await page.locator('#race-sort').inputValue(),'venue');
 await page.locator('[data-page="races"]').filter({visible:true}).first().click();await page.locator('#page-races [data-open-race]').first().click();
 assert.equal(await page.locator('#prediction-select').inputValue(),String(expected.indices[0]),'append/reordering retains the selected original by identity');
 assert.match(await page.locator('#detail-tab-content').innerText(),/架空追加選手1/);
 const combos=await page.locator('#detail-tab-content .saved-ticket .combo').evaluateAll(nodes=>nodes.map(n=>[...n.querySelectorAll('.lane')].map(x=>Number(x.textContent))));assert.deepEqual(combos,expected.target.ordered_top8);
 await page.locator('[data-page="picks"]').filter({visible:true}).first().click();assert.equal(await page.locator('#ticket-list .ticket-amount').count(),8);assert.equal(await page.locator('#ticket-list .ticket-amount').first().inputValue(),'200');
 await page.locator('[data-page="results"]').filter({visible:true}).first().click();await page.locator('#result-coverage').click();
 for(const invalid of ['bad-base','bad-inventory','removed','replaced','wrong-parent']){
  active=invalid;await tick();await page.waitForFunction(()=>document.querySelector('#saved-view-sync').textContent.includes('前回取得'));
  assert.equal(await page.locator('#saved-view-sync').getAttribute('data-generation'),'2',invalid+' retains the last valid view');assert.equal(await page.locator('#results-model option').count(),5);
 }
 active='v4-next';tamper=true;await tick();assert.equal(await page.locator('#saved-view-sync').getAttribute('data-generation'),'2');
 tamper=false;await tick();await page.waitForFunction(()=>document.querySelector('#saved-view-sync')?.dataset.generation==='3');assert.equal(await page.locator('#results-model option').count(),6);
 await page.locator('[data-page="races"]').filter({visible:true}).first().click();await page.locator('#page-races [data-open-race]').first().click();assert.equal(await page.locator('#prediction-select').inputValue(),String(expected.indices[1]));
 await page.locator('[data-page="settings"]').filter({visible:true}).first().click();assert.equal(await page.locator('#daily-budget').inputValue(),'6300');
 await page.locator('[data-page="races"]').filter({visible:true}).first().click();await page.locator('#period-filter').selectOption('all');await page.locator('[data-page="results"]').filter({visible:true}).first().click();assert.equal(await page.locator('#results-model option').count(),7,'new day and every saved model group are available');await page.locator('#result-coverage').click();
 active='v3';await tick();assert.equal(await page.locator('#saved-view-sync').getAttribute('data-generation'),'3');
 active='v4-next';offline=true;await tick();assert.equal(await page.locator('#saved-view-sync').getAttribute('data-generation'),'3');
 assert.equal((await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).includes(key),false);assert.equal(requests.some(r=>JSON.stringify(r).includes(key)),false);assert.deepEqual(errors,[]);
 console.log('PASS encrypted append feed: V3/V4, numeric canonical inventory, new days/models/names, identity selection, filters/budgets/drafts retained; bad anchor/inventory/removal/replacement/parent/rollback/tamper/offline held');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));fs.rmSync(dir,{recursive:true,force:true});});
