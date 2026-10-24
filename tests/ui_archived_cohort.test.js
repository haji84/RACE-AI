const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {webcrypto}=require('node:crypto');
const cohort=require('../web/archived-cohort.js');
const bytes=fs.readFileSync(require('node:path').join(__dirname,'../web/data/archived-cohort-20261016-ce380fb6.json'));
const now=()=>new Date('2026-11-01T00:00:00Z');
const response=(body=bytes,status=200)=>({ok:status===200,status,arrayBuffer:async()=>body.buffer.slice(body.byteOffset,body.byteOffset+body.byteLength)});

test('historical report retains dates and UNVALIDATED gates on later days',async()=>{
  const report=await cohort.verify(bytes,webcrypto,now());
  const html=cohort.render(report);
  assert.equal(report.race_count,3);assert.equal(report.day_count,2);
  for(const label of ['2026-10-15','2026-10-16','3レース','2日','物理的な展示前後の対：0','未検証','B情報のみ比較元','通常展示反映','オリジナル展示反映','0.986487','4.255679','採用判断'])assert.ok(html.includes(label),label);
  assert.equal((html.match(/data-cohort-model=/g)||[]).length,3);
  assert.ok(html.includes('tabindex="0"'));assert.ok(html.includes('99eef90bd88b5c377cef1e00ee4be81667c11fe9'));
});
test('modified report is rejected even when altered fields look valid',async()=>{
  for(const mutate of [r=>r.race_count++,r=>r.models[0].mean_log_loss=4,r=>r.validation_status='VALIDATED',r=>r.as_of='2026-10-16T02:10:44Z']){
    const r=JSON.parse(bytes);mutate(r);
    await assert.rejects(cohort.verify(Buffer.from(JSON.stringify(r)),webcrypto,now()));
  }
});
test('future audit, oversized body, missing crypto and invalid clock fail closed',async()=>{
  for(const args of [[bytes,webcrypto,new Date('2026-10-16T02:15:00Z')],[Buffer.alloc(256001),webcrypto,now()],[bytes,null,now()],[bytes,webcrypto,new Date('bad')]])await assert.rejects(cohort.verify(...args));
});
function elements(){return {button:{disabled:false,addEventListener(){}},status:{textContent:'',dataset:{}},content:{innerHTML:''}};}
test('button performs only a same-origin bounded GET, preserves historical timestamp',async()=>{
  const els=elements();let calls=[];
  const load=cohort.controller(els,{fetch:async(url,options)=>{calls.push({url,options});return response();},crypto:webcrypto,now});
  await load();
  assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/archived-cohort');
  assert.equal(calls[0].options.method,'GET');assert.equal(calls[0].options.cache,'no-store');
  assert.equal(calls[0].options.redirect,'error');assert.equal(calls[0].options.credentials,'same-origin');
  assert.ok(calls[0].options.signal instanceof AbortSignal);
  assert.equal(els.button.disabled,false);assert.equal(els.status.dataset.state,'success');
  assert.ok(els.content.innerHTML.includes('2026-10-16T02:10:43.089393+00:00'));
});
test('refresh clears old rows immediately and on HTTP or checksum errors',async()=>{
  for(const bad of [()=>response(bytes,503),()=>response(Buffer.from('{}'))]){
    const els=elements();let next=response();let resolve;
    const load=cohort.controller(els,{fetch:()=>new Promise(r=>{resolve=r;}),crypto:webcrypto,now});
    let pending=load();resolve(next);await pending;assert.ok(els.content.innerHTML);
    pending=load();assert.equal(els.content.innerHTML,'');assert.equal(els.button.disabled,true);
    resolve(bad());await pending;assert.equal(els.content.innerHTML,'');assert.equal(els.status.dataset.state,'error');
    assert.equal(els.button.disabled,false);
  }
});
test('duplicate click makes one request; transport abort does not restore stale rows',async()=>{
  const els=elements();let calls=0,reject;
  const load=cohort.controller(els,{fetch:()=>{calls++;return new Promise((_,r)=>{reject=r;});},crypto:webcrypto,now});
  const pending=load();await load();assert.equal(calls,1);
  reject(new Error('AbortError'));await pending;assert.equal(els.content.innerHTML,'');assert.equal(els.button.disabled,false);
});
test('ten second timeout aborts the actual request and clears content',async(t)=>{
  t.mock.timers.enable({apis:['setTimeout']});
  const els=elements();let signal;
  const load=cohort.controller(els,{fetch:(_,options)=>new Promise((resolve,reject)=>{
    signal=options.signal;signal.addEventListener('abort',()=>reject(new Error('aborted')));
  }),crypto:webcrypto,now});
  const pending=load();t.mock.timers.tick(9999);assert.equal(signal.aborted,false);
  t.mock.timers.tick(1);await pending;
  assert.equal(signal.aborted,true);assert.equal(els.content.innerHTML,'');assert.equal(els.status.dataset.state,'error');assert.equal(els.button.disabled,false);
});
test('research markup and mounted click handler expose the read-only flow',async()=>{
  const html=fs.readFileSync(require('node:path').join(__dirname,'../web/index.html'),'utf8');
  const els=elements();let click;
  els.button.addEventListener=(event,handler)=>{assert.equal(event,'click');click=handler;};
  const byId={'archived-cohort-load':els.button,'archived-cohort-status':els.status,'archived-cohort-content':els.content};
  cohort.mount({getElementById:id=>byId[id]});assert.equal(typeof click,'function');
  assert.match(html,/<script src="\.\/archived-cohort.js" defer><\/script>/);
  assert.match(html,/id="archived-cohort-status"[^>]*role="status"[^>]*aria-live="polite"/);
  for(const id of Object.keys(byId))assert.ok(html.includes(`id="${id}"`));
});
