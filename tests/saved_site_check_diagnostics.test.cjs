'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),cp=require('node:child_process');
const checker=path.resolve(__dirname,'../scripts/boat_saved_site_check.cjs');
const poisonKey='PUBLIC_PRIVATE_KEY_SENTINEL_43_CHARS_123456789';
const poisonUrl='https://private.invalid/'+poisonKey+'?owner=PRIVATE';
const poisonPath='/private/operator/'+poisonKey+'/context.json';
function context(){return {schema:'RACE_AI_PRIVATE_LIVE_SITE_CHECK_CONTEXT_V1',owner_url:'https://haji84.github.io/RACE-AI/#saved='+'a'.repeat(64)+'.'+'e'.repeat(43),
  day:'2030-04-01',current_day:'2030-04-01',generation:12,day_races:1,minimum_results:0,native_p1_groups:1,native_groups:[['fixture','v1',null,null]],
  native_probe:{race_id:'20300401-01-01',index:0,cutoff_at:'2030-04-01T12:00:00+09:00'},future_native:null,old_day:null,old_completed:0};}
function safeReport(result,{browserErrors=false}={}){
  assert.equal(result.status,2);assert.equal(result.stderr,'');
  for(const privateText of [poisonKey,poisonUrl,poisonPath,'PRIVATE_ACTUAL','PRIVATE_EXPECTED'])assert.equal(result.stdout.includes(privateText),false,'private error properties must never leave the child');
  const report=JSON.parse(result.stdout);assert.equal(report.status,'LIVE_OWNER_SITE_REJECTED');assert.equal(report.reason,'SAVED_SITE_BROWSER_CHECK_FAILED');
  assert.ok(report.diagnostic,'the failure has safe branch diagnostics');
  assert.deepEqual(Object.keys(report).sort(),['diagnostic','reason','status']);
  assert.deepEqual(Object.keys(report.diagnostic).sort(),[...(browserErrors?['browser_errors']:[]),'completed_numeric_scenarios','error_class','error_code','line','numeric_field','phase','script','width']);
  assert.equal(report.diagnostic.script,'boat_saved_site_check.cjs');assert.ok(Number.isSafeInteger(report.diagnostic.line)&&report.diagnostic.line>0);
  return report.diagnostic;
}
function launchFailure({unknown=false,invalidContext=false,corruptStackFormat=false}={}){
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'site-diagnostic-'));
  try{
    const script=path.join(folder,'boat_saved_site_check.cjs');fs.copyFileSync(checker,script);
    fs.writeFileSync(path.join(folder,'boat_saved_simulation_context.cjs'),'module.exports={};\n');
    const modules=path.join(folder,'modules'),playwright=path.join(modules,'playwright');fs.mkdirSync(playwright,{recursive:true});
    fs.writeFileSync(path.join(playwright,'fixture.json'),JSON.stringify({poisonKey,poisonUrl,poisonPath,unknown,corruptStackFormat}));
    fs.writeFileSync(path.join(playwright,'index.js'),`
const fs=require('node:fs'),p=require('./fixture.json'),exists=fs.existsSync;
fs.existsSync=value=>['/usr/bin/google-chrome','/opt/google/chrome/google-chrome','/opt/google/chrome/chrome','/usr/bin/chromium'].includes(value)||exists(value);
if(p.corruptStackFormat)Error.prepareStackTrace=()=>{throw new Error(p.poisonKey+' '+p.poisonUrl);};
exports.chromium={launch:async()=>{
 const error=new Error(p.poisonKey+' '+p.poisonUrl+' '+p.poisonPath);
 error.name=p.unknown?p.poisonKey:'TimeoutError';error.code=p.poisonUrl;
 error.actual='PRIVATE_ACTUAL '+p.poisonKey;error.expected='PRIVATE_EXPECTED '+p.poisonUrl;
 Object.defineProperty(error,'stack',{get(){throw new Error('private stack must not be inspected');}});
 throw error;
}};
`);
    const input=path.join(folder,'context.json');fs.writeFileSync(input,invalidContext?'PRIVATE_EXPECTED '+poisonUrl:JSON.stringify(context()));
    return cp.spawnSync(process.execPath,[script,input],{encoding:'utf8',env:{PATH:process.env.PATH||'/usr/bin:/bin',LANG:'C.UTF-8',TZ:'UTC',NODE_PATH:modules}});
  }finally{fs.rmSync(folder,{recursive:true,force:true});}
}
test('real CLI child reports the browser-launch branch without poisoned messages, values, URLs or stacks',()=>{
  const diagnostic=safeReport(launchFailure());assert.equal(diagnostic.phase,'browser_launch');assert.equal(diagnostic.width,null);
  assert.equal(diagnostic.completed_numeric_scenarios,0);assert.equal(diagnostic.error_class,'TimeoutError');assert.equal(diagnostic.error_code,null);assert.equal(diagnostic.numeric_field,null);
});
test('unknown error names and codes cannot become credential or URL output channels',()=>{
  const diagnostic=safeReport(launchFailure({unknown:true}));assert.equal(diagnostic.error_class,'UNRECOGNIZED_ERROR');assert.equal(diagnostic.error_code,null);
});
test('diagnostic callsite formatting cannot replace the underlying browser failure',()=>{
  const diagnostic=safeReport(launchFailure({corruptStackFormat:true}));assert.equal(diagnostic.phase,'browser_launch');assert.equal(diagnostic.error_class,'TimeoutError');
});
test('invalid context JSON is diagnosed before browser startup without echoing its contents',()=>{
  const diagnostic=safeReport(launchFailure({invalidContext:true}));assert.equal(diagnostic.phase,'context_read');assert.equal(diagnostic.error_class,'SyntaxError');
});
function numericFailure(options={}){
  const program=String.raw`
const fs=require('node:fs'),crypto=require('node:crypto'),C=require(process.argv[1]),p=JSON.parse(fs.readFileSync(0,'utf8'));
if(typeof C.withDiagnostics!=='function'||typeof C.failureReport!=='function'){process.stdout.write(JSON.stringify({status:'LIVE_OWNER_SITE_REJECTED',reason:'SAVED_SITE_BROWSER_CHECK_FAILED'}));process.exit(2);}
const group=JSON.stringify(['research','boat','P1','fixture','v1',null]),digest=crypto.createHash('sha256').update(group).digest('hex');
const counts={hits:0,misses:0,pending:1,void:0,noForecast:0,review:0};
const scenarios=[10000,5000].flatMap(budget=>[800,1000].map(race=>({budgetPerDay:budget,raceBudget:race,budgetTotal:budget,spent:800,reserved:race,held:race-800,unspent:budget-800,payout:0,refund:0,settledStake:0,settledCount:0,pendingStake:800,bought:1,skippedBudget:0,balance:budget-800,settledNet:null,net:null,roi:null,comparison:counts,boughtComparison:counts})));
const context={day:'2030-04-01',generation:12,day_races:1,native_groups:[['fixture','v1',null,null]],numeric_simulation_required:true,simulation_as_of:'2030-04-01T15:00:00+09:00',simulation_expected:{schema:'RACE_AI_SAVED_SITE_SIMULATION_EXPECTED_V1',day:'2030-04-01',generation:12,group_sha256:digest,eligible_native_races:1,issued_races:1,observed:{races:1,available:0,...counts},observed_closed:{races:1,available:0,...counts},lifecycle:{as_of:'2030-04-01T15:00:00+09:00',closed:1,upcoming:0,unknown:0},scenarios,budget_cap_exercised:false,budget_cap_coverage:'INSUFFICIENT_ELIGIBLE_RACES'}};
let daily='10000',race='800',reads=0,controls=0;
const metric=(label,value,detail='')=>({label,value,detail}),yen=n=>n.toLocaleString('ja-JP')+'円';
const page={locator:selector=>({evaluateAll:async()=>[group],selectOption:async value=>{if(selector==='#simulation-race-budget')race=value;},isVisible:async()=>true,fill:async value=>{if(p.controlFailure&&++controls===2)throw new Error(p.poisonKey+' '+p.poisonUrl);daily=value;},dispatchEvent:async()=>{},inputValue:async()=>daily,innerText:async()=> '確定分の収支 確定分の回収率 未確定購入額 全体の収支'}),evaluate:async()=>{
 const reading=++reads;if(p.snapshotFailure&&reading===2)throw new Error(p.poisonKey+' '+p.poisonUrl);
 const s=scenarios.find(s=>s.budgetPerDay===Number(daily)&&s.raceBudget===Number(race));
 return {day:context.day,generation:reading===3?13:12,group_value:group,daily_budget:Number(daily),race_budget:Number(race),coverage:'対象 1レース · 未予想・照合不可 0',
 saved_metrics:[metric('取得結果','0レース'),metric('的中','0レース'),metric('不的中','0レース'),metric('結果待ち','1レース'),metric('中止・返還','0レース'),metric('照合保留','0レース'),metric('保存Top8的中率','算出対象なし','0 / 0レース')],
 simulation_metrics:[metric('予定購入額','800円','1レース · 上限'+yen(s.raceBudget)+'/レース'),metric('未使用予算',yen(s.unspent),'1日 '+yen(s.budgetPerDay)+' × 1日 · 追加未配分 '+yen(s.held)),metric('確認済み払戻','0円','返還 0円'),metric('確定分の収支','未確定','購入額 0円'),metric('未確定購入額','800円'),metric('全体の収支','未確定','仮の残高 '+yen(s.balance)),metric('確定分の回収率','未確定'),metric('収支確定の購入予定','0 / 1レース'),metric('購入予定分の的中率','算出対象なし','0 / 0レース')]};
}};
C.withDiagnostics(async()=>{
 try{await C.checkSimulationMetrics(page,context);}catch(error){error.message=p.poisonKey+' '+p.poisonUrl;error.actual='PRIVATE_ACTUAL '+p.poisonKey;error.expected='PRIVATE_EXPECTED '+p.poisonPath;Object.defineProperty(error,'stack',{get(){throw new Error('private stack must not be inspected');}});throw error;}
}).then(()=>process.stdout.write('unexpected success')).catch(error=>{process.stdout.write(JSON.stringify(C.failureReport(error)));process.exitCode=2;});
`;
  return cp.spawnSync(process.execPath,['-e',program,checker],{input:JSON.stringify({poisonKey,poisonUrl,poisonPath,...options}),encoding:'utf8',env:{PATH:process.env.PATH||'/usr/bin:/bin',LANG:'C.UTF-8',TZ:'UTC'}});
}
test('a real child reports only the numeric mismatch field and completed scenarios, preserving the original rejection',()=>{
  const diagnostic=safeReport(numericFailure());assert.equal(diagnostic.phase,'numeric_snapshot');assert.equal(diagnostic.numeric_field,'generation');
  assert.equal(diagnostic.completed_numeric_scenarios,2);assert.equal(diagnostic.error_class,'AssertionError');assert.equal(diagnostic.error_code,'ERR_ASSERTION');
});
test('second-scenario control failures clear the previous numeric field and retain completed progress',()=>{
  const diagnostic=safeReport(numericFailure({controlFailure:true}));assert.equal(diagnostic.phase,'simulation_controls');assert.equal(diagnostic.numeric_field,null);
  assert.equal(diagnostic.completed_numeric_scenarios,1);assert.equal(diagnostic.error_class,'Error');assert.equal(diagnostic.error_code,null);
});
test('second-scenario snapshot failures report capture rather than the preceding numeric field',()=>{
  const diagnostic=safeReport(numericFailure({snapshotFailure:true}));assert.equal(diagnostic.phase,'numeric_capture');assert.equal(diagnostic.numeric_field,null);
  assert.equal(diagnostic.completed_numeric_scenarios,1);assert.equal(diagnostic.error_class,'Error');assert.equal(diagnostic.error_code,null);
});
function researchFailure({operation=null,browserErrors=false,events=null}={}){
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'site-research-diagnostic-'));
  try{
    const script=path.join(folder,'boat_saved_site_check.cjs');fs.copyFileSync(checker,script);
    fs.writeFileSync(path.join(folder,'boat_saved_simulation_context.cjs'),'module.exports={};\n');
    const modules=path.join(folder,'modules'),playwright=path.join(modules,'playwright');fs.mkdirSync(playwright,{recursive:true});
    fs.writeFileSync(path.join(playwright,'fixture.json'),JSON.stringify({poisonKey,poisonUrl,poisonPath,operation,browserErrors:browserErrors||events!==null,events}));
    fs.writeFileSync(path.join(playwright,'index.js'),String.raw`
const fs=require('node:fs'),vm=require('node:vm'),p=require('./fixture.json'),exists=fs.existsSync;
fs.existsSync=value=>['/usr/bin/google-chrome','/opt/google/chrome/google-chrome','/opt/google/chrome/chrome','/usr/bin/chromium'].includes(value)||exists(value);
let returned=false;const listeners=new Map();
const frame={addEventListener:(name,handler)=>listeners.set(name,handler)};
const fail=name=>{if(p.operation===name){const error=new Error(p.poisonKey+' '+p.poisonUrl);error.actual='PRIVATE_ACTUAL';error.expected='PRIVATE_EXPECTED';Object.defineProperty(error,'stack',{get(){throw new Error(p.poisonPath);}});throw error;}};
function locator(selector){return {
 filter:()=>locator(selector),first:()=>locator(selector),locator:child=>locator(selector+' '+child),
 click:async()=>{if(selector==='[data-page="research"]')fail('nav');if(selector.endsWith('[data-return-to-race]')){fail('return');returned=true;}},
 fill:async()=>{},dispatchEvent:async()=>{},selectOption:async()=>{},
 isVisible:async()=>{if(selector==='#research-race-audit')fail('visible');return selector!=='#all-venues';},
 inputValue:async()=>{if(selector==='#research-race-select'){fail('race');return '20300401-01-01';}if(selector==='#research-prediction-select')fail('model');if(selector==='#prediction-select'&&returned)fail('postmodel');return '0';},
 count:async()=>selector.includes('placeholder-entrants')||selector==='#all-races .race-result-card'||selector==='#race-detail .race-audit-details'?0:selector==='#prediction-select option'?2:1,
 getAttribute:async name=>{if(selector==='#research-race-audit .race-audit-details')fail('sectionmodel');return name==='data-entrants'?'3':name==='data-native-dispatch'?'true':'fixture';},
 allTextContents:async()=>['Fixture Alpha','Fixture Beta','Fixture Gamma'],evaluateAll:async()=>[],
 evaluate:async()=>{fail('section');return 'SECTION';},
 innerText:async()=>{if(selector==='#research-race-audit'){fail('sha');return '予想SHA';}if(selector==='#race-detail .forecast-rationale'){if(returned)fail('rationale');return 'fixture rationale';}if(selector==='#race-detail .forecast-rationale-heading')return '予想根拠';return selector.startsWith('#prediction-select option')?'P1 Fixture':'通常の予想';}
};}
const page={setDefaultTimeout:()=>{},on:()=>{},route:async()=>{},setViewportSize:async()=>{},waitForFunction:async()=>{},locator,
 addInitScript:async(fn,arg)=>vm.runInNewContext('('+fn.toString()+')(__arg)',{globalThis:frame,__arg:arg}),
 goto:async()=>{if(p.browserErrors){if(p.events)for(const entry of p.events){
   const reason={name:entry.name||'TypeError'};for(const key of ['message','stack'])Object.defineProperty(reason,key,{get(){throw new Error(p.poisonKey+' '+p.poisonUrl);}});
   if(entry.throwName)Object.defineProperty(reason,'name',{get(){throw new Error(p.poisonPath);}});
   const kind=entry.kind||'error',event=kind==='unhandledrejection'?{reason}:{error:reason,filename:entry.filename,lineno:entry.line};
   if(entry.throwReason)Object.defineProperty(event,'reason',{get(){throw new Error(p.poisonKey);}});
   if(entry.throwFilename)Object.defineProperty(event,'filename',{get(){throw new Error(p.poisonUrl);}});
   Object.defineProperty(event,'message',{get(){throw new Error(p.poisonPath);}});listeners.get(kind)?.(event);
 }else if(listeners.has('error'))for(let i=0;i<12;i++){
   const error={name:i===1?p.poisonKey:'TypeError'};Object.defineProperty(error,'stack',{get(){throw new Error(p.poisonPath);}});
   if(i===7)Object.defineProperty(error,'name',{get(){throw new Error(p.poisonKey);}});
   const event={error,filename:i===0||i>=3?'https://haji84.github.io/RACE-AI/app.js':i===2?'https://haji84.github.io/RACE-AI/app.js?'+p.poisonKey:p.poisonUrl,lineno:i===0?77:i===3?p.poisonKey:i===4?-1:i===5?1000000:i===6?1.25:123};
   Object.defineProperty(event,'message',{get(){throw new Error(p.poisonKey+' '+p.poisonUrl);}});listeners.get('error')(event);
 }throw new Error(p.poisonKey+' '+p.poisonUrl);}},
 evaluate:async(fn)=>p.browserErrors?vm.runInNewContext('('+fn.toString()+')()',{globalThis:frame}):({ids:Array.from({length:15},(_,i)=>'fixture-'+i),retired:['seller-shadow-v1-20261104']})
};
exports.chromium={launch:async()=>({newPage:async()=>page,close:async()=>{}})};
`);
    const input=path.join(folder,'context.json');fs.writeFileSync(input,JSON.stringify(context()));
    return cp.spawnSync(process.execPath,[script,input,'--compact-results'],{encoding:'utf8',env:{PATH:process.env.PATH||'/usr/bin:/bin',LANG:'C.UTF-8',TZ:'UTC',NODE_PATH:modules}});
  }finally{fs.rmSync(folder,{recursive:true,force:true});}
}
test('research diagnostics pinpoint each failing operation without changing its rejection',()=>{
  const lines=fs.readFileSync(checker,'utf8').split('\n');
  for(const [operation,statement] of [
    ['nav','await page.locator(\'[data-page="research"]\').filter({visible:true}).first().click();'],
    ['visible','assert.equal(await audit.isVisible(),true);'],
    ['race','assert.equal(await page.locator(\'#research-race-select\').inputValue(),expectedRace);'],
    ['model','assert.equal(await page.locator(\'#research-prediction-select\').inputValue(),selected);'],
    ['section',"assert.equal(await audit.locator('.race-audit-details').evaluate(n=>n.tagName),'SECTION');"],
    ['sectionmodel',"assert.equal(await audit.locator('.race-audit-details').getAttribute('data-model-id'),modelId);"],
    ['sha','assert.match(await audit.innerText(),/予想SHA/);'],
    ['return',"await audit.locator('[data-return-to-race]').click();"],
    ['postmodel',"assert.equal(await page.locator('#prediction-select').inputValue(),selected);"],
    ['rationale',"const returnedRationale=returnedRationaleCount?await page.locator('#race-detail .forecast-rationale').innerText():null;"]
  ]){
    const diagnostic=safeReport(researchFailure({operation})),line=lines.findIndex(text=>text.trim()===statement);
    assert.equal(diagnostic.phase,'research_audit',operation);assert.equal(diagnostic.width,320);assert.equal(diagnostic.completed_numeric_scenarios,0);
    assert.ok(line>0,'each operation occupies its own marked line');assert.equal(lines[line-1].trim(),"diagnosticPhase('research_audit');");assert.equal(diagnostic.line,line,operation);
  }
});
test('real CLI ErrorEvent diagnostics are bounded and never expose poisoned message, stack, name or filename',()=>{
  const diagnostic=safeReport(researchFailure({browserErrors:true}),{browserErrors:true});
  assert.equal(diagnostic.phase,'owner_navigation');assert.equal(diagnostic.error_class,'Error');assert.equal(diagnostic.browser_errors.length,8);
  assert.deepEqual(diagnostic.browser_errors[0],{kind:'error',error_class:'TypeError',script:'app.js',line:77});
  assert.deepEqual(diagnostic.browser_errors[1],{kind:'error',error_class:'UNRECOGNIZED_ERROR',script:null,line:null});
  assert.deepEqual(diagnostic.browser_errors[2],{kind:'error',error_class:'TypeError',script:null,line:null});
  for(const event of diagnostic.browser_errors.slice(3,7))assert.deepEqual(event,{kind:'error',error_class:'TypeError',script:'app.js',line:null});
  assert.deepEqual(diagnostic.browser_errors[7],{kind:'error',error_class:'UNRECOGNIZED_ERROR',script:null,line:null});
});
test('versioned public ErrorEvent locations accept exactly one lowercase hex v query',()=>{
  const origin='https://haji84.github.io/RACE-AI/',version='b677fde4cfe6';
  const valid=['app.js?v='+version,'app.js','app.js?v='+'a'.repeat(64),'ui-model.js?v=cb4c6bed3082'];
  const diagnostic=safeReport(researchFailure({events:valid.map(filename=>({filename:origin+filename,line:91}))}),{browserErrors:true});
  assert.equal(diagnostic.browser_errors.length,valid.length);
  assert.equal(diagnostic.browser_errors[0].script,'app.js','the actual deployed version query retains its public location');
  for(let i=0;i<valid.length;i++)assert.deepEqual(diagnostic.browser_errors[i],{kind:'error',error_class:'TypeError',script:valid[i].split('?')[0],line:91});
  const invalid=[
    origin+'app.js?v='+'a'.repeat(11),origin+'app.js?v='+'a'.repeat(65),origin+'app.js?v='+version.toUpperCase(),
    origin+'app.js?version='+version,origin+'app.js?v='+version+'&v='+version,origin+'app.js?v='+version+'&owner='+poisonKey,
    origin+'app.js?v='+version+'#'+poisonKey,origin+'app.js#'+poisonKey,origin+'app.js?v='+version+'\n',
    'https://operator@haji84.github.io/RACE-AI/app.js?v='+version,poisonUrl+'/app.js?v='+version,
    origin+'../RACE-AI/app.js?v='+version,origin+'%61pp.js?v='+version,origin+'private.js?v='+version
  ];
  for(let start=0;start<invalid.length;start+=8){
    const records=safeReport(researchFailure({events:invalid.slice(start,start+8).map(filename=>({filename,line:91}))}),{browserErrors:true}).browser_errors;
    for(const record of records)assert.deepEqual(record,{kind:'error',error_class:'TypeError',script:null,line:null});
  }
});
test('error and unhandled-rejection diagnostics share the eight-record cap without reading poisoned reason properties',()=>{
  const events=[
    {kind:'unhandledrejection'},
    {filename:'https://haji84.github.io/RACE-AI/ui-model.js?v=cb4c6bed3082',line:22},
    {kind:'unhandledrejection',name:poisonKey},{kind:'unhandledrejection',throwName:true},
    {throwFilename:true},{kind:'unhandledrejection',throwReason:true},
    {filename:'https://haji84.github.io/RACE-AI/app.js?v=b677fde4cfe6',line:poisonKey},
    {kind:'unhandledrejection'},{kind:'unhandledrejection'},
    {filename:'https://haji84.github.io/RACE-AI/app.js',line:77}
  ];
  const records=safeReport(researchFailure({events}),{browserErrors:true}).browser_errors;assert.equal(records.length,8);
  assert.deepEqual(records[0],{kind:'unhandledrejection',error_class:'TypeError',script:null,line:null});
  assert.deepEqual(records[1],{kind:'error',error_class:'TypeError',script:'ui-model.js',line:22});
  for(const index of [2,3,5])assert.deepEqual(records[index],{kind:'unhandledrejection',error_class:'UNRECOGNIZED_ERROR',script:null,line:null});
  assert.deepEqual(records[4],{kind:'error',error_class:'UNRECOGNIZED_ERROR',script:null,line:null});
  assert.deepEqual(records[6],{kind:'error',error_class:'TypeError',script:'app.js',line:null});
  assert.deepEqual(records[7],{kind:'unhandledrejection',error_class:'TypeError',script:null,line:null});
});
