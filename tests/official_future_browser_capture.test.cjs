'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../scripts/official_result_browser_capture.cjs');
const NOW=new Date('2030-01-15T00:00:00Z');
const auto={sport:'autorace',race_id:'autorace:2030-01-15:isesaki:1',ui_entry_url:'https://autorace.jp/race_info/Live/isesaki',expected_date:'2030-01-15',venue:'isesaki',race_no:1,cutoff_at:'2030-01-15T10:58:00+09:00'};
const kei={sport:'keirin',race_id:'keirin:2030-01-15:keirin-jyo-48:2',ui_entry_url:'https://keirin.jp/pc/top',expected_date:'2030-01-15',venue:'keirin-jyo-48',ui_venue_name:'創作競輪場',race_no:2,cutoff_at:'2030-01-15T11:50:00+09:00'};
const plan=cases=>({schema:'RACE_AI_OFFICIAL_FUTURE_BROWSER_PLAN_V1',intent:'CAPTURE_FRESH_NATIVE_FUTURE_CARDS',available_after:'2030-01-14T23:59:00Z',cases});

test('future intent requires today, baseline availability and a full ten minute cutoff margin',()=>{
 assert.equal(typeof api.validateFuturePlan,'function','future plan validation is missing');
 const input=plan([auto,kei]),before=structuredClone(input);assert.deepEqual(api.validateFuturePlan(input,NOW),input);assert.deepEqual(input,before);
 for(const change of [{intent:'COLLECT_RESULTS'},{available_after:'2030-01-15T00:00:00.000001Z'},{available_after:'2030-01-15T00:00:01Z'},
  {cases:[{...auto,expected_date:'2030-01-16',race_id:auto.race_id.replace('2030-01-15','2030-01-16'),cutoff_at:'2030-01-16T10:58:00+09:00'}]},
  {cases:[{...auto,cutoff_at:'2030-01-15T09:10:00+09:00'}]},{request_budget:33},{dynamic_cache:[]}]){
  assert.throws(()=>api.validateFuturePlan({...input,...change},NOW));
 }
 assert.throws(()=>api.validatePlan(input,NOW),/PLAN_SCHEMA/,'result mode must not accept the new intent');
});

test('optional future authorization expiry is strict and remains active after plan validation',()=>{
 const input={...plan([auto]),not_after:'2030-01-15T00:00:01Z'},before=structuredClone(input);
 assert.deepEqual(api.validateFuturePlan(input,NOW),input);assert.deepEqual(input,before);
 api.requireFutureClock(input,new Date('2030-01-15T00:00:00.999Z'));
 for(const clock of ['2030-01-15T00:00:01Z','2030-01-15T00:00:01.001Z']){
  assert.throws(()=>api.requireFutureClock(input,new Date(clock)),/CLOCK_AUTHORIZATION_EXPIRED/);
 }
 for(const not_after of ['2030-01-15T00:00:00Z','2030-01-15T00:00:00',null,0]){
  assert.throws(()=>api.validateFuturePlan({...input,not_after},NOW));
 }
 api.requireFutureClock(plan([auto]),new Date('2030-01-15T00:00:02Z'));
});

test('future route restriction keeps result transport out without changing result policy',()=>{
 assert.equal(typeof api.futureRoutePolicy,'function','future route restriction is missing');
 const request={url:'https://autorace.jp/race_info/Program',method:'POST',resource_type:'xhr',content_type:'application/json',headers:{},body:Buffer.from('{"placeCode":3,"raceDate":"2030-01-15","raceNo":1}')};
 assert.equal(api.futureRoutePolicy(request,plan([auto])).allow,true);
 for(const endpoint of ['RaceResult','RaceRefund']){const r={...request,url:'https://autorace.jp/race_info/'+endpoint};assert.equal(api.futureRoutePolicy(r,plan([auto])).allow,false);assert.equal(api.routePolicy(r,{cases:[auto]}).allow,true);}
 const result={url:'https://keirin.jp/pc/racelist',method:'POST',resource_type:'document',content_type:'application/x-www-form-urlencoded',headers:{},body:Buffer.from('disp=PJ0306&encp=published-ui')};
 assert.equal(api.futureRoutePolicy(result,plan([kei])).allow,false);assert.equal(api.routePolicy(result,{cases:[kei]}).allow,true);
});

