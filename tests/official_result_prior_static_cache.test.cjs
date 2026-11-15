'use strict';
// Invented response bodies and a mock Playwright wire; no browser or HTTP.
const test=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const api=require('../scripts/official_result_browser_capture.cjs');

const item={sport:'autorace',race_id:'autorace:2020-01-01:isesaki:1',
 ui_entry_url:'https://autorace.jp/race_info/Live/isesaki',expected_date:'2020-01-01',
 venue:'isesaki',race_no:1,due_at:'2020-01-01T11:30:00+09:00'};
const cssUrls=['https://autorace.jp/content/assets/css/app.css?20200101',
 'https://autorace.jp/content/assets/css/style.css?20200101',
 'https://autorace.jp/content/assets/css/videojs/video-js.css'];
const notices=['https://autorace.jp/race_info/important_notice',
 'https://autorace.jp/race_info/XML/Hold/Today',
 'https://autorace.jp/data/notice/all-01.json',
 'https://autorace.jp/data/notice/info-01.json'];
const postBody=Buffer.from(JSON.stringify({placeCode:3,raceDate:item.expected_date,raceNo:1}));

function staticEntries(){return cssUrls.map((url,index)=>{
 const raw=Buffer.from('/* invented stylesheet '+index+' */ body { color: black; }');
 return {raw_base64:raw.toString('base64'),metadata:{source_url:url,final_url:url,
  status:200,byte_count:raw.length,source_sha256:api.sha(raw),http_method:'GET',method:'GET',
  resource_type:'stylesheet',headers:{'Content-Type':'text/css; charset=UTF-8'},
  fetched_at:'2020-01-01T00:00:00Z',response_received_at:'2020-01-01T00:00:01Z'}};
});}

