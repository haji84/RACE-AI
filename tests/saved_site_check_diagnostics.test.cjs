'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),cp=require('node:child_process');
const checker=path.resolve(__dirname,'../scripts/boat_saved_site_check.cjs');
const poisonKey='PUBLIC_PRIVATE_KEY_SENTINEL_43_CHARS_123456789';
const poisonUrl='https://private.invalid/'+poisonKey+'?owner=PRIVATE';
const poisonPath='/private/operator/'+poisonKey+'/context.json';
function context(){return {schema:'RACE_AI_PRIVATE_LIVE_SITE_CHECK_CONTEXT_V1',owner_url:'https://haji84.github.io/RACE-AI/#saved='+'a'.repeat(64)+'.'+'e'.repeat(43),
  day:'2030-04-01',current_day:'2030-04-01',generation:12,day_races:1,minimum_results:0,native_p1_groups:1,native_groups:[['fixture','v1',null,null]],
  native_probe:{race_id:'20300401-01-01',index:0,cutoff_at:'2030-04-01T12:00:00+09:00'},future_native:null,old_day:null,old_completed:0};}
function safeReport(result){
  assert.equal(result.status,2);assert.equal(result.stderr,'');
  for(const privateText of [poisonKey,poisonUrl,poisonPath,'PRIVATE_ACTUAL','PRIVATE_EXPECTED'])assert.equal(result.stdout.includes(privateText),false,'private error properties must never leave the child');
  const report=JSON.parse(result.stdout);assert.equal(report.status,'LIVE_OWNER_SITE_REJECTED');assert.equal(report.reason,'SAVED_SITE_BROWSER_CHECK_FAILED');
  assert.ok(report.diagnostic,'the failure has safe branch diagnostics');
  assert.deepEqual(Object.keys(report).sort(),['diagnostic','reason','status']);
  assert.deepEqual(Object.keys(report.diagnostic).sort(),['completed_numeric_scenarios','error_class','error_code','line','numeric_field','phase','script','width']);
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