function autoPage(){
 const calls=[];let complete=false;
 const request={url:()=> 'https://autorace.jp/race_info/OtherRaceInfo',method:()=> 'POST',resourceType:()=> 'xhr',postDataBuffer:()=>Buffer.from('{"placeCode":3,"raceDate":"2030-01-15","raceNo":1}'),headers:()=>({'content-type':'application/json'})};
 const response={request:()=>request,url:()=>request.url(),status:()=>200,finished:async()=>{complete=true;}};
 const page={url:()=>auto.ui_entry_url+'/Program/2030-01-15_12/program',waitForResponse:async predicate=>{assert.equal(predicate(response),true);return response;},waitForLoadState:async()=>{},locator(selector){
  const race=selector.includes('data-raceno'),date=selector.includes('data-period-date');
  const node={count:async()=>1,isVisible:async()=>true,waitFor:async()=>{},getAttribute:async k=>k==='class'?'liveTabMenu__item--current':'2030-01-15',innerText:async()=>race?'1R':date?'初日':'レース結果',click:async()=>calls.push(race?'race':date?'date':'result'),last:()=>node};return node;
 }};return {page,calls,complete:()=>complete};
}
test('shared Program selection completes target identity without selecting Result',async()=>{
 assert.equal(typeof api.selectAutoProgram,'function','shared Program selector is missing');
 const f=autoPage();await api.selectAutoProgram(f.page,auto,[]);assert.deepEqual(f.calls,['race']);assert.equal(f.complete(),true);
 const old=autoPage();await api.selectAutoCase(old.page,auto,[]);assert.deepEqual(old.calls,['race','result']);
});

test('normal KEIRIN future detail never selects result list or result tab',async()=>{
 assert.equal(typeof api.selectKeirinCard,'function','normal card selector is missing');
 const calls=[];const page={url:()=> 'https://keirin.jp/pc/racelist',on(){},off(){},waitForTimeout:async()=>{},waitForLoadState:async()=>{},locator(selector){
  const node={inputValue:async()=>selector==='#hhSelK'?'20300115':'48',innerText:async()=>selector==='#hhLblRaceDtl'?'2R S級一般':selector==='#hhRaceBtn2'?'2R':'結果一覧',count:async()=>1,isVisible:async()=>true,click:async()=>calls.push(selector)};return node;
 }};
 await api.selectKeirinCard(page,kei,[],{onListReady:async()=>calls.push('selected-list-ready')});assert.deepEqual(calls,['selected-list-ready','#hhRaceBtn2']);
});

test('future roles select actual Program and companion HTML, never a result substitute',()=>{
 assert.equal(typeof api.futureCaseResponses,'function','future source roles are missing');
 const entries=[['OtherRaceInfo',1],['Program',2],['RaceResult',3]].map(([endpoint,sequence])=>({sequence,url:'https://autorace.jp/race_info/'+endpoint,method:'POST',status:200,request_identity:{placeCode:3,raceDate:auto.expected_date,raceNo:1}}));
 assert.deepEqual(api.futureCaseResponses(auto,entries),[{role:'identity',sequence:1},{role:'program',sequence:2}]);
 const listing={sequence:1,url:'https://keirin.jp/pc/racelist',method:'POST',resource_type:'document',status:200};
 const detail={...listing,sequence:3,url:'https://keirin.jp/pc/racelive'};
 assert.deepEqual(api.futureCaseResponses(kei,[listing,{...detail,sequence:2},detail],2),[{role:'racelist',sequence:1},{role:'racelive',sequence:3}]);
});

