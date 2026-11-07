'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const script=path.resolve(__dirname,'../scripts/official_result_browser_capture.cjs');
test('bounded normal UI capture module exists',()=>assert.ok(fs.existsSync(script),'normal UI capture implementation missing'));
const api=fs.existsSync(script)?require(script):null;
const NOW=new Date('2030-01-01T03:00:00Z');
const auto={sport:'autorace',race_id:'autorace:2030-01-01:isesaki:2',ui_entry_url:'https://autorace.jp/race_info/Live/isesaki',expected_date:'2030-01-01',venue:'isesaki',race_no:2,due_at:'2030-01-01T11:30:00+09:00'};
const keirin={sport:'keirin',race_id:'keirin:2030-01-01:keirin-jyo-48:2',ui_entry_url:'https://keirin.jp/pc/top',expected_date:'2030-01-01',venue:'keirin-jyo-48',ui_venue_name:'創作競輪場',race_no:2,due_at:'2030-01-01T11:30:00+09:00'};
const plan=cases=>({schema:'RACE_AI_OFFICIAL_RESULT_BROWSER_PLAN_V1',cases});
const enabled={skip:!api};
test('plan binds native case identity and selects only due cases without inventing times',enabled,()=>{
 const input=plan([auto,{...keirin,due_at:'2030-01-01T13:00:00+09:00'}]);const before=structuredClone(input);
 assert.equal(api.validatePlan(input,NOW).cases.length,2);assert.deepEqual(api.dueCases(input,NOW),[auto]);assert.deepEqual(input,before);
 for(const change of [{race_id:auto.race_id.replace(':2',':3')},{ui_entry_url:'https://autorace.jp.evil.invalid/race_info/Live/isesaki'},{ui_entry_url:'https://user:password@autorace.jp/race_info/Live/isesaki'},{due_at:'2030-01-01T11:30:00'},{expected_date:'2030-02-31'},{race_no:true}])assert.throws(()=>api.validatePlan(plan([{...auto,...change}]),NOW));
 assert.throws(()=>api.validatePlan(plan([auto,auto]),NOW));assert.throws(()=>api.validatePlan({...plan([auto]),request_budget:33},NOW));
 assert.throws(()=>api.validatePlan({...plan([auto]),not_before:'2030-01-01T03:00:00.000001Z'},NOW));
 assert.equal(api.validatePlan({...plan([auto]),not_before:NOW.toISOString()},NOW).not_before,NOW.toISOString());
});
test('one official UI day accepts all twelve races while network budget remains thirty-two',enabled,()=>{
 const races=(base,count)=>Array.from({length:count},(_,i)=>({...base,race_no:i+1,race_id:`${base.sport}:${base.expected_date}:${base.venue}:${i+1}`}));
 const old=plan(races(auto,8));assert.equal(api.validatePlan(old,NOW).cases.length,8);
 const full={...plan([...races(auto,12),...races(keirin,11)]),request_budget:32};const before=structuredClone(full);
 assert.equal(api.validatePlan(full,NOW).cases.length,23);assert.deepEqual(full,before);
 assert.equal(api.validatePlan(plan(races(keirin,12)),NOW).cases.length,12);
 assert.throws(()=>api.validatePlan(plan(races(auto,13)),NOW));
 assert.throws(()=>api.validatePlan(plan(races(keirin,13)),NOW),/CASE_CLOCK_OR_NUMBER/);
 assert.throws(()=>api.validatePlan({...full,request_budget:33},NOW),/REQUEST_BUDGET/);
});
test('two KEIRIN venues sharing top URL get independent twelve-race limits and UI contexts',enabled,async()=>{
 const other={...keirin,venue:'keirin-jyo-74',race_id:keirin.race_id.replace('keirin-jyo-48','keirin-jyo-74'),ui_venue_name:'別創作競輪場'};
 const races=(base,count)=>Array.from({length:count},(_,i)=>({...base,race_no:i+1,race_id:`${base.sport}:${base.expected_date}:${base.venue}:${i+1}`}));
 for(const count of [11,12])assert.equal(api.validatePlan({...plan([...races(keirin,12),...races(other,count)]),request_budget:32},NOW).cases.length,12+count);
 const input=[...races(keirin,12),...races(other,11)],before=structuredClone(input),groups=[...api.groupCases(input).values()];
 assert.equal(groups.length,2);assert.deepEqual(groups.map(g=>[g[0].venue,g.length]),[['keirin-jyo-48',12],['keirin-jyo-74',11]]);assert.deepEqual(input,before);
 const opened=[];const names=[keirin.ui_venue_name,other.ui_venue_name];
 const page={url:()=>keirin.ui_entry_url,on(){},off(){},waitForTimeout:async()=>{},waitForLoadState:async()=>{},locator(selector){
  if(selector==='.kaisaichi')return {filter:({hasText})=>({venue:names.find(n=>hasText.test(n))})};
  assert.equal(selector,'#kaisaiInfoTable tr');return {filter:({has})=>({waitFor:async()=>{},getByRole:()=>({count:async()=>1,isVisible:async()=>true,innerText:async()=>'出走表一覧',click:async()=>{opened.push(has.venue);}})})};
 }};
 for(const group of groups)await api.openKeirinList(page,group[0],[]);
 assert.deepEqual(opened,names);
});
test('route policy admits only official normal read transport and denies credentials/mutations',enabled,()=>{
 const req=(changes={})=>({url:'https://autorace.jp/race_info/OtherRaceInfo',method:'POST',resource_type:'xhr',content_type:'application/json',body:Buffer.from(JSON.stringify({placeCode:3,raceDate:'2030-01-01',raceNo:2})),headers:{},...changes});
 assert.equal(api.routePolicy(req(),plan([auto])).allow,true);
 assert.equal(api.routePolicy(req({body:Buffer.from('{"placeCode":2,"raceDate":"2030-01-01","raceNo":2}')}),plan([auto])).allow,false);
 assert.equal(api.routePolicy(req({url:'https://autorace.jp/race_info/Program',body:Buffer.from('{"placeCode":3,"raceDate":"2030-01-01","raceNo":9}')}),plan([auto])).allow,false);
 for(const change of [{url:'https://foreign.invalid/race_info/OtherRaceInfo'},{url:'http://autorace.jp/race_info/OtherRaceInfo'},{url:'https://autorace.jp/login'},{url:'https://autorace.jp/race_info/SubmitVote'},{method:'DELETE'},{headers:{authorization:'secret'}},{body:Buffer.from('{"placeCode":3,"raceDate":"2030-01-01","raceNo":2,"password":"private"}')},{body:Buffer.from('{"placeCode":3,"raceDate":"2030-01-02","raceNo":2}')},{resource_type:'image'}])assert.equal(api.routePolicy(req(change),plan([auto])).allow,false,JSON.stringify(change));
 const natural={url:'https://keirin.jp/pc/racelive',method:'POST',resource_type:'document',content_type:'application/x-www-form-urlencoded',body:Buffer.from('encp=actual-published-opaque&disp=PJ0315'),headers:{}};
 assert.equal(api.routePolicy(natural,plan([keirin])).allow,true);
 assert.equal(api.routePolicy({...natural,body:Buffer.from('encp=x&password=hidden')},plan([keirin])).allow,false);
 assert.equal(api.routePolicy({...natural,url:'https://keirin.jp/pc/racevote'},plan([keirin])).allow,false);
 const json={...natural,method:'GET',body:Buffer.alloc(0),resource_type:'xhr',url:'https://keirin.jp/pc/json?encp=actual-published-opaque&type=JSJ012'};
 assert.equal(api.routePolicy(json,plan([keirin])).allow,true);
 assert.equal(api.routePolicy({...json,url:json.url+'&access_token=secret'},plan([keirin])).allow,false);
 assert.equal(api.routePolicy({...json,url:json.url.replace('JSJ012','WRITE001')},plan([keirin])).allow,false);
});
test('request scope contains only the current due venue group',enabled,()=>{
 const later={...auto,race_no:9,race_id:auto.race_id.replace(':2',':9'),due_at:'2030-01-01T13:00:00+09:00'};
 const other={...auto,venue:'kawaguchi',ui_entry_url:auto.ui_entry_url.replace('isesaki','kawaguchi'),race_id:auto.race_id.replace('isesaki','kawaguchi')};
 const scoped=api.requestScope(plan([auto,later,other]),[auto]);assert.deepEqual(scoped.cases,[auto]);
 const req={url:'https://autorace.jp/race_info/Program',method:'POST',resource_type:'xhr',content_type:'application/json',headers:{},body:Buffer.from('{"placeCode":3,"raceDate":"2030-01-01","raceNo":9}')};
 assert.equal(api.routePolicy(req,scoped).allow,false);
});
test('static cache authenticates original GET bytes clocks and MIME without replaying results',enabled,()=>{
 const raw=Buffer.from('/* invented static */'),sha=api.sha(raw),metadata={source_url:'https://keirin.jp/pc/static/js/fixture.js',final_url:'https://keirin.jp/pc/static/js/fixture.js',status:200,byte_count:raw.length,source_sha256:sha,fetched_at:'2029-12-31T01:00:00Z',response_received_at:'2029-12-31T01:00:01Z',headers:{'content-type':'application/javascript'},http_method:'GET',resource_type:'script'};
 const entry={raw_base64:raw.toString('base64'),metadata};const loaded=api.validateStaticCache([entry],plan([keirin]),NOW);
 assert.equal(loaded.get(metadata.source_url).metadata.response_received_at,metadata.response_received_at);assert.deepEqual(loaded.get(metadata.source_url).raw,raw);
 for(const change of [{status:403},{http_method:'POST'},{source_sha256:'f'.repeat(64)},{resource_type:'document'},{source_url:'https://keirin.jp/pc/json?encp=x&type=JSJ012',final_url:'https://keirin.jp/pc/json?encp=x&type=JSJ012'},{response_received_at:'2030-01-02T00:00:00Z'},{headers:{'content-type':'text/html'}}])assert.throws(()=>api.validateStaticCache([{...entry,metadata:{...metadata,...change}}],plan([keirin]),NOW));
 assert.throws(()=>api.validateStaticCache([{...entry,raw_base64:entry.raw_base64+'='}],plan([keirin]),NOW));
});
test('static Content-Type lookup preserves original header casing and rejects ambiguous variants',enabled,()=>{
 const raw=Buffer.from('/* invented cached script */'),url='https://keirin.jp/pc/static/js/header-fixture.js';
 const metadata={source_url:url,final_url:url,status:200,byte_count:raw.length,source_sha256:api.sha(raw),fetched_at:'2029-12-31T01:00:00Z',response_received_at:'2029-12-31T01:00:01Z',headers:{'Content-Type':'application/javascript; charset=UTF-8'},http_method:'GET',resource_type:'script'};
 const entry={raw_base64:raw.toString('base64'),metadata},before=structuredClone(entry);
 const loaded=api.validateStaticCache([entry],plan([keirin]),NOW);
 assert.deepEqual(loaded.get(url).metadata,metadata);assert.deepEqual(entry,before);
 assert.equal(api.contentType(loaded.get(url).metadata.headers),'application/javascript; charset=UTF-8');
 for(const headers of [{},{'Content-Type':'application/javascript','content-type':'application/javascript'},
                       {'CONTENT-TYPE':'text/css','Content-Type':'application/javascript'}]){
  assert.throws(()=>api.validateStaticCache([{...entry,metadata:{...metadata,headers}}],plan([keirin]),NOW));
 }
});
test('global request budget spaces starts and permanently stops on denial/deadline',enabled,async()=>{
 let now=0;const budget=api.createBudget(2,{now:()=>now,sleep:async ms=>{now+=ms;}});
 assert.equal((await budget.reserve()).sequence,1);assert.equal((await budget.reserve()).sequence,2);assert.equal(now,825);
 assert.equal(await budget.reserve(),null);assert.equal(budget.reason,'REQUEST_LIMIT');
 const denied=api.createBudget(32,{now:()=>now,sleep:async ms=>{now+=ms;}});denied.deny(403);assert.equal(await denied.reserve(),null);assert.equal(denied.reason,'HTTP_ACCESS_DENIED');
 const timed=api.createBudget(32,{now:()=>now,sleep:async ms=>{now+=ms;}});now+=85000;assert.equal(await timed.reserve(),null);assert.equal(timed.reason,'TIME_LIMIT');
 now=0;const dispatched=api.createBudget(32,{now:()=>now,sleep:async ms=>{now+=ms;}});await dispatched.reserve();now=50;dispatched.completeDispatch();await dispatched.reserve();assert.equal(now,875);
});
test('HTTP metadata uses completed body clock and strips sensitive headers',enabled,()=>{
 const raw=Buffer.from('invented response'),entry={url:'https://autorace.jp/race_info/RaceResult',method:'POST',resource_type:'xhr',request_started_at:'2030-01-01T02:59:00Z',request_body_sha256:'a'.repeat(64),request_body_file:'request-01.body',request_content_type:'application/json'};
 const result=api.makeMetadata(entry,{url:entry.url,status:200,headers:{'content-type':'application/json','set-cookie':'private','authorization':'private'}},raw,'2030-01-01T02:59:02Z');
 assert.equal(result.response_received_at,'2030-01-01T02:59:02Z');assert.equal(result.fetched_at,entry.request_started_at);assert.equal(result.source_sha256,api.sha(raw));assert.deepEqual(result.headers,{'content-type':'application/json'});
 assert.equal(result.method,'POST');
 assert.throws(()=>api.makeMetadata(entry,{url:entry.url,status:200,headers:{}},Buffer.alloc(2*1024*1024+1),'2030-01-01T02:59:02Z'));
});
test('browser provenance is captured at the case completion with original ledger and DOM hash',enabled,()=>{
 const dom={file:'case-01/rendered-dom.html',source_url:keirin.ui_entry_url,final_url:'https://keirin.jp/pc/racelive',captured_at:'2030-01-01T03:00:00Z',byte_count:10,source_sha256:'a'.repeat(64)};
 const ledger=[{event:'NORMAL_SEMANTIC_UI_CLICK',label:'競走結果',before:'https://keirin.jp/pc/racelive',after:'https://keirin.jp/pc/racelive',at:'2030-01-01T02:59:59Z'}];
 const actual=api.browserMetadata(keirin,dom,'2030-01-01T02:59:00Z',ledger);
 assert.equal(actual.schema,'RACE_AI_PRIVATE_OFFICIAL_BROWSER_PROBE_V1');assert.equal(actual.normal_ui_only,true);assert.equal(actual.undocumented_api_manually_called,false);assert.equal(actual.stop_reason,'FINISHED');assert.deepEqual(actual.ledger,ledger);assert.deepEqual(actual.rendered_dom,dom);
 ledger.push({status:403});assert.equal(actual.ledger.length,1);
 const mixed=[{status:200,url:'https://autorace.jp/race_info/RaceResult'},...actual.ledger,{status:200,url:'https://keirin.jp/pc/json?encp=x&type=JSJ012'}];
 const scoped=api.browserMetadata(keirin,dom,'2030-01-01T02:59:00Z',mixed);
 assert.equal(scoped.ledger.length,2);assert.ok(scoped.ledger.every(e=>!e.url?.includes('autorace.jp')));
});
test('Chromium keeps inherited proxy and CA transport while excluding owner credentials',enabled,()=>{
 const transport={HTTPS_PROXY:'http://127.0.0.1:8080',https_proxy:'http://127.0.0.1:8080',HTTP_PROXY:'http://127.0.0.1:8080',NO_PROXY:'localhost,127.0.0.1',SSL_CERT_FILE:'/fixture/ca.pem',NODE_EXTRA_CA_CERTS:'/fixture/ca.pem',REQUESTS_CA_BUNDLE:'/fixture/ca.pem'};
 const clean=api.browserEnvironment({PATH:'/usr/bin',HOME:'/fictional/home',LANG:'en_US.UTF-8',RACE_AI_STATE_KEY:'secret',GH_TOKEN:'secret',GITHUB_TOKEN:'secret',GIT_CONFIG_VALUE_0:'secret',...transport});
 assert.deepEqual(clean,{PATH:'/usr/bin',HOME:'/fictional/home',LANG:'en_US.UTF-8',...transport});
 assert.deepEqual(api.browserProxy(transport),{server:transport.HTTPS_PROXY,bypass:transport.NO_PROXY});
 assert.equal(api.browserProxy({}),undefined);
 assert.throws(()=>api.browserProxy({HTTPS_PROXY:'https://proxy.invalid/altered/path'}));
});
test('live request clock cannot regress behind the authenticated epoch',enabled,()=>{
 const value={...plan([auto]),not_before:'2030-01-01T03:00:00.000001Z'};
 assert.throws(()=>api.requireCurrentClock(value,NOW));assert.doesNotThrow(()=>api.requireCurrentClock(value,new Date('2030-01-01T03:00:00.001Z')));
});
test('private output is fresh outside Git with 0700 directory and 0600 create-only files',enabled,()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'official-ui-test-'));try{
  const out=path.join(root,'capture');api.createPrivateOutput(out);api.savePrivate(out,'request.body',Buffer.from('invented'));
  assert.equal(fs.statSync(out).mode&0o777,0o700);assert.equal(fs.statSync(path.join(out,'request.body')).mode&0o777,0o600);
  assert.throws(()=>api.createPrivateOutput(out));assert.throws(()=>api.savePrivate(out,'request.body',Buffer.from('replacement')));assert.throws(()=>api.savePrivate(out,'../outside',Buffer.from('no')));
  fs.mkdirSync(path.join(root,'.git'));assert.throws(()=>api.createPrivateOutput(path.join(root,'git-output')));
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('response role selection binds each AUTO literal request body and KEIRIN opaque identity',enabled,()=>{
 const make=(sequence,endpoint,race=2)=>({sequence,url:'https://autorace.jp/race_info/'+endpoint,method:'POST',status:200,request_identity:{placeCode:3,raceDate:'2030-01-01',raceNo:race},source_sha256:'a'.repeat(64)});
 assert.deepEqual(api.caseResponses(auto,[make(1,'OtherRaceInfo'),make(2,'RaceResult'),make(3,'RaceResult',3)]),[{role:'identity',sequence:1},{role:'result',sequence:2}]);
 assert.deepEqual(api.caseResponses(auto,[{...make(1,'OtherRaceInfo'),request_identity:{placeCode:2,raceDate:'2030-01-01',raceNo:2}},{...make(2,'RaceResult'),request_identity:{placeCode:2,raceDate:'2030-01-01',raceNo:2}}]),[]);
 const json=(sequence,type,encp)=>({sequence,url:'https://keirin.jp/pc/json?encp='+encp+'&type='+type,method:'GET',status:200,...(type==='JSJ001'?{case_identity:{sport:'keirin',expected_date:keirin.expected_date,venue:keirin.venue,race_no:keirin.race_no}}:{})});
 assert.deepEqual(api.caseResponses(keirin,[json(1,'JSJ001','same'),json(2,'JSJ012','other'),json(3,'JSJ012','same')]),[{role:'identity',sequence:1},{role:'result',sequence:3}]);
 assert.deepEqual(api.caseResponses(keirin,[{...json(1,'JSJ001','same'),case_identity:{...keirin,race_no:9}},json(3,'JSJ012','same')]),[]);
});
test('network byte guard stops a chunked response above the body cap',enabled,async()=>{
 const handlers={};let stopped=null;const session={send:async()=>{},on:(event,fn)=>{handlers[event]=fn;}};
 await api.installByteGuard({newCDPSession:async()=>session},{},reason=>{stopped=reason;});
 handlers['Network.dataReceived']({requestId:'one',dataLength:api.MAX_BODY});assert.equal(stopped,null);
 handlers['Network.dataReceived']({requestId:'one',dataLength:1});assert.equal(stopped,'BODY_BOUND');
});
test('future cases write a truthful private HOLD without loading any browser',enabled,async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'official-ui-due-'));try{
  const future={...auto,expected_date:'2099-01-01',race_id:'autorace:2099-01-01:isesaki:2',due_at:'2099-01-01T11:30:00+09:00'};
  const result=await api.capturePlan(plan([future]),path.join(root,'capture'),{chromium:{launch:async()=>{throw Error('browser must not launch');}}});
  assert.equal(result.actual_request_count,0);assert.equal(result.cases[0].state,'HOLD_NOT_DUE');assert.equal(result.manual_api_requests,0);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('offline browser transport retains exact natural UI request/response bytes and DOM',enabled,async()=>{
 const {EventEmitter}=require('node:events');const root=fs.mkdtempSync(path.join(os.tmpdir(),'official-ui-flow-'));
 const item={...auto,expected_date:'2020-01-01',race_id:'autorace:2020-01-01:isesaki:2',due_at:'2020-01-01T11:30:00+09:00'};
 const sourceBody=Buffer.from('{"invented":"normal-result-source"}');let handler,launchOptions,closed=false;
 class Page extends EventEmitter{
  url(){return item.ui_entry_url;}
  async waitForLoadState(){}async waitForTimeout(ms){await new Promise(r=>setTimeout(r,Math.min(ms,5)));}async close(){}
  async goto(){await perform(item.ui_entry_url,'GET','document',Buffer.alloc(0),Buffer.from('<html>invented index</html>'));}
  locator(selector){const endpoint=selector.includes('data-main-menu')?'RaceResult':selector.includes('data-raceno')?'OtherRaceInfo':null;const label=selector.includes('data-main-menu')?'レース結果':selector.includes('data-raceno')?'2R':'初日';
   const loc={count:async()=>1,isVisible:async()=>true,waitFor:async()=>{},innerText:async()=>label,click:async()=>{if(endpoint)await perform('https://autorace.jp/race_info/'+endpoint,'POST','xhr',Buffer.from(JSON.stringify({placeCode:3,raceDate:item.expected_date,raceNo:2})),sourceBody);},last:()=>loc};return loc;}
  async content(){return '<html>invented rendered result</html>';}
 }
 const page=new Page(),context=new EventEmitter();Object.assign(context,{setDefaultTimeout(){},routeWebSocket:async()=>{},newCDPSession:async()=>({send:async()=>{},on(){}}),route:async(_,fn)=>{handler=fn;},newPage:async()=>page,close:async()=>{closed=true;}});
 async function perform(url,method,type,body,raw){
  const req={url:()=>url,method:()=>method,resourceType:()=>type,postDataBuffer:()=>body,headers:()=>({'content-type':'application/json'})};let aborted=false;
  const response={request:()=>req,status:()=>200,url:()=>url,headers:()=>({'content-type':type==='document'?'text/html':'application/json'}),body:async()=>raw};
  await handler({request:()=>req,abort:async()=>{aborted=true;},continue:async()=>{const n=req._officialCapture.sequence;const progress=JSON.parse(fs.readFileSync(path.join(root,'capture','request-ledger-'+String(n).padStart(3,'0')+'.json')));assert.equal(progress.schema,'RACE_AI_OFFICIAL_RESULT_BROWSER_REQUEST_CHECKPOINT_V1');assert.equal(progress.actual_request_count,n);assert.equal(progress.ledger.at(-1).sequence,n);context.emit('response',response);},fulfill:async()=>{throw Error('no authored cache expected');}});assert.equal(aborted,false);
 }
 try{
  const index=await api.capturePlan(plan([item]),path.join(root,'capture'),{executablePath:process.execPath,chromium:{launch:async opts=>{launchOptions=opts;return {newContext:async()=>context,close:async()=>{}};}}});
  assert.equal(index.actual_request_count,3);assert.equal(index.cases[0].state,'CAPTURED');assert.deepEqual(index.cases[0].responses.map(x=>x.role),['identity','result']);assert.equal(closed,true);assert.equal(launchOptions.timeout,12000);
  const result=index.responses.find(x=>x.url.endsWith('/RaceResult'));assert.deepEqual(fs.readFileSync(path.join(root,'capture',result.body_file)),sourceBody);
  const request=fs.readFileSync(path.join(root,'capture',result.request_body_file));assert.equal(api.sha(request),result.request_body_sha256);assert.deepEqual(JSON.parse(request),{placeCode:3,raceDate:item.expected_date,raceNo:2});
  assert.equal(index.cases[0].browser_metadata.normal_ui_only,true);assert.equal(index.cases[0].browser_metadata.ledger.some(x=>x.event==='NORMAL_SEMANTIC_UI_CLICK'&&x.label==='レース結果'),true);
  for(const file of fs.readdirSync(path.join(root,'capture'))){const stat=fs.statSync(path.join(root,'capture',file));assert.equal(stat.mode&0o777,stat.isDirectory()?0o700:0o600);}
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('CLI malformed private plan emits counts only without URLs, paths or browser access',enabled,()=>{
 const {spawnSync}=require('node:child_process');const root=fs.mkdtempSync(path.join(os.tmpdir(),'official-ui-cli-'));try{
  const filename=path.join(root,'private-owner-plan.json');fs.writeFileSync(filename,JSON.stringify({private_url:'https://secret.invalid'}),{mode:0o600});
  const run=spawnSync(process.execPath,[script,'--plan',filename,'--out-dir',path.join(root,'output')],{encoding:'utf8',env:{PATH:process.env.PATH,CHROMIUM_PATH:'/definitely/missing'}});
  assert.equal(run.status,1);assert.deepEqual(JSON.parse(run.stdout),{state:'HOLD',actual_request_count:0,captured_case_count:0,held_case_count:0,stopped_host:false});assert.equal(run.stderr,'');assert.ok(!run.stdout.includes(root));assert.ok(!run.stdout.includes('secret.invalid'));
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
