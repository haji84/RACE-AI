'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),{EventEmitter}=require('node:events');
const api=require('../scripts/official_result_browser_capture.cjs');
const item={sport:'autorace',race_id:'autorace:2020-01-01:isesaki:2',ui_entry_url:'https://autorace.jp/race_info/Live/isesaki',expected_date:'2020-01-01',venue:'isesaki',race_no:2,due_at:'2020-01-01T11:30:00+09:00'};
const plan={schema:api.SCHEMA,cases:[item],request_budget:16};
const csv='https://autorace.jp/data/refund/20200101-isesaki-02R-refund.csv';
const reason='OFFICIAL_BROWSER_UNNEEDED_AUTO_REFUND_CSV';
const request=(url=csv,extra={})=>({url,method:'GET',resource_type:'xhr',headers:{},...extra});

test('only the literal scoped AUTO result-case ancillary refund CSV is filtered before reservation',()=>{
 const original=structuredClone(plan),req=request();
 assert.deepEqual(api.routePolicy(req,plan),{allow:false,reason});
 assert.deepEqual(api.routePolicy(request(csv,{resource_type:'fetch'}),plan),{allow:false,reason});
 assert.deepEqual(plan,original);assert.deepEqual(req,request());
 // Both approved official aliases are already host-validated; no other host is admitted.
 assert.equal(api.routePolicy(request(csv.replace('https://autorace.jp','https://www.autorace.jp')),plan).reason,reason);
});

test('the filter cannot disguise other cases, queries, credentials, methods, intents or source denials',()=>{
 for(const url of [csv.replace('02R','01R'),csv.replace('20200101','20200102'),csv.replace('isesaki','kawaguchi'),csv+'?anything=1',csv.replace('02R','%30%32R'),csv.replace('https://autorace.jp','https://other.invalid'),csv+'#fragment',csv.replace('https://','https://user:secret@')]){
  assert.notEqual(api.routePolicy(request(url),plan).reason,reason,url);
 }
 for(const extra of [{method:'POST',body:Buffer.from('{}'),content_type:'application/json'},{resource_type:'document'},{headers:{authorization:'not-a-real-credential'}}])assert.notEqual(api.routePolicy(request(csv,extra),plan).reason,reason);
 assert.equal(api.routePolicy(request(),{cases:[item]}).allow,true);
 assert.equal(api.futureRoutePolicy(request(),{schema:api.FUTURE_SCHEMA,intent:api.FUTURE_INTENT,cases:[item]}).allow,true);
 assert.equal(api.routePolicy(request('https://autorace.jp/data/notice/all-01.json'),plan).allow,true);
 assert.equal(api.routePolicy(request('https://autorace.jp/race_info/XML/Hold/Today'),plan).allow,true);
 const budget=api.createBudget(16);for(const status of [401,403,429]){budget.deny(status);assert.equal(budget.reason,'HTTP_ACCESS_DENIED');}
});