test('future expiry reached during request spacing prevents a second actual wire',async()=>{
 const {EventEmitter}=require('node:events'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'future-expiry-')),OriginalDate=Date,started=performance.now();
 global.Date=class extends OriginalDate{constructor(...args){super(...(args.length?args:[NOW.valueOf()+performance.now()-started]));}static now(){return NOW.valueOf()+performance.now()-started;}};
 let handler,firstWire=false,secondWire=false,contextClosed=false;
 const page={goto:async()=>{
  await perform(auto.ui_entry_url,()=>{firstWire=true;});
  await perform('https://autorace.jp/race_info/important_notice',()=>{secondWire=true;});
 },close:async()=>{}};
 const context=new EventEmitter();Object.assign(context,{setDefaultTimeout(){},routeWebSocket:async()=>{},newCDPSession:async()=>({send:async()=>{},on(){}}),route:async(_,fn)=>{handler=fn;},newPage:async()=>page,close:async()=>{contextClosed=true;}});
 async function perform(url,onWire){
  const document=url===auto.ui_entry_url,req={url:()=>url,method:()=> 'GET',resourceType:()=>document?'document':'xhr',postDataBuffer:()=>null,headers:()=>({})};
  const response={request:()=>req,status:()=>200,url:()=>url,headers:()=>({'content-type':'text/html'}),body:async()=>Buffer.from('<html>fresh source</html>')};
  await handler({request:()=>req,abort:async()=>{},continue:async()=>{onWire();context.emit('response',response);},fulfill:async()=>assert.fail('no dynamic replay')});
 }
 try{
  const input={...plan([auto]),not_after:new OriginalDate(NOW.valueOf()+500).toISOString()};
  const index=await api.capturePlan(input,path.join(root,'capture'),{executablePath:process.execPath,chromium:{launch:async()=>({newContext:async()=>context,close:async()=>{}})}});
  assert.equal(firstWire,true);assert.equal(secondWire,false);assert.equal(contextClosed,true);
  assert.equal(index.responses.length,1);assert.equal(index.stop_reason,'REQUEST_DISPATCH_FAILED');
  assert.ok(index.cases.every(item=>item.state!=='CAPTURED'));
 }finally{global.Date=OriginalDate;fs.rmSync(root,{recursive:true,force:true});}
});

test('KEIRIN date selection binds its exact current listing instead of conflicting with a prior date',()=>{
 const row=(sequence,hash)=>({sequence,url:'https://keirin.jp/pc/racelist',method:'POST',resource_type:'document',status:200,
  source_sha256:hash.repeat(64),byte_count:10,request_body_sha256:'c'.repeat(64),request_content_type:'application/x-www-form-urlencoded',
  request_started_at:'2030-01-15T00:00:01Z',response_received_at:'2030-01-15T00:00:02Z'});
 const entries=[row(1,'a'),row(2,'b'),{...row(3,'d'),url:'https://keirin.jp/pc/racelive'}];
 assert.deepEqual(api.futureCaseResponses(kei,entries,2,{listingSequence:2}),[{role:'racelist',sequence:2},{role:'racelive',sequence:3}]);
});