async function capture(withCache,{lateRead=false,closeRead=false,capDelay=false}={}){
 const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'prior-static-wire-'));
 const out=path.join(temporary,'capture');
 const entries=staticEntries(),before=structuredClone(entries),requests=[],fulfilled=[];
 let handler,closed=false,lateTask,closingTask,delayedTask;
 const context=new EventEmitter();
 async function perform(url,method,type,body,raw){
  const record={url,method,type,body:Buffer.from(body),continued:false,aborted:false};requests.push(record);
  const req={url:()=>url,method:()=>method,resourceType:()=>type,postDataBuffer:()=>body,
   headers:()=>({'content-type':'application/json'})};
  const mime=type==='document'?'text/html':type==='stylesheet'?'text/css':'application/json';
  const response={request:()=>req,status:()=>200,url:()=>url,
   headers:()=>({'content-type':mime}),body:async()=>{if(lateRead&&record.sequence===9)await new Promise(resolve=>setTimeout(resolve,25));return raw;},finished:async()=>{}};
  await handler({request:()=>req,abort:async()=>{record.aborted=true;},
   continue:async()=>{
    record.continued=true;record.reserved_after_close=closed;record.sequence=req._officialCapture.sequence;
    const checkpoint=JSON.parse(fs.readFileSync(path.join(out,'request-ledger-'+String(record.sequence).padStart(3,'0')+'.json')));
    assert.equal(checkpoint.actual_request_count,record.sequence);
    const emit=()=>{context.emit('response',response);context.emit('page-response',response);};
    if(capDelay&&record.sequence===5)delayedTask=new Promise(resolve=>setTimeout(()=>{if(!closed)emit();resolve();},1600));else emit();
   },fulfill:async options=>{
    assert.equal(type,'stylesheet');assert.equal(method,'GET');
    assert.equal(req._officialCapture,undefined,'cache hit must precede reservation and numbered ledger');
    const saved=entries.find(entry=>entry.metadata.source_url===url);
    assert.ok(saved);assert.equal(options.status,200);
    assert.equal(options.contentType,'text/css; charset=UTF-8');
    assert.deepEqual(options.body,Buffer.from(saved.raw_base64,'base64'));
    fulfilled.push(url);
   }});
 }
 class Page extends EventEmitter{
  url(){return item.ui_entry_url;}
  waitForResponse(predicate,options){assert.equal(options.timeout,12000);return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{context.off('page-response',check);reject(Error('fixture identity wait timeout'));},3000);const check=response=>{if(predicate(response)){clearTimeout(timer);context.off('page-response',check);resolve(response);}};context.on('page-response',check);});}
  async waitForLoadState(){}async waitForTimeout(ms){await new Promise(resolve=>setTimeout(resolve,Math.min(ms,5)));}
  async close(){}
  async goto(){
   await perform(item.ui_entry_url,'GET','document',Buffer.alloc(0),Buffer.from('<html>invented index</html>'));
   for(let index=0;index<cssUrls.length;index++)await perform(cssUrls[index],'GET','stylesheet',Buffer.alloc(0),Buffer.from(entries[index].raw_base64,'base64'));
   for(const url of (capDelay?[]:notices))await perform(url,'GET','xhr',Buffer.alloc(0),Buffer.from('{"invented_notice":true}'));
  }
  locator(selector){
   const race=selector.includes('data-raceno'),result=selector.includes('data-main-menu');
   const label=result?'レース結果':race?'1R':'初日';
   const locator={count:async()=>1,isVisible:async()=>true,waitFor:async()=>{},innerText:async()=>label,
    click:async()=>{
     const endpoints=race?['OtherRaceInfo']:result?['RaceResult','RaceRefund']:[];
     for(const endpoint of endpoints)await perform('https://autorace.jp/race_info/'+endpoint,'POST','xhr',postBody,
      Buffer.from(JSON.stringify({invented_source:true,endpoint})));
    },last:()=>locator};return locator;
  }
  async content(){if((lateRead||capDelay)&&!lateTask){const read=()=>perform('https://autorace.jp/race_info/OtherRaceInfo','POST','xhr',postBody,Buffer.from(JSON.stringify({invented_source:true,endpoint:'OtherRaceInfo'})));lateTask=capDelay?Promise.all([read(),read()]):read();}return '<html>invented transport fixture; no result teacher</html>';}
 }
 Object.assign(context,{setDefaultTimeout(){},routeWebSocket:async()=>{},
  newCDPSession:async()=>({send:async()=>{},on(){}}),route:async(_,callback)=>{handler=callback;},
  newPage:async()=>new Page(),close:async()=>{closed=true;if(closeRead&&!closingTask)closingTask=perform('https://autorace.jp/race_info/OtherRaceInfo','POST','xhr',postBody,Buffer.from('{}'));if(closingTask)await closingTask;}});
 const plan={schema:api.SCHEMA,cases:[structuredClone(item)],request_budget:capDelay?5:lateRead?10:8,
  ...(withCache?{static_cache:entries}:{})};
 const original=structuredClone(plan);
 try{
  if(withCache)assert.equal(api.validateStaticCache(entries,plan).size,3);
  const index=await api.capturePlan(plan,out,{executablePath:process.execPath,
   chromium:{launch:async()=>({newContext:async()=>context,close:async()=>{}})}});
  if(lateTask)await lateTask;if(delayedTask)await delayedTask;
  assert.equal(closed,true);assert.deepEqual(entries,before);assert.deepEqual(plan,original);
  const files=Object.fromEntries(fs.readdirSync(out).filter(name=>fs.statSync(path.join(out,name)).isFile())
   .map(name=>[name,fs.readFileSync(path.join(out,name))]));
  return {index,requests,fulfilled,entries,files};
 }finally{fs.rmSync(temporary,{recursive:true,force:true});}
}

test('uncached normal UI spends its unchanged eight requests before result sources',{timeout:20000},async()=>{
 const {index,requests,fulfilled}=await capture(false);
 assert.equal(index.maximum_requests,8);assert.equal(index.actual_request_count,8);
 assert.equal(index.stop_reason,'REQUEST_LIMIT');assert.equal(index.stopped_host,false);
 assert.deepEqual(fulfilled,[]);
 assert.deepEqual(requests.filter(request=>request.continued).map(request=>request.type),
  ['document','stylesheet','stylesheet','stylesheet','xhr','xhr','xhr','xhr']);
 assert.deepEqual(index.ledger.filter(row=>Number.isInteger(row.sequence)).map(row=>row.sequence),[1,2,3,4,5,6,7,8]);
 assert.equal(requests.filter(request=>request.method==='POST'&&request.continued).length,0);
 assert.equal(requests.filter(request=>request.method==='POST'&&request.aborted).length,1);
 assert.equal(index.responses.some(row=>row.url.endsWith('/RaceResult')),false);
 assert.notEqual(index.cases[0].state,'CAPTURED');assert.equal(index.formal_learning_or_pdca_claim,false);
});