test('SYNTHETIC_ONLY: D1-shaped normal-UI sequence keeps all16 source bodies and DOM without a seventeenth refund request',async()=>{
 // Authored transport simulation, not a replayed R2 teacher. The real UI prefix
 // motivates these counts; every response and driver ID below is synthetic.
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'auto-optional-csv-'));
 const out=path.join(root,'capture'),identity=Buffer.from(JSON.stringify({SYNTHETIC_ONLY:true,drivers:Array.from({length:8},(_,i)=>({car_no:i+1,registration_no:String(900001+i)}))}));
 const result=Buffer.from(JSON.stringify({SYNTHETIC_ONLY:true,normal_order:[1,2,3,4,5,6,7,8],refundInfo:{typeCode:0,typeName:'通常'}}));
 let handler,closed=false,blockedCsv=0;const sent=[];
 const body=raceNo=>Buffer.from(JSON.stringify({placeCode:3,raceDate:item.expected_date,raceNo}));
 class Page extends EventEmitter{
  url(){return item.ui_entry_url;}
  waitForResponse(predicate){return new Promise(resolve=>{const check=response=>{if(predicate(response)){this.off('response',check);resolve(response);}};this.on('response',check);});}
  async waitForLoadState(){}async waitForTimeout(ms){await new Promise(resolve=>setTimeout(resolve,Math.min(ms,5)));}async close(){}
  async goto(){
   await perform(item.ui_entry_url,'GET','document',Buffer.alloc(0),Buffer.from('<html>SYNTHETIC_ONLY index</html>'));
   for(const suffix of ['race_info/important_notice','race_info/XML/Hold/Today','data/notice/all-01.json','data/notice/info-01.json','race_info/XML/Hold/Today','race_info/XML/Hold/Today','race_info/JushouEvent/Amount','race_info/XML/Hold/Today'])await get(suffix);
  }
  locator(selector){const isResult=selector.includes('data-main-menu'),isRace=selector.includes('data-raceno'),label=isResult?'レース結果':isRace?'2R':'初日';
   const loc={count:async()=>1,isVisible:async()=>true,waitFor:async()=>{},innerText:async()=>label,last:()=>loc,click:async()=>{
    if(isRace){await post('OtherRaceInfo',2,identity);await post('Program',2,Buffer.from('{"SYNTHETIC_ONLY":true}'));}
    else if(isResult){await get('race_info/XML/Hold/Today');await post('RaceResult',2,result);await post('OtherRaceInfo',2,identity);await perform(csv,'GET','xhr',Buffer.alloc(0),Buffer.from('SYNTHETIC_ONLY unused CSV'),true);}
    else{await post('OtherRaceInfo',1,identity);await get('race_info/XML/Hold/Today');}
   }};return loc;
  }
  async content(){return '<html>SYNTHETIC_ONLY complete eight-driver result DOM</html>';}
 }
 const page=new Page(),context=new EventEmitter();Object.assign(context,{setDefaultTimeout(){},routeWebSocket:async()=>{},newCDPSession:async()=>({send:async()=>{},on(){}}),route:async(_,fn)=>{handler=fn;},newPage:async()=>page,close:async()=>{closed=true;}});
 const get=suffix=>perform('https://autorace.jp/'+suffix,'GET','xhr',Buffer.alloc(0),Buffer.from('{"SYNTHETIC_ONLY":true}'));
 const post=(endpoint,raceNo,raw)=>perform('https://autorace.jp/race_info/'+endpoint,'POST','xhr',body(raceNo),raw);
 async function perform(url,method,type,rawBody,raw,optional=false){
  const req={url:()=>url,method:()=>method,resourceType:()=>type,postDataBuffer:()=>rawBody,headers:()=>({'content-type':'application/json'})};let aborted=false;
  const response={request:()=>req,status:()=>200,url:()=>url,headers:()=>({'content-type':type==='document'?'text/html':'application/json'}),body:async()=>raw,finished:async()=>{}};
  await handler({request:()=>req,abort:async()=>{aborted=true;if(optional)blockedCsv++;},continue:async()=>{sent.push(url);context.emit('response',response);page.emit('response',response);},fulfill:async()=>{throw Error('no cache expected in authored simulation');}});
  if(!optional)assert.equal(aborted,false);
 }
 try{
  const index=await api.capturePlan(plan,out,{executablePath:process.execPath,chromium:{launch:async()=>({newContext:async()=>context,close:async()=>{}})}});
  assert.equal(index.stop_reason,'FINISHED');assert.equal(index.maximum_requests,16);assert.equal(index.actual_request_count,16);assert.equal(index.responses.length,16);
  assert.equal(index.cases[0].state,'CAPTURED');assert.deepEqual(index.cases[0].responses,[{role:'identity',sequence:12},{role:'result',sequence:15},{role:'program',sequence:13}]);
  assert.equal(blockedCsv,1);assert.equal(sent.includes(csv),false);assert.equal(closed,true);
  assert.equal(index.ledger.filter(row=>row.event==='BLOCKED_REQUEST'&&row.reason===reason).length,1);
  assert.deepEqual(index.ledger.filter(row=>row.event==='NORMAL_SEMANTIC_UI_CLICK').map(row=>row.label),['初日','2R','レース結果']);
  assert.equal(index.formal_learning_or_pdca_claim,false);assert.equal(index.manual_api_requests,0);
  assert.equal(fs.existsSync(path.join(out,'request-ledger-017.json')),false);assert.equal(fs.existsSync(path.join(out,'response-017.body')),false);
  for(const row of index.responses){const raw=fs.readFileSync(path.join(out,row.body_file));assert.equal(api.sha(raw),row.source_sha256);assert.equal(raw.length,row.byte_count);assert.equal(row.status,200);}
  assert.deepEqual(fs.readFileSync(path.join(out,index.responses.find(row=>row.sequence===15).body_file)),result);
  const dom=index.cases[0].rendered_dom;assert.equal(api.sha(fs.readFileSync(path.join(out,dom.file))),dom.source_sha256);
  for(const filename of fs.readdirSync(out)){const info=fs.statSync(path.join(out,filename));assert.equal(info.mode&0o777,info.isDirectory()?0o700:0o600);}
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(out,'capture-index.json'),'utf8')),index);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