test('future capture retains fully drained fresh Program sources and typed original provenance',async()=>{
 const {EventEmitter}=require('node:events'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'future-card-flow-')),OriginalDate=Date,started=performance.now();
 global.Date=class extends OriginalDate{constructor(...args){super(...(args.length?args:[NOW.valueOf()+performance.now()-started]));}static now(){return NOW.valueOf()+performance.now()-started;}};
 let handler,launchOptions,complete=false,contextClosed=false;const requested=[];
 class Page extends EventEmitter{
  url(){return auto.ui_entry_url+'/Program/2030-01-15_1/program';}
  waitForResponse(predicate){return new Promise(resolve=>{const listener=response=>{if(predicate(response)){this.off('response',listener);resolve(response);}};this.on('response',listener);});}
  async waitForLoadState(){}async waitForTimeout(){await new Promise(resolve=>setTimeout(resolve,5));}async close(){}
  async goto(){await perform(auto.ui_entry_url,'GET','document',Buffer.alloc(0),Buffer.from('<html>fresh bootstrap</html>'));}
  locator(selector){const race=selector.includes('data-raceno'),date=selector.includes('data-period-date');const node={count:async()=>1,isVisible:async()=>true,waitFor:async()=>{},getAttribute:async k=>k==='class'?'liveTabMenu__item--current':'2030-01-15',innerText:async()=>race?'1R':date?'初日':'レース結果',last:()=>node,click:async()=>{
   assert.ok(race,'future mode must never click Result');
   const body=Buffer.from('{"placeCode":3,"raceDate":"2030-01-15","raceNo":1}');
   await perform('https://autorace.jp/race_info/Program','POST','xhr',body,Buffer.from('{"fresh":"program"}'),true);
   await perform('https://autorace.jp/race_info/OtherRaceInfo','POST','xhr',body,Buffer.from('{"fresh":"identity"}'));
  }};return node;}
  async content(){assert.equal(complete,true,'DOM cannot precede completed Program body');return '<html>fresh rendered Program</html>';}
 }
 const page=new Page(),context=new EventEmitter();Object.assign(context,{setDefaultTimeout(){},routeWebSocket:async()=>{},newCDPSession:async()=>({send:async()=>{},on(){}}),route:async(_,fn)=>{handler=fn;},newPage:async()=>page,close:async()=>{contextClosed=true;}});
 async function perform(url,method,type,body,raw,delayed=false){
  requested.push(url);const req={url:()=>url,method:()=>method,resourceType:()=>type,postDataBuffer:()=>body,headers:()=>({'content-type':'application/json'})};
  const response={request:()=>req,status:()=>200,url:()=>url,headers:()=>({'content-type':type==='document'?'text/html':'application/json'}),finished:async()=>{},body:async()=>{if(delayed){await new Promise(resolve=>setTimeout(resolve,30));complete=true;}return raw;}};
  await handler({request:()=>req,abort:async()=>assert.fail('expected fresh normal UI read'),continue:async()=>{context.emit('response',response);page.emit('response',response);},fulfill:async()=>assert.fail('dynamic sources cannot be replayed')});
 }
 try{
  const index=await api.capturePlan(plan([auto]),path.join(root,'capture'),{executablePath:process.execPath,chromium:{launch:async opts=>{launchOptions=opts;return {newContext:async()=>context,close:async()=>{}};}}});
  assert.equal(index.schema,'RACE_AI_OFFICIAL_FUTURE_BROWSER_CAPTURE_V1');assert.equal(index.intent,'CAPTURE_FRESH_NATIVE_FUTURE_CARDS');assert.equal(index.available_after,plan([auto]).available_after);
  assert.equal(index.actual_request_count,3);assert.equal(index.cases[0].state,'CAPTURED');assert.deepEqual(index.cases[0].responses.map(r=>r.role),['identity','program']);assert.equal(index.stop_reason,'FINISHED');
  assert.equal(index.native_contracts_verified,false);assert.equal(index.independent_pre_cutoff_receipt_verified,false);
  const metadata=index.cases[0].browser_metadata;assert.equal(metadata.ui_capture_kind,'NORMAL_BROWSER_UI');assert.equal(metadata.scope,'OPERATOR_SUPPLIED_RESEARCH');assert.equal(metadata.final_url,page.url());assert.equal(metadata.stopped_host,false);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(root,'capture','case-01/browser.metadata.json'))),metadata);
  assert.equal(metadata.ledger.filter(r=>r.sequence).length,3);assert.equal(contextClosed,true);assert.equal(launchOptions.env.RACE_AI_STATE_KEY,undefined);
  assert.ok(requested.every(url=>!url.includes('RaceResult')));
  const program=index.responses.find(r=>r.url.endsWith('/Program'));assert.deepEqual(fs.readFileSync(path.join(root,'capture',program.body_file)),Buffer.from('{"fresh":"program"}'));
 }finally{global.Date=OriginalDate;fs.rmSync(root,{recursive:true,force:true});}
});