test('three validated prior CSS bodies replay with zero dispatches and free three normal read slots',{timeout:20000},async()=>{
 const {index,requests,fulfilled,entries,files}=await capture(true);
 assert.equal(index.maximum_requests,8);assert.equal(index.actual_request_count,8);
 assert.equal(index.stop_reason,'FINISHED');assert.equal(index.stopped_host,false);
 assert.deepEqual(fulfilled,cssUrls);
 const styles=requests.filter(request=>request.type==='stylesheet');
 assert.equal(styles.length,3);assert.ok(styles.every(request=>!request.continued&&!request.aborted));
 assert.equal(index.responses.filter(row=>row.resource_type==='stylesheet').length,0);
 const replays=index.ledger.filter(row=>row.event==='STATIC_CACHE_REPLAY');
 assert.deepEqual(replays.map(row=>row.url),cssUrls);
 for(const replay of replays){
  const original=entries.find(entry=>entry.metadata.source_url===replay.url).metadata;
  assert.equal(replay.source_sha256,original.source_sha256);
  assert.equal(replay.original_captured_at,original.response_received_at);
  assert.equal(replay.sequence,undefined);
 }
 const posted=requests.filter(request=>request.method==='POST');
 assert.deepEqual(posted.map(request=>request.url.split('/').pop()),['OtherRaceInfo','RaceResult','RaceRefund']);
 assert.ok(posted.every(request=>request.continued&&!request.aborted));
 assert.deepEqual(posted.map(request=>request.sequence),[6,7,8]);
 assert.ok(posted.every(request=>request.body.equals(postBody)));
 for(const row of index.responses.filter(row=>row.method==='POST')){
  assert.deepEqual(files[row.request_body_file],postBody);assert.equal(api.sha(files[row.request_body_file]),row.request_body_sha256);
  assert.deepEqual(JSON.parse(files[row.request_body_file]),{placeCode:3,raceDate:item.expected_date,raceNo:1});
 }
 assert.equal(index.cases[0].state,'CAPTURED');
 assert.deepEqual(index.cases[0].responses.map(row=>row.role),['identity','result','result_companion']);
 assert.equal(index.normal_ui_only,true);assert.equal(index.manual_api_requests,0);
 assert.equal(index.formal_learning_or_pdca_claim,false);
});


test('queued normal reads finish before context closes and the final index is immutable',{timeout:20000},async()=>{
 const {index,requests,files}=await capture(true,{lateRead:true,closeRead:true});
 assert.equal(index.actual_request_count,9,'late queued read must be settled before index count');
 assert.equal(index.stop_reason,'FINISHED');assert.equal(index.cases[0].state,'CAPTURED');
 const sent=requests.filter(row=>row.continued);
 assert.equal(sent.length,9);assert.ok(sent.every(row=>!row.reserved_after_close),'no queued reservation after context close');
 const numbered=index.ledger.filter(row=>Number.isInteger(row.sequence));
 assert.equal(numbered.length,9);assert.equal(index.responses.length,9);
 for(const row of numbered){
  assert.equal(row.status,200);assert.ok(row.body_captured_at);
  assert.ok(files[row.body_file]);assert.ok(files[row.metadata_file]);
 }
 const stored=JSON.parse(files['capture-index.json']);assert.deepEqual(stored,index,'no ledger mutations after index serialization');
 assert.equal(index.cases[0].browser_metadata.ledger.filter(row=>Number.isInteger(row.sequence)).length,9);
 const extra=requests.at(-1);assert.equal(extra.aborted,true);assert.equal(extra.continued,false);
 assert.equal(extra.sequence,undefined);
 assert.equal(Object.keys(files).some(name=>name.startsWith('request-010')||name.startsWith('response-010')),false);
 assert.ok(index.ledger.some(row=>row.event==='BLOCKED_REQUEST'&&row.reason==='CAPTURE_FINALIZING'));
});


test('request cap stops queued reads while preserving a previously dispatched delayed response',{timeout:20000},async()=>{
 const {index,requests,files}=await capture(true,{capDelay:true});
 assert.equal(index.actual_request_count,5);assert.equal(index.maximum_requests,5);assert.equal(index.stop_reason,'REQUEST_LIMIT');
 assert.equal(index.responses.length,5,'last permitted wire response must finish even after the next read hits cap');
 const last=index.ledger.find(row=>row.sequence===5);assert.equal(last.status,200);assert.ok(last.body_captured_at);
 assert.ok(files[last.body_file]);assert.ok(files[last.metadata_file]);
 const sent=requests.filter(row=>row.continued);assert.equal(sent.length,5);assert.ok(sent.every(row=>!row.reserved_after_close));
 const extra=requests.at(-1);assert.equal(extra.aborted,true);assert.equal(extra.continued,false);assert.equal(extra.sequence,undefined);
 assert.deepEqual(JSON.parse(files['capture-index.json']),index);assert.equal(index.formal_learning_or_pdca_claim,false);
});
