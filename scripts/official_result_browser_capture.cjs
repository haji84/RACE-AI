/* Normal official UI only. Importing this module never loads a browser. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const SCHEMA='RACE_AI_OFFICIAL_RESULT_BROWSER_PLAN_V1',CAPTURE='RACE_AI_OFFICIAL_RESULT_BROWSER_CAPTURE_V1';
const MAX_BODY=2*1024*1024,MAX_CACHE=16*1024*1024,MAX_REQUESTS=32,SPACING_MS=825,TIMEOUT_MS=12000,ELAPSED_MS=85000;
const AUTO_VENUES=new Set(['isesaki','kawaguchi','hamamatsu','iizuka','sanyou']);
// Observed normal OtherRaceInfo identities; other venues require a saved source code.
const OBSERVED_AUTO_CODES={isesaki:3,kawaguchi:2};
const HOSTS={autorace:new Set(['autorace.jp','www.autorace.jp']),keirin:new Set(['keirin.jp','www.keirin.jp'])};
const DENY_PATH=/(?:login|logout|sign[upin]|password|register|racevote|touhyou|betting|purchase|submitvote|payment|deposit|withdraw|account|\/ana(?:\/|$))/i;
const SECRET_KEY=/^(?:pass(?:word|wd)?|authorization|cookie|session(?:id)?|csrf(?:token)?|access_token|refresh_token|auth_token|credential|secret|token)$/i;
const sha=raw=>crypto.createHash('sha256').update(raw).digest('hex');
const stamp=()=>new Date().toISOString();
function need(ok,code){if(!ok)throw Error('OFFICIAL_BROWSER_'+code);}
function plain(x){return x!==null&&typeof x==='object'&&!Array.isArray(x)&&Object.getPrototypeOf(x)===Object.prototype;}
function keys(x,required,optional=[]){return plain(x)&&required.every(k=>Object.hasOwn(x,k))&&Object.keys(x).every(k=>required.includes(k)||optional.includes(k));}
function contentType(headers){
 need(plain(headers),'CONTENT_TYPE_HEADER');const values=Object.entries(headers).filter(([name])=>name.toLowerCase()==='content-type');
 need(values.length===1&&typeof values[0][1]==='string','CONTENT_TYPE_HEADER');return values[0][1];
}
function time(value){need(typeof value==='string'&&value.length<=64&&/(?:Z|[+-]\d\d:\d\d)$/.test(value)&&Number.isFinite(Date.parse(value)),'AWARE_CLOCK');return Date.parse(value);}
function requireCurrentClock(plan,now=new Date()){
 if(!Object.hasOwn(plan,'not_before'))return;
 const parsed=time(plan.not_before),fraction=/\.(\d+)(?:Z|[+-]\d\d:\d\d)$/.exec(plan.not_before);
 const minimum=parsed+(fraction&&/[1-9]/.test(fraction[1].slice(3))?1:0);
 need(now instanceof Date&&Number.isFinite(now.valueOf())&&now.valueOf()>=minimum,'CLOCK_REGRESSION');
}
function day(value){need(typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value,'EVENT_DAY');return value;}
function placeCode(item){const value=item.place_code??OBSERVED_AUTO_CODES[item.venue];need(Number.isInteger(value)&&value>=1&&value<=20&&(!Object.hasOwn(OBSERVED_AUTO_CODES,item.venue)||value===OBSERVED_AUTO_CODES[item.venue]),'SAVED_AUTO_PLACE_CODE');return value;}
function safeUrl(value,sport){
 need(typeof value==='string'&&value.length<=4096,'SOURCE_URL');let u;try{u=new URL(value);}catch{throw Error('OFFICIAL_BROWSER_SOURCE_URL');}
 need(u.protocol==='https:'&&HOSTS[sport]?.has(u.hostname)&&!u.username&&!u.password&&!u.port&&!u.hash&&!DENY_PATH.test(decodeURIComponent(u.pathname)),'OFFICIAL_SOURCE');
 need([...u.searchParams.keys()].every(k=>!SECRET_KEY.test(k)),'CREDENTIAL_QUERY');return u;
}
function validatePlan(value,now=new Date()){
 need(now instanceof Date&&Number.isFinite(now.valueOf()),'AWARE_CLOCK');
 need(keys(value,['schema','cases'],['request_budget','static_cache','not_before'])&&value.schema===SCHEMA&&Array.isArray(value.cases)&&value.cases.length>=1&&value.cases.length<=24,'PLAN_SCHEMA');
 requireCurrentClock(value,now);
 if(Object.hasOwn(value,'request_budget'))need(Number.isInteger(value.request_budget)&&value.request_budget>=1&&value.request_budget<=MAX_REQUESTS,'REQUEST_BUDGET');
 const seen=new Set(),counts={};
 for(const item of value.cases){
  need(keys(item,['sport','race_id','ui_entry_url','expected_date','venue','race_no','due_at'],['ui_venue_name','place_code'])&&['autorace','keirin'].includes(item.sport),'CASE_SCHEMA');
  day(item.expected_date);const due=time(item.due_at);
  need(new Date(due+9*3600000).toISOString().slice(0,10)===item.expected_date&&Number.isInteger(item.race_no)&&item.race_no>=1&&item.race_no<=12,'CASE_CLOCK_OR_NUMBER');
  need(typeof item.venue==='string'&&(item.sport==='autorace'?AUTO_VENUES.has(item.venue):/^keirin-jyo-[0-9]{2}$/.test(item.venue)),'CASE_VENUE');
  if(item.sport==='autorace')placeCode(item);else need(!Object.hasOwn(item,'place_code'),'CASE_SCHEMA');
  need(item.race_id===`${item.sport}:${item.expected_date}:${item.venue}:${item.race_no}`&&!seen.has(item.race_id),'CASE_IDENTITY');seen.add(item.race_id);
  if(Object.hasOwn(item,'ui_venue_name'))need(typeof item.ui_venue_name==='string'&&item.ui_venue_name.trim()===item.ui_venue_name&&item.ui_venue_name.length>=1&&item.ui_venue_name.length<=80&&!/[<>\r\n]/.test(item.ui_venue_name),'UI_VENUE_NAME');
  const u=safeUrl(item.ui_entry_url,item.sport);
  need(!u.search&&(item.sport==='autorace'?u.pathname==='/race_info/Live/'+item.venue:u.pathname==='/pc/top'),'UI_ENTRY_URL');
  const group=caseGroupKey(item);counts[group]=(counts[group]||0)+1;need(counts[group]<=12,'VENUE_CASE_BOUND');
 }
 if(Object.hasOwn(value,'static_cache'))validateStaticCache(value.static_cache,value,now);
 return structuredClone(value);
}
function caseGroupKey(item){return JSON.stringify([item.sport,item.venue,item.expected_date,item.ui_entry_url]);}
function groupCases(items){const groups=new Map();for(const item of items){const key=caseGroupKey(item);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);}return groups;}
function dueCases(plan,now=new Date()){return plan.cases.filter(c=>time(c.due_at)<=now.valueOf()).map(c=>structuredClone(c));}
function requestScope(plan,group){need(Array.isArray(group)&&group.length>0&&group.every(c=>plan.cases.some(p=>p.race_id===c.race_id)),'REQUEST_GROUP');return {...plan,cases:group};}
function bodyFields(raw,contentType){
 need(Buffer.isBuffer(raw)&&raw.length>0&&raw.length<=16384,'READ_REQUEST_BODY');let value;
 if(/^application\/json(?:;|$)/i.test(contentType)){try{value=JSON.parse(raw.toString('utf8'));}catch{throw Error('OFFICIAL_BROWSER_READ_REQUEST_BODY');}need(plain(value),'READ_REQUEST_BODY');}
 else{need(/^application\/x-www-form-urlencoded(?:;|$)/i.test(contentType),'READ_REQUEST_CONTENT_TYPE');const params=new URLSearchParams(raw.toString('utf8'));need([...params.keys()].length===new Set(params.keys()).size,'DUPLICATE_FORM_FIELD');value=Object.fromEntries(params);}
 need(Object.keys(value).every(k=>!SECRET_KEY.test(k)),'CREDENTIAL_BODY');return value;
}
function routePolicy(req,plan){
 try{
  need(plain(req)&&typeof req.method==='string'&&typeof req.resource_type==='string','REQUEST_SCHEMA');
  need(!req.headers?.authorization&&!req.headers?.Authorization,'CREDENTIAL_HEADER');
  const sports=[...new Set(plan.cases.map(c=>c.sport))];let sport;
  for(const candidate of sports){try{safeUrl(req.url,candidate);sport=candidate;break;}catch{}}
  need(sport,'OFFICIAL_SOURCE');const u=safeUrl(req.url,sport),type=req.resource_type,method=req.method;
  need(!['image','font','media','websocket','eventsource','manifest'].includes(type),'UNNEEDED_RESOURCE');
  if(['script','stylesheet'].includes(type)){
   need(method==='GET'&&new RegExp(type==='script'?'\\.js$':'\\.css$','i').test(u.pathname)&&!/(?:analytics|tracker|banner)/i.test(u.pathname),'STATIC_READ_ONLY');return {allow:true,sport,static:true};
  }
  if(sport==='autorace'){
   if(method==='POST'){
    need(['xhr','fetch'].includes(type)&&['/race_info/Program','/race_info/OtherRaceInfo','/race_info/RaceResult','/race_info/RaceRefund'].includes(u.pathname)&&!u.search,'NORMAL_READ_POST');
    const identity=bodyFields(req.body,req.content_type||'');
    need(keys(identity,['placeCode','raceDate','raceNo'])&&Number.isInteger(identity.placeCode)&&/^([1-9]|1[0-2])$/.test(String(identity.raceNo))&&plan.cases.some(c=>c.sport===sport&&c.expected_date===identity.raceDate&&placeCode(c)===identity.placeCode&&(c.race_no===Number(identity.raceNo)||u.pathname==='/race_info/OtherRaceInfo')),'NORMAL_READ_IDENTITY');
    return {allow:true,sport,request_identity:{...identity,raceNo:Number(identity.raceNo)}};
   }
   need(method==='GET','READ_METHOD');
   if(type==='document')need(plan.cases.some(c=>c.sport===sport&&(u.pathname===new URL(c.ui_entry_url).pathname||u.pathname.startsWith(new URL(c.ui_entry_url).pathname+'/'))),'NORMAL_UI_DOCUMENT');
   else need(['xhr','fetch'].includes(type)&&(/^\/race_info\/(?:XML\/Hold\/Today|important_notice|JushouEvent\/Amount)$/.test(u.pathname)||/^\/data\/notice\/(?:all|info)-\d+\.json$/.test(u.pathname)||/^\/data\/refund\/\d{8}-[a-z]+-\d{2}R-refund\.csv$/.test(u.pathname)),'NORMAL_UI_READ');
  }else{
   if(method==='POST'){
    need(type==='document'&&['/pc/racelist','/pc/racelive'].includes(u.pathname)&&!u.search,'NORMAL_READ_POST');
    const value=bodyFields(req.body,req.content_type||'');
    need(keys(value,['disp','encp'])&&['PJ0305','PJ0306','PJ0315'].includes(value.disp)&&typeof value.encp==='string'&&/^[a-zA-Z0-9_=-]{1,512}$/.test(value.encp),'NORMAL_READ_IDENTITY');
   }else{
    need(method==='GET','READ_METHOD');
    if(type==='document')need(['/pc/top','/pc/racelist','/pc/racelive'].includes(u.pathname)&&!u.search,'NORMAL_UI_DOCUMENT');
    else need(['xhr','fetch'].includes(type)&&u.pathname==='/pc/json'&&[...u.searchParams.keys()].sort().join(',')==='encp,type'&&u.searchParams.getAll('encp').length===1&&/^[a-zA-Z0-9_=-]{1,512}$/.test(u.searchParams.get('encp'))&&['JSJ001','JSJ003','JSJ004','JSJ012'].includes(u.searchParams.get('type')),'NORMAL_UI_READ');
   }
  }
  return {allow:true,sport,static:false};
 }catch(error){return {allow:false,reason:/^OFFICIAL_BROWSER_[A-Z_]+$/.test(error.message)?error.message:'OFFICIAL_BROWSER_REQUEST_REJECTED'};}
}
function validateStaticCache(entries,plan,now=new Date()){
 need(Array.isArray(entries)&&entries.length<=128,'STATIC_CACHE_BOUND');let total=0;const out=new Map();
 for(const entry of entries){
  need(keys(entry,['raw_base64','metadata'])&&typeof entry.raw_base64==='string'&&entry.raw_base64.length<=Math.ceil(MAX_BODY/3)*4,'STATIC_CACHE_SCHEMA');
  const raw=Buffer.from(entry.raw_base64,'base64'),m=entry.metadata;
  need(raw.length>0&&raw.length<=MAX_BODY&&raw.toString('base64')===entry.raw_base64&&plain(m),'STATIC_CACHE_BYTES');
  const policy=routePolicy({url:m.source_url,method:m.http_method,resource_type:m.resource_type,headers:{}},plan);
  need(policy.allow&&policy.static&&m.final_url===m.source_url&&m.status===200&&m.byte_count===raw.length&&m.source_sha256===sha(raw),'STATIC_CACHE_PROOF');
  const mime=contentType(m.headers);need(m.resource_type==='script'?/^(?:application|text)\/(?:javascript|x-javascript|ecmascript)(?:;|$)/i.test(mime):/^text\/css(?:;|$)/i.test(mime),'STATIC_CACHE_MIME');
  need(time(m.fetched_at)<=time(m.response_received_at)&&time(m.response_received_at)<=now.valueOf(),'STATIC_CACHE_CLOCK');
  total+=raw.length;need(total<=MAX_CACHE,'STATIC_CACHE_BOUND');
  need(!out.has(m.source_url)||sha(out.get(m.source_url).raw)===sha(raw),'CONFLICTING_STATIC_CACHE');
  out.set(m.source_url,{raw,metadata:structuredClone(m)});
 }
 return out;
}
function createBudget(limit=MAX_REQUESTS,{now=()=>performance.now(),sleep=ms=>new Promise(r=>setTimeout(r,ms))}={}){
 need(Number.isInteger(limit)&&limit>=1&&limit<=MAX_REQUESTS,'REQUEST_BUDGET');const start=now();let last=null,count=0,reason=null,serial=Promise.resolve();
 const state={get count(){return count;},get reason(){return reason;},get started(){return start;},completeDispatch(){last=now();},stop(value){if(!reason)reason=value;},deny(status){if([401,403,429].includes(status))reason='HTTP_ACCESS_DENIED';},
  reserve(){const work=serial.then(async()=>{if(reason)return null;let remaining=last===null?0:Math.max(0,last+SPACING_MS-now());if(remaining)await sleep(remaining);if(now()-start>=ELAPSED_MS)reason='TIME_LIMIT';if(count>=limit)reason='REQUEST_LIMIT';if(reason)return null;last=now();count++;return {sequence:count,started_ms:last};});serial=work.catch(()=>{});return work;}};return state;
}
function makeMetadata(entry,response,raw,completed){
 need(Buffer.isBuffer(raw)&&raw.length<=MAX_BODY,'BODY_BOUND');need(time(entry.request_started_at)<=time(completed),'RESPONSE_CLOCK');
 const headers={};for(const [key,value]of Object.entries(response.headers||{}))if(['content-type','content-length','date','cache-control','location'].includes(key.toLowerCase()))headers[key.toLowerCase()]=value;
 return {source_url:entry.url,final_url:response.url,status:response.status,byte_count:raw.length,source_sha256:sha(raw),fetched_at:entry.request_started_at,response_received_at:completed,headers,method:entry.method,http_method:entry.method,resource_type:entry.resource_type,ui_capture_kind:'NORMAL_BROWSER_UI',...(entry.request_body_file?{request_body_file:entry.request_body_file,request_body_sha256:entry.request_body_sha256,request_content_type:entry.request_content_type}:{} )};
}
function browserMetadata(item,dom,started,ledger){
 const scoped=ledger.filter(e=>{try{if(e.url)return HOSTS[item.sport].has(new URL(e.url).hostname);if(e.before&&e.after)return HOSTS[item.sport].has(new URL(e.before).hostname)&&HOSTS[item.sport].has(new URL(e.after).hostname);return !Object.hasOwn(e,'status');}catch{return false;}});
 const denied=scoped.some(e=>[401,403,429].includes(e.status));
 return {schema:'RACE_AI_PRIVATE_OFFICIAL_BROWSER_PROBE_V1',source_url:item.ui_entry_url,
  started_at:started,captured_at:dom.captured_at,normal_ui_only:true,undocumented_api_manually_called:false,
  http_access_denied:denied,entire_host_stopped:denied,
  stop_reason:denied?'HTTP_ACCESS_DENIED':'FINISHED',network_host_allowlist:[...HOSTS[item.sport]],rendered_dom:structuredClone(dom),ledger:structuredClone(scoped)};
}
function privatePath(value){
 const target=path.resolve(value);need(!String(value).split(path.sep).includes('..'),'PRIVATE_PATH');
 let p=target;while(true){if(fs.existsSync(p)){need(!fs.lstatSync(p).isSymbolicLink(),'PRIVATE_SYMLINK');need(!fs.existsSync(path.join(p,'.git')),'PRIVATE_OUTSIDE_GIT');}const up=path.dirname(p);if(up===p)break;p=up;}return target;
}
function createPrivateOutput(value){const target=privatePath(value);need(!fs.existsSync(target),'OUTPUT_EXISTS');const parent=fs.statSync(path.dirname(target));need(parent.isDirectory()&&parent.uid===process.getuid()&&!(parent.mode&0o022),'PRIVATE_PARENT');fs.mkdirSync(target,{mode:0o700});return target;}
function savePrivate(root,name,raw){need(typeof name==='string'&&/^[a-zA-Z0-9_.-]+$/.test(name)&&!['.','..'].includes(name),'PRIVATE_FILE_NAME');fs.writeFileSync(path.join(root,name),raw,{mode:0o600,flag:'wx'});}
function caseResponses(item,entries){
 const found=[];
 if(item.sport==='autorace'){
  const roles={OtherRaceInfo:'identity',RaceResult:'result',Program:'program',RaceRefund:'result_companion'};
  for(const row of entries){const id=row.request_identity;if(row.status!==200||!id||id.raceDate!==item.expected_date||id.raceNo!==item.race_no||id.placeCode!==placeCode(item))continue;const role=roles[new URL(row.url).pathname.split('/').pop()];if(role)found.push({role,sequence:row.sequence});}
 }else{
  const identity=entries.filter(r=>r.status===200&&new URL(r.url).pathname==='/pc/json'&&new URL(r.url).searchParams.get('type')==='JSJ001'&&r.case_identity?.expected_date===item.expected_date&&r.case_identity?.venue===item.venue&&r.case_identity?.race_no===item.race_no).at(-1);
  if(identity){const selector=new URL(identity.url).searchParams.get('encp');found.push({role:'identity',sequence:identity.sequence});for(const row of entries)if(row.status===200&&new URL(row.url).pathname==='/pc/json'&&new URL(row.url).searchParams.get('type')==='JSJ012'&&new URL(row.url).searchParams.get('encp')===selector)found.push({role:'result',sequence:row.sequence});}
 }
 return found;
}
function cleanLabel(value){return String(value).replace(/\s+/g,' ').trim();}
function browserEnvironment(env=process.env){const out={};for(const name of ['PATH','HOME','LANG','LC_ALL','TMPDIR','XDG_CACHE_HOME','HTTP_PROXY','HTTPS_PROXY','NO_PROXY','http_proxy','https_proxy','no_proxy','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS','REQUESTS_CA_BUNDLE'])if(typeof env[name]==='string')out[name]=env[name];return out;}
function browserProxy(env=process.env){
 const value=env.HTTPS_PROXY||env.https_proxy||env.HTTP_PROXY||env.http_proxy;if(!value)return undefined;
 let parsed;try{parsed=new URL(value);}catch{throw Error('OFFICIAL_BROWSER_PROXY_CONFIGURATION');}
 need(['http:','https:'].includes(parsed.protocol)&&!parsed.username&&!parsed.password&&!parsed.search&&!parsed.hash&&parsed.pathname==='/','PROXY_CONFIGURATION');
 const bypass=env.NO_PROXY||env.no_proxy;return {server:value,...(bypass?{bypass}:{})};
}
function regexEscape(value){return value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');}
async function click(page,locator,expected,ledger,{popup=false}={}){
 need(await locator.count()===1&&await locator.isVisible(),'VISIBLE_UI_CONTROL');const label=cleanLabel(await locator.innerText());need(expected.test(label)&&!/ログイン|投票|購入|入金|出金|会員|登録/.test(label),'READ_ONLY_UI_LABEL');
 const before=page.url();let next=null;const listener=p=>{next=p;};if(popup)page.on('popup',listener);
 try{await locator.click({timeout:TIMEOUT_MS});if(popup&&!next)await page.waitForTimeout(250);}finally{if(popup)page.off('popup',listener);}
 const target=next||page;await target.waitForLoadState('domcontentloaded',{timeout:TIMEOUT_MS}).catch(()=>{});
 ledger.push({event:'NORMAL_SEMANTIC_UI_CLICK',label,before,after:target.url(),at:stamp()});return target;
}
async function selectAutoCase(page,item,ledger){
 const date=page.locator('#live-paragraphday-main [data-period-date="'+item.expected_date+'"] a');await date.waitFor({state:'visible',timeout:TIMEOUT_MS});await click(page,date,/^.+$/,ledger);
 const race=page.locator('#live-raceno-link [data-raceno="'+item.race_no+'"] a');await race.waitFor({state:'visible',timeout:TIMEOUT_MS});await click(page,race,new RegExp('^'+item.race_no+'R$'),ledger);
 const result=page.locator('li[data-main-menu="result"] a').last();await result.waitFor({state:'visible',timeout:TIMEOUT_MS});await click(page,result,/^レース結果$/,ledger);return page;
}
async function openKeirinList(page,item,ledger){
 need(typeof item.ui_venue_name==='string','UI_VENUE_NAME_REQUIRED');
 const venue=page.locator('.kaisaichi').filter({hasText:new RegExp('^\\s*'+regexEscape(item.ui_venue_name)+'\\s*$')});
 const row=page.locator('#kaisaiInfoTable tr').filter({has:venue});await row.waitFor({state:'visible',timeout:TIMEOUT_MS});
 return click(page,row.getByRole('button',{name:/^出走表\s*一覧$/}),/^出走表\s*一覧$/,ledger,{popup:true});
}
async function selectKeirinCase(listPage,item,ledger){
 need(await listPage.locator('#hhSelJ').inputValue()===item.venue.slice(-2),'VISIBLE_VENUE_IDENTITY');
 const [year,month,date]=item.expected_date.split('-');const wanted=year+month+date;
 if(await listPage.locator('#hhSelK').inputValue()!==wanted){const dateLink=listPage.locator('[name="hhlnkRaceDate"]').filter({hasText:new RegExp('^0?'+Number(month)+'/0?'+Number(date)+'(?:\\D|$)')});await click(listPage,dateLink,/^\d{1,2}\/\d{1,2}/,ledger);}
 need(await listPage.locator('#hhSelK').inputValue()===wanted&&await listPage.locator('#hhSelJ').inputValue()===item.venue.slice(-2),'VISIBLE_DAY_VENUE_IDENTITY');
 await click(listPage,listPage.locator('#hhbtnResultList'),/^結果一覧$/,ledger);
 const detail=await click(listPage,listPage.locator('#hhRaceBtn'+item.race_no),new RegExp('^'+item.race_no+'R$'),ledger,{popup:true});
 need(await detail.locator('#hhSelK').inputValue()===wanted&&await detail.locator('#hhSelJ').inputValue()===item.venue.slice(-2),'VISIBLE_DETAIL_IDENTITY');
 const heading=cleanLabel(await detail.locator('#hhLblRaceDtl').innerText());need(new RegExp('^'+item.race_no+'R(?:\\s|$)').test(heading),'VISIBLE_RACE_IDENTITY');
 await click(detail,detail.locator('#rcbtn8'),/^競走結果$/,ledger);return detail;
}
async function installByteGuard(context,page,stop){
 need(typeof context.newCDPSession==='function','CHROMIUM_BYTE_GUARD_REQUIRED');const session=await context.newCDPSession(page),sizes=new Map();
 session.on('Network.dataReceived',event=>{const size=(sizes.get(event.requestId)||0)+event.dataLength;sizes.set(event.requestId,size);if(size>MAX_BODY)stop('BODY_BOUND');});
 for(const event of ['Network.loadingFinished','Network.loadingFailed'])session.on(event,value=>sizes.delete(value.requestId));
 await session.send('Network.enable');return session;
}
async function capturePlan(input,out,{chromium,executablePath=process.env.CHROMIUM_PATH||'/usr/bin/chromium'}={}){
 const plan=validatePlan(input),root=createPrivateOutput(out),started=stamp(),due=dueCases(plan),budget=createBudget(plan.request_budget||MAX_REQUESTS);
 const ledger=[],responses=[],cases=[],cache=validateStaticCache(plan.static_cache||[],plan),pending=new Set(),timers=new Map();let browser,context,deadline,activeSport=null,activeCases=[],dispatch=Promise.resolve();
 const add=e=>{if(ledger.length<2048)ledger.push(e);else budget.stop('LEDGER_LIMIT');};
 const stop=reason=>{budget.stop(reason);if(context)context.close().catch(()=>{});};
 deadline=setTimeout(()=>stop('TIME_LIMIT'),ELAPSED_MS);
 try{
  if(due.length){need(typeof executablePath==='string'&&path.isAbsolute(executablePath)&&fs.existsSync(executablePath),'FIXED_CHROMIUM_REQUIRED');
   if(!chromium)chromium=require('playwright').chromium;
   requireCurrentClock(plan);const proxy=browserProxy();
   browser=await chromium.launch({executablePath,timeout:TIMEOUT_MS,env:browserEnvironment(),...(proxy?{proxy}:{}),headless:true,args:['--no-sandbox','--disable-background-networking','--disable-component-update','--disable-default-apps','--disable-sync','--no-first-run']});need(!budget.reason,'CAPTURE_STOPPED');
   context=await browser.newContext({serviceWorkers:'block',viewport:{width:1440,height:1100},userAgent:'RACE-AI-owner-personal-normal-browser/1.0'});context.setDefaultTimeout(TIMEOUT_MS);
   need(typeof context.routeWebSocket==='function','WEBSOCKET_BLOCK_REQUIRED');await context.routeWebSocket('**/*',socket=>socket.close());
   const guarded=new WeakMap();const guard=page=>{if(!guarded.has(page))guarded.set(page,installByteGuard(context,page,stop));return guarded.get(page);};
   context.on('page',page=>guard(page).catch(()=>stop('BYTE_GUARD_UNAVAILABLE')));
   await context.route('**/*',async route=>{
    const req=route.request();const request={url:req.url(),method:req.method(),resource_type:req.resourceType(),body:req.postDataBuffer()||Buffer.alloc(0),content_type:req.headers()['content-type']||'',headers:{authorization:req.headers().authorization}};
    const scoped=requestScope(plan,activeCases);const policy=routePolicy(request,scoped);
    if(budget.reason||!policy.allow){add({event:'BLOCKED_REQUEST',reason:budget.reason||policy.reason,method:request.method,resource_type:request.resource_type,at:stamp()});await route.abort().catch(()=>{});return;}
    if(policy.static&&cache.has(request.url)){const saved=cache.get(request.url);add({event:'STATIC_CACHE_REPLAY',url:request.url,method:'GET',resource_type:request.resource_type,source_sha256:sha(saved.raw),original_captured_at:saved.metadata.response_received_at,at:stamp()});await route.fulfill({status:200,contentType:contentType(saved.metadata.headers),body:saved.raw});return;}
    const action=dispatch.then(async()=>{
     requireCurrentClock(plan);
     const reservation=await budget.reserve();if(!reservation){await route.abort().catch(()=>{});return;}
     requireCurrentClock(plan);
     const entry={sequence:reservation.sequence,url:request.url,method:request.method,resource_type:request.resource_type,...(policy.request_identity?{request_identity:policy.request_identity}:{})};
     if(request.method==='POST'){entry.request_body_file='request-'+String(entry.sequence).padStart(3,'0')+'.body';entry.request_body_sha256=sha(request.body);entry.request_content_type=request.content_type;savePrivate(root,entry.request_body_file,request.body);}
     entry.request_started_at=stamp();requireCurrentClock(plan,new Date(entry.request_started_at));req._officialCapture=entry;add(entry);
     savePrivate(root,'request-ledger-'+String(entry.sequence).padStart(3,'0')+'.json',JSON.stringify({schema:'RACE_AI_OFFICIAL_RESULT_BROWSER_REQUEST_CHECKPOINT_V1',started_at:started,last_updated_at:entry.request_started_at,actual_request_count:budget.count,maximum_requests:plan.request_budget||MAX_REQUESTS,ledger:structuredClone(ledger)},null,2));
     requireCurrentClock(plan);timers.set(entry.sequence,setTimeout(()=>stop('REQUEST_TIMEOUT'),TIMEOUT_MS));await route.continue();budget.completeDispatch();
    });dispatch=action.catch(()=>stop('REQUEST_DISPATCH_FAILED'));await action;
   });
   context.on('response',response=>{
    const task=(async()=>{const entry=response.request()._officialCapture;if(!entry)return;entry.status=response.status();entry.headers_received_at=stamp();
     if([401,403,429].includes(entry.status)){budget.deny(entry.status);stop('HTTP_ACCESS_DENIED');return;}
     const headers=response.headers();if(Number(headers['content-length'])>MAX_BODY){stop('BODY_BOUND');return;}
     const raw=await response.body();const completed=stamp();need(raw.length<=MAX_BODY,'BODY_BOUND');const metadata=makeMetadata(entry,{url:response.url(),status:entry.status,headers},raw,completed);
     entry.body_captured_at=completed;entry.response_received_at=completed;entry.byte_count=raw.length;entry.source_sha256=metadata.source_sha256;entry.content_type=metadata.headers['content-type']||'';
     entry.body_file='response-'+String(entry.sequence).padStart(3,'0')+'.body';entry.metadata_file='response-'+String(entry.sequence).padStart(3,'0')+'.metadata.json';savePrivate(root,entry.body_file,raw);savePrivate(root,entry.metadata_file,JSON.stringify(metadata,null,2));
     if(activeSport==='keirin'&&new URL(entry.url).pathname==='/pc/json'&&new URL(entry.url).searchParams.get('type')==='JSJ001'){
      try{const source=JSON.parse(raw.toString('utf8')).C0201data;if(plain(source)&&/^\d{8}$/.test(source.selKaisai)&&/^\d{2}$/.test(source.selKjyoCd)&&/^([1-9]|1[0-2])$/.test(String(source.selRaceNo)))entry.case_identity={sport:'keirin',expected_date:source.selKaisai.slice(0,4)+'-'+source.selKaisai.slice(4,6)+'-'+source.selKaisai.slice(6),venue:'keirin-jyo-'+source.selKjyoCd,race_no:Number(source.selRaceNo)};}catch{}
     }
     responses.push({...entry});
     if(['script','stylesheet'].includes(entry.resource_type)&&entry.status===200){try{const authenticated=validateStaticCache([{raw_base64:raw.toString('base64'),metadata}],plan);cache.set(entry.url,authenticated.get(entry.url));}catch{}}
    })().catch(error=>{add({event:'CAPTURE_ERROR',reason:/^OFFICIAL_BROWSER_[A-Z_]+$/.test(error.message)?error.message:'RESPONSE_UNAVAILABLE',at:stamp()});stop('CAPTURE_ERROR');}).finally(()=>{const entry=response.request()._officialCapture;if(entry){clearTimeout(timers.get(entry.sequence));timers.delete(entry.sequence);}pending.delete(task);});pending.add(task);
   });
   const groups=groupCases(due);
   for(const group of groups.values()){
    if(budget.reason)break;activeSport=group[0].sport;activeCases=group;const groupStart=stamp(),groupLedgerStart=ledger.length;let page=await context.newPage(),listPage;await guard(page);
    try{await page.goto(group[0].ui_entry_url,{waitUntil:'domcontentloaded',timeout:TIMEOUT_MS});if(activeSport==='keirin')listPage=await openKeirinList(page,group[0],ledger);
     for(const item of group){
      if(budget.reason)break;const before=budget.count;
      try{
       page=item.sport==='autorace'?await selectAutoCase(page,item,ledger):await selectKeirinCase(listPage,item,ledger);
       const until=Date.now()+TIMEOUT_MS;let selected=[];
       while(!budget.reason&&Date.now()<until){await Promise.allSettled([...pending]);selected=caseResponses(item,responses.filter(r=>item.sport==='autorace'||r.sequence>before));if(selected.some(r=>r.role==='result')&&selected.some(r=>r.role==='identity'))break;await page.waitForTimeout(100);}
       need(!budget.reason,'CAPTURE_STOPPED');const raw=Buffer.from(await page.content());need(raw.length<=MAX_BODY,'DOM_BOUND');
       const name='case-'+String(cases.length+1).padStart(2,'0'),folder=path.join(root,name);fs.mkdirSync(folder,{mode:0o700});savePrivate(folder,'rendered-dom.html',raw);
       const dom={file:name+'/rendered-dom.html',source_url:item.ui_entry_url,final_url:page.url(),captured_at:stamp(),byte_count:raw.length,source_sha256:sha(raw)};savePrivate(folder,'dom.metadata.json',JSON.stringify(dom,null,2));
       const provenance=browserMetadata(item,dom,groupStart,ledger.slice(groupLedgerStart));savePrivate(folder,'browser.metadata.json',JSON.stringify(provenance,null,2));
       cases.push({sport:item.sport,race_id:item.race_id,state:selected.some(r=>r.role==='result')&&selected.some(r=>r.role==='identity')?'CAPTURED':'HOLD_RESULT_SOURCE_UNAVAILABLE',responses:selected,rendered_dom:dom,browser_metadata:provenance});
       if(item.sport==='keirin'&&page!==listPage){await page.close();page=listPage;}
      }catch(error){cases.push({sport:item.sport,race_id:item.race_id,state:'HOLD_UI_OR_SOURCE_UNAVAILABLE',responses:[],reason:/^OFFICIAL_BROWSER_[A-Z_]+$/.test(error.message)?error.message:'UI_OPERATION_REJECTED'});if(budget.reason)break;}
     }
    }catch{for(const item of group)if(!cases.some(c=>c.race_id===item.race_id))cases.push({sport:item.sport,race_id:item.race_id,state:'HOLD_UI_ENTRY_UNAVAILABLE',responses:[]});}
    await page.close().catch(()=>{});
   }
  }
 }catch(error){add({event:'CAPTURE_HOLD',reason:/^OFFICIAL_BROWSER_[A-Z_]+$/.test(error.message)?error.message:'BROWSER_OPERATION_REJECTED',at:stamp()});budget.stop('CAPTURE_HOLD');}
 finally{clearTimeout(deadline);for(const timer of timers.values())clearTimeout(timer);if(context)await context.close().catch(()=>{});await Promise.allSettled([...pending]);if(browser)await browser.close().catch(()=>{});}
 for(const item of plan.cases)if(!cases.some(c=>c.race_id===item.race_id))cases.push({sport:item.sport,race_id:item.race_id,state:time(item.due_at)>Date.now()?'HOLD_NOT_DUE':'HOLD_'+(budget.reason||'NOT_CAPTURED'),responses:[]});
 const index={schema:CAPTURE,started_at:started,completed_at:stamp(),actual_request_count:budget.count,maximum_requests:plan.request_budget||MAX_REQUESTS,minimum_spacing_ms:SPACING_MS,maximum_elapsed_ms:ELAPSED_MS,request_timeout_ms:TIMEOUT_MS,stop_reason:budget.reason||'FINISHED',stopped_host:budget.reason==='HTTP_ACCESS_DENIED',cases,responses,ledger,normal_ui_only:true,manual_api_requests:0,formal_learning_or_pdca_claim:false};savePrivate(root,'capture-index.json',JSON.stringify(index,null,2));return index;
}
async function main(argv=process.argv.slice(2)){
 let result={state:'HOLD',actual_request_count:0,captured_case_count:0,held_case_count:0,stopped_host:false};
 try{need(argv.length===4&&argv[0]==='--plan'&&argv[2]==='--out-dir','CLI_ARGUMENTS');const input=privatePath(argv[1]),info=fs.lstatSync(input);need(info.isFile()&&(info.mode&0o777)===0o600&&info.uid===process.getuid()&&info.size>0&&info.size<=24*1024*1024,'PRIVATE_PLAN');
  const plan=JSON.parse(fs.readFileSync(input,'utf8'));const out=await capturePlan(plan,argv[3]);result={state:out.cases.some(c=>c.state==='CAPTURED')?'CAPTURED':'HOLD',actual_request_count:out.actual_request_count,captured_case_count:out.cases.filter(c=>c.state==='CAPTURED').length,held_case_count:out.cases.filter(c=>c.state!=='CAPTURED').length,stopped_host:out.stopped_host};
 }catch{process.exitCode=1;}process.stdout.write(JSON.stringify(result)+'\n');return result;
}
module.exports={SCHEMA,CAPTURE,MAX_BODY,validatePlan,requireCurrentClock,dueCases,groupCases,requestScope,routePolicy,validateStaticCache,createBudget,makeMetadata,browserMetadata,browserEnvironment,browserProxy,createPrivateOutput,savePrivate,caseResponses,selectAutoCase,selectKeirinCase,openKeirinList,installByteGuard,capturePlan,contentType,sha,main};
if(require.main===module)main();