test('future KEIRIN capture binds the newly selected normal list before its detail click',async()=>{
 const {EventEmitter}=require('node:events'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'future-keirin-flow-')),OriginalDate=Date,started=performance.now();
 global.Date=class extends OriginalDate{constructor(...args){super(...(args.length?args:[NOW.valueOf()+performance.now()-started]));}static now(){return NOW.valueOf()+performance.now()-started;}};
 let handler,current=kei.ui_entry_url,selectedDate='20300114';const labels=[];
 class Page extends EventEmitter{
  url(){return current;}async waitForLoadState(){}async waitForTimeout(ms){await new Promise(resolve=>setTimeout(resolve,Math.min(ms,5)));}async close(){}
  async goto(){await perform(kei.ui_entry_url,'GET','document',Buffer.alloc(0),Buffer.from('<html>fresh top</html>'));}
  locator(selector){
   const node={count:async()=>1,isVisible:async()=>true,waitFor:async()=>{},filter:()=>node,
    inputValue:async()=>selector==='#hhSelK'?selectedDate:'48',getByRole:()=>this.locator('list-button'),
    innerText:async()=>selector==='list-button'?'出走表一覧':selector.includes('hhlnkRaceDate')?'1/15':selector==='#hhRaceBtn2'?'2R':selector==='#hhLblRaceDtl'?'2R S級一般':'結果一覧',
    click:async()=>{
     labels.push(await node.innerText());
     if(selector==='list-button'||selector.includes('hhlnkRaceDate')){
      current='https://keirin.jp/pc/racelist';if(selector.includes('hhlnkRaceDate'))selectedDate='20300115';
      await perform(current,'POST','document',Buffer.from('disp=PJ0305&encp=normal-list-'+selectedDate),Buffer.from('<html>published list '+selectedDate+'</html>'));
     }else if(selector==='#hhRaceBtn2'){
      current='https://keirin.jp/pc/racelive';await perform(current,'POST','document',Buffer.from('disp=PJ0315&encp=normal-detail'),Buffer.from('<html>published detail</html>'));
     }else assert.fail('unexpected future UI control');
    }};return node;
  }
  async content(){return '<html>rendered published detail</html>';}
 }
 const page=new Page(),context=new EventEmitter();Object.assign(context,{setDefaultTimeout(){},routeWebSocket:async()=>{},newCDPSession:async()=>({send:async()=>{},on(){}}),route:async(_,fn)=>{handler=fn;},newPage:async()=>page,close:async()=>{}});
 async function perform(url,method,type,body,raw){
  const req={url:()=>url,method:()=>method,resourceType:()=>type,postDataBuffer:()=>body,headers:()=>({'content-type':'application/x-www-form-urlencoded'})};
  const response={request:()=>req,status:()=>200,url:()=>url,headers:()=>({'content-type':'text/html;charset=UTF-8'}),body:async()=>raw};
  await handler({request:()=>req,abort:async()=>assert.fail('expected normal published UI'),continue:async()=>context.emit('response',response),fulfill:async()=>assert.fail('no dynamic replay')});
 }
 try{
  const index=await api.capturePlan(plan([kei]),path.join(root,'capture'),{executablePath:process.execPath,chromium:{launch:async()=>({newContext:async()=>context,close:async()=>{}})}});
  assert.equal(index.cases[0].state,'CAPTURED');assert.deepEqual(labels,['出走表一覧','1/15','2R']);
  assert.deepEqual(index.cases[0].responses,[{role:'racelist',sequence:3},{role:'racelive',sequence:4}]);
  const source=index.responses.find(row=>row.sequence===3);assert.match(fs.readFileSync(path.join(root,'capture',source.body_file),'utf8'),/20300115/);
 }finally{global.Date=OriginalDate;fs.rmSync(root,{recursive:true,force:true});}
});
